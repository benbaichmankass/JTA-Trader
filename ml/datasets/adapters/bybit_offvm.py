"""Bybit-V5 off-VM adapter for `market_raw` (S-AI-WS5-B-PART-1 + PART-2).

**Off-VM only.** Refuses to run unless the operator has set
`ICT_OFFVM_BUILD_HOST=1`. The Oracle live VM must NEVER set this
env var; market_raw builds are meant to run on a separate build
host (developer laptop, HF Space, GitHub Actions runner with
operator-supplied creds).

WS9 rule: heavy market-data pulls do not belong on the live trading
VM. This adapter exists so the regime classifier (WS5-B-PART-2) can
build historical bars from Bybit V5 klines on a build host.

Sprint history:
- S-AI-WS5-B-PART-1 — class + env-gate + `NotImplementedError` on
  the actual fetch path.
- S-AI-WS5-B-PART-2 (PR 2A) — `_fetch_bars(...)` wired via ccxt's
  Bybit V5 connector. Time-range pagination (`since`, `limit`) over
  `[start, end]`; canonical row normalisation; credentials sourced
  from env (`BYBIT_API_KEY` / `BYBIT_API_SECRET`); klines endpoint
  is public so anonymous fallback is supported. Tests mock the
  exchange object via `_build_exchange` so CI never touches the
  network.
"""
from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from typing import Any, ClassVar

from .base import MarketRawAdapter

OFFVM_ENV = "ICT_OFFVM_BUILD_HOST"
OFFVM_EXPECTED = "1"

