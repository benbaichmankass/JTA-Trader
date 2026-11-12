"""VENUE-KLINE-RATE-LIMIT: one venue call per (Bybit network, market, symbol, timeframe) per bar.

Measured 2026-11-11T14:59Z..2026-11-12T09:30Z on ict-trader-live (journal, complete scans): 30 Bybit retCode 10006
cooldown starts, all within ~78 s after a 15m/1h boundary, and 380 strategy ``no candle data`` raises behind them.
The bar-close burst fetched the same frame once per account key, per symbol spelling (``SOLUSDT`` vs
``SOL/USDT:USDT``), per ``limit`` and per post-close (``bypass_cache``) reader. These tests pin the sharing rules and
the guarantees that must NOT change: a post-close read never gets a pre-close frame, never gets a frame that lacks
the just-closed bar, and non-Bybit clients keep the original always-call-the-venue behaviour.
"""
from __future__ import annotations

import threading
import time

import pandas as pd
import pytest

pytest.importorskip("ccxt")

from src.exchange.bybit_connector import BybitConnector  # noqa: E402
from src.runtime import market_data as md  # noqa: E402

H = 3600


def _frame(last_open_s: float, n: int, close: float = 1.0) -> pd.DataFrame:
    ts = [pd.Timestamp((last_open_s - (n - 1 - i) * H), unit="s") for i in range(n)]
    return pd.DataFrame({"timestamp": ts, "open": close, "high": close, "low": close, "close": close,
                         "volume": 1.0})


class _CountingBybit(BybitConnector):
    """Never used for the shared-key tests: a SUBCLASS must keep a per-client slot (exact class check)."""


def _bybit(monkeypatch, *, key="k1", market_type="linear", testnet=False):
    c = BybitConnector(api_key=key, api_secret="s", testnet=testnet, market_type=market_type)
    return c


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    md.reset_candle_cache()
    monkeypatch.setenv("CANDLE_CACHE_TTL_FRACTION", "0.10")
    monkeypatch.setenv("CANDLE_CACHE_TTL_MAX_S", "300")
    yield
    md.reset_candle_cache()


class _Venue:
    """Patches BybitConnector.get_ohlcv; counts every venue call across all instances."""

    def __init__(self, monkeypatch, frame_fn, delay: float = 0.0):
        self.calls = []
        self.frame_fn = frame_fn
        self.delay = delay
        venue = self

        def get_ohlcv(conn, symbol, timeframe="15m", limit=100, since=None):
            venue.calls.append((symbol, timeframe, limit))
            if venue.delay:
                time.sleep(venue.delay)
            return venue.frame_fn(symbol, timeframe, limit)

        monkeypatch.setattr(BybitConnector, "get_ohlcv", get_ohlcv)


def _now_after_close(monkeypatch, seconds_after: float) -> float:
    close = (time.time() // H) * H
    now = close + seconds_after
    monkeypatch.setattr(md.time, "time", lambda: now)
    return close


# ---------------------------------------------------------------------------------------------------- sharing


def test_two_account_keys_share_one_fetch(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))
    a, b = _bybit(monkeypatch, key="acct1"), _bybit(monkeypatch, key="acct2")
    md.fetch_candles("SOLUSDT", "1h", exchange_client=a, limit=200)
    md.fetch_candles("SOLUSDT", "1h", exchange_client=b, limit=200)
    assert len(v.calls) == 1


def test_bare_and_unified_spelling_share_one_fetch(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))
    c = _bybit(monkeypatch)
    md.fetch_candles("SOLUSDT", "1h", exchange_client=c, limit=200)
    md.fetch_candles("SOL/USDT:USDT", "1h", exchange_client=c, limit=200)
    assert len(v.calls) == 1


def test_smaller_limit_served_as_tail_of_larger_frame(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))
    c = _bybit(monkeypatch)
    big = md.fetch_candles("ETHUSDT", "1h", exchange_client=c, limit=400)
    small = md.fetch_candles("ETHUSDT", "1h", exchange_client=c, limit=200)
    assert len(v.calls) == 1
    assert len(small) == 200 and small["timestamp"].tolist() == big["timestamp"].tolist()[-200:]


def test_larger_limit_than_cached_refetches(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))
    c = _bybit(monkeypatch)
    md.fetch_candles("ETHUSDT", "1h", exchange_client=c, limit=200)
    out = md.fetch_candles("ETHUSDT", "1h", exchange_client=c, limit=400)
    assert len(v.calls) == 2 and len(out) == 400
    # and the larger frame now answers the smaller request too
    md.fetch_candles("ETHUSDT", "1h", exchange_client=c, limit=200)
    assert len(v.calls) == 2


def test_market_type_and_network_stay_separate(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))
    md.fetch_candles("BTCUSDT", "1h", exchange_client=_bybit(monkeypatch, market_type="linear"), limit=100)
    md.fetch_candles("BTCUSDT", "1h", exchange_client=_bybit(monkeypatch, market_type="spot"), limit=100)
    md.fetch_candles("BTCUSDT", "1h", exchange_client=_bybit(monkeypatch, testnet=True), limit=100)
    assert len(v.calls) == 3


def test_timeframes_stay_separate(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))
    c = _bybit(monkeypatch)
    md.fetch_candles("BTCUSDT", "1h", exchange_client=c, limit=100)
    md.fetch_candles("BTCUSDT", "4h", exchange_client=c, limit=100)
    assert len(v.calls) == 2


def test_subclass_is_not_shared(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))
    md.fetch_candles("BTCUSDT", "1h", exchange_client=_CountingBybit(api_key="a", api_secret="s"), limit=100)
    md.fetch_candles("BTCUSDT", "1h", exchange_client=_CountingBybit(api_key="b", api_secret="s"), limit=100)
    assert len(v.calls) == 2


