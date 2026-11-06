"""M15 Phase 1 — data-only connectors + market-hours gate.

Covers:
- AlpacaMarketData / OandaMarketData ``get_ohlcv`` normalisation against
  mocked HTTP responses (no network).
- ``_build_exchange_client`` routing for the new exchange names.
- ``market_hours.is_market_open`` session logic (fx weekend close,
  us_equity RTH incl. the DST month approximation, crypto 24/7,
  fail-permissive unknown class).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.exchange.alpaca_connector import AlpacaMarketData
from src.exchange.oanda_connector import OandaMarketData, _to_instrument
from src.runtime.market_data import _build_exchange_client
from src.runtime.market_hours import asset_class_for_exchange, is_market_open


class _FakeClock:
    """Monotonic clock + sleep for the Alpaca pacing/backoff (no real sleeping in tests)."""

    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


@pytest.fixture(autouse=True)
def _alpaca_fake_clock(monkeypatch):
    import src.exchange.alpaca_connector as ac
    clk = _FakeClock()
    monkeypatch.setattr(ac, "_now", clk.now)
    monkeypatch.setattr(ac, "_sleep", clk.sleep)
    monkeypatch.setitem(ac._pace, "next", 0.0)
    monkeypatch.setitem(ac._budget, "window_start", 0.0)
    monkeypatch.setitem(ac._budget, "spent", 0.0)
    return clk


class _Resp:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_alpaca_get_ohlcv_normalises(monkeypatch):
    payload = {
        "bars": [
            {"t": "2026-06-10T15:00:00Z", "o": 2, "h": 3, "l": 1, "c": 2.5, "v": 100},
            {"t": "2026-06-10T14:55:00Z", "o": 1, "h": 2, "l": 0.5, "c": 2.0, "v": 50},
        ]
    }
    monkeypatch.setattr(
        "src.exchange.alpaca_connector.requests.get",
        lambda *a, **k: _Resp(payload),
    )
    df = AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("QQQ", "5m", limit=2)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    # desc payload must come back ascending
    assert df["timestamp"].is_monotonic_increasing
    assert df["timestamp"].dt.tz is not None
    assert len(df) == 2


def test_alpaca_get_ohlcv_passes_explicit_lookback_start(monkeypatch):
    """Alpaca defaults ``start`` to the beginning of the CURRENT day, so the
    connector must send an explicit lookback or daily strategies get at most
    today's partial bar (M15 soak finding, 2026-06-11)."""
    captured = {}

    def fake_get(url, params=None, **kwargs):
        captured["params"] = params or {}
        return _Resp({"bars": [
            {"t": "2026-06-10T15:00:00Z", "o": 2, "h": 3, "l": 1, "c": 2.5, "v": 100},
        ]})

    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", fake_get)

    AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("SPY", "1d", limit=200)
    start = captured["params"].get("start")
    assert start, "explicit start param must be sent"
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    age_days = (datetime.now(timezone.utc) - start_dt).days
    # 200 daily bars need ≥ 200 * 7/5 = 280 calendar days of lookback.
    assert age_days >= 280, f"lookback too shallow for 200 daily bars: {age_days}d"

    AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("SPY", "5m", limit=100)
    start_dt = datetime.fromisoformat(
        captured["params"]["start"].replace("Z", "+00:00"))
    # 100 five-minute bars span ~8.3 session hours ≈ 2 calendar days
    # at the 6x session-to-calendar factor (+10d buffer).
    assert (datetime.now(timezone.utc) - start_dt).days >= 10


def test_alpaca_returns_none_on_error_and_empty(monkeypatch):
    monkeypatch.setattr(
        "src.exchange.alpaca_connector.requests.get",
        lambda *a, **k: _Resp({"bars": []}),
    )
    assert AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("QQQ", "5m", limit=2) is None
    monkeypatch.setattr(
        "src.exchange.alpaca_connector.requests.get",
        lambda *a, **k: _Resp({}, status=403),
    )
    assert AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("QQQ", "5m", limit=2) is None
    assert AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("QQQ", "7m", limit=2) is None


def test_oanda_get_ohlcv_normalises_and_drops_incomplete(monkeypatch):
    payload = {
        "candles": [
            {
                "time": "2026-06-10T15:00:00.000000000Z",
                "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.15"},
                "volume": 42,
                "complete": True,
            },
            {
                "time": "2026-06-10T15:15:00.000000000Z",
                "mid": {"o": "1.15", "h": "1.16", "l": "1.14", "c": "1.155"},
                "volume": 7,
                "complete": False,
            },
        ]
    }
    monkeypatch.setattr(
        "src.exchange.oanda_connector.requests.get",
        lambda *a, **k: _Resp(payload),
    )
    df = OandaMarketData(api_token="t").get_ohlcv("EURUSD", "15m", limit=2)
    assert len(df) == 1  # incomplete candle dropped
    assert df["close"].dtype.kind == "f"
    assert df["timestamp"].dt.tz is not None


