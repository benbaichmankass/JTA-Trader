"""PULLBACK-ENTRY-MODE-LIMIT: closed-bar ``entry_mode="limit"`` on scripts/backtest_pullback.py (mirrors ict_scalp).

Contract: market (default) is byte-identical to not passing it; a limit at the signal close fills only when a bar's
low is STRICTLY below it within ``limit_expire_bars``; unfilled signals are counted, not dropped; limit trades carry
maker+taker fees; the forming-bar path refuses limit mode.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backtest_pullback as bp  # noqa: E402


def _df(bars):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [{"timestamp": start + timedelta(hours=i), "open": o, "high": max(o, c) + 0.5,
             "low": min(o, c) - 0.5, "close": c, "volume": 1.0} for i, (o, c) in enumerate(bars)]
    return pd.DataFrame(rows)


def _tape(next_bar, tail=None):
    up = [100.0 + 1.5 * i for i in range(20)]
    closes = up + [127.0, 125.5, 124.5, 125.2]            # the trigger bar closes 125.2
    bars = [(c, c) for c in closes] + [next_bar]
    bars += tail if tail is not None else [(126.0, 127.0), (127.0, 128.0)] + [(118.0, 118.0)] * 10
    return _df(bars)


def _pb(df, **kw):
    return bp.run_backtest(df, trend_lookback=10, pullback_lookback=5, pullback_frac=0.5, atr_period=5,
                           atr_stop_mult=2.0, trail_mult=3.0, timeout_bars=50, cooldown_bars=1,
                           timeframe="1h", symbol="BTCUSDT", **kw)


FILL = (125.0, 126.0)       # low 124.5 < 125.2: trades through the limit
MISS = (125.8, 126.0)       # low 125.3 > 125.2: never trades through


def test_market_default_is_byte_identical():
    df = _tape(FILL)
    a, b = _pb(df), _pb(df, entry_mode="market")
    assert a["total_trades"] >= 1                          # not a vacuous equality
    assert a["net_total_r"] == b["net_total_r"] and a["params"] == b["params"]
    assert "entry_mode" not in a["params"]


def test_limit_fills_when_price_trades_through_and_charges_maker_taker():
    df = _tape(FILL)
    m, lim = _pb(df), _pb(df, entry_mode="limit")
    assert lim["total_trades"] == 1
    assert lim["params"]["limit_signals"] == 1 and lim["params"]["limit_missed"] == 0
    t = bp.Trade(entry_index=0, entry_time=None, direction="long", entry=100.0, sl=98.0, risk=2.0, exit_index=1,
                 exit_time=None, exit_price=101.0, outcome="x", r_multiple=0.5, mfe_r=0.5, limit_fill=True)
    t_m = bp.Trade(**{**t.__dict__, "limit_fill": False})
    assert bp._cost_breakdown(t)["fee_r"] == pytest.approx(
        bp._cost_breakdown(t_m)["fee_r"] * (bp.LIMIT_MAKER_FEE_BPS + bp.LIMIT_TAKER_FEE_BPS) / bp.FEE_BPS_ROUNDTRIP)
    assert m["total_trades"] >= 1


def test_limit_missed_signal_is_counted_not_dropped():
    lim = _pb(_tape(MISS), entry_mode="limit", limit_expire_bars=1)
    assert lim["total_trades"] == 0
    assert lim["params"]["limit_signals"] >= 1
    assert lim["params"]["limit_missed"] == lim["params"]["limit_signals"]
    assert lim["params"]["limit_fill_rate"] == 0.0


def test_touch_without_trade_through_does_not_fill():
    # low exactly equals the limit (125.2): strict inequality, so no fill
    bar = (125.7, 125.7)
    df = _tape(bar)
    df.loc[24, "low"] = 125.2
    lim = _pb(df, entry_mode="limit", limit_expire_bars=1)
    assert lim["params"]["limit_missed"] >= 1


def test_unknown_mode_and_bad_expiry_raise_and_forming_refuses():
    df = _tape(FILL)
    with pytest.raises(ValueError):
        _pb(df, entry_mode="stop")
    with pytest.raises(ValueError):
        _pb(df, entry_mode="limit", limit_expire_bars=0)
    with pytest.raises(ValueError, match="closed-bar only"):
        _pb(df, entry_mode="limit", decision_bar="forming", decision_1m=pd.DataFrame(), decision_cfg={})
