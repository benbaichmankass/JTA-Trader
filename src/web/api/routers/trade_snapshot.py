"""Tier-1 read routes: closed-trade chart snapshot + open-trade decision markers (UI-REDESIGN-2026-11).

``GET /api/bot/trades/{trade_id}/snapshot``  -- the STORED snapshot (``trade_chart_snapshots``); never fetches candles.
``GET /api/bot/prop-trades/{fill_id}/snapshot`` / ``/markers`` -- the same for a PROP trade, keyed by a
``prop_fills`` id (the opening or the closing row; both resolve to the trade, stored as ``prop:<closing row id>``).
``GET /api/bot/trades/{trade_id}/markers?interval=1h`` -- entry, entry signal, bracket history and every LTR review /
directed action on the trade, computed per request from the journal + local review files (no network).

Contract: docs/reference/bot-api-reference.md § "Trade chart snapshot + decision markers"; fixtures
tests/fixtures/trade_chart_snapshot_v1.json, tests/fixtures/trade_markers_v1.json. GET only (CORS allows GET).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from src.runtime import trade_snapshot_store as store
from src.utils.paths import trade_journal_db_path, trade_snapshots_db_path
from src.web.api import brackets_history as bh
from src.web.api import trade_chart_snapshot as tcs
from src.web.api import trade_decision_sources as srcs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot", tags=["bot"])

_DB_PATH = Path(trade_journal_db_path())
_SNAP_PATH = Path(trade_snapshots_db_path())


def _connect() -> sqlite3.Connection:
    """The journal, READ-ONLY (mode=ro): these routes never write it."""
    conn = store.journal_ro(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_trade(conn: sqlite3.Connection, trade_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (int(trade_id),)).fetchone()
    return dict(row) if row is not None else None


def load_package(conn: sqlite3.Connection, order_package_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not order_package_id:
        return None
    row = conn.execute("SELECT * FROM order_packages WHERE order_package_id = ?", (order_package_id,)).fetchone()
    return dict(row) if row is not None else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _closed_population(conn: sqlite3.Connection) -> Dict[str, Any]:
    """What the writer must eventually build: closed live trades + closed prop fills (the builder's own population)."""
    trades = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'closed' AND closed_at IS NOT NULL "
                          "AND COALESCE(is_backtest, 0) = 0").fetchone()[0]
    try:
        prop = conn.execute("SELECT COUNT(*) FROM prop_fills WHERE lower(status) = 'closed'").fetchone()[0]
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        prop = 0
    return {"trades": trades, "prop": prop}


@router.get("/trades/snapshots/status")
def get_snapshot_writer_status() -> Dict[str, Any]:
    """Backfill / writer progress (the builder logs at INFO, which the journal does not keep): built, pending,
    failing, total_closed, last batch and last error. Read-only; nulls mean "could not look", never 0."""
    as_of = _now()
    reasons = []
    counts = store.status_counts(str(_SNAP_PATH))
    if counts["state"] != "read":
        reasons.append(f"snapshot_db_{counts['state']}")
    try:
        conn = _connect()
        try:
            pop = _closed_population(conn)
        finally:
            conn.close()
    except sqlite3.Error:  # allow-silent: surfaced as total_closed null + partial_reasons journal_unreadable
        logger.warning("snapshot status: journal read failed", exc_info=True)
        pop = None
        reasons.append("journal_unreadable")
    total = (pop["trades"] + pop["prop"]) if pop else None
    built, retrying = counts["built"], counts["retrying"]
    pending = (max(total - built - retrying, 0) if (total is not None and built is not None and retrying is not None)
               else None)
    try:
        from src.runtime import trade_snapshot_builder as tsb
        rt = dict(tsb.STATUS)
        running = tsb._thread is not None and tsb._thread.is_alive()
    except Exception:  # noqa: BLE001  # allow-silent: surfaced as writer.running null + partial reason
        rt, running = {}, None
        reasons.append("writer_status_unreadable")
    if running is False:
        reasons.append("writer_not_running")
    return {
        "as_of": as_of,
        "read_state": "measured" if not reasons else "partial",
        "partial_reasons": reasons,
        "total_closed": total,
        "total_closed_trades": pop["trades"] if pop else None,
        "total_closed_prop": pop["prop"] if pop else None,
        "built": built, "built_partial": counts["built_partial"],
        "built_trade": counts["built_trade"], "built_prop": counts["built_prop"],
        "pending": pending,
        "failing": retrying, "failing_flagged": counts["failing_flagged"], "failing_max_attempts": counts["max_attempts"],
        "last_built_at": counts["last_built_at"],
        "last_error": counts["last_error"], "last_error_key": counts["last_error_key"],
        "writer": {"running": running, "started_at": rt.get("started_at"), "last_batch_at": rt.get("last_batch_at"),
                   "last_batch": rt.get("last_batch"), "loop_errors": rt.get("errors")},
    }


