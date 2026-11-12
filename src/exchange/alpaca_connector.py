"""Alpaca market-data connector — data-only (M15 Phase 1).

Read path for US stocks/ETFs bars via Alpaca's Market Data REST API
(https://data.alpaca.markets). Deliberately mirrors the
``get_ohlcv(symbol, timeframe, limit) -> DataFrame | None`` contract of
``BybitConnector`` so ``src.runtime.market_data.fetch_candles`` can use
it unchanged. **No order path** — execution wiring is M15 Phase 2 and
goes through the ``new-broker`` checklist (account package, integrator,
executor branch), not this module.

Uses plain ``requests`` (no alpaca-py dependency). Credentials come
from ``ALPACA_API_KEY_ID`` / ``ALPACA_API_SECRET_KEY`` (free paper
account keys work for data). ``ALPACA_DATA_FEED`` selects the feed
(default ``iex`` — the free real-time feed; ``sip`` needs the paid
consolidated plan).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_TIMEFRAME_MAP = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "2h": "2Hour",
    "4h": "4Hour",
    "1d": "1Day",
}

# Bar span in minutes, used to derive the explicit ``start`` lookback below.
_TIMEFRAME_MINUTES = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
}

# Calendar slack multipliers: intraday bars only print during the ~6.5h RTH
# session 5 days a week (24*7 / (6.5*5) ≈ 5.2 calendar-hours per session
# hour — use 6 for holidays); daily bars only need the weekend/holiday
# stretch (7/5 = 1.4 — use 1.6).
_INTRADAY_CALENDAR_FACTOR = 6.0
_DAILY_CALENDAR_FACTOR = 1.6
_LOOKBACK_BUFFER_DAYS = 10
# Bars pagination (row ML-ENTRY-ALPACA-BAR-PARITY): Alpaca's per-request cap, and a bound on pages per fetch.
_PAGE_LIMIT_MAX = 10000
_MAX_PAGES = 10
# Multi-symbol bars (row ML-EQ-ENTRY-TIMING): symbols per request (keeps the URL short), and a bound on pages per chunk. Pages come back far
# smaller than ``limit`` (MEASURED 2026-11-12: a ~235-day window for 100 ETFs did not finish in 200 pages), so this endpoint serves only the
# refresher's INCREMENTAL read (~32 bars per symbol); full-window seeds stay per symbol (ml_entry_eq_refresher.BarCache.update).
_MULTI_CHUNK = 100
_MULTI_MAX_PAGES = 200

# ── 429 / 5xx handling (PI-20261106-5A1BGFHC-0001; MEASURED RQ-20261106-d5a1-01 run 42145318852: one unpaced 173-symbol
# 1h pass made 217 calls, 104 returned 429 and 82 symbols came back EMPTY, because a first-page HTTPError was re-raised and
# get_ohlcv returned None -- a rate limit read as "no data").
#
# NON-BLOCKING, the pattern of #23580 (bybit_connector.RATE_LIMIT_COOLDOWN_S): this connector is called from BOTH the trading
# tick and the exit-evaluation thread (src/main.py::_build_monitor_ohlcv_fetcher -> connector_for_symbol routes every open
# Alpaca package's symbol here), so it must NEVER sleep in line -- an in-line backoff or a shared pacing queue would put Alpaca
# waits on the exit pass, the same class as the bybit sleep(15) that left a trade 115 s unevaluated. Instead:
#   * a 429 / 5xx starts ONE process-wide cooldown (Retry-After honoured, else _DEFAULT_COOLDOWN_S; capped at _MAX_COOLDOWN_S)
#     -- process-wide because the data limit is per key, not per instance;
#   * while it runs every Alpaca bars call returns at once with the NAMED read state ``rate_limited`` (no venue call, no sleep);
#   * a fetch never ends in a bare None that reads as "the venue had no bars": the state is recorded, counted and logged.
_DEFAULT_COOLDOWN_S = 10.0
_MAX_COOLDOWN_S = 60.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
READ_STATES = ("ok", "empty", "rate_limited", "could_not_look")

# Injectable for tests (never patched in production).
_now = time.monotonic

_STATE_LOCK = threading.Lock()
_cooldown = {"until": 0.0}
READ_STATE_COUNTS: Counter = Counter()


class AlpacaRateLimited(RuntimeError):
    """The data endpoint answered 429/5xx, or a cooldown from an earlier one is still running (no call was made)."""


def _cooldown_remaining() -> float:
    with _STATE_LOCK:
        return max(0.0, _cooldown["until"] - _now())


def _start_cooldown(seconds: float) -> bool:
    """Extend the shared cooldown; True only for the call that STARTED it (it logs the one line)."""
    now = _now()
    with _STATE_LOCK:
        started = _cooldown["until"] <= now
        _cooldown["until"] = max(_cooldown["until"], now + seconds)
    return started


def _retry_after_s(resp) -> float:
    try:
        ra = float(resp.headers.get("Retry-After"))
        if ra >= 0:
            return min(ra, _MAX_COOLDOWN_S)
    except (TypeError, ValueError, AttributeError):
        pass
    return _DEFAULT_COOLDOWN_S


def read_state_counts() -> dict:
    """Cumulative per-state fetch counts since process start (observability; never a gate)."""
    with _STATE_LOCK:
        return dict(READ_STATE_COUNTS)


def _lookback_start(timeframe_key: str, limit: int) -> str:
    """RFC-3339 ``start`` reaching back far enough to cover *limit* bars.

    Alpaca's ``/v2/stocks/{symbol}/bars`` defaults ``start`` to the
    beginning of the CURRENT day (docs.alpaca.markets/reference/stockbars),
    so omitting it returns at most today's bars — pre-market that is an
    empty list, and during the session a single partial daily bar. The
    daily ETF strategies need ~200 bars of history, so an explicit
    lookback window is required (M15 soak finding, 2026-06-11).
    """
    minutes = _TIMEFRAME_MINUTES[timeframe_key]
    factor = _DAILY_CALENDAR_FACTOR if minutes >= 1440 else _INTRADAY_CALENDAR_FACTOR
    span = timedelta(minutes=minutes * max(int(limit), 1) * factor)
    start = datetime.now(timezone.utc) - span - timedelta(days=_LOOKBACK_BUFFER_DAYS)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _bars_frame(bars: list) -> pd.DataFrame:
    """Alpaca bar dicts -> the canonical frame (``timestamp, open, high, low, close, volume``; tz-aware UTC, deduplicated, sorted).
    ONE builder for ``get_ohlcv`` and ``get_bars_multi`` so both paths hand callers identical frames for identical bars."""
    df = pd.DataFrame(
        [
            {
                "timestamp": b.get("t"),
                "open": b.get("o"),
                "high": b.get("h"),
                "low": b.get("l"),
                "close": b.get("c"),
                "volume": b.get("v"),
            }
            for b in bars
        ]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return (
        df.dropna(subset=["timestamp"])
        .drop_duplicates("timestamp", keep="last")   # a page boundary must never double a bar
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


class AlpacaMarketData:
    """Read-only OHLCV fetcher for US stocks/ETFs via Alpaca Data v2."""

    def __init__(self, api_key=None, api_secret=None, base_url=None, feed=None,
                 timeout: float = 10.0):
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY_ID", "")
        self.api_secret = api_secret or os.environ.get("ALPACA_API_SECRET_KEY", "")
        self.base_url = (base_url or os.environ.get(
            "ALPACA_DATA_URL", "https://data.alpaca.markets")).rstrip("/")
        self.feed = feed or os.environ.get("ALPACA_DATA_FEED", "iex")
        self.timeout = timeout
        # symbol -> the named read state of its LAST get_ohlcv (one of READ_STATES). None from get_ohlcv is ambiguous by
        # contract; this says which None it was.
        self.last_read_state: dict = {}

    def _record(self, symbol: str, state: str) -> None:
        self.last_read_state[symbol] = state
        with _STATE_LOCK:
            READ_STATE_COUNTS[state] += 1

    def _get(self, url: str, params: dict):
        """One GET, never a sleep. Raises AlpacaRateLimited while a cooldown runs (no call made) or when this call answers
        429/5xx (which starts the cooldown); otherwise returns the response for raise_for_status to judge."""
        left = _cooldown_remaining()
        if left > 0.0:
            raise AlpacaRateLimited(f"cooldown {left:.1f}s left (no call made)")
        resp = requests.get(
            url, params=params,
            headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret},
            timeout=self.timeout,
        )
        status = getattr(resp, "status_code", 200)   # raise_for_status still judges the answer
        if status in _RETRY_STATUSES:
            secs = _retry_after_s(resp)
            if _start_cooldown(secs):
                logger.warning("alpaca: HTTP %s on %s (thread=%s) -- Alpaca bars calls return read_state=rate_limited for "
                               "%.0f s (no in-line sleep)", status, url.rsplit("/", 2)[-2], threading.current_thread().name,
                               secs)
            raise AlpacaRateLimited(f"HTTP {status}; cooldown {secs:.0f}s")
        return resp

    def get_ohlcv(self, symbol: str, timeframe: str = "5m", limit: int = 100):
        """Return the most recent *limit* bars as a canonical DataFrame.

        Columns: ``timestamp, open, high, low, close, volume`` —
        timestamps are tz-aware UTC. Returns ``None`` on any error or
        empty response (the ``fetch_candles`` contract).
        """
        tf_key = str(timeframe).lower()
        tf = _TIMEFRAME_MAP.get(tf_key)
        if tf is None:
            logger.warning("alpaca: unsupported timeframe %r", timeframe)
            return None
        try:
            bars = self._bars_paged(symbol, tf, tf_key, int(limit))
            if not bars:
                self._record(symbol, "empty")
                logger.warning(
                    "alpaca: empty bars for %s %s (limit=%s feed=%s) — "
                    "returning None", symbol, timeframe, limit, self.feed,
                )
                return None
            df = _bars_frame(bars)
            self._record(symbol, "ok")
            return df
        except AlpacaRateLimited as exc:
            self._record(symbol, "rate_limited")
            logger.warning("alpaca: read_state=rate_limited %s %s (%s) — NOT 'no bars'; returning None",
                           symbol, timeframe, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            self._record(symbol, "could_not_look")
            logger.warning("alpaca: read_state=could_not_look get_ohlcv failed for %s %s (%s)", symbol, timeframe, exc)
            return None

    def _bars_paged(self, symbol: str, tf: str, tf_key: str, limit: int) -> list:
        """Up to ``limit`` most-recent bars, following ``next_page_token``.

        Alpaca can answer a page SHORT of ``limit`` and hand back a ``next_page_token`` for the rest; reading only the
        first page left ml_entry's ``limit=400`` 1h fetch with 203-267 bars on 7 of the 13 alpaca_paper ETFs at the
        2026-11-02 16:00Z decision (``insufficient_bars`` vs MIN_BARS 337; row ML-ENTRY-ALPACA-BAR-PARITY). Pages are
        read until ``limit`` bars are in hand, the token runs out, or ``_MAX_PAGES`` (a bound on venue calls). A page
        after the first that fails keeps the bars already read (logged); the first page failing raises to the caller."""
        out: list = []
        token = None
        start = _lookback_start(tf_key, limit)
        for page in range(_MAX_PAGES):
            params = {
                "timeframe": tf,
                "limit": max(1, min(limit - len(out), _PAGE_LIMIT_MAX)),
                # Explicit lookback — without it Alpaca only returns the
                # current day's bars (see _lookback_start docstring).
                "start": start,
                "adjustment": "split",
                "feed": self.feed,
                "sort": "desc",
            }
            if token:
                params["page_token"] = token
            try:
                resp = self._get(f"{self.base_url}/v2/stocks/{symbol}/bars", params)
                resp.raise_for_status()
                body = resp.json() or {}
            except Exception as exc:  # noqa: BLE001
                if page == 0:
                    raise   # AlpacaRateLimited propagates as itself -> read_state=rate_limited in get_ohlcv
                logger.warning("alpaca: page %d of %s %s failed (%s) — keeping %d bars already read",
                               page + 1, symbol, tf, exc, len(out))
                break
            out.extend(body.get("bars") or [])
            token = body.get("next_page_token")
            if len(out) >= limit or not token:
                break
        else:
            logger.warning("alpaca: %s %s stopped at %d pages with %d/%d bars", symbol, tf, _MAX_PAGES, len(out), limit)
            return out[:limit]
        if len(out) < limit:
            # the post-deploy observation reads this: a short frame with no token left is the venue's whole answer
            logger.info("alpaca: %s %s %d/%d bars after %d page(s), next_page_token=%s",
                        symbol, tf, len(out), limit, page + 1, "set" if token else "none")
        return out[:limit]

    def get_bars_multi(self, symbols, timeframe: str, start: str, chunk: int = _MULTI_CHUNK) -> tuple:
        """Bars for MANY symbols in a few requests: ``GET /v2/stocks/bars?symbols=A,B,...`` from ``start`` to now, every page
        (row ML-EQ-ENTRY-TIMING, Tier 2; the per-symbol ``get_ohlcv`` pass took ~11 min for 173 ETFs).

        Returns ``(frames, states)``: ``frames[symbol]`` is a canonical DataFrame (the ``get_ohlcv`` columns and cleaning) of EVERY bar the
        venue holds for that symbol in ``[start, now]``; ``states[symbol]`` is one of ``READ_STATES``. A chunk whose pages do not ALL read
        is dropped whole (``rate_limited`` / ``could_not_look``) -- a symbol cut mid-page would look complete. Never sleeps (the shared
        non-blocking cooldown applies), never raises."""
        tf_key = str(timeframe).lower()
        tf = _TIMEFRAME_MAP.get(tf_key)
        frames: dict = {}
        states: dict = {}
        syms = [str(s) for s in symbols]
        if tf is None:
            return frames, {s: "could_not_look" for s in syms}
        for i in range(0, len(syms), max(1, int(chunk))):
            part = syms[i:i + max(1, int(chunk))]
            bars: dict = {}
            token = None
            state = "ok"
            for _page in range(_MULTI_MAX_PAGES):
                params = {"symbols": ",".join(part), "timeframe": tf, "start": start, "limit": _PAGE_LIMIT_MAX,
                          "adjustment": "split", "feed": self.feed, "sort": "asc"}
                if token:
                    params["page_token"] = token
                try:
                    resp = self._get(f"{self.base_url}/v2/stocks/bars", params)
                    resp.raise_for_status()
                    body = resp.json() or {}
                except AlpacaRateLimited as exc:
                    state = "rate_limited"
                    logger.warning("alpaca: multi-bars read_state=rate_limited (%d symbols, %s) -- chunk dropped", len(part), exc)
                    break
                except Exception as exc:  # noqa: BLE001
                    state = "could_not_look"
                    logger.warning("alpaca: multi-bars read_state=could_not_look (%d symbols, %s) -- chunk dropped", len(part), exc)
                    break
                for sym, rows in (body.get("bars") or {}).items():
                    bars.setdefault(str(sym), []).extend(rows or [])
                token = body.get("next_page_token")
                if not token:
                    break
            else:
                state = "could_not_look"
                logger.warning("alpaca: multi-bars stopped at %d pages (%d symbols) -- chunk dropped", _MULTI_MAX_PAGES, len(part))
            for sym in part:
                if state != "ok":
                    self._record(sym, state)
                    states[sym] = state
                    continue
                rows = bars.get(sym) or []
                if not rows:
                    self._record(sym, "empty")
                    states[sym] = "empty"
                    continue
                frames[sym] = _bars_frame(rows)
                self._record(sym, "ok")
                states[sym] = "ok"
        return frames, states

    def get_price(self, symbol: str):
        """Latest trade price, or ``None`` on error."""
        try:
            resp = requests.get(
                f"{self.base_url}/v2/stocks/{symbol}/trades/latest",
                params={"feed": self.feed},
                headers={
                    "APCA-API-KEY-ID": self.api_key,
                    "APCA-API-SECRET-KEY": self.api_secret,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            trade = (resp.json() or {}).get("trade") or {}
            price = trade.get("p")
            return float(price) if price is not None else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("alpaca: get_price failed for %s (%s)", symbol, exc)
            return None
