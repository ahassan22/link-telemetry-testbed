"""OID catalogue for the link-telemetry testbed.

Every per-interface OID below is a column OID; the collector appends
".<ifIndex>" to it. All of them are standard MIBs (IF-MIB, EtherLike-MIB)
except the DDM profiles, which are vendor-specific.
"""

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"  # TimeTicks (1/100 s); a drop means the agent restarted

# Per-interface metrics: name -> column OID.
# Order here is the column order in the raw CSV.
IF_METRICS = {
    # state
    "oper_status": "1.3.6.1.2.1.2.2.1.8",        # 1=up 2=down
    "last_change": "1.3.6.1.2.1.2.2.1.9",        # TimeTicks of last state change -> flaps between polls
    "high_speed": "1.3.6.1.2.1.31.1.1.1.15",     # Mb/s -> 1000 to 100 = classic copper degradation sign
    "duplex_status": "1.3.6.1.2.1.10.7.2.1.19",  # 1=unknown 2=half 3=full
    # traffic, 64-bit (preferred)
    "in_octets_hc": "1.3.6.1.2.1.31.1.1.1.6",
    "out_octets_hc": "1.3.6.1.2.1.31.1.1.1.10",
    "in_ucast_hc": "1.3.6.1.2.1.31.1.1.1.7",
    "out_ucast_hc": "1.3.6.1.2.1.31.1.1.1.11",
    # traffic, 32-bit (fallback for agents without ifXTable)
    "in_octets": "1.3.6.1.2.1.2.2.1.10",
    "out_octets": "1.3.6.1.2.1.2.2.1.16",
    "in_ucast": "1.3.6.1.2.1.2.2.1.11",
    "out_ucast": "1.3.6.1.2.1.2.2.1.17",
    # errors and drops
    "in_errors": "1.3.6.1.2.1.2.2.1.14",
    "out_errors": "1.3.6.1.2.1.2.2.1.20",
    "in_discards": "1.3.6.1.2.1.2.2.1.13",
    "out_discards": "1.3.6.1.2.1.2.2.1.19",
    "fcs_errors": "1.3.6.1.2.1.10.7.2.1.3",        # CRC errors: physical-layer damage
    "alignment_errors": "1.3.6.1.2.1.10.7.2.1.2",
    "late_collisions": "1.3.6.1.2.1.10.7.2.1.8",   # typical symptom of duplex mismatch
}

# Counter width, used when turning cumulative counters into per-interval deltas.
COUNTER_BITS = {
    "in_octets_hc": 64, "out_octets_hc": 64, "in_ucast_hc": 64, "out_ucast_hc": 64,
    "in_octets": 32, "out_octets": 32, "in_ucast": 32, "out_ucast": 32,
    "in_errors": 32, "out_errors": 32, "in_discards": 32, "out_discards": 32,
    "fcs_errors": 32, "alignment_errors": 32, "late_collisions": 32,
}

# Optical DDM/DOM profiles, keyed by vendor. Values are column OIDs; the row
# index is the port's ifIndex unless the config gives a ddm_index.
DDM_PROFILES = {
    # TP-Link JetStream / Omada: TPLINK-DDMSTATUS-MIB, ddmStatusTable.
    # Values come back as text (DisplayString), parsed to numbers in derive.py.
    "tplink": {
        "ddm_temperature": "1.3.6.1.4.1.11863.6.96.1.7.1.1.2",
        "ddm_voltage": "1.3.6.1.4.1.11863.6.96.1.7.1.1.3",
        "ddm_bias_current": "1.3.6.1.4.1.11863.6.96.1.7.1.1.4",
        "ddm_tx_power": "1.3.6.1.4.1.11863.6.96.1.7.1.1.5",
        "ddm_rx_power": "1.3.6.1.4.1.11863.6.96.1.7.1.1.6",
        "ddm_data_ready": "1.3.6.1.4.1.11863.6.96.1.7.1.1.7",
        "ddm_loss_signal": "1.3.6.1.4.1.11863.6.96.1.7.1.1.8",
        "ddm_tx_fault": "1.3.6.1.4.1.11863.6.96.1.7.1.1.9",
    },
}

DDM_TABLE_ROOT = {"tplink": "1.3.6.1.4.1.11863.6.96.1.7.1"}

# All DDM column names across profiles (fixed CSV schema).
DDM_COLUMNS = sorted({c for p in DDM_PROFILES.values() for c in p})

# Used by discover.py
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
