#!/usr/bin/env python3
"""Correct three alpaca_options_paper journal rows from 2026-11-25 from their VENUE fills (row-specific, one-shot).

Operator decision, 2026-11-26 popup, verbatim: "Backfill the P&L (Recommended)" -- carried out by the venue-fill method the
manager approved on 2026-11-26 (Manager Session 2026-11-26a), because the generic backfill-pnl-nulls would have written
wrong numbers (rows ALPACA-PKG-CLOSE-LEAVES-WORKING-ENTRY-1125, OCC-OPTION-MULTIPLIER-UNRESOLVED).

What happened (alpaca_options_paper order history, read 2026-11-26 via /api/diag/alpaca_order_history):
  * 8569 slv_trend_1h: a DAY mleg LIMIT entry (order f48416cd-3f29-4804-81c5-d471d518e330) worked from 15:30Z. The row
    closed at 17:11:35Z on sl_cross with no position. The entry FILLED at 18:11:05Z (net 0.40), AFTER the close, so 8569
    never held anything. Its legs were adopted as orphans 8612 / 8613 and flattened at market at 18:13Z.
  * 8612 SLV261231P00034000 short 1: sold 1.56 (entry leg), bought back 1.58 (order 4910cbab-1076-4a06-9bdd-977cece03960,
    filled 18:13:49.7526Z) -> (1.56 - 1.58) x 1 x 100 = -2.00 USD.
  * 8613 SLV261231P00035000 long 1: bought 1.96 (entry leg), sold 1.88 (order c4dfe183-6991-4b75-b434-e371812fa260,
    filled 18:13:51.947948Z) -> (1.88 - 1.96) x 1 x 100 = -8.00 USD.

What it writes (one transaction, only on --apply; dry-run prints the same plan):
  * 8612 / 8613: exit_price = the venue exit fill, pnl = the venue figure above (the 100-share contract multiplier applied
    here, because contract_value_usd_for() returns 1.0 for OCC symbols today), pnl_percent, pnl_basis 'venue_fills_net'
    (entry AND exit are venue fills), notes: exit_price_source 'exchange_fill', pnl_source 'venue_fills', exit_fill
    {order_id, filled_at}, options_correction_1125 {at, row, operator decision}.
  * 8569: exit_reason 'entry_unfilled' (true at its close: the entry had not filled), pnl stays NULL, notes:
    pnl_source 'unmeasured' (src/runtime/provenance.UNMEASURED_MARKER, the declaration INV-2 accepts),
    unmeasured_reason 'entry_unfilled', pre_mark_exit_reason (the prior label), entry_filled_after_close
    {order_id, filled_at, pnl_carried_on: [8612, 8613]}.
Refuses (writes NOTHING) unless every row matches its expected account, symbol, direction, status 'closed', size 1 and
entry price, and pnl is still NULL. A row already carrying options_correction_1125 is skipped (idempotent). Never touches
an order, a service, SL/TP or size.

Usage:
  python3 scripts/ops/correct_slv_options_rows_1125.py --db PATH            # dry-run
  python3 scripts/ops/correct_slv_options_rows_1125.py --db PATH --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ACCOUNT = "alpaca_options_paper"
MARK = "options_correction_1125"
DECISION = 'Operator decision, 2026-11-26 popup, verbatim: "Backfill the P&L (Recommended)" (venue-fill method, manager 26a)'
CONTRACT = 100.0
LEGS = {
    8612: {"symbol": "SLV261231P00034000", "direction": "short", "entry": 1.56, "exit": 1.58,
           "order_id": "4910cbab-1076-4a06-9bdd-977cece03960", "filled_at": "2026-11-25T18:13:49.7526Z", "pnl": -2.00},
    8613: {"symbol": "SLV261231P00035000", "direction": "long", "entry": 1.96, "exit": 1.88,
           "order_id": "c4dfe183-6991-4b75-b434-e371812fa260", "filled_at": "2026-11-25T18:13:51.947948Z", "pnl": -8.00},
}
PARENT = {"id": 8569, "symbol": "SLV", "direction": "short", "entry": 34.64,
          "order_id": "f48416cd-3f29-4804-81c5-d471d518e330", "filled_at": "2026-11-25T18:11:05.387939Z"}


def _notes(raw: Any) -> dict:
    try:
        n = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {"_original_notes": raw}
    return n if isinstance(n, dict) else {"_original_notes": raw}


def leg_pnl(spec: dict, qty: float) -> float:
    sign = 1.0 if spec["direction"] == "long" else -1.0
    return round((spec["exit"] - spec["entry"]) * qty * CONTRACT * sign, 8)


def plan(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    ids = [*LEGS, PARENT["id"]]
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT id, account_id, symbol, direction, status, entry_price, exit_price, position_size, pnl, exit_reason, notes "
        f"FROM trades WHERE id IN ({','.join('?' * len(ids))})", ids)}
    problems, writes, skipped = [], [], []
    for rid in ids:
        r = rows.get(rid)
        spec = LEGS.get(rid) or PARENT
        if r is None:
            problems.append(f"{rid}: row not found")
            continue
        if MARK in _notes(r["notes"]):
            skipped.append(rid)
            continue
        want = {"account_id": ACCOUNT, "symbol": spec["symbol"], "direction": spec["direction"], "status": "closed"}
        bad = {k: r[k] for k, v in want.items() if r[k] != v}
        if bad:
            problems.append(f"{rid}: expected {want}, got {bad}")
        if abs(float(r["position_size"] or 0) - 1.0) > 1e-9:
            problems.append(f"{rid}: position_size {r['position_size']} != 1")
        if r["entry_price"] is None or abs(float(r["entry_price"]) - spec["entry"]) > 1e-9:
            problems.append(f"{rid}: entry_price {r['entry_price']} != {spec['entry']}")
        if r["pnl"] is not None:
            problems.append(f"{rid}: pnl already {r['pnl']} (not NULL)")
        if rid in LEGS:
            if leg_pnl(spec, 1.0) != spec["pnl"]:
                problems.append(f"{rid}: arithmetic {leg_pnl(spec, 1.0)} != stated {spec['pnl']}")
            writes.append({"id": rid, "kind": "leg", "prior_exit": r["exit_price"], "exit": spec["exit"], "pnl": spec["pnl"],
                           "pnl_percent": round(spec["pnl"] / (spec["entry"] * CONTRACT) * 100.0, 6), "notes": r["notes"]})
        else:
            writes.append({"id": rid, "kind": "parent", "prior_exit_reason": r["exit_reason"], "notes": r["notes"]})
    return {"problems": problems, "writes": writes, "skipped": skipped}


def apply(conn: sqlite3.Connection, p: dict, now_iso: str) -> int:
    if p["problems"]:
        raise SystemExit("refusing: " + "; ".join(p["problems"]))
    from src.runtime.provenance import UNMEASURED_MARKER
    n = 0
    with conn:
        for w in p["writes"]:
            notes = _notes(w["notes"])
            notes[MARK] = {"at": now_iso, "rows": "ALPACA-PKG-CLOSE-LEAVES-WORKING-ENTRY-1125", "decision": DECISION}
            if w["kind"] == "leg":
                spec = LEGS[w["id"]]
                notes.update({"exit_price_source": "exchange_fill", "pnl_source": "venue_fills",
                              "exit_fill": {"order_id": spec["order_id"], "filled_at": spec["filled_at"]}})
                conn.execute("UPDATE trades SET exit_price = ?, pnl = ?, pnl_percent = ?, pnl_basis = 'venue_fills_net', "
                             "notes = ? WHERE id = ? AND pnl IS NULL",
                             (spec["exit"], spec["pnl"], w["pnl_percent"], json.dumps(notes), w["id"]))
            else:
                notes.update({"pnl_source": UNMEASURED_MARKER, "unmeasured_reason": "entry_unfilled",
                              "pre_mark_exit_reason": w["prior_exit_reason"],
                              "entry_filled_after_close": {"order_id": PARENT["order_id"], "filled_at": PARENT["filled_at"],
                                                           "pnl_carried_on": sorted(LEGS)}})
                conn.execute("UPDATE trades SET exit_reason = 'entry_unfilled', notes = ? WHERE id = ? AND pnl IS NULL",
                             (json.dumps(notes), w["id"]))
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    from src.utils.paths import trade_journal_db_path
    db = a.db or str(trade_journal_db_path())
    if not Path(db).exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(db)
    try:
        p = plan(conn)
        print(f"[{'APPLY' if a.apply else 'DRY-RUN (no write)'}] db={db}")
        for w in p["writes"]:
            if w["kind"] == "leg":
                print(f"  {w['id']}: exit_price {w['prior_exit']} -> {w['exit']}; pnl NULL -> {w['pnl']:+.2f} "
                      f"(x{CONTRACT:g} contract); pnl_basis -> venue_fills_net")
            else:
                print(f"  {w['id']}: exit_reason {w['prior_exit_reason']} -> entry_unfilled; pnl stays NULL; "
                      f"notes.pnl_source -> unmeasured (P&L carried on {sorted(LEGS)})")
        print(f"  skipped (already corrected): {p['skipped']}")
        if p["problems"]:
            print("  REFUSED -- nothing will be written:")
            for x in p["problems"]:
                print(f"    {x}")
            return 1
        if a.apply:
            print(f"  APPLIED: {apply(conn, p, datetime.now(timezone.utc).isoformat())} row(s)")
        elif p["writes"]:
            print("  re-run with --apply to write.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
