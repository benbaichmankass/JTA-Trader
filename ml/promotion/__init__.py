"""Promotion checklist (WS4).

Documented hard gates per registry transition. The CLI's `promote`
subcommand surfaces these and refuses to act unless the operator
explicitly acknowledges them via `--gates-acknowledged`. The reason
string on the resulting `StatusEvent` is the durable record of which
gates were satisfied.

The gates here are documentation; gate evidence (e.g. "leakage_test
results at experiments/<id>/leakage.json") lives in the experiment
artifacts and is referenced from the StatusEvent.reason.

Two gates are no longer documentation only (ML-TRAINING-PRINCIPLES-GAPS,
operator Tier-2 popups 2026-10-28, verbatim):

- "Yes, ship it today (Recommended)" — ``cost_net_evaluation_beats_incumbent_and_baselines``
  is COMPUTED by ``ml.promotion.cost_gate`` on every training run and
  ENFORCED by the registry (``promote_stage`` and the CLI ``promote`` into
  advisory / live-approved / champion refuse a failed or missing evaluation).
- "Same as trades: 1-2 clean" — the legacy calendar soak string
  ``shadow_mode_clean_soak_at_least_7d`` is replaced by the MECHANICAL
  ``shadow_mechanics_clean_1_to_2_scored_predictions``, computed by
  ``ml.promotion.gates.count_clean_shadow_predictions`` (no calendar term;
  docs/plans/OPERATING-PLAN-2026-09-21.md § 2 "The soak is MECHANICAL").
  Promotion is decided on the offline cost-net evidence.
"""
from __future__ import annotations

from typing import Mapping

PROMOTION_GATES: Mapping[tuple[str, str], tuple[str, ...]] = {
    ("candidate", "paper"): (
        "leakage_test_passed",
        "walk_forward_evaluation_complete",
    ),
    ("candidate", "champion"): (
        "cost_net_evaluation_beats_incumbent_and_baselines",
        "comparison_against_incumbent_complete",
        "operator_explicit_approval",
    ),
    ("paper", "advisory"): (
        "cost_net_evaluation_beats_incumbent_and_baselines",
        "metrics_beat_heuristic_baseline",
    ),
    ("advisory", "live-approved"): (
        "shadow_mechanics_clean_1_to_2_scored_predictions",
        "cost_net_evaluation_beats_incumbent_and_baselines",
        "operator_explicit_approval",
        "rollback_plan_documented",
    ),
    ("live-approved", "champion"): (
        "cost_net_evaluation_beats_incumbent_and_baselines",
        "comparison_against_incumbent_complete",
        "operator_explicit_approval",
    ),
}


def gates_for(from_status: str, to_status: str) -> tuple[str, ...]:
    """Return the documented gates for a given transition (empty if none)."""
    return PROMOTION_GATES.get((from_status, to_status), ())
