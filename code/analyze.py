"""Results of the testbed runs: tables and figures for the paper.

Reads one saved session (data/derived.csv, data/events.csv, config.json) and
writes everything into results/. Run it again on the final session and every
number is recomputed; nothing is typed by hand.

    python analyze.py --session path/to/unzipped/session --out results

Corrections to the event log are kept in EPISODE_NOTES below (never in the
raw files): each says what an episode was and why.
"""

import argparse
import csv
import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime

import rules
from derive import load_events

# What each logged window was. Keyed by start time (local, to the second).
# role: official = used for results and survey; repeat = same protocol, counted as a
# repetition; exploration / method = setting up the protocol; excluded = not a fault run.
EPISODE_NOTES = {
    "2026-11-02T16:00:41": ("fiber_bend", "exploration",
                            "marker then pen, unequal steps; logged as 'baseline' by mistake (correction note at 16:3x)"),
    "2026-11-02T17:07:11": ("fiber_bend", "method",
                            "CLI vs SNMP refresh test; bend lasted ~3 min between two DOM updates"),
    "2026-11-02T18:19:04": ("fiber_bend", "official", "run 1: 1 to 5 turns, one turn per 10 min"),
    "2026-11-02T19:29:23": ("fiber_bend", "official", "run 2: 5, 10, 15 turns, 10 min each"),
    "2026-11-02T21:57:11": ("fiber_bend", "official", "run 3: 5, 10, 15 turns, 10 min each"),
    "2026-11-02T23:18:21": ("copper_duplex_mismatch", "repeat", "run 1, about 10 min"),
    "2026-11-03T00:43:09": ("copper_duplex_mismatch", "repeat", "run 2, about 7 min"),
    "2026-11-03T16:57:37": ("copper_duplex_mismatch", "repeat",
                            "run 3, about 7 min; traffic history before it was not steady (iperf catch-up burst), "
                            "so the survey image was taken again in run 4"),
    "2026-11-03T18:41:04": ("copper_duplex_mismatch", "official", "run 4, about 8 min; survey image S2"),
    "2026-11-03T02:23:39": ("copper_bad_cable", "excluded",
                            "on PC1's link, which also carries the monitoring: the monitor lost contact for 1.5 min"),
    "2026-11-03T03:04:58": ("copper_bad_cable", "method", "smoke test of the capture rule on PC2's link"),
    "2026-11-03T15:29:15": ("copper_bad_cable", "official", "BAD cable (brown pair cut) on PC2's link, 10 min"),
    "2026-11-03T21:22:20": ("planned_change", "official",
                            "S4: calibrated chain (6 couplers + 7 patch cords incl. the original) inserted on the "
                            "fiber link, about 18 min; calibrated beforehand with the switch CLI during a hold"),
}
# What was done at the moment a fault window was opened, when the start note does not say it.
START_STEP = {"2026-11-02T18:19:04": "pen 1 turn"}
FAULTS = {"fiber_bend", "fiber_dirty_connector", "fiber_loose_connector", "fiber_unplug", "copper_unplug",
          "copper_bad_cable", "copper_forced_100m", "copper_duplex_mismatch", "copper_emi", "planned_change"}


def _n(v):
    try:
        return None if v in ("", None) else float(v)
    except ValueError:
        return None


def hhmm(t):
    return datetime.fromtimestamp(t).strftime("%H:%M:%S")


def settled(r):
    return r["status"] == "ok" and str(r.get("state_changed")) != "1"


