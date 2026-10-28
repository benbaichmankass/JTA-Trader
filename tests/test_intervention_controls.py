"""Shared intervention control set (RESEARCH-INTERVENTION-CONTROL-SET)."""
from __future__ import annotations

import numpy as np

from scripts.research.intervention_controls import (
    HOLD, best_static_rule, boot_ci_by_group, control_set, hold_to_bracket,
    matched_random_intervention)

CLOSE = ("close",)


def _legacy_b2(table, freq, seed, draws):
    """Verbatim logic of desk_replay_driver.b2_random_timing before the lift (RNG order is the contract)."""
    rng = np.random.default_rng(seed)
    kinds = [s for s in freq if s != HOLD]
    probs = np.array([freq.get(HOLD, 0.0)] + [freq[s] for s in kinds])
    probs = probs / probs.sum()
    out = np.zeros(len(table))
    for i, tb in enumerate(table):
        choice = rng.choice(len(probs), size=draws, p=probs)
        tot = 0.0
        for c in choice:
            if c == 0:
                continue
            arr = tb[kinds[c - 1]]
            if len(arr):
                tot += arr[rng.integers(0, len(arr))]
        out[i] = tot / draws
    return out


def test_hold_is_zero():
    assert not hold_to_bracket(5).any()


def test_matched_random_equals_legacy_draw_for_draw():
    rng = np.random.default_rng(1)
    table = [{CLOSE: rng.normal(size=6), ("partial_close",): np.array([])} for _ in range(8)]
    freq = {HOLD: 0.6, CLOSE: 0.3, ("partial_close",): 0.1}
    assert np.array_equal(matched_random_intervention(table, freq, 7, 200), _legacy_b2(table, freq, 7, 200))


def test_matched_random_action_rate_and_inapplicable_scores_zero():
    table = [{CLOSE: np.full(4, 1.0)}] * 50
    out = matched_random_intervention(table, {HOLD: 0.75, CLOSE: 0.25}, 3, 2000)
    assert abs(out.mean() - 0.25) < 0.03              # expected action rate x dR
    empty = matched_random_intervention([{CLOSE: np.array([])}], {HOLD: 0.0, CLOSE: 1.0}, 3, 50)
    assert empty[0] == 0.0                             # could not be applied -> 0, not hidden


def test_matched_random_beats_nothing_when_actions_are_worthless():
    rng = np.random.default_rng(2)
    table = [{CLOSE: rng.normal(0, 1, 10)} for _ in range(300)]
    assert abs(matched_random_intervention(table, {HOLD: 0.5, CLOSE: 0.5}, 4, 500).mean()) < 0.05


def test_best_static_never_uses_own_fold():
    # rule 0 wins only in fold 1; rule 1 is mildly good elsewhere. Fold 1 must therefore NOT pick rule 0.
    mat = np.array([[5.0, 0.1]] * 4 + [[-1.0, 0.1]] * 8)
    folds = [1] * 4 + [2] * 4 + [3] * 4
    out, chosen = best_static_rule(mat, folds, ["a", "b"])
    assert chosen[1] == "b" and chosen[2] == "a"   # fold 2 may use fold 1's data, fold 1 may not
    assert np.allclose(out[:4], 0.1)


def test_best_static_nan_rule_leaves_trade_untouched():
    mat = np.array([[np.nan, 0.0], [np.nan, 0.0]])
    out, _ = best_static_rule(mat, [1, 2], ["a", "b"])
    assert not out.any()


def test_group_bootstrap_is_wider_than_point_bootstrap_when_points_correlate():
    rng = np.random.default_rng(5)
    trade_effect = rng.normal(0, 1, 30)
    x = np.repeat(trade_effect, 5)                    # 5 identical points per trade
    groups = np.repeat(np.arange(30), 5)
    _, lo_g, hi_g = boot_ci_by_group(x, groups, np.random.default_rng(0), 4000)
    _, lo_p, hi_p = boot_ci_by_group(x, None, np.random.default_rng(0), 4000)
    assert (hi_g - lo_g) > 1.5 * (hi_p - lo_p)


def test_control_set_planted_signal_beats_every_control_and_null_does_not():
    rng = np.random.default_rng(9)
    n = 120
    folds = np.tile([1, 2, 3, 4], n // 4)
    groups = np.arange(n)
    table = [{CLOSE: rng.normal(0, 0.3, 8)} for _ in range(n)]
    mat = rng.normal(0, 0.3, (n, 2))
    freq = {HOLD: 0.5, CLOSE: 0.5}
    real = control_set(rng.normal(0.5, 0.3, n), table=table, freq=freq, mat=mat, folds=folds,
                       grid=["a", "b"], groups=groups, seed=1, draws=200, boot_draws=2000)
    for k in ("margin_vs_b1", "margin_vs_b2", "margin_vs_b3"):
        assert real[k]["ci_lo"] > 0, k
    null = control_set(rng.normal(0.0, 0.3, n), table=table, freq=freq, mat=mat, folds=folds,
                       grid=["a", "b"], groups=groups, seed=1, draws=200, boot_draws=2000)
    assert null["margin_vs_b2"]["ci_lo"] < 0 < null["margin_vs_b2"]["ci_hi"]
    assert real["n_groups"] == n and real["b1_hold_to_bracket"]["mean_dR"] == 0.0
