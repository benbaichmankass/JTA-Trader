"""EXIT-GIVEBACK-PREDICTOR-GATE: grade_replace's optional candidate-vs-control contrast (default off = unchanged)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops"), str(REPO)]
import exit_lever_ablation as ela  # noqa: E402


def _arm(net, folds, n=100):
    return {"n": n, "net_r": net, "max_drawdown_r": 5.0, "folds": [{"net_r": f} for f in folds], "reach_ge_6r": 0.0}


def _grade(vs):
    arms = {"A": _arm(10.0, [1, 1, 1, 1, 1, 1]), "G": _arm(14.0, [2, 2, 2, 2, 2, 2]),
            "U": _arm(9.0, [1, 1, 1, 1, 1, 1]), "R": _arm(15.0, [2, 2, 2, 2, 2, 2])}
    return ela.grade_replace(arms, baseline="A", candidates=["G"], fold_majority=5, n_floor=39, dd_tol_frac=0.35,
                             control=None, vs_controls=vs)


def test_default_is_unchanged():
    assert _grade(None)["verdict"] == "pass"


def test_gated_arm_must_beat_unconditional_and_random_controls():
    assert _grade({"G": ["U"]})["verdict"] == "pass"
    g = _grade({"G": ["U", "R"]})  # R (matched random) earns more than G: the predictor adds nothing
    assert g["verdict"] == "fail" and g["candidates"]["G"]["vs_controls"]["R"]["beats"] is False


def test_control_arms_are_excluded_from_candidates_in_main(tmp_path):
    src = (REPO / "scripts" / "research" / "exit_lever_ablation.py").read_text()
    assert "ctl_labels" in src and "lab not in ctl_labels" in src
