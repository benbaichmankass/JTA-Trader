#!/usr/bin/env python3
r"""Backfill: settle historical ``intent_reduce`` legs' realised PnL from venue fills.

PERF-FU-REDUCE-PNL. A reduce that PARTIALLY consumes a parent shrinks the parent
row, so the reduced units' realised PnL was booked on no row (the
``deferred_intent_reduce`` marker assumed the parent carried it). The forward fix
is ``order_monitor._sweep_settle_intent_reduce_legs`` (last 3 days only); this
script settles the history with the SAME plan
(:mod:`src.runtime.reduce_leg_settlement`).

PROVENANCE: a row is booked only when BOTH the reduce order's fill and every
partially-consumed parent's entry fill are in the exchange-fills store (venue
fills, joined by venue order id) → ``exit_price_source='exchange_fill'``
(MEASURED), ``pnl_source='local_compute'``, net of the reduce fees pro-rated to
the booked share. Otherwise ``pnl`` stays NULL and the row is stamped
``reduce_settlement='unverified'`` + the reason. Nothing is estimated.

SAFETY:
  * DRY-RUN by default: prints every row's plan and the per-account delta
    (real-money first). ``--apply`` writes, after a timestamped DB backup.
  * Idempotent: a row already carrying ``notes.reduce_settlement`` is skipped.
  * Touches only reduce AUDIT rows (``exit_reason='intent_reduce_executed'``);
    never a parent row, never the venue, never a service.

Usage on the VM (the system-action wrapper passes ``--db``):
    python3 scripts/ops/backfill_intent_reduce_pnl.py                  # dry-run
    python3 scripts/ops/backfill_intent_reduce_pnl.py --apply          # write
    python3 scripts/ops/backfill_intent_reduce_pnl.py --ids 6532,6540  # restrict
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.runtime import reduce_leg_settlement as rls  # noqa: E402


class _Db:
    """The two methods ``apply_settlement`` needs, on one sqlite file."""

    def __init__(self, path: str) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def update_trade(self, trade_id: int, updates: Dict[str, Any]) -> int:
        conn = self.connect()
        try:
            cols = ", ".join(f"{k} = ?" for k in updates)
            cur = conn.execute(
                f"UPDATE trades SET {cols} WHERE id = ? AND pnl IS NULL",
                list(updates.values()) + [int(trade_id)],
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


def _account_class(row: Dict[str, Any]) -> str:
    return str(row.get("account_class") or "real_money")


def run(db_path: str, *, apply: bool, ids: Optional[List[int]] = None,
        fills_db: Optional[str] = None) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cand = rls.select_candidates(conn, ids=ids)
    finally:
        conn.close()
    rows = cand["rows"]
    if fills_db and not os.path.exists(fills_db):
        print(f"error: fills store not found at {fills_db} — refusing: an absent "
              "store would read as 'no fills' and plan every row unverified "
              "(BL-20260717-FILLS-STORE-PATH-SPLIT).", file=sys.stderr)
        return 2
    factory = (lambda: sqlite3.connect(f"file:{fills_db}?mode=ro", uri=True)) \
        if fills_db else None
    try:
        fills = rls.fills_by_order_from_store(cand["order_ids"], conn_factory=factory)
    except rls.FillsStoreUnavailable as exc:
        print(f"error: {exc} — refusing (pass --fills-db; the system-action wrapper "
              "passes $(fills_store_path)).", file=sys.stderr)
        return 2
    print(f"fills store: {fills_db or 'resolver default'}")
    print(f"population: {len(rows)} unsettled reduce leg(s) "
          f"(exit_reason=intent_reduce_executed, closed, pnl NULL, non-backtest, "
          f"not superseded, not yet looked at) · {len(cand['parents_by_id'])} parent "
          f"row(s) · fills found for {len(fills)} of {len(cand['order_ids'])} order id(s)")

    plans = [(r, rls.plan_settlement(r, cand["parents_by_id"], fills)) for r in rows]
    agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    reasons: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r, p in plans:
        a = agg[r.get("account_id") or "?"]
        a["class"] = _account_class(r)
        a[p.state] += 1
        if p.state == rls.SETTLED_STATE:
            a["net_pnl"] += p.pnl or 0.0
            a["gross_pnl"] += p.gross_pnl or 0.0
            a["fees"] += p.fees_usd or 0.0
        else:
            reasons[r.get("account_id") or "?"][p.reason.split("(")[0]] += 1

    print("\nper-row plan:")
    print(f"{'id':>6} {'account':<16} {'symbol':<9} {'state':<19} "
          f"{'net_pnl':>11} {'gross':>11} {'fees':>9}  reason")
    for r, p in plans:
        print(f"{p.trade_id:>6} {p.account_id:<16} {p.symbol:<9} {p.state:<19} "
              f"{(p.pnl if p.pnl is not None else float('nan')):>11.2f} "
              f"{(p.gross_pnl if p.gross_pnl is not None else float('nan')):>11.2f} "
              f"{(p.fees_usd if p.fees_usd is not None else float('nan')):>9.2f}  {p.reason}")

    print("\nP&L the backfill would BOOK, per account (real money first):")
    order = sorted(agg, key=lambda k: (agg[k]["class"] != "real_money", k))
    for acct in order:
        a = agg[acct]
        print(f"  {acct:<16} [{a['class']}] settled={int(a[rls.SETTLED_STATE])} "
              f"absorbed={int(a[rls.ABSORBED_STATE])} "
              f"unverified={int(a[rls.UNVERIFIED_STATE])} · "
              f"net {a['net_pnl']:+.2f} USD (gross {a['gross_pnl']:+.2f}, "
              f"fees {a['fees']:.2f})"
              + (f" · refusals {dict(reasons[acct])}" if reasons[acct] else ""))

    if not apply:
        print("\ndry-run — pass --apply to write (a DB backup is taken first).")
        return 0
    if not plans:
        print("nothing to do.")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{db_path}.bak-reduce-pnl-{stamp}"
    shutil.copy2(db_path, backup)
    print(f"\nbackup: {backup}")
    db = _Db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    written = 0
    for r, p in plans:
        rls.apply_settlement(db, r, p, now_iso=now_iso)
        written += 1
    print(f"applied: {written} row(s) stamped "
          f"({sum(1 for _, p in plans if p.state == rls.SETTLED_STATE)} with pnl).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    ap.add_argument("--db", default=None, help="trade_journal.db (default: canonical resolver)")
    ap.add_argument("--fills-db", default=None,
                    help="exchange_fills.sqlite (default: $EXCHANGE_FILLS_DB / resolver)")
    ap.add_argument("--ids", default=None, help="comma-separated trade-id allowlist")
    args = ap.parse_args()
    if args.db:
        db_path = args.db
    else:
        from src.utils.paths import trade_journal_db_path
        db_path = str(trade_journal_db_path())
    if not os.path.exists(db_path):
        print(f"error: db not found at {db_path}", file=sys.stderr)
        return 2
    ids = None
    if args.ids:
        try:
            ids = [int(x) for x in args.ids.split(",") if x.strip()]
        except ValueError:
            print(f"error: --ids must be integers, got {args.ids!r}", file=sys.stderr)
            return 2
    return run(db_path, apply=args.apply, ids=ids, fills_db=args.fills_db)


if __name__ == "__main__":
    sys.exit(main())
