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


# LTR-ROWS-BRANCH-STALE-VALIDATOR: --only-new validates only the rows a reviewer adds.
def _two_row_files(tmp_path, new_bad=False):
    old = copy.deepcopy(m.GOOD_REVIEW)
    old["review_id"] = "LR-20261111T1401Z-pkg-old"
    old["order_package_id"] = "pkg-old"
    old["handoff"] = {"prior_decision_id": None, "verdict": "keep", "reason": "x", "read_state": "read"}   # off-enum
    new = copy.deepcopy(m.GOOD_REVIEW)
    new["review_id"] = "LR-20261116T2000Z-pkg-1"
    if new_bad:
        new["handoff"] = {"prior_decision_id": None, "verdict": "keep", "reason": "x", "read_state": "read"}
    rv = tmp_path / "reviews.jsonl"
    rv.write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n")
    oc = tmp_path / "outcomes.jsonl"
    oc.write_text("")
    return rv, oc


def test_only_new_skips_an_old_off_schema_row_but_the_full_check_still_flags_it(tmp_path):
    rv, oc = _two_row_files(tmp_path)
    assert any("handoff.verdict" in x for x in m.findings(rv, oc, m.SCHEMA))          # full check: flagged
    assert m.findings(rv, oc, m.SCHEMA, skip_ids={"LR-20261111T1401Z-pkg-old"}) == []   # only-new: the old row is skipped


def test_only_new_still_flags_a_bad_new_row(tmp_path):
    rv, oc = _two_row_files(tmp_path, new_bad=True)
    f = m.findings(rv, oc, m.SCHEMA, skip_ids={"LR-20261111T1401Z-pkg-old"})
    assert f and all("reviews.jsonl:2:" in x for x in f)


def test_only_new_still_flags_a_new_row_reusing_an_old_review_id(tmp_path):
    rv, oc = _two_row_files(tmp_path)
    rows = [json.loads(x) for x in rv.read_text().splitlines()]
    rows[1]["review_id"] = rows[0]["review_id"]
    rv.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    f = m.findings(rv, oc, m.SCHEMA, skip_ids={rows[0]["review_id"]})
    assert any("duplicate review_id" in x for x in f)


def test_base_review_ids_none_when_the_ref_is_unreadable_and_main_falls_back_to_everything(monkeypatch, capsys):
    assert m.base_review_ids("refs/heads/does-not-exist-xyz") is None
    seen = {}
    monkeypatch.setattr(m, "base_review_ids", lambda ref=m.DEFAULT_BASE_REF: None)
    monkeypatch.setattr(m, "findings", lambda **kw: seen.setdefault("skip", kw.get("skip_ids")) and [] or [])
    assert m.main(["--only-new"]) == 0
    assert seen["skip"] is None                                  # nothing skipped: validate everything
    assert "validating EVERY row" in capsys.readouterr().out
