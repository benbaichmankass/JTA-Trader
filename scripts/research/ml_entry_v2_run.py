#!/usr/bin/env python3
"""Runner entry for the ENTRY v2 units (RQ-20261101-fs01-01 ablation, fs02-01 forward). The research runner executes only
``python3 scripts/research/<name>.py``, so the pipeline that used to be a shell script lives here.

    python3 scripts/research/ml_entry_v2_run.py ablation <unit> <out_dir>
    python3 scripts/research/ml_entry_v2_run.py forward  <unit> <out_dir>   # needs ABLATION_JSON=<fs01-01 ablation.json>

Steps: install the PINNED lightgbm (the live pin; a no-op once the runner image carries it, row RESEARCH-RUNNER-ML-DEPS / #22143),
fetch the Binance Vision streams (vision_streams.py), build the family table, run the arms in parallel (dev folds only), combine.
`forward` claims ONE read of W1 through holdout_lock.py inside ml_entry_v2.py.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PIN = "lightgbm==4.6.0"
HERE = Path(__file__).resolve().parent
ARMS = ["A", "A2", "B", "C", "D", "E", "F", "G"]


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], check=True)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("ablation", "forward"):
        print(__doc__)
        return 2
    mode, unit, out = argv[0], argv[1], Path(argv[2])
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", PIN, "scikit-learn"], check=True)
    streams, octd, work = out / "streams", out / "oct", out / "work"
    for d in (streams, octd, work):
        d.mkdir(parents=True, exist_ok=True)
    vs = str(HERE / "vision_streams.py")
    v2 = str(HERE / "ml_entry_v2.py")
    run(vs, "--out", str(streams), "--streams", "klines12,funding,premium", "--workers", "24")
    run(vs, "--out", str(streams), "--streams", "metrics", "--start", "2021-12-01", "--end", "2026-10-31", "--workers", "32")
    run(vs, "--out", str(octd), "--streams", "klines12d,premiumd", "--start", "2026-10-01", "--end", "2026-10-31", "--workers", "16")
    run(vs, "--out", str(octd), "--streams", "funding", "--start", "2026-10", "--end", "2026-10", "--workers", "16")
    run(v2, "build-table", "--streams", str(streams), "--oct-dir", str(octd), "--out", str(work))
    if mode == "ablation":
        procs = [subprocess.Popen([sys.executable, v2, "arm", "--arm", a, "--out", str(work), "--n-jobs", "2"]) for a in ARMS]
        if any(p.wait() for p in procs):
            return 1
        run(v2, "combine", "--out", str(work))
        for f in list(work.glob("ablation.json")) + list(work.glob("arm_*.json")):
            shutil.copy(f, out / f.name)
    else:
        abl = os.environ.get("ABLATION_JSON")
        if not abl:
            print("set ABLATION_JSON to the fs01-01 ablation.json", file=sys.stderr)
            return 2
        run(v2, "forward", "--out", str(work), "--ablation", abl, "--unit", unit)
        shutil.copy(work / "forward.json", out / "forward.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
