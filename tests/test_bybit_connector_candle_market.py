"""BybitConnector candle reads resolve to the market the account TRADES (PI-20261103-SPOTCANDLES-0001).

The ccxt client is built ``defaultType: spot``; a bare ``BTCUSDT`` resolved to the SPOT market, so every
perp-traded Bybit leg read spot candles. These tests pin the connector-level fix: a linear connector asks
for ``BASE/USDT:USDT`` and the V5 kline request carries ``category=linear``; a spot connector keeps spot.
"""
from __future__ import annotations

import pytest

from src.exchange.bybit_connector import BybitConnector, market_symbol

ccxt = pytest.importorskip("ccxt")


@pytest.mark.parametrize("sym,mt,want", [
    ("BTCUSDT", "linear", "BTC/USDT:USDT"),
    ("XRPUSDT", None, "XRP/USDT:USDT"),          # default market_type is linear
    ("AVAXUSDT", "LINEAR", "AVAX/USDT:USDT"),
    ("BTCUSDT", "spot", "BTC/USDT"),
    ("BTC/USDT:USDT", "linear", "BTC/USDT:USDT"),  # already unified: unchanged
    ("ETH/USDT", "linear", "ETH/USDT"),
    ("USDT", "linear", "USDT"),
    ("BTCPERP", "linear", "BTCPERP"),               # not a USDT id: unchanged
    ("", "linear", ""),
])
def test_market_symbol(sym, mt, want):
    assert market_symbol(sym, mt) == want


def _market(kind: str) -> dict:
    spot = kind == "spot"
    return {
        "id": "BTCUSDT", "symbol": "BTC/USDT" if spot else "BTC/USDT:USDT",
        "base": "BTC", "quote": "USDT", "settle": None if spot else "USDT",
        "baseId": "BTC", "quoteId": "USDT", "settleId": None if spot else "USDT",
        "type": "spot" if spot else "swap", "spot": spot, "margin": False, "swap": not spot,
        "future": False, "option": False, "active": True, "contract": not spot,
        "linear": None if spot else True, "inverse": None if spot else False,
        "contractSize": None if spot else 1.0, "precision": {"amount": 0.001, "price": 0.1},
        "limits": {}, "info": {}, "taker": 0.001, "maker": 0.001,
    }


def _connector_capturing(market_type: str):
    conn = BybitConnector(api_key=None, api_secret=None, testnet=False, market_type=market_type)
    conn.exchange.set_markets([_market("spot"), _market("linear")])
    seen = []

    def kline(params, *a, **k):
        seen.append(dict(params))
        return {"retCode": 0, "result": {"category": params.get("category"), "list": []}}
    conn.exchange.publicGetV5MarketKline = kline
    return conn, seen


def test_bare_id_on_spot_default_client_resolves_spot_without_the_fix():
    """The defect, reproduced on the real ccxt resolver: a bare id picks the SPOT market."""
    conn, _ = _connector_capturing("linear")
    assert conn.exchange.market("BTCUSDT")["spot"] is True


def test_linear_connector_reads_linear_klines():
    conn, seen = _connector_capturing("linear")
    conn.get_ohlcv("BTCUSDT", "1h", limit=5)
    assert seen and seen[-1]["category"] == "linear"
    assert seen[-1]["symbol"] == "BTCUSDT"


def test_default_connector_is_linear_as_market_data_builds_it():
    """market_data._build_exchange_client builds BybitConnector without market_type."""
    conn = BybitConnector(api_key=None, api_secret=None, testnet=False)
    assert conn.market_type == "linear"


def test_spot_connector_keeps_spot_klines():
    conn, seen = _connector_capturing("spot")
    conn.get_ohlcv("BTCUSDT", "1h", limit=5)
    assert seen and seen[-1]["category"] == "spot"


def test_unified_symbol_from_ml_entry_still_linear():
    conn, seen = _connector_capturing("linear")
    conn.get_ohlcv("BTC/USDT:USDT", "1h", limit=5)
    assert seen[-1]["category"] == "linear"
