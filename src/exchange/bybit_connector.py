import collections
import json
import logging
import os
import threading
import time
import urllib.parse

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)

# NOTE — dual-library design (intentional):
#   BybitConnector (this file) uses ccxt for market data + order placement.
#   telegram_query_bot.py uses pybit for wallet balance + positions display.
#   Both read the same BYBIT_API_KEY / BYBIT_API_SECRET env vars.
#   BYBIT_TESTNET=true  -> sandbox mode
#   BYBIT_TESTNET=false -> live mode (default if var is missing)


def market_symbol(symbol, market_type="linear"):
    """The ccxt symbol to ASK for, given this connector's account ``market_type``.

    The ccxt client below is built with ``defaultType: spot``, and ccxt resolves a
    bare exchange id (``BTCUSDT``) through ``markets_by_id`` by that default -- so a
    bare id read the SPOT market wherever Bybit lists one, while every Bybit account
    in ``config/accounts.yaml`` trades the LINEAR perp and every Stage-0 corpus is
    linear (``scripts/ops/fetch_backtest_candles.py`` category=linear;
    ``ml/datasets/adapters/bybit_offvm.py`` ccxt default ``swap``).
    PI-20261103-SPOTCANDLES-0001 / lane SPOTCANDLES-AUDIT; #22650 fixed ml_entry
    alone, this fixes it for every caller in one place.

    A bare ``<BASE>USDT`` id becomes ccxt's unified ``<BASE>/USDT:USDT`` (linear)
    for a non-spot connector and ``<BASE>/USDT`` for a spot one. Anything already
    unified (contains ``/``) or not a USDT id passes through unchanged.
    """
    s = str(symbol or "")
    if "/" in s or not s.endswith("USDT") or len(s) <= 4:
        return symbol
    base = s[:-4]
    if str(market_type or "linear").strip().lower() == "spot":
        return f"{base}/USDT"
    return f"{base}/USDT:USDT"


def _read_testnet_flag() -> bool:
    raw = os.getenv("BYBIT_TESTNET", "false").strip().lower()
    return raw == "true"


#: How long a Bybit ``retCode 10006`` (rate limit) keeps ``get_ohlcv`` returning ``None``.
#: It replaces an in-line ``time.sleep(15)`` of the same length -- see ``BybitConnector.get_ohlcv``.
#: BACKOFF (row VENUE-KLINE-RATE-LIMIT, 2026-11-13): a 10006 blanked EVERY Bybit read in the process for a flat 15 s,
#: although the first bybit_10006_context lines (#25825) show this process makes only 1-6 calls in the 5 s before a
#: 10006 -- the cooldown was the larger cost. Now the first 10006 cools down RATE_LIMIT_COOLDOWN_BASE_S; each further
#: 10006 started within RATE_LIMIT_STREAK_WINDOW_S of the previous doubles it, capped at RATE_LIMIT_COOLDOWN_S (the old
#: flat value), so a sustained wall still backs off to 15 s. No sleep, no pacing: only the length of the None window.
RATE_LIMIT_COOLDOWN_S = 15.0
RATE_LIMIT_COOLDOWN_BASE_S = 3.0
RATE_LIMIT_STREAK_WINDOW_S = 60.0

#: Process-wide, deliberately NOT per instance: the limit is per IP / API key, so every connector
#: instance (one per symbol, per account) hits the same wall, and a cooldown held by one instance
#: would let the others keep hammering it.
_RATE_LIMIT_LOCK = threading.Lock()
_rate_limited_until = 0.0   # time.monotonic() deadline; 0.0 = not cooling down
_last_cooldown_start = 0.0  # time.monotonic() of the last cooldown START; 0.0 = none yet
_cooldown_streak = 0        # cooldown starts in the current streak (reset when a start is > window after the last)


def _cooldown_remaining() -> float:
    """Seconds left on the shared rate-limit cooldown (0.0 when none)."""
    with _RATE_LIMIT_LOCK:
        return max(0.0, _rate_limited_until - time.monotonic())


