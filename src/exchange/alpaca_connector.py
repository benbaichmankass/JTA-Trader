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
                logger.warning(
                    "alpaca: empty bars for %s %s (limit=%s feed=%s) — "
                    "returning None", symbol, timeframe, limit, self.feed,
                )
                return None
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("alpaca: get_ohlcv failed for %s %s (%s)", symbol, timeframe, exc)
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
                resp = requests.get(
                    f"{self.base_url}/v2/stocks/{symbol}/bars",
                    params=params,
                    headers={
                        "APCA-API-KEY-ID": self.api_key,
                        "APCA-API-SECRET-KEY": self.api_secret,
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                body = resp.json() or {}
            except Exception as exc:  # noqa: BLE001
                if page == 0:
                    raise
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
