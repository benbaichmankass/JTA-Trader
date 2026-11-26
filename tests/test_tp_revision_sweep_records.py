"""tp_revision_sweep.grade fans out emit-valid rows (RQ-20261007-080 run 38747768830 could not land: bare per-leg dicts)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research")]

import tp_revision_sweep as T  # noqa: E402


def _sweep(clears: bool):
    legs = [{"leg": "a", "state": "graded", "control_trades": 120, "arms": {}, "tp_revision_counts": {"1.0": {"applied": 10, "clamped": 1}}},
            {"leg": "b", "state": "too_few", "control_trades": 3, "arms": {}, "tp_revision_counts": {}}]
    return {"legs": legs, "pooled": {"by_arm": {"1.0": {"clears_gate": clears, "d_net_r_vs_control": 0.05}}}}


def test_rows_carry_verdict_population_and_n_on_both_branches():
    for clears, top in ((True, "pass"), (False, "fail")):
        v = T.grade(_sweep(clears))
        assert v["verdict"] == top
        a, b = v["records"]
        assert (a["verdict"], a["read_state"], a["n"]) == (top, "measured", 120) and a["population"].startswith("a: ")
        assert (b["verdict"], b["read_state"], b["n"]) == ("not_applicable", "no_data", None) and "below MIN_TRADES" in b["population"]
        assert a["measurement"]["leg"] == "a"
