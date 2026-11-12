"""ENTRY-GRADE-REPRO: a bar hole must not leak into positional rolling features (hole_safe=True)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import ml_decision_entry as E  # noqa: E402


def _bars(n=700, hole=None):
    ts = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    c = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.5, n))
    df = pd.DataFrame({"ts": ts, "open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 10.0})
    if hole:
        df = df[~((df.ts >= hole[0]) & (df.ts < hole[1]))].reset_index(drop=True)
    return df


def test_regrid_turns_hole_into_nan_not_seam():
    df = _bars(hole=("2026-01-10", "2026-01-11"))
    g = E.regrid_hourly(df)
    assert len(g) == 700 and g.close.isna().sum() == 24
    f_seam, f_safe = E.features_symbol(df), E.features_symbol(g)
    # positional build computes a 25h "ret_1" at the seam; the regridded build has NaN there
    seam = df.index[df.ts == pd.Timestamp("2026-01-11", tz="UTC")][0]
    assert not np.isnan(f_seam.ret_1.iloc[seam])
    assert np.isnan(f_safe.ret_1[g.ts == pd.Timestamp("2026-01-11", tz="UTC")].iloc[0])
    # and ret_168 stays NaN for 168 bars after the hole instead of spanning it
    assert np.isnan(f_safe.ret_168[g.ts == pd.Timestamp("2026-01-17 12:00", tz="UTC")].iloc[0])


def test_regrid_identity_without_hole():
    df = _bars()
    pd.testing.assert_frame_equal(E.regrid_hourly(df), df, check_dtype=False)
