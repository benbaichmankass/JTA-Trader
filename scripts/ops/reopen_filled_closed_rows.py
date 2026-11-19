#!/usr/bin/env python3
# wiring: manual-only - run by the `reopen-filled-closed-rows` system action (Tier 2, dry-run default);
#   a journal repair driven by ONE committed spec per (account, symbol), never scheduled.
"""Re-open journal rows that read CLOSED while their entries FILLED at the venue (spec-driven).

PI-20261118-JFWRQYOV-0004. The reconciler closed journal rows (exit_reason ``exchange_flat_reconciled``)
while their bracket entry orders were still queued (pre-open / after-close). Every one of those orders then
filled at the venue, netting into one position the journal no longer knows. Cases: alpaca_portfolio SLV
(877 sh; applied 2026-11-19 04:04Z, spec ``alpaca_portfolio__SLV.json``) and alpaca_paper QQQ (1981 sh,
spec ``alpaca_paper__QQQ.json``). Root-cause fix: PR #27151.

THE SPEC (``comms/ops/reopen_specs/<account>__<symbol>.json``, reviewed in git before any apply)::

    {"account": "...", "symbol": "...", "direction": "short"|"long", "venue_qty": 1981,
     "reopen":    [{"id": 7712, "size": 1182, "broker_order_id": "..."}, ...],
     "keep_open": [{"id": 7783, "size": 2,    "broker_order_id": "..."}],     # already open, counted
     "phantom":   [{"id": 7784, "size": 6}],                                   # open, never filled
     "decision": "who decided, when", "why": "..."}

WHAT IT DOES (only after every check passes)
  * each REOPEN row: status closed -> open; closed_at, exit_reason -> NULL; entry_price -> the venue's
    filled_avg_price; its order package status -> open, close_reason -> NULL. Prior values are kept under
    ``notes.reopen_repair`` / ``meta.reopen_repair``.
  * each PHANTOM row: status open -> closed, exit_reason ``never_filled_phantom``, reconcile_status
    ``superseded`` (excluded from analytics, kept for audit), pnl stays NULL (UNMEASURED: nothing filled).
  * KEEP_OPEN rows are verified and counted, never written.
WHAT IT REFUSES (writes nothing): a spec that is malformed or names another account/symbol than asked; a row
id listed twice; any row whose live values differ from the spec (account, symbol, direction, size, status,
exit_reason for reopen rows, broker_order_id); a reopen/keep-open row whose broker order is not a FILLED
entry-side order (SELL for short, BUY for long) of exactly its size in the venue history; a phantom that
does have a venue order; reopen + keep_open sizes that do not sum to ``venue_qty``; a venue position that
is not exactly ``venue_qty`` on that side; an unreadable payload ("could not look" is never "flat").
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

SPEC_DIR = Path(__file__).resolve().parents[2] / "comms" / "ops" / "reopen_specs"
REOPEN_FROM_EXIT = "exchange_flat_reconciled"
_ENTRY_SIDE = {"short": "sell", "long": "buy"}


class Refused(Exception):
    pass


def _num(x: Any, what: str) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise Refused(f"spec: {what} is not a number ({x!r})")
    if v <= 0:
        raise Refused(f"spec: {what} must be > 0 ({v})")
    return v


def load_spec(raw: Any, account: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
    """Validate a spec document. Returns a normalised copy, or Refused."""
    if not isinstance(raw, dict):
        raise Refused("spec is not an object")
    acct, sym, direction = raw.get("account"), raw.get("symbol"), str(raw.get("direction") or "").lower()
    if not isinstance(acct, str) or not acct or not isinstance(sym, str) or not sym:
        raise Refused("spec: account and symbol are required")
    if account is not None and acct != account:
        raise Refused(f"spec account {acct!r} != requested {account!r}")
    if symbol is not None and sym.upper() != symbol.upper():
        raise Refused(f"spec symbol {sym!r} != requested {symbol!r}")
    if direction not in _ENTRY_SIDE:
        raise Refused(f"spec: direction must be short|long ({direction!r})")
    out: Dict[str, Any] = {"account": acct, "symbol": sym.upper(), "direction": direction,
                           "venue_qty": _num(raw.get("venue_qty"), "venue_qty"),
                           "decision": raw.get("decision"), "why": raw.get("why")}
    seen: set = set()
    for key, needs_order in (("reopen", True), ("keep_open", True), ("phantom", False)):
        items = raw.get(key) or []
        if not isinstance(items, list):
            raise Refused(f"spec: {key} must be a list")
        norm = []
        for it in items:
            if not isinstance(it, dict) or not isinstance(it.get("id"), int):
                raise Refused(f"spec: {key} entry needs an integer id ({it!r})")
            if it["id"] in seen:
                raise Refused(f"spec: row {it['id']} listed twice")
            seen.add(it["id"])
            e = {"id": it["id"], "size": _num(it.get("size"), f"{key} {it['id']} size")}
            if needs_order:
                boid = it.get("broker_order_id")
                if not isinstance(boid, str) or not boid.strip():
                    raise Refused(f"spec: {key} {it['id']} needs a broker_order_id")
                e["broker_order_id"] = boid.strip()
            norm.append(e)
        out[key] = norm
    if not out["reopen"] and not out["phantom"]:
        raise Refused("spec: nothing to repair (no reopen and no phantom rows)")
    counted = sum(e["size"] for e in out["reopen"]) + sum(e["size"] for e in out["keep_open"])
    if abs(counted - out["venue_qty"]) > 1e-9:
        raise Refused(f"spec: reopen + keep_open sizes sum to {counted}, not venue_qty {out['venue_qty']}")
    return out


def _orders(history: Any) -> Tuple[Dict[str, Dict[str, Any]], Optional[set]]:
    """order_id -> order, from either payload shape of /api/diag/alpaca_order_history.

    ``order_ids=`` lookups (what the action captures) answer per id in ``result.by_id``: ``order_read`` is
    kept, ``not_found`` is absent, and anything else (``could_not_look``) refuses, because a row we could not
    look up is never evidence either way. A list read (``result.orders``) is accepted too. Returns
    ``(orders, looked_up)``; ``looked_up`` is the set of ids the by-id read answered for (None for a list).
    """
    if not isinstance(history, dict):
        raise Refused("order history payload is not an object")
    if history.get("read_state") not in (None, "orders_read"):
        raise Refused(f"order history unreadable (read_state={history.get('read_state')!r})")
    res = history.get("result") if isinstance(history.get("result"), dict) else history
    out: Dict[str, Dict[str, Any]] = {}
    by_id = res.get("by_id") if isinstance(res, dict) else None
    if isinstance(by_id, dict) and by_id:
        for oid, entry in by_id.items():
            st = entry.get("read_state") if isinstance(entry, dict) else None
            if st == "order_read" and isinstance(entry.get("order"), dict):
                out[str(oid)] = entry["order"]
            elif st != "not_found":
                raise Refused(f"order {oid}: venue lookup read_state={st!r} (could not look)")
        return out, {str(k) for k in by_id}
    orders = res.get("orders") if isinstance(res, dict) else None
    if not isinstance(orders, list) or not orders:
        raise Refused("order history has neither by_id lookups nor an order list")
    return {str(o.get("order_id")): o for o in orders}, None


def _real_order_id(oid: Any) -> bool:
    s = str(oid or "").strip()
    return bool(s) and not s.startswith(("rejected-", "exchange_rejected-", "dry-"))


def lookup_ids(conn: sqlite3.Connection, spec: Dict[str, Any]) -> List[str]:
    """Every order id the capture must look up: reopen + keep_open entries, plus each phantom row's own
    broker_order_id (read from the journal) so its absence at the venue is LOOKED AT, not assumed."""
    ids = [e["broker_order_id"] for k in ("reopen", "keep_open") for e in spec[k]]
    for e in spec["phantom"]:
        row = conn.execute("SELECT broker_order_id FROM trades WHERE id = ?", (e["id"],)).fetchone()
        if row and _real_order_id(row[0]):
            ids.append(str(row[0]))
    return ids


def _venue_size(positions: Any, spec: Dict[str, Any]) -> float:
    if not isinstance(positions, dict) or not isinstance(positions.get("accounts"), list):
        raise Refused("positions payload has no accounts list")
    for a in positions["accounts"]:
        if a.get("account_id") != spec["account"]:
            continue
        if a.get("read_state") != "ok":
            raise Refused(f"{spec['account']} positions unreadable (read_state={a.get('read_state')!r})")
        size = 0.0
        for p in a.get("positions") or []:
            if (str(p.get("symbol")).upper() == spec["symbol"]
                    and str(p.get("side")).lower() == spec["direction"]):
                size += float(p.get("size") or 0)
        return size
    raise Refused(f"{spec['account']} absent from the positions payload (could not look; not 'flat')")


def _filled_entry(orders: Dict[str, Dict[str, Any]], rid: int, boid: str, size: float,
                  side: str) -> Dict[str, Any]:
    o = orders.get(boid)
    if o is None:
        raise Refused(f"row {rid}: broker order {boid} is not in the venue history")
    filled = float(o.get("filled_qty") or 0)
    if str(o.get("status")) != "filled" or str(o.get("side")).lower() != side or abs(filled - size) > 1e-9:
        raise Refused(f"row {rid}: venue order {boid} is {o.get('status')}/{o.get('side')} filled {filled}, "
                      f"not a filled {side.upper()} of {size}")
    return o


def plan(conn: sqlite3.Connection, spec: Dict[str, Any], history: Any, positions: Any) -> Dict[str, Any]:
    """The full diff, or Refused. Pure apart from reads."""
    orders, looked_up = _orders(history)
    vsize = _venue_size(positions, spec)
    if abs(vsize - spec["venue_qty"]) > 1e-9:
        raise Refused(f"venue {spec['symbol']} {spec['direction']} size is {vsize}, not the spec's "
                      f"{spec['venue_qty']}: the book moved")
    side = _ENTRY_SIDE[spec["direction"]]
    conn.row_factory = sqlite3.Row
    ids = [e["id"] for k in ("reopen", "keep_open", "phantom") for e in spec[k]]
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT * FROM trades WHERE id IN ({','.join('?' * len(ids))})", ids)}
    base = (spec["account"], spec["symbol"], spec["direction"])
    out: Dict[str, Any] = {"account": spec["account"], "symbol": spec["symbol"], "venue_size": vsize,
                           "reopen": [], "keep_open": [], "phantom": []}

    def _row(rid: int) -> Dict[str, Any]:
        r = rows.get(rid)
        if r is None:
            raise Refused(f"row {rid} not found")
        return r

    for e in spec["reopen"]:
        r = _row(e["id"])
        sig = base_sig = (r["account_id"], str(r["symbol"]).upper(), r["direction"],
                          float(r["position_size"] or 0), r["status"], r["exit_reason"], r["broker_order_id"])
        want = base + (e["size"], "closed", REOPEN_FROM_EXIT, e["broker_order_id"])
        if sig != want:
            raise Refused(f"row {e['id']} signature {base_sig} != spec {want} (already repaired, or it moved)")
        o = _filled_entry(orders, e["id"], e["broker_order_id"], e["size"], side)
        pkg = conn.execute("SELECT status, close_reason FROM order_packages WHERE order_package_id = ?",
                           (r["order_package_id"],)).fetchone()
        out["reopen"].append({"id": e["id"], "size": e["size"], "broker_order_id": e["broker_order_id"],
                              "entry_price_before": r["entry_price"],
                              "entry_price_after": float(o.get("filled_avg_price")),
                              "closed_at_before": r["closed_at"], "package": r["order_package_id"],
                              "package_status_before": pkg["status"] if pkg else None,
                              "package_close_reason_before": pkg["close_reason"] if pkg else None})
    for e in spec["keep_open"]:
        r = _row(e["id"])
        sig = (r["account_id"], str(r["symbol"]).upper(), r["direction"], float(r["position_size"] or 0),
               r["status"], r["broker_order_id"])
        want = base + (e["size"], "open", e["broker_order_id"])
        if sig != want:
            raise Refused(f"keep_open row {e['id']} signature {sig} != spec {want}")
        _filled_entry(orders, e["id"], e["broker_order_id"], e["size"], side)
        out["keep_open"].append({"id": e["id"], "size": e["size"]})
    all_order_ids = set(orders)
    for e in spec["phantom"]:
        r = _row(e["id"])
        sig = (r["account_id"], str(r["symbol"]).upper(), r["direction"], float(r["position_size"] or 0),
               r["status"])
        if sig != base + (e["size"], "open"):
            raise Refused(f"phantom row {e['id']} signature {sig} moved")
        if r["broker_order_id"] and str(r["broker_order_id"]) in all_order_ids:  # found at the venue
            raise Refused(f"phantom row {e['id']} has a venue order {r['broker_order_id']}: not a phantom")
        if (looked_up is not None and _real_order_id(r["broker_order_id"])
                and str(r["broker_order_id"]) not in looked_up):
            raise Refused(f"phantom row {e['id']}: its order {r['broker_order_id']} was not looked up at the venue")
        out["phantom"].append({"id": e["id"], "size": e["size"], "package": r["order_package_id"]})
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



#: How long the apply waits for the live trader's journal write lock (seconds). A dry run never writes.
WRITE_LOCK_TIMEOUT_S = 60.0

def apply(conn: sqlite3.Connection, p: Dict[str, Any], now: str, why: str) -> None:
    with conn:
        for r in p["reopen"]:
            notes = conn.execute("SELECT notes FROM trades WHERE id = ?", (r["id"],)).fetchone()[0]
            conn.execute(
                "UPDATE trades SET status='open', closed_at=NULL, exit_reason=NULL, entry_price=?, notes=? "
                "WHERE id=? AND status='closed'",
                (r["entry_price_after"], _merge_json(notes, "reopen_repair", {
                    "at": now, "why": why,
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
                    "at": now, "why": why + " (no venue order; the venue position is the reopened rows)",
                    "pnl": "NULL (UNMEASURED: nothing filled)"}), r["id"]))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--spec", help=f"spec JSON (default {SPEC_DIR}/<account>__<SYMBOL>.json)")
    ap.add_argument("--order-history", help="/api/diag/alpaca_order_history payload (order_ids= lookup)")
    ap.add_argument("--positions", help="/api/diag/exchange_positions payload")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--print-lookup", action="store_true",
                    help="print the comma-joined order ids (and phantom row ids) the capture needs, then exit")
    a = ap.parse_args(argv)
    spec_path = Path(a.spec) if a.spec else SPEC_DIR / f"{a.account}__{a.symbol.upper()}.json"
    try:
        spec = load_spec(json.loads(spec_path.read_text()), a.account, a.symbol)
    except (OSError, ValueError) as exc:
        print(f"REFUSED: spec {spec_path} unreadable: {exc}")
        return 2
    except Refused as exc:
        print(f"REFUSED (nothing written): {exc}")
        return 3
    if a.print_lookup:
        conn = sqlite3.connect(a.db)
        try:
            print(",".join(lookup_ids(conn, spec)))
        finally:
            conn.close()
        return 0
    if not a.order_history or not a.positions:
        print("REFUSED: --order-history and --positions are required (the venue evidence)")
        return 2
    try:
        history = json.loads(Path(a.order_history).read_text())
        positions = json.loads(Path(a.positions).read_text())
    except (OSError, ValueError) as exc:
        print(f"REFUSED: payload unreadable: {exc}")
        return 2
    conn = sqlite3.connect(a.db)
    try:
        p = plan(conn, spec, history, positions)
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
    # The live trader writes this journal continuously. sqlite3's default 5 s wait lost the race on 2026-11-19
    # (run 44513698892: 'database is locked' on the first UPDATE; the `with conn:` transaction rolled back, nothing
    # written). Wait up to WRITE_LOCK_TIMEOUT_S for the trader's write lock instead.
    conn = sqlite3.connect(a.db, timeout=WRITE_LOCK_TIMEOUT_S)
    conn.execute(f"PRAGMA busy_timeout={int(WRITE_LOCK_TIMEOUT_S * 1000)}")
    why = f"PI-20261118-JFWRQYOV-0004: closed before its entry filled; the venue filled it ({spec_path.name})"
    apply(conn, plan(conn, spec, history, positions), now, why)
    print(f"APPLIED at {now}; backup {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
