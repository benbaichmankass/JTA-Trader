"""Closed-trade chart snapshot WRITER + BACKFILL (UI-REDESIGN-2026-11 addendum 3; row CLOSED-TRADE-SNAPSHOT-WRITER).

Covers ``trades`` rows (exchange / paper accounts) AND prop trades (closed ``prop_fills`` rows), operator
direction relayed by AM-UI 2026-11-12 (PROP-UI-BRACKETS-CLOSED).

ONE loop does both jobs: every ``POLL_S`` it builds up to ``BATCH`` closed trades that have no snapshot yet and
whose framed window (close + 15% of the span) has ended, newest first. A new close is therefore built within one
poll of its window ending; the backlog of already-closed trades drains ``BATCH`` per poll. Idempotent per
``trades.id`` (a built row is never rebuilt; two processes racing write the same row).

Where it runs: a daemon thread in ``ict-web-api`` (started on app startup), NOT in the trader. It never touches
the trader process, the close path or an order: a close is never blocked or delayed by it. Candles come from the
web-api's own market-data path (``routers.candles``: its cached connectors, its dedicated IB clientId and its
single-worker IB thread), so it never contends for the trader's sockets.

Failure containment (Prime Directive rule 7, no halting): every trade is built inside its own try/except; a
failure writes ``state=retrying`` with a backoff and the loop moves on. A trade still failing after
``FLAG_AFTER`` attempts logs ONE error naming it and keeps retrying at the longest backoff. Candles that cannot be
read (a venue whose connector has no historical ``since`` read, or an outage) are retried
``CANDLE_RETRIES`` times, then the snapshot is stored WITHOUT candles (``candles.state: unavailable``), so the
brackets and decisions still show; that is a ``partial`` snapshot, said in ``partial_reasons``.
"""
from __future__ import annotations

import logging
import math
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.runtime import trade_snapshot_store as store
from src.web.api import brackets_history as bh
from src.web.api import trade_chart_snapshot as tcs

logger = logging.getLogger(__name__)

POLL_S = 120
BATCH = 20
BACKOFF_S = (300, 900, 3600, 6 * 3600, 24 * 3600)
FLAG_AFTER = 5
CANDLE_RETRIES = 3
FETCH_TIMEOUT_S = 60
MAX_LIMIT = 1000

#: ``fetch(symbol, interval, since_ms, limit) -> (rows | None, source)``; rows = ``[{time, open, high, low, close, volume}]``.
Fetch = Callable[[str, str, Optional[int], int], Tuple[Optional[List[Dict[str, Any]]], str]]

STATUS: Dict[str, Any] = {"started_at": None, "last_batch_at": None, "last_batch": None, "errors": 0}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _due_sql(alias: str) -> str:
    return (f"({alias}.snapshot_key IS NULL OR ({alias}.state = 'retrying' AND "
            f"({alias}.next_attempt_at IS NULL OR {alias}.next_attempt_at <= ?)))")


def pending(conn: sqlite3.Connection, now: datetime, limit: int) -> List[Dict[str, Any]]:
    """Closed trades with no built snapshot (or a retry that is due) whose framed window has ended, newest close
    first: ``trades`` rows (closed, not backtest) and prop trades (closed ``prop_fills`` rows). Each item carries
    ``_key`` (the store key), ``_attempts`` and, for prop, the resolved trade."""
    conn.execute(store.DDL)
    items: List[Dict[str, Any]] = []
    for r in conn.execute(
            f"SELECT t.*, s.attempts AS _attempts FROM trades t LEFT JOIN {store.TABLE} s "
            "ON s.snapshot_key = 'trade:' || t.id "
            "WHERE t.status = 'closed' AND t.closed_at IS NOT NULL AND COALESCE(t.is_backtest, 0) = 0 "
            f"AND {_due_sql('s')} ORDER BY t.id DESC LIMIT ?", (_iso(now), limit * 3)).fetchall():
        d = dict(r)
        d["_key"] = store.trade_key(d["id"])
        items.append(d)
    try:
        prop_rows = conn.execute(
            f"SELECT f.id AS fill_id, s.attempts AS _attempts FROM prop_fills f LEFT JOIN {store.TABLE} s "
            "ON s.snapshot_key = 'prop:' || f.id WHERE lower(f.status) = 'closed' "
            f"AND {_due_sql('s')} ORDER BY f.id DESC LIMIT ?", (_iso(now), limit * 3)).fetchall()
    except sqlite3.OperationalError as exc:   # no prop tables on this box: nothing to build, not an error
        if "no such table" not in str(exc):
            raise
        prop_rows = []
    for r in prop_rows:
        got = store.resolve_prop(conn, r[0])
        if got is None:
            continue
        opener, closer, ticket = got
        t = tcs.prop_trade(opener, closer or opener, ticket)
        t["_key"] = store.prop_key(r[0])
        t["_attempts"] = r[1]
        items.append(t)
    items.sort(key=lambda d: str(d.get("closed_at") or ""), reverse=True)
    out = []
    for d in items:
        end = tcs.window_end(d)
        if end is None or end <= now:   # no usable times -> built as a failure below, never skipped silently
            out.append(d)
        if len(out) >= limit:
            break
    return out


