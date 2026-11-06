"""The collector hands research_result.py one integer `n` (run 40153686572 lost three same-symbol runs to a dict)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import collect_runner_results as c  # noqa: E402


def test_dict_n_collapses_to_together():
    rec = {"verdict": "pass", "n": {"solo:a": 125, "solo:b": 359, "together": 371}}
    assert c._scalar_n(rec)["n"] == 371
    assert rec["n"]["together"] == 371   # input untouched


def test_dict_n_without_together_is_null_not_a_guess():
    assert c._scalar_n({"n": {"solo:a": 1}})["n"] is None
    assert c._scalar_n({"n": {"together": True}})["n"] is None


def test_scalar_and_missing_n_pass_through():
    assert c._scalar_n({"n": 7}) == {"n": 7}
    assert c._scalar_n({"n": None}) == {"n": None}
    assert c._scalar_n({}) == {}


def test_stringified_per_arm_dict_is_collapsed_to_together():
    # record-inputs.json stores the per-arm dict as its str(); the orphan re-emit must still collect it
    s = "{'solo:a': 74, 'solo:b': 115, 'together': 165}"
    assert c._scalar_n({"n": s})["n"] == 165
    assert c._scalar_n({"n": "{'solo:a': 1}"})["n"] is None
    assert c._scalar_n({"n": "{not python"})["n"] == "{not python"


def test_measured_with_not_applicable_lands_as_producer_failed_not_refused():
    import research_result as RR
    rec = {"read_state": "measured", "verdict": "not_applicable", "n": "3896", "research_unit": "RQ-20261105-001", "note": "dev"}
    out = c._unpair_measured_not_applicable(rec)
    assert out["read_state"] == "producer_failed" and out["n"] == "null" and "dev" in out["note"]
    assert c._unpair_measured_not_applicable({"read_state": "measured", "verdict": "pass", "n": "5"})["read_state"] == "measured"
    r = RR.build(research_unit="RQ-20261105-001", decision_rule_id="R", decision_rule_registered_at="2026-11-05", verdict=out["verdict"],
                 read_state=out["read_state"], population_description=out["population"], n=None, workflow="w", run_id="1", commit_sha="abc",
                 tool="t", artifact_store="s", artifact_locator="l")
    assert RR.validate(r) == []
