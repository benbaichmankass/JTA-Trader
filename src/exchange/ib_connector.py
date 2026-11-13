"""Interactive Brokers market-data connector (MES candles via ib_insync).

Companion to ``src/units/accounts/ib_client.py`` (which owns *execution*).
This module owns *market data*: it exposes the same ``get_ohlcv(symbol,
timeframe, limit)`` surface as ``BybitConnector``
so it is a drop-in connector for ``src/runtime/market_data.fetch_candles``
and the per-symbol data routing in the multi-symbol pipeline.

Why a separate connector from IBClient:
    The repo separates per-exchange *market data* (``src/exchange/``)
    from per-account *execution* (``src/units/accounts/``). IBClient is
    the execution surface (orders/positions/balance, tied to a trading
    account). IBMarketData is the read-only candle surface, tied to a
    Gateway endpoint rather than an account. They share the underlying
    ib_insync connection through the ``get_ib_client`` registry, but use
    distinct ``clientId``s so a market-data request never contends with
    an order socket.

No API keys: like IBClient, the connection is the IB Gateway / TWS login
session (host + port + clientId). See ib_client.py for the full rationale.
ib_insync is imported lazily (with ib_async fallback) so this module
imports cleanly without the package installed.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from typing import Any, Optional

import pandas as pd

from src.units.accounts.ib_client import DEFAULT_IB_HOST, IBClient, get_ib_client

logger = logging.getLogger(__name__)

# Hard wall-clock cap (seconds) on a single IB historical-data request.
# WHY (2026-06-05 incident): a logged-out IB Gateway can ACCEPT the API
# socket (so IBClient.connect() succeeds within its own timeout) yet never
# return bars for reqHistoricalData — which, with no timeout, blocks the
# caller indefinitely. The bot's pipeline fetches market data inline on the
# single main-loop thread, so one hung IB fetch stalls the BTCUSDT/Bybit
# tick AND starves the liveness heartbeat. Bounding reqHistoricalData keeps
# a wedged/logged-out Gateway from ever blocking the live-money Bybit path:
# on timeout ib_insync returns the (empty) bars it has, get_ohlcv returns
# None, and fetch_candles degrades gracefully to its fallback. Override on
# the VM via IB_FETCH_TIMEOUT_S without a redeploy.
try:
    _IB_FETCH_TIMEOUT_S = float(os.environ.get("IB_FETCH_TIMEOUT_S", "") or 8.0)
except (TypeError, ValueError):
    _IB_FETCH_TIMEOUT_S = 8.0


# --- Single-thread pinning for every IB market-data request ----------------
#
# WHY (2026-08-14 incident, BL-20260814-IB-EVENTLOOP-CONTENTION): ib_insync
# resolves its event loop per sync call and the cached IB's socket transport
# LIVES ON ONE LOOP (see IBClient._ensure_event_loop's docstring: "dispatching
# a request on a different loop would hang instead of returning bars"). So
# every IB request in a process must run on ONE thread. The web-api already
# encodes this — src/web/api/routers/candles.py pins its fetches to a
# max_workers=1 pool and calls that "load-bearing".
#
# The trader had no such pin, and until the M20 exit-loop decouple it did not
# need one: exit evaluation ran INLINE on the tick thread, so the process had
# exactly one IB caller by construction. The decouple moved exit evaluation to
# a daemon thread, and both it and the main tick call get_ohlcv on the SAME
# cached IBClient (get_ib_client caches per host/port/client_id). IBClient's
# _usage_lock covers connect() but NOT reqHistoricalData, so the two threads
# drove one loop and produced, live:
#     IBMarketData.get_ohlcv failed for symbol=MES timeframe=5m:
#         This event loop is already running
# The same collisions time out the liveness probe, which trips the circuit
# breaker for IB_BREAKER_COOLDOWN_S (120s) — and the breaker suppresses ALL IB
# calls, so the blast radius is far wider than the racing fetch: candles go
# unavailable (MONITOR BLIND on open MGC/MES packages), strategy_builder raises
# for MGC/MES/MHG, and balance() returns None so new entries are refused with
# sizing_failed.
#
# TWO invariants are needed, and each covers a collision the other cannot.
#
#   1. PINNING (this executor) serialises market-data against market-data and
#      keeps every fetch on one thread. A plain lock cannot do this job: it
#      would still let thread B run the loop that thread A created, and the
#      transport is bound to that loop.
#   2. _usage_lock serialises market-data against the ACCOUNT/ORDER surface
#      (connect/place/close/balance/positions/has_protective_orders, which all
#      hold it). Pinning cannot do this job: those callers run on the tick and
#      exit threads by design, so the pinned thread and a lock-holding thread
#      would otherwise drive the one persistent `self._loop` concurrently —
#      which is precisely the "already running" condition, just reached from
#      the other side.
#
# The first version of this fix (PR #9240) shipped only invariant 1, because
# get_ohlcv was the surface that had actually failed in the 2026-08-14
# incident. That closed the half that was firing, not the class: a fetch on
# the pinned thread could still overlap a lock-held close() on the exit
# thread. _get_ohlcv_pinned therefore takes _usage_lock as well, so EVERY
# loop-driving operation in the process is mutually exclusive.
_IB_FETCH_THREAD_PREFIX = "ib-marketdata"
_IB_FETCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix=_IB_FETCH_THREAD_PREFIX
)

# How long a caller waits for the pinned thread. It covers QUEUE time (another
# thread's fetch ahead of us) plus our own bounded request, so it must exceed
# _IB_FETCH_TIMEOUT_S or a queued-but-healthy fetch would be discarded as a
# failure. Overridable on the VM without a redeploy; an unparseable value falls
# back to the derived default rather than disabling the wait.
try:
    _IB_FETCH_QUEUE_TIMEOUT_S = float(
        os.environ.get("IB_FETCH_QUEUE_TIMEOUT_S", "") or 0.0
    ) or (_IB_FETCH_TIMEOUT_S * 3.0 + 5.0)
except (TypeError, ValueError):
    _IB_FETCH_QUEUE_TIMEOUT_S = _IB_FETCH_TIMEOUT_S * 3.0 + 5.0


# How long the pinned fetch waits for the client's _usage_lock before giving
# up. BOUNDED on purpose: connect() can hold that lock for ~20s worst case
# (probe + retry + account warm-up + retry), and an unbounded wait here would
# back the single-worker queue up behind it — every later fetch would then miss
# its caller's _IB_FETCH_QUEUE_TIMEOUT_S while the worker sat blocked. Sized to
# outlast a worst-case connect() rather than to race it.
try:
    _IB_USAGE_LOCK_WAIT_S = float(
        os.environ.get("IB_USAGE_LOCK_WAIT_S", "") or 0.0
    ) or (_IB_FETCH_TIMEOUT_S * 3.0)
except (TypeError, ValueError):
    _IB_USAGE_LOCK_WAIT_S = _IB_FETCH_TIMEOUT_S * 3.0


# --- The per-pass IB circuit breaker's ONE signal (R2, 2026-09-10) ----------
#
# WHY A THREAD-LOCAL AND NOT A COUNTER. The exit-evaluation pass needs to know
# that ITS OWN fetch hit the pinned-thread queue timeout -- not that some fetch
# somewhere in the process did. A module counter would also be incremented by
# the tick thread, so a pass whose own IB fetch SUCCEEDED could still see a
# delta and trip. That is a widening of the operator-approved change: R2 is
# "once ONE IB-routed fetch IN THAT PASS has returned a queue timeout".
#
# The flag is set on the CALLING thread because that is where it happens:
# `future.result(timeout=...)` raises _FutureTimeout in the caller, never on
# the pinned worker. So the thread that observes the timeout is exactly the
# thread that asked, which is exactly the thread running the pass.
#
# THREE STATES, NEVER COLLAPSED, and this is why the reader is a distinct
# signal rather than "get_ohlcv returned None":
#   * queue timeout      -> flag set, get_ohlcv returns None  (the breaker's trigger)
#   * any OTHER failure  -> flag clear, get_ohlcv returns None (gateway down, an
#                           unknown symbol, a venue-side reqHistoricalData timeout)
#   * success            -> flag clear, DataFrame returned
# A breaker keyed on `None` alone would trip on all three, and the second is not
# congestion -- it is a fault whose retry cost is not 29s and whose remedy is
# different. Collapsing them is the class docs/CLAUDE-RULES-CANONICAL.md calls
# out under "Collapsed states".
_QUEUE_TIMEOUT_TLS = threading.local()


def _mark_queue_timeout() -> None:
    """Record that THIS thread just observed a pinned-thread queue timeout."""
    _QUEUE_TIMEOUT_TLS.hit = True


def consume_queue_timeout() -> bool:
    """Pop-and-clear this thread's pinned-thread queue-timeout flag.

    Returns True exactly once per observed timeout, on the thread that observed
    it. Read-and-clear rather than read-only so a flag set in pass N can never
    trip the breaker in pass N+1 -- a stale trip would skip IB packages on a
    healthy pass, which is a real degradation and not what was approved.

    Reading it is optional: nothing in ``get_ohlcv``'s contract depends on the
    flag being consumed, so a caller that never asks is byte-for-byte unaffected.
    """
    hit = bool(getattr(_QUEUE_TIMEOUT_TLS, "hit", False))
    _QUEUE_TIMEOUT_TLS.hit = False
    return hit


def _on_ib_fetch_thread() -> bool:
    """True when already running ON the pinned thread.

    Re-entrancy guard: submitting to a max_workers=1 pool from inside that
    pool's own worker would wait for a slot that cannot free until the caller
    returns — a self-deadlock. Running inline is correct there anyway, since
    being on that thread is exactly the property the pin exists to provide.
    """
    return threading.current_thread().name.startswith(_IB_FETCH_THREAD_PREFIX)


@contextlib.contextmanager
def _client_usage_lock(client: Any):
    """Hold the client's ``_usage_lock`` for the duration of a fetch.

    Yields True when the lock is held (or when the client exposes none — a
    stand-in or a non-IBClient, where there is no shared loop to protect and
    proceeding is correct), False when it could not be acquired in time.

    The two outcomes are kept DISTINCT rather than both surfacing as "no
    bars": "we could not get the lock" and "the venue has no data" are opposite
    statements, and the caller logs them differently for that reason.
    """
    lock = getattr(client, "_usage_lock", None)
    if lock is None:
        yield True
        return
    acquired = lock.acquire(timeout=_IB_USAGE_LOCK_WAIT_S)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


# Map the bot's timeframe vocabulary to IB ``barSizeSetting`` strings.
_BAR_SIZE = {
    "1m": "1 min",
    "2m": "2 mins",
    "3m": "3 mins",
    "5m": "5 mins",
    "15m": "15 mins",
    "30m": "30 mins",
    "1h": "1 hour",
    "2h": "2 hours",
    "4h": "4 hours",
    "1d": "1 day",
}

# Approximate seconds per timeframe, used to size the IB ``durationStr``.
_TF_SECONDS = {
    "1m": 60, "2m": 120, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400,
}


def _duration_str(timeframe: str, limit: int) -> str:
    """Return an IB ``durationStr`` covering at least *limit* bars.

    IB caps the seconds form at 86400 ("1 D"); above that it wants a day
    count. A small headroom factor absorbs non-trading gaps so the
    request still returns ``limit`` bars after IB drops closed-session
    periods.
    """
    secs = _TF_SECONDS.get(timeframe, 300) * max(int(limit), 1)
    secs = int(secs * 1.5) + 60  # headroom for session gaps
    if secs <= 86400:
        return f"{secs} S"
    days = (secs // 86400) + 1
    return f"{days} D"


def _since_end(timeframe: str, limit: int, since: Optional[int]):
    """``endDateTime`` for a historical read starting at ``since`` (epoch ms): ``""`` (now) without one, else the
    UTC datetime ``limit`` bars after it, capped at now (IB rejects a future end)."""
    if since is None:
        return ""
    from datetime import datetime, timezone
    end_s = int(since) / 1000.0 + _TF_SECONDS.get(timeframe, 300) * max(int(limit), 1)
    return datetime.fromtimestamp(min(end_s, datetime.now(timezone.utc).timestamp()), tz=timezone.utc)


class IBMarketData:
    """Read-only OHLCV connector for Interactive Brokers instruments.

    Parameters mirror :class:`IBClient` connection identity. Only ``MES``
    is wired (contract resolution lives in :class:`IBClient`); other
    symbols raise ``ValueError`` from the underlying contract builder.

    Parameters
    ----------
    host, port, client_id, account : see :class:`IBClient`.
        ``client_id`` should differ from the execution client's id so the
        data socket and the order socket coexist on the Gateway.
    use_rth : bool
        Regular-trading-hours only. Default False (include the full
        electronic session, matching crypto's 24/7 candle stream as
        closely as a futures session allows).
    market_data_type : int
        IB market-data mode passed to ``reqMarketDataType``: 1=live,
        2=frozen, 3=delayed, 4=delayed-frozen. **Defaults to 3 (delayed)**
        so the bot works WITHOUT a paid CME real-time subscription —
        suitable for strategy refinement + model training. Set to 1 once a
        live CME subscription is active for latency-sensitive execution.
    _client : IBClient, optional
        Test seam — inject a client with a fake ib_insync ``IB``.
    """

    def __init__(
        self,
        *,
        host: str = DEFAULT_IB_HOST,
        port: int,
        client_id: int,
        account: Optional[str] = None,
        use_rth: bool = False,
        market_data_type: int = 3,
        _client: Optional[IBClient] = None,
    ) -> None:
        self.use_rth = bool(use_rth)
        self.market_data_type = int(market_data_type)
        if _client is not None:
            self._client = _client
        else:
            self._client = get_ib_client(
                host=host, port=int(port), client_id=int(client_id), account=account,
            )

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]:
        """Return a candle DataFrame for *symbol* / *timeframe*.

        Columns: ``["timestamp", "open", "high", "low", "close",
        "volume"]`` — identical to the Bybit/Binance connectors so
        ``fetch_candles`` and the strategies consume IB candles unchanged.
        Returns ``None`` on any error (never raises) so the pipeline's
        per-symbol loop degrades gracefully when the Gateway is down.

        The request is executed on the process-wide pinned IB thread (see
        ``_IB_FETCH_EXECUTOR``) regardless of which thread calls, because the
        cached IB connection's socket transport is bound to a single loop.
        Callers are unaffected: this is still a blocking call returning the
        same value, and it still never raises.

        Deliberately NO ``since``: an old window of a future needs the contract
        that traded then, not today's front month (``get_ohlcv_at``). A
        ``fetch_candles(since=...)`` against this connector therefore still
        returns None (window uncovered) rather than mislabelled bars.
        """
        if _on_ib_fetch_thread():
            return self._get_ohlcv_pinned(symbol, timeframe, limit)
        try:
            future = _IB_FETCH_EXECUTOR.submit(
                self._get_ohlcv_pinned, symbol, timeframe, limit
            )
            return future.result(timeout=_IB_FETCH_QUEUE_TIMEOUT_S)
        except _FutureTimeout:
            # Degrade exactly like a venue timeout: the caller already handles
            # None. Distinct message so a queue starvation is never read as a
            # gateway fault — they need different fixes.
            #
            # Also raise the thread-local flag so a caller that wants to bound
            # the COST of a congested queue can see WHICH failure this was. The
            # return value is unchanged (None), so a caller that never reads the
            # flag behaves exactly as before.
            _mark_queue_timeout()
            logger.warning(
                "IBMarketData.get_ohlcv timed out waiting for the pinned IB "
                "thread (symbol=%s timeframe=%s, waited %.1fs) — another IB "
                "request is still in flight.",
                symbol, timeframe, _IB_FETCH_QUEUE_TIMEOUT_S,
            )
            return None
        except Exception as exc:  # noqa: BLE001 — never raise into the tick
            logger.warning(
                "IBMarketData.get_ohlcv dispatch failed for symbol=%s "
                "timeframe=%s: %s", symbol, timeframe, exc,
            )
            return None

    def get_ohlcv_at(self, symbol: str, timeframe: str, limit: int, since: int,
                     anchor_price: Optional[float] = None, anchor_ms: Optional[int] = None) -> tuple:
        """Historical bars of the CONTRACT the trade traded, for an old window: ``(DataFrame|None, info)``.
        See ``_ib_get_ohlcv_at`` (closed-trade snapshots only; the live tick never calls this)."""
        return _ib_get_ohlcv_at(self, symbol, timeframe, limit, since, anchor_price, anchor_ms)

    def _get_ohlcv_pinned(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> Optional[pd.DataFrame]:
        """The real fetch. MUST run on the pinned thread — see ``get_ohlcv``."""
        bar_size = _BAR_SIZE.get(timeframe)
        if bar_size is None:
            logger.warning("IBMarketData: unsupported timeframe %r", timeframe)
            return None
        try:
            # Invariant 2 (see the module header): exclude the account/order
            # surface, which drives this same persistent loop from the tick and
            # exit threads. Taken OUTSIDE connect() — _usage_lock is an RLock
            # and connect() re-takes it, so the nesting is safe on this thread.
            with _client_usage_lock(self._client) as got_lock:
                if not got_lock:
                    # NOT "no data" — we never asked the venue. Logged as its
                    # own cause so a saturated client is never read as a dead
                    # feed; the caller treats None as unavailable either way.
                    logger.warning(
                        "IBMarketData: could not acquire the IB client's usage "
                        "lock within %.1fs for symbol=%s timeframe=%s — the "
                        "account/order surface held it; deferring this fetch "
                        "(no request was sent to the venue)",
                        _IB_USAGE_LOCK_WAIT_S,
                        symbol,
                        timeframe,
                    )
                    return None
                ib = self._client.connect()
                # Re-assert the loop right before the data calls. connect()
                # already does this, but a Telegram alert (asyncio.run) firing
                # between connect() and here would null the current loop and
                # ib_insync's reqHistoricalData would raise "no current event
                # loop". Re-asserting the client's persistent loop (the one
                # this IB is bound to) keeps the sync request resolvable.
                self._client._ensure_event_loop()
                # Delayed mode (3) by default → no paid CME real-time feed
                # needed; IB serves free delayed futures bars. Best-effort:
                # older ib_insync builds always have reqMarketDataType.
                try:
                    ib.reqMarketDataType(self.market_data_type)
                except Exception:  # noqa: BLE001
                    pass
                contract = self._client._build_contract(symbol)
                # `timeout` is the hard cap that makes a logged-out/wedged
                # Gateway unable to block the (single-threaded) trading loop —
                # see _IB_FETCH_TIMEOUT_S above. On timeout ib_insync returns
                # whatever bars arrived (typically none), which we treat as a
                # graceful no-data result below.
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=_duration_str(timeframe, limit),
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=self.use_rth,
                    formatDate=2,
                    timeout=_IB_FETCH_TIMEOUT_S,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IBMarketData.get_ohlcv failed for symbol=%s timeframe=%s: %s",
                symbol, timeframe, exc,
            )
            return None

        if not bars:
            return None
        rows = []
        for b in bars:
            ts = getattr(b, "date", None)
            rows.append({
                "timestamp": pd.to_datetime(ts) if ts is not None else pd.NaT,
                "open": getattr(b, "open", None),
                "high": getattr(b, "high", None),
                "low": getattr(b, "low", None),
                "close": getattr(b, "close", None),
                "volume": getattr(b, "volume", None),
            })
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        if len(df) > limit:
            df = df.iloc[-limit:].reset_index(drop=True)
        return df


# ─────────────────────── historical read for an OLD window (closed-trade snapshots)
#
# CLOSED-TRADE-SNAPSHOT-FUTURES-CANDLES (c), manager GO 2026-11-13 03:25Z. An old trade's window needs the
# CONCRETE contract the trade traded, not today's front month: IB refuses an endDateTime on a continuous future, and
# a pre-roll trade on today's front month would chart a different contract whose prices are offset from the fill.
# So: list the root's contracts once (includeExpired), try the nearest expiry at/after the trade's open and the one
# after it, and accept only the contract whose bars around the entry CONTAIN the fill price. Never touches the
# client's cached front-month contract (``IBClient._contract``), which live chart reads use.
#
# Pacing (IB historical limits are per gateway/account, and the trader shares this gateway): the CALLER paces calls
# (``trade_snapshot_builder.IB_SINCE_MIN_INTERVAL_S``); here, any error 162 or 420 seen on a request starts a
# ``PACING_BACKOFF_S`` backoff during which ``get_ohlcv_at`` sends nothing and answers ``deferred``.

PACING_BACKOFF_S = 600.0
_PACING = {"until": 0.0, "last": None}
_EXPIRIES_TTL_S = 6 * 3600.0
_EXPIRIES: dict = {}
_PRICE_TOL = 0.002          # 0.2 %: the entry fill must sit inside the bars around entry, widened by this
_ANCHOR_BARS = 2            # bars either side of the entry bar checked for the fill


def _now_mono() -> float:
    import time
    return time.monotonic()


def pacing_backoff_remaining() -> float:
    """Seconds left on the historical-read backoff (0 when none)."""
    return max(0.0, _PACING["until"] - _now_mono())


def _note_pacing(code: int, msg: str) -> None:
    _PACING["until"] = _now_mono() + PACING_BACKOFF_S
    _PACING["last"] = {"code": code, "msg": str(msg)[:200]}
    logger.warning("IBMarketData: historical read got error %s (%s) -- backing off IB since-reads for %.0fs",
                   code, str(msg)[:120], PACING_BACKOFF_S)


def _is_no_data(msg: Any) -> bool:
    """IB error 162 text for an empty historical answer (not a pacing problem)."""
    return "returned no data" in str(msg or "").lower()


def _split_month(symbol: str) -> tuple:
    """``MHGN6`` -> (``MHG``, ``202607``); ``MGC`` -> (``MGC``, None). Same grammar as connector_for_symbol."""
    import re
    s = str(symbol or "").strip().upper()
    m = re.match(r"^([A-Z]{2,})([FGHJKMNQUVXZ])(\d{1,2})$", s)
    if not m:
        return s, None
    month = "FGHJKMNQUVXZ".index(m.group(2)) + 1
    yy = int(m.group(3))
    year = 2020 + yy if yy < 10 else 2000 + yy
    return m.group(1), f"{year:04d}{month:02d}"


def _bars_contain(df: pd.DataFrame, anchor_price: float, anchor_ms: int, step_s: int) -> bool:
    """True when the bars within ``_ANCHOR_BARS`` of the entry bar span the entry fill (widened by _PRICE_TOL)."""
    if df is None or not len(df) or anchor_price is None:
        return False
    ts = pd.to_datetime(df["timestamp"], utc=True)
    a = pd.Timestamp(int(anchor_ms), unit="ms", tz="UTC")
    w = pd.Timedelta(seconds=step_s * (_ANCHOR_BARS + 1))
    near = df[(ts >= a - w) & (ts <= a + w)]
    if not len(near):
        return False
    lo, hi = float(near["low"].min()), float(near["high"].max())
    p = float(anchor_price)
    return lo * (1 - _PRICE_TOL) <= p <= hi * (1 + _PRICE_TOL)


def _candidates(expiries: list, month: Optional[str], anchor_ms: int) -> list:
    """Contracts to try, in order: the explicit month when the symbol names one; else the nearest two whose last
    trade date is on/after the trade's open."""
    from datetime import datetime, timezone
    if month:
        return [e for e in expiries if e["month"] == month][:1]
    day = datetime.fromtimestamp(int(anchor_ms) / 1000.0, tz=timezone.utc).strftime("%Y%m%d")
    return [e for e in expiries if e["last"] >= day][:2]


