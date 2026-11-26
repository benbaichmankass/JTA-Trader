"""Row NEWS-ALPHA-EVENT-PVALUE-FLOOR: the event bootstrap's p floor (1/2000 = 0.0005) sits above wave-1 BH's rank-1 threshold
0.10/600; the opt-in analytic day-clustered p has no floor, and the default stays the registered bootstrap."""
import numpy as np
import pandas as pd

from scripts.research import news_alpha_ic as nai


def _events(effect: float, n_days: int = 200, per_day: int = 2, seed: int = 3):
    rng = np.random.default_rng(seed)
    days = np.repeat(pd.date_range("2024-01-01", periods=n_days, freq="D", tz="UTC"), per_day)
    return effect + rng.standard_normal(len(days)), days


def test_bootstrap_floor_is_above_the_bh_rank1_threshold():
    assert 1.0 / nai.BOOT_RESAMPLES > nai.BH_Q * 1 / nai.DEFAULT_BUDGET


def test_analytic_p_reaches_below_the_rank1_threshold_on_a_large_effect():
    abn, days = _events(0.5)
    p, t = nai.day_clustered_p(abn, days)
    assert p < nai.BH_Q / nai.DEFAULT_BUDGET and t > 5


def test_analytic_p_is_not_small_on_a_null():
    abn, days = _events(0.0)
    p, _ = nai.day_clustered_p(abn, days)
    assert p > 0.01


def test_event_p_method_defaults_to_the_registered_bootstrap():
    class S:
        raw = {"news_alpha": {}}
    assert nai.event_p_method(S()) == "bootstrap"
    S.raw = {"news_alpha": {"event_p": "analytic"}}
    assert nai.event_p_method(S()) == "analytic"
