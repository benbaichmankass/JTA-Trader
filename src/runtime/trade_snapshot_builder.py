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


#: A built-partial snapshot put back in the queue by a one-off re-queue (see :func:`requeue_alpaca_candle_partials`).
#: Its old payload stays in place, so the read route keeps serving the partial chart until a rebuild replaces it.
REQUEUED = "requeued"


def _due_sql(alias: str) -> str:
    return (f"({alias}.snapshot_key IS NULL OR {alias}.state = '{REQUEUED}' OR ({alias}.state = 'retrying' AND "
            f"({alias}.next_attempt_at IS NULL OR {alias}.next_attempt_at <= ?)))")


def pending(conn: sqlite3.Connection, now: datetime, limit: int) -> List[Dict[str, Any]]:
    """Closed trades with no built snapshot (or a retry that is due) whose framed window has ended, newest close
    first: ``trades`` rows (closed, not backtest) and prop trades (closed ``prop_fills`` rows). Each item carries
    ``_key`` (the store key), ``_attempts`` and, for prop, the resolved trade."""
    items: List[Dict[str, Any]] = []
    for r in conn.execute(
            f"SELECT t.*, s.attempts AS _attempts, s.state AS _state FROM trades t LEFT JOIN {store.TABLE} s "
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
    opened, closed = bh.parse_ts(trade.get("timestamp")), bh.parse_ts(trade.get("closed_at"))
    if opened is None or closed is None:
        # A clear error instead of "NoneType - datetime" (seen live on trade:6131): the row stays retrying, named.
        raise ValueError(f"unparseable_times: timestamp={trade.get('timestamp')!r} closed_at={trade.get('closed_at')!r}")
    tf = tcs.time_frame(opened, closed)
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
    conn.execute(f"INSERT OR REPLACE INTO main.{store.TABLE} ({names}) VALUES ({marks})", list(cols.values()))
    conn.commit()


def build_one(conn: sqlite3.Connection, trade: Dict[str, Any], fetch: Fetch, reviews: Dict[str, Any],
              receipts: Dict[str, Any], now: datetime) -> str:
    """Build + store one trade. Returns ``built`` / ``built_partial`` / ``retrying``. Never raises."""
    attempts = int(trade.get("_attempts") or 0) + 1
    requeued = trade.get("_state") == REQUEUED
    try:
        candles, source = candles_for(trade, fetch, now)
        if candles is None and requeued:
            # One attempt only for a re-queued row: if the venue still has no candles, the existing partial stays.
            _restore_requeued(conn, trade, "requeue: candles still unavailable")
            return "built_partial"
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
        if requeued:
            # Never wipe a stored partial because its optional rebuild failed: put the old row back as built.
            _restore_requeued(conn, trade, f"requeue failed: {err}"[:300])
            logger.warning("trade snapshot: requeued %s rebuild failed, kept the stored partial: %s", trade.get("_key"), err)
            return "built_partial"
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


def _restore_requeued(conn: sqlite3.Connection, trade: Dict[str, Any], note: str) -> None:
    """A re-queued row whose rebuild did not produce candles goes back to ``built`` with its stored payload."""
    try:
        conn.execute(f"UPDATE main.{store.TABLE} SET state = 'built', last_error = ? WHERE snapshot_key = ? "
                     f"AND state = '{REQUEUED}'", (note[:300], trade["_key"]))
        conn.commit()
    except sqlite3.Error:
        logger.warning("trade snapshot: could not restore requeued %s", trade.get("_key"), exc_info=True)


#: CLOSED-TRADE-SNAPSHOT-FUTURES-CANDLES (manager GO 2026-11-13 02:45Z): once #25565 gave Alpaca a historical
#: ``since`` read, the trades already stored as partial with ``candles_unavailable`` get ONE rebuild. Scope is
#: exactly: ``trade:`` rows, state ``built``, read_state ``partial``, payload candles state not ``measured``, on a
#: symbol whose instrument profile routes to Alpaca. Idempotent: recorded once in ``MIGRATIONS_TABLE``.
REQUEUE_ALPACA_CANDLES = "requeue_alpaca_candles_v1"
MIGRATIONS_TABLE = "trade_snapshot_migrations"


#: CLOSED-TRADE-SNAPSHOT-FUTURES-CANDLES (c): the same one-off re-queue for IB-routed symbols once IBMarketData
#: gained a historical ``since`` read. Its own marker, so it runs once even where the Alpaca one already ran.
REQUEUE_IB_CANDLES = "requeue_ib_candles_v1"
_IB_VENUES = ("interactive_brokers", "ib")


def _venue_symbols(venues: Tuple[str, ...]) -> set:
    """Symbols whose instrument profile routes candles to one of ``venues`` (``config/instruments.yaml``
    ``exchange``), read without building any connector (no venue socket is opened)."""
    from src.core.profile_loader import load_instrument_profiles
    out = set()
    for sym, prof in (load_instrument_profiles() or {}).items():
        if str(getattr(prof, "exchange", "") or "").strip().lower() in venues:
            out.add(sym)
    return out


def _alpaca_symbols() -> set:
    return _venue_symbols(("alpaca",))


def _routes_to(sym: Any, syms: set) -> bool:
    """``sym`` is in ``syms``, or is a futures contract month (``MHGN6``) whose root is -- the same grammar
    ``market_data.connector_for_symbol`` resolves when it routes the fetch."""
    import re
    s = str(sym or "").strip().upper()
    if s in syms:
        return True
    m = re.match(r"^([A-Z]{2,})([FGHJKMNQUVXZ]\d{1,2})$", s)
    return bool(m and m.group(1) in syms)


def requeue_alpaca_candle_partials(conn: sqlite3.Connection, alpaca_symbols: Optional[set] = None,
                                   now: Optional[datetime] = None) -> Optional[int]:
    """Put Alpaca-symbol partial snapshots that lack candles back in the queue, once. Returns the number re-queued,
    or None when the migration already ran. The stored payload is kept (the chart keeps serving until rebuilt);
    rebuilds go through the builder's normal path and its 1-per-10 s Alpaca pacing."""
    return _requeue_candle_partials(conn, REQUEUE_ALPACA_CANDLES,
                                    alpaca_symbols if alpaca_symbols is not None else _alpaca_symbols(), now)


def requeue_ib_candle_partials(conn: sqlite3.Connection, ib_symbols: Optional[set] = None,
                               now: Optional[datetime] = None) -> Optional[int]:
    """The IB-routed twin of :func:`requeue_alpaca_candle_partials` (1-per-15 s IB pacing)."""
    return _requeue_candle_partials(conn, REQUEUE_IB_CANDLES,
                                    ib_symbols if ib_symbols is not None else _venue_symbols(_IB_VENUES), now)


def _requeue_candle_partials(conn: sqlite3.Connection, name: str, syms: set,
                             now: Optional[datetime]) -> Optional[int]:
    conn.execute(f"CREATE TABLE IF NOT EXISTS main.{MIGRATIONS_TABLE} (name TEXT PRIMARY KEY, applied_at TEXT, "
                 "rows INTEGER)")
    if conn.execute(f"SELECT 1 FROM main.{MIGRATIONS_TABLE} WHERE name = ?", (name,)).fetchone():
        return None
    keys = []
    for key, payload, sym in conn.execute(
            f"SELECT s.snapshot_key, s.payload, t.symbol FROM main.{store.TABLE} s JOIN trades t "
            "ON s.snapshot_key = 'trade:' || t.id WHERE s.state = 'built' AND s.read_state = 'partial'").fetchall():
        if not _routes_to(sym, syms):
            continue
        doc = store.decode(payload)
        # the exact rule behind the "candles_unavailable" read-state reason (tcs.snapshot_read_state)
        if doc is not None and (doc.get("candles") or {}).get("state") not in (None, "measured"):
            keys.append(key)
    for key in keys:
        conn.execute(f"UPDATE main.{store.TABLE} SET state = '{REQUEUED}', attempts = 0, next_attempt_at = NULL "
                     "WHERE snapshot_key = ? AND state = 'built'", (key,))
    conn.execute(f"INSERT INTO main.{MIGRATIONS_TABLE} (name, applied_at, rows) VALUES (?, ?, ?)",
                 (name, _iso(now or datetime.now(timezone.utc)), len(keys)))
    conn.commit()
    logger.info("trade snapshot: %s re-queued %d partial snapshots without candles", name, len(keys))
    return len(keys)


def _snap_path_for(db_path: Path) -> Path:
    """The snapshot DB beside ``db_path`` (tests); production passes the canonical resolver's path."""
    return Path(db_path).parent / "trade_chart_snapshots.db"


def run_batch(db_path: Path, fetch: Fetch, now: Optional[datetime] = None, limit: int = BATCH,
              reviews: Optional[Dict[str, Any]] = None, receipts: Optional[Dict[str, Any]] = None,
              snap_path: Optional[Path] = None, requeue_symbols: Optional[set] = None) -> Dict[str, int]:
    """One batch (``requeue_symbols`` overrides the Alpaca symbol set for the one-off re-queue; tests only). ``db_path`` = ``trade_journal.db``, ATTACHed READ-ONLY; every write goes to ``snap_path``
    (``trade_chart_snapshots.db``), so this never opens a write transaction on the money DB."""
    from src.web.api import trade_decision_sources as srcs
    now = now or datetime.now(timezone.utc)
    counts = {"built": 0, "built_partial": 0, "retrying": 0}
    conn = store.snapshots_rw(str(snap_path or _snap_path_for(db_path)), journal_path=str(db_path))
    try:
        for name, fn in ((REQUEUE_ALPACA_CANDLES, requeue_alpaca_candle_partials),
                         (REQUEUE_IB_CANDLES, requeue_ib_candle_partials)):
            try:
                fn(conn, requeue_symbols, now=now)
            except Exception:  # noqa: BLE001  # allow-silent: an optional one-off; logged, the batch still runs
                logger.warning("trade snapshot: %s failed; will retry next batch", name, exc_info=True)
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


#: CLOSED-TRADE-SNAPSHOT-FUTURES-CANDLES (AM-UI 2026-11-12 Q10 option (b)): the builder's historical (``since``) reads
#: against Alpaca are paced to at most one per ``ALPACA_SINCE_MIN_INTERVAL_S``. The wait happens on the BUILDER's own
#: thread, never on the shared fetch executor (which also serves GET /api/bot/candles), and never in the trader process.
ALPACA_SINCE_MIN_INTERVAL_S = 10.0
_THROTTLED = object()
_alpaca_since_last = {"at": None}
_sleep = time.sleep
_mono = time.monotonic


#: The same pacing for IB historical reads (CLOSED-TRADE-SNAPSHOT-FUTURES-CANDLES (c), measured 2026-11-13): one per
#: 15 s = at most 40 per 10 min, under even IB's strict 60-per-10-min historical rule. The builder uses the web-api's
#: own read-only IB client, never the trader's.
IB_SINCE_MIN_INTERVAL_S = 15.0
_ib_since_last = {"at": None}


def _is_alpaca(client: Any) -> bool:
    from src.exchange.alpaca_connector import AlpacaMarketData
    return isinstance(client, AlpacaMarketData)


def _is_ib(client: Any) -> bool:
    from src.exchange.ib_connector import IBMarketData
    return isinstance(client, IBMarketData)


def _since_pace(client: Any) -> Optional[Tuple[Dict[str, Any], float]]:
    """``(last-call state, min interval)`` for a venue whose historical reads are paced; None = unpaced."""
    if _is_alpaca(client):
        return _alpaca_since_last, ALPACA_SINCE_MIN_INTERVAL_S
    if _is_ib(client):
        return _ib_since_last, IB_SINCE_MIN_INTERVAL_S
    return None


def web_api_fetch(symbol: str, interval: str, since_ms: Optional[int], limit: int) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Candles through the web-api's own market-data path, on its single IB-safe worker thread."""
    from src.web.api.routers import candles as cr
    paced: Dict[str, Any] = {"pace": None}

    def go() -> Any:
        from src.runtime.market_data import fetch_candles
        settings = cr._settings()
        client = cr._connector(symbol, settings)
        pace = _since_pace(client) if since_ms is not None else None
        if pace is not None:
            paced["pace"] = pace
            state, gap = pace
            last = state["at"]
            if last is not None and _mono() - last < gap:
                return _THROTTLED   # no venue call; the builder thread waits and resubmits
            state["at"] = _mono()
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

    for _ in range(3):
        out = cr._FETCH_EXECUTOR.submit(go).result(timeout=FETCH_TIMEOUT_S)
        if out is not _THROTTLED:
            return out, "bot-exchange"
        state, gap = paced["pace"]
        last = state["at"] or _mono()
        _sleep(max(0.0, gap - (_mono() - last)) + 0.05)
    return None, "bot-exchange"


_started = threading.Lock()
_thread: Optional[threading.Thread] = None


def _loop(db_path: Path, fetch: Fetch, snap_path: Optional[Path] = None) -> None:
    while True:
        try:
            STATUS["last_batch"] = run_batch(db_path, fetch, snap_path=snap_path)
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
        from src.utils.paths import trade_journal_db_path, trade_snapshots_db_path
        if db_path is None:
            db_path = Path(trade_journal_db_path())
        snap = Path(trade_snapshots_db_path())
        _thread = threading.Thread(target=_loop, args=(db_path, fetch or web_api_fetch, snap),
                                   name="trade-snapshot-builder", daemon=True)
        _thread.start()
        STATUS["started_at"] = _iso(datetime.now(timezone.utc))
        return True
