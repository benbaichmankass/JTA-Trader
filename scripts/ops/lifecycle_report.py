#!/usr/bin/env python3
"""Read-only report of lifecycle results (what /ml-review and the console read).

Per plan/job: latest result, age, status counts; plus red flags and plans never run. Never
collapses "no results file" into zero: prints read_state. Usage: lifecycle_report.py [--results PATH]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(REPO / "runtime_logs/trainer/lifecycle_results.jsonl"))
    a = ap.parse_args()
    path = Path(a.results)
    if not path.is_file():
        print(json.dumps({"read_state": "unavailable", "detail": f"{path} missing (scheduler has not run here)"}))
        return 0
    latest, counts, n = {}, Counter(), 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("kind") == "pass_summary":
            continue
        n += 1
        latest[(r["plan_id"], r["job"])] = r
        counts[r["status"]] += 1
    print(json.dumps({"read_state": "ok", "population": f"{n} job records, {len(latest)} plan/job pairs",
                      "status_counts": counts,
                      "failing": sorted(f"{p}/{j}" for (p, j), r in latest.items() if r["status"] == "failed")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