@router.get("/trades/{trade_id}/snapshot")
def get_trade_snapshot(trade_id: int) -> Dict[str, Any]:
    as_of = _now()
    try:
        conn = _connect()
        try:
            trade = load_trade(conn, trade_id)
            if trade is None:
                raise HTTPException(status_code=404, detail="no such trade")
            if str(trade.get("status")) != "closed":
                raise HTTPException(status_code=404, detail="trade is not closed; use /markers for an open trade")
            got = store.read_key(str(_SNAP_PATH), store.trade_key(trade_id))
        finally:
            conn.close()
    except HTTPException:
        raise
    except sqlite3.Error:  # allow-silent: logs the stack and answers read_state no_record + journal_unreadable
        logger.warning("trade snapshot: read failed", exc_info=True)
        return {"as_of": as_of, "trade_id": trade_id, "prop_fill_id": None, "read_state": "no_record",
                "partial_reasons": ["journal_unreadable"], "snapshot": None}
    return _snapshot_envelope(as_of, got, trade_id=trade_id, prop_fill_id=None)


def _snapshot_envelope(as_of: str, got: Dict[str, Any], trade_id: Optional[int],
                       prop_fill_id: Optional[int]) -> Dict[str, Any]:
    ids = {"trade_id": trade_id, "prop_fill_id": prop_fill_id}
    payload = got.get("payload")
    if payload is None:
        reasons = ["snapshot_not_built"]
        if got.get("state") == "retrying":
            reasons.append(f"build_retrying:{got.get('attempts')}")
        return {"as_of": as_of, **ids, "read_state": "not_built", "partial_reasons": reasons, "snapshot": None}
    if "indicators" not in payload:   # stored without them (store.encode); recomputed from the stored candles
        payload["indicators"] = tcs.indicators(((payload.get("candles") or {}).get("rows")) or [])
    rs, reasons = tcs.snapshot_read_state(payload)
    return {"as_of": as_of, **ids, "read_state": rs, "partial_reasons": reasons, "snapshot": payload}


@router.get("/trades/{trade_id}/markers")
def get_trade_markers(trade_id: int, interval: str = "1h") -> Dict[str, Any]:
    if interval not in bh._INTERVAL_S:
        raise HTTPException(status_code=400, detail=f"unknown interval {interval!r}; one of {sorted(bh._INTERVAL_S)}")
    as_of = _now()
    try:
        conn = _connect()
        try:
            trade = load_trade(conn, trade_id)
            if trade is None:
                raise HTTPException(status_code=404, detail="no such trade")
            pkg = load_package(conn, trade.get("order_package_id"))
        finally:
            conn.close()
    except HTTPException:
        raise
    except sqlite3.Error:  # allow-silent: logs the stack and answers read_state no_record + journal_unreadable
        logger.warning("trade markers: read failed", exc_info=True)
        return {"as_of": as_of, "trade_id": trade_id, "prop_fill_id": None, "interval": interval,
                "read_state": "no_record",
                "partial_reasons": ["journal_unreadable"], "entry": None, "entry_signal": None,
                "brackets": None, "decisions": None}
    return tcs.build_markers(trade, pkg, srcs.load_reviews(), srcs.load_receipts(), interval, as_of)


def _prop(conn: sqlite3.Connection, fill_id: int):
    got = store.resolve_prop(conn, fill_id)
    if got is None:
        raise HTTPException(status_code=404, detail="no such prop fill")
    opener, closer, ticket = got
    pkg = load_package(conn, (ticket or {}).get("order_package_id"))
    return tcs.prop_trade(opener, closer, ticket), pkg, closer


@router.get("/prop-trades/{fill_id}/snapshot")
def get_prop_trade_snapshot(fill_id: int) -> Dict[str, Any]:
    as_of = _now()
    try:
        conn = _connect()
        try:
            trade, _pkg, closer = _prop(conn, fill_id)
            if closer is None:
                raise HTTPException(status_code=404, detail="prop trade is not closed; use /markers for an open trade")
            got = store.read_key(str(_SNAP_PATH), store.prop_key(closer["id"]))
        finally:
            conn.close()
    except HTTPException:
        raise
    except sqlite3.Error:  # allow-silent: logs the stack and answers read_state no_record + journal_unreadable
        logger.warning("prop trade snapshot: read failed", exc_info=True)
        return {"as_of": as_of, "trade_id": None, "prop_fill_id": fill_id, "read_state": "no_record",
                "partial_reasons": ["journal_unreadable"], "snapshot": None}
    return _snapshot_envelope(as_of, got, trade_id=None, prop_fill_id=trade["prop_fill_id"])


@router.get("/prop-trades/{fill_id}/markers")
def get_prop_trade_markers(fill_id: int, interval: str = "1h") -> Dict[str, Any]:
    if interval not in bh._INTERVAL_S:
        raise HTTPException(status_code=400, detail=f"unknown interval {interval!r}; one of {sorted(bh._INTERVAL_S)}")
    as_of = _now()
    try:
        conn = _connect()
        try:
            trade, pkg, _closer = _prop(conn, fill_id)
        finally:
            conn.close()
    except HTTPException:
        raise
    except sqlite3.Error:  # allow-silent: logs the stack and answers read_state no_record + journal_unreadable
        logger.warning("prop trade markers: read failed", exc_info=True)
        return {"as_of": as_of, "trade_id": None, "prop_fill_id": fill_id, "interval": interval,
                "read_state": "no_record", "partial_reasons": ["journal_unreadable"], "entry": None,
                "entry_signal": None, "brackets": None, "decisions": None}
    return tcs.build_markers(trade, pkg, srcs.load_reviews(), srcs.load_receipts(), interval, as_of)
