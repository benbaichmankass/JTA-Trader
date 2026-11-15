"""PROP-CANDLE-FEED-FIX (2026-11-12): an UNSET ``BYBIT_TESTNET`` must read MAINNET candles.

The prop executor tick exports only its mode / login / token keys, so the market-data builder's old default
(``"true"``) sent every prop candle read (the trail's SOLUSDT 4h: low 22.93 / high 172.22 against a real ~81) to
the Bybit testnet market. These tests pin the default and the explicit overrides.
"""
from __future__ import annotations

import pytest

from src.runtime import market_data as md


@pytest.fixture(autouse=True)
def _fresh_clients():
    md.reset_exchange_client_cache()
    yield
    md.reset_exchange_client_cache()


@pytest.mark.parametrize("raw,expected", [
    (None, False),          # the prop-executor shape: variable not exported at all
    ("", False),
    ("false", False), ("0", False), ("no", False), ("FALSE", False),
    ("true", True), ("True", True), ("1", True), ("yes", True),
])
def test_bybit_testnet_flag(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("BYBIT_TESTNET", raising=False)
    else:
        monkeypatch.setenv("BYBIT_TESTNET", raw)
    assert md.bybit_testnet() is expected


def test_unset_env_builds_a_mainnet_connector(monkeypatch):
    monkeypatch.delenv("BYBIT_TESTNET", raising=False)
    client = md._build_exchange_client({"EXCHANGE": "bybit"})
    assert client.testnet is False
    # the memo key carries the same flag, so a mainnet and a testnet client never share a slot
    assert md._client_cache_key({"EXCHANGE": "bybit"})[2] is False


def test_explicit_true_still_reads_testnet(monkeypatch):
    monkeypatch.setenv("BYBIT_TESTNET", "true")
    client = md._build_exchange_client({"EXCHANGE": "bybit"})
    assert client.testnet is True
    assert md._client_cache_key({"EXCHANGE": "bybit"})[2] is True


def test_prop_trail_default_candles_fn_routes_to_mainnet(monkeypatch):
    """The trail's own candle path (prop_trail.default_candles_fn -> connector_for_symbol) with the prop tick's env."""
    monkeypatch.delenv("BYBIT_TESTNET", raising=False)
    seen = {}

    def fake_fetch(symbol, timeframe, *, limit, bypass_cache, exchange_client):
        seen["testnet"] = getattr(exchange_client, "testnet", None)
        seen["symbol"] = symbol
        return None

    monkeypatch.setattr(md, "fetch_candles", fake_fetch)
    from src.prop import prop_trail
    prop_trail.default_candles_fn()("SOLUSDT", "4h")
    assert seen == {"testnet": False, "symbol": "SOLUSDT"}
