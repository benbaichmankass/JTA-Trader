"""EXIT-EVAL-IB-OUTAGE-STALL: pre-trip the per-pass IB breaker when the IB client
already reports it cannot answer.

MEASURED 2026-11-13 (ict-trader-live journal 05:16:30-05:19:30Z): IB Error 1100
(gateway lost IBKR) from 05:16:41Z; at 05:17:53Z the exit loop's MHG/1d fetch
waited 29.0 s on the pinned IB thread before the breaker tripped; exit passes at
05:17:16 and 05:18:25 -> a 69 s interval -> EXIT-EVAL INTERVAL BREACHED.

What these tests pin (a harness cannot reach a real gateway, so the fleet half is
the row's observation, not this file):
  * IBClient tracks 1100 -> lost and 1101/1102 -> restored, and a fresh connect
    resets it;
  * the exit loop's fetcher pre-trips on that state, skips IB packages with the
    same candles=None the timeout would have produced, and CLEARS when the state
    clears;
  * a Bybit package is never skipped;
  * the rollback (EXIT_LOOP_IB_BREAKER_DISABLED) restores the prior behaviour;
  * the 05:16-05:18Z sequence breaches without the pre-trip and does not with it.
"""
from __future__ import annotations

import pandas as pd
import pytest

import src.main as main_module
from src.exchange import ib_connector
from src.units.accounts.ib_client import IBClient


# --------------------------------------------------------------------------
# IBClient: the link state.
# --------------------------------------------------------------------------


