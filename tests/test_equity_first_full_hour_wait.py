"""D9 (operator 2026-11-18, popup "Wait for the first full hour of trading (Recommended)").

A 1h US-equity signal in the pre-market or the first full regular hour is held back; the leg re-evaluates every tick.
2026-11-18: SLV re-entered 7 times and QQQ 4 times before the open (PI-20261118-JFWRQYOV-0004).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.runtime import intent_multiplexer as im
from src.runtime.market_hours import equity_first_full_hour_wait as wait


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# November = standard time in this module's table: ET = UTC - 5.
@pytest.mark.parametrize("ts,expected", [
    (_utc(2026, 11, 18, 8, 59), True),    # 03:59 ET, overnight
    (_utc(2026, 11, 18, 9, 0), True),     # 04:00 ET
    (_utc(2026, 11, 18, 13, 3), True),    # 08:03 ET (the SLV re-entry minute)
    (_utc(2026, 11, 18, 14, 29), True),   # 09:29 ET
    (_utc(2026, 11, 18, 14, 30), True),   # 09:30 ET regular open, first hour not elapsed
    (_utc(2026, 11, 18, 15, 29), True),   # 10:29 ET
    (_utc(2026, 11, 18, 15, 30), False),  # 10:30 ET: first full hour done
    (_utc(2026, 11, 18, 15, 30), False),
    (_utc(2026, 11, 18, 18, 0), False),   # midday
    (_utc(2026, 11, 18, 20, 59), False),  # 15:59 ET, last regular minute
    (_utc(2026, 11, 18, 21, 0), True),    # 16:00 ET close: after-hours waits (manager 2026-11-18)
    (_utc(2026, 11, 18, 21, 30), True),   # 16:30 ET after-hours
    (_utc(2026, 11, 18, 2, 0), True),     # 21:00 ET the evening before: overnight
    (_utc(2026, 11, 17, 21, 1), True),    # the QQQ 11-17 21:01Z after-close entry
    (_utc(2026, 11, 21, 15, 0), True),    # Saturday
])
def test_window(ts, expected):
    assert wait(ts) is expected


def test_dst_months_shift_the_window_by_an_hour():
    # July: ET = UTC - 4, so 10:30 ET = 14:30Z
    assert wait(_utc(2026, 7, 15, 14, 29)) is True
    assert wait(_utc(2026, 7, 15, 14, 30)) is False
    assert wait(_utc(2026, 7, 15, 19, 59)) is False   # 15:59 ET
    assert wait(_utc(2026, 7, 15, 20, 0)) is True      # 16:00 ET close


def test_weekend_always_waits():
    assert wait(_utc(2026, 11, 22, 16, 0)) is True  # Sunday midday


def _ts(dt):
    return dt.timestamp()


def test_hourly_equity_signal_is_held_pre_market(monkeypatch):
    sig = {"side": "sell", "symbol": "SLV"}
    now = _ts(_utc(2026, 11, 18, 13, 3))
    assert im._equity_hourly_must_wait("slv_trend_1h", {"timeframe": "1h"}, "SLV", sig, now) is True


def test_hourly_equity_signal_passes_inside_regular_trading_after_the_first_hour():
    sig = {"side": "sell", "symbol": "SLV"}
    now = _ts(_utc(2026, 11, 18, 15, 31))
    assert im._equity_hourly_must_wait("slv_trend_1h", {"timeframe": "1h"}, "SLV", sig, now) is False


def test_hourly_equity_signal_is_held_after_the_close():
    sig = {"side": "sell", "symbol": "QQQ"}
    now = _ts(_utc(2026, 11, 17, 21, 1))
    assert im._equity_hourly_must_wait("qqq_pullback_1h", {"timeframe": "1h"}, "QQQ", sig, now) is True


def test_non_hourly_legs_and_non_signals_are_untouched():
    pre = _ts(_utc(2026, 11, 18, 13, 3))
    assert im._equity_hourly_must_wait("tqqq_trend_long_1d", {"timeframe": "1d"}, "TQQQ", {"side": "buy"}, pre) is False
    assert im._equity_hourly_must_wait("slv_trend_1h", {"timeframe": "1h"}, "SLV", {"side": "none"}, pre) is False


def test_crypto_and_futures_hourly_legs_are_untouched():
    pre = _ts(_utc(2026, 11, 18, 13, 3))
    assert im._equity_hourly_must_wait("trend_donchian_1h", {"timeframe": "1h"}, "BTCUSDT", {"side": "buy"}, pre) is False
    assert im._equity_hourly_must_wait("mgc_trend_1h", {"timeframe": "1h"}, "MGC", {"side": "sell"}, pre) is False


def test_gate_fails_open_on_an_error(monkeypatch):
    import src.runtime.market_hours as mh

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(mh, "equity_first_full_hour_wait", boom)
    assert im._equity_hourly_must_wait("slv_trend_1h", {"timeframe": "1h"}, "SLV", {"side": "sell"},
                                       _ts(_utc(2026, 11, 18, 13, 3))) is False
