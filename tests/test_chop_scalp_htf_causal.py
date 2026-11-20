"""chop_scalp's HTF features are CAUSAL: an LTF bar never reads an HTF bar that closes after it.

WHY (PI-20261120-7ITMUEB1-0006, ML-PRIMARY-14, 2026-11-20). PR #27566 moved every harness ``_resample`` to the native
open-stamped grid (label/closed left). chop_scalp also built its HTF range features with ``_resample`` and attached them
with a BACKWARD merge_asof: under open stamps the HTF bar labelled T (covering [T, T+htf)) was visible to every LTF bar
inside it, a lookahead of up to one HTF bar. The HTF frame now uses ``_resample_close_stamped`` (label at the close).
Test: perturb every price AFTER an LTF bar's close; that bar's attached HTF features must not change. The open-stamped
build is the positive control that must fail the same test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import scripts.backtest_chop_scalp as cs  # noqa: E402

KW = {"htf_rule": "1h", "range_lookback": 3, "adx_period": 3, "touch_tol_pct": 0.5}
COLS = ["htf_hi", "htf_lo", "htf_adx", "htf_touch_hi", "htf_touch_lo"]


def _frame(seed: int = 3, n: int = 12 * 48) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    c = 100 + np.cumsum(rng.normal(0, 0.3, n))
    o = np.r_[100.0, c[:-1]]
    return pd.DataFrame({"timestamp": ts, "open": o, "high": np.maximum(o, c) + 0.2,
                         "low": np.minimum(o, c) - 0.2, "close": c})


def _attached(base: pd.DataFrame, builder) -> pd.DataFrame:
    htf = builder(base, **KW)
    return pd.merge_asof(base.sort_values("timestamp"), htf.sort_values("timestamp"), on="timestamp",
                         direction="backward")


def _leaks(builder) -> int:
    base = _frame()
    ref = _attached(base, builder)
    leaks = 0
    for k in range(200, len(base) - 13, 7):          # LTF bars across many HTF phases
        pert = base.copy()
        fut = pert.index > k                          # every bar opened after bar k (k's own close is its decision time)
        pert.loc[fut, ["open", "high", "low", "close"]] *= 1.5
        got = _attached(pert, builder)
        a, b = ref.loc[k, COLS].to_numpy(float), got.loc[k, COLS].to_numpy(float)
        if not np.allclose(np.nan_to_num(a, nan=-9.9), np.nan_to_num(b, nan=-9.9)):
            leaks += 1
    return leaks


def test_htf_features_never_read_the_future():
    assert _leaks(cs._build_htf_features) == 0


def test_the_open_stamped_build_is_the_positive_control(monkeypatch):
    monkeypatch.setattr(cs, "_resample_close_stamped", cs._resample)
    assert _leaks(cs._build_htf_features) > 0, "the leak test must be able to fail"


def test_close_stamped_groups_like_the_native_grid():
    base = _frame()
    a, b = cs._resample(base, "1h"), cs._resample_close_stamped(base, "1h")
    assert len(a) == len(b)
    assert (b["timestamp"] - a["timestamp"] == pd.Timedelta("1h")).all()
    assert np.allclose(a[["open", "high", "low", "close"]].to_numpy(), b[["open", "high", "low", "close"]].to_numpy())
