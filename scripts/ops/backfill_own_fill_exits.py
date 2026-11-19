#!/usr/bin/env python3
r"""Backfill: price a closed trade's exit from the venue fill that closed it.

SOAK-MECH-B / PI-20261010-RNCT2YDP-0001. Two populations reached their close
with no MEASURED exit price, while the closing fill sat in the exchange-fills
store:

* **Alpaca ``exchange_flat_reconciled`` rows with ``exit_price`` NULL.** The
  broker sweep (``order_monitor._sweep_pending_pnl_from_bybit``) only selects
  rows closed in the last 7 days, and until E62 (2026-09-05) that window was
  keyed on the OPEN — so a position held > 7 days was never asked about.
  MEASURED 2026-10-17 (alpaca_order_history + /api/bot/pnl/exchange/fills,
  alpaca_paper): 3934 GLD, 4422 IWM, 4710 SCHA each closed on ONE stop order
  whose fills sum exactly to the row's qty.
* **Bybit rows priced off the close-time candle** (``candle_at_close``,
  ESTIMATED) because the cumulative fills read refuses on a netted position.
  MEASURED: bybit_1 6171 booked 1.5399 (candle); its 1221.9 were sold at
  1.5428 by order 15ee6294 (SOAK-MECH-C).

The forward fix is the same resolver in the live local sweep
(``fills_pnl.exit_from_one_order_fills``); this script settles history with it.

WHAT IT WRITES: ``exit_price``, ``pnl`` (local compute, net of the close-side
fees on those fills), ``pnl_percent``, and in ``notes``
``exit_price_source='exchange_fill'`` (MEASURED), ``pnl_source='local_compute'``
and a ``backfill_own_fill`` audit record holding the prior exit price, prior
source and prior pnl (reversible per row).

WHAT IT NEVER TOUCHES: ``exit_reason`` (``backfill-exit-labels`` owns labels),
``status``, ``closed_at``, any row whose exit price is already MEASURED,
backtest rows, intent_reduce legs, the venue, or a service.

RESOLUTION, in order, both bounded to [open - 60 s, closed_at + 60 s]:
  1. ``exit_from_one_order_fills``: the row's own sl/tp order, else the ONE
     order whose fills sum to the qty. First, because it prices EVERY fill of
     that order (GLD 3934: 385.333056, Alpaca's own filled_avg_price).
  2. ``exit_from_fills``: close-side fills across orders summing to the qty
     (it stops once within 5%, so it can leave a tail of the order out).
Anything else is left alone and listed with the reason (e.g. QQQ 6023: its
22 shares left through four orders, none of them 22).

SAFETY: dry-run by default; ``--apply`` writes after an online sqlite backup;
each UPDATE re-checks the prior exit_price and pnl so a concurrent writer wins.

    python3 scripts/ops/backfill_own_fill_exits.py --ids 3934,4422     # dry-run
    python3 scripts/ops/backfill_own_fill_exits.py --ids 3934 --apply  # write
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.runtime import provenance as prov  # noqa: E402
from src.runtime.fills_pnl import (  # noqa: E402
    FILL_EXIT_SOURCE,
    exit_from_fills,
    exit_from_one_order_fills,
)
from src.runtime.local_pnl import (  # noqa: E402
    compute_pnl_percent,
    compute_realized_pnl,
    contract_value_usd_for,
)

_SLACK_MS = 60_000


def _ms(value: Any) -> Optional[int]:
    s = str(value or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _notes(raw: Any) -> Dict[str, Any]:
    try:
        n = json.loads(raw or "{}")
        return n if isinstance(n, dict) else {}
    except (TypeError, ValueError):
        return {}


def _skip_reason(row: Dict[str, Any]) -> Optional[str]:
    """Why *row* is not a candidate, else None."""
    if row.get("status") != "closed":
        return f"status={row.get('status')!r}"
    if row.get("is_backtest"):
        return "backtest row"
    notes = _notes(row.get("notes"))
    if str(row.get("setup_type") or "").lower() == "intent_reduce" or notes.get("intent_reduce"):
        return "intent_reduce leg (reduce_leg_settlement owns it)"
    if row.get("exit_price") is not None and prov.classify(
            notes.get("exit_price_source"), "exit_price_source") == prov.MEASURED:
        return f"exit already MEASURED ({notes.get('exit_price_source')})"
    if not (float(row.get("position_size") or 0) > 0 and float(row.get("entry_price") or 0) > 0):
        return "no entry price / size"
    if _ms(row.get("created_at")) is None or _ms(row.get("closed_at")) is None:
        return "open or close time unparseable"
    return None


def plan_row(row: Dict[str, Any], conn_factory: Callable[[], Any]
             ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``(updates, None)`` or ``(None, why_not)`` for one trades row."""
    why = _skip_reason(row)
    if why:
        return None, why
    common = dict(
        account_id=str(row["account_id"] or ""), symbol=str(row["symbol"] or ""),
        direction=str(row["direction"] or ""), opened_at_ms=_ms(row["created_at"]),
        closed_at_ms=_ms(row["closed_at"]) + _SLACK_MS,
        qty=float(row["position_size"]), conn_factory=conn_factory,
    )
    rec = exit_from_one_order_fills(
        **common, own_order_ids=(row.get("sl_order_id"), row.get("tp_order_id")))
    match = (rec or {}).get("match") or ""
    if rec is None:
        rec = exit_from_fills(**common)
        match = "window_qty"
    if rec is None:
        return None, "no attributable close fill (window qty off, no single order of this qty)"
    exit_px = float(rec["avg_exit_price"])
    cvu = contract_value_usd_for(row["symbol"])
    pnl = compute_realized_pnl(entry_price=row["entry_price"], exit_price=exit_px,
                               qty=row["position_size"], direction=row["direction"],
                               contract_value_usd=cvu)
    if pnl is None:
        return None, "pnl not computable"
    fees = float(rec.get("fees") or 0.0)
    pnl = round(pnl - fees, 4)
    notes = _notes(row.get("notes"))
    notes["backfill_own_fill"] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "match": match, "order_id": rec.get("order_id"), "fill_at": rec.get("closed_at"),
        "prior_exit_price": row.get("exit_price"),
        "prior_exit_price_source": notes.get("exit_price_source"),
        "prior_pnl": row.get("pnl"),
    }
    notes["exit_price_source"] = FILL_EXIT_SOURCE
    notes["pnl_source"] = "local_compute"
    notes["contract_value_usd"] = cvu
    if fees:
        notes["close_fees_usd"] = fees
        notes["pnl_net_of_close_fees"] = True
    updates: Dict[str, Any] = {"exit_price": exit_px, "pnl": pnl,
                               "notes": json.dumps(notes, ensure_ascii=False)}
    pct = compute_pnl_percent(pnl=pnl, entry_price=row["entry_price"],
                              qty=row["position_size"], contract_value_usd=cvu)
    if pct is not None:
        updates["pnl_percent"] = pct
    return updates, None


