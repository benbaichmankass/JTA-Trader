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
        f"""SELECT t.id, t.account_id, t.strategy_name, t.symbol, t.direction, t.entry_price, t.stop_loss, t.take_profit_1,
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
            out.append({"account_id": aid, "strategy_name": "prop", "symbol": f.get("symbol"), "direction": f.get("direction"), "pnl": f["pnl"],
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
    except sqlite3.Error:
        logger.warning("performance/categories: journal read failed", exc_info=True)
        return {"as_of": as_of, "window": window, "read_state": "journal_unreadable", "categories": [], "excluded": excluded,
                "population": None}
    return {"as_of": as_of, "window": window, "read_state": "measured", "categories": out, "excluded": excluded,
            "population": {"window": window, "since": since, "accounts": {c: cats[c] for c in pc.CATEGORIES},
                           "n_closed": sum(c["n_closed"] for c in out),
                           "rows_excluded_null_pnl": sum(c["n_excluded_null_pnl"] for c in out),
                           "also_excluded": "backtest, superseded, reconciler pseudo-strategy, reset-flat, reduce legs"}}


_SERIES_MAX_DAYS = 400   # "all" is capped here (pnl_history.MAX_DAYS is 90 and serves the older flat route)


def _start_capital(conn: sqlite3.Connection, account_ids: List[str], start: datetime) -> Dict[str, Any]:
    """Sum over accounts of the balance at-or-before ``start``; first row after it when none earlier (flagged)."""
    total, n_ok, n_after = 0.0, 0, 0
    for aid in account_ids:
        row = conn.execute("SELECT balance FROM balance_snapshots WHERE account_id = ? AND api_ok = 1 AND balance IS NOT NULL "
                           "AND datetime(ts) <= datetime(?) ORDER BY datetime(ts) DESC LIMIT 1", (aid, start.isoformat())).fetchone()
        if row is None:
            row = conn.execute("SELECT balance FROM balance_snapshots WHERE account_id = ? AND api_ok = 1 AND balance IS NOT NULL "
                               "ORDER BY datetime(ts) ASC LIMIT 1", (aid,)).fetchone()
            n_after += row is not None
        if row is not None:
            total += float(row[0])
            n_ok += 1
    if not account_ids or n_ok < len(account_ids) or total <= 0:
        return {"usd": None, "read_state": "no_capital_record" if n_ok < len(account_ids) or not account_ids else "non_positive"}
    return {"usd": round(total, 4), "read_state": "first_snapshot_after_start" if n_after else "measured"}


@router.get("/performance/pnl-series")
def get_pnl_series(window: str = "30d", category: Optional[str] = None, account_id: Optional[str] = None,
                   strategy: Optional[str] = None, symbol: Optional[str] = None, asset_class: Optional[str] = None,
                   measured_only: bool = True) -> Dict[str, Any]:
    """Cumulative P&L per category: ``points[{date, pnl_usd, cum_pnl_usd, cum_pct|null, n, cum_pnl_all_rows_usd}]``.

    ``cum_pct`` is over the category's capital at window start (hourly ``balance_snapshots``); null -> the SPA draws $ only.
    ``measured_only`` (default true) skips non-MEASURED rows; the all-rows curve rides alongside. Last point's
    ``cum_pnl_usd`` equals ``/performance/categories`` ``measured_usd`` (or ``net_pnl_usd`` with measured_only=false)."""
    from src.core.instrument_class import asset_class_for_symbol
    if window not in _WINDOWS:
        raise HTTPException(status_code=400, detail=f"unknown window {window!r}; valid: {sorted(_WINDOWS)}")
    wanted = [c.strip() for c in category.split(",") if c.strip()] if category else list(pc.CATEGORIES)
    bad = [c for c in wanted if c not in pc.CATEGORIES]
    if bad:
        raise HTTPException(status_code=400, detail=f"unknown category {bad}; valid: {list(pc.CATEGORIES)}")
    now = datetime.now(timezone.utc)
    days = _WINDOWS[window] or _SERIES_MAX_DAYS
    start = now - timedelta(days=days)
    since = start.isoformat()
    as_of = now.isoformat()
    try:
        cats, _excluded = pc.categorize(_accounts())
    except Exception:  # noqa: BLE001  # allow-silent: an unreadable accounts.yaml is a stated read_state, not a 5xx
        logger.warning("performance/pnl-series: accounts.yaml unreadable", exc_info=True)
        return {"as_of": as_of, "window": window, "read_state": "accounts_unreadable", "series": [], "population": None}
    series: List[Dict[str, Any]] = []
    n_rows = 0
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            for cat in wanted:
                ids = [a for a in cats[cat] if not account_id or a == account_id]
                data = _prop_rows(ids, since) if cat == "prop" else _trade_rows(conn, ids, since)
                rows = [r for r in data["rows"]
                        if (not strategy or r.get("strategy_name") == strategy) and (not symbol or r.get("symbol") == symbol)
                        and (not asset_class or asset_class_for_symbol(r.get("symbol")) == asset_class)]
                cap = _start_capital(conn, ids, start) if ids else {"usd": None, "read_state": "no_accounts"}
                pts = pc.pnl_series(rows, category=cat, per_trade=(window == "7d"), measured_only=measured_only,
                                    start_capital=cap["usd"])
                n_rows += len(rows)
                series.append({"category": cat, "accounts": ids, "start_capital_usd": cap["usd"],
                               "capital_read_state": cap["read_state"], "n_rows": len(rows), "points": pts,
                               "read_state": "measured" if ids else "no_accounts"})
        finally:
            conn.close()
    except sqlite3.Error:
        logger.warning("performance/pnl-series: journal read failed", exc_info=True)
        return {"as_of": as_of, "window": window, "read_state": "journal_unreadable", "series": [], "population": None}
    return {"as_of": as_of, "window": window, "read_state": "measured", "measured_only": measured_only,
            "bucket": "trade" if window == "7d" else "utc_day", "series": series,
            "population": {"window": window, "since": since, "categories": wanted, "n_rows": n_rows,
                           "filters": {"account_id": account_id, "strategy": strategy, "symbol": symbol,
                                       "asset_class": asset_class},
                           "capital": "balance_snapshots at-or-before window start (prop and any account without a "
                                      "snapshot -> null, $ only)"}}
