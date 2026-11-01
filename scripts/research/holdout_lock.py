#!/usr/bin/env python3
"""HOLDOUT-LOCK: a read-once ledger for sealed forward/held-out windows (rows HOLDOUT-LOCK, ML-BAR-ONE-READ).

Operator 2026-11-01 (popup, verbatim): "Yes, one model, one read (Rec.)". A scoring script calls ``claim_read``
BEFORE it touches any outcome in a sealed window. The ledger (append-only JSONL, committed with the result) holds one
line per read: who, when, which model, which window. Rules:

* a (model_id, window) pair can be read ONCE; a second claim raises ``HoldoutAlreadyRead`` and appends nothing;
* the claim returns ``variants_on_window`` = distinct models that have read an OVERLAPPING window, this one
  included, so every result record can state its variant count (ML-BAR-ONE-READ);
* dev-fold reads are not claimed (dev folds may be read repeatedly); only windows named sealed are.

    python3 scripts/research/holdout_lock.py --self-test
    python3 scripts/research/holdout_lock.py claim --model-id ENTRY-v2 --start 2026-10-01 --end 2026-10-31 --unit RQ-... --reader <who>
    python3 scripts/research/holdout_lock.py list
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[2] / "research" / "holdout_reads.jsonl"


class HoldoutAlreadyRead(RuntimeError):
    pass


def _rows(ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    return [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]


def _overlap(a0: str, a1: str, b0: str, b1: str) -> bool:
    return a0 <= b1 and b0 <= a1


def claim_read(model_id: str, start: str, end: str, unit: str, reader: str, ledger: Path = LEDGER,
               read_at: str | None = None) -> dict:
    """``read_at`` is only for BACKFILLING a read that happened before this lock existed (recorded with backfilled=true)."""
    if not (model_id and unit and reader):
        raise ValueError("model_id, unit and reader are required")
    if not start <= end:
        raise ValueError("start must be <= end")
    rows = _rows(ledger)
    for r in rows:
        if r["model_id"] == model_id and _overlap(r["start"], r["end"], start, end):
            raise HoldoutAlreadyRead(
                f"{model_id} already read {r['start']}..{r['end']} at {r['read_at']} by {r['reader']} "
                f"(unit {r['unit']}); one model, one read")
    models = {r["model_id"] for r in rows if _overlap(r["start"], r["end"], start, end)} | {model_id}
    rec = {"model_id": model_id, "start": start, "end": end, "unit": unit, "reader": reader,
           "read_at": read_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "backfilled": bool(read_at),
           "variants_on_window": len(models)}
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a") as f:
        f.write(json.dumps(rec) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return rec


def self_test() -> None:
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "l.jsonl"
        a = claim_read("m1", "2026-10-01", "2026-10-31", "U1", "tester", led)
        assert a["variants_on_window"] == 1
        try:
            claim_read("m1", "2026-10-15", "2026-11-05", "U1", "tester", led)
            raise AssertionError("second read of an overlapping window was allowed")
        except HoldoutAlreadyRead:
            pass
        assert len(_rows(led)) == 1, "a refused claim must append nothing"
        b = claim_read("m2", "2026-10-01", "2026-10-31", "U2", "tester", led)
        assert b["variants_on_window"] == 2, "second model on the same window must count as a variant"
        c = claim_read("m1", "2026-11-11", "2026-11-20", "U3", "tester", led)
        assert c["variants_on_window"] == 1, "a disjoint window starts a fresh count"
        assert all(r["reader"] and r["read_at"] for r in _rows(led))
    print("holdout_lock self-test OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["claim", "list"])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--model-id")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--unit")
    ap.add_argument("--reader", default=os.environ.get("USER", "unknown"))
    ap.add_argument("--ledger", default=str(LEDGER))
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return 0
    if a.cmd == "claim":
        print(json.dumps(claim_read(a.model_id, a.start, a.end, a.unit, a.reader, Path(a.ledger))))
        return 0
    if a.cmd == "list":
        for r in _rows(Path(a.ledger)):
            print(json.dumps(r))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