#: GROUP MODE (opt-in, ``--group``): rows closed in ONE close event span at most this many seconds.
GROUP_CLOSE_SPAN_S = 300


def plan_group(rows: List[Dict[str, Any]], conn_factory: Callable[[], Any]
               ) -> Tuple[Optional[Dict[int, Dict[str, Any]]], Optional[str]]:
    """``({row_id: updates}, None)`` or ``(None, why_not)`` for SEVERAL rows one venue order closed together.

    WHY (ALPACA-CLOSE-BROKER-TRUTH, 2026-11-19): alpaca_paper QQQ rows 7780/7781/7782 (735/55/7 sh) and 7783 (2 sh)
    were closed at once when the US-open gap took out their stops; no row's OWN qty equals a fill window or an order,
    so ``plan_row`` refuses each one. Every share of a single venue order fills at that order's price, so when ONE
    order's fills sum to the rows' combined qty, giving each row that price is still a MEASURED exit.

    Refuses (never guesses) unless ALL hold: >= 2 rows; every row passes ``_skip_reason``; one account + symbol +
    direction; closes within ``GROUP_CLOSE_SPAN_S``; ``exit_from_one_order_fills`` over the union window finds
    exactly ONE order whose fills sum to the combined qty (two candidates or none refuse there). Close fees are
    split by qty. The match is recorded as ``group_single_order`` with the group's ids and qty.
    """
    if len(rows) < 2:
        return None, "group mode needs >= 2 rows"
    for r in rows:
        why = _skip_reason(r)
        if why:
            return None, f"id={r['id']}: {why}"
    keys = {(str(r["account_id"] or ""), str(r["symbol"] or ""), str(r["direction"] or "").lower()) for r in rows}
    if len(keys) != 1:
        return None, f"rows span {len(keys)} account/symbol/direction keys; a group is one"
    closes = [_ms(r["closed_at"]) for r in rows]
    if (max(closes) - min(closes)) > GROUP_CLOSE_SPAN_S * 1000:
        return None, f"closes span {(max(closes) - min(closes)) / 1000:.0f}s > {GROUP_CLOSE_SPAN_S}s: not one close event"
    total = round(sum(float(r["position_size"]) for r in rows), 10)
    acct, sym, direction = next(iter(keys))
    rec = exit_from_one_order_fills(
        account_id=acct, symbol=sym, direction=direction,
        opened_at_ms=min(_ms(r["created_at"]) for r in rows), closed_at_ms=max(closes) + _SLACK_MS,
        qty=total, own_order_ids=(), conn_factory=conn_factory)
    if rec is None or rec.get("match") != "single_order_qty":
        return None, f"no single venue order whose fills sum to the group qty {total:g} (or two that do)"
    # EXACT, not the per-row QTY_TOLERANCE (5%): a group is allocated share-for-share, so an order that filled
    # 797 of 799 grouped shares would price a row that order never closed. Any mismatch refuses.
    filled = float(rec.get("qty") or 0.0)
    if abs(filled - total) > max(1e-9, total * 1e-9):
        return None, (f"no single venue order whose fills sum to the group qty {total:g} "
                      f"(nearest order {rec.get('order_id')} filled {filled:g}; group mode needs an exact match)")
    exit_px = float(rec["avg_exit_price"])
    fees_total = float(rec.get("fees") or 0.0)
    cvu = contract_value_usd_for(sym)
    ids = [r["id"] for r in rows]
    out: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        share = float(r["position_size"]) / total
        pnl = compute_realized_pnl(entry_price=r["entry_price"], exit_price=exit_px, qty=r["position_size"],
                                   direction=r["direction"], contract_value_usd=cvu)
        if pnl is None:
            return None, f"id={r['id']}: pnl not computable"
        fees = round(fees_total * share, 6)
        pnl = round(pnl - fees, 4)
        notes = _notes(r.get("notes"))
        notes["backfill_own_fill"] = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "match": "group_single_order", "order_id": rec.get("order_id"), "fill_at": rec.get("closed_at"),
            "group_ids": ids, "group_qty": total, "qty_share": round(share, 8),
            "prior_exit_price": r.get("exit_price"),
            "prior_exit_price_source": notes.get("exit_price_source"),
            "prior_pnl": r.get("pnl"),
        }
        notes["exit_price_source"] = FILL_EXIT_SOURCE
        notes["exit_price_allocation"] = "group_allocated"
        notes["pnl_source"] = "local_compute"
        notes["contract_value_usd"] = cvu
        if fees:
            notes["close_fees_usd"] = fees
            notes["pnl_net_of_close_fees"] = True
        upd: Dict[str, Any] = {"exit_price": exit_px, "pnl": pnl, "notes": json.dumps(notes, ensure_ascii=False)}
        pct = compute_pnl_percent(pnl=pnl, entry_price=r["entry_price"], qty=r["position_size"],
                                  contract_value_usd=cvu)
        if pct is not None:
            upd["pnl_percent"] = pct
        out[r["id"]] = upd
    return out, None


