#!/usr/bin/env python3
# wiring: manual-only - run by the `reopen-filled-closed-rows` system action (Tier 2, dry-run default);
#   a ONE-OFF journal repair pinned to 8 row ids, never scheduled.
"""Re-open journal rows that read CLOSED while their entries FILLED at the venue (one-off, pinned).

PI-20261118-JFWRQYOV-0004 (alpaca_portfolio SLV, 2026-11-18). The pre-open re-entry loop placed seven
bracket SELL orders 13:03-13:47Z. The reconciler closed each journal row (exit_reason
``exchange_flat_reconciled``) before its order filled, and every one of them then filled at the venue:
794 + 53 + 2 + 19 + 2 + 2 + 5 = 877 = the venue position, each protected by its own bracket. Row 7784
(6 sh, open) has no venue order at all: a phantom. The reconciler logs ``venue 877 exceeds the journal's
open rows (6) by 871`` every pass. Decision: manager 2026-11-19 ~00:24Z (option a: the venue is the truth;
re-open the rows with their real fills), GO on this action ~01:02Z.

WHAT IT DOES (only after every check passes)
  * each REOPEN row: status closed -> open; closed_at, exit_reason -> NULL; entry_price -> the venue's
    filled_avg_price; its order package status -> open, close_reason -> NULL. Prior values are kept under
    ``notes.reopen_repair`` / ``meta.reopen_repair``.
  * the PHANTOM row: status open -> closed, exit_reason ``never_filled_phantom``, reconcile_status
    ``superseded`` (excluded from analytics, kept for audit), pnl stays NULL (UNMEASURED: nothing filled).
WHAT IT REFUSES (writes nothing): any row whose live values differ from the pinned signature; a reopen row
whose broker_order_id is not a FILLED SELL order of exactly its size in the venue history; a phantom that
does have a venue order; a venue position that is not SLV short 877; an unreadable payload.
It places, modifies and cancels NOTHING at any venue.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ACCOUNT = "alpaca_portfolio"
SYMBOL = "SLV"
DIRECTION = "short"
VENUE_SIZE = 877.0
#: row id -> (position_size, broker_order_id) as read 2026-11-19 ~01:20Z from /api/diag/journal.
REOPEN: Dict[int, Tuple[float, str]] = {
    7750: (794.0, "9c02dc76-46c2-4c69-a0b1-56dd3dbc2be7"),
    7754: (53.0, "65edd36b-a359-4b13-9f6c-980322f19f8a"),
    7758: (2.0, "c64f9ccc-cfe5-48f9-b9a1-893c82da6708"),
    7762: (19.0, "ea2cc6af-7dc7-4834-a1dd-340b38a7ab1f"),
    7766: (2.0, "aa1dff1a-d0cd-45b8-87bd-98426916d19b"),
    7770: (2.0, "51f4045b-338d-4b3b-afb4-3a1c92fb1159"),
    7774: (5.0, "1dd31562-6df7-49de-8ded-37e806c5de8e"),
}
PHANTOM: Dict[int, float] = {7784: 6.0}
REOPEN_FROM_EXIT = "exchange_flat_reconciled"


class Refused(Exception):
    pass


def _orders(history: Any) -> List[Dict[str, Any]]:
    if not isinstance(history, dict):
        raise Refused("order history payload is not an object")
    res = history.get("result") if isinstance(history.get("result"), dict) else history
    orders = res.get("orders") if isinstance(res, dict) else None
    if history.get("read_state") not in (None, "orders_read") or not isinstance(orders, list) or not orders:
        raise Refused(f"order history unreadable or empty (read_state={history.get('read_state')!r})")
    return orders


def _venue_size(positions: Any) -> float:
    if not isinstance(positions, dict) or not isinstance(positions.get("accounts"), list):
        raise Refused("positions payload has no accounts list")
    for a in positions["accounts"]:
        if a.get("account_id") != ACCOUNT:
            continue
        if a.get("read_state") != "ok":
            raise Refused(f"{ACCOUNT} positions unreadable (read_state={a.get('read_state')!r})")
        size = 0.0
        for p in a.get("positions") or []:
            if str(p.get("symbol")).upper() == SYMBOL and str(p.get("side")).lower() == DIRECTION:
                size += float(p.get("size") or 0)
        return size
    raise Refused(f"{ACCOUNT} absent from the positions payload (could not look; not 'flat')")


def plan(conn: sqlite3.Connection, history: Any, positions: Any) -> Dict[str, Any]:
    """The full diff, or Refused. Pure apart from reads."""
    orders = {str(o.get("order_id")): o for o in _orders(history)}
    vsize = _venue_size(positions)
    if abs(vsize - VENUE_SIZE) > 1e-9:
        raise Refused(f"venue {SYMBOL} {DIRECTION} size is {vsize}, not the pinned {VENUE_SIZE}: the book moved")
    if abs(sum(s for s, _ in REOPEN.values()) - VENUE_SIZE) > 1e-9:
        raise Refused("pinned reopen sizes do not sum to the venue size")
    conn.row_factory = sqlite3.Row
    ids = list(REOPEN) + list(PHANTOM)
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT * FROM trades WHERE id IN ({','.join('?' * len(ids))})", ids)}
    out: Dict[str, Any] = {"reopen": [], "phantom": [], "venue_size": vsize}
    for rid, (size, boid) in REOPEN.items():
        r = rows.get(rid)
        if r is None:
            raise Refused(f"row {rid} not found")
        sig = (r["account_id"], r["symbol"], r["direction"], float(r["position_size"] or 0), r["status"],
               r["exit_reason"], r["broker_order_id"])
        want = (ACCOUNT, SYMBOL, DIRECTION, size, "closed", REOPEN_FROM_EXIT, boid)
        if sig != want:
            raise Refused(f"row {rid} signature {sig} != pinned {want} (already repaired, or it moved)")
        o = orders.get(boid)
        if o is None:
            raise Refused(f"row {rid}: broker order {boid} is not in the venue history")
        filled = float(o.get("filled_qty") or 0)
        if str(o.get("status")) != "filled" or str(o.get("side")).lower() != "sell" or abs(filled - size) > 1e-9:
            raise Refused(f"row {rid}: venue order {boid} is {o.get('status')}/{o.get('side')} filled {filled}, "
                          f"not a filled SELL of {size}")
        pkg = conn.execute("SELECT status, close_reason, meta FROM order_packages WHERE order_package_id = ?",
                           (r["order_package_id"],)).fetchone()
        out["reopen"].append({"id": rid, "size": size, "broker_order_id": boid,
                              "entry_price_before": r["entry_price"],
                              "entry_price_after": float(o.get("filled_avg_price")),
                              "closed_at_before": r["closed_at"], "package": r["order_package_id"],
                              "package_status_before": pkg["status"] if pkg else None,
                              "package_close_reason_before": pkg["close_reason"] if pkg else None})
    boids_sold = {str(o.get("order_id")) for o in orders.values()}
    for rid, size in PHANTOM.items():
        r = rows.get(rid)
        if r is None:
            raise Refused(f"phantom row {rid} not found")
        sig = (r["account_id"], r["symbol"], r["direction"], float(r["position_size"] or 0), r["status"])
        if sig != (ACCOUNT, SYMBOL, DIRECTION, size, "open"):
            raise Refused(f"phantom row {rid} signature {sig} moved")
        if r["broker_order_id"] and str(r["broker_order_id"]) in boids_sold:
            raise Refused(f"phantom row {rid} has a venue order {r['broker_order_id']}: not a phantom")
        out["phantom"].append({"id": rid, "size": size, "package": r["order_package_id"]})
    return out


def _merge_json(raw: Optional[str], key: str, value: Dict[str, Any]) -> str:
    try:
        doc = json.loads(raw) if raw else {}
    except ValueError:
        doc = {"_unparseable_prior": raw}
    if not isinstance(doc, dict):
        doc = {"_prior": doc}
    doc[key] = value
    return json.dumps(doc, sort_keys=True)


def apply(conn: sqlite3.Connection, p: Dict[str, Any], now: str) -> None:
    with conn:
        for r in p["reopen"]:
            notes = conn.execute("SELECT notes FROM trades WHERE id = ?", (r["id"],)).fetchone()[0]
            conn.execute(
                "UPDATE trades SET status='open', closed_at=NULL, exit_reason=NULL, entry_price=?, notes=? "
                "WHERE id=? AND status='closed'",
                (r["entry_price_after"], _merge_json(notes, "reopen_repair", {
                    "at": now, "why": "PI-20261118-JFWRQYOV-0004: closed before its entry filled; the venue filled it",
                    "prior": {"status": "closed", "exit_reason": REOPEN_FROM_EXIT, "closed_at": r["closed_at_before"],
                              "entry_price": r["entry_price_before"]},
                    "venue_order_id": r["broker_order_id"]}), r["id"]))
            if r["package"] and r["package_status_before"] == "closed":
                meta = conn.execute("SELECT meta FROM order_packages WHERE order_package_id = ?",
                                    (r["package"],)).fetchone()[0]
                conn.execute("UPDATE order_packages SET status='open', close_reason=NULL, updated_at=?, meta=? "
                             "WHERE order_package_id=?",
                             (now, _merge_json(meta, "reopen_repair", {
                                 "at": now, "prior": {"status": "closed", "close_reason": r["package_close_reason_before"]}}),
                              r["package"]))
        for r in p["phantom"]:
            notes = conn.execute("SELECT notes FROM trades WHERE id = ?", (r["id"],)).fetchone()[0]
            conn.execute(
                "UPDATE trades SET status='closed', closed_at=?, exit_reason='never_filled_phantom', "
                "reconcile_status='superseded', notes=? WHERE id=? AND status='open'",
                (now, _merge_json(notes, "phantom_close", {
                    "at": now, "why": "PI-20261118-JFWRQYOV-0004: no venue order; the venue's 877 is the 7 reopened rows",
                    "pnl": "NULL (UNMEASURED: nothing filled)"}), r["id"]))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--order-history", required=True, help="/api/diag/alpaca_order_history payload (alpaca_portfolio SLV)")
    ap.add_argument("--positions", required=True, help="/api/diag/exchange_positions payload")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        history = json.loads(Path(a.order_history).read_text())
        positions = json.loads(Path(a.positions).read_text())
    except (OSError, ValueError) as exc:
        print(f"REFUSED: payload unreadable: {exc}")
        return 2
    conn = sqlite3.connect(a.db)
    try:
        p = plan(conn, history, positions)
    except Refused as exc:
        print(f"REFUSED (nothing written): {exc}")
        return 3
    print(json.dumps(p, indent=2, sort_keys=True))
    if not a.apply:
        print("DRY RUN: nothing written (pass --apply to write)")
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    backup = f"{a.db}.bak-reopen-{now.replace(':', '')}"
    conn.close()
    shutil.copy2(a.db, backup)
    conn = sqlite3.connect(a.db)
    apply(conn, plan(conn, history, positions), now)
    print(f"APPLIED at {now}; backup {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
