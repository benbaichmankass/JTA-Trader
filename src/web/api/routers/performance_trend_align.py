"""Tier-1 read endpoint: live closes split by TREND-ALIGN-V1 label, per strategy x account (row TREND-ALIGN-LABEL-ALL).

``GET /api/bot/performance/trend-align?window=7d|30d|90d|all&axis=D1|LEG`` ->
``{as_of, window, axis, read_state, groups[], population}``.

Each closed trade's label is read from its OWN order package (``order_packages.meta.trend_align``), joined on
``trades.order_package_id`` so every per-account row (live, mirror, paper) carries its package's label -- not only the
primary entry that ``linked_trade_id`` points at. The label was stamped at signal time by the live trader (provenance
``measured``). A trade whose package carries no label (closed before the stamp shipped, or a path that never stamped)
is grouped under ``label: null`` and the UI renders it as "—": never neutral, never 0. ``missing_reason`` counts say why.

Read only: this route never writes, and nothing in the trade path reads the label.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException

from src.runtime.provenance import MEASURED
from src.utils.paths import trade_journal_db_path
from src.web.api._clean_trades import (
    exclude_reconciler_predicate, exclude_reduce_leg_predicate, exclude_reset_flat_predicate,
    exclude_superseded_predicate)
from src.web.api._closed_at import close_time_sql

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot", tags=["bot"])

_DB_PATH = Path(trade_journal_db_path())
_WINDOWS: Dict[str, Optional[int]] = {"7d": 7, "30d": 30, "90d": 90, "all": None}
_AXES = ("D1", "LEG")
_LABELS = ("with_trend", "counter_trend", "neutral")
_CT = close_time_sql("t.closed_at", "opl.updated_at", "t.timestamp")


def _label(meta_text: Any, axis: str) -> Tuple[Optional[str], Optional[str]]:
    """``(label, missing_reason)`` for one package's meta. No meta / no trend_align -> ``(None, "unlabelled")``."""
    try:
        meta = json.loads(meta_text) if isinstance(meta_text, str) and meta_text else (meta_text or {})
    except (TypeError, ValueError):
        return None, "meta_unreadable"
    ta = meta.get("trend_align") if isinstance(meta, dict) else None
    if not isinstance(ta, dict):
        return None, "unlabelled"
    node = ta.get(axis) if isinstance(ta.get(axis), dict) else {}
    lab = node.get("label")
    if lab in _LABELS:
        return lab, None
    return None, str(node.get("missing_reason") or "unlabelled")


def _rows(conn: sqlite3.Connection, since: Optional[str]) -> List[Dict[str, Any]]:
    q = f"""
        SELECT t.id, t.account_id, t.strategy_name, t.pnl, opm.meta AS package_meta
        FROM trades t
        LEFT JOIN (SELECT linked_trade_id, MIN(updated_at) AS updated_at FROM order_packages
                   WHERE linked_trade_id IS NOT NULL GROUP BY linked_trade_id) opl ON opl.linked_trade_id = t.id
        LEFT JOIN order_packages opm ON opm.order_package_id = t.order_package_id
        WHERE t.status = 'closed' AND COALESCE(t.is_backtest, 0) = 0 AND t.pnl IS NOT NULL
        {exclude_reconciler_predicate("t.")}{exclude_superseded_predicate("t.")}
        {exclude_reset_flat_predicate("t.")}{exclude_reduce_leg_predicate("t.")}"""
    params: List[Any] = []
    if since:
        q += f" AND {_CT} >= datetime(?)"
        params.append(since)
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def split(rows: List[Dict[str, Any]], axis: str) -> Dict[str, Any]:
    """Group closed rows by (strategy, account, label). Pure: the route's whole computation, unit-tested."""
    acc: Dict[Tuple[str, str, Optional[str]], Dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "wins": 0, "net_pnl_usd": 0.0, "missing_reasons": Counter()})
    for r in rows:
        lab, why = _label(r.get("package_meta"), axis)
        g = acc[(str(r.get("strategy_name") or ""), str(r.get("account_id") or ""), lab)]
        pnl = float(r["pnl"])
        g["n"] += 1
        g["wins"] += 1 if pnl > 0 else 0
        g["net_pnl_usd"] += pnl
        if why:
            g["missing_reasons"][why] += 1
    groups = []
    for (strategy, account, lab), g in sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "~")):
        groups.append({"strategy": strategy, "account_id": account, "axis": axis, "label": lab,
                       "label_provenance": MEASURED if lab is not None else None,
                       "n": g["n"], "wins": g["wins"], "win_rate": round(g["wins"] / g["n"], 4),
                       "net_pnl_usd": round(g["net_pnl_usd"], 4), "mean_pnl_usd": round(g["net_pnl_usd"] / g["n"], 4),
                       "missing_reasons": dict(g["missing_reasons"]) or None})
    n_lab = sum(g["n"] for g in groups if g["label"] is not None)
    return {"groups": groups, "n_closed": sum(g["n"] for g in groups), "n_labelled": n_lab}


@router.get("/performance/trend-align")
def get_performance_trend_align(window: str = "30d", axis: str = "D1") -> Dict[str, Any]:
    """Closed-trade P&L split with / counter / neutral (and unlabelled "—") per strategy x account."""
    if window not in _WINDOWS:
        raise HTTPException(status_code=400, detail=f"unknown window {window!r}; valid: {sorted(_WINDOWS)}")
    if axis not in _AXES:
        raise HTTPException(status_code=400, detail=f"unknown axis {axis!r}; valid: {list(_AXES)}")
    now = datetime.now(timezone.utc)
    days = _WINDOWS[window]
    since = (now - timedelta(days=days)).isoformat() if days else None
    head = {"as_of": now.isoformat(), "window": window, "axis": axis, "definition": "TREND-ALIGN-V1"}
    try:
        conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        try:
            rows = _rows(conn, since)
        finally:
            conn.close()
    except sqlite3.Error:  # allow-silent: logs the stack and answers read_state journal_unreadable with population null, never an empty table that reads as "no trades"
        logger.warning("performance/trend-align: journal read failed", exc_info=True)
        return {**head, "read_state": "journal_unreadable", "groups": [], "population": None}
    out = split(rows, axis)
    return {**head, "read_state": "measured", "groups": out["groups"],
            "population": {"since": since, "n_closed": out["n_closed"], "n_labelled": out["n_labelled"],
                           "n_unlabelled": out["n_closed"] - out["n_labelled"],
                           "text": f"{window} · closed trades (all accounts, not backtest/superseded/reconciler/"
                                   f"reset-flat/reduce legs, pnl not null) · n_closed={out['n_closed']} · "
                                   f"labelled on {axis}={out['n_labelled']}; unlabelled rows render '—'"}}