def _candidates(conn: sqlite3.Connection, ids: Optional[List[int]]) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    cols = ("id, account_id, symbol, direction, entry_price, exit_price, position_size, "
            "status, is_backtest, setup_type, exit_reason, pnl, created_at, closed_at, "
            "notes, sl_order_id, tp_order_id")
    if ids:
        q = f"SELECT {cols} FROM trades WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id"
        return [dict(r) for r in conn.execute(q, ids).fetchall()]
    # No allowlist: the generic-reason rows with no MEASURED exit.
    q = (f"SELECT {cols} FROM trades WHERE status='closed' AND COALESCE(is_backtest,0)=0 "
         "AND COALESCE(exit_reason,'') IN ('', 'reconciler_filled', 'exchange_flat_reconciled', "
         "'stuck_strategy_watchdog', 'netting_attributed') ORDER BY id")
    return [dict(r) for r in conn.execute(q).fetchall()]

def _take_backup():
    """The shared pre-APPLY backup with per-tag retention (scripts/ops/journal_backup.py)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts.ops.journal_backup import take_backup
    return take_backup


def run(db_path: str, fills_db: str, *, apply: bool, ids: Optional[List[int]] = None, group: bool = False) -> int:
    def fills_conn():
        return sqlite3.connect(f"file:{fills_db}?mode=ro", uri=True) if os.path.exists(fills_db) else None

    conn = sqlite3.connect(db_path)
    try:
        rows = _candidates(conn, ids)
    finally:
        conn.close()
    plans: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    print(f"db: {db_path}\nfills: {fills_db}\nrows read: {len(rows)}"
          + (f" (ids {','.join(map(str, ids))})" if ids else " (generic-reason population)"))
    if ids:
        missing = sorted(set(ids) - {r["id"] for r in rows})
        if missing:
            print(f"  ids not in the journal: {missing}")
    if group:
        gplan, why = plan_group(rows, fills_conn)
        if gplan is None:
            print(f"  GROUP REFUSED: {why}")
            rows = []
        else:
            for r in rows:
                upd = gplan[r["id"]]
                n = json.loads(upd["notes"])["backfill_own_fill"]
                print(f"  PLAN id={r['id']} {r['account_id']} {r['symbol']} {r['direction']} "
                      f"qty={r['position_size']} exit {r['exit_price']} -> {upd['exit_price']:.6g} "
                      f"pnl {r['pnl']} -> {upd['pnl']} (group_single_order order={n['order_id']} "
                      f"group_qty={n['group_qty']:g} share={n['qty_share']} prior_src={n['prior_exit_price_source']})")
                plans.append((r, upd))
            rows = []
    for r in rows:
        upd, why = plan_row(r, fills_conn)
        if upd is None:
            if ids or not why.startswith("exit already MEASURED"):
                print(f"  SKIP id={r['id']} {r['account_id']} {r['symbol']}: {why}")
            continue
        n = json.loads(upd["notes"])["backfill_own_fill"]
        print(f"  PLAN id={r['id']} {r['account_id']} {r['symbol']} {r['direction']} "
              f"qty={r['position_size']} exit {r['exit_price']} -> {upd['exit_price']:.6g} "
              f"pnl {r['pnl']} -> {upd['pnl']} ({n['match']} order={n['order_id']} "
              f"prior_src={n['prior_exit_price_source']})")
        plans.append((r, upd))
    print(f"planned: {len(plans)}")
    if not apply:
        print("dry-run — pass --apply to write (an online DB backup is taken first).")
        return 0
    if not plans:
        return 0
    # Pre-APPLY copy; keeps only the newest per tag (scripts/ops/journal_backup.py).
    backup = _take_backup()(db_path, "own-fill-exits", method="online", stamp_style="iso", read_only=False)
    print(f"backup: {backup}")
    written = 0
    conn = sqlite3.connect(db_path)
    try:
        for r, upd in plans:
            sets = ", ".join(f"{k} = ?" for k in upd)
            cur = conn.execute(
                f"UPDATE trades SET {sets} WHERE id = ? AND status = 'closed' "
                "AND exit_price IS ? AND pnl IS ?",
                (*upd.values(), r["id"], r["exit_price"], r["pnl"]))
            if cur.rowcount:
                written += 1
            else:
                print(f"  LOST RACE id={r['id']}: exit_price/pnl changed since the plan; left alone")
        conn.commit()
    finally:
        conn.close()
    print(f"WROTE {written} of {len(plans)} rows.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    ap.add_argument("--db", default=None, help="trade_journal.db (default: canonical resolver)")
    ap.add_argument("--fills-db", default=None,
                    help="exchange_fills.sqlite (default: canonical resolver)")
    ap.add_argument("--ids", default=None, help="comma-separated trade-id allowlist")
    ap.add_argument("--group", action="store_true",
                    help="opt-in: price the --ids rows TOGETHER from the ONE venue order whose fills sum to their "
                         "combined qty (refuses on any mismatch); see plan_group()")
    a = ap.parse_args()
    if a.db:
        db = a.db
    else:
        from src.utils.paths import trade_journal_db_path  # noqa: PLC0415
        db = str(trade_journal_db_path())
    if a.fills_db:
        fills = a.fills_db
    else:
        from src.runtime.exchange_fills_store import get_fills_db_path  # noqa: PLC0415
        fills = str(get_fills_db_path())
    ids = [int(x) for x in a.ids.split(",") if x.strip()] if a.ids else None
    if a.group and (not ids or len(ids) < 2):
        print("refusing --group without --ids naming >= 2 rows", file=sys.stderr)
        return 2
    if a.apply and not ids:
        print("refusing --apply without --ids: name the rows you are repricing", file=sys.stderr)
        return 2
    if not os.path.exists(db):
        print(f"error: db not found at {db}", file=sys.stderr)
        return 2
    return run(db, fills, apply=a.apply, ids=ids, group=a.group)


if __name__ == "__main__":
    sys.exit(main())
