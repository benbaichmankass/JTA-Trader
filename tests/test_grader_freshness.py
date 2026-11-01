"""GRADE-EVERYTHING-CONTINUOUSLY: the grader registry only names things that exist, and the checker is alert-only."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gf", REPO / "scripts/ci/check_grader_freshness.py")
gf = importlib.util.module_from_spec(spec)
sys.modules["gf"] = gf
spec.loader.exec_module(gf)


def _reg():
    return yaml.safe_load((REPO / "scripts/ci/grader_registry.yaml").read_text())["graders"]


def test_self_test_passes():
    assert gf.self_test() == 0


def test_registry_names_real_graders_and_workflows():
    for g in _reg():
        if g["status"] == "scheduled":
            assert (REPO / g["grader"]).is_file(), g["id"]
            assert (REPO / ".github/workflows" / g["workflow"]).is_file(), g["id"]
            assert g["store"]["max_age_hours"] > 0 and g.get("drives_action"), g["id"]
        else:
            assert g["store"] is None and g.get("gap_owner"), g["id"]


def test_default_mode_never_fails_even_with_a_missing_grader(capsys):
    assert gf.main([]) == 0
    assert gf.main(["--strict"]) in (0, 1, 2)
    out = capsys.readouterr().out
    assert "NO_GRADER" in out and "served-model-decision-value" in out
