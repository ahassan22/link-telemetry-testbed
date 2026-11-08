# From Telemetry to Actionable Information: testbed data and analysis

Data and analysis code for the paper *From Telemetry to Actionable Information* by Ahmed Hassan (preprint, 2026).

The study ran common link faults on a small lab testbed and recorded what standard switch telemetry (SNMP) showed while they happened. It then compared two ways of turning the same readings into an alert:

- **Display A** uses fixed limits, the way many monitoring tools do.
- **Display B** judges the link against its own normal behaviour.

This repository holds the raw readings and the code that turns them into every table and figure reported in the paper.

## What is here

| Path | Contents |
|---|---|
| `session/data/raw.csv` | Every SNMP reading from both switches, every 15 s (21,538 polls per switch) |
| `session/data/derived.csv` | Rates and per-interval changes computed from `raw.csv` by `derive.py` |
| `session/data/events.csv` | The event log: start and end of each fault window, holds and notes, on the same clock |
| `session/config.json` | Interfaces monitored and alert settings (Display A and Display B) |
| `session/captures/survey/` | Metadata of the eight moments chosen by the fixed capture rule for the operator survey |
| `code/analyze.py` | Builds all results tables and figures from the session |
| `code/rules.py` | The two alerting rules (Display A and Display B), exactly as used in the study |
| `code/derive.py`, `code/oids.py` | Turn raw counters into rates and per-interval changes |
| `results/` | Output of `analyze.py` on this session, as reported in the paper |

## Testbed

- Cisco Catalyst 2960-X (IOS 15.2(2)E7) and TP-Link SG2428P (firmware 5.30.23).
- One fiber link between them (Cisco GLC-LH-SMD, 1310 nm single-mode, 10 m OS2 patch cord) and one copper link from the TP-Link to a PC.
- Traffic was generated with iperf3 at about 500 Mb/s in each direction.
- Readings come from the switches only. The TP-Link exposes no optical readings, so the fiber's optical view comes from the Cisco end.

Faults run: fiber bend (3 runs), copper duplex mismatch (4 runs), damaged copper cable (1 run), and a planned change on the fiber link (1 run). The paper gives the full protocol and the reasons for the excluded runs. The same reasons are recorded in `EPISODE_NOTES` in `analyze.py`. Corrections to the event log are kept there, never in the raw files.

## Reproduce the results

```
pip install -r code/requirements.txt
cd code
python analyze.py --session ../session --out ../results
```

The script recomputes every number from the session files; nothing is typed by hand. Running it on this repository reproduces the files in `results/`. To regenerate `derived.csv` from the raw readings:

```
python derive.py ../session/data/raw.csv --events ../session/data/events.csv --out ../session/data/derived.csv
```

## What is not here

- **The data collection prototype.** This includes the SNMP collector, the live dashboard and the screenshot tool. It is available from the author on request.
- **Operator survey responses.** These are not shared individually. As promised to participants, they are reported only in aggregate.
- **Lab details.** Device addresses and access credentials were removed. Hosts appear as `cisco-switch` and `tplink-switch`.

## Licence

- Code (`code/`): MIT License, see `LICENSE`.
- Data and results (`session/`, `results/`): Creative Commons Attribution 4.0 International (CC BY 4.0), see `LICENSE-DATA`.

If you use the data or code, please cite the paper.

## Contact

Ahmed Hassan · ahassanccna@gmail.com
