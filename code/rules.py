"""Alerting rules, used by the dashboard (problem list) and by the survey
screenshots (Display A vs Display B).

Two ways to turn a reading into an alert:

  fixed     what common monitoring tools do: one fixed limit per metric,
            the same for every link (Display A)
  baseline  judge the link against its own normal behaviour, learned from
            fault-free data, and say which signals are off (Display B)

All limits live in config.json under "alerting"; the defaults are below.
"""

import statistics
from collections import Counter

DEFAULTS = {
    "window_minutes": 15,          # dashboard: a port is a problem if anything fired in this window
    "fixed": {
        "rx_power_min_dbm": -14.0,  # typical vendor low-Rx alarm for LR optics
        "errors_per_interval": 10,
        "crc_per_interval": 10,
    },
    "baseline": {
        "learn_minutes": 60,        # how much fault-free data defines "normal"
        "rx_drop_db": 2.0,
        "min_rows": 4,              # fewer fault-free rows than this -> no baseline yet
    },
}


def settings(cfg):
    a = (cfg or {}).get("alerting", {})
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in a.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def _n(v):
    return None if v in ("", None) else float(v)


def is_clean(r):
    """Row usable for learning 'normal': answered, not in a hold, no fault active."""
    active = [x for x in (r.get("event_active") or "").split("+") if x]
    return (r["status"] == "ok" and not int(r.get("excluded") or 0)
            and all(a == "baseline" for a in active))


def learn_baseline(rows, s):
    """Normal behaviour of one interface from its fault-free rows.
    Rows inside a logged 'baseline' window are preferred when there are any."""
    clean = [r for r in rows if is_clean(r)]
    marked = [r for r in clean if "baseline" in (r.get("event_active") or "")]
    use = marked if len(marked) >= s["baseline"]["min_rows"] else clean
    if not use:
        return None
    t0 = float(use[0]["ts_unix"])
    use = [r for r in use if float(r["ts_unix"]) - t0 <= s["baseline"]["learn_minutes"] * 60]
    if len(use) < s["baseline"]["min_rows"]:
        return None
    rx = [_n(r["ddm_rx_power"]) for r in use if _n(r["ddm_rx_power"]) is not None]
    speeds = Counter(r["high_speed"] for r in use if r["high_speed"] not in ("", None))

    def peak(c):
        vals = [_n(r[c]) for r in use if _n(r[c]) is not None]
        return max(vals) if vals else None
    return {
        "rows": len(use), "from_ts": float(use[0]["ts_unix"]), "to_ts": float(use[-1]["ts_unix"]),
        "rx_mean": statistics.fmean(rx) if rx else None,
        "rx_min": min(rx) if rx else None, "rx_max": max(rx) if rx else None,
        "speed": _n(speeds.most_common(1)[0][0]) if speeds else None,
        "errors_max": peak("in_errors_d"), "crc_max": peak("fcs_errors_d"),
        "late_max": peak("late_collisions_d"),
    }


def evaluate(r, base, s):
    """Evaluate one derived row. Returns {"fixed": {...}, "baseline": {...}, "reachable": bool}."""
    f = s["fixed"]
    res = {"reachable": r["status"] != "poll_error",
           "fixed": {"fired": False, "rule": "", "reasons": []},
           "baseline": {"fired": False, "headline": "", "reasons": []}}
    if not res["reachable"]:
        msg = "Not answering (link down, device off or path cut)"
        res["fixed"].update(fired=True, rule="Device does not answer SNMP", reasons=[msg])
        res["baseline"].update(fired=True, headline=msg, reasons=[msg])
        return res

    rx, inerr, crc = _n(r["ddm_rx_power"]), _n(r["in_errors_d"]), _n(r["fcs_errors_d"])
    late, speed = _n(r["late_collisions_d"]), _n(r["high_speed"])
    oper = str(r["oper_status"])

    # ---- fixed limits (Display A) ----
    fx = []
    if oper == "2":
        fx.append(("Link down", "Rule: alert when the link is down"))
    if rx is not None and rx < f["rx_power_min_dbm"]:
        fx.append((f"Rx power {rx:.1f} dBm below {f['rx_power_min_dbm']:g} dBm",
                   f"Rule: alert when Rx power is below {f['rx_power_min_dbm']:g} dBm"))
    if inerr is not None and inerr >= f["errors_per_interval"]:
        fx.append((f"{inerr:.0f} input errors in one interval",
                   f"Rule: alert at {f['errors_per_interval']} or more input errors per interval"))
    if crc is not None and crc >= f["crc_per_interval"]:
        fx.append((f"{crc:.0f} CRC errors in one interval",
                   f"Rule: alert at {f['crc_per_interval']} or more CRC errors per interval"))
    if fx:
        res["fixed"].update(fired=True, rule=fx[0][1], reasons=[a for a, _ in fx])
    else:
        rules = ["link down"]
        if r.get("ddm_rx_power") not in ("", None):
            rules.append(f"Rx power below {f['rx_power_min_dbm']:g} dBm")
        rules.append(f"{f['errors_per_interval']}+ errors per interval")
        res["fixed"]["rule"] = "Rules: alert on " + ", ".join(rules)

    # ---- baseline (Display B) ----
    bl = []
    if oper == "2":
        bl.append("Link down")
    if r.get("state_changed") in (1, "1"):
        bl.append("Link state changed since the last reading")
    if base:
        if rx is not None and base["rx_mean"] is not None:
            drop = base["rx_mean"] - rx
            if drop >= s["baseline"]["rx_drop_db"]:
                bl.append(f"Rx power {drop:.1f} dB below this link's normal ({base['rx_mean']:.1f} dBm)")
        if base["speed"] and speed and speed < base["speed"]:
            bl.append(f"Speed {speed:g} Mb/s, normally {base['speed']:g}")
        for val, peak, name in ((inerr, base["errors_max"], "Input errors"),
                                (crc, base["crc_max"], "CRC errors"),
                                (late, base["late_max"], "Late collisions")):
            if val is not None and val > (peak or 0):
                bl.append(f"{name}: {val:.0f} in the last interval (normal: up to {peak or 0:.0f})")
    else:
        if late:
            bl.append(f"Late collisions: {late:.0f} in the last interval")
    if str(r.get("duplex_status")) == "2":
        bl.append("Half duplex")
    if bl:
        res["baseline"].update(fired=True, headline=bl[0], reasons=bl)
    return res


def false_alarm(ev):
    """Fixed rule fires while the link is within its own normal range."""
    return ev["reachable"] and ev["fixed"]["fired"] and not ev["baseline"]["fired"]


def port_status(rows, base, s, now_ts):
    """Problem list for the dashboard: everything that fired in the recent window."""
    window = s["window_minutes"] * 60
    recent = [r for r in rows if float(r["ts_unix"]) >= now_ts - window]
    reasons, last_ev = [], None
    for r in recent:
        if int(r.get("excluded") or 0):
            continue
        ev = evaluate(r, base, s)
        last_ev = ev
        for x in ev["baseline"]["reasons"]:
            if x not in reasons:
                reasons.append(x)
    current = evaluate(rows[-1], base, s) if rows else None
    return {"problem": bool(reasons), "reasons": reasons,
            "now": current["baseline"]["reasons"] if current else [],
            "reachable": current["reachable"] if current else False}
