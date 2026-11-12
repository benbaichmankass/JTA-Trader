"""Book a PARTIAL close as its own closed journal row (PARTIAL-CLOSE-PNL-NOT-JOURNALED).

THE DEFECT (MEASURED 2026-11-12, pkg-633f05fad1ee4c1d, trend_donchian_xrp_4h)
-----------------------------------------------------------------------------
Live review LR-20261109T0828Z applied a 50% ``partial_close``. The venue bought back
bybit_2 53.8 @ 1.0893 (order ac3c1ec8, 09:51:51Z) and bybit_portfolio 16239.2 @ 1.0836
(order 9178f2b1, 10:52:17Z). ``scripts/ops/live_review_apply.py`` shrank each parent
row's ``position_size`` and wrote the action into ``notes.live_review_actions``, and
nothing else. Two failures followed:

* **The closed half's realised P&L landed on no row.** The parent's pnl is computed
  on the REMAINING size only, and the action list (an unprotected notes key) was shed
  by the next 500-char notes rewrite: rows 6982/6983 no longer carry it, and 0 of the
  newest 600 journal rows carry ``live_review_actions`` at all.
* **The un-booked fill was then mistaken for the parent's exit.** The demo
  pending-pnl path priced row 6983 from the FIRST close-side fill whose qty matched,
  9178f2b1 @ 1.0836, though the row's own stop bd8d3a72 filled at 1.0629
  (DEMO-EXIT-FIRST-FILL-ATTRIBUTION). That is the whole "mirror 0.42 R worse than live"
  gap PI-20261106-Y7JEXUWW-0006 reported.

THE RECORD
----------
:func:`book_partial_close` writes ONE closed child row per partial close:

* the parent's account, symbol, direction, strategy and ``order_package_id``;
  ``entry_price`` = the parent's entry; ``position_size`` = the closed qty;
* ``setup_type='partial_close'``, ``exit_reason`` = the caller's reason;
* ``exit_price`` = the venue fill and ``pnl`` from it (net of the fees passed), or both
  NULL with ``partial_close_state='pending_fill'`` when the fill could not be read at
  apply time; :func:`settle_pending_children` prices those from the exchange-fills
  store by ``broker_order_id`` (the close order's venue id);
* the child row itself IS the action record. Its notes stay short and every key a
  reader branches on is protected (``src.utils.json_notes._DEFAULT_PROTECTED``).

Idempotent per ``(parent_trade_id, close_order_id)``: a second call for the same venue
order returns the existing child and writes nothing. With ``shrink_parent=True`` the
parent's ``position_size`` is reduced in the same call, guarded on its current value.
The callers that already shrink the parent themselves pass ``False``.

A child row is a REALISED-P&L record of the parent's trade, not an independent trading
decision. Readers that count decisions should group by ``order_package_id`` (or use
:func:`is_partial_close_child`); readers that sum money include it. Both P&L sweeps in
``order_monitor`` skip ``setup_type='partial_close'`` rows, so only this module prices them.

Never raises from the public functions; failures come back as ``state='error'``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "PARTIAL_CLOSE_SETUP_TYPE",
    "STATE_BOOKED",
    "STATE_PENDING",
    "STATE_DUPLICATE",
    "STATE_ERROR",
    "book_partial_close",
    "settle_pending_children",
    "is_partial_close_child",
]

#: ``trades.setup_type`` of a child row.
PARTIAL_CLOSE_SETUP_TYPE = "partial_close"

#: ``notes.partial_close_state`` values and the call's returned ``state``.
STATE_BOOKED = "booked"            # exit price + pnl written from the venue fill
STATE_PENDING = "pending_fill"     # fill not read yet; settle_pending_children prices it
STATE_DUPLICATE = "duplicate"      # this close order already has a child row
STATE_ERROR = "error"

#: Exit-price provenance stamped on a child priced from a venue fill. Both values
#: are MEASURED in ``src.runtime.provenance``.
_FILL_SOURCE_AT_APPLY = "exchange"        # the order's own avg fill, read back at apply
_FILL_SOURCE_FROM_STORE = "exchange_fill"  # the exchange-fills store, by order id


def _f(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def is_partial_close_child(row: Any) -> bool:
    """True for a child row written by :func:`book_partial_close`."""
    try:
        return str((row or {}).get("setup_type") or "") == PARTIAL_CLOSE_SETUP_TYPE
    except AttributeError:
        return False


def _child_pnl(parent: Dict[str, Any], qty: float, fill_price: float,
               fees_usd: float) -> Dict[str, Any]:
    from src.runtime.local_pnl import (
        compute_pnl_percent, compute_realized_pnl, contract_value_usd_for,
    )
    entry = _f(parent.get("entry_price"))
    cvu = contract_value_usd_for(parent.get("symbol"))
    pnl = compute_realized_pnl(
        entry_price=entry, exit_price=fill_price, qty=qty,
        direction=parent.get("direction"), contract_value_usd=cvu,
    )
    if pnl is None:
        return {}
    net = round(pnl - (fees_usd or 0.0), 8)
    out: Dict[str, Any] = {"pnl": net, "_cvu": cvu, "_gross": pnl}
    pct = compute_pnl_percent(pnl=net, entry_price=entry, qty=qty, contract_value_usd=cvu)
    if pct is not None:
        out["pnl_percent"] = pct
    return out


def book_partial_close(
    db,
    *,
    parent_trade_id: int,
    qty: Any,
    fill_price: Any,
    filled_at: Optional[str],
    close_order_id: Optional[str],
    source: str,
    reason: str,
    fees_usd: Any = 0.0,
    shrink_parent: bool = False,
    review_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the closed child row for one partial close. See the module docstring.

    Returns ``{"state", "child_id", "parent_size_after", "detail"}``.
    """
    out: Dict[str, Any] = {"state": STATE_ERROR, "child_id": None,
                           "parent_size_after": None, "detail": ""}
    try:
        from src.utils.json_notes import dump_capped

        q = _f(qty)
        if not q or q <= 0:
            out["detail"] = f"qty {qty!r} is not a positive number"
            return out
        oid = str(close_order_id or "").strip() or None
        conn = db.connect()
        try:
            conn.row_factory = __import__("sqlite3").Row
            prow = conn.execute(
                "SELECT id, account_id, symbol, direction, entry_price, stop_loss, "
                "       take_profit_1, position_size, strategy_name, order_package_id, "
                "       account_class, is_demo, status "
                "  FROM trades WHERE id = ?", (int(parent_trade_id),)).fetchone()
            parent = dict(prow) if prow else None
            existing = None
            if parent is not None and oid:
                existing = conn.execute(
                    "SELECT id FROM trades WHERE setup_type = ? AND broker_order_id = ? "
                    "   AND account_id = ? AND order_package_id IS ? LIMIT 1",
                    (PARTIAL_CLOSE_SETUP_TYPE, oid, parent["account_id"],
                     parent["order_package_id"])).fetchone()
        finally:
            conn.close()
        if parent is None:
            out["detail"] = f"no parent trade {parent_trade_id}"
            return out
        if existing is not None:
            out.update(state=STATE_DUPLICATE, child_id=int(existing[0]),
                       parent_size_after=_f(parent.get("position_size")),
                       detail=f"close order {oid} already booked")
            return out

        fees = _f(fees_usd) or 0.0
        px = _f(fill_price)
        priced = _child_pnl(parent, q, px, fees) if px and px > 0 else {}
        now_iso = datetime.now(timezone.utc).isoformat()
        closed_at = str(filled_at or "").strip() or now_iso
        notes: Dict[str, Any] = {
            "parent_trade_id": int(parent["id"]),
            "partial_close_source": str(source),
            "partial_close_state": STATE_BOOKED if priced else STATE_PENDING,
            "closed_at": closed_at,
            "closed_by": f"partial_close:{source}"[:60],
        }
        if review_id:
            notes["review_id"] = str(review_id)[:80]
        row: Dict[str, Any] = {
            "timestamp": now_iso,
            "symbol": parent.get("symbol"),
            "direction": parent.get("direction"),
            "entry_price": _f(parent.get("entry_price")),
            "stop_loss": _f(parent.get("stop_loss")),
            "take_profit_1": _f(parent.get("take_profit_1")),
            "position_size": q,
            "setup_type": PARTIAL_CLOSE_SETUP_TYPE,
            "entry_reason": f"partial close of trade {int(parent['id'])}"[:500],
            "exit_reason": str(reason or "partial_close")[:80],
            # status='closed' so insert_trade fires no trade_opened ping.
            "status": "closed",
            "closed_at": closed_at,
            "is_backtest": 0,
            "account_class": parent.get("account_class"),
            "is_demo": parent.get("is_demo"),
            "strategy_name": parent.get("strategy_name"),
            "account_id": parent.get("account_id"),
            "order_package_id": parent.get("order_package_id"),
            "broker_order_id": oid,
        }
        if priced:
            row["exit_price"] = float(px)
            row["pnl"] = priced["pnl"]
            if "pnl_percent" in priced:
                row["pnl_percent"] = priced["pnl_percent"]
            notes["exit_price_source"] = _FILL_SOURCE_AT_APPLY
            notes["pnl_source"] = "local_compute"
            notes["contract_value_usd"] = priced["_cvu"]
            if fees:
                notes["close_fees_usd"] = round(fees, 8)
                notes["pnl_net_of_close_fees"] = True
        else:
            notes["pnl_source"] = STATE_PENDING
        row["notes"] = dump_capped(notes, 500)
        child_id = db.insert_trade(row)
        out.update(state=STATE_BOOKED if priced else STATE_PENDING, child_id=int(child_id))

        size_before = _f(parent.get("position_size")) or 0.0
        if shrink_parent:
            remaining = max(0.0, round(size_before - q, 10))
            wconn = db.connect()
            try:
                cur = wconn.execute(
                    "UPDATE trades SET position_size = ? "  # writer-conformance: allow guarded shrink of the parent's open size; the WHERE pins the size read above so a concurrent writer wins, and update_trade cannot guard on a prior value
                    " WHERE id = ? AND position_size IS ?",
                    (remaining, int(parent["id"]), parent.get("position_size")))
                wconn.commit()
                changed = cur.rowcount
            finally:
                wconn.close()
            out["parent_size_after"] = remaining if changed else size_before
            if not changed:
                out["detail"] = "child booked; parent size changed concurrently, not shrunk"
        else:
            out["parent_size_after"] = size_before
        return out
    except Exception as exc:  # noqa: BLE001 — a journal write must never break the caller's close
        logger.warning("book_partial_close(parent=%s order=%s): %s",
                       parent_trade_id, close_order_id, exc)
        out["detail"] = f"{type(exc).__name__}: {exc}"
        return out


