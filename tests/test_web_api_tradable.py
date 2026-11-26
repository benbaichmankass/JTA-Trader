"""GET /api/bot/tradable + unprofiled-equity candle routing (DESK-MACRO-DAILY, operator 2026-11-26: the macro brief may
recommend "any symbols that we are able to trade"). Read-only; the venue calls are monkeypatched."""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.web.api import main as api_main  # noqa: E402
from src.web.api.routers import candles as R  # noqa: E402


class _P:
    def __init__(self, exchange):
        self.exchange = exchange


PROFILES = {"MES": _P("interactive_brokers"), "SPY": _P("alpaca"), "BTCUSDT": _P("bybit")}


@pytest.fixture(autouse=True)
def _clear():
    R._TRADABLE_CACHE.clear()
    yield
    R._TRADABLE_CACHE.clear()


def test_classify_profile_first_then_shape():
    assert R.classify("MES", PROFILES)["exchange"] == "interactive_brokers"
    assert R.classify("MESZ6", PROFILES)["basis"] == "instrument_profile"          # contract month -> profiled root
    assert R.classify("SPY", PROFILES)["basis"] == "instrument_profile"
    assert R.classify("HYPEUSDT", PROFILES) == {"exchange": "bybit", "basis": "crypto_suffix"}
    assert R.classify("NVDA", PROFILES) == {"exchange": "alpaca", "basis": "equity_shape_unprofiled"}
    assert R.classify("BRK.B", PROFILES)["exchange"] == "alpaca"
    assert R.classify("not a symbol", PROFILES)["exchange"] is None


def test_unprofiled_equity_routes_candles_to_alpaca(monkeypatch):
    monkeypatch.setattr(R, "_profiles", lambda: PROFILES)
    assert R._routed_settings("NVDA", {"EXCHANGE": "bybit"})["EXCHANGE"] == "alpaca"
    assert R._routed_settings("HYPEUSDT", {"EXCHANGE": "bybit"}) == {"EXCHANGE": "bybit"}     # unchanged
    assert R._routed_settings("MES", {"EXCHANGE": "bybit"}) == {"EXCHANGE": "bybit"}          # profile routes it downstream


def test_parsers_never_turn_a_failed_read_into_false():
    assert R.parse_alpaca_asset(500, {})["tradable"] is None
    assert R.parse_alpaca_asset(404, {})["tradable"] is False
    assert R.parse_alpaca_asset(200, {"tradable": True, "status": "active", "shortable": True})["tradable"] is True
    assert R.parse_alpaca_asset(200, {"tradable": True, "status": "inactive"})["tradable"] is False
    assert R.parse_bybit_instrument("X", {"retCode": 10001})["tradable"] is None
    assert R.parse_bybit_instrument("HYPEUSDT", {"retCode": 0, "result": {"list": [{"symbol": "HYPEUSDT", "status": "Trading"}]}})["tradable"] is True
    assert R.parse_bybit_instrument("ZZZUSDT", {"retCode": 0, "result": {"list": []}})["tradable"] is False


def test_route_wire_shape_and_cache(monkeypatch):
    calls = []

    def one(sym):
        calls.append(sym)
        return {"read_state": "measured", "exchange": "alpaca", "tradable": True, "basis": "equity_shape_unprofiled"}
    monkeypatch.setattr(R, "_tradable_one", one)
    c = TestClient(api_main.app, raise_server_exceptions=False)
    body = c.get("/api/bot/tradable?symbols=nvda,aapl").json()
    assert body["n"] == 2 and body["symbols"]["NVDA"]["tradable"] is True
    c.get("/api/bot/tradable?symbols=NVDA")
    assert calls == ["NVDA", "AAPL"]                                            # second call served from the 6 h cache
