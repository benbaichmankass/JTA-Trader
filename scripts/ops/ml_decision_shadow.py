#!/usr/bin/env python3
"""Run ONE observe-only ML ENTRY scoring pass (src/runtime/ml_decision_shadow.py) and print its summary.

Fired every 15 minutes by deploy/ict-ml-decision-shadow.timer, in its own process (never the trader loop). Reads public
Bybit klines, scores every Bybit-listed reference symbol under ml_entry (v1) and ml_entry_v2, appends rows to
runtime_logs/ml_decision_shadow.jsonl. Places no order, touches no account. A failure exits non-zero so systemd and
/api/diag/services show it; the next timer fire retries (no halting).

    python3 scripts/ops/ml_decision_shadow.py            # one pass at the latest closed 15m boundary
    python3 scripts/ops/ml_decision_shadow.py --freshness
"""
# wiring: deploy/ict-ml-decision-shadow.service (ExecStart), fired by deploy/ict-ml-decision-shadow.timer
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freshness", action="store_true", help="print the sink's four-state freshness and exit")
    args = ap.parse_args(argv)
    from src.runtime import ml_decision_shadow as M
    from src.utils.paths import runtime_logs_dir
    if args.freshness:
        print(json.dumps(M.freshness(runtime_logs_dir() / M.LOG_NAME)))
        return 0
    summary = M.run_once()
    print(json.dumps({"ml_decision_shadow": summary}), flush=True)
    return 0 if summary["rows"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