def settle_pending_children(
    db, *, fills_conn_factory: Optional[Callable[[], Any]] = None, limit: int = 50,
) -> Dict[str, int]:
    """Price ``pending_fill`` child rows from the exchange-fills store, by close order id.

    A local read of the fills store (never a broker call). A child whose order has no
    stored fill yet stays pending and is retried next tick. Never raises.
    """
    summary = {"scanned": 0, "settled": 0, "still_pending": 0, "errors": 0}
    try:
        from src.utils.json_notes import dump_capped

        conn = db.connect()
        try:
            conn.row_factory = __import__("sqlite3").Row
            rows = [dict(r) for r in conn.execute(
                "SELECT id, account_id, symbol, direction, entry_price, position_size, "
                "       broker_order_id, notes "
                "  FROM trades "
                " WHERE setup_type = ? AND status = 'closed' AND pnl IS NULL "
                "   AND COALESCE(broker_order_id, '') != '' "
                "   AND datetime(COALESCE(closed_at, created_at)) >= datetime('now', '-14 days') "
                " ORDER BY id DESC LIMIT ?",
                (PARTIAL_CLOSE_SETUP_TYPE, int(limit))).fetchall()]
        finally:
            conn.close()
        if not rows:
            return summary
        summary["scanned"] = len(rows)
        if fills_conn_factory is not None:
            fconn = fills_conn_factory()
        else:
            import sqlite3 as _sq
            from src.runtime.exchange_fills_store import get_fills_db_path
            path = get_fills_db_path()
            fconn = _sq.connect(f"file:{path}?mode=ro", uri=True) if path.exists() else None
        if fconn is None:
            summary["still_pending"] = len(rows)
            return summary
        try:
            for r in rows:
                try:
                    fills = fconn.execute(
                        "SELECT price, qty, fee FROM exchange_fills "
                        " WHERE account_id = ? AND order_id = ?",
                        (str(r["account_id"]), str(r["broker_order_id"]))).fetchall()
                    q = sum((_f(x[1]) or 0.0) for x in fills)
                    if not fills or q <= 0:
                        summary["still_pending"] += 1
                        continue
                    vwap = sum((_f(x[0]) or 0.0) * (_f(x[1]) or 0.0) for x in fills) / q
                    fees = sum((_f(x[2]) or 0.0) for x in fills)
                    size = _f(r.get("position_size")) or q
                    priced = _child_pnl(r, size, vwap, fees)
                    if not priced:
                        summary["still_pending"] += 1
                        continue
                    try:
                        notes = json.loads(r.get("notes") or "{}")
                        notes = notes if isinstance(notes, dict) else {}
                    except (TypeError, ValueError):
                        notes = {}
                    notes.update({
                        "partial_close_state": STATE_BOOKED,
                        "exit_price_source": _FILL_SOURCE_FROM_STORE,
                        "pnl_source": "local_compute",
                        "contract_value_usd": priced["_cvu"],
                    })
                    if fees:
                        notes["close_fees_usd"] = round(fees, 8)
                        notes["pnl_net_of_close_fees"] = True
                    upd: Dict[str, Any] = {"exit_price": round(vwap, 10), "pnl": priced["pnl"],
                                           "notes": dump_capped(notes, 500)}
                    if "pnl_percent" in priced:
                        upd["pnl_percent"] = priced["pnl_percent"]
                    db.update_trade(int(r["id"]), upd)
                    summary["settled"] += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("settle_pending_children: child %s: %s", r.get("id"), exc)
                    summary["errors"] += 1
        finally:
            try:
                fconn.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("settle_pending_children: scan failed: %s", exc)
        summary["errors"] += 1
    return summary
