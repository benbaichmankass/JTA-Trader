"""Tier-1 read endpoint: one row per account CATEGORY for the Performance page (PERF-PAGE-CATEGORY-TABLE).

``GET /api/bot/performance/categories?window=7d|30d|90d|all`` -> ``{as_of, window, read_state, categories[], excluded[],
population}``. Metric definitions live in ``src.runtime.perf_category`` (one definition, tested). Unknown ``window`` is
HTTP 400 (the /performance rule). A sibling of ``/performance``: that route's shape is untouched.

Closed trades: ``trades.status='closed'``, not backtest, ``pnl`` NOT NULL, not superseded/reconciler/reset-flat/reduce-leg,
close time = the canonical ``close_time_sql``. Prop category reads closing rows of ``prop_journal.prop_fills`` (opening
row supplies entry/qty/open time/stop). Rows dropped for NULL pnl are COUNTED in ``population``, never hidden.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from src.runtime import perf_category as pc
from src.utils.paths import trade_journal_db_path
from src.web.api._clean_trades import (
    exclude_reconciler_predicate, exclude_reduce_leg_predicate, exclude_reset_flat_predicate,
    exclude_superseded_predicate)
from src.web.api._closed_at import close_time_sql

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot", tags=["bot"])

_DB_PATH = Path(trade_journal_db_path())
_ACCOUNTS_YAML = Path(__file__).resolve().parents[4] / "config" / "accounts.yaml"
_WINDOWS: Dict[str, Optional[int]] = {"7d": 7, "30d": 30, "90d": 90, "all": None}
_CT = close_time_sql("t.closed_at", "op.updated_at", "t.timestamp")


def _accounts() -> Dict[str, Any]:
    from src.config.accounts_loader import load_accounts_dict
    return load_accounts_dict(_ACCOUNTS_YAML)


def _trade_rows(conn: sqlite3.Connection, account_ids: List[str], since: Optional[str]) -> Dict[str, Any]:
    if not account_ids:
        return {"rows": [], "n_null_pnl": 0}
    ph = ",".join("?" for _ in account_ids)
    base = f"""
        FROM trades t
        LEFT JOIN (SELECT linked_trade_id, MIN(updated_at) AS updated_at, MIN(meta) AS meta FROM order_packages
                   WHERE linked_trade_id IS NOT NULL GROUP BY linked_trade_id) op ON op.linked_trade_id = t.id
        WHERE t.status = 'closed' AND COALESCE(t.is_backtest, 0) = 0 AND t.account_id IN ({ph})
        {exclude_reconciler_predicate("t.")}{exclude_superseded_predicate("t.")}
        {exclude_reset_flat_predicate("t.")}{exclude_reduce_leg_predicate("t.")}"""
    params: List[Any] = list(account_ids)
    if since:
        base += f" AND {_CT} >= datetime(?)"
        params.append(since)
    conn.row_factory = sqlite3.Row
    n_null = conn.execute("SELECT COUNT(*) " + base + " AND t.pnl IS NULL", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT t.id, t.account_id, t.symbol, t.direction, t.entry_price, t.stop_loss, t.take_profit_1,
                   t.position_size AS qty, t.pnl, t.notes, t.timestamp AS opened_at, {_CT} AS closed_at,
                   t.fee_taker_usd, t.fee_maker_usd, t.funding_paid_usd, op.meta AS package_meta
            {base} AND t.pnl IS NOT NULL""", params).fetchall()
    return {"rows": [dict(r) for r in rows], "n_null_pnl": n_null}


def _prop_stop(opener: Dict[str, Any]) -> Optional[float]:
    """Initial stop for R: the level before the first journaled amend, else the opener's recorded stop (a hand-move that
    never reached the journal is invisible -- the R then rests on the stored stop and is graded as such)."""
    b = opener.get("bracket") or {}
    return b.get("entry_sl") if b.get("entry_sl") is not None else b.get("final_sl")


