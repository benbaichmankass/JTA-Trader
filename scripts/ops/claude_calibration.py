#!/usr/bin/env python3
# wiring: library — imported by scripts/ops/live_review_grade.py and scripts/ops/desk_grade.py (CLAUDE-GRADE-LOOP); no CLI, no timer.
"""Calibration of Claude's stated confidence against priced outcomes (CLAUDE-GRADE-LOOP).

One question for both graders: **does the confidence Claude states predict what the call earned?**

Two shapes, because the two producers state confidence differently:

* ``probability(points)`` -- a numeric probability that the call succeeds (LTR ``judgement_confidence``,
  desk ``proposal.tp.p_hit``) against a binary success. Reports n, the Brier score, the REFERENCE Brier
  of always forecasting the realised base rate (climatology), the Brier skill score
  ``1 - brier / brier_ref``, a reliability table by bucket, and the over-confidence gap
  ``mean(confidence) - hit_rate``.
* ``ordinal(points)`` -- a categorical confidence (desk ``confidence`` enum
  ``anecdote < suggestive < measured``) against a continuous ``delta_r`` / ``net_r``. Reports the mean
  per category and whether the means rise with the category (``monotone``).

THE RULES (registered here, before any run reads them; tests pin them):

* below ``MIN_N`` points a stratum's verdict is ``INDETERMINATE`` -- the numbers are printed, the verdict
  is not drawn;
* ``OVERCONFIDENT`` iff n >= MIN_N and ``mean(confidence) - hit_rate > OVERCONFIDENCE_GAP``;
  ``UNDERCONFIDENT`` iff the gap is below ``-OVERCONFIDENCE_GAP``; else ``CALIBRATED`` when the Brier
  skill score is > 0, ``NO_SKILL`` when it is <= 0 (the stated confidence is no better than the base rate);
* an ordinal stratum is ``MONOTONE`` / ``NOT_MONOTONE`` only when every category present has
  >= ``MIN_N_PER_CATEGORY`` points; else ``INDETERMINATE``.

``None`` is never a number: a point whose confidence or outcome is None is not a point, and is counted in
``dropped_unpriced`` so the population still adds up.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MIN_N = 10
MIN_N_PER_CATEGORY = 5
OVERCONFIDENCE_GAP = 0.10
BUCKETS: Tuple[Tuple[float, float], ...] = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0001))
ORDINAL_ORDER: Tuple[str, ...] = ("anecdote", "suggestive", "measured")


def probability(points: Iterable[Tuple[Optional[float], Optional[float]]]) -> Dict[str, Any]:
    """``points`` = (stated probability of success, 1.0 success / 0.0 failure)."""
    raw = list(points)
    pts = [(float(c), float(y)) for c, y in raw if c is not None and y is not None]
    out: Dict[str, Any] = {"n": len(pts), "dropped_unpriced": len(raw) - len(pts)}
    if not pts:
        out.update({"brier": None, "brier_ref": None, "skill": None, "mean_confidence": None,
                    "hit_rate": None, "overconfidence_gap": None, "reliability": [],
                    "verdict": f"INDETERMINATE (n=0 < {MIN_N})"})
        return out
    brier = statistics.fmean((c - y) ** 2 for c, y in pts)
    base = statistics.fmean(y for _, y in pts)
    ref = base * (1.0 - base)
    mean_c = statistics.fmean(c for c, _ in pts)
    gap = mean_c - base
    skill = None if ref == 0 else 1.0 - brier / ref
    rel = []
    for lo, hi in BUCKETS:
        b = [(c, y) for c, y in pts if lo <= c < hi]
        if b:
            rel.append({"bucket": f"[{lo:.1f},{min(hi, 1.0):.1f}]", "n": len(b),
                        "mean_confidence": round(statistics.fmean(c for c, _ in b), 3),
                        "realised_hit_rate": round(statistics.fmean(y for _, y in b), 3)})
    out.update({"brier": round(brier, 4), "brier_ref": round(ref, 4),
                "skill": None if skill is None else round(skill, 4), "mean_confidence": round(mean_c, 4),
                "hit_rate": round(base, 4), "overconfidence_gap": round(gap, 4), "reliability": rel})
    if len(pts) < MIN_N:
        out["verdict"] = f"INDETERMINATE (n={len(pts)} < {MIN_N})"
    elif gap > OVERCONFIDENCE_GAP:
        out["verdict"] = "OVERCONFIDENT"
    elif gap < -OVERCONFIDENCE_GAP:
        out["verdict"] = "UNDERCONFIDENT"
    elif skill is not None and skill > 0:
        out["verdict"] = "CALIBRATED"
    else:
        out["verdict"] = "NO_SKILL"
    return out


def ordinal(points: Iterable[Tuple[Optional[str], Optional[float]]],
            order: Sequence[str] = ORDINAL_ORDER) -> Dict[str, Any]:
    """``points`` = (confidence category, realised delta_r or net_r)."""
    raw = list(points)
    pts = [(str(c), float(v)) for c, v in raw if c is not None and v is not None]
    cats: Dict[str, List[float]] = {}
    for c, v in pts:
        cats.setdefault(c, []).append(v)
    rows = []
    for c in list(order) + sorted(set(cats) - set(order)):
        if c in cats:
            xs = cats[c]
            rows.append({"category": c, "n": len(xs), "mean": round(statistics.fmean(xs), 4),
                         "hit_rate": round(sum(1 for x in xs if x > 0) / len(xs), 3)})
    out: Dict[str, Any] = {"n": len(pts), "dropped_unpriced": len(raw) - len(pts), "by_category": rows}
    ranked = [r for r in rows if r["category"] in order]
    if len(ranked) < 2 or any(r["n"] < MIN_N_PER_CATEGORY for r in ranked):
        out["verdict"] = (f"INDETERMINATE (needs >= 2 ranked categories with n >= {MIN_N_PER_CATEGORY} each; "
                          f"have {[(r['category'], r['n']) for r in ranked]})")
    else:
        means = [r["mean"] for r in ranked]
        out["verdict"] = "MONOTONE" if all(a <= b for a, b in zip(means, means[1:])) else "NOT_MONOTONE"
    return out
