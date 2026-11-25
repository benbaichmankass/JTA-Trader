"""index_capitulation_1x reads its SIGNAL from Alpaca SIP closed daily bars and keeps the venue (IEX) forming row as the entry
reference (row INDEX-CAPIT-SIP-CLOSED-BARS). Only this leg's input changes: the connector's own feed is untouched."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import src.runtime.strategy_signal_builders as B
from src.units.strategies import index_capitulation_1x as L
from tests.test_index_capitulation_1x import _builder_env, _frame_with_signal


def _venue(f: pd.DataFrame) -> pd.DataFrame:
    """The fetch_candles shape: a tz-aware UTC ``timestamp`` column (midnight ET on the session date), RangeIndex."""
    out = f.reset_index(drop=True).copy()
    out.insert(0, "timestamp", pd.DatetimeIndex(f.index).tz_localize("America/New_York").tz_convert("UTC"))
    out["volume"] = 1000.0
    return out


class _Ex:
    def __init__(self, sip, state="ok"):
        self.sip, self.calls, self.last_read_state = sip, [], {"EFA": state}

    def get_closed_bars(self, symbol, timeframe="1d", limit=200, *, feed="sip"):
        self.calls.append((symbol, timeframe, limit, feed))
        return None if self.sip is None else self.sip.copy()


def _feeds(seed: int = 3):
    """(iex venue frame with NO signal on the last closed bar, sip frame WITH it plus today's partial bar, the signal)."""
    f, s = _frame_with_signal(seed)
    sip_closed = _venue(f.iloc[:-1])
    today = _venue(f.iloc[[-1]])
    sip = pd.concat([sip_closed, today], ignore_index=True)       # the venue can include the forming session at end = now - 16 min
    iex_f = f.copy()
    iex_f.iloc[-2, iex_f.columns.get_loc("close")] = float(iex_f["close"].iloc[-3]) * 0.999   # kills the signal bar's up-close
    iex = _venue(iex_f)
    iex.iloc[-1, iex.columns.get_loc("close")] = float(f["open"].iloc[-1]) * 1.0004            # the IEX first-tick price
    return iex, sip, s


@pytest.fixture(autouse=True)
def _clear_cache():
    B._INDEX_CAPIT_SIP_CACHE.clear()
    yield
    B._INDEX_CAPIT_SIP_CACHE.clear()


def test_iex_alone_has_no_signal_but_sip_closed_bars_do():
    iex, sip, _ = _feeds()
    cfg = {"symbol": "EFA", "k_star": {"EFA": 2.5}}
    with pytest.raises(ValueError, match="no_signal_on_last_closed_bar"):
        L.order_package(cfg, iex)
    frame, feed = B._index_capit_sip_frame("EFA", _Ex(sip), iex)
    assert feed == "sip_closed"
    assert L.order_package(cfg, frame)["sl"] > 0


def test_splice_keeps_sip_closed_rows_and_the_iex_forming_row():
    iex, sip, s = _feeds()
    ex = _Ex(sip)
    frame, feed = B._index_capit_sip_frame("EFA", ex, iex)
    assert feed == "sip_closed" and ex.calls == [("EFA", "1d", 205, "sip")]
    assert len(frame) == len(iex)                                   # SIP's own forming-session row was dropped
    pd.testing.assert_series_equal(frame.iloc[-1], iex.iloc[-1], check_names=False)
    pd.testing.assert_frame_equal(frame.iloc[:-1].reset_index(drop=True),
                                  sip.iloc[:-1][list(frame.columns)].tail(len(frame) - 1).reset_index(drop=True))
    pkg = L.order_package({"symbol": "EFA", "k_star": {"EFA": 2.5}}, frame)
    assert pkg["sl"] == pytest.approx(s["stop"])                    # the stop is SIP's flush-to-signal low
    assert pkg["entry"] == pytest.approx(float(iex["close"].iloc[-1]))   # the entry reference is the IEX forming price


def test_sip_read_once_per_symbol_per_session():
    iex, sip, _ = _feeds()
    ex = _Ex(sip)
    for _ in range(3):
        _frame, feed = B._index_capit_sip_frame("EFA", ex, iex)
        assert feed == "sip_closed"
    assert len(ex.calls) == 1


@pytest.mark.parametrize("state", ["rate_limited", "could_not_look", "empty"])
def test_failed_sip_read_falls_back_to_the_venue_frame_and_names_why(state):
    iex, _sip, _ = _feeds()
    ex = _Ex(None, state=state)
    frame, feed = B._index_capit_sip_frame("EFA", ex, iex)
    assert frame is iex and feed == f"iex_fallback:sip_{state}"
    assert "EFA" not in B._INDEX_CAPIT_SIP_CACHE                    # a failure is never cached: the next tick retries
    B._index_capit_sip_frame("EFA", ex, iex)
    assert len(ex.calls) == 2


def test_sip_missing_the_previous_session_falls_back():
    iex, sip, _ = _feeds()
    stale = sip.iloc[:-2]                                            # no previous-session row, no forming row
    frame, feed = B._index_capit_sip_frame("EFA", _Ex(stale), iex)
    assert frame is iex and feed.startswith("iex_fallback:sip_stale:")


def test_venue_without_closed_bars_is_unchanged():
    iex, _sip, _ = _feeds()
    frame, feed = B._index_capit_sip_frame("EFA", object(), iex)
    assert frame is iex and feed == "venue_default"


def test_builder_trades_the_sip_signal_and_stamps_the_feed(monkeypatch):
    iex, sip, s = _feeds()
    Bm = _builder_env(monkeypatch, iex)
    monkeypatch.setattr(Bm, "_build_killzone_exchange", lambda settings: _Ex(sip))
    rows = []
    monkeypatch.setattr(Bm, "log_signal", lambda row, *a, **k: rows.append(row))
    monkeypatch.setattr(Bm, "_stamp_regime", lambda row, df: row)
    sig = Bm.index_capitulation_1x_signal_builder({"SYMBOL": "EFA"})
    assert sig["side"] == "buy" and sig["meta"]["signal_feed"] == "sip_closed"
    assert sig["stop_loss"] == pytest.approx(s["stop"])
    assert rows and rows[-1]["signal_feed"] == "sip_closed"


def test_builder_on_fallback_decides_on_the_venue_frame(monkeypatch):
    iex, _sip, _ = _feeds()
    Bm = _builder_env(monkeypatch, iex)
    monkeypatch.setattr(Bm, "_build_killzone_exchange", lambda settings: _Ex(None, state="rate_limited"))
    rows = []
    monkeypatch.setattr(Bm, "log_signal", lambda row, *a, **k: rows.append(row))
    monkeypatch.setattr(Bm, "_stamp_regime", lambda row, df: row)
    sig = Bm.index_capitulation_1x_signal_builder({"SYMBOL": "EFA"})
    assert sig["side"] == "none" and sig["meta"]["reason"] == "no_signal_on_last_closed_bar"
    assert rows[-1]["signal_feed"] == "iex_fallback:sip_rate_limited"


# ------------------------------------------------------------------------------------------------------------ the connector
class _Resp:
    status_code = 200

    def __init__(self, bars):
        self._bars = bars

    def raise_for_status(self):
        return None

    def json(self):
        return {"bars": self._bars, "next_page_token": None}


def _bar(day: str) -> dict:
    return {"t": f"{day}T05:00:00Z", "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.05, "v": 10}


def test_connector_closed_bars_ask_sip_ending_16_min_ago_and_leave_the_feed_alone(monkeypatch):
    import src.exchange.alpaca_connector as AC

    sent = []
    monkeypatch.setattr(AC.requests, "get", lambda url, params=None, **k: sent.append(dict(params)) or _Resp([_bar("2026-11-24")]))
    md = AC.AlpacaMarketData(api_key="k", api_secret="s", feed="iex")
    before = datetime.now(timezone.utc)
    df = md.get_closed_bars("EFA", "1d", limit=5)
    assert df is not None and len(df) == 1 and md.last_read_state["EFA"] == "ok"
    assert sent[-1]["feed"] == "sip"
    end = datetime.strptime(sent[-1]["end"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before - timedelta(minutes=17) <= end <= before - timedelta(minutes=15)
    assert md.feed == "iex"
    md.get_ohlcv("EFA", "1d", limit=5)                               # every other read keeps the account's feed and no end
    assert sent[-1]["feed"] == "iex" and "end" not in sent[-1]


def test_connector_closed_bars_failure_is_a_named_read_state(monkeypatch):
    import src.exchange.alpaca_connector as AC

    class _Forbidden(_Resp):
        status_code = 403

        def raise_for_status(self):
            raise AC.requests.HTTPError("403 subscription does not permit querying recent SIP data")

    monkeypatch.setattr(AC.requests, "get", lambda url, params=None, **k: _Forbidden([]))
    md = AC.AlpacaMarketData(api_key="k", api_secret="s")
    assert md.get_closed_bars("EFA") is None and md.last_read_state["EFA"] == "could_not_look"