# ccxt timeframe tokens we accept. Bybit-via-ccxt accepts these
# tokens directly; mapping to bar-length-in-ms is also used to
# advance the pagination cursor when a page comes back empty so we
# don't loop forever on a stale `since`.
_TIMEFRAME_MS: Mapping[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

# ccxt's bybit fetch_ohlcv default page size; 1000 is the documented
# Bybit V5 max per request.
_PAGE_LIMIT = 1000

# Retry budget per page: 7 attempts, backoff 1,2,4,...,60 s (~2 min max).
_MAX_ATTEMPTS = 7

# An empty page before `end`: re-fetch the same cursor this many times, then
# step forward by whole pages at most this many times before giving up (a
# genuine listing gap longer than 30 pages is not something a daily rebuild
# should paper over silently; the completeness check below then fails it).
_EMPTY_PAGE_RETRIES = 3
_MAX_EMPTY_PAGE_SKIPS = 30

# A fetch whose last bar is further than this many bars before `end` did not
# finish; the adapter raises instead of letting the builder write it as `ok`.
# 2 pages leaves room for the exchange's own publication lag at any timeframe.
_SHORT_FETCH_BARS = 2 * _PAGE_LIMIT

# ccxt exception CLASS names that are transient by construction.
_TRANSIENT_CLASS_KEYS = ("RateLimit", "DDoS", "Network", "Timeout", "ExchangeNotAvailable")

# Bybit V5 retCodes that are server-side transients but surface as a plain
# ``ccxt.ExchangeError`` (class name carries nothing). From Bybit's V5 error
# table: 10016 "Server error" / "svc error: Get kline failed", 10002 "Request
# not authorized -- timestamp / request timeout" (clock-skew + timeout class).
_TRANSIENT_RET_CODES = ("10016", "10002")


def _is_transient(exc: BaseException) -> bool:
    """Is this fetch failure worth retrying?

    True for the transient ccxt classes (rate limit, DDoS guard, network,
    timeout, exchange-unavailable) AND for a plain ``ExchangeError`` whose
    message carries one of Bybit's transient retCodes. Everything else --
    bad symbol, auth, a programming error -- is NOT transient and must
    surface on the first attempt.
    """
    name = type(exc).__name__
    if any(k in name for k in _TRANSIENT_CLASS_KEYS):
        return True
    msg = str(exc)
    return any(
        f'"retCode":{code}' in msg or f'"retCode": {code}' in msg or f"retCode={code}" in msg
        for code in _TRANSIENT_RET_CODES
    )


class OffVmGuardrailViolation(RuntimeError):
    """Raised when the off-VM adapter tries to run on (or as if on) the live VM."""


def _iso_to_ms(iso_str: str) -> int:
    """Parse ISO 8601 (with optional `Z`) to ms epoch UTC.

    Accepts both `2025-01-01` (date only, treated as 00:00 UTC) and
    `2025-01-01T00:00:00Z` / `2025-01-01T00:00:00+00:00`. Naive
    datetimes are treated as UTC. Raises ValueError on parse failure.
    """
    text = iso_str.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def _ms_to_iso(ms: int) -> str:
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


class BybitOffvmMarketRawAdapter(MarketRawAdapter):
    source: ClassVar[str] = "bybit_v5_offvm"

    def iter_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        api_key: str | None = None,
        api_secret: str | None = None,
        testnet: bool | None = None,
        pause_s: float = 0.0,
        **_: Any,
    ) -> Iterator[Mapping[str, Any]]:
        self._enforce_offvm()
        # CLI family-args may arrive as strings; coerce defensively so the
        # `pause > 0` throttle check never hits a str-vs-int TypeError.
        pause = float(pause_s or 0.0)

        if timeframe not in _TIMEFRAME_MS:
            raise ValueError(
                f"unsupported timeframe {timeframe!r}; "
                f"known: {sorted(_TIMEFRAME_MS)}"
            )
        bar_ms = _TIMEFRAME_MS[timeframe]
        start_ms = _iso_to_ms(start)
        end_ms = _iso_to_ms(end)
        if end_ms <= start_ms:
            raise ValueError(
                f"end {end!r} must be after start {start!r}"
            )

        exchange = self._build_exchange(
            api_key=api_key if api_key is not None else os.environ.get("BYBIT_API_KEY"),
            api_secret=(
                api_secret if api_secret is not None
                else os.environ.get("BYBIT_API_SECRET")
            ),
            testnet=testnet if testnet is not None else _read_testnet_flag(),
        )

        cursor = start_ms
        last_cursor = -1
        empty_streak = 0
        last_bar_ms: int | None = None
        while cursor < end_ms:
            if cursor == last_cursor:
                # Defensive: stale `since` (exchange returned the same
                # boundary twice). Advance one bar so we don't spin.
                cursor += bar_ms
                continue
            last_cursor = cursor
            # Retry with exponential backoff on transient errors (Bybit
            # retCode 10006 RateLimitExceeded, DDoS guard, network blips) so
            # a deep multi-million-bar pull (e.g. years of 1m) survives the
            # exchange's per-minute cap instead of aborting mid-stream.
            #
            # Bybit's SERVER-SIDE transient ("retCode":10016 "svc error: Get
            # kline failed", and 10002 request-timeout) arrives as a plain
            # ccxt ``ExchangeError`` -- a class name the list above never
            # matched, so ONE such page aborted the whole shard. MEASURED on
            # the trainer (dataset_builds.jsonl, trainer-vm-diag #18882): 12
            # ``market_raw`` failures 2026-10-13..18, every one retCode 10016,
            # every one on the first try. Transient-by-message is retried
            # the same way; everything else still raises immediately.
            page = None
            last_exc: Exception | None = None
            for _attempt in range(_MAX_ATTEMPTS):
                try:
                    page = exchange.fetch_ohlcv(
                        symbol, timeframe=timeframe, since=cursor, limit=_PAGE_LIMIT,
                    )
                    break
                except Exception as exc:
                    if _is_transient(exc) and _attempt < _MAX_ATTEMPTS - 1:
                        last_exc = exc
                        delay = min(2 ** _attempt, 60)
                        print(
                            f"bybit_offvm: transient {type(exc).__name__} on "
                            f"{symbol} {timeframe} since={cursor} "
                            f"(attempt {_attempt + 1}/{_MAX_ATTEMPTS}, retry in {delay}s): "
                            f"{str(exc)[:160]}",
                            file=sys.stderr,
                        )
                        time.sleep(delay)
                        continue
                    raise
            else:  # pragma: no cover - the loop only falls through after re-raising
                raise last_exc  # type: ignore[misc]
            if not page:
                # An EMPTY page before `end` is NOT end-of-data. MEASURED on the
                # trainer (trainer-vm-diag #18889, 2026-10-18): shards cut at an
                # exact multiple of the 1000-row page and rebuilt that way every
                # night -- BTCUSDT 1h 27,000 rows ending 2024-11-15, ETHUSDT 1h
                # 24,000 ending 2024-07-13, BTCUSDT 5m 105,000 ending 2022-10-17,
                # ADAUSDT 15m 149,000 ending 2026-01-16 -- while SOLUSDT 1h over
                # the same window is whole (43,824). `break` here wrote each of
                # those as an `ok` build (row ML-SHARD-TRUNCATED). Retry the same
                # cursor a few times, then step one page forward and keep going;
                # the completeness check after the loop refuses a short fetch.
                empty_streak += 1
                if empty_streak <= _EMPTY_PAGE_RETRIES:
                    print(
                        f"bybit_offvm: empty page on {symbol} {timeframe} since={_ms_to_iso(cursor)} "
                        f"before end (attempt {empty_streak}/{_EMPTY_PAGE_RETRIES}); retrying",
                        file=sys.stderr,
                    )
                    time.sleep(min(2 ** empty_streak, 30))
                    last_cursor = -1   # re-fetch the SAME cursor
                    continue
                if empty_streak > _EMPTY_PAGE_RETRIES + _MAX_EMPTY_PAGE_SKIPS:
                    break
                print(
                    f"bybit_offvm: empty page on {symbol} {timeframe} since={_ms_to_iso(cursor)} "
                    f"persists; stepping one page ({_PAGE_LIMIT} bars) forward",
                    file=sys.stderr,
                )
                cursor += _PAGE_LIMIT * bar_ms
                continue
            empty_streak = 0
            advanced = False
            for candle in page:
                # ccxt OHLCV row is [ts_ms, open, high, low, close, volume].
                ts_ms = int(candle[0])
                if ts_ms < cursor:
                    # Defensive: drop bars before our cursor (the API
                    # occasionally returns a pre-window prefix).
                    continue
                if ts_ms >= end_ms:
                    return
                yield {
                    "ts": _ms_to_iso(ts_ms),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]) if candle[5] is not None else 0.0,
                    "source": self.source,
                }
                advanced = True
                last_bar_ms = ts_ms
                cursor = ts_ms + bar_ms
            if not advanced:
                # Page came back but every bar was filtered out.
                # Step one bar to avoid an infinite loop.
                cursor += bar_ms
            if pause > 0:
                # Extra throttle on top of ccxt's enableRateLimit so a deep
                # multi-year pull stays gentle on the public API.
                time.sleep(pause)
        # Completeness: a fetch that stopped more than `_SHORT_FETCH_BARS` bars
        # before `end` is a FAILED build, never an `ok` one. The old shard stays
        # in place because the builder writes to a temp file and renames on
        # success (ml/datasets/builder.py). A symbol listed after `start` still
        # passes (Bybit returns its first bars for an early `since`); a symbol
        # with no data at all raises here rather than writing an empty shard.
        if last_bar_ms is None or (end_ms - last_bar_ms) > _SHORT_FETCH_BARS * bar_ms:
            last_txt = _ms_to_iso(last_bar_ms) if last_bar_ms is not None else "none"
            raise RuntimeError(
                f"bybit_offvm: fetch for {symbol} {timeframe} ended at {last_txt}, more than "
                f"{_SHORT_FETCH_BARS} bars before end {_ms_to_iso(end_ms)} -- refusing to write a "
                "truncated shard (ML-SHARD-TRUNCATED)"
            )

    @classmethod
    def _build_exchange(
        cls,
        *,
        api_key: str | None,
        api_secret: str | None,
        testnet: bool,
    ) -> Any:
        """Construct a ccxt Bybit client. Tests monkeypatch this hook.

        Lazy-imports ccxt so a build host without ccxt installed can
        still hit the env-gate guardrail without an ImportError, and
        so tests that monkeypatch this method don't need ccxt either.
        """
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError(
                "ccxt is required for BybitOffvmMarketRawAdapter live fetch; "
                "install with `pip install ccxt` on the build host."
            ) from e
        exchange = ccxt.bybit({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
        })
        if testnet:
            exchange.set_sandbox_mode(True)
        return exchange

    @staticmethod
    def _enforce_offvm() -> None:
        if os.environ.get(OFFVM_ENV, "") != OFFVM_EXPECTED:
            raise OffVmGuardrailViolation(
                f"BybitOffvmMarketRawAdapter requires {OFFVM_ENV}={OFFVM_EXPECTED} "
                "to run. This adapter MUST NOT run on the Oracle live VM. "
                "Set the env var only on a build host that is not the live VM."
            )


def _read_testnet_flag() -> bool:
    return os.environ.get("BYBIT_TESTNET", "false").strip().lower() == "true"
