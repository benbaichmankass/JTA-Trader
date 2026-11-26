"""REGIME rates / risk-off hand rule (rostered_leg_replay --mode ratesrule, RQ-20261126-b71e-01): the real-yield shock is read strictly before the
entry day, only LONG entries are skipped, and an unreadable series grades INDETERMINATE (never a silent pass)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))


def _series():
    d = pd.date_range("2021-01-01", periods=80, freq="D", tz="UTC")
    v = np.r_[np.full(40, 1.0), np.linspace(1.0, 1.6, 20), np.full(20, 1.6)]   # +60 bp over days 40..59
    return pd.Series(v, index=d)


def test_shock_uses_only_observations_before_the_entry_day():
    import rostered_leg_replay as R
    s = _series()
    when = pd.Series(pd.to_datetime(["2021-01-15 10:00", "2021-03-01 00:00", "2021-03-01 23:00", "2020-12-01 00:00"], utc=True))
    got = R.rates_shock(s, when, lookback=20, shock_bp=20.0).tolist()
    # Jan 15: flat history; Mar 1 (= day 59): uses day 58 -> change vs day 38 = (1.0 + 18*0.6/19 - 1.0)*100 ~ 57 bp > 20; same day later: same value
    assert got == [False, True, True, False]


def test_only_longs_are_skipped_and_missing_series_is_indeterminate():
    import rostered_leg_replay as R
    rng = np.random.default_rng(0)
    n = 600
    ts = pd.Series(pd.to_datetime("2022-01-03", utc=True) + pd.to_timedelta(np.sort(rng.uniform(0, 1700, n)), unit="D"))
    tr = pd.DataFrame({"family": rng.choice(["tlt_pullback_1h", "mgc_trend_1h"], n), "direction": rng.choice(["long", "short"], n),
                       "net_r": rng.normal(0, 1, n), "ts": ts})
    d = pd.date_range("2021-06-01", "2026-12-31", freq="D", tz="UTC")
    s = pd.Series(np.cumsum(rng.normal(0, 0.03, len(d))), index=d)
    out = R.grade_ratesrule(tr, s)
    g = out["arms"]["rates_shock_skip"]
    shock = R.rates_shock(s, tr.ts) & (tr.direction == "long").to_numpy()
    assert g["skipped"]["n"] == int(shock.sum()) and g["skipped"]["n"] > 0
    assert abs(g["delta"] - (-tr.net_r[shock].sum() / n)) < 1e-4
    assert R.grade_ratesrule(tr, None)["verdict"] == "indeterminate"
