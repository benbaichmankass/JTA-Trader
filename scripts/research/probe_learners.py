#!/usr/bin/env python3
# wiring: .github/workflows/research-script-run.yml, research-script-run-data.yml, research-script-run-kaggle-cpu.yml, research-script-run-kaggle.yml
"""Print which ml_bakeoff learner kinds can run in THIS interpreter (ML-NONGBDT-RUNNERS, 2026-10-22).

One line per kind, then one JSON line, from ``ml_bakeoff.probe_learner`` -- the same import check the engine
runs before an arm, so "ok" here means the arm will not land ``unavailable`` on this backend. No data is read,
no network is used (a tabpfn import does not fetch weights; its token gate is ML-TABPFN-LICENCE).

    python3 scripts/research/probe_learners.py [--require kind,kind] [--backend NAME]

Exit 0 always unless --require names a kind that is unavailable (the workflow steps never pass --require:
a missing arm is a reported fact, not a halt).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ml_bakeoff  # noqa: E402

KINDS = ("lightgbm", "catboost", "sklearn_hgb", "tabicl", "tabpfn", "torch_gru")


def probe() -> dict:
    return {k: (ml_bakeoff.probe_learner(k, {}) or "ok") for k in KINDS}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--require", default="")
    ap.add_argument("--backend", default="")
    a = ap.parse_args(argv)
    res = probe()
    for k, v in res.items():
        print(f"{k:12s} {v}")
    print("PROBE_LEARNERS " + json.dumps({"backend": a.backend, "py": sys.version.split()[0], "arms": res}, sort_keys=True))
    need = [k for k in a.require.split(",") if k]
    bad = [k for k in need if res.get(k) != "ok"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
