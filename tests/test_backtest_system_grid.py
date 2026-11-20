"""backtest_system on the native OPEN-stamped grid, with a causal clock mapping and HTF join (PI-20261120-7ITMUEB1-0006).

WHY (ML-PRIMARY-14, 2026-11-20). backtest_system resampled with label/closed='right' (one sub-bar off the exchange grid).
A unit survey showed the strategy frame must be OPEN-stamped (trend_donchian skip_hours, ict_scalp session and
hf_displacement_cont killzone filters read the bar hour, fitted on open-stamped bars; live bars are open-stamped). With
open stamps, a signal on the strategy bar [T, T+tf) must be acted on only from the first clock bar opening at/after
T+tf, and HTF context must come from HTF bars closed by T+tf. These tests pin all three, with positive controls.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import scripts.backtest_system as bs  # noqa: E402


def _five(hours: int = 40, seed: int = 9) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = hours * 12
    ts = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    c = 100 + np.cumsum(rng.normal(0, 0.3, n))
    o = np.r_[100.0, c[:-1]]
    return pd.DataFrame({"timestamp": ts, "open": o, "high": np.maximum(o, c) + .1, "low": np.minimum(o, c) - .1,
                         "close": c, "volume": 1.0})


def test_resample_is_the_native_open_stamped_grid():
    df5 = _five()
    out = bs._resample(df5, "1h")
    g = df5.groupby(df5["timestamp"].dt.floor("1h"))
    assert list(out["timestamp"]) == list(g.groups)
    assert np.allclose(out["close"].to_numpy(), g["close"].last().to_numpy())
    assert np.allclose(out["open"].to_numpy(), g["open"].first().to_numpy())


def test_signal_maps_to_the_first_clock_bar_after_the_strategy_bar_closes():
    clock = bs._resample(_five(), "15min")
    cts = clock["timestamp"].values
    strat = bs._resample(_five(), "1h")
    for t in strat["timestamp"].iloc[2:20]:
        i = bs._signal_clock_index(cts, t, "1h")
        assert pd.Timestamp(cts[i]).tz_localize("UTC") >= t + pd.Timedelta("1h")          # causal
        assert pd.Timestamp(cts[i - 1]).tz_localize("UTC") < t + pd.Timedelta("1h")       # and not later than needed


def test_old_mapping_on_open_stamps_is_the_positive_control():
    clock = bs._resample(_five(), "15min")
    cts = clock["timestamp"].values
    t = bs._resample(_five(), "1h")["timestamp"].iloc[5]
    naive = int(np.searchsorted(cts, np.datetime64(t), side="right"))
    assert pd.Timestamp(cts[naive]).tz_localize("UTC") < t + pd.Timedelta("1h")           # acts before the 1h bar closed


def test_htf_asof_never_reads_an_unclosed_htf_bar():
    base = _five()
    df = bs._resample(base, "15min")
    hc0, he0 = bs._htf_asof(df, base, "15min", "1h", 5)
    leaks = 0
    for k in range(20, len(df) - 5, 3):
        cut = df["timestamp"].iloc[k] + pd.Timedelta("15min")      # strategy bar k's close = decision time
        pert = base.copy()
        pert.loc[pert["timestamp"] >= cut, ["open", "high", "low", "close"]] *= 1.5
        hc, he = bs._htf_asof(bs._resample(pert, "15min"), pert, "15min", "1h", 5)
        if not (np.allclose(np.nan_to_num(hc0[k], nan=-1), np.nan_to_num(hc[k], nan=-1))
                and np.allclose(np.nan_to_num(he0[k], nan=-1), np.nan_to_num(he[k], nan=-1))):
            leaks += 1
    assert leaks == 0


def test_open_stamped_htf_is_the_positive_control(monkeypatch):
    monkeypatch.setattr(bs, "_resample_close_stamped", bs._resample)
    base = _five()
    df = bs._resample(base, "15min")
    hc0, _ = bs._htf_asof(df, base, "15min", "1h", 5)
    k = 41                                                          # a 15m bar inside an hour (not its last)
    cut = df["timestamp"].iloc[k] + pd.Timedelta("15min")
    pert = base.copy()
    pert.loc[pert["timestamp"] >= cut, ["close"]] *= 1.5
    hc, _ = bs._htf_asof(bs._resample(pert, "15min"), pert, "15min", "1h", 5)
    assert not np.isclose(hc0[k], hc[k])


def test_the_signal_cache_key_carries_the_grid():
    a = bs._cache_key("trend_donchian", "x", None, None, {})
    assert bs.GRID == "open-stamped-v2" and a.name.startswith("trend_donchian_")
    import hashlib
    import json
    old = hashlib.sha1(json.dumps(["trend_donchian", "x", "None", "None", {}], sort_keys=True,
                                  default=str).encode()).hexdigest()[:12]
    assert old not in a.name, "a stream cached under the right/right grid must not be reused"
