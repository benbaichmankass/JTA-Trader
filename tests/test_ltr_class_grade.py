"""LTR-CLASS-GRADE: the per-class verdict rule (comms/research/ltr_class_grade/PREREGISTRATION.md)."""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ltr_class_grade", REPO / "scripts/research/ltr_class_grade.py")
g = importlib.util.module_from_spec(spec)
sys.modules["ltr_class_grade"] = g
spec.loader.exec_module(g)

OK_REGIME = {"p5_pass": True, "p5_why": ""}


def test_small_n_is_indeterminate_never_pass():
    assert g.verdict(19, 1.0, [0.5, 1.5], [0.5, 1.5], "", OK_REGIME)["verdict"] == "INDETERMINATE"


def test_pass_needs_every_clause():
    assert g.verdict(25, 0.5, [0.1, 0.9], [0.1, 0.9], "", OK_REGIME)["verdict"] == "PASS"
    assert g.verdict(25, 0.5, [0.1, 0.9], [-0.1, 0.9], "", OK_REGIME)["verdict"] == "INDETERMINATE"   # P6 cluster
    assert g.verdict(25, 0.5, [0.1, 0.9], [0.1, 0.9], "OVERCONFIDENT", OK_REGIME)["verdict"] == "INDETERMINATE"
    assert g.verdict(25, 0.5, [0.1, 0.9], [0.1, 0.9], "", {"p5_pass": False, "p5_why": "one week"})["verdict"] == "INDETERMINATE"


def test_negative_interval_fails():
    assert g.verdict(25, -0.5, [-0.9, -0.1], [-0.9, -0.1], "", OK_REGIME)["verdict"] == "FAIL"


def test_one_week_cannot_carry_the_regime_clause():
    rows = [{"reviewed_at": "2026-10-28T00:00:00Z", "delta_r": 1.0}] * 25
    assert g.regime(rows)["p5_pass"] is False


def test_cluster_bootstrap_treats_one_package_as_one_draw():
    pairs = [("a", 1.0)] * 20 + [("b", -1.0)]
    ci = g.cluster_ci(pairs, random.Random(1))
    assert ci[0] < 0 < ci[1]          # two clusters: the 20 repeats of one package do not make a tight interval
