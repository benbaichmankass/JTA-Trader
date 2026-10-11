"""ML-RQ-RUNNER: the generic ML bake-off engine, its routing, and the result shape research-ops reads.

Three things are pinned: (1) the numbers (metrics, purged folds, causal blocks, paired deltas) are right;
(2) the REGISTERED rule is applied verbatim and a FAIL never claims more than was tested; (3) the unit
routes to the trainer through the existing dispatcher/collector and its verdict.json is accepted by
script_run.derive_record as `measured` (not the producer_failed / malformed fallbacks)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.research import collect_runner_results as collector  # noqa: E402
from scripts.research import dispatch_queue, ml_bakeoff as mb, research_queue, script_run  # noqa: E402

SMOKE = "RQ-20261011-0ac8-01"


def _spec(**over):
    spec = {"task": "classification", "metric": "macro_f1",
            "dataset": {"kind": "synthetic", "groups": ["A", "B"], "n": 2400, "signal": 2.0, "ts_col": "ts",
                        "target": "label", "features": ["x0", "x1", "x2", "x3"]},
            "cv": {"folds": 4, "embargo_rows": 10, "min_train_frac": 0.4},
            "baseline": "prior", "controls": [], "candidates": ["logit"],
            "learners": {"prior": {"kind": "prior"}, "logit": {"kind": "numpy_logit"}},
            "rule": {"min_folds": 3,
                     "pass_if": [{"group": ["A", "B"], "vs": "baseline", "op": ">=", "value": 0.05}],
                     "fail_if_no_candidate_reaches": [{"group": "any", "vs": "baseline", "op": ">", "value": 0.05}]}}
    spec.update(over)
    return spec


# ── numbers ──────────────────────────────────────────────────────────────────
def test_metrics_known_values():
    y = np.array([0, 0, 1, 1, 2, 2])
    perfect = np.eye(3)[y]
    assert mb.compute_metric("macro_f1", y, perfect, [0, 1, 2]) == pytest.approx(1.0)
    assert mb.compute_metric("accuracy", y, perfect, [0, 1, 2]) == pytest.approx(1.0)
    assert mb.compute_metric("auc_ovr", y, perfect, [0, 1, 2]) == pytest.approx(1.0)
    # all-wrong-by-one: accuracy 0, logloss large
    wrong = np.eye(3)[(y + 1) % 3]
    assert mb.compute_metric("accuracy", y, wrong, [0, 1, 2]) == 0.0
    uniform = np.full((6, 3), 1 / 3)
    assert mb.compute_metric("logloss", y, uniform, [0, 1, 2]) == pytest.approx(np.log(3))
    assert mb.compute_metric("brier", y, uniform, [0, 1, 2]) == pytest.approx(2 / 3)
    # binary f1 of the positive class: tp=1 fp=1 fn=1 -> 0.5
    yb, pb = np.array([1, 1, 0, 0]), np.array([[0.2, 0.8], [0.9, 0.1], [0.3, 0.7], [0.8, 0.2]])
    assert mb.compute_metric("f1_class:1", yb, pb, [0, 1]) == pytest.approx(0.5)
    assert mb.compute_metric("mae", np.array([1.0, 2.0]), np.array([2.0, 2.0]), []) == pytest.approx(0.5)


def test_auc_handles_ties_like_mann_whitney():
    y = np.array([0, 0, 1, 1])
    assert mb._auc_binary(y, np.array([0.5, 0.5, 0.5, 0.5])) == pytest.approx(0.5)


def test_purged_folds_never_leak_the_embargo():
    folds = mb.purged_folds(1000, 5, embargo=24, min_train_frac=0.4)
    assert len(folds) == 5
    for tr, te in folds:
        assert tr.max() < te.min() - 24 + 1          # train ends >= `embargo` rows before test starts
        assert len(np.intersect1d(tr, te)) == 0
    # a dataset too short for the embargo yields NO folds (no_data), never a leaky fold
    assert mb.purged_folds(80, 5, embargo=60, min_train_frac=0.4) == []


def test_har_rv_block_is_causal():
    import pandas as pd
    rng = np.random.default_rng(0)
    r = rng.normal(scale=0.01, size=300)
    a = mb.block_har_rv(pd.DataFrame({"log_return": r}), {"d": 1, "w": 5, "m": 22})
    r2 = r.copy()
    r2[200:] = 9.9                                   # corrupt the FUTURE
    b = mb.block_har_rv(pd.DataFrame({"log_return": r2}), {"d": 1, "w": 5, "m": 22})
    for k in a:
        assert np.allclose(a[k][:200], b[k][:200], equal_nan=True), k


def test_paired_delta_sign_and_interval():
    d = mb.paired_delta([0.6, 0.62, 0.61, 0.63], [0.5, 0.5, 0.5, 0.5])
    assert d["n_folds"] == 4 and d["mean"] == pytest.approx(0.115) and d["ci95"][0] > 0 and d["sign_consistent"]
    assert mb.paired_delta([], [])["mean"] is None
    assert mb.paired_delta([0.5], [0.4])["ci95"] is None     # one fold: no invented interval


def test_lower_is_better_metrics_flip_the_delta_sign():
    assert mb.metric_higher_is_better("logloss", None) is False
    assert mb.metric_higher_is_better("macro_f1", None) is True
    groups = {"A": {"arms": {"x": {"windows": {"cv": {"fold_metric": [0.4, 0.4, 0.4]}}},
                              "b": {"windows": {"cv": {"fold_metric": [0.6, 0.6, 0.6]}}}}}}
    d = mb.build_deltas(groups, ["x"], ["b"], ["cv"], better_high=False)
    assert d["A"]["cv"]["x"]["b"]["mean"] == pytest.approx(0.2)   # lower loss = better = positive


# ── the registered rule ──────────────────────────────────────────────────────
def test_rule_pass_and_result_shape():
    v = mb.run_spec(_spec(), unit="t")
    assert v["verdict"] == "pass" and v["read_state"] == "measured" and isinstance(v["n"], int) and v["n"] > 0
    m = v["measurement"]
    assert set(m) >= {"deltas", "rule_evaluation", "arm_status", "licences", "metric", "baseline", "candidates"}
    d = m["deltas"]["A"]["cv"]["logit"]["prior"]
    assert d["n_folds"] >= 3 and d["ci95"] and d["mean"] > 0.05


def test_fail_requires_every_candidate_to_have_been_evaluated():
    impossible = {"pass_if": [{"group": ["A", "B"], "vs": "baseline", "op": ">=", "value": 5.0}],
                  "fail_if_no_candidate_reaches": [{"group": "any", "vs": "baseline", "op": ">", "value": 5.0}]}
    v = mb.run_spec(_spec(rule=impossible), unit="t")
    assert v["verdict"] == "fail"
    # add a candidate whose library is absent: the same rule can no longer say FAIL — a FAIL closes only what was tested
    spec = _spec(rule=impossible, candidates=["logit", "ghost"])
    spec["learners"]["ghost"] = {"kind": "tabpfn"}
    if mb.probe_learner("tabpfn", {}) is not None:
        v2 = mb.run_spec(spec, unit="t")
        assert v2["verdict"] == "indeterminate"
        assert "ghost" in v2["note"] and v2["measurement"]["arm_status"]["ghost"] == "unavailable"
        assert v2["measurement"]["licences"]["ghost"]["research_only"] is True


def test_too_few_folds_is_indeterminate_not_pass():
    v = mb.run_spec(_spec(cv={"folds": 2, "embargo_rows": 10, "min_train_frac": 0.4}), unit="t")
    assert v["verdict"] == "indeterminate" and "min_folds" in v["note"]


def test_unavailable_baseline_is_producer_failed_never_a_verdict():
    spec = _spec()
    spec["learners"]["prior"] = {"kind": "no_such_kind"}
    v = mb.run_spec(spec, unit="t")
    assert v["read_state"] == "producer_failed" and v["verdict"] == "not_applicable" and v["n"] is None


def test_headline_checks_are_reported():
    spec = _spec()
    spec["rule"]["headline_checks"] = [{"name": "logit_beats_baseline", "learner": "logit", "vs": "baseline",
                                        "op": ">=", "value": 0.0, "group": "A"}]
    v = mb.run_spec(spec, unit="t")
    assert v["measurement"]["headline_checks"][0]["holds"] is True


def test_unknown_learner_name_in_lists_is_refused_loudly():
    with pytest.raises(ValueError):
        mb.run_spec(_spec(candidates=["nope"]), unit="t")


# ── the plumbing: derive_record accepts the verdict, the smoke unit routes to the trainer ──
def _run_unit_in(tmp_path, unit_src):
    q = tmp_path / "queue"
    q.mkdir()
    raw = yaml.safe_load(unit_src.read_text(encoding="utf-8"))
    (q / f"{raw['id']}.yaml").write_text(yaml.safe_dump(raw))
    return raw, q


def test_smoke_unit_plans_runs_and_derives_a_measured_record(tmp_path):
    unit_path = REPO / "research" / "queue" / f"{SMOKE}.yaml"
    raw, q = _run_unit_in(tmp_path, unit_path)
    p = script_run.plan(SMOKE, run_id="t1", queue_dir=q)
    assert p.ok, p.errors
    assert raw["run"]["workflow"] == script_run.TRAINER_WORKFLOW
    out = tmp_path / "out"
    proc = subprocess.run([sys.executable, str(REPO / "scripts/research/ml_bakeoff.py"), "--unit", SMOKE,
                           "--out", str(out), "--queue-dir", str(q)], capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    v = json.loads((out / "verdict.json").read_text())
    assert v["verdict"] == "pass" and v["read_state"] == "measured"
    # feed it through the real deriver exactly as the workflow does
    (REPO / p.out_dir).mkdir(parents=True, exist_ok=True)
    try:
        (REPO / p.out_dir / "verdict.json").write_text(json.dumps(v))
        (REPO / p.out_dir / "run-manifest.json").write_text(json.dumps(
            {"commands": [{"index": 0, "argv": p.commands[0], "exit_code": 0}], "all_ok": True}))
        rec = script_run.derive_record(p)
    finally:
        import shutil
        shutil.rmtree(REPO / "comms" / "research" / SMOKE / "t1", ignore_errors=True)
        try:
            (REPO / "comms" / "research" / SMOKE).rmdir()
        except OSError:
            pass
    assert rec["read_state"] == "measured" and rec["verdict"] == "pass"
    assert rec["n"].isdigit() and rec["decision_rule_id"] == "RULE-RQ1011-0AC8-01-ML-RUNNER-SMOKE"
    assert rec["measurement_file"].endswith("measurement.json")


def test_smoke_unit_routes_to_the_trainer_and_is_dispatchable():
    raw = yaml.safe_load((REPO / "research" / "queue" / f"{SMOKE}.yaml").read_text(encoding="utf-8"))
    assert research_queue.grade_route(raw).state == research_queue.TRAINER
    inputs, dropped = dispatch_queue.dispatch_inputs(raw, power_state="not_applicable")
    assert inputs["research_unit"] == SMOKE and not dropped
    assert dispatch_queue.declared_inputs("research-script-run-trainer.yml") == ["research_unit", "power_state"] or \
        set(dispatch_queue.declared_inputs("research-script-run-trainer.yml")) == {"research_unit", "power_state"}
    # one trainer run at a time: the constant concurrency group makes the dispatcher serialize it
    assert dispatch_queue.serialized_workflow("research-script-run-trainer.yml") is True
    assert dispatch_queue.serialized_workflow("research-script-run.yml") is False


def test_collector_lands_trainer_artifacts_through_the_same_path():
    assert collector.TRAINER_WORKFLOW in collector.COLLECTED_WORKFLOWS
    m = collector._ARTIFACT_RE.match(f"research-script-run-trainer-{SMOKE}-99")
    assert m and m.group(1) == SMOKE and m.group(2) == "99"


def test_trainer_workflow_never_takes_a_command_input_and_holds_only_the_ssh_key():
    from scripts.ci import check_research_script_run as guard
    assert guard.check() == []
    wf = yaml.safe_load((REPO / ".github/workflows/research-script-run-trainer.yml").read_text())
    trig = wf.get("on", wf.get(True))
    assert set(trig) == {"workflow_dispatch"} and set(trig["workflow_dispatch"]["inputs"]) == {"research_unit", "power_state"}


def test_self_test_passes():
    proc = subprocess.run([sys.executable, str(REPO / "scripts/research/ml_bakeoff.py"), "--self-test"],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
