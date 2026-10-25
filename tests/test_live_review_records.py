"""LTR-2-RECORDS: the live-review records validator."""
import copy
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("clrr", REPO / "scripts/ci/check_live_review_records.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)
SCHEMA = json.loads(m.SCHEMA.read_text())


def test_self_test_passes():
    assert m._self_test() == 0


def test_committed_files_are_valid():
    assert m.findings() == []


def test_good_rows_valid():
    assert m.row_problems(m.GOOD_REVIEW, "reviews", SCHEMA) == []
    assert m.row_problems(m.GOOD_OUTCOME, "outcomes", SCHEMA) == []


def test_shadow_arm_required_and_is_half_r():
    r = copy.deepcopy(m.GOOD_REVIEW)
    r["shadow_policy"]["bound_r"] = 0.25
    assert m.row_problems(r, "reviews", SCHEMA)


def test_ml_fields_required():
    for k in ("schema_version", "info_cutoff_at", "prompt_sha", "skill_sha", "features_at_review", "judge_prior", "applied"):
        r = copy.deepcopy(m.GOOD_REVIEW)
        r.pop(k)
        assert m.row_problems(r, "reviews", SCHEMA), k
    for k in ("net_r", "cf_r", "cf_method", "pnl_provenance", "cf_provenance"):
        r = copy.deepcopy(m.GOOD_OUTCOME)
        r.pop(k)
        assert m.row_problems(r, "outcomes", SCHEMA), k


def test_bool_is_not_a_number():
    r = copy.deepcopy(m.GOOD_REVIEW)
    r["state"]["open_r"] = True
    assert m.row_problems(r, "reviews", SCHEMA)
