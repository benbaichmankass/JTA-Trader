#!/usr/bin/env python3
"""Backfill partial-close child rows + the exit they corrupted (PARTIAL-CLOSE-PNL-NOT-JOURNALED).

Applies the committed, venue-verified plan
``docs/research/evidence/partial-close-backfill-plan-2026-11-12.json``:

* ``partial_children``: one closed ``setup_type='partial_close'`` child row per TRUE partial
  close, written through ``src.runtime.partial_close_journal.book_partial_close`` (the same
  writer the live path uses; idempotent per close order, the parent is NOT shrunk again
  because its ``position_size`` already holds the remainder);
* ``exit_corrections``: a row whose exit the demo pending-pnl read took from another order's
  fill gets its OWN order's fill as ``exit_price`` and ``pnl`` (local compute net of that
  fill's fees), with the prior values kept in ``notes.backfill_partial_close``.

Every item is RE-VERIFIED on the VM before it is written, against the exchange-fills store
(by venue order id: qty within 1%, vwap within 0.1%). An item the store cannot confirm is
reported ``could_not_verify`` and NOT written. Nothing is estimated.

DRY-RUN by default: prints each item's verdict and the exact before/after. ``--apply`` writes
(the system-action wrapper takes a DB backup first). Idempotent. No venue call, no service.

Usage:
  backfill_partial_close_children.py --db PATH --fills-db PATH [--plan FILE] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEFAULT_PLAN = ROOT / "docs/research/evidence/partial-close-backfill-plan-2026-11-12.json"
QTY_TOL = 0.01
PX_TOL = 0.001


class _DB:
    """The minimal Database surface ``book_partial_close`` needs, on an explicit path."""

    def __init__(self, path: str):
        self.path = path

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def insert_trade(self, row: Dict[str, Any]) -> int:
        from src.units.db.database import Database
        return Database(self.path).insert_trade(row)

    def update_trade(self, tid: int, upd: Dict[str, Any]):
        from src.units.db.database import Database
        return Database(self.path).update_trade(tid, upd)


def _store_fill(fconn, account: str, order_id: str) -> Optional[Dict[str, float]]:
    rows = fconn.execute(
        "SELECT price, qty, fee FROM exchange_fills WHERE account_id = ? AND order_id = ?",
        (account, order_id)).fetchall()
    q = sum(float(r[1] or 0) for r in rows)
    if not rows or q <= 0:
        return None
    return {"qty": q, "vwap": sum(float(r[0]) * float(r[1]) for r in rows) / q,
            "fees": sum(float(r[2] or 0) for r in rows)}


def _agrees(store: Dict[str, float], qty: float, px: float) -> bool:
    return abs(store["qty"] - qty) <= QTY_TOL * qty and abs(store["vwap"] - px) <= PX_TOL * px


def plan_items(db: _DB, fconn, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    conn = db.connect()
    try:
        for it in plan.get("partial_children") or []:
            tid, oid = int(it["trade_id"]), str(it["close_order_id"])
            parent = conn.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()
            done = conn.execute(
                "SELECT id FROM trades WHERE setup_type = 'partial_close' AND broker_order_id = ?",
                (oid,)).fetchone()
            store = _store_fill(fconn, str(it["account"]), oid) if fconn else None
            v = {"kind": "partial_child", "trade_id": tid, "close_order_id": oid,
                 "qty": float(it["fill_qty"]), "fill_price": float(it["fill_price"]),
                 "filled_at": it.get("filled_at")}
            if parent is None:
                v["verdict"] = "no_parent_row"
            elif done is not None:
                v["verdict"] = "already_booked"
            elif store is None:
                v["verdict"] = "could_not_verify"
            elif not _agrees(store, v["qty"], v["fill_price"]):
                v.update(verdict="store_disagrees", store=store)
            else:
                v.update(verdict="write", fees=store["fees"],
                         pnl_preview=round((float(parent["entry_price"]) - v["fill_price"]) * v["qty"]
                                           * (1 if parent["direction"] == "short" else -1)
                                           - store["fees"], 4))
            out.append(v)
        for it in plan.get("exit_corrections") or []:
            tid, oid = int(it["trade_id"]), str(it["own_order_id"])
            row = conn.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()
            store = _store_fill(fconn, str(it["account"]), oid) if fconn else None
            v = {"kind": "exit_correction", "trade_id": tid, "own_order_id": oid,
                 "to_exit_price": float(it["to_exit_price"])}
            if row is None:
                v["verdict"] = "no_row"
            elif abs(float(row["exit_price"] or 0) - float(it["from_exit_price"])) > 1e-9:
                v.update(verdict="row_changed", exit_price_now=row["exit_price"])
            elif store is None:
                v["verdict"] = "could_not_verify"
            elif not _agrees(store, float(row["position_size"]), v["to_exit_price"]):
                v.update(verdict="store_disagrees", store=store)
            else:
                from src.runtime.local_pnl import compute_realized_pnl, contract_value_usd_for
                gross = compute_realized_pnl(
                    entry_price=float(row["entry_price"]), exit_price=store["vwap"],
                    qty=float(row["position_size"]), direction=row["direction"],
                    contract_value_usd=contract_value_usd_for(row["symbol"]))
                v.update(verdict="write", from_exit_price=row["exit_price"], from_pnl=row["pnl"],
                         to_exit_price=round(store["vwap"], 10),
                         to_pnl=round(gross - store["fees"], 4), close_fees_usd=store["fees"])
            out.append(v)
    finally:
        conn.close()
    return out


def apply_items(db: _DB, items: List[Dict[str, Any]]) -> int:
    from src.runtime.partial_close_journal import book_partial_close
    from src.utils.json_notes import dump_capped

    n = 0
    for v in items:
        if v.get("verdict") != "write":
            continue
        if v["kind"] == "partial_child":
            r = book_partial_close(
                db, parent_trade_id=v["trade_id"], qty=v["qty"], fill_price=v["fill_price"],
                filled_at=v.get("filled_at"), close_order_id=v["close_order_id"],
                source="backfill_partial_close", reason="partial_close", fees_usd=v.get("fees") or 0.0,
                shrink_parent=False)
            v["result"] = r
            n += r.get("state") == "booked"
        else:
            conn = db.connect()
            try:
                row = conn.execute("SELECT notes FROM trades WHERE id = ?", (v["trade_id"],)).fetchone()
                notes = json.loads((row and row[0]) or "{}")
            finally:
                conn.close()
            notes["backfill_partial_close"] = {"from_exit_price": v["from_exit_price"],
                                               "from_pnl": v["from_pnl"], "own_order_id": v["own_order_id"]}
            notes["exit_price_source"] = "exchange_fill"
            notes["close_fees_usd"] = v["close_fees_usd"]
            w = sqlite3.connect(db.path)
            try:
                cur = w.execute(
                    "UPDATE trades SET exit_price = ?, pnl = ?, notes = ? "  # writer-conformance: allow one-shot operator backfill guarded on the prior exit price
                    " WHERE id = ? AND exit_price = ?",
                    (v["to_exit_price"], v["to_pnl"], dump_capped(notes, 500),
                     v["trade_id"], v["from_exit_price"]))
                w.commit()
                v["result"] = {"updated": cur.rowcount}
                n += cur.rowcount
            finally:
                w.close()
    return n


def _backup(db_path: str) -> str:
    """Online SQLite backup (consistent under WAL, unlike a file copy) beside the DB."""
    from datetime import datetime, timezone
    dest = f"{db_path}.bak-partial-close-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    src = sqlite3.connect(db_path)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    return dest


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--fills-db", required=True)
    ap.add_argument("--plan", default=str(DEFAULT_PLAN))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    db = _DB(a.db)
    fpath = Path(a.fills_db)
    fconn = sqlite3.connect(f"file:{fpath}?mode=ro", uri=True) if fpath.exists() else None
    try:
        items = plan_items(db, fconn, plan)
    finally:
        if fconn:
            fconn.close()
    print(f"plan: {a.plan}")
    print(f"population: {plan.get('population')}")
    print(f"mode: {'APPLY' if a.apply else 'DRY-RUN (nothing written)'}")
    for v in items:
        print(" ", json.dumps(v, default=str))
    if a.apply:
        if any(v.get("verdict") == "write" for v in items):
            print(f"backup: {_backup(a.db)}")
        print(f"written: {apply_items(db, items)}")
        for v in items:
            if "result" in v:
                print("  result", v["trade_id"], json.dumps(v["result"], default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