def _next_cooldown_s(now: float) -> float:
    """Length of the cooldown a 10006 at *now* starts (caller holds the lock): base, doubled per streak step, capped."""
    global _cooldown_streak
    if _last_cooldown_start and now - _last_cooldown_start <= RATE_LIMIT_STREAK_WINDOW_S:
        _cooldown_streak += 1
    else:
        _cooldown_streak = 0
    return min(RATE_LIMIT_COOLDOWN_S, RATE_LIMIT_COOLDOWN_BASE_S * (2 ** _cooldown_streak))


def _start_cooldown() -> bool:
    """Start the shared cooldown; True only for the call that STARTED it (it logs the one line)."""
    global _rate_limited_until, _last_cooldown_start, _last_cooldown_s
    now = time.monotonic()
    with _RATE_LIMIT_LOCK:
        started = _rate_limited_until <= now
        if started:
            _last_cooldown_s = _next_cooldown_s(now)
            _last_cooldown_start = now
            _rate_limited_until = now + _last_cooldown_s
    return started


_last_cooldown_s = RATE_LIMIT_COOLDOWN_BASE_S   # the length of the most recently STARTED cooldown (for the log line)


# -------------------------------------------------------------------------------------------------------------------
# 10006 OBSERVABILITY (row VENUE-KLINE-RATE-LIMIT, follow-up to #25256). LOGGING ONLY: nothing here waits, sleeps,
# paces, refuses or retries. #25256 shared candle frames across accounts (per-tick cache hits 26% -> 40%), but the
# 10006 rate did not move (2026-11-12T18:40Z..11-13T19:11Z: 36 cooldown starts in 24.5 h vs 30 in 18.5 h before), and
# the error body does not say WHICH endpoint answered it or at WHAT call rate. Every HTTP request any BybitConnector
# makes (klines, load_markets, private reads, orders) goes through ccxt's ``Exchange.fetch``; each instance's fetch is
# wrapped to append (monotonic time, thread, method, path) to one process-wide ring, and the 10006 warning prints what
# that ring held over the preceding seconds. The path is logged WITHOUT its query string unless it is a public
# /v5/market/ path (no account data there); headers and bodies are never logged.
_CALL_WINDOW_S = 5.0
_CALL_RING_MAX = 4096
_CALL_RING: "collections.deque" = collections.deque(maxlen=_CALL_RING_MAX)
_CALL_RING_LOCK = threading.Lock()
#: Bybit's own limit headers (present on V5 responses); logged verbatim when the 10006 response carries them.
_LIMIT_HEADERS = ("X-Bapi-Limit", "X-Bapi-Limit-Status", "X-Bapi-Limit-Reset-Timestamp")


def _safe_path(url) -> str:
    """The request path; the query string only for public market-data paths. Never raises."""
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
        path = parts.path or "?"
        if parts.query and path.startswith("/v5/market/"):
            return f"{path}?{parts.query}"
        return path
    except Exception:  # noqa: BLE001
        return "?"


def _note_call(url, method) -> None:
    """Record one outgoing Bybit HTTP call. Never raises (a counter must never break a request)."""
    try:
        entry = (time.monotonic(), threading.current_thread().name, str(method or "GET"), _safe_path(url))
        with _CALL_RING_LOCK:
            _CALL_RING.append(entry)
    except Exception:  # noqa: BLE001
        pass