def test_returned_frame_is_a_copy(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))
    c = _bybit(monkeypatch)
    first = md.fetch_candles("BTCUSDT", "1h", exchange_client=c, limit=100)
    first["indicator"] = 1
    second = md.fetch_candles("BTCUSDT", "1h", exchange_client=c, limit=100)
    assert "indicator" not in second.columns


# ---------------------------------------------------------------------------------------------- post-close reads


def test_post_close_reader_reuses_a_post_close_frame(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))   # carries the bar that opened at the close
    a, b = _bybit(monkeypatch, key="acct1"), _bybit(monkeypatch, key="acct2")
    md.fetch_candles("XRPUSDT", "1h", exchange_client=a, limit=200, bypass_cache=True)
    md.fetch_candles("XRP/USDT:USDT", "1h", exchange_client=b, limit=200, bypass_cache=True)
    md.fetch_candles("XRPUSDT", "1h", exchange_client=a, limit=100, bypass_cache=True)
    assert len(v.calls) == 1


def test_post_close_reader_never_gets_a_pre_close_frame(monkeypatch):
    close = (time.time() // H) * H
    clock = {"now": close - 20}                                   # 20 s BEFORE the close
    monkeypatch.setattr(md.time, "time", lambda: clock["now"])
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close - H, n))
    c = _bybit(monkeypatch)
    md.fetch_candles("XRPUSDT", "1h", exchange_client=c, limit=200)
    clock["now"] = close + 30
    md.fetch_candles("XRPUSDT", "1h", exchange_client=c, limit=200, bypass_cache=True)
    assert len(v.calls) == 2
    # a default (non post-close) reader still gets the TTL cache, as before
    md.fetch_candles("XRPUSDT", "1h", exchange_client=c, limit=200)
    assert len(v.calls) == 2


def test_post_close_reader_never_gets_a_frame_inside_the_settle(monkeypatch):
    close = (time.time() // H) * H
    clock = {"now": close + 2}                                    # inside the 5 s settle
    monkeypatch.setattr(md.time, "time", lambda: clock["now"])
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n))
    c = _bybit(monkeypatch)
    md.fetch_candles("XRPUSDT", "1h", exchange_client=c, limit=200, bypass_cache=True)
    clock["now"] = close + 30
    md.fetch_candles("XRPUSDT", "1h", exchange_client=c, limit=200, bypass_cache=True)
    assert len(v.calls) == 2


def test_post_close_reader_refetches_when_closed_bar_was_not_published(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    # the venue answered without the just-closed bar (last row opened two bars ago)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close - 2 * H, n))
    c = _bybit(monkeypatch)
    md.fetch_candles("XRPUSDT", "1h", exchange_client=c, limit=200, bypass_cache=True)
    md.fetch_candles("XRPUSDT", "1h", exchange_client=c, limit=200, bypass_cache=True)
    assert len(v.calls) == 2


def test_closed_bar_only_frame_is_served(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    # a venue that returns only CLOSED bars: last row opened one bar before the close
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close - H, n))
    c = _bybit(monkeypatch)
    md.fetch_candles("XRPUSDT", "1h", exchange_client=c, limit=200, bypass_cache=True)
    md.fetch_candles("XRPUSDT", "1h", exchange_client=c, limit=200, bypass_cache=True)
    assert len(v.calls) == 1


def test_non_bybit_client_post_close_read_always_calls_venue(monkeypatch):
    close = _now_after_close(monkeypatch, 30)

    class _Stub:
        calls = 0

        def get_ohlcv(self, symbol, timeframe, limit=100):
            _Stub.calls += 1
            return _frame(close, limit)

    c = _Stub()
    md.fetch_candles("SPY", "1h", exchange_client=c, limit=50, bypass_cache=True)
    md.fetch_candles("SPY", "1h", exchange_client=c, limit=50, bypass_cache=True)
    assert _Stub.calls == 2


# --------------------------------------------------------------------------------------- no wait on the trade path


def test_a_fetch_never_waits_on_another_in_flight_fetch(monkeypatch):
    """AM-OPS ruling 2026-11-12 (#25256): only a COMPLETED frame is shared. Two callers missing at the same instant
    each call the venue in parallel; neither blocks on the other."""
    close = _now_after_close(monkeypatch, 30)
    v = _Venue(monkeypatch, lambda s, tf, n: _frame(close, n), delay=0.3)
    clients = [_bybit(monkeypatch, key=f"acct{i}") for i in range(4)]
    out = []

    def run(c):
        out.append(md.fetch_candles("BTCUSDT", "1h", exchange_client=c, limit=200, bypass_cache=True))

    threads = [threading.Thread(target=run, args=(c,)) for c in clients]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    wall = time.monotonic() - t0
    assert len(out) == 4 and all(f is not None and len(f) == 200 for f in out)
    assert len(v.calls) == 4                # nobody waited for the in-flight call
    assert wall < 0.9                       # parallel, not serialized (4 x 0.3 s = 1.2 s if they queued)
    # once completed, the frame IS shared
    md.fetch_candles("BTCUSDT", "1h", exchange_client=clients[0], limit=200, bypass_cache=True)
    assert len(v.calls) == 4


def test_failed_fetch_is_not_cached(monkeypatch):
    close = _now_after_close(monkeypatch, 30)
    answers = [None, _frame(close, 200)]
    v = _Venue(monkeypatch, lambda s, tf, n: answers[min(len(v.calls) - 1, 1)])
    c = _bybit(monkeypatch)
    assert md.fetch_candles("BTCUSDT", "1h", exchange_client=c, limit=200) is None
    assert md.fetch_candles("BTCUSDT", "1h", exchange_client=c, limit=200) is not None
    assert len(v.calls) == 2
