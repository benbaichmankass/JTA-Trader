"""Set ONE open journal row's ``position_size`` to the venue's quantity, guarded.

WHY. A journal row can disagree with the venue about how many units it holds (ib_paper MGC trade 6673: journal
14, venue 12) and no existing action writes ``position_size`` for a single row: ``reconcile-netting-rows`` only
CLOSES surplus rows on Bybit groups. This is the narrow writeback, with the same shape as
``mark_operator_flattened.py``: targets are NAMED, never derived.

GUARDS (any failure writes NOTHING):
  * the row exists, is ``status='open'``, is not a backtest row, and belongs to ``--account``;
  * ``--symbol`` matches the row;
  * its CURRENT ``position_size`` equals ``--expect-qty`` (the value the caller read), so a stale plan cannot
    overwrite a row that moved since it was planned;
  * ``--new-qty`` is positive, finite and different from the current value.
The prior value is recorded in ``notes.qty_writeback`` AND printed (the wrapper also writes it to the audit
record), so the write is reversible by hand. No money field (entry, pnl, SL/TP) and no venue is touched.

Usage on the VM:
    python3 scripts/ops/set_journal_trade_qty.py --trade-id 6673 --account ib_paper --symbol MGC \\
        --expect-qty 14 --new-qty 12 --reason "journal 14 vs venue 12" [--apply]
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

NOTE_KEY = "qty_writeback"


def _db_path() -> str:
    from src.utils.paths import trade_journal_db_path
    return str(trade_journal_db_path())


def _dump_notes(notes: Dict[str, Any]) -> str:
    try:
        from src.utils.json_notes import dump_capped
        return dump_capped(notes, 500)
    except Exception:  # noqa: BLE001  # allow-silent: bare invocation outside the repo; plain JSON is the named degraded path
        return json.dumps(notes)


def _load_notes(raw: Any) -> Dict[str, Any]:
    try:
        n = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {"_original_notes": raw}
    return n if isinstance(n, dict) else {"_original_notes": raw}


def plan(conn: sqlite3.Connection, trade_id: int, account: str, symbol: str,
         expect_qty: float, new_qty: float, reason: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """(update, refusals). A non-empty refusal list means write NOTHING."""
    conn.row_factory = sqlite3.Row
    refusals: List[str] = []
    if not (math.isfinite(new_qty) and new_qty > 0):
        refusals.append(f"new_qty {new_qty!r} must be a positive finite number")
    if not (math.isfinite(expect_qty) and expect_qty > 0):
        refusals.append(f"expect_qty {expect_qty!r} must be a positive finite number")
    if not reason.strip():
        refusals.append("reason is empty - the record of WHY is the point")
    row = conn.execute(
        "SELECT id, status, is_backtest, symbol, account_id, position_size, notes FROM trades WHERE id = ?",
        (trade_id,)).fetchone()
    if row is None:
        return None, refusals + [f"id={trade_id}: no such trade row"]
    if int(row["is_backtest"] or 0):
        refusals.append(f"id={trade_id}: is a backtest row")
    if str(row["status"] or "") != "open":
        refusals.append(f"id={trade_id}: status={row['status']!r}, not 'open' - a closed row's size is history")
    if str(row["account_id"] or "") != account:
        refusals.append(f"id={trade_id}: account_id={row['account_id']!r}, not {account!r}")
    if str(row["symbol"] or "").upper() != symbol.upper():
        refusals.append(f"id={trade_id}: symbol={row['symbol']!r}, not {symbol!r}")
    cur = float(row["position_size"])
    if abs(cur - expect_qty) > 1e-9:
        refusals.append(f"id={trade_id}: position_size is {cur!r} now, not the expected {expect_qty!r} (moved since planned)")
    if abs(cur - new_qty) <= 1e-9:
        refusals.append(f"id={trade_id}: position_size is already {new_qty!r} (nothing to write)")
    if refusals:
        return None, refusals
    notes = _load_notes(row["notes"])
    notes[NOTE_KEY] = {"prior": cur, "new": new_qty, "reason": reason,
                       "at": datetime.now(timezone.utc).isoformat()}
    return {"id": trade_id, "prior": cur, "new": new_qty, "notes": _dump_notes(notes)}, []


def apply(conn: sqlite3.Connection, u: Dict[str, Any]) -> int:
    with conn:
        cur = conn.execute(
            "UPDATE trades SET position_size = ?, notes = ? WHERE id = ? AND status = 'open' AND position_size = ?",
            (u["new"], u["notes"], u["id"], u["prior"]))
    return cur.rowcount


def _self_test() -> int:
    c = sqlite3.connect(":memory:")
    # data-wiring: in-memory self-test fixture mirroring canonical trade_journal.db trades; no persistent table, no backfill
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT, is_backtest INT, symbol TEXT, "
              "account_id TEXT, position_size REAL NOT NULL, notes TEXT)")
    c.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?)", [
        (1, "open", 0, "MGC", "ib_paper", 14.0, None),
        (2, "closed", 0, "MGC", "ib_paper", 14.0, None),
        (3, "open", 1, "MGC", "ib_paper", 14.0, None),
        (4, "open", 0, "MGC", "ib_paper", 14.0, '{"keep": 1}')])
    bad = 0

    def chk(name: str, ok: bool) -> None:
        nonlocal bad
        print(("PASS " if ok else "FAIL ") + name)
        bad += 0 if ok else 1

    u, r = plan(c, 1, "ib_paper", "MGC", 14, 12, "x")
    chk("happy path plans 14 -> 12", u is not None and not r and u["prior"] == 14.0)
    chk("apply writes exactly one row", apply(c, u) == 1 and
        c.execute("SELECT position_size FROM trades WHERE id=1").fetchone()[0] == 12.0)
    chk("re-run is refused (already 12)", plan(c, 1, "ib_paper", "MGC", 14, 12, "x")[0] is None)
    chk("stale expect_qty refused", plan(c, 4, "ib_paper", "MGC", 13, 12, "x")[0] is None)
    chk("closed row refused", plan(c, 2, "ib_paper", "MGC", 14, 12, "x")[0] is None)
    chk("backtest row refused", plan(c, 3, "ib_paper", "MGC", 14, 12, "x")[0] is None)
    chk("wrong account refused", plan(c, 4, "bybit_1", "MGC", 14, 12, "x")[0] is None)
    chk("wrong symbol refused", plan(c, 4, "ib_paper", "MES", 14, 12, "x")[0] is None)
    chk("non-positive qty refused", plan(c, 4, "ib_paper", "MGC", 14, 0, "x")[0] is None)
    chk("missing row refused", plan(c, 99, "ib_paper", "MGC", 14, 12, "x")[0] is None)
    chk("empty reason refused", plan(c, 4, "ib_paper", "MGC", 14, 12, " ")[0] is None)
    u4, _ = plan(c, 4, "ib_paper", "MGC", 14, 12, "x")
    chk("existing notes keys are kept", u4 is not None and json.loads(u4["notes"]).get("keep") == 1)
    return 1 if bad else 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--trade-id", type=int)
    p.add_argument("--account")
    p.add_argument("--symbol")
    p.add_argument("--expect-qty", type=float)
    p.add_argument("--new-qty", type=float)
    p.add_argument("--reason", default="")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return _self_test()
    missing = [k for k in ("trade_id", "account", "symbol", "expect_qty", "new_qty") if getattr(a, k) is None]
    if missing:
        p.error("required: " + ", ".join("--" + m.replace("_", "-") for m in missing))
    conn = sqlite3.connect(_db_path())
    u, refusals = plan(conn, a.trade_id, a.account, a.symbol, a.expect_qty, a.new_qty, a.reason)
    if refusals:
        print("REFUSED (nothing written):")
        for r in refusals:
            print("  - " + r)
        return 2
    print(f"PLAN: trade {u['id']} position_size {u['prior']!r} -> {u['new']!r}")
    if not a.apply:
        print("DRY-RUN: nothing written. Re-dispatch with apply: true.")
        return 0
    n = apply(conn, u)
    print(f"APPLIED: {n} row(s). prior={u['prior']!r} new={u['new']!r}")
    return 0 if n == 1 else 3


if __name__ == "__main__":
    sys.exit(main())