def _prop_rows(account_ids: List[str], since: Optional[str]) -> Dict[str, Any]:
    """Closed prop trades from prop_fills: the CLOSING row carries pnl/exit; the opener carries entry/qty/stop/open time."""
    from src.prop import prop_journal, prop_overview
    out: List[Dict[str, Any]] = []
    n_null = 0
    cutoff = datetime.fromisoformat(since) if since else None
    for aid in account_ids:
        fills = prop_journal.list_fills(account_id=aid, limit=5000)
        prop_overview.annotate_trade_state(fills)
        prop_overview.attach_trade_brackets(fills)
        by_ticket = {f.get("ticket_id"): f for f in fills if str(f.get("status", "")).lower() in ("open", "filled")}
        for f in fills:
            if str(f.get("status", "")).lower() != "closed":
                continue
            c = pc._dt(f.get("closed_at") or f.get("reported_at"))
            if cutoff and (c is None or c < cutoff):
                continue
            if f.get("pnl") is None:
                n_null += 1
                continue
            o = by_ticket.get(f.get("ticket_id")) or f
            out.append({"account_id": aid, "symbol": f.get("symbol"), "direction": f.get("direction"), "pnl": f["pnl"],
                        "entry_price": o.get("entry_price") or f.get("entry_price"), "qty": o.get("qty") or f.get("qty"),
                        "stop_loss": _prop_stop(o), "opened_at": o.get("opened_at"),
                        "closed_at": f.get("closed_at") or f.get("reported_at"), "notes": None})
    return {"rows": out, "n_null_pnl": n_null}


def _snapshots(conn: sqlite3.Connection, account_ids: List[str], since: Optional[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for aid in account_ids:
        q = "SELECT COUNT(balance), AVG(balance) FROM balance_snapshots WHERE account_id = ? AND api_ok = 1"
        p: List[Any] = [aid]
        if since:
            q += " AND datetime(ts) >= datetime(?)"
            p.append(since)
        n, mean = conn.execute(q, p).fetchone()
        out[aid] = {"n": n or 0, "mean_balance": mean}
    return out


@router.get("/performance/categories")
def get_performance_categories(window: str = "30d") -> Dict[str, Any]:
    if window not in _WINDOWS:
        raise HTTPException(status_code=400, detail=f"unknown window {window!r}; valid: {sorted(_WINDOWS)}")
    now = datetime.now(timezone.utc)
    days = _WINDOWS[window]
    since = (now - timedelta(days=days)).isoformat() if days else None
    as_of = now.isoformat()
    try:
        cats, excluded = pc.categorize(_accounts())
    except Exception:  # noqa: BLE001  # allow-silent: an unreadable accounts.yaml is a stated read_state, not a 5xx
        logger.warning("performance/categories: accounts.yaml unreadable", exc_info=True)
        return {"as_of": as_of, "window": window, "read_state": "accounts_unreadable", "categories": [], "excluded": [],
                "population": None}
    out: List[Dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            for cat in pc.CATEGORIES:
                ids = cats[cat]
                data = _prop_rows(ids, since) if cat == "prop" else _trade_rows(conn, ids, since)
                # all-time: window length = span from the first close to now (None when no rows)
                wd = float(days) if days else None
                if wd is None and data["rows"]:
                    first = min(pc._dt(r["closed_at"]) or now for r in data["rows"])
                    wd = max((now - first).total_seconds() / 86400.0, 1e-9)
                m = pc.category_metrics(data["rows"], category=cat, window_days=wd,
                                        snapshots=_snapshots(conn, ids, since) if ids else None)
                m.update({"accounts": ids, "n_excluded_null_pnl": data["n_null_pnl"],
                          "read_state": "measured" if ids else "no_accounts"})
                out.append(m)
        finally:
            conn.close()
    except sqlite3.Error:  # allow-silent: logs the stack and answers read_state journal_unreadable with population null, never an empty table that reads as "no trades"
        logger.warning("performance/categories: journal read failed", exc_info=True)
        return {"as_of": as_of, "window": window, "read_state": "journal_unreadable", "categories": [], "excluded": excluded,
                "population": None}
    return {"as_of": as_of, "window": window, "read_state": "measured", "categories": out, "excluded": excluded,
            "population": {"window": window, "since": since, "accounts": {c: cats[c] for c in pc.CATEGORIES},
                           "n_closed": sum(c["n_closed"] for c in out),
                           "rows_excluded_null_pnl": sum(c["n_excluded_null_pnl"] for c in out),
                           "also_excluded": "backtest, superseded, reconciler pseudo-strategy, reset-flat, reduce legs"}}
