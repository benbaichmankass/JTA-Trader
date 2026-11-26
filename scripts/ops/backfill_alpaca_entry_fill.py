#!/usr/bin/env python3
"""Backfill ``trades.entry_price`` on Alpaca rows that booked the PACKAGE price because the entry filled late.

ALPACA-ENTRY-FILL-PRICE-UNSYNCED (2026-11-26, MEASURED). ``AlpacaClient.place`` reads the entry fill only inside its
``ALPACA_PLACE_CONFIRM_S`` (3 s) confirm poll. An entry that filled later kept the package's signal price as
``entry_price``, and nothing corrected it. The row's P&L was still labelled ``venue_fills_net`` (its exit is a venue
fill), and ``pnl_computed`` used the same entry, so ``pnl_gap_usd`` read 0. Measured over 65 Alpaca stock entries
2026-11-09..11-25: 15 had journal entry != venue ``filled_avg_price``, every one filled 3.5 s or more after submit, net
+1,471.86 USD journal-minus-venue P&L. The forward fix (same PR) makes the monitor's entry sweep read those fills; this
one-shot corrects the history.

Population (the script prints every row it would touch, with its old and venue entry and P&L delta):
  Alpaca accounts (``config/accounts.yaml`` exchange ``alpaca``), non-backtest rows with a ``broker_order_id``,
  ``notes.entry_price_source`` absent or ``plan`` (a venue-labelled entry is never touched), opened within
  ``--days`` (default 30), whose entry order reads ``filled`` with ``filled_qty`` equal to the row's size (2 % tol,
  the sweep's rule) and a ``filled_avg_price`` that differs from ``entry_price``.

Per row, on ``--apply`` (one UPDATE per row, in one transaction):
  * ``entry_price`` = the entry order's ``filled_avg_price``; ``notes.package_entry`` keeps the old value;
    ``notes.entry_price_source`` = ``alpaca_order_status``; ``notes.entry_fill_backfill`` records when and why;
  * closed rows: ``pnl`` -= delta where delta = (venue entry - old entry) x qty x side sign (the entry moves for the
    whole size, so the change is linear); ``notes.pnl_prior`` keeps the old figure; ``pnl_percent`` is recomputed;
    ``pnl_basis`` / ``pnl_computed`` / ``pnl_gap_usd`` are cleared so the monitor's venue sweep re-classifies the row
    with the corrected entry (rows older than its 7-day scan stay unclassified, which net-R readers treat as gross
    minus the row's own costs -- zero for Alpaca equities);
  * open rows: entry_price + notes only.
Never places, amends or cancels an order; never touches SL/TP, size, status or any service. Idempotent: a row it
corrected carries ``entry_price_source = alpaca_order_status`` and is skipped on a re-run. Dry-run by default.

Usage:
  python scripts/ops/backfill_alpaca_entry_fill.py                 # dry-run (reads Alpaca, writes nothing)
  python scripts/ops/backfill_alpaca_entry_fill.py --apply
  python scripts/ops/backfill_alpaca_entry_fill.py --db PATH --days 30
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

QTY_TOL = 0.02
SOURCE = "alpaca_order_status"
ROW_KEY = "ALPACA-ENTRY-FILL-PRICE-UNSYNCED"


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def plan_rows(conn: sqlite3.Connection, alpaca_accounts: dict[str, dict[str, Any]],
              read_order: Callable[[dict[str, Any], str], dict[str, Any] | None], days: int) -> dict[str, Any]:
    """Every candidate with its decision. ``read_order(cfg, oid)`` returns the order dict
    (``status``, ``filled_qty``, ``filled_avg_price``), ``{"read_state": "not_found"}``, or ``None`` (could not look)."""
    conn.row_factory = sqlite3.Row
    accts = sorted(alpaca_accounts)
    if not accts:
        return {"rows": [], "could_not_look": 0, "scanned": 0}
    q = ("SELECT id, account_id, symbol, direction, entry_price, position_size, status, pnl, notes, broker_order_id "
         "  FROM trades WHERE COALESCE(is_backtest, 0) = 0 AND broker_order_id IS NOT NULL "
         f"  AND account_id IN ({','.join('?' * len(accts))}) "
         "  AND datetime(COALESCE(created_at, timestamp)) >= datetime('now', ?) ORDER BY id")
    rows = [dict(r) for r in conn.execute(q, (*accts, f"-{int(days)} days")).fetchall()]
    out: list[dict[str, Any]] = []
    blind = 0
    for r in rows:
        try:
            notes = json.loads(r["notes"]) if r.get("notes") else {}
        except (TypeError, ValueError):
            notes = {}
        if not isinstance(notes, dict):
            notes = {}
        src = notes.get("entry_price_source")
        if src not in (None, "plan"):
            continue                                   # a venue-labelled entry is never touched
        got = read_order(alpaca_accounts[r["account_id"]], str(r["broker_order_id"]))
        rec = {"id": r["id"], "account_id": r["account_id"], "symbol": r["symbol"], "direction": r["direction"],
               "status": r["status"], "qty": _f(r["position_size"]), "old_entry": _f(r["entry_price"]),
               "venue_entry": None, "pnl_delta": None, "action": "skip", "why": ""}
        if got is None:
            blind += 1
            rec["why"] = "could_not_look"
        elif got.get("read_state") == "not_found":
            rec["why"] = "entry_order_not_found"
        else:
            avg, fq, st = _f(got.get("filled_avg_price")), _f(got.get("filled_qty")), str(got.get("status") or "")
            qty = rec["qty"] or 0.0
            if st != "filled" or not avg or avg <= 0:
                rec["why"] = f"entry_order_{st or 'unknown'}"
            elif qty <= 0 or fq is None or abs(fq - qty) / qty > QTY_TOL:
                rec["why"] = "entry_order_qty_mismatch"
            elif rec["old_entry"] is not None and abs(avg - rec["old_entry"]) <= 1e-9 * max(1.0, avg):
                rec["why"] = "already_equal"
            else:
                sign = 1.0 if str(r["direction"]).lower() == "long" else -1.0
                rec.update(venue_entry=avg, action="write", why="late_fill",
                           pnl_delta=(avg - (rec["old_entry"] or 0.0)) * qty * sign)
        out.append(rec)
    return {"rows": out, "could_not_look": blind, "scanned": len(rows)}


def apply_rows(conn: sqlite3.Connection, plan: dict[str, Any], now_iso: str) -> int:
    from src.runtime.local_pnl import compute_pnl_percent, contract_value_usd_for
    from src.utils.json_notes import dump_capped
    n = 0
    for p in plan["rows"]:
        if p["action"] != "write":
            continue
        cur = conn.execute("SELECT entry_price, pnl, notes, status, symbol, position_size FROM trades WHERE id = ?",
                           (p["id"],)).fetchone()
        if cur is None:
            continue
        old_entry, old_pnl, raw, status, symbol, qty = cur
        try:
            notes = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            notes = {}
        if not isinstance(notes, dict) or notes.get("entry_price_source") not in (None, "plan"):
            continue                                   # changed since the plan was read: leave it
        notes["package_entry"] = _f(old_entry)
        notes["entry_price_source"] = SOURCE
        notes.pop("entry_price_source_reason", None)
        notes["entry_fill_backfill"] = {"at": now_iso, "row": ROW_KEY, "from": _f(old_entry), "to": p["venue_entry"]}
        sets: dict[str, Any] = {"entry_price": p["venue_entry"]}
        if status == "closed" and _f(old_pnl) is not None:
            new_pnl = round(_f(old_pnl) - p["pnl_delta"], 8)
            notes["pnl_prior"] = _f(old_pnl)
            sets.update(pnl=new_pnl, pnl_basis=None, pnl_computed=None, pnl_gap_usd=None)
            pct = compute_pnl_percent(pnl=new_pnl, entry_price=p["venue_entry"], qty=_f(qty),
                                      contract_value_usd=contract_value_usd_for(symbol))
            if pct is not None:
                sets["pnl_percent"] = pct
        sets["notes"] = dump_capped(notes, max(2000, len(raw or "")))
        cols = ", ".join(f"{k} = ?" for k in sets)
        conn.execute(f"UPDATE trades SET {cols} WHERE id = ?", (*sets.values(), p["id"]))
        n += 1
    conn.commit()
    return n


def _alpaca_accounts() -> dict[str, dict[str, Any]]:
    import yaml
    root = Path(__file__).resolve().parents[2]
    doc = yaml.safe_load((root / "config" / "accounts.yaml").read_text()) or {}
    accts = doc.get("accounts", doc)
    out = {}
    for aid, cfg in (accts.items() if isinstance(accts, dict) else []):
        if isinstance(cfg, dict) and str(cfg.get("exchange") or "").lower() == "alpaca" \
                and "options" not in str(aid):        # options rows journal the underlying, not the contract fill
            out[str(aid)] = {**cfg, "account_id": str(aid)}
    return out


def _live_reader(cfg: dict[str, Any], oid: str) -> dict[str, Any] | None:
    from src.units.accounts.clients import account_alpaca_order_history
    try:
        res = account_alpaca_order_history(cfg, order_ids=[oid])
    except ValueError:
        return {"read_state": "not_found"}
    if not isinstance(res, dict):
        return None
    hit = (res.get("by_id") or {}).get(oid) or {}
    if hit.get("read_state") == "not_found":
        return {"read_state": "not_found"}
    return hit.get("order") if hit.get("read_state") == "order_read" else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    from src.utils.paths import trade_journal_db_path
    db = a.db or str(trade_journal_db_path())
    if not Path(db).exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 2
    accounts = _alpaca_accounts()
    conn = sqlite3.connect(db)
    try:
        plan = plan_rows(conn, accounts, _live_reader, a.days)
        writes = [p for p in plan["rows"] if p["action"] == "write"]
        print(f"[{'APPLY' if a.apply else 'DRY-RUN (no write)'}] db={db} accounts={sorted(accounts)} days={a.days}")
        print(f"  rows scanned: {plan['scanned']}  candidates (entry source plan/unlabelled): {len(plan['rows'])}"
              f"  could_not_look: {plan['could_not_look']}  would write: {len(writes)}")
        print("  id | account | symbol | side | status | qty | journal entry -> venue entry | pnl delta USD (journal - venue)")
        for p in writes:
            print(f"  {p['id']} | {p['account_id']} | {p['symbol']} | {p['direction']} | {p['status']} | {p['qty']:g} | "
                  f"{p['old_entry']} -> {p['venue_entry']} | {p['pnl_delta']:+.2f}")
        print(f"  net pnl delta: {sum(p['pnl_delta'] for p in writes):+.2f}  abs: {sum(abs(p['pnl_delta']) for p in writes):.2f}")
        skipped: dict[str, int] = {}
        for p in plan["rows"]:
            if p["action"] != "write":
                skipped[p["why"]] = skipped.get(p["why"], 0) + 1
        print(f"  skipped by reason: {json.dumps(skipped, sort_keys=True)}")
        if plan["could_not_look"]:
            print("  NOTE: some orders could not be read; those rows are untouched and a re-run will retry them.")
        if a.apply:
            n = apply_rows(conn, plan, datetime.now(timezone.utc).isoformat())
            print(f"  APPLIED: {n} row(s) updated")
        elif writes:
            print("  re-run with --apply to write.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
