#!/usr/bin/env python3
"""Standard control set for any intervention / exit / active-management test.

WHY THIS EXISTS
---------------
`docs/reference/trading-and-model-practice-principles.md` T1 (and M6): judge any in-trade intervention
(human, LLM or rule) against **hold-to-exit AND a matched random intervention** (same count and type of
actions at random check-ins); the strongest exit evidence (Akepanidtaworn et al., JF 2023: institutional
sells underperform random sells) uses exactly that counterfactual. Checklist row
`RESEARCH-INTERVENTION-CONTROL-SET`.

The three controls, lifted out of `scripts/research/desk_replay_driver.py` (B1/B2/B3) so every harness gets
them without forking the driver:

  B1 hold-to-bracket        dR = 0 by construction (paired dR is measured against the recorded exit).
  B2 matched-random         the intervention's own per-run action mix (same count and type of actions),
                            applied at random valid check-ins of the SAME trade, N draws.
  B3 best static rule       the single fixed rule from a registered grid with the best mean dR on the
                            OTHER folds (leave-one-fold-out), so no test fold chooses its own control.

Inference is group-by-trade: several decision points can share one price path, so the bootstrap resamples
whole trades, never points.

This module is harness-agnostic. A harness prices its own actions (the cost stack lives there) and hands in
plain arrays; nothing here fetches data or reads config. Tier 1, numpy only.

    from scripts.research.intervention_controls import control_set
"""
from __future__ import annotations

from typing import Any, Dict, Hashable, Mapping, Optional, Sequence, Tuple

import numpy as np

HOLD: Tuple = ("hold",)
DEFAULT_DRAWS = 1_000
DEFAULT_BOOT_DRAWS = 10_000


def hold_to_bracket(n: int) -> np.ndarray:
    """B1. Paired dR of 'do nothing' against the recorded exit is 0 by definition."""
    return np.zeros(int(n))


def boot_ci_by_group(x: Sequence[float], groups: Optional[Sequence[Hashable]], rng: np.random.Generator,
                     draws: int = DEFAULT_BOOT_DRAWS) -> Tuple[float, float, float]:
    """Mean and 95% CI, resampling whole groups (trades). groups=None resamples points (one point per trade).

    The resampled statistic is the mean over all points of the drawn groups, so a trade with more decision
    points weighs more, as it does in the point estimate."""
    a = np.asarray(x, dtype=float)
    if len(a) == 0:
        return (float("nan"),) * 3
    if groups is None:
        idx = rng.integers(0, len(a), size=(draws, len(a)))
        m = a[idx].mean(axis=1)
        return float(a.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))
    labels = list(dict.fromkeys(groups))
    pos = {g: k for k, g in enumerate(labels)}
    gi = np.array([pos[g] for g in groups])
    sums = np.bincount(gi, weights=a, minlength=len(labels))
    cnts = np.bincount(gi, minlength=len(labels)).astype(float)
    pick = rng.integers(0, len(labels), size=(draws, len(labels)))
    m = sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
    return float(a.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def matched_random_intervention(table: Sequence[Mapping[Tuple, np.ndarray]], freq: Mapping[Tuple, float],
                                seed: int, draws: int = DEFAULT_DRAWS) -> np.ndarray:
    """B2. Per-trade mean dR over `draws` draws of the intervention's own action mix at random check-ins.

    table[i][action] = dR of applying `action` at each valid check-in of trade i (already net of cost).
    freq = the intervention's action frequencies per decision point, INCLUDING HOLD (`("hold",)`); the
    count and type of non-hold actions therefore match in expectation. A drawn non-hold action with no
    valid check-in on that trade scores 0 (it could not be applied); it is not redrawn or hidden."""
    rng = np.random.default_rng(seed)
    kinds = [s for s in freq if s != HOLD]
    probs = np.array([freq.get(HOLD, 0.0)] + [freq[s] for s in kinds], dtype=float)
    if probs.sum() <= 0:
        return np.zeros(len(table))
    probs = probs / probs.sum()
    per_point = np.zeros(len(table))
    for i, tb in enumerate(table):
        choice = rng.choice(len(probs), size=draws, p=probs)
        tot = 0.0
        for c in choice:
            if c == 0:
                continue
            arr = tb.get(kinds[c - 1])
            if arr is not None and len(arr):
                tot += arr[rng.integers(0, len(arr))]
        per_point[i] = tot / draws
    return per_point


def best_static_rule(mat: np.ndarray, folds: Sequence[int], grid: Sequence[Any]
                     ) -> Tuple[np.ndarray, Dict[int, Optional[Any]]]:
    """B3. Leave-one-fold-out best static rule.

    mat[i, g] = dR of grid rule g on point i (NaN = rule inapplicable, leaves the trade untouched = 0).
    For each fold the rule is the one with the best mean dR on the OTHER folds; the returned array is each
    point's dR under the rule chosen without its own fold."""
    mat0 = np.where(np.isnan(mat), 0.0, mat)
    f = np.asarray(folds)
    chosen: Dict[int, Optional[Any]] = {}
    out = np.zeros(len(mat0))
    for fold in sorted(set(f.tolist())):
        train = f != fold
        if not train.any():
            chosen[fold] = None
            continue
        best = int(np.argmax(mat0[train].mean(axis=0)))
        chosen[fold] = grid[best]
        out[f == fold] = mat0[f == fold, best]
    return out, chosen


def control_set(claude_dR: Sequence[float], *, table: Sequence[Mapping[Tuple, np.ndarray]],
                freq: Mapping[Tuple, float], mat: np.ndarray, folds: Sequence[int], grid: Sequence[Any],
                groups: Optional[Sequence[Hashable]] = None, seed: int, draws: int = DEFAULT_DRAWS,
                boot_draws: int = DEFAULT_BOOT_DRAWS) -> Dict[str, Any]:
    """All three controls plus the intervention's paired margin over each, with group-by-trade CIs.

    `claude_dR` is the intervention's paired dR per point (vs hold). Returns means, CIs and the paired
    difference (intervention - control) with its CI, per control. Verdict logic stays in the unit's
    pre-registered decision_rule, never here."""
    x = np.asarray(claude_dR, dtype=float)
    b1 = hold_to_bracket(len(x))
    b2 = matched_random_intervention(table, freq, seed + 2, draws)
    b3, chosen = best_static_rule(mat, folds, grid)
    rng = np.random.default_rng(seed)

    def arm(v: np.ndarray) -> Dict[str, Any]:
        m, lo, hi = boot_ci_by_group(v, groups, rng, boot_draws)
        return {"mean_dR": m, "ci_lo": lo, "ci_hi": hi}

    def diff(c: np.ndarray) -> Dict[str, Any]:
        m, lo, hi = boot_ci_by_group(x - c, groups, rng, boot_draws)
        return {"mean": m, "ci_lo": lo, "ci_hi": hi}

    return {
        "n_points": int(len(x)),
        "n_groups": int(len(set(groups))) if groups is not None else int(len(x)),
        "intervention": arm(x),
        "b1_hold_to_bracket": arm(b1),
        "b2_matched_random": dict(arm(b2), draws=draws),
        "b3_best_static": dict(arm(b3), chosen_by_fold={int(k): v for k, v in chosen.items()}),
        "margin_vs_b1": diff(b1), "margin_vs_b2": diff(b2), "margin_vs_b3": diff(b3),
    }
