"""CLOSED-TRADE-SNAPSHOT-FUTURES-CANDLES (c): IBMarketData historical ``since`` read, its builder pacing, and the
one-off IB re-queue. The live tick never passes ``since`` (endDateTime stays "" = now)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pandas")

from src.exchange import ib_connector as ibc  # noqa: E402
from src.runtime import trade_snapshot_builder as tsb  # noqa: E402

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class _Bar:
    def __init__(self, dt):
        self.date = dt
        self.open = self.high = self.low = self.close = 4300.0
        self.volume = 10


class _Client:
    symbol = "MGC"

    def __init__(self, bars):
        self.calls = []
        self._bars = bars

    def connect(self):
        return self

    def _ensure_event_loop(self):
        return None

    def _build_contract(self, symbol):
        return object()

    def reqMarketDataType(self, *_a, **_k):
        return None

    def reqHistoricalData(self, contract, **kw):
        self.calls.append(kw)
        return self._bars


def _md(bars):
    c = _Client(bars)
    return ibc.IBMarketData(port=7497, client_id=9358, account=None, _client=c), c


def test_live_read_still_ends_now():
    md, c = _md([_Bar(T0)])
    assert md.get_ohlcv("MGC", "5m", limit=10) is not None
    assert c.calls[0]["endDateTime"] == ""


def test_since_end_is_capped_at_now():
    future = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp() * 1000)
    end = ibc._since_end("1h", 10, future)
    assert end <= datetime.now(timezone.utc)
    assert ibc._since_end("1h", 10, None) == ""


def test_plain_get_ohlcv_takes_no_since_so_old_windows_stay_uncovered():
    md, _ = _md([_Bar(T0)])
    with pytest.raises(TypeError):
        md.get_ohlcv("MGC", "5m", limit=5, since=1)     # fetch_candles turns this TypeError into None


class _Evt:
    def __init__(self):
        self.h = []

    def __iadd__(self, f):
        self.h.append(f)
        return self

    def __isub__(self, f):
        self.h.remove(f)
        return self

    def fire(self, *a):
        for f in list(self.h):
            f(*a)


class _Detail:
    def __init__(self, con_id, last, month):
        self.contract = type("C", (), {"conId": con_id, "lastTradeDateOrContractMonth": last})()
        self.contractMonth = month


class _IBFake(_Client):
    """Two MGC contracts priced 100 apart; bars every 5m from T0 - 1h to T0 + 3h."""

    def __init__(self, error=None):
        super().__init__([])
        self.errorEvent = _Evt()
        self.detail_calls = 0
        self.error = error
        self.hist = []

    def reqContractDetails(self, c):
        self.detail_calls += 1
        return [_Detail(1, "20261028", "202610"), _Detail(2, "20261229", "202612"), _Detail(0, "", "")]

    def reqHistoricalData(self, contract, **kw):
        self.hist.append((contract.conId, kw))
        if self.error:
            self.errorEvent.fire(7, self.error[0], self.error[1], contract)
            return []
        px = 4000.0 if contract.conId == 1 else 4100.0
        out = []
        for i in range(-12, 36):
            b = _Bar(T0 + timedelta(minutes=5 * i))
            b.open = b.close = px
            b.low, b.high = px - 2, px + 2
            out.append(b)
        return out


@pytest.fixture(autouse=True)
def _reset_ib_state(monkeypatch):
    import importlib.util
    import sys
    import types
    if importlib.util.find_spec("ib_insync") is None and importlib.util.find_spec("ib_async") is None:
        mod = types.ModuleType("ib_insync")

        class Future:  # the only surface get_ohlcv_at uses: a constructor carrying conId
            def __init__(self, **kw):
                self.__dict__.update(kw)
                self.conId = kw.get("conId", 0)
        mod.Future = Future
        monkeypatch.setitem(sys.modules, "ib_insync", mod)
    ibc._EXPIRIES.clear()
    ibc._PACING.update(until=0.0, last=None)
    yield
    ibc._EXPIRIES.clear()
    ibc._PACING.update(until=0.0, last=None)


def _at(fake, symbol="MGC", price=4100.5):
    md = ibc.IBMarketData(port=7497, client_id=9358, account=None, _client=fake)
    ms = int(T0.timestamp() * 1000)
    return md.get_ohlcv_at(symbol, "5m", 24, ms, price, ms)


def test_get_ohlcv_at_picks_the_contract_whose_bars_contain_the_fill():
    fake = _IBFake()
    df, info = _at(fake, price=4100.5)                   # matches the Dec contract, not the Oct one tried first
    assert info["outcome"] == "matched" and info["contract"] == "202612" and info["tried"] == ["202610", "202612"]
    assert info["requests"] == 3 and len(df) == 24
    assert df["timestamp"].iloc[0].tz_convert("UTC") == T0
    assert fake.hist[0][1]["endDateTime"] == T0 + timedelta(minutes=120)
    _, info2 = _at(fake, price=4000.0)                   # expiries cached: no second contract-details request
    assert info2["contract"] == "202610" and fake.detail_calls == 1


def test_get_ohlcv_at_never_charts_a_contract_that_misses_the_fill():
    df, info = _at(_IBFake(), price=3500.0)
    assert df is None and info["outcome"] == "price_mismatch"


def test_explicit_contract_month_symbol_reads_that_month_only():
    fake = _IBFake()
    _, info = _at(fake, symbol="MGCV6", price=4000.0)      # V = October
    assert info["outcome"] == "matched" and info["tried"] == ["202610"]


def test_pacing_error_backs_off_and_sends_nothing_after():
    fake = _IBFake(error=(162, "Historical Market Data Service error message: pacing violation"))
    df, info = _at(fake)
    assert df is None and info["outcome"] == "deferred" and len(fake.hist) == 1   # no inline retry, no 2nd contract
    assert ibc.pacing_backoff_remaining() > ibc.PACING_BACKOFF_S - 5
    sent = len(fake.hist)
    _, info2 = _at(fake)
    assert info2["outcome"] == "deferred" and len(fake.hist) == sent and info2["requests"] == 0


def test_no_data_162_is_an_empty_answer_not_pacing():
    """MEASURED 2026-11-13: 'HMDS query returned no data: MGCV6@COMEX' arrived as error 162. It must not back off
    or keep the trade queued -- the next contract is tried and the outcome says what happened."""
    class _NoDataOct(_IBFake):
        def reqHistoricalData(self, contract, **kw):
            if contract.conId == 1:
                self.hist.append((contract.conId, kw))
                self.errorEvent.fire(5, 162, "Historical Market Data Service error message:HMDS query returned no data: MGCV6@COMEX Trades", contract)
                return []
            return super().reqHistoricalData(contract, **kw)
    fake = _NoDataOct()
    df, info = _at(fake, price=4100.5)
    assert info["outcome"] == "matched" and info["contract"] == "202612" and info["tried"] == ["202610", "202612"]
    assert ibc.pacing_backoff_remaining() == 0
    _, info2 = _at(_NoDataOct(), price=3500.0)          # nothing matches: an outcome, never a deferral
    assert info2["outcome"] in ("no_bars", "price_mismatch") and ibc.pacing_backoff_remaining() == 0


def test_query_cancelled_162_still_backs_off():
    _, info = _at(_IBFake(error=(162, "Historical Market Data Service error message:API historical data query cancelled: 7")))
    assert info["outcome"] == "deferred" and ibc.pacing_backoff_remaining() > 0


def test_error_420_also_backs_off():
    _, info = _at(_IBFake(error=(420, "Invalid real-time query")))
    assert info["outcome"] == "deferred" and ibc.pacing_backoff_remaining() > 0


def test_non_futures_symbol_is_unsupported_not_an_error():
    _, info = _at(_IBFake(), symbol="BTCUSDT")
    assert info["outcome"] == "unsupported"


def _builder_env(monkeypatch, md):
    import concurrent.futures as cf

    from src.web.api.routers import candles as cr
    clock = {"t": 1000.0}
    slept = []
    monkeypatch.setattr(tsb, "_mono", lambda: clock["t"])
    monkeypatch.setattr(tsb, "_sleep", lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s)))
    monkeypatch.setitem(tsb._ib_since_last, "at", None)
    monkeypatch.setattr(cr, "_settings", lambda: {})
    monkeypatch.setattr(cr, "_connector", lambda symbol, settings: md)
    monkeypatch.setattr(cr, "_FETCH_EXECUTOR", cf.ThreadPoolExecutor(max_workers=1))
    return slept


def test_builder_paces_ib_since_reads_and_names_the_contract(monkeypatch):
    fake = _IBFake()
    md = ibc.IBMarketData(port=7497, client_id=9358, account=None, _client=fake)
    slept = _builder_env(monkeypatch, md)
    ms = int(T0.timestamp() * 1000)
    rows, source = tsb.web_api_fetch("MGC", "5m", ms, 24, anchor=(4100.5, ms))
    assert rows and source == "bot-exchange:ib:202612"
    tsb.web_api_fetch("MGC", "5m", ms, 24, anchor=(4100.5, ms))
    assert len(slept) == 1 and slept[0] >= tsb.IB_SINCE_MIN_INTERVAL_S
    assert tsb.IB_OUTCOMES[-1]["outcome"] == "matched" and tsb.web_api_fetch.accepts_anchor


def test_builder_returns_deferred_during_backoff(monkeypatch):
    md = ibc.IBMarketData(port=7497, client_id=9358, account=None, _client=_IBFake())
    _builder_env(monkeypatch, md)
    ibc._PACING["until"] = ibc._now_mono() + 300
    rows, _ = tsb.web_api_fetch("MGC", "5m", int(T0.timestamp() * 1000), 24, anchor=(4100.5, 0))
    assert rows is tsb.DEFERRED


def test_ib_pace_bounds_requests_per_10_min():
    # worst case 2 bar requests per call (contract retry) + the trader's worst measured window (51 per 10 min, all
    # request types, 2026-11-12 reqId growth) must stay under IB's 60 per 10 min
    assert 51 + 2 * 600 / tsb.IB_SINCE_MIN_INTERVAL_S < 60


def test_contract_month_routes_to_its_root():
    assert tsb._routes_to("MHGN6", {"MHG"}) and tsb._routes_to("MGC", {"MGC"})
    assert not tsb._routes_to("AAPL", {"MHG"}) and not tsb._routes_to(None, {"MHG"})


def test_ib_symbols_read_from_instrument_profiles():
    syms = tsb._venue_symbols(tsb._IB_VENUES)
    assert {"MES", "MGC"} <= syms and "BTCUSDT" not in syms
