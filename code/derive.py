"""Turns raw cumulative readings (collector.py) into per-interval values,
and labels every interval with the ground-truth events active at that time.

Handles: 32-bit counter wrap, agent restarts (counters reset), failed polls,
choosing 64-bit counters when the agent has them, DDM text -> numbers.

    python derive.py data/raw.csv --events data/events.csv --out data/derived.csv
"""

import argparse
import csv
import os
import re
from collections import defaultdict

from oids import COUNTER_BITS

NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")

OUT_COLUMNS = [
    "ts_local", "ts_unix", "target", "if_index", "label", "interval_s", "status",
    "oper_status", "high_speed", "duplex_status", "state_changed", "speed_changed",
    "counter_source", "wrapped",
    "in_mbps", "out_mbps", "in_pps", "out_pps",
    "in_errors_d", "out_errors_d", "fcs_errors_d", "alignment_errors_d",
    "late_collisions_d", "in_discards_d", "out_discards_d", "in_error_ratio",
    "ddm_temperature", "ddm_voltage", "ddm_bias_current", "ddm_tx_power", "ddm_rx_power",
    "ddm_loss_signal",
    "event_active", "event_point", "excluded",
]


def num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    m = NUM.search(str(v))
    return float(m.group()) if m else None


def intval(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def counter_delta(prev, cur, bits):
    """Delta of a cumulative counter. Returns (delta or None, wrapped?)."""
    if prev is None or cur is None:
        return None, False
    d = cur - prev
    if d >= 0:
        return d, False
    if bits == 32 and prev > 2**31:          # plausible wrap
        return d + 2**32, True
    return None, False                       # reset or garbage


def load_events(path):
    if not path or not os.path.exists(path):
        return [], []
    with open(path, newline="", encoding="utf-8") as f:
        evs = sorted(csv.DictReader(f), key=lambda e: float(e["ts_unix"]))
    windows, points, open_ = [], [], {}
    for e in evs:
        key = (e["type"], e["target"], e["if_index"])
        t = float(e["ts_unix"])
        if e["phase"] == "start":
            open_[key] = (t, e.get("note", ""))
        elif e["phase"] == "end" and key in open_:
            t0, note = open_.pop(key)
            windows.append((t0, t, *key, note))
        elif e["phase"] == "point":
            points.append((t, *key, e.get("note", "")))
    for key, (t0, note) in open_.items():  # started, never ended
        windows.append((t0, float("inf"), *key, note))
    return windows, points


def in_scope(ev_target, ev_if, row):
    return (not ev_target or ev_target == row["target"]) and (not ev_if or str(ev_if) == str(row["if_index"]))


def derive(raw_path, events_path):
    with open(raw_path, newline="", encoding="utf-8") as f:
        raw = list(csv.DictReader(f))
    groups = defaultdict(list)
    for r in raw:
        groups[(r["target"], r["if_index"])].append(r)

    windows, points = load_events(events_path)
    holds = [(a, b, et, ei) for (a, b, ty, et, ei, _n) in windows if ty == "hold"]
    out = []
    for key, rows in groups.items():
        rows.sort(key=lambda r: float(r["ts_unix"]))
        prev = None  # last successful row
        for r in rows:
            o = {c: "" for c in OUT_COLUMNS}
            o.update(ts_local=r["ts_local"], ts_unix=r["ts_unix"], target=r["target"],
                     if_index=r["if_index"], label=r["label"],
                     oper_status=r["oper_status"], high_speed=r["high_speed"],
                     duplex_status=r["duplex_status"])
            for c in ("ddm_temperature", "ddm_voltage", "ddm_bias_current", "ddm_tx_power", "ddm_rx_power"):
                v = num(r.get(c))
                o[c] = "" if v is None else v
            o["ddm_loss_signal"] = r.get("ddm_loss_signal", "")

            if r["status"] != "ok":
                o["status"] = "poll_error"
                out.append(o)
                continue
            if prev is None:
                o["status"] = "first"
                out.append(o)
                prev = r
                continue

            dt = float(r["ts_unix"]) - float(prev["ts_unix"])
            o["interval_s"] = round(dt, 3)
            up0, up1 = intval(prev["sys_uptime"]), intval(r["sys_uptime"])
            o["state_changed"] = int(r["last_change"] != prev["last_change"] or r["oper_status"] != prev["oper_status"])
            o["speed_changed"] = int(r["high_speed"] != prev["high_speed"])
            if up0 is not None and up1 is not None and up1 < up0:
                o["status"] = "agent_restart"     # counters were reset; no deltas this interval
                out.append(o)
                prev = r
                continue
            o["status"] = "ok"

            use_hc = all(intval(x[c]) is not None for x in (prev, r) for c in ("in_octets_hc", "in_ucast_hc"))
            o["counter_source"] = "hc64" if use_hc else "if32"
            sfx = "_hc" if use_hc else ""
            wrapped, d = [], {}
            for base in ("in_octets", "out_octets", "in_ucast", "out_ucast"):
                col = base + sfx
                d[base], w = counter_delta(intval(prev[col]), intval(r[col]), COUNTER_BITS[col])
                if w:
                    wrapped.append(col)
            for col in ("in_errors", "out_errors", "fcs_errors", "alignment_errors",
                        "late_collisions", "in_discards", "out_discards"):
                d[col], w = counter_delta(intval(prev[col]), intval(r[col]), COUNTER_BITS[col])
                if w:
                    wrapped.append(col)
            o["wrapped"] = ";".join(wrapped)

            def rate(v, scale):
                return "" if v is None or dt <= 0 else round(v * scale / dt, 3)
            o["in_mbps"] = rate(d["in_octets"], 8 / 1e6)
            o["out_mbps"] = rate(d["out_octets"], 8 / 1e6)
            o["in_pps"] = rate(d["in_ucast"], 1)
            o["out_pps"] = rate(d["out_ucast"], 1)
            for col in ("in_errors", "out_errors", "fcs_errors", "alignment_errors",
                        "late_collisions", "in_discards", "out_discards"):
                o[col + "_d"] = "" if d[col] is None else d[col]
            speed = num(r["high_speed"])
            if speed and any(o[c] != "" and o[c] > 1.05 * speed for c in ("in_mbps", "out_mbps")):
                o["status"] = "implausible"       # faster than the link: bad counter pair, don't trust
                for c in ("in_mbps", "out_mbps", "in_pps", "out_pps"):
                    o[c] = ""
            if d["in_errors"] is not None and d["in_ucast"] is not None and (d["in_errors"] + d["in_ucast"]) > 0:
                o["in_error_ratio"] = d["in_errors"] / (d["in_errors"] + d["in_ucast"])

            t = float(r["ts_unix"])
            t_prev = float(prev["ts_unix"])
            active = [f"{ty}" for (a, b, ty, et, ei, _n) in windows
                      if a <= t and b >= t_prev and in_scope(et, ei, r)]
            pts = [ty for (pt, ty, et, ei, _n) in points if t_prev < pt <= t and in_scope(et, ei, r)]
            o["event_active"] = "+".join(sorted(set(active)))
            o["event_point"] = "+".join(pts)
            out.append(o)
            prev = r

    for o in out:  # hold windows: kept in the data, left out of the analysis
        t = float(o["ts_unix"])
        o["excluded"] = int(any(a <= t <= b and in_scope(et, ei, o) for (a, b, et, ei) in holds))
    out.sort(key=lambda o: (float(o["ts_unix"]), o["target"], int(o["if_index"])))
    return out


def summarize(rows):
    by = defaultdict(list)
    for r in rows:
        by[(r["target"], r["if_index"], r["label"])].append(r)
    print(f"\n{'target':<10} {'ifIdx':>5} {'label':<14} {'rows':>5} {'ok':>5} {'err':>4} {'rst':>4} "
          f"{'avg in Mb/s':>11} {'inErr':>7} {'FCS':>7} {'Rx dBm min':>10}")
    for (t, i, lab), rs in sorted(by.items()):
        ok = [r for r in rs if r["status"] == "ok"]
        mbps = [r["in_mbps"] for r in ok if r["in_mbps"] != ""]
        inerr = sum(r["in_errors_d"] for r in ok if r["in_errors_d"] != "")
        fcs = sum(r["fcs_errors_d"] for r in ok if r["fcs_errors_d"] != "")
        rx = [r["ddm_rx_power"] for r in rs if r["ddm_rx_power"] != ""]
        print(f"{t:<10} {i:>5} {lab[:14]:<14} {len(rs):>5} {len(ok):>5} "
              f"{sum(r['status'] == 'poll_error' for r in rs):>4} {sum(r['status'] == 'agent_restart' for r in rs):>4} "
              f"{(sum(mbps) / len(mbps)) if mbps else 0:>11.1f} {inerr:>7} {fcs:>7} "
              f"{(min(rx) if rx else ''):>10}")


def main():
    p = argparse.ArgumentParser(description="Raw SNMP readings -> per-interval rates + event labels")
    p.add_argument("raw", nargs="?", default="data/raw.csv")
    p.add_argument("--events", default="data/events.csv")
    p.add_argument("--out", default="data/derived.csv")
    a = p.parse_args()
    rows = derive(a.raw, a.events)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {a.out}")
    summarize(rows)


if __name__ == "__main__":
    main()
