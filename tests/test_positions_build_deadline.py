"""WEBAPP-API-SLOW-1127: one /positions build is bounded, and a stuck row read is joined, never queued again.

Measured 2026-11-27: Bybit private reads from the VM took > 25 s, and the build awaited one per open row with no
deadline, so /positions?include_paper=true did not answer in 90 s and held the SPA Overview.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from src.web.api.routers import dashboard as dash

ROW = (1, "bybit_1", "BTCUSDT", "long", 0.01, 90000.0, "2026-11-27T00:00:00Z", None, None, "p", 1, "paper", None, None)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    dash._ROW_PNL_INFLIGHT.clear()
    monkeypatch.setattr(dash, "_fetch_open_position_rows", lambda include: [ROW])
    monkeypatch.setattr(dash, "_telemetry_map", lambda: {})
    monkeypatch.setattr(dash, "_account_exchanges", lambda: {})  # single lane unless a test routes otherwise
    yield
    dash._ROW_PNL_INFLIGHT.clear()


def test_a_slow_broker_read_does_not_hold_the_build(monkeypatch):
    monkeypatch.setattr(dash, "POSITIONS_BUILD_BUDGET_S", 0.2)

    async def slow(fn, *args):
        await asyncio.sleep(5)
        return 1.0, "broker"

    monkeypatch.setattr(dash, "run_account_read", slow)

    async def go():
        t0 = time.monotonic()
        out = await dash._build_positions(True)
        return out, time.monotonic() - t0

    out, took = asyncio.run(go())
    assert took < 2.0
    assert out[0]["unrealizedPnl"] is None
    assert out[0]["unrealizedPnlSource"] == "unavailable"
    assert out[0]["unrealizedPnlReadState"] == "timed_out"


def test_a_fast_read_is_served_with_read_state_read(monkeypatch):
    async def fast(fn, *args):
        return 12.5, "broker"

    monkeypatch.setattr(dash, "run_account_read", fast)
    out = asyncio.run(dash._build_positions(True))
    assert out[0]["unrealizedPnl"] == 12.5
    assert out[0]["unrealizedPnlSource"] == "broker"
    assert out[0]["unrealizedPnlReadState"] == "read"


def test_a_second_build_joins_the_stuck_read_instead_of_queueing_another(monkeypatch):
    monkeypatch.setattr(dash, "POSITIONS_BUILD_BUDGET_S", 0.1)
    calls = {"n": 0}
    release = {}

    async def stuck(fn, *args):
        calls["n"] += 1
        await release["ev"].wait()
        return 3.0, "broker"

    monkeypatch.setattr(dash, "run_account_read", stuck)

    async def go():
        release["ev"] = asyncio.Event()
        a = await dash._build_positions(True)
        b = await dash._build_positions(True)
        assert calls["n"] == 1  # the second build joined the in-flight read
        release["ev"].set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        c = await dash._build_positions(True)  # the finished read is gone; a fresh one answers in budget
        return a, b, c

    a, b, c = asyncio.run(go())
    assert a[0]["unrealizedPnlReadState"] == b[0]["unrealizedPnlReadState"] == "timed_out"
    assert c[0]["unrealizedPnlReadState"] == "read" and c[0]["unrealizedPnl"] == 3.0
    assert calls["n"] == 2


def test_bybit_and_alpaca_rows_use_the_parallel_lane_ib_and_unknown_do_not(monkeypatch):
    rows = [(i, acct, "SYM", "long", 1.0, 1.0, "t", None, None, "p", 1, "paper", None, None)
            for i, acct in enumerate(["bybit_1", "alpaca_paper", "ib_paper", "tradeify_1"], start=1)]
    monkeypatch.setattr(dash, "_fetch_open_position_rows", lambda include: rows)
    monkeypatch.setattr(dash, "_account_exchanges", lambda: {
        "bybit_1": "bybit", "alpaca_paper": "alpaca", "ib_paper": "interactive_brokers", "tradeify_1": "tradovate"})
    lanes = {}

    def lane(name):
        async def run(fn, *args):
            lanes[args[0]] = name
            return 1.0, "broker"
        return run

    monkeypatch.setattr(dash, "run_account_read", lane("single"))
    monkeypatch.setattr(dash, "run_account_read_parallel", lane("parallel"))
    out = asyncio.run(dash._build_positions(True))
    assert lanes == {"bybit_1": "parallel", "alpaca_paper": "parallel", "ib_paper": "single", "tradeify_1": "single"}
    assert all(r["unrealizedPnlReadState"] == "read" for r in out)


def test_parallel_rows_overlap_inside_one_budget(monkeypatch):
    rows = [(i, "bybit_1", f"S{i}", "long", 1.0, 1.0, "t", None, None, "p", 1, "paper", None, None) for i in range(1, 6)]
    monkeypatch.setattr(dash, "_fetch_open_position_rows", lambda include: rows)
    monkeypatch.setattr(dash, "_account_exchanges", lambda: {"bybit_1": "bybit"})
    monkeypatch.setattr(dash, "POSITIONS_BUILD_BUDGET_S", 1.0)

    async def half_second(fn, *args):
        await asyncio.sleep(0.5)
        return 2.0, "broker"

    monkeypatch.setattr(dash, "run_account_read_parallel", half_second)
    t0 = time.monotonic()
    out = asyncio.run(dash._build_positions(True))
    assert time.monotonic() - t0 < 1.0  # 5 x 0.5 s side by side, not 2.5 s in line
    assert all(r["unrealizedPnlReadState"] == "read" for r in out)
