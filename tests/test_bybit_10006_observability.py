"""Row VENUE-KLINE-RATE-LIMIT: when Bybit answers retCode 10006, log WHICH endpoint answered, Bybit's limit headers,
and every Bybit call the process made in the preceding seconds. LOGGING ONLY: these tests also pin that nothing
sleeps, retries or refuses, and that the wrapped request passes arguments, results and exceptions through unchanged.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import pytest

pytest.importorskip("ccxt")

from src.exchange import bybit_connector as bc  # noqa: E402

RL_BODY = 'bybit {"retCode":10006,"retMsg":"Too many visits. Exceeded the API Rate Limit.","result":{}}'


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    with bc._CALL_RING_LOCK:
        bc._CALL_RING.clear()
    monkeypatch.setattr(bc, "_rate_limited_until", 0.0)
    yield
    with bc._CALL_RING_LOCK:
        bc._CALL_RING.clear()
    monkeypatch.setattr(bc, "_rate_limited_until", 0.0)


def _connector(monkeypatch, *, raise_on_kline=None, headers=None):
    """A real BybitConnector whose ccxt HTTP layer is replaced by a fake. The fake sits UNDER the counting wrapper,
    exactly where ccxt's real network call would be."""
    calls = []

    def fake_http(url, method="GET", headers_=None, body=None):
        calls.append((url, method))
        c.exchange.last_request_url = url
        c.exchange.last_response_headers = headers or {}
        if raise_on_kline and "/v5/market/kline" in url:
            raise raise_on_kline
        return {"retCode": 0, "result": {"list": []}}

    # Install the fake as the ORIGINAL fetch, then let the connector wrap it.
    import ccxt
    monkeypatch.setattr(ccxt.bybit, "fetch", lambda self, url, method="GET", headers=None, body=None:
                        fake_http(url, method, headers, body))
    c = bc.BybitConnector(api_key="k", api_secret="s", testnet=False)
    return c, calls


def test_every_request_is_counted_and_passes_through_unchanged(monkeypatch):
    c, calls = _connector(monkeypatch)
    out = c.exchange.fetch("https://api.bybit.com/v5/market/kline?symbol=BTCUSDT&interval=60", "GET", {"h": "1"}, None)
    assert out == {"retCode": 0, "result": {"list": []}}
    assert calls == [("https://api.bybit.com/v5/market/kline?symbol=BTCUSDT&interval=60", "GET")]
    s = bc.recent_call_summary()
    assert s["calls_1s"] == 1 and s["calls_5s"] == 1
    assert s["by_endpoint"] == {"GET /v5/market/kline": 1}
    assert s["by_thread"] == {threading.current_thread().name: 1}


def test_exceptions_pass_through_the_wrapper(monkeypatch):
    import ccxt
    c, _ = _connector(monkeypatch, raise_on_kline=ccxt.RateLimitExceeded(RL_BODY))
    with pytest.raises(ccxt.RateLimitExceeded):
        c.exchange.fetch("https://api.bybit.com/v5/market/kline?symbol=X", "GET", None, None)
    assert bc.recent_call_summary()["calls_5s"] == 1      # counted even though it failed


def test_wrapper_is_applied_once(monkeypatch):
    c, calls = _connector(monkeypatch)
    bc._instrument_fetch(c.exchange)                       # second wrap is a no-op
    c.exchange.fetch("https://api.bybit.com/v5/market/time", "GET", None, None)
    assert len(calls) == 1 and bc.recent_call_summary()["calls_5s"] == 1


def test_private_paths_never_log_their_query_string():
    assert bc._safe_path("https://api.bybit.com/v5/position/list?category=linear&symbol=BTCUSDT") == "/v5/position/list"
    assert bc._safe_path("https://api.bybit.com/v5/order/create") == "/v5/order/create"
    assert bc._safe_path("https://api.bybit.com/v5/market/kline?symbol=BTCUSDT&interval=60") == \
        "/v5/market/kline?symbol=BTCUSDT&interval=60"
    assert bc._safe_path(None) == "?"


