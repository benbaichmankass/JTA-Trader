"""Regime ENTRY FILTER (rostered_leg_replay --mode filter, RQ-20261125-f1a0-35): a skipped trade contributes 0 R, nothing is renormalised, and
the matched-random control skips the same count within the same leg x month."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))


def _trades(n=600, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2023-01-02", periods=n, freq="13h", tz="UTC")
    return pd.DataFrame({"family": "L", "direction": "long", "net_r": rng.normal(0, 1, n), "ts": ts, "xts": ts + pd.Timedelta(hours=5)})


def test_filter_delta_is_minus_skipped_r_over_all_trades():
    import rostered_leg_replay as R
    t = _trades()
    keep = np.r_[np.zeros(150), np.ones(450)]
    g = R.grade_raw(t, keep, R.RULE_FILTER, normalise=False)
    assert abs(g["delta"] - (-t.net_r.iloc[:150].sum() / 600)) < 1e-4
    assert abs(g["money_arm"] - t.net_r.iloc[150:].sum() / 600) < 1e-4
    assert g["random"]["draws"] == R.RR.N_RANDOM


def test_skipping_only_losers_beats_random_skips_of_the_same_count():
    import rostered_leg_replay as R
    t = _trades(seed=1)
    keep = (t.net_r > -0.5).astype(float).to_numpy()
    g = R.grade_raw(t, keep, R.RULE_FILTER, normalise=False)
    assert g["delta"] > 0.05 and g["random"]["share_ge_arm"] == 0.0


def test_filter_rule_and_mode_are_registered():
    import rostered_leg_replay as R
    assert R.RULE_FILTER["id"] == "RULE-REGIME-ENTRY-FILTER-20261125" and R.RULE_FILTER["min_delta_r"] == R.RULE_MS["min_delta_r"]
    src = (REPO / "scripts/research/rostered_leg_replay.py").read_text()
    assert '"filter"]' in src and 'kind="filter"' in src
