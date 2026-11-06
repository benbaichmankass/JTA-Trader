#!/usr/bin/env python3
"""Upgrade cleanly-attributable closed trades from an estimate to BROKER-TRUTH fees.

Slice B / B2 (MB-20260629-ALLOC-COSTCAP). Joins `trade_journal.db::trades` to the
exchange-fills store (`runtime_state/exchange_fills.sqlite`) by the Slice-B/B0
`trades.broker_order_id` join key and FIFO-attributes each round trip's fees
(`src.runtime.broker_cost_attribution.attribute_roundtrip_fees`).

Writes `fee_taker_usd` + `fee_maker_usd` + `cost_source='broker'` ONLY for trades
whose attribution is **clean** (both legs matched, unambiguous, USD-denominated
fees). It overwrites a prior `'estimate'`/NULL cost (broker truth supersedes the
model) but NEVER an existing `'broker'` row, and never touches `pnl`, funding, the
order path, or any live-trading state. Ambiguous (netted) / entry-only / non-USD
trades keep their estimate — a wrong money-label is worse than an approximate one.

It does NOT populate `funding_paid_usd` — perp funding is not in the fills store
(it needs the separate funding puller, Slice B / B1).

Usage:
  python scripts/ops/backfill_broker_truth_costs.py            # dry-run (coverage report)
  python scripts/ops/backfill_broker_truth_costs.py --apply    # write broker-truth fees
  python scripts/ops/backfill_broker_truth_costs.py --db X --fills-db Y
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import datetime, timezone  # noqa: E402

from src.runtime.broker_cost_attribution import (  # noqa: E402
    attribute_funding_to_trades,
    attribute_roundtrip_fees,
)
from src.utils.paths import trade_journal_db_path  # noqa: E402

_USD = {"USDT", "USD", "USDC", ""}  # empty = unspecified, assume USD-margined


def _to_iso(val) -> str:
    """Normalise a trade timestamp (ISO or epoch-ms string) to an ISO string."""
    s = str(val or "")
    if s.isdigit():  # epoch ms
        try:
            return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).isoformat()
        except (ValueError, OverflowError):
            return s
    return s


def _load_trades(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, account_id, symbol, direction, broker_order_id, cost_source, "
        "funding_paid_usd, timestamp, closed_at "
        "FROM trades WHERE status='closed' AND COALESCE(is_backtest,0)=0 "
        "AND broker_order_id IS NOT NULL AND broker_order_id != ''"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["open_time"] = _to_iso(d.get("timestamp"))
        d["close_time"] = _to_iso(d.get("closed_at"))
        out.append(d)
    return out


def _load_funding(fills_db: str) -> list[dict]:
    conn = sqlite3.connect(f"file:{fills_db}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT account_id, symbol, funding_usd, funding_time FROM exchange_funding"
            ).fetchall()
        except sqlite3.OperationalError:
            return []  # funding table absent — B1 puller hasn't run yet
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _load_fills(fills_db: str) -> list[dict]:
    conn = sqlite3.connect(f"file:{fills_db}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT account_id, symbol, side, qty, fee, fee_currency, is_maker, "
            "order_id, exec_time, exec_id FROM exchange_fills"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _funding_covered(funding: list[dict]) -> dict:
    """Latest funding_time per account: funding is only trusted for a trade whose
    close is <= this, so a stale funding puller yields NULL, never a false $0."""
    out: dict = {}
    for f in funding:
        a, t = str(f.get("account_id")), str(f.get("funding_time") or "")
        if t and t > out.get(a, ""):
            out[a] = t
    return out


def sweep(db_path: str, fills_db: str, *, apply: bool, with_funding: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        trades = _load_trades(conn)
        fills = _load_fills(fills_db)
        funding = _load_funding(fills_db)
        costs = attribute_roundtrip_fees(trades, fills)
        cost_source_by_id = {int(t["id"]): t.get("cost_source") for t in trades}

        # Funding is attributed only to trades B2 flagged clean (sole holders).
        clean_ids = [tid for tid, c in costs.items() if c.clean]
        funding_by_id = attribute_funding_to_trades(trades, funding, clean_ids)
        covered = _funding_covered(funding)
        trade_by_id = {int(t["id"]): t for t in trades}

        def _funding_for(tid: int):
            t = trade_by_id[int(tid)]
            # exchange_funding was stored sign-INVERTED until #23570 (puller negation +
            # migration) deploys: funding is opt-in (--with-funding) until then.
            if not with_funding or not funding or tid not in funding_by_id:
                return None
            cov = covered.get(str(t["account_id"]), "")
            # normalise both sides to a comparable ISO prefix
            if not cov or _to_iso(cov)[:19] < _to_iso(t["close_time"])[:19]:
                return None  # funding store does not reach this close
            return funding_by_id[tid]

        summary = {
            "closed_with_join_key": len(trades),
            "fills_scanned": len(fills),
            "funding_scanned": len(funding),
            "clean": 0, "ambiguous": 0, "entry_only": 0, "no_match": 0,
            "non_usd_skipped": 0, "written": 0, "already_broker": 0, "funding_topped_up": 0,
            "total_broker_fee_usd": 0.0, "total_funding_usd": 0.0,
        }
        for tid, c in costs.items():
            if c.ambiguous:
                summary["ambiguous"] += 1
                continue
            if not c.entry_matched and not c.exit_matched:
                summary["no_match"] += 1
                continue
            if not c.clean:
                summary["entry_only"] += 1
                continue
            if not c.fee_currencies.issubset(_USD):
                summary["non_usd_skipped"] += 1
                continue
            if str(cost_source_by_id.get(tid) or "").lower() == "broker":
                summary["already_broker"] += 1
                if trade_by_id[int(tid)].get("funding_paid_usd") is None:
                    fv = _funding_for(tid)
                    if fv is not None:
                        summary["funding_topped_up"] += 1
                        if apply:
                            conn.execute(
                                "UPDATE trades SET funding_paid_usd=? WHERE id=? "
                                "AND funding_paid_usd IS NULL", (fv, int(tid)))
                continue
            summary["clean"] += 1
            fee_taker = round(float(c.fee_taker_usd), 8)
            fee_maker = round(float(c.fee_maker_usd), 8)
            # funding_paid_usd: NULL when no funding data (B1 puller hasn't run
            # / no funding events in the window) so we never write a false $0.
            funding_val = _funding_for(int(tid))
            summary["total_broker_fee_usd"] += fee_taker + fee_maker
            if funding_val is not None:
                summary["total_funding_usd"] += funding_val
            if apply:
                conn.execute(
                    "UPDATE trades SET fee_taker_usd=?, fee_maker_usd=?, "
                    "funding_paid_usd=COALESCE(?, funding_paid_usd), cost_source='broker' "
                    "WHERE id=? AND COALESCE(cost_source,'') != 'broker'",
                    (fee_taker, fee_maker, funding_val, int(tid)),
                )
            summary["written"] += 1
        if apply:
            conn.commit()
    finally:
        conn.close()
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None, help="trade_journal.db path (default: canonical resolver)")
    ap.add_argument("--fills-db", default=None, help="exchange_fills.sqlite path (default: store resolver)")
    ap.add_argument("--with-funding", action="store_true",
                    help="also write funding_paid_usd (only after the exchange_funding sign fix #23570 is deployed + re-pulled)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    args = ap.parse_args()

    db_path = args.db or str(trade_journal_db_path())
    if not Path(db_path).exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 2
    fills_db = args.fills_db
    if not fills_db:
        from src.runtime.exchange_fills_store import get_fills_db_path
        fills_db = str(get_fills_db_path())
    if not Path(fills_db).exists():
        print(f"fills store not found: {fills_db} — run pull-exchange-fills first", file=sys.stderr)
        return 2

    s = sweep(db_path, fills_db, apply=args.apply, with_funding=args.with_funding)
    mode = "APPLIED" if args.apply else "DRY-RUN (no write)"
    print(f"[{mode}] db={db_path} fills={fills_db}")
    print(f"  closed trades with a broker_order_id join key: {s['closed_with_join_key']}")
    print(f"  fills scanned: {s['fills_scanned']}  funding scanned: {s['funding_scanned']}")
    print(f"  CLEAN (both legs, unambiguous, USD) → broker-truth: {s['clean']}")
    print(f"  ambiguous (netted, kept estimate): {s['ambiguous']}")
    print(f"  entry-only / still-open (kept estimate): {s['entry_only']}")
    print(f"  no fill match (kept estimate): {s['no_match']}")
    print(f"  non-USD fees skipped: {s['non_usd_skipped']}")
    print(f"  already broker-truth (skipped): {s['already_broker']}")
    print(f"  funding topped up on existing broker rows: {s['funding_topped_up']}")
    print(f"  would-write broker-truth fees: {s['written']}  (fees ${s['total_broker_fee_usd']:.4f} · funding ${s['total_funding_usd']:.4f})")
    if not args.apply and s["written"]:
        print("  re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
