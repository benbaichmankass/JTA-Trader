"""P2b — read-only market-data WebSocket ``/ws/market``.

Verifies the endpoint accepts a connection, streams the ``hello`` frame, then
pushes ``candles`` (one per subscribed symbol) + a ``positions`` frame, and
degrades gracefully when the underlying fetchers return nothing (no exchange
creds / empty DB in CI). No order path — a pure read surface.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.web.api.main import app


def test_ws_market_streams_hello_candles_positions():
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/market?symbols=BTCUSDT,MES&interval=5m&limit=50"
        ) as ws:
            frames = [ws.receive_json() for _ in range(5)]

    # First frame is always the hello, echoing the subscription.
    assert frames[0]["type"] == "hello"
    assert frames[0]["symbols"] == ["BTCUSDT", "MES"]
    assert frames[0]["interval"] == "5m"

    assert frames[0]["candle_symbols"] == ["MES"] and frames[0]["browser_fed"] == ["BTCUSDT"]
    types = {f["type"] for f in frames}
    assert "candles" in types, "expected at least one candle frame"
    assert "positions" in types, "expected a positions frame"
    src = [f for f in frames if f["type"] == "candles_source"]
    assert len(src) == 1 and src[0]["symbol"] == "BTCUSDT" and src[0]["feed"] == "bybit_public_ws"

    for f in frames:
        if f["type"] == "candles":
            assert f["symbol"] == "MES", "T3a: *USDT candles are browser-fed, never fetched here"
            assert f["interval"] == "5m"
            assert isinstance(f["candles"], list)  # possibly empty (no creds in CI)
        if f["type"] == "positions":
            assert isinstance(f["positions"], list)


def test_ws_market_empty_symbols_still_streams_positions():
    """No symbols → no candle frames, but the positions stream still runs."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/market") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert hello["symbols"] == []
            nxt = ws.receive_json()
            assert nxt["type"] == "positions"
            assert isinstance(nxt["positions"], list)


def test_ws_market_never_fetches_usdt_candles(monkeypatch):
    """T3a acceptance, bot side: a *USDT-only subscription makes ZERO candle fetches through the VM."""
    from src.web.api.routers import market_ws
    calls = []
    monkeypatch.setattr(market_ws, "_fetch_candles", lambda sym, *a: calls.append(sym) or [])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/market?symbols=BTCUSDT,ETHUSDT") as ws:
            frames = [ws.receive_json() for _ in range(5)]
    assert calls == []
    assert [f["symbol"] for f in frames if f["type"] == "candles_source"] == ["BTCUSDT", "ETHUSDT"]
    assert not any(f["type"] == "candles" for f in frames)
    assert any(f["type"] == "positions" for f in frames)
