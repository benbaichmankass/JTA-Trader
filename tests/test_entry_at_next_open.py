"""HARNESS-ENTRY-NEXT-OPEN: the ``entry_at`` execution convention on the trend and pullback research harnesses.

Contract (both harnesses; research harness only, no live path reads it):
  * ``entry_at="close"`` (the default) is BYTE-IDENTICAL to not passing it.
  * ``entry_at="next_open"`` fills at the NEXT bar's open; the stop / risk anchor stays the SIGNAL close and the ATR the
    signal bar's (live sends SL/TP computed from the signal price), so ``sl`` and ``risk`` equal the same-bar trade's while
    ``entry`` moves, and ``entry_time`` stays the SIGNAL bar.
  * A fill already through the stop is refused (the venue's SL-side guard): no trade.
  * An unknown value raises.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from tests.trend_harness_engine import trend_trades

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from backtest_pullback import run_backtest as pb_run


def _df(bars):
    """bars: list of (open, close). high/low = max/min(open, close) +/- 0.5, so the open is a real price on the bar."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [{"timestamp": start + timedelta(hours=i), "open": o, "high": max(o, c) + 0.5,
             "low": min(o, c) - 0.5, "close": c, "volume": 1.0} for i, (o, c) in enumerate(bars)]
    return pd.DataFrame(rows)


def _flat(x, n):
    return [(x, x)] * n


# --- trend harness -----------------------------------------------------------------------------

def _trend_tape(next_open, next_close=102.5):
    # 20 flat bars build the channel; bar 20 closes 101.5 above it (the signal); bar 21 opens at ``next_open`` and closes
    # at ``next_close`` (kept inside the channel in the refusal case so the gap bar is not itself a second signal).
    return _df(_flat(100.0, 20) + [(100.0, 101.5), (next_open, next_close), (next_close, next_close + 1.0),
                                   (next_close + 1.0, next_close + 1.5)] + _flat(100.0, 20))


def _long(trades):
    return next(t for t in trades if t.direction == "long")


def test_trend_close_is_byte_identical_to_default():
    df = _trend_tape(102.0)
    base = trend_trades(df)
    same = trend_trades(df, entry_at="close")
    assert base, "tape must produce a baseline trade (guards a vacuous [] == [])"
    assert [t.__dict__ for t in base] == [t.__dict__ for t in same]


def test_trend_next_open_fills_at_next_bar_open_with_signal_anchored_risk():
    df = _trend_tape(102.0)
    b = _long(trend_trades(df))
    n = _long(trend_trades(df, entry_at="next_open"))
    assert b.entry == pytest.approx(101.5)               # same-bar convention: the signal close
    assert n.entry == pytest.approx(102.0)               # t+1: the next bar's open
    assert n.sl == pytest.approx(b.sl)                   # stop anchored to the SIGNAL close, as live
    assert n.risk == pytest.approx(b.risk)
    assert pd.Timestamp(n.entry_time) == pd.Timestamp(b.entry_time)   # signal-time stamp
    # the same exit price in different fills must read as a different R: next_open paid 0.5 more on a long
    assert n.entry > b.entry


def test_trend_next_open_fill_through_the_stop_is_refused():
    df = _trend_tape(90.0, next_close=100.0)              # gaps far below any 2-ATR stop of the 101.5 signal
    assert any(t.direction == "long" for t in trend_trades(df))
    assert not any(t.direction == "long" for t in trend_trades(df, entry_at="next_open"))


def test_trend_unknown_entry_at_raises():
    with pytest.raises(ValueError):
        trend_trades(_trend_tape(102.0), entry_at="vwap")


# --- pullback harness --------------------------------------------------------------------------

def _pb(df, **kw):
    return pb_run(df, trend_lookback=10, pullback_lookback=5, pullback_frac=0.5, atr_period=5, atr_stop_mult=2.0,
                  trail_mult=3.0, timeout_bars=50, cooldown_bars=1, timeframe="1h", symbol="BTCUSDT", **kw)


def _pb_tape(next_open, tail=None):
    up = [100.0 + 1.5 * i for i in range(20)]            # to 128.5
    closes = up + [127.0, 125.5, 124.5, 125.2]           # pullback then the trigger bar (125.2)
    bars = [(c, c) for c in closes]
    bars += [(next_open, 126.0)] + (tail if tail is not None else [(126.0, 127.0), (127.0, 128.0)] + _flat(118.0, 10))
    return _df(bars)


def test_pb_close_is_byte_identical_to_default():
    df = _pb_tape(125.8)
    a, b = _pb(df), _pb(df, entry_at="close")
    assert a["total_trades"] >= 1
    assert a["total_trades"] == b["total_trades"] and a["net_total_r"] == b["net_total_r"]


def test_pb_next_open_equal_to_signal_close_is_the_same_trade():
    # the invariance: when the next bar opens AT the signal close, t+1 and same-bar fills coincide exactly
    df = _pb_tape(125.2)
    a, n = _pb(df), _pb(df, entry_at="next_open")
    assert a["total_trades"] == n["total_trades"] >= 1
    assert a["net_total_r"] == pytest.approx(n["net_total_r"])


def test_pb_next_open_paying_more_on_a_long_reads_as_lower_r_with_signal_anchored_risk():
    a = _pb(_pb_tape(125.2), entry_at="next_open")        # fill == signal close
    n = _pb(_pb_tape(125.8), entry_at="next_open")        # the next bar gaps 0.6 up: the long pays 0.6 more
    assert a["total_trades"] == n["total_trades"] == 1
    assert n["net_total_r"] < a["net_total_r"]            # same stop/risk anchor, worse fill => lower R
    assert n["params"]["entry_at"] == "next_open" and "entry_at" not in _pb(_pb_tape(125.8))["params"]


def test_pb_next_open_fill_through_the_stop_is_refused():
    tape = _pb_tape(80.0, tail=[])                        # the tape ends right after the gap bar: no second setup
    assert _pb(tape)["total_trades"] >= 1                 # same-bar convention enters at the trigger close
    assert _pb(tape, entry_at="next_open")["total_trades"] == 0


def test_pb_unknown_entry_at_raises():
    with pytest.raises(ValueError):
        _pb(_pb_tape(125.8), entry_at="vwap")