def _ib_get_ohlcv_at(self, symbol: str, timeframe: str, limit: int, since: int,
                     anchor_price: Optional[float], anchor_ms: Optional[int]) -> tuple:
    """``(DataFrame|None, info)`` for an OLD window of futures *symbol*; see the block comment above.

    ``info``: ``{"outcome": matched|price_mismatch|no_contract|no_bars|deferred|error|unsupported,
    "contract": YYYYMM|None, "tried": [YYYYMM...], "requests": n}``. Never raises."""
    info = {"outcome": "error", "contract": None, "tried": [], "requests": 0}
    if pacing_backoff_remaining() > 0:
        info["outcome"] = "deferred"
        return None, info
    if _on_ib_fetch_thread():
        return _ib_get_ohlcv_at_pinned(self, symbol, timeframe, limit, since, anchor_price, anchor_ms, info)
    try:
        fut = _IB_FETCH_EXECUTOR.submit(_ib_get_ohlcv_at_pinned, self, symbol, timeframe, limit, since,
                                        anchor_price, anchor_ms, info)
        return fut.result(timeout=_IB_FETCH_QUEUE_TIMEOUT_S * 2)
    except Exception as exc:  # noqa: BLE001  # allow-silent: never raise into the builder; outcome=error names it
        info["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return None, info


def _ib_get_ohlcv_at_pinned(self, symbol, timeframe, limit, since, anchor_price, anchor_ms, info) -> tuple:
    from src.units.accounts.ib_instruments import ib_instrument_spec
    bar_size = _BAR_SIZE.get(timeframe)
    root, month = _split_month(symbol)
    try:
        spec = ib_instrument_spec(root)
    except ValueError as exc:
        info.update(outcome="unsupported", error=str(exc)[:200])
        return None, info
    if bar_size is None or spec.sec_type != "FUT":
        info["outcome"] = "unsupported"
        return None, info
    step_s = _TF_SECONDS.get(timeframe, 300)
    anchor = int(anchor_ms if anchor_ms is not None else since)
    try:
        with _client_usage_lock(self._client) as got_lock:
            if not got_lock:
                info["outcome"] = "deferred"
                return None, info
            ib = self._client.connect()
            self._client._ensure_event_loop()
            try:
                from ib_insync import Future  # type: ignore
            except ImportError:
                from ib_async import Future  # type: ignore
            cached = _EXPIRIES.get(root)
            if cached is None or _now_mono() - cached[0] > _EXPIRIES_TTL_S:
                details = ib.reqContractDetails(Future(symbol=root, exchange=spec.exchange,
                                                       currency=spec.currency or "USD", includeExpired=True))
                info["requests"] += 1
                rows = []
                for d in details or []:
                    c = getattr(d, "contract", None)
                    last = str(getattr(c, "lastTradeDateOrContractMonth", "") or "")[:8]
                    mon = str(getattr(d, "contractMonth", "") or last[:6])[:6]
                    if c is not None and getattr(c, "conId", 0) and len(last) == 8:
                        rows.append({"conId": c.conId, "last": last, "month": mon})
                cached = (_now_mono(), sorted(rows, key=lambda r: r["last"]))
                _EXPIRIES[root] = cached
            cands = _candidates(cached[1], month, anchor)
            if not cands:
                info["outcome"] = "no_contract"
                return None, info
            end_dt = _since_end(timeframe, limit, since)
            outcome = "no_bars"
            for c in cands:
                info["tried"].append(c["month"])
                contract = Future(conId=c["conId"], exchange=spec.exchange, includeExpired=True)
                errs: list = []

                def _on_err(*a, _errs=errs):
                    # ib_insync errorEvent: (reqId, errorCode, errorString, contract)
                    if len(a) >= 3:
                        _errs.append((a[1], a[2]))
                ib.errorEvent += _on_err
                try:
                    bars = ib.reqHistoricalData(contract, endDateTime=end_dt,
                                                durationStr=_duration_str(timeframe, limit), barSizeSetting=bar_size,
                                                whatToShow="TRADES", useRTH=self.use_rth, formatDate=2,
                                                timeout=_IB_FETCH_TIMEOUT_S)
                finally:
                    ib.errorEvent -= _on_err
                info["requests"] += 1
                # IB reuses 162 for "HMDS query returned no data" (e.g. an expired month with no bars in the window):
                # that is an empty answer for THIS contract, not pacing -- try the next one. Every other 162
                # (pacing violation, query cancelled on our timeout) and any 420 still backs off (MEASURED 2026-11-13
                # 05:0xZ: two MGCV6 no-data 162s each started a 600 s backoff and left the trade re-queued forever).
                bad = [(code, msg) for code, msg in errs if code == 420 or (code == 162 and not _is_no_data(msg))]
                if bad:
                    _note_pacing(*bad[0])
                    info["outcome"] = "deferred"
                    return None, info
                df = _bars_frame(bars)
                if df is None:
                    continue
                if _bars_contain(df, anchor_price, anchor, step_s):
                    ts = pd.to_datetime(df["timestamp"], utc=True)
                    df = df[ts >= pd.Timestamp(int(since), unit="ms", tz="UTC")].reset_index(drop=True)
                    if not len(df):
                        continue
                    info.update(outcome="matched", contract=c["month"])
                    return df.iloc[:limit].reset_index(drop=True), info
                outcome = "price_mismatch"
            info["outcome"] = outcome
            return None, info
    except Exception as exc:  # noqa: BLE001  # allow-silent: never raise into the builder; outcome=error names it
        info.update(outcome="error", error=f"{type(exc).__name__}: {exc}"[:200])
        logger.warning("IBMarketData.get_ohlcv_at failed for %s %s: %s", symbol, timeframe, exc)
        return None, info


def _bars_frame(bars) -> Optional[pd.DataFrame]:
    if not bars:
        return None
    rows = [{"timestamp": pd.to_datetime(getattr(b, "date", None)) if getattr(b, "date", None) is not None else pd.NaT,
             "open": getattr(b, "open", None), "high": getattr(b, "high", None), "low": getattr(b, "low", None),
             "close": getattr(b, "close", None), "volume": getattr(b, "volume", None)} for b in bars]
    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])