def recent_call_summary(window_s: float = _CALL_WINDOW_S, now: float | None = None) -> dict:
    """What the ring holds over the last ``window_s`` seconds: totals for 1 s and the window, and counts per
    endpoint (query dropped, so klines group by path) and per thread. Never raises."""
    try:
        t = time.monotonic() if now is None else float(now)
        with _CALL_RING_LOCK:
            recent = [e for e in _CALL_RING if t - e[0] <= window_s]
        by_path: dict = {}
        by_thread: dict = {}
        for _ts, thread, method, path in recent:
            key = f"{method} {path.split('?', 1)[0]}"
            by_path[key] = by_path.get(key, 0) + 1
            by_thread[thread] = by_thread.get(thread, 0) + 1
        return {
            "calls_1s": sum(1 for e in recent if t - e[0] <= 1.0),
            f"calls_{int(window_s)}s": len(recent),
            "by_endpoint": dict(sorted(by_path.items(), key=lambda kv: -kv[1])),
            "by_thread": dict(sorted(by_thread.items(), key=lambda kv: -kv[1])),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}"}


def _instrument_fetch(exchange) -> None:
    """Wrap this ccxt instance's ``fetch`` so every request is counted. The original is called unchanged, with the
    same arguments, and its result or exception passes through untouched."""
    original = getattr(exchange, "fetch", None)
    if original is None or getattr(original, "_jta_counted", False):
        return

    def fetch(url, method="GET", headers=None, body=None):
        _note_call(url, method)
        return original(url, method, headers, body)

    fetch._jta_counted = True
    try:
        exchange.fetch = fetch
    except Exception:  # noqa: BLE001 -- an un-patchable client still works, it is just not counted
        pass


def _rate_limit_context(exchange) -> dict:
    """The endpoint that answered (from ccxt's last request), Bybit's limit headers and the recent call counts."""
    ctx: dict = {}
    try:
        ctx["endpoint"] = _safe_path(getattr(exchange, "last_request_url", None))
        hdrs = getattr(exchange, "last_response_headers", None) or {}
        lower = {str(k).lower(): v for k, v in dict(hdrs).items()}
        for h in _LIMIT_HEADERS:
            if h.lower() in lower:
                ctx[h] = lower[h.lower()]
    except Exception:  # noqa: BLE001
        pass
    ctx.update(recent_call_summary())
    return ctx


