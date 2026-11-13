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


def test_since_read_ends_limit_bars_after_since_and_trims_the_headroom():
    since_ms = int(T0.timestamp() * 1000)
    bars = [_Bar(T0 + timedelta(minutes=5 * i)) for i in range(-6, 20)]   # 6 bars before the start (headroom)
    md, c = _md(bars)
    df = md.get_ohlcv("MGC", "5m", limit=12, since=since_ms)
    end = c.calls[0]["endDateTime"]
    assert end == T0 + timedelta(minutes=60)                             # since + 12 x 5m, UTC
    assert len(df) == 12 and df["timestamp"].iloc[0].tz_convert("UTC") == T0


def test_since_end_is_capped_at_now():
    future = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp() * 1000)
    end = ibc._since_end("1h", 10, future)
    assert end <= datetime.now(timezone.utc)
    assert ibc._since_end("1h", 10, None) == ""


def test_since_read_with_nothing_in_window_is_none():
    md, _ = _md([_Bar(T0 - timedelta(hours=3))])
    assert md.get_ohlcv("MGC", "5m", limit=5, since=int(T0.timestamp() * 1000)) is None


def test_builder_paces_ib_since_reads_at_15s(monkeypatch):
    import concurrent.futures as cf

    import src.runtime.market_data as mdmod
    from src.web.api.routers import candles as cr

    clock = {"t": 1000.0}
    slept = []
    monkeypatch.setattr(tsb, "_mono", lambda: clock["t"])
    monkeypatch.setattr(tsb, "_sleep", lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s)))
    monkeypatch.setitem(tsb._ib_since_last, "at", None)
    md, _ = _md([])
    monkeypatch.setattr(cr, "_settings", lambda: {})
    monkeypatch.setattr(cr, "_connector", lambda symbol, settings: md)
    monkeypatch.setattr(cr, "_FETCH_EXECUTOR", cf.ThreadPoolExecutor(max_workers=1))
    venue = []
    monkeypatch.setattr(mdmod, "fetch_candles", lambda symbol, interval, **kw: venue.append(kw.get("since")))
    tsb.web_api_fetch("MGC", "5m", 1_700_000_000_000, 10)
    tsb.web_api_fetch("MGC", "5m", 1_700_000_000_000, 10)
    assert len(venue) == 2 and len(slept) == 1 and slept[0] >= tsb.IB_SINCE_MIN_INTERVAL_S
    tsb.web_api_fetch("MGC", "5m", None, 10)                                # a recent read is never paced
    assert len(slept) == 1


def test_contract_month_routes_to_its_root():
    assert tsb._routes_to("MHGN6", {"MHG"}) and tsb._routes_to("MGC", {"MGC"})
    assert not tsb._routes_to("AAPL", {"MHG"}) and not tsb._routes_to(None, {"MHG"})


def test_ib_symbols_read_from_instrument_profiles():
    syms = tsb._venue_symbols(tsb._IB_VENUES)
    assert {"MES", "MGC"} <= syms and "BTCUSDT" not in syms
