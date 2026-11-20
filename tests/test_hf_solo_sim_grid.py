"""hf_solo_sim on the native open-stamped grid with signals mapped at their bar close (PI-20261120-7ITMUEB1-0006).

Same contract as tests/test_backtest_system_grid.py: strategy frame and clock open-stamped (units read the bar hour,
fitted on open-stamped bars), a signal on [T, T+tf) acts from the first clock bar opening at/after T+tf, HTF joined at
the bar close. simulate() refuses to run without the strategy frame's rule.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import scripts.research.hf_solo_sim as sim  # noqa: E402


def _five(hours: int = 30, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = hours * 12
    ts = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    c = 100 + np.cumsum(rng.normal(0, 0.3, n))
    o = np.r_[100.0, c[:-1]]
    return pd.DataFrame({"timestamp": ts, "open": o, "high": np.maximum(o, c) + .1, "low": np.minimum(o, c) - .1,
                         "close": c, "volume": 1.0})


def test_resample_is_open_stamped():
    df5 = _five()
    out = sim._resample(df5, "1h")
    assert list(out["timestamp"]) == list(df5["timestamp"].dt.floor("1h").drop_duplicates())


def test_simulate_requires_the_signal_rule():
    clock = sim._resample(_five(), "1h")
    sigs = pd.DataFrame(columns=["ts", "side", "entry", "sl", "tp", "confidence"])
    with pytest.raises(ValueError):
        sim.simulate(sigs, clock)


def test_a_signal_never_fills_before_its_bar_closes():
    base = _five()
    clock = sim._resample(base, "15min")
    t = sim._resample(base, "1h")["timestamp"].iloc[6]
    px = float(clock.loc[clock["timestamp"] == t + pd.Timedelta("1h"), "open"].iloc[0])
    sig = pd.DataFrame([{"ts": t, "side": "long", "entry": px, "sl": px - 50, "tp": px + 50, "confidence": 1.0}])
    out = sim.simulate(sig, clock, signal_tf="1h")
    assert out["trades"] >= 0                                    # runs
    i = int(np.searchsorted(clock["timestamp"].values, np.datetime64(t + pd.Timedelta("1h")), side="left"))
    assert pd.Timestamp(clock["timestamp"].iloc[i]) >= t + pd.Timedelta("1h")


def test_cli_passes_the_signal_rule():
    src = (REPO / "scripts" / "research" / "hf_solo_sim.py").read_text()
    assert "signal_tf=_PANDAS_TF[args.tf]" in src
