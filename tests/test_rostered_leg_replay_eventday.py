"""DESK-MACRO-DAILY 3a (rostered_leg_replay --mode eventday, RQ-20261126-d3a5-01): entry-conditioned event-day grading with a week-cluster CI, a
date-shift placebo and an equivalence bound."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))


def _rel():
    t = pd.date_range("2022-01-05 13:30", periods=60, freq="14D", tz="UTC")
    return pd.DataFrame({"cls": (["cpi", "nfp", "fomc_decision"] * 20), "t": t})


def _trades(effect, n=3000, seed=0):
    import rostered_leg_replay as R
    rng = np.random.default_rng(seed)
    ts = pd.Series(pd.to_datetime("2022-01-01", utc=True) + pd.to_timedelta(rng.uniform(0, 830, n), unit="D"))
    flag = R.event_flags(ts, _rel().t)
    net = rng.normal(0, 1.0, n) + np.where(flag, effect, 0.0)
    return pd.DataFrame({"family": rng.choice(["L1", "L2", "L3"], n), "direction": "long", "net_r": net, "ts": ts})


def test_event_flags_window():
    import rostered_leg_replay as R
    rel = pd.Series(pd.to_datetime(["2023-03-10 13:30"], utc=True))
    ts = pd.Series(pd.to_datetime(["2023-03-09 14:00", "2023-03-11 13:00", "2023-03-11 14:00", "2023-03-05 00:00"], utc=True))
    assert R.event_flags(ts, rel).tolist() == [True, True, False, False]


def test_planted_event_day_loss_passes_and_its_absence_fails():
    import rostered_leg_replay as R
    rule = dict(R.RULE_EV, n_boot=200, n_placebo=100)
    bad = R.grade_eventday(_trades(-0.6), _rel(), rule)
    assert bad["verdict"] == "pass" and bad["classes"]["any"]["diff_r"] < -0.3 and bad["classes"]["any"]["placebo_share"] <= 0.05
    flat = R.grade_eventday(_trades(0.0, n=20000, seed=1), _rel(), rule)
    assert flat["verdict"] == "fail" and -0.1 < flat["classes"]["any"]["ci95"][0] and flat["classes"]["any"]["ci95"][1] < 0.1
    assert set(flat["classes"]) == {"fomc_decision", "cpi", "nfp", "any"}


def test_releases_file_loads_graded_classes_only():
    import rostered_leg_replay as R
    rel = R.load_releases()
    assert len(rel) >= 100 and set(rel.cls) <= set(R.EV_CLASSES) and rel.t.is_monotonic_increasing


def test_cli_guards():
    import rostered_leg_replay as R
    with pytest.raises(SystemExit):
        R.main(["--universe", "all", "--mode", "filter", "--out", "/tmp/_ev_refuse"])
    with pytest.raises(SystemExit):
        R.main(["--mode", "eventday", "--population", "fresh", "--out", "/tmp/_ev_refuse"])
