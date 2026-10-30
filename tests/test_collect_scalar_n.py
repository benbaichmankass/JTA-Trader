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