def test_oanda_instrument_mapping():
    assert _to_instrument("EURUSD") == "EUR_USD"
    assert _to_instrument("EUR_USD") == "EUR_USD"
    assert _to_instrument("XAUUSD") == "XAU_USD"


def test_build_exchange_client_routes_new_exchanges():
    assert isinstance(_build_exchange_client({"EXCHANGE": "alpaca"}), AlpacaMarketData)
    assert isinstance(_build_exchange_client({"EXCHANGE": "oanda"}), OandaMarketData)
    with pytest.raises(ValueError):
        _build_exchange_client({"EXCHANGE": "nonsense"})


# ---------------------------------------------------------------- hours
def _dt(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_crypto_and_unknown_always_open():
    assert is_market_open("crypto", _dt(2026, 6, 13, 3, 0))  # Saturday
    assert is_market_open("whatever", _dt(2026, 6, 13, 3, 0))  # fail-permissive


def test_fx_weekend_close():
    assert is_market_open("fx", _dt(2026, 6, 12, 20, 59))  # Fri before 21:00
    assert not is_market_open("fx", _dt(2026, 6, 12, 21, 0))  # Fri 21:00
    assert not is_market_open("fx", _dt(2026, 6, 13, 12, 0))  # Saturday
    assert not is_market_open("fx", _dt(2026, 6, 14, 20, 59))  # Sun before 21:00
    assert is_market_open("fx", _dt(2026, 6, 14, 21, 0))  # Sunday reopen
    assert is_market_open("fx", _dt(2026, 6, 10, 3, 0))  # mid-week night


def test_us_equity_rth_dst_months():
    # June = DST month -> 13:30-20:00 UTC
    assert not is_market_open("us_equity", _dt(2026, 6, 10, 13, 29))
    assert is_market_open("us_equity", _dt(2026, 6, 10, 13, 30))
    assert is_market_open("us_equity", _dt(2026, 6, 10, 19, 59))
    assert not is_market_open("us_equity", _dt(2026, 6, 10, 20, 0))
    assert not is_market_open("us_equity", _dt(2026, 6, 13, 15, 0))  # Saturday


def test_us_equity_rth_standard_months():
    # January = standard time -> 14:30-21:00 UTC
    assert not is_market_open("us_equity", _dt(2026, 1, 7, 14, 29))
    assert is_market_open("us_equity", _dt(2026, 1, 7, 14, 30))
    assert is_market_open("us_equity", _dt(2026, 1, 7, 20, 59))
    assert not is_market_open("us_equity", _dt(2026, 1, 7, 21, 0))


def test_asset_class_for_exchange():
    assert asset_class_for_exchange("oanda") == "fx"
    assert asset_class_for_exchange("alpaca") == "us_equity"
    assert asset_class_for_exchange("bybit") == "crypto"


def _hourly(n, end="2026-11-02T15:00:00Z"):
    t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
    from datetime import timedelta
    return [{"t": (t1 - timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}
            for i in range(n)]  # newest first, as sort=desc returns them


def test_alpaca_follows_next_page_token_until_limit(monkeypatch):
    """Row ML-ENTRY-ALPACA-BAR-PARITY: a short first page + next_page_token left ml_entry with 203-267 of 400 bars."""
    allbars = _hourly(500)
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(dict(params))
        off = int(params.get("page_token") or 0)
        page = allbars[off:off + min(223, int(params["limit"]))]   # the venue answers short of limit
        nxt = off + len(page)
        return _Resp({"bars": page, "next_page_token": str(nxt) if nxt < len(allbars) else None})

    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", fake_get)
    df = AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("SPY", "1h", limit=400)
    assert len(df) == 400 and df["timestamp"].is_monotonic_increasing and df["timestamp"].is_unique
    assert len(calls) == 2 and "page_token" not in calls[0] and calls[1]["page_token"] == "223"
    assert calls[1]["limit"] == 400 - 223                  # asks only for the remainder
    assert calls[0]["start"] == calls[1]["start"]          # one window across pages
    assert df["timestamp"].iloc[-1].isoformat().startswith("2026-11-02T15:00")   # the newest bars are kept


def test_alpaca_single_page_is_one_call(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params)
        return _Resp({"bars": _hourly(int(params["limit"])), "next_page_token": "x"})

    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", fake_get)
    assert len(AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("SPY", "1h", limit=50)) == 50
    assert len(calls) == 1


def test_alpaca_later_page_failure_keeps_first_page(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params)
        if params.get("page_token"):
            return _Resp({}, status=429)
        return _Resp({"bars": _hourly(100), "next_page_token": "p2"})

    import src.exchange.alpaca_connector as ac
    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", fake_get)
    df = AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("SPY", "1h", limit=400)
    # page 2 is retried up to the cap (PI-20261106-5A1BGFHC-0001), then the first page is kept
    assert len(df) == 100 and len(calls) == 2 + ac._MAX_RETRIES


def test_alpaca_page_loop_is_bounded(monkeypatch):
    import src.exchange.alpaca_connector as ac
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params)
        return _Resp({"bars": _hourly(1, end=f"2026-11-0{1 + len(calls) % 2}T10:00:00Z"), "next_page_token": "again"})

    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", fake_get)
    AlpacaMarketData(api_key="k", api_secret="s").get_ohlcv("SPY", "1h", limit=400)
    assert len(calls) == ac._MAX_PAGES


# ── PI-20261106-5A1BGFHC-0001: bounded 429 backoff, pacing, and a NAMED read state (never a silent None) ──────────────

def test_alpaca_429_then_200_succeeds_and_honours_retry_after(monkeypatch, _alpaca_fake_clock):
    import src.exchange.alpaca_connector as ac
    seq = [_Resp({}, status=429, headers={"Retry-After": "1.5"}), _Resp({"bars": _hourly(10)})]
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params)
        return seq[min(len(calls) - 1, len(seq) - 1)]

    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", fake_get)
    md = AlpacaMarketData(api_key="k", api_secret="s")
    df = md.get_ohlcv("SPY", "1h", limit=10)
    assert df is not None and len(df) == 10 and len(calls) == 2
    assert md.last_read_state["SPY"] == "ok"
    assert 1.5 in _alpaca_fake_clock.slept                      # Retry-After honoured
    assert ac.read_state_counts().get("ok", 0) >= 1