def _package(conn: sqlite3.Connection, pkg_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not pkg_id:
        return None
    r = conn.execute("SELECT * FROM order_packages WHERE order_package_id = ?", (pkg_id,)).fetchone()
    return dict(r) if r is not None else None


def candles_for(trade: Dict[str, Any], fetch: Fetch, now: datetime) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """The window's candles: a historical ``since`` read first; a connector without one gets the most recent
    bars, used only when they reach back to the window start (true for a fresh close, not an old backfill)."""
    tf = tcs.time_frame(bh.parse_ts(trade["timestamp"]), bh.parse_ts(trade["closed_at"]))
    step = bh._INTERVAL_S[tf["interval"]]
    need = int(math.ceil((tf["time_to"] - tf["time_from"]).total_seconds() / step)) + 2
    since_ms = int((tf["time_from"].timestamp() - step) * 1000)
    rows, source = fetch(trade["symbol"], tf["interval"], since_ms, min(need, MAX_LIMIT))
    if rows:
        return rows, source
    back = int(math.ceil((now - tf["time_from"]).total_seconds() / step)) + 2
    if back <= MAX_LIMIT:
        rows, source = fetch(trade["symbol"], tf["interval"], None, back)
        if rows and rows[0]["time"] <= tf["time_from"].timestamp():
            return rows, source
    return None, source


def _upsert(conn: sqlite3.Connection, trade: Dict[str, Any], **cols: Any) -> None:
    cols = {"snapshot_key": trade["_key"], "trade_id": trade.get("id"), "prop_fill_id": trade.get("prop_fill_id"),
            "order_package_id": trade.get("order_package_id"), "account_id": trade.get("account_id"), **cols}
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    conn.execute(f"INSERT OR REPLACE INTO {store.TABLE} ({names}) VALUES ({marks})", list(cols.values()))
    conn.commit()


def build_one(conn: sqlite3.Connection, trade: Dict[str, Any], fetch: Fetch, reviews: Dict[str, Any],
              receipts: Dict[str, Any], now: datetime) -> str:
    """Build + store one trade. Returns ``built`` / ``built_partial`` / ``retrying``. Never raises."""
    attempts = int(trade.get("_attempts") or 0) + 1
    try:
        candles, source = candles_for(trade, fetch, now)
        if candles is None and attempts < CANDLE_RETRIES:
            raise RuntimeError(f"candles_unavailable:{trade.get('symbol')}")
        pkg = _package(conn, trade.get("order_package_id"))
        payload = tcs.build_snapshot(trade, pkg, candles, source, reviews, receipts, now)
        rs, _ = tcs.snapshot_read_state(payload)
        _upsert(conn, trade, schema=tcs.SCHEMA, state="built", read_state=rs, attempts=attempts, last_error=None,
                next_attempt_at=None, built_at=_iso(now), payload=store.encode(payload))
        return "built" if rs == "measured" else "built_partial"
    except Exception as exc:  # noqa: BLE001  # allow-silent: contained per trade, stored as retrying + logged; flagged at FLAG_AFTER
        err = f"{type(exc).__name__}: {exc}"[:300]
        wait = BACKOFF_S[min(attempts - 1, len(BACKOFF_S) - 1)]
        try:
            _upsert(conn, trade, schema=tcs.SCHEMA, state="retrying", read_state=None, attempts=attempts,
                    last_error=err, next_attempt_at=_iso(now + timedelta(seconds=wait)), built_at=None, payload=None)
        except sqlite3.Error:
            logger.warning("trade snapshot: could not record retry for %s", trade.get("_key"), exc_info=True)
        if attempts == FLAG_AFTER:
            logger.error("trade snapshot: %s still failing after %d attempts (%s); retrying every %ds",
                         trade.get("_key"), attempts, err, BACKOFF_S[-1])
        else:
            logger.warning("trade snapshot: %s attempt %d failed: %s", trade.get("_key"), attempts, err)
        return "retrying"


def run_batch(db_path: Path, fetch: Fetch, now: Optional[datetime] = None, limit: int = BATCH,
              reviews: Optional[Dict[str, Any]] = None, receipts: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    from src.web.api import trade_decision_sources as srcs
    now = now or datetime.now(timezone.utc)
    counts = {"built": 0, "built_partial": 0, "retrying": 0}
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        todo = pending(conn, now, limit)
        if not todo:
            return counts
        reviews = reviews if reviews is not None else srcs.load_reviews()
        receipts = receipts if receipts is not None else srcs.load_receipts()
        for t in todo:
            counts[build_one(conn, t, fetch, reviews, receipts, now)] += 1
    finally:
        conn.close()
    return counts


def web_api_fetch(symbol: str, interval: str, since_ms: Optional[int], limit: int) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Candles through the web-api's own market-data path, on its single IB-safe worker thread."""
    from src.web.api.routers import candles as cr

    def go() -> Optional[List[Dict[str, Any]]]:
        from src.runtime.market_data import fetch_candles
        settings = cr._settings()
        client = cr._connector(symbol, settings)
        df = fetch_candles(symbol, interval, settings=settings, limit=limit, exchange_client=client,
                           since=since_ms, bypass_cache=True)
        if df is None or len(df) == 0:
            return None
        out = []
        for _, row in df.iterrows():
            t = cr._epoch_s(row.get("timestamp"))
            if t is None:
                continue
            try:
                out.append({"time": t, "open": float(row["open"]), "high": float(row["high"]),
                            "low": float(row["low"]), "close": float(row["close"]),
                            "volume": float(row.get("volume") or 0.0)})
            except (TypeError, ValueError, KeyError):
                continue
        out.sort(key=lambda c: c["time"])
        return out or None

    return cr._FETCH_EXECUTOR.submit(go).result(timeout=FETCH_TIMEOUT_S), "bot-exchange"


_started = threading.Lock()
_thread: Optional[threading.Thread] = None


def _loop(db_path: Path, fetch: Fetch) -> None:
    while True:
        try:
            STATUS["last_batch"] = run_batch(db_path, fetch)
            STATUS["last_batch_at"] = _iso(datetime.now(timezone.utc))
            if any(STATUS["last_batch"].values()):
                logger.info("trade snapshot batch: %s", STATUS["last_batch"])
        except Exception:  # noqa: BLE001  # allow-silent: the loop never dies (no halting); logged, next poll retries
            STATUS["errors"] += 1
            logger.warning("trade snapshot: batch failed", exc_info=True)
        time.sleep(POLL_S)


def start(db_path: Optional[Path] = None, fetch: Optional[Fetch] = None) -> bool:
    """Start the builder thread once per process. Returns False when already running."""
    global _thread
    with _started:
        if _thread is not None and _thread.is_alive():
            return False
        if db_path is None:
            from src.utils.paths import trade_journal_db_path
            db_path = Path(trade_journal_db_path())
        _thread = threading.Thread(target=_loop, args=(db_path, fetch or web_api_fetch),
                                   name="trade-snapshot-builder", daemon=True)
        _thread.start()
        STATUS["started_at"] = _iso(datetime.now(timezone.utc))
        return True