def test_window_drops_old_calls():
    now = time.monotonic()
    with bc._CALL_RING_LOCK:
        bc._CALL_RING.extend([(now - 9.0, "T", "GET", "/old"), (now - 3.0, "T", "GET", "/mid"),
                              (now - 0.5, "T", "GET", "/new")])
    s = bc.recent_call_summary(now=now)
    assert s["calls_1s"] == 1 and s["calls_5s"] == 2
    assert set(s["by_endpoint"]) == {"GET /mid", "GET /new"}


def test_10006_logs_endpoint_headers_and_recent_calls_and_never_sleeps(monkeypatch, caplog):
    import ccxt
    hdrs = {"X-Bapi-Limit": "600", "X-Bapi-Limit-Status": "0", "X-Bapi-Limit-Reset-Timestamp": "1794474011000",
            "Authorization": "secret-must-not-appear"}
    c, _ = _connector(monkeypatch, raise_on_kline=ccxt.RateLimitExceeded(RL_BODY), headers=hdrs)
    # some earlier traffic in the window
    for _ in range(3):
        c.exchange.fetch("https://api.bybit.com/v5/market/tickers?category=linear", "GET", None, None)
    monkeypatch.setattr(c.exchange, "load_markets", lambda *a, **k: {})
    monkeypatch.setattr(c.exchange, "market", lambda s: {"id": "BTCUSDT", "symbol": s, "linear": True,
                                                          "spot": False, "type": "swap", "contract": True})

    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    caplog.set_level(logging.WARNING, logger=bc.logger.name)
    t0 = time.monotonic()
    out = c.get_ohlcv("BTCUSDT", "1h", limit=5)
    assert out is None
    assert time.monotonic() - t0 < 1.0 and slept == []          # logging only: no sleep, no retry
    ctx_lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("bybit_10006_context ")]
    assert len(ctx_lines) == 1
    ctx = json.loads(ctx_lines[0].split(" ", 1)[1])
    assert ctx["endpoint"].startswith("/v5/market/kline")
    assert ctx["X-Bapi-Limit"] == "600" and ctx["X-Bapi-Limit-Status"] == "0"
    assert "secret-must-not-appear" not in ctx_lines[0] and "Authorization" not in ctx_lines[0]
    assert ctx["calls_5s"] >= 4                                  # 3 tickers + the kline that failed
    assert ctx["by_endpoint"]["GET /v5/market/tickers"] == 3
    # behaviour unchanged: the shared cooldown started and the next read returns None without a venue call
    assert bc._cooldown_remaining() > 0
    n_before = bc.recent_call_summary()["calls_5s"]
    assert c.get_ohlcv("BTCUSDT", "1h", limit=5) is None
    assert bc.recent_call_summary()["calls_5s"] == n_before


def test_context_is_logged_once_per_cooldown(monkeypatch, caplog):
    import ccxt
    c, _ = _connector(monkeypatch, raise_on_kline=ccxt.RateLimitExceeded(RL_BODY))
    monkeypatch.setattr(c.exchange, "load_markets", lambda *a, **k: {})
    monkeypatch.setattr(c.exchange, "market", lambda s: {"id": "BTCUSDT", "symbol": s, "linear": True,
                                                          "spot": False, "type": "swap", "contract": True})
    caplog.set_level(logging.WARNING, logger=bc.logger.name)
    c.get_ohlcv("BTCUSDT", "1h", limit=5)
    monkeypatch.setattr(bc, "_rate_limited_until", 0.0)          # cooldown over
    monkeypatch.setattr(bc, "_start_cooldown", lambda: False)   # a concurrent caller already started it
    c.get_ohlcv("BTCUSDT", "1h", limit=5)
    assert sum(1 for r in caplog.records if r.getMessage().startswith("bybit_10006_context ")) == 1