def test_alpaca_persistent_429_hits_the_cap_and_returns_a_named_state(monkeypatch, _alpaca_fake_clock):
    import src.exchange.alpaca_connector as ac
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params)
        return _Resp({}, status=429)                           # no Retry-After -> exponential

    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", fake_get)
    md = AlpacaMarketData(api_key="k", api_secret="s")
    before = ac.read_state_counts().get("rate_limited", 0)
    assert md.get_ohlcv("SPY", "1h", limit=10) is None
    assert md.last_read_state["SPY"] == "rate_limited"         # NOT "empty": a rate limit is not "no bars"
    assert len(calls) == 1 + ac._MAX_RETRIES
    assert ac.read_state_counts()["rate_limited"] == before + 1
    backoff = sum(s for s in _alpaca_fake_clock.slept if s > ac._MIN_INTERVAL_S + 1e-9)
    assert backoff <= ac._MAX_BACKOFF_S_PER_FETCH + 1e-9


def test_alpaca_backoff_is_bounded_per_window_across_symbols(monkeypatch, _alpaca_fake_clock):
    """Sustained throttling over many symbols costs the tick at most the rolling budget, then fails fast."""
    import src.exchange.alpaca_connector as ac
    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get",
                        lambda *a, **k: _Resp({}, status=429, headers={"Retry-After": "10"}))
    md = AlpacaMarketData(api_key="k", api_secret="s")
    t0 = _alpaca_fake_clock.t
    syms = [f"S{i}" for i in range(40)]
    for s in syms:
        assert md.get_ohlcv(s, "1h", limit=10) is None
    assert all(md.last_read_state[s] == "rate_limited" for s in syms)
    elapsed = _alpaca_fake_clock.t - t0
    pacing = ac._MIN_INTERVAL_S * len(syms) * (1 + ac._MAX_RETRIES)
    assert elapsed <= ac._BACKOFF_BUDGET_S + pacing + 1e-6, elapsed


def test_alpaca_pacing_spaces_calls(monkeypatch, _alpaca_fake_clock):
    import src.exchange.alpaca_connector as ac
    stamps = []

    def fake_get(url, params=None, **kwargs):
        stamps.append(_alpaca_fake_clock.t)
        return _Resp({"bars": _hourly(5)})

    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", fake_get)
    md = AlpacaMarketData(api_key="k", api_secret="s")
    for s in ("A", "B", "C"):
        md.get_ohlcv(s, "1h", limit=5)
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= ac._MIN_INTERVAL_S - 1e-9 for g in gaps), gaps


def test_alpaca_non_retryable_error_is_could_not_look(monkeypatch):
    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", lambda *a, **k: _Resp({}, status=403))
    md = AlpacaMarketData(api_key="k", api_secret="s")
    assert md.get_ohlcv("SPY", "1h", limit=10) is None
    assert md.last_read_state["SPY"] == "could_not_look"


def test_alpaca_empty_answer_is_empty_not_rate_limited(monkeypatch):
    monkeypatch.setattr("src.exchange.alpaca_connector.requests.get", lambda *a, **k: _Resp({"bars": []}))
    md = AlpacaMarketData(api_key="k", api_secret="s")
    assert md.get_ohlcv("SPY", "1h", limit=10) is None
    assert md.last_read_state["SPY"] == "empty"
