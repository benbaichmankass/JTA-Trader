"""The same-frame research resamplers reproduce the NATIVE open-stamped grid (PI-20261120-7ITMUEB1-0006, group A).

WHY (ML-PRIMARY-14, 2026-11-20). These four ``_resample`` copies used label/closed='right', grouping the sub-bars opened
in (T-rule, T] into the bar labelled T: one sub-bar off the exchange grid (the defect #27566 fixed in the harnesses). The
audit found no as-of join on their output (each consumes the resampled frame by position or by exact-timestamp join), so
open stamps [T, T+rule) labelled T are both correct and causal here. Consumers that map a coarser bar onto a finer
timeline (backtest_system, hf_solo_sim, hf_vectorized HTF, chop_scalp HTF) need CLOSE stamps instead and are NOT in this
set (tests/test_chop_scalp_htf_causal.py is that pattern's test).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ml")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MODULES = ("scripts.ml.replay_pregate", "scripts.research.timeframe_breakeven",
           "scripts.research.research_momentum", "scripts.research.cointegration_stability")


def _five_minute(hours: int = 30, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = hours * 12
    ts = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    c = 100 + np.cumsum(rng.normal(0, 0.2, n))
    o = np.r_[100.0, c[:-1]]
    return pd.DataFrame({"timestamp": ts, "open": o, "high": np.maximum(o, c) + 0.1,
                         "low": np.minimum(o, c) - 0.1, "close": c, "volume": 1.0})


def _native(df5: pd.DataFrame, minutes: int) -> pd.DataFrame:
    g = df5.groupby(df5["timestamp"].dt.floor(f"{minutes}min"))
    return pd.DataFrame({"timestamp": list(g.groups), "open": g["open"].first().values, "high": g["high"].max().values,
                         "low": g["low"].min().values, "close": g["close"].last().values})


@pytest.mark.parametrize("mod", MODULES)
@pytest.mark.parametrize("rule,minutes", [("15min", 15), ("1h", 60), ("4h", 240)])
def test_research_resample_reproduces_the_native_grid(mod, rule, minutes):
    got = importlib.import_module(mod)._resample(_five_minute(), rule).reset_index(drop=True)
    nat = _native(_five_minute(), minutes)
    cols = [c for c in ("open", "high", "low", "close") if c in got.columns]
    assert len(got) == len(nat), mod
    assert (pd.to_datetime(got["timestamp"], utc=True) == pd.to_datetime(nat["timestamp"], utc=True)).all(), mod
    assert np.allclose(got[cols].to_numpy(float), nat[cols].to_numpy(float)), mod


@pytest.mark.parametrize("mod", MODULES)
def test_a_native_file_at_its_own_grain_is_unchanged(mod):
    nat = _native(_five_minute(), 60).assign(volume=1.0)
    got = importlib.import_module(mod)._resample(nat.copy(), "1h").reset_index(drop=True)
    assert (pd.to_datetime(got["timestamp"], utc=True) == nat["timestamp"]).all(), mod
    assert np.allclose(got["close"].to_numpy(float), nat["close"].to_numpy(float)), mod


def test_the_old_convention_is_the_positive_control():
    df5 = _five_minute()
    old = (df5.set_index("timestamp").resample("1h", label="right", closed="right")
           .agg({"close": "last"}).dropna().reset_index())
    nat = _native(df5, 60)
    same = len(old) == len(nat) and np.allclose(old["close"].to_numpy(float), nat["close"].to_numpy(float))
    assert not same
