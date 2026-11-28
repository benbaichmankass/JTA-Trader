#!/usr/bin/env python3
"""Cut the d6c2-01 arm ledgers (B = stop 1.5, S10T4 = stop 1.0; committed, run 46056323510) to the trailing 3y and
365d windows ending at that run's end (2026-10-15), the windows the current prop record was graded on. Read-only."""
import json
from pathlib import Path

SRC = "comms/research/RQ-20261127-d6c2-01/46056323510/arms/{arm}__trades.jsonl"
OUT = Path(__file__).resolve().parent / "ledgers"
WIN = {"3y": "2023-10-15", "365d": "2025-10-15"}
for arm, leg in (("B", "stop15"), ("S10T4", "stop10")):
    rows = [json.loads(x) for x in Path(SRC.format(arm=arm)).read_text().splitlines() if x.strip()]
    for win, start in WIN.items():
        keep = [r for r in rows if r["entry_time"] >= start]
        (OUT / f"{leg}_{win}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in keep))
        print(leg, win, len(keep), keep[0]["entry_time"], keep[-1]["entry_time"])