class _Event:
    """ib_insync-style event: `+=` subscribes, `emit` calls every handler."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def emit(self, *args):
        for fn in list(self.handlers):
            fn(*args)


class _FakeIBHandle:
    def __init__(self):
        self.errorEvent = _Event()


def _client() -> IBClient:
    return IBClient(host="127.0.0.1", port=4002, client_id=91)


def test_1100_marks_the_link_lost_and_1101_or_1102_restores_it():
    c, ib = _client(), _FakeIBHandle()
    c._attach_link_watch(ib)
    assert c.ibkr_link_lost is False
    ib.errorEvent.emit(-1, 1100, "Connectivity between IBKR and Trader Workstation has been lost.", None)
    assert c.ibkr_link_lost is True
    ib.errorEvent.emit(-1, 2104, "Market data farm connection is OK", None)  # unrelated: no change
    assert c.ibkr_link_lost is True
    ib.errorEvent.emit(-1, 1102, "Connectivity restored - data maintained.", None)
    assert c.ibkr_link_lost is False
    ib.errorEvent.emit(-1, 1100, "lost", None)
    ib.errorEvent.emit(-1, 1101, "Connectivity restored - data lost.", None)
    assert c.ibkr_link_lost is False


def test_garbage_error_codes_never_raise_or_flip_the_state():
    c, ib = _client(), _FakeIBHandle()
    c._attach_link_watch(ib)
    ib.errorEvent.emit(-1, None, "x", None)
    ib.errorEvent.emit(-1, "not-a-code", "x", None)
    assert c.ibkr_link_lost is False


def test_a_handle_without_error_event_leaves_the_state_not_lost():
    c = _client()
    c._attach_link_watch(object())
    assert c.ibkr_link_lost is False


# --------------------------------------------------------------------------
# The fetcher: pre-trip, clear, Bybit untouched, rollback.
# --------------------------------------------------------------------------


class _LinkState:
    """Stands in for the IBClient behind an IBMarketData."""

    def __init__(self, lost=False, connected=True, has_handle=True):
        self.ibkr_link_lost = lost
        self.connected = connected
        self._ib = object() if has_handle else None


class _FakeIB(ib_connector.IBMarketData):
    def __init__(self, link):  # noqa: D107 -- no socket
        self._client = link


class _FakeBybit:
    pass


@pytest.fixture
def harness(monkeypatch):
    ib_connector.consume_queue_timeout()
    monkeypatch.delenv("EXIT_LOOP_IB_BREAKER_DISABLED", raising=False)
    link = _LinkState()
    ib, bybit = _FakeIB(link), _FakeBybit()
    state = {"calls": [], "link": link, "clock": [0.0], "hang_s": 29.0}

    monkeypatch.setattr(
        "src.runtime.market_data.connector_for_symbol",
        lambda symbol, settings: ib if symbol in {"MES", "MGC", "MHG"} else bybit,
    )

    def _fake_fetch_candles(symbol, timeframe, **kwargs):
        state["calls"].append(symbol)
        if symbol in {"MES", "MGC", "MHG"} and (link.ibkr_link_lost or not link.connected):
            # what the gateway outage did: the pinned queue does not answer
            state["clock"][0] += state["hang_s"]
            ib_connector._mark_queue_timeout()
            return None
        state["clock"][0] += 0.2
        return pd.DataFrame({"close": [1.0]})

    monkeypatch.setattr("src.runtime.market_data.fetch_candles", _fake_fetch_candles)
    monkeypatch.setattr("src.units.strategies.load_strategy_config", lambda: {}, raising=False)
    return state


def test_link_lost_pre_trips_and_no_ib_fetch_is_attempted(harness):
    harness["link"].ibkr_link_lost = True
    fetch = main_module._build_monitor_ohlcv_fetcher({})
    assert fetch("MGC", "15m") is None
    assert fetch("MHG", "1d") is None
    assert harness["calls"] == []  # nobody waited on the pinned queue
    rep = main_module._ib_breaker_report(fetch)["ib_breaker"]
    assert rep == {"state": "armed", "tripped": True, "skipped": 2,
                   "pre_trip": "IBKR connectivity lost (Error 1100)"}


def test_a_disconnected_socket_pre_trips_too(harness):
    harness["link"].connected = False
    fetch = main_module._build_monitor_ohlcv_fetcher({})
    assert fetch("MGC", "15m") is None
    assert harness["calls"] == []
    assert main_module._ib_breaker_report(fetch)["ib_breaker"]["pre_trip"] == "the IB socket is disconnected"


def test_no_handle_yet_is_not_a_pre_trip_so_the_first_connect_still_happens(harness):
    harness["link"].connected = False
    harness["link"]._ib = None
    fetch = main_module._build_monitor_ohlcv_fetcher({})
    fetch("MGC", "15m")
    assert harness["calls"] == ["MGC"]


def test_the_pre_trip_clears_when_connectivity_returns(harness):
    harness["link"].ibkr_link_lost = True
    first = main_module._build_monitor_ohlcv_fetcher({})
    assert first("MGC", "15m") is None and harness["calls"] == []
    harness["link"].ibkr_link_lost = False  # 1101/1102 arrived
    second = main_module._build_monitor_ohlcv_fetcher({})
    assert second("MGC", "15m") is not None
    assert harness["calls"] == ["MGC"]
    assert "pre_trip" not in main_module._ib_breaker_report(second)["ib_breaker"]


def test_a_bybit_package_is_never_skipped_during_an_ib_outage(harness):
    harness["link"].ibkr_link_lost = True
    fetch = main_module._build_monitor_ohlcv_fetcher({})
    assert fetch("MGC", "15m") is None
    assert fetch("BTCUSDT", "5m") is not None
    assert fetch("ETHUSDT", "1h") is not None
    assert harness["calls"] == ["BTCUSDT", "ETHUSDT"]


def test_the_rollback_restores_the_prior_behaviour(monkeypatch, harness):
    monkeypatch.setenv("EXIT_LOOP_IB_BREAKER_DISABLED", "1")
    harness["link"].ibkr_link_lost = True
    fetch = main_module._build_monitor_ohlcv_fetcher({})
    fetch("MGC", "15m")
    fetch("MHG", "1d")
    assert harness["calls"] == ["MGC", "MHG"]  # every IB package asked again
    assert main_module._ib_breaker_report(fetch)["ib_breaker"]["state"] == "disabled"


def test_an_unreadable_client_never_pre_trips():
    class _Hostile:
        @property
        def _client(self):
            raise RuntimeError("boom")

    assert main_module._ib_link_down(_Hostile()) is None
    assert main_module._ib_link_down(object()) is None


# --------------------------------------------------------------------------
# The 2026-11-13 05:16-05:18Z sequence, on a simulated clock.
# --------------------------------------------------------------------------

#: time between the previous pass's end and this pass's IB fetches, without IB
#: waits (05:17:16 -> 05:18:25 was 69 s with one 29 s wait, so ~40 s otherwise)
_BASELINE_S = 40.0
_REQUIREMENT_S = 60.0
_PACKAGES = [("BTCUSDT", "5m"), ("MHG", "1d"), ("MGC", "15m"), ("MES", "5m"), ("ETHUSDT", "1h")]


def test_reproduces_the_breach_without_the_pre_trip(harness, monkeypatch):
    # The pre-fix client: no ibkr_link_lost attribute. The gateway still hangs.
    old = type("_OldClient", (), {})()
    old.connected, old._ib = True, object()
    ib = _FakeIB(old)
    monkeypatch.setattr(
        "src.runtime.market_data.connector_for_symbol",
        lambda symbol, settings: ib if symbol in {"MES", "MGC", "MHG"} else _FakeBybit(),
    )
    harness["link"].ibkr_link_lost = True  # drives the fake hang
    harness["clock"][0] = _BASELINE_S
    fetch = main_module._build_monitor_ohlcv_fetcher({})
    for sym, tf in _PACKAGES:
        fetch(sym, tf)
    interval = harness["clock"][0]
    assert interval > _REQUIREMENT_S, interval  # 40 + 29 (+ crypto) = the 69 s breach
    assert harness["calls"][:2] == ["BTCUSDT", "MHG"]  # MHG paid the wait, then the breaker tripped


def test_no_breach_with_the_pre_trip(harness):
    harness["link"].ibkr_link_lost = True
    harness["clock"][0] = _BASELINE_S
    fetch = main_module._build_monitor_ohlcv_fetcher({})
    for sym, tf in _PACKAGES:
        fetch(sym, tf)
    interval = harness["clock"][0]
    assert interval < _REQUIREMENT_S, interval
    assert harness["calls"] == ["BTCUSDT", "ETHUSDT"]  # crypto evaluated, IB skipped