def load(session):
    with open(os.path.join(session, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(session, "data", "derived.csv"), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    windows, points = load_events(os.path.join(session, "data", "events.csv"))
    by = defaultdict(list)
    for r in rows:
        by[(r["target"], str(r["if_index"]))].append(r)
    for v in by.values():
        v.sort(key=lambda r: float(r["ts_unix"]))
    return cfg, by, windows, points


def episodes(windows):
    out = []
    for (t0, t1, ty, tgt, idx, note) in windows:
        key = datetime.fromtimestamp(t0).strftime("%Y-%m-%dT%H:%M:%S")
        fixed = EPISODE_NOTES.get(key)
        kind, role, why = fixed if fixed else (ty, "repeat" if ty in FAULTS else None, "")
        if kind not in FAULTS or role is None:
            continue
        out.append({"start": t0, "end": t1, "type": kind, "target": tgt, "if_index": str(idx),
                    "note": note, "role": role, "role_reason": why})
    return sorted(out, key=lambda e: e["start"])


def evaluate_rows(rows, s):
    base = rules.learn_baseline(rows, s)
    return base, [(r, rules.evaluate(r, base, s)) for r in rows]


def restore_time(ep, points):
    """Copper runs: when the fault was physically undone (the 'restored' note), if it was logged in the window."""
    if not ep["type"].startswith("copper"):
        return None
    rs = [p[0] for p in points if ep["start"] <= p[0] <= ep["end"] + 5 and (p[4] or "").strip().lower().startswith("restored")
          and str(p[3] or "") in ("", ep["if_index"])]
    return min(rs) if rs else None


ACTIVE_COLS = ("settled_readings", "A_fired_settled", "B_fired_settled", "A_fired_any", "speed_mode",
               "half_duplex_readings", "in_errors_max", "out_errors_max", "crc_max", "late_coll_max")


def episode_metrics(ep, evald, t_end=None):
    t0, t1 = ep["start"], (t_end or ep["end"])
    inside = [(r, ev) for r, ev in evald if t0 <= float(r["ts_unix"]) <= t1]
    st = [(r, ev) for r, ev in inside if settled(r)]
    first = lambda pred: next((float(r["ts_unix"]) - t0 for r, ev in st if pred(ev)), None)
    vals = lambda c: [_n(r[c]) for r, _ in st if _n(r[c]) is not None]
    rx = vals("ddm_rx_power")
    speeds = Counter(r["high_speed"] for r, _ in st)
    dup = Counter(r["duplex_status"] for r, _ in st)
    return {
        "readings": len(inside), "settled_readings": len(st),
        "no_reply": sum(r["status"] == "poll_error" for r, _ in inside),
        "A_fired_settled": sum(ev["fixed"]["fired"] for _, ev in st),
        "B_fired_settled": sum(ev["baseline"]["fired"] for _, ev in st),
        "A_fired_any": sum(ev["fixed"]["fired"] for _, ev in inside),
        "A_first_s": first(lambda ev: ev["fixed"]["fired"]),
        "B_first_s": first(lambda ev: ev["baseline"]["fired"]),
        "speed_mode": speeds.most_common(1)[0][0] if speeds else "",
        "half_duplex_readings": dup.get("2", 0),
        "in_errors_max": max(vals("in_errors_d") or [0]), "out_errors_max": max(vals("out_errors_d") or [0]),
        "crc_max": max(vals("fcs_errors_d") or [0]), "late_coll_max": max(vals("late_collisions_d") or [0]),
        "in_mbps_median": round(statistics.median(vals("in_mbps")), 1) if vals("in_mbps") else "",
        "out_mbps_median": round(statistics.median(vals("out_mbps")), 1) if vals("out_mbps") else "",
        "rx_min_dbm": min(rx) if rx else "",
        **link_changes(inside),
    }


def link_changes(inside):
    """Readings where the link changed state, and how long until traffic flowed again after the first one.

    Traffic counts as flowing again at the first answered reading with more than 1 Mb/s in both directions.
    """
    ch = [float(r["ts_unix"]) for r, _ in inside if str(r.get("state_changed")) == "1"]
    back = None
    if ch:
        back = next((float(r["ts_unix"]) - ch[0] for r, _ in inside if float(r["ts_unix"]) > ch[0]
                     and r["status"] == "ok" and (_n(r["in_mbps"]) or 0) > 1 and (_n(r["out_mbps"]) or 0) > 1), None)
    return {"link_change_readings": len(ch), "traffic_back_s_after_first_change": round(back) if back is not None else ""}


def dom_refresh(rows):
    """Seconds between changes of the optical readings (they only change when the switch refreshes them)."""
    prev, ch = None, []
    for r in rows:
        v = (r["ddm_rx_power"], r["ddm_temperature"], r["ddm_bias_current"])
        if r["ddm_rx_power"] == "":
            continue
        if prev is not None and v != prev:
            ch.append(float(r["ts_unix"]))
        prev = v
    gaps = [round(b - a) for a, b in zip(ch, ch[1:])]
    return Counter(int(g // 15 * 15) for g in gaps), len(ch)


def fiber_steps(ep, evald, points, base):
    """Each bend step: the Rx the monitor showed at the end of the step (after a DOM refresh)."""
    marks = sorted([p for p in points if ep["start"] - 1 <= p[0] <= ep["end"] + 1 and p[1] == "note"
                    and ("turn" in (p[4] or "") or "released" in (p[4] or ""))], key=lambda p: p[0])
    key = datetime.fromtimestamp(ep["start"]).strftime("%Y-%m-%dT%H:%M:%S")
    first = START_STEP.get(key) or next((f"pen {w} turns" for w in ep["note"].replace(",", " ").split() if w.isdigit()), "start")
    steps = [(ep["start"], first)] + [(p[0], p[4]) for p in marks]
    out = []
    times = [float(r["ts_unix"]) for r, _ in evald]
    for i, (t, label) in enumerate(steps):
        t_next = steps[i + 1][0] if i + 1 < len(steps) else ep["end"] + 600
        seg = [(r, ev) for r, ev in evald if t <= float(r["ts_unix"]) < t_next and r["ddm_rx_power"] != ""]
        if not seg:
            continue
        last_r, last_ev = seg[-1]
        rx = _n(last_r["ddm_rx_power"])
        b_on = [float(r["ts_unix"]) for r, ev in seg if ev["baseline"]["fired"] and settled(r)]
        already = bool(out) and out[-1]["B_alerting_during_step"]
        out.append({"label": label, "logged_at": hhmm(t), "rx_end_of_step": rx,
                    "drop_db": round(base["rx_mean"] - rx, 2) if rx is not None else "",
                    "A_alerting_during_step": any(ev["fixed"]["fired"] for _, ev in seg),
                    "B_alerting_during_step": bool(b_on),
                    # first crossing only: seconds from the logged step to the first Display B alert
                    "B_first_alert_after_step_s": round(b_on[0] - t) if b_on and not already and "released" not in label else "",
                    # after release: how long B kept alerting on the old (not yet refreshed) reading
                    "B_still_alerting_after_release_s": round(b_on[-1] - t) if b_on and "released" in label else ""})
    return out


def recovery_after_release(ep, evald, points, base, tol=0.3):
    rel = [p for p in points if ep["start"] <= p[0] <= ep["end"] + 5 and "released" in (p[4] or "")]
    if not rel:
        return None
    t = rel[-1][0]
    back = next((float(r["ts_unix"]) for r, ev in evald if float(r["ts_unix"]) >= t
                 and _n(r["ddm_rx_power"]) is not None and abs(_n(r["ddm_rx_power"]) - base["rx_mean"]) <= tol), None)
    return round(back - t) if back else None


def planned_change(ep, evald, base, tol=0.3):
    """The planned-change run (S4): what each display did while a known, intended loss was on the link.

    Insertion and removal are the first and last readings in the window where the link changed state.
    """
    t0, t1 = ep["start"], ep["end"]
    allr = [(float(r["ts_unix"]), r, ev) for r, ev in evald]
    inside = [x for x in allr if t0 <= x[0] <= t1]
    ch = [t for t, r, _ in inside if str(r.get("state_changed")) == "1"]
    if not ch:
        return None
    t_in = ch[0]
    t_out = ch[-1] if len(ch) > 1 else None
    at = lambda t: next((r, ev) for tt, r, ev in allr if tt == t)
    rx_in = _n(at(t_in)[0]["ddm_rx_power"])
    # first reading after insertion that shows a different optical value (the switch refreshed it)
    seen = next((t for t, r, _ in inside if t > t_in and _n(r["ddm_rx_power"]) is not None
                 and _n(r["ddm_rx_power"]) != rx_in), None)
    upto = t_out or t1
    loaded = [(t, r, ev) for t, r, ev in inside if seen and seen <= t < upto and settled(r)]
    rx_vals = []
    for _, r, _ in loaded:
        v = _n(r["ddm_rx_power"])
        if v is not None and v not in rx_vals:
            rx_vals.append(v)
    b_on = [t for t, r, ev in allr if t >= (seen or t0) and ev["baseline"]["fired"] and settled(r)]
    after_end = [t for t in b_on if t > t1]
    back = None
    if t_out:
        back = next((t for t, r, _ in allr if t > t_out and _n(r["ddm_rx_power"]) is not None
                     and abs(_n(r["ddm_rx_power"]) - base["rx_mean"]) <= tol), None)
    r_in, ev_in = at(t_in)
    r_out, ev_out = at(t_out) if t_out else (None, None)
    return {
        "inserted_at": hhmm(t_in), "removed_at": hhmm(t_out) if t_out else "",
        "minutes_inserted": round((t_out - t_in) / 60, 1) if t_out else "",
        "first_reading_showing_loss_s_after_insertion": round(seen - t_in) if seen else "",
        "rx_values_reported_dbm": " ".join(f"{v:g}" for v in rx_vals),
        "drop_db_reported": " ".join(f"{base['rx_mean'] - v:.2f}" for v in rx_vals),
        "settled_readings_with_loss_visible": len(loaded),
        "B_alerted_on": sum(ev["baseline"]["fired"] for _, _, ev in loaded),
        "A_alerted_on": sum(ev["fixed"]["fired"] for _, _, ev in loaded),
        "B_first_alert_s_after_insertion": round(b_on[0] - t_in) if b_on else "",
        # readings at the plug / unplug moments: B reports the link-state change itself
        "link_change_readings_at_insertion": sum(1 for t in ch if t < (seen or upto)),
        "B_alerts_on_link_change_at_insertion": sum(1 for t, r, ev in inside if t < (seen or upto) and ev["baseline"]["fired"]),
        "in_errors_at_insertion": _n(r_in["in_errors_d"]), "A_at_insertion": ev_in["fixed"]["fired"],
        "in_errors_at_removal": _n(r_out["in_errors_d"]) if r_out else "",
        "A_at_removal": ev_out["fixed"]["fired"] if ev_out else "",
        "B_still_alerting_s_after_window_end": round(after_end[-1] - t1) if after_end else 0,
        "monitor_shows_normal_s_after_removal": round(back - t_out) if back and t_out else "",
    }


def survey_images(session):
    """The survey screens chosen by the capture rule (one JSON per image, written by snapshot.py)."""
    folder = os.path.join(session, "captures", "survey")
    out = []
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            j = json.load(f)
        v = j.get("values", {})
        out.append({"screen": j.get("screen"), "scenario": j.get("scenario"), "display": j.get("variant"),
                    "fault_type": j.get("fault_type"), "target": j.get("target"), "if_index": j.get("if_index"),
                    "reading_time": (j.get("reading_time") or "")[:19].replace("T", " "),
                    "s_after_fault_start": j.get("seconds_after_fault_start"),
                    "history_clean": j.get("history_clean"),
                    "A_fired": j.get("alert_fixed", {}).get("fired"), "B_fired": j.get("alert_baseline", {}).get("fired"),
                    "shown_alert": " · ".join((j.get("alert_baseline" if j.get("variant") == "B" else "alert_fixed")
                                               or {}).get("reasons") or []) or "no active alerts",
                    "speed": v.get("high_speed"), "duplex": {"2": "half", "3": "full"}.get(str(v.get("duplex_status")), ""),
                    "rx_dbm": v.get("ddm_rx_power", ""), "in_mbps": v.get("in_mbps"), "out_mbps": v.get("out_mbps"),
                    "in_errors": v.get("in_errors_d"), "out_errors": v.get("out_errors_d", ""),
                    "crc": v.get("fcs_errors_d"), "late_collisions": v.get("late_collisions_d")})
    return sorted(out, key=lambda x: x["screen"] or 0)


def holds(windows, points):
    """Hold windows (left out of the analysis) with the notes logged around them."""
    out = []
    for (t0, t1, ty, tgt, idx, note) in windows:
        if ty != "hold":
            continue
        notes = [p[4] for p in points if t0 - 120 <= p[0] <= t1 + 60 and p[4]]
        out.append({"start": datetime.fromtimestamp(t0).strftime("%Y-%m-%d %H:%M:%S"),
                    "end": datetime.fromtimestamp(t1).strftime("%Y-%m-%d %H:%M:%S"),
                    "minutes": round((t1 - t0) / 60, 1), "notes": " | ".join(n.strip() for n in notes)})
    return out


def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def figures(out, cfg, by, eps, evald_by, steps_by_run):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})

    # Rx drop by number of turns, official fiber runs
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    for run, steps in steps_by_run.items():
        pts = []
        for s in steps:
            lab = s["label"]
            num = next((int(w) for w in lab.split() if w.isdigit()), None)
            if num is not None and s["drop_db"] != "":
                pts.append((num, s["drop_db"]))
        if pts:
            pts.sort()
            ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", lw=1.5, label=run)
    base_cfg = rules.settings(cfg)
    ax.axhline(base_cfg["baseline"]["rx_drop_db"], color="#d08a00", ls="--", lw=1)
    ax.text(0.5, base_cfg["baseline"]["rx_drop_db"] + 0.15, "Display B threshold (2 dB below normal)", fontsize=7.5,
            color="#9a6500")
    # Display A's fixed optical limit, expressed as dB below the fiber link's normal
    fb = next((rules.learn_baseline(rows, base_cfg) for (t, i), rows in by.items()
               if any(r.get("ddm_rx_power") not in ("", None) for r in rows)), None) if hasattr(rules, "learn_baseline") else None
    rx_norm = (fb or {}).get("rx_mean")
    if rx_norm is not None:
        lim = rx_norm - base_cfg["fixed"]["rx_power_min_dbm"]
        ax.axhline(lim, color="#b03030", ls=":", lw=1)
        ax.text(0.5, lim + 0.15, f"Display A limit (-14 dBm, {lim:.1f} dB below normal)", fontsize=7.5, color="#8a2020")
        ax.set_ylim(0, lim + 0.8)
    ax.set_xlabel("turns on a ballpoint pen (about 9 mm)")
    ax.set_ylabel("Rx below the link's normal (dB)")
    ax.set_title("Optical loss reported by the switch, by bend step", loc="left", fontsize=9.5)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_fiber_steps.png"), dpi=200)
    plt.close(fig)

    # one timeline per official / repeat episode
    for ep in eps:
        if ep["role"] not in ("official", "repeat"):
            continue
        key = (ep["target"], ep["if_index"])
        ev = evald_by.get(key)
        if not ev:
            continue
        lo, hi = ep["start"] - 900, ep["end"] + 900
        seg = [(r, e) for r, e in ev if lo <= float(r["ts_unix"]) <= hi]
        ts = [(float(r["ts_unix"]) - ep["start"]) / 60 for r, _ in seg]
        fiber = any(r["ddm_rx_power"] != "" for r, _ in seg)
        n = 3 if fiber else 4
        fig, axes = plt.subplots(n, 1, figsize=(6.4, 5.0 if fiber else 6.4), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 2, 0.8] if fiber else [1.6, 1.6, 1.8, 0.8]})
        if fiber:
            axes[0].plot(ts, [_n(r["ddm_rx_power"]) for r, _ in seg], color="#2a78d6", lw=1.5)
            axes[0].set_ylabel("Rx (dBm)")
        else:
            axes[0].plot(ts, [_n(r["high_speed"]) for r, _ in seg], color="#2a78d6", lw=1.5, label="speed")
            axes[0].set_ylabel("Speed (Mb/s)")
        axes[1].plot(ts, [_n(r["in_mbps"]) if r["status"] == "ok" else None for r, _ in seg], lw=1.2, label="in")
        axes[1].plot(ts, [_n(r["out_mbps"]) if r["status"] == "ok" else None for r, _ in seg], lw=1.2, label="out")
        axes[1].set_ylabel("Traffic (Mb/s)")
        axes[1].legend(frameon=False, fontsize=7.5, ncol=2)
        if not fiber:
            for c, lab in (("in_errors_d", "in errors"), ("out_errors_d", "out errors"),
                           ("fcs_errors_d", "CRC"), ("late_collisions_d", "late collisions")):
                axes[2].plot(ts, [_n(r[c]) if r["status"] == "ok" else None for r, _ in seg], lw=1.1, label=lab)
            axes[2].set_yscale("symlog", linthresh=1)
            axes[2].set_ylabel("Errors per reading")
            axes[2].set_ylim(-0.5, 1e8)
            axes[2].legend(frameon=False, fontsize=7, ncol=4, loc="upper left")
        al = axes[-1]
        for i, (lab, getter, col) in enumerate((("A", lambda e: e["fixed"]["fired"], "#d03b3b"),
                                                 ("B", lambda e: e["baseline"]["fired"], "#d08a00"))):
            xs = [t for t, (r, e) in zip(ts, seg) if getter(e)]
            al.scatter(xs, [i] * len(xs), s=6, color=col)
        al.set_yticks([0, 1])
        al.set_yticklabels(["Display A alert", "Display B alert"])
        al.set_ylim(-0.6, 1.6)
        for a in axes:
            a.axvspan(0, (ep["end"] - ep["start"]) / 60, color="#888", alpha=0.10)
        al.set_xlabel("minutes from window start (shaded: fault or planned change logged)")
        names = {"fiber_bend": "Fiber bend", "planned_change": "Planned change on the fiber link",
                 "copper_duplex_mismatch": "Duplex mismatch", "copper_bad_cable": "Damaged copper cable"}
        side = ("Cisco end of the fiber" if fiber else
                "Cisco port to PC 1" if ep["target"] == "CISCO" else "TP-Link port to PC 2")
        axes[0].set_title(f"{names.get(ep['type'], ep['type'])} · {side} · {datetime.fromtimestamp(ep['start']):%d %b %H:%M}",
                          loc="left", fontsize=9.5)
        fig.tight_layout()
        name = f"fig_{ep['type']}_{datetime.fromtimestamp(ep['start']):%m%d_%H%M}.png"
        fig.savefig(os.path.join(out, name), dpi=200)
        plt.close(fig)


