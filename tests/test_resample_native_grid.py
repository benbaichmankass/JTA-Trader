"""Every harness ``_resample`` must reproduce the NATIVE exchange grid: open-stamped buckets [T, T+rule) labelled T.

WHY (PI-20261120-7ITMUEB1-0001, ML-PRIMARY-14, 2026-11-20). The harnesses resampled with ``label='right',
closed='right'``, so the 1h bar labelled T held the sub-bars opened T-55m..T (true close T+5m), a one-sub-bar phase
shift of the grid. Measured on the trainer (relay #27551): aggregating ``ETHUSDT_5m.csv`` to 15m, left/left reproduced
199,185 of 199,259 native ``ETHUSDT_15m.csv`` bars exactly (the 74-bar residual is source gaps), right/right 4. On
trend_donchian_eth's evidence argv (2023-02..2026-11) the shifted 5m->1h grid gave n 465, -35.73 R against the native
1h grid's n 451, +4.26 R. These tests build the native grid the way an exchange stamps it (by bar OPEN time) and pin
every harness to it; the old convention is the positive control that must fail.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

HARNESSES = ("chop_scalp", "fade", "funding_carry", "fvg_range", "pairs", "pullback", "squeeze", "trend")


def _five_minute(hours: int = 48, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = hours * 12
    ts = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0, 0.2, n))
    open_ = np.r_[100.0, close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0, 0.3, n)
    low = np.minimum(open_, close) - rng.uniform(0, 0.3, n)
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": high, "low": low, "close": close})


def _native(df5: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """What the exchange serves at `minutes`: each bar stamped by its OPEN time, built from the sub-bars inside it."""
    key = df5["timestamp"].dt.floor(f"{minutes}min")
    g = df5.groupby(key)
    return pd.DataFrame({"timestamp": list(g.groups), "open": g["open"].first().values, "high": g["high"].max().values,
                         "low": g["low"].min().values, "close": g["close"].last().values}).reset_index(drop=True)


def _same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    cols = ["open", "high", "low", "close"]
    a = a.reset_index(drop=True)
    b = b.reset_index(drop=True)
    return (len(a) == len(b) and (pd.to_datetime(a["timestamp"], utc=True) == pd.to_datetime(b["timestamp"], utc=True)).all()
            and np.allclose(a[cols].to_numpy(float), b[cols].to_numpy(float)))


@pytest.mark.parametrize("name", HARNESSES)
@pytest.mark.parametrize("rule,minutes", [("15min", 15), ("1h", 60), ("4h", 240)])
def test_harness_resample_reproduces_the_native_grid(name, rule, minutes):
    h = importlib.import_module(f"scripts.backtest_{name}")
    df5 = _five_minute()
    got = h._resample(df5.copy(), rule)
    assert _same(got[["timestamp", "open", "high", "low", "close"]], _native(df5, minutes)), name


def test_the_old_convention_is_the_positive_control():
    """label/closed='right' on the same frame must NOT reproduce the native grid (proves the test can fail)."""
    df5 = _five_minute()
    old = (df5.set_index("timestamp").resample("1h", label="right", closed="right")
           .agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index())
    assert not _same(old, _native(df5, 60))


@pytest.mark.parametrize("name", HARNESSES)
def test_a_native_file_resampled_to_its_own_grain_is_unchanged(name):
    """The Stage-0 evidence path fetches the leg's native timeframe and passes --resample <tf>: a no-op."""
    h = importlib.import_module(f"scripts.backtest_{name}")
    native = _native(_five_minute(), 60)
    assert _same(h._resample(native.copy(), "1h"), native), name


def test_exit_head_replay_and_load_resolved_frame_use_the_native_grid(tmp_path):
    from scripts.ops import backtest_data_source as ds
    df5 = _five_minute()
    p = tmp_path / "ZZZUSDT_5m.csv"
    df5.to_csv(p, index=False)
    sys.path.insert(0, str(REPO / "scripts" / "ml"))
    from exit_head_replay import _load_harness
    h = _load_harness()
    framed = ds.load_resolved_frame(h, str(p), "1h")
    assert _same(framed[["timestamp", "open", "high", "low", "close"]], _native(df5, 60))
    import exit_head_replay as ehr
    own = ehr._load_candles(str(p), "1h")
    assert _same(own[["timestamp", "open", "high", "low", "close"]], _native(df5, 60))


def test_trend_cli_reads_resampled_bars_as_open_stamped():
    src = (REPO / "scripts" / "backtest_trend.py").read_text()
    assert 'bar_label="open",' in src and 'bar_label=("close" if args.resample else "open")' not in src