class BybitConnector:
    """
    Bybit connector for Unified Trading Account.
    Works with Cross Margin and linear perpetual contracts.

    Testnet / live mode is controlled by the BYBIT_TESTNET environment
    variable.  Set BYBIT_TESTNET=false in .env.live for live trading.
    If testnet param is omitted, the env var is read.
    """

    def __init__(self, api_key=None, api_secret=None, testnet=None,
                 market_type="linear"):
        if testnet is None:
            testnet = _read_testnet_flag()
        self.testnet = testnet
        # The account's config/accounts.yaml ``market_type`` — decides the V5
        # ``category`` for position reads (see get_positions). Default
        # ``linear``: every Bybit account in config/accounts.yaml is linear
        # (bybit_1, bybit_2, bybit_portfolio; 2026-10-01).
        self.market_type = market_type

        self.exchange = ccxt.bybit({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        if testnet:
            self.exchange.set_sandbox_mode(True)
        _instrument_fetch(self.exchange)

        # Operator directive 2026-05-03 — dry/live mode is per-account
        # (config/accounts.yaml `mode`, applied via RiskManager.dry_run).
        # The connector itself doesn't gate on a process-level flag.
        logger.info("Bybit market data environment: %s", "testnet" if testnet else "mainnet")

    def get_price(self, symbol="BTC/USDT:USDT"):
        try:
            ticker = self.exchange.fetch_ticker(market_symbol(symbol, self.market_type))
            return ticker["last"]
        except Exception as e:
            print(f"Error fetching price: {e}")
            return None

    def get_ohlcv(self, symbol="BTC/USDT:USDT", timeframe="15m", limit=100, since=None):
        # ``since`` (epoch MILLISECONDS, CCXT convention) fetches candles FORWARD
        # from that time — the historical-range read the M30 P5 exit panel needs
        # to reconstruct MFE/MAE over a closed trade's holding window. Default
        # None = the exchange's most-recent ``limit`` candles (unchanged behaviour).
        # NON-BLOCKING RATE-LIMIT COOLDOWN (MECH-FOLLOWUPS-1105, manager 2026-11-05b). While cooling down this
        # returns None at once instead of calling Bybit again. Every caller already treats None as "no candles
        # this pass" (order_monitor: "monitor will short-circuit"; entry builders skip the tick).
        if _cooldown_remaining() > 0.0:
            return None
        try:
            # market_symbol: a bare id on this defaultType=spot client read SPOT
            # candles for perp-traded legs (PI-20261103-SPOTCANDLES-0001).
            ohlcv = self.exchange.fetch_ohlcv(
                market_symbol(symbol, self.market_type), timeframe, since=since, limit=limit)
            df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except Exception as e:
            print(f"Error fetching OHLCV: {e}")
            msg = str(e)
            if "Rate Limit" in msg or "Too many visits" in msg or 'retCode":10006' in msg:
                # This used to be ``time.sleep(15)`` IN THE CALLER. The exit-evaluation pass fetches candles
                # for every open package through here, so one 10006 stalled the pass for 15 s per hit: 11 hits
                # at the 00:00Z bar boundary left a live trade 115.3 s without re-evaluation (requirement 60 s;
                # PI-20261105-F2QX97PI-0001). Now: start a shared cooldown, return None, never sleep.
                if _start_cooldown():
                    logger.warning(
                        "bybit get_ohlcv: rate limit (retCode 10006) hit by thread=%s symbol=%s timeframe=%s -- "
                        "get_ohlcv returns None for %.0f s (no in-line sleep; streak %d)",
                        threading.current_thread().name, symbol, timeframe, _last_cooldown_s, _cooldown_streak)
                    # Observability only (row VENUE-KLINE-RATE-LIMIT): which endpoint answered 10006, Bybit's own limit
                    # headers, and every Bybit call this process made in the preceding seconds.
                    logger.warning("bybit_10006_context %s",
                                   json.dumps(_rate_limit_context(self.exchange), sort_keys=True, default=str))
            return None

    def get_balance(self):
        try:
            return self.exchange.fetch_balance()
        except Exception as e:
            print(f"Error fetching balance: {e}")
            return None

    def get_positions(self):
        """Return only positions with non-zero size.

        The V5 ``category`` comes from this connector's ``market_type``, via
        the same resolver the order path uses (``execute._bybit_category``).
        It was hardcoded ``"spot"`` — for a linear-perp account that is the
        wrong book, so the read silently returned ``[]``
        (AUD-20260927-CA-A15-bybit-positions-spot-category, ORDER-AUDIT-2
        item 6). Spot has no positions on V5 (a spot holding is a wallet
        balance), so a spot connector returns ``[]`` without a call.

        A failed read RAISES. It used to return ``[]``, which made "could not
        read" and "no positions" the same answer; the one consumer
        (``risk_counters.inject_runtime_counters``) that used to catch it was
        retired 2026-10-21 with the MAX_OPEN_POSITIONS guard. The contracts > 0 filter matches the
        Binance connector's schema exactly.
        """
        from src.units.accounts.execute import _bybit_category
        category = _bybit_category({"market_type": self.market_type})
        if category == "spot":
            return []
        positions = self.exchange.fetch_positions(params={"category": category})
        return [p for p in positions if float(p.get("contracts", 0) or 0) > 0]

    def place_market_order(self, symbol, side, amount, params=None):
        try:
            if params is None:
                params = {}
            order = self.exchange.create_market_order(symbol=symbol, side=side, amount=amount, params=params)
            mode = "TESTNET" if self.testnet else "LIVE"
            print(f"[{mode}] Market {side.upper()}: {amount} {symbol}")
            return order
        except Exception as e:
            print(f"Error placing order: {e}")
            return None



if __name__ == "__main__":
    print("BybitConnector loaded")
    print(f"Testnet from env: {_read_testnet_flag()}")