def main():
    p = argparse.ArgumentParser(description="Tables and figures from a saved lab session")
    p.add_argument("--session", default=".", help="folder that holds config.json and data/")
    p.add_argument("--out", default="results")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cfg, by, windows, points = load(a.session)
    s = rules.settings(cfg)
    eps = episodes(windows)

    evald_by, bases = {}, {}
    for key, rows in by.items():
        bases[key], evald_by[key] = evaluate_rows(rows, s)

    # episodes table
    table = []
    for ep in eps:
        key = (ep["target"], ep["if_index"])
        m = episode_metrics(ep, evald_by.get(key, [])) if key in evald_by else {}
        # copper: the same counts limited to the time the fault was physically in place (start to 'restored' note)
        t_res = restore_time(ep, points)
        act = episode_metrics(ep, evald_by[key], t_res) if (t_res and key in evald_by) else {}
        m.update({"fault_in_place_min": round((t_res - ep["start"]) / 60, 1) if t_res else ""})
        m.update({"active_" + c: act.get(c, "") for c in ACTIVE_COLS})
        table.append({"start": datetime.fromtimestamp(ep["start"]).strftime("%Y-%m-%d %H:%M:%S"),
                      "minutes": round((ep["end"] - ep["start"]) / 60, 1), "type": ep["type"],
                      "target": ep["target"], "if_index": ep["if_index"], "role": ep["role"],
                      "role_reason": ep["role_reason"], "note": ep["note"], **m})
    write_csv(os.path.join(a.out, "episodes.csv"), table)

    # baseline (normal) per port
    bl = [{"target": k[0], "if_index": k[1], **{x: (round(v, 2) if isinstance(v, float) else v)
                                                 for x, v in (bases[k] or {}).items() if x not in ("from_ts", "to_ts")}}
          for k in sorted(bases)]
    write_csv(os.path.join(a.out, "baseline.csv"), bl)

    # DOM refresh
    fib = [k for k in by if any(r["ddm_rx_power"] != "" for r in by[k])]
    dom = []
    for k in fib:
        hist, n = dom_refresh(by[k])
        for gap, cnt in sorted(hist.items()):
            dom.append({"target": k[0], "if_index": k[1], "seconds_between_updates": gap, "count": cnt})
    write_csv(os.path.join(a.out, "dom_refresh.csv"), dom)

    # fiber steps and recovery
    steps_all, steps_by_run, recov = [], {}, []
    for ep in eps:
        if not ep["type"].startswith("fiber") or ep["role"] != "official":
            continue
        key = (ep["target"], ep["if_index"])
        st = fiber_steps(ep, evald_by[key], points, bases[key])
        run = ep["role_reason"].split(":")[0]
        steps_by_run[run] = st
        for x in st:
            steps_all.append({"run": run, **x})
        recov.append({"run": run, "seconds_until_monitor_shows_normal_after_release":
                      recovery_after_release(ep, evald_by[key], points, bases[key])})
    write_csv(os.path.join(a.out, "fiber_steps.csv"), steps_all)
    write_csv(os.path.join(a.out, "fiber_recovery.csv"), recov)

    pcs = []
    for ep in eps:
        if ep["type"] != "planned_change":
            continue
        key = (ep["target"], ep["if_index"])
        m = planned_change(ep, evald_by[key], bases[key])
        if m:
            pcs.append({"start": datetime.fromtimestamp(ep["start"]).strftime("%Y-%m-%d %H:%M:%S"),
                        "role": ep["role"], **m})
    write_csv(os.path.join(a.out, "planned_change.csv"), pcs)
    survey = survey_images(a.session)
    write_csv(os.path.join(a.out, "survey_images.csv"), survey)
    hl = holds(windows, points)
    write_csv(os.path.join(a.out, "holds.csv"), hl)

    figures(a.out, cfg, by, eps, evald_by, steps_by_run)

    # short summary
    lines = ["# Testbed results (generated by analyze.py)", ""]
    for k in fib:
        hist, n = dom_refresh(by[k])
        tot = sum(hist.values())
        top, cnt = hist.most_common(1)[0] if hist else (None, 0)
        lines.append(f"- Optical readings on {k[0]} {k[1]} changed {n} times; the most common gap between changes was "
                     f"{top} s ({cnt} of {tot} gaps).")
    for row in table:
        if row["role"] in ("official", "repeat") and row.get("fault_in_place_min") != "":
            lines.append(f"- {row['start']} {row['type']} on {row['target']} {row['if_index']} ({row['role']}), while the fault "
                         f"was in place ({row['fault_in_place_min']} min): settled readings {row['active_settled_readings']}, "
                         f"Display A fired on {row['active_A_fired_settled']} (any reading: {row['active_A_fired_any']}), "
                         f"Display B on {row['active_B_fired_settled']}; speed {row['active_speed_mode']}, half-duplex readings "
                         f"{row['active_half_duplex_readings']}, max in errors {row['active_in_errors_max']}, max out errors "
                         f"{row['active_out_errors_max']}, max CRC {row['active_crc_max']}, max late collisions {row['active_late_coll_max']}; "
                         f"traffic flowing again {row.get('traffic_back_s_after_first_change')} s after the first link change.")
        elif row["role"] in ("official", "repeat"):
            lines.append(f"- {row['start']} {row['type']} on {row['target']} {row['if_index']} ({row['role']}, "
                         f"{row['minutes']} min): settled readings {row.get('settled_readings')}, Display A fired on "
                         f"{row.get('A_fired_settled')}, Display B on {row.get('B_fired_settled')}; speed {row.get('speed_mode')}, "
                         f"max out errors/reading {row.get('out_errors_max')}, max late collisions {row.get('late_coll_max')}, "
                         f"min Rx {row.get('rx_min_dbm')}.")
    for x in steps_all:
        lines.append(f"- {x['run']} · {x['label']}: Rx {x['rx_end_of_step']} dBm ({x['drop_db']} dB below normal); "
                     f"A {'alerting' if x['A_alerting_during_step'] else 'silent'}, B {'alerting' if x['B_alerting_during_step'] else 'silent'}"
                     + (f"; first B alert {x['B_first_alert_after_step_s']} s after the step" if x['B_first_alert_after_step_s'] != "" else "")
                     + (f"; B kept alerting for {x['B_still_alerting_after_release_s']} s after release (reading not yet refreshed)"
                        if x['B_still_alerting_after_release_s'] != "" else "") + ".")
    for x in recov:
        lines.append(f"- {x['run']}: after release, the monitor showed normal Rx again after "
                     f"{x['seconds_until_monitor_shows_normal_after_release']} s.")
    for x in pcs:
        lines.append(f"- Planned change {x['start']}: chain in from {x['inserted_at']} to {x['removed_at']} "
                     f"({x['minutes_inserted']} min); the switch first showed the loss {x['first_reading_showing_loss_s_after_insertion']} s "
                     f"after insertion (Rx {x['rx_values_reported_dbm']} dBm, {x['drop_db_reported']} dB below normal). "
                     f"Display B alerted on {x['B_alerted_on']} of {x['settled_readings_with_loss_visible']} settled readings, "
                     f"Display A on {x['A_alerted_on']}. While the chain was being plugged in, B reported the link-state change on "
                     f"{x['B_alerts_on_link_change_at_insertion']} reading(s). In-errors {x['in_errors_at_insertion']:g} at insertion "
                     f"(A {'alerted' if x['A_at_insertion'] else 'silent'}) and {x['in_errors_at_removal']:g} at removal "
                     f"(A {'alerted' if x['A_at_removal'] else 'silent'}). B kept alerting {x['B_still_alerting_s_after_window_end']} s "
                     f"after the window was closed; the monitor showed normal Rx {x['monitor_shows_normal_s_after_removal']} s after removal.")
    for x in survey:
        lines.append(f"- Survey screen {x['screen']} ({x['scenario']}-{x['display']}): reading {x['reading_time']}, "
                     f"{x['s_after_fault_start']} s after the window opened; shows \"{x['shown_alert']}\"; "
                     f"A fired {x['A_fired']}, B fired {x['B_fired']}; history clean {x['history_clean']}.")
    for x in hl:
        lines.append(f"- Hold {x['start']} to {x['end']} ({x['minutes']} min): {x['notes'] or 'no note'}.")
    with open(os.path.join(a.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nWritten to {a.out}/")


if __name__ == "__main__":
    main()
