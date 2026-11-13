"""TP-PREDICT-GRADER: RULE-RQ1009-900-MFE-HEAD-VS-NAIVE-TP applied to ml2_bracket_train_eval output.

The planted-evaluator cases pin every branch of the registered rule; one case runs the REAL evaluator on a small
synthetic corpus to pin the wiring (evaluate(outcome='mfe_r') -> gate_state / vs_Bk_improvement -> grade)."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import tp_predict_grader as tpg  # noqa: E402
from scripts.research import research_result as rr  # noqa: E402

UP = {"a": (60, 1), "b": (60, 1)}


def _grade(spec):
    return tpg.grade(tpg._rows(spec), evaluator=tpg._planted(spec))


def _states(v):
    return {s["stratum"]: s["state"] for s in v["measurement"]["strata"]}


def test_selftest_passes():
    assert tpg.selftest() == 0


def test_registered_constants_match_the_unit():
    import yaml
    u = yaml.safe_load((REPO / "research" / "queue" / "blocked" / "RQ-20261009-900.yaml").read_text()) \
        if (REPO / "research" / "queue" / "blocked" / "RQ-20261009-900.yaml").exists() else \
        yaml.safe_load((REPO / "research" / "queue" / "RQ-20261009-900.yaml").read_text())
    rule = u["decision_rule"]
    assert rule["id"] == tpg.RULE_ID and str(rule["registered_at"]) == tpg.RULE_REGISTERED_AT
    txt = rule["rule"] + rule["statistic"]
    for frag in ("0.55", "0.65", "0.75", ">= 3 of the 5 quantiles", ">= 88", "ALL FOUR", ">= 20"):
        assert frag in txt, frag
    assert tpg.SPLITS == (0.55, 0.65, 0.75) and tpg.QUANTILES == (0.5, 0.6, 0.7, 0.8, 0.9)
    assert tpg.EVAL_N_FLOOR == 88 and tpg.MIN_SHARP_QUANTILES == 3 and tpg.MIN_CONTROL_TRIALS == 20


def test_pass_is_per_stratum_and_mixed_is_not_averaged():
    v = _grade({"S1": {"n": 74, "sharp": 5, "legs": UP}, "S2": {"n": 200, "sharp": 3, "legs": UP},
                "S3": {"n": 400, "sharp": 0, "legs": UP}})
    assert v["verdict"] == "pass" and v["rule_verdict"] == "PASS"
    assert _states(v) == {"S1": "indeterminate", "S2": "sharper", "S3": "not_sharper"}
    assert v["measurement"]["strata_passing"] == ["S2"] and v["measurement"]["mixed"] is True


def test_every_split_must_clear_three_of_five():
    v = _grade({"S2": {"n": 200, "sharp": {0.55: 5, 0.65: 5, 0.75: 2}, "legs": UP}})
    assert v["rule_verdict"] == "HONEST_NEGATIVE" and v["verdict"] == "fail"


def test_leg_reversal_fails_and_unmeasured_leg_is_indeterminate():
    assert _states(_grade({"S2": {"n": 200, "sharp": 5, "legs": {"a": (60, 1), "b": (60, -1)}}})) == {"S2": "not_sharper"}
    v = _grade({"S2": {"n": 200, "sharp": 5, "legs": {"a": (60, 1), "b": (10, 1)}}})
    assert v["rule_verdict"] == "INDETERMINATE" and _states(v) == {"S2": "indeterminate"}


def test_leg_sign_check_any_baseline_per_quantile():
    pooled = tpg._fake_res(100, 5, 0.1)
    leg = tpg._fake_res(60, 0, 0.1)
    leg["sharpness"][0]["vs_B4_improvement"] = -0.2      # q0.5: B4 flips
    leg["sharpness"][1]["vs_B1_improvement"] = -0.2      # q0.6: B1 flips
    assert tpg.leg_sign_check(pooled, leg)["state"] == "ok"            # 2 quantiles reversed
    leg["sharpness"][2]["vs_B2_improvement"] = -0.2      # q0.7: B2 flips -> 3 quantiles, different baselines
    r = tpg.leg_sign_check(pooled, leg)
    assert r["state"] == "reverses" and set(r["reversed_quantiles"]) == {"0.5", "0.6", "0.7"}
    leg["sharpness"][2]["vs_B2_improvement"] = None      # a null is not a reversal
    assert tpg.leg_sign_check(pooled, leg)["state"] == "ok"


def test_all_underpowered_is_indeterminate_and_records_validate():
    v = _grade({"S1": {"n": 74, "sharp": 5, "legs": UP}})
    assert v["verdict"] == "indeterminate" and v["n"] == 74
    rec = rr.build(research_unit="RQ-20261009-900", decision_rule_id=tpg.RULE_ID,
                   decision_rule_registered_at=tpg.RULE_REGISTERED_AT, verdict=v["verdict"],
                   read_state=v["read_state"], population_description=v["population"], n=v["n"], workflow="w",
                   run_id="1", run_attempt="1", run_url="u", commit_sha="a" * 40, tool="t", power_state="accruing",
                   artifact_store="comms/research/x", artifact_locator="comms/research/x/")
    assert rr.validate(rec) == []


def test_control_trials_below_registered_floor_refused():
    with pytest.raises(ValueError):
        tpg.grade([{"stratum": "S", "leg": "a"}], evaluator=tpg._planted({}), control_trials=19)


def test_real_evaluator_wiring_on_a_synthetic_corpus(tmp_path, monkeypatch):
    """The real ml2_bracket_train_eval.evaluate on 2 strata x 2 legs: the grader reads its fields, every stratum gets
    a state, and the verdict.json written by main() is a contract-valid record."""
    rnd = random.Random(7)
    rows = []
    for st, legs in (("S_a", ("l1", "l2")), ("S_b", ("l3", "l4"))):
        for lg in legs:
            for i in range(120):
                rf = 0.01 + 0.02 * rnd.random()
                rows.append({"stratum": st, "leg": lg, "entry_time": f"2024-01-{1 + i // 5:02d}T{i % 24:02d}:00:00Z",
                             "risk_frac": rf, "is_long": rnd.random() > 0.5, "confidence": rnd.random(),
                             "hour_sin": rnd.uniform(-1, 1), "hour_cos": rnd.uniform(-1, 1), "dow": rnd.randint(0, 6),
                             "adx_at_entry": rnd.uniform(10, 40), "regime_weight": rnd.random(),
                             "mfe_r": rnd.expovariate(0.7), "declared_tp_r": 2.0, "class_default_tp_r": 3.0})
    corpus = tmp_path / "c.jsonl"
    corpus.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "out"
    monkeypatch.setattr(tpg, "MIN_CONTROL_TRIALS", 2)    # wiring test, not a power test: keep CI fast
    assert tpg.main(["--corpus", str(corpus), "--out", str(out), "--control-trials", "2"]) == 0
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "measured" and v["verdict"] in ("pass", "fail", "indeterminate")
    states = {s["stratum"]: s for s in v["measurement"]["strata"]}
    assert set(states) == {"S_a", "S_b"}
    for s in states.values():
        assert set(s["by_split"]) == {"0.55", "0.65", "0.75"} and set(s["leg_sign_check"]) == set(s["legs"])
        assert s["eval_n"] == 84                    # 240 rows, last 35%
        assert s["state"] == "indeterminate"        # 84 < 88: the floor fires whatever the head did
