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

# collapsed-state: not_applicable — E5 VERDICT vocabulary asserted on a producer_failed fixture (the baseline-unavailable
# case), not a research_queue.power_state branch; this file branches on no power state at all.
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


def test_jsonl_shard_is_read_column_pruned_and_missing_columns_are_nan(tmp_path):
    p = tmp_path / "data.jsonl"
    rng = np.random.default_rng(3)
    rows = []
    for i in range(600):
        x = float(rng.normal())
        rows.append({"ts": f"2025-01-01T{(i // 60) % 24:02d}:{i % 60:02d}:00Z", "x0": x, "huge": "y" * 200,
                     "label": int(x > 0)} | ({"x1": 1.0} if i % 2 else {}))
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    g = mb.load_groups({"kind": "jsonl", "path": str(p), "ts_col": "ts", "target": "label", "features": ["x0", "x1"]})
    df = g["ALL"]
    assert list(df.columns) == ["ts", "label", "x0", "x1"] and len(df) == 600      # 'huge' is never held
    assert df["x1"].isna().sum() == 300                                             # absent -> NaN, not dropped
    g2 = mb.load_groups({"kind": "jsonl", "path": str(p), "ts_col": "ts", "target": "label", "features": ["x0"],
                         "tail_rows": 100})
    assert len(g2["ALL"]) == 100


def test_stale_checkout_guard_ignores_only_the_dispatcher_stamp(tmp_path):
    """The trainer must hold the bytes the runner validated -- but the dispatcher's own post-fire stamp
    (last_dispatched_at) lands on main after the run starts and must NOT read as a stale checkout."""
    q = tmp_path / "research" / "queue"
    q.mkdir(parents=True)
    unit = q / "RQ-20300101-001.yaml"
    unit.write_text("id: RQ-20300101-001\nrule: a\nlast_dispatched_at: null\n")
    h0 = script_run.content_hash(unit)
    unit.write_text("id: RQ-20300101-001\nrule: a\nlast_dispatched_at: '2026-10-11T17:00:00Z'\n")
    assert script_run.content_hash(unit) == h0                     # stamp-only change: same content
    unit.write_text("id: RQ-20300101-001\nrule: b\nlast_dispatched_at: null\n")
    assert script_run.content_hash(unit) != h0                     # a RULE change is stale
    # the manifest verifier: match, mismatch, missing file, malformed token
    py = tmp_path / "scripts" / "research"
    py.mkdir(parents=True)
    (py / "x.py").write_text("print(1)\n")
    good = f"{script_run.content_hash(py / 'x.py')}:scripts/research/x.py"
    assert script_run.verify_manifest([good], repo=tmp_path) == []
    (py / "x.py").write_text("print(2)\n")
    assert script_run.verify_manifest([good], repo=tmp_path) == ["scripts/research/x.py"]
    assert script_run.verify_manifest([f"{'0' * 64}:scripts/research/missing.py"], repo=tmp_path) == ["scripts/research/missing.py"]
    assert script_run.verify_manifest(["nothex:../etc/passwd"], repo=tmp_path) != []


def test_hash_manifest_covers_unit_runner_and_scripts():
    p = script_run.plan(SMOKE, run_id="t")
    rels = [t.split(":", 1)[1] for t in script_run.hash_manifest(p)]
    assert set(rels) == {f"research/queue/{SMOKE}.yaml", "scripts/research/script_run.py",
                         "scripts/research/ml_bakeoff.py", "scripts/ml/_heavy_queue.py"}
    assert script_run.verify_manifest(script_run.hash_manifest(p)) == []


def test_non_boosting_learners_run_through_the_engine_and_beat_the_prior_on_planted_signal():
    pytest.importorskip("sklearn")
    """QUEUE-FILL-1013B: sklearn_extratrees (bagging) and sklearn_mlp (neural tabular) are first-class arms."""
    spec = _spec(candidates=["et", "mlp"],
                 learners={"prior": {"kind": "prior"},
                           "et": {"kind": "sklearn_extratrees", "params": {"n_estimators": 60}},
                           "mlp": {"kind": "sklearn_mlp", "params": {"max_iter": 80}}})
    res = mb.run_spec(spec, unit="(test)")["measurement"]
    assert res["arm_status"]["et"] == "ok" and res["arm_status"]["mlp"] == "ok", res["arm_status"]
    for cand in ("et", "mlp"):
        assert res["deltas"]["A"]["cv"][cand]["prior"]["mean"] > 0.05, cand
    assert res["licences"]["et"]["research_only"] is False


def test_df_columns_block_gives_one_arm_its_own_extra_columns():
    """QUEUE-FILL-1013B: an arm with `df_columns` sees columns the shared feature list does not (a with/without test)."""
    import pandas as pd
    df = pd.DataFrame({"x0": np.arange(10.0), "fc_a": np.arange(10.0) * 2})
    out = mb.FEATURE_BLOCKS["df_columns"](df, {"columns": ["fc_a"]})
    assert list(out) == ["fc_a"] and out["fc_a"][3] == 6.0


def test_unit_declared_verbose_does_not_collide_with_engine_default(monkeypatch):
    """RQ-20261014-4591-04: a unit that declares ``verbose`` made CatBoost land ``unavailable`` (TypeError: multiple
    values for keyword argument) and turned a runnable question INDETERMINATE. Unit params must override defaults."""
    import types

    seen = {}

    class _Fake:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setitem(sys.modules, "catboost", types.SimpleNamespace(CatBoostClassifier=_Fake))
    mb._mk_catboost({"verbose": 0, "depth": 6})
    assert seen["verbose"] == 0 and seen["depth"] == 6 and seen["iterations"] == 300
    seen.clear()
    mb._mk_catboost({})
    assert seen["verbose"] == 0


def test_calibrated_logit_learner_is_registered_and_beats_the_prior_on_a_linear_latent():
    """ML-UNBLOCK-1018: the calibrated linear head is a registered, non-research-only kind. ml_bakeoff's synthetic
    frame has an x0*x1 interaction a linear model cannot learn, so the probability-quality check runs on a linear
    latent built here: log-loss must beat the class prior."""
    pytest.importorskip("sklearn")
    assert mb.probe_learner("sklearn_logit_calibrated", {}) is None
    assert mb.LEARNERS["sklearn_logit_calibrated"][2] is False
    rng = np.random.default_rng(3)
    n = 3000
    X = rng.normal(size=(n, 4))
    logits = np.column_stack([1.5 * X[:, 0], 1.5 * X[:, 1], -0.8 * (X[:, 0] + X[:, 1])]) + rng.gumbel(size=(n, 3))
    y = np.argmax(logits, axis=1)
    tr, te = np.arange(2000), np.arange(2000, n)
    fit = mb.LEARNERS["sklearn_logit_calibrated"][0]
    P = fit(X[tr], y[tr], X[te], 3, {"method": "sigmoid", "cv": 3})
    assert P.shape == (len(te), 3) and np.allclose(P.sum(axis=1), 1.0, atol=1e-6)
    ll = mb.compute_metric("logloss", y[te], P, [0, 1, 2])
    ll_prior = mb.compute_metric("logloss", y[te], mb._fit_prior(X[tr], y[tr], X[te], 3, {}), [0, 1, 2])
    assert ll < ll_prior - 0.1, (ll, ll_prior)


# ── ML-INSTRUMENTS-W43: the non-GBDT arms that errored or could not run ─────────────────────────────────────────────
class _CpuLimited:
    """Stand-in for TabPFN's CPU refusal: raises above 5,000 training rows, otherwise a class-frequency model."""
    LIMIT = 5000

    def __init__(self, **kw):
        self.kw = kw

    def fit(self, X, y):
        if len(X) > self.LIMIT:
            raise RuntimeError("Running on CPU with more than 5000 samples is not allowed by default")
        self.classes_ = np.array(sorted(set(np.asarray(y).tolist())))
        self.p_ = np.array([(np.asarray(y) == c).mean() for c in self.classes_])
        return self

    def predict_proba(self, X):
        assert len(X) <= self.LIMIT, "predict called with more rows than the cap"
        return np.tile(self.p_, (len(X), 1))


def test_tabpfn_cpu_row_limit_is_subsampled_not_an_error(monkeypatch):
    import types
    monkeypatch.setitem(sys.modules, "tabpfn", types.SimpleNamespace(TabPFNClassifier=_CpuLimited))
    rng = np.random.RandomState(0)
    X, y = rng.normal(size=(12000, 3)), rng.randint(0, 3, 12000)
    P = mb.LEARNERS["tabpfn"][0](X[:9000], y[:9000], X[9000:], 3, {})  # 9,000 train + 3,000 test: both sides capped
    assert P.shape == (3000, 3) and np.allclose(P.sum(axis=1), 1.0)
    with pytest.raises(RuntimeError):  # the uncapped base really does refuse this size (the failure being fixed)
        _CpuLimited().fit(X[:9000], y[:9000])


def test_capped_ensemble_averages_members_and_handles_a_class_missing_from_a_member():
    rng = np.random.RandomState(1)
    y = np.concatenate([np.zeros(6000, int), np.ones(6000, int), [2] * 5])  # class 2 is rare: most draws miss it
    X = rng.normal(size=(len(y), 2))
    ens = mb._CappedEnsemble(lambda: _CpuLimited(), 3000, 4, "random", 0, 3000).fit(X, y)
    assert len(ens._fitted) == 4
    P = ens.predict_proba(X[:10])
    assert P.shape == (10, 3) and np.allclose(P.sum(axis=1), 1.0)
    # different members drew different rows (seeded per member), and the draw is reproducible
    assert not all(np.array_equal(ens._rows(len(y), 0), ens._rows(len(y), j)) for j in (1, 2, 3))
    assert np.array_equal(ens._rows(len(y), 2), ens._rows(len(y), 2))
    recent = mb._CappedEnsemble(lambda: _CpuLimited(), 3000, 4, "recent", 0, 3000).fit(X, y)
    assert len(recent._fitted) == 1 and np.array_equal(recent._rows(len(y), 0), np.arange(len(y) - 3000, len(y)))


def test_tabpfn_arm_runs_through_the_engine_when_capped(monkeypatch):
    import types
    monkeypatch.setitem(sys.modules, "tabpfn", types.SimpleNamespace(TabPFNClassifier=_CpuLimited))
    spec = _spec(dataset={"kind": "synthetic", "groups": ["A"], "n": 9000, "signal": 2.0, "ts_col": "ts",
                          "target": "label", "features": ["x0", "x1", "x2", "x3"]},
                 candidates=["pfn"], learners={"prior": {"kind": "prior"}, "pfn": {"kind": "tabpfn", "params": {"n_members": 2}}},
                 rule={"min_folds": 3, "pass_if": [{"group": ["A"], "vs": "baseline", "op": ">=", "value": -1.0}],
                       "fail_if_no_candidate_reaches": [{"group": "any", "vs": "baseline", "op": ">", "value": -1.0}]})
    arm = mb.run_spec(spec, unit="t")["measurement"]["groups"]["A"]["arms"]["pfn"]
    assert arm["status"] == "ok", arm  # 9,000 rows x 4 folds: was status=error before the cap


def test_torch_gru_sees_a_lagged_signal_a_flat_learner_cannot():
    torch = pytest.importorskip("torch")
    assert torch
    rng = np.random.RandomState(0)
    n = 3200
    X = rng.normal(size=(n, 3))
    y = np.zeros(n, dtype=int)
    y[3:] = (X[:-3, 0] > 0).astype(int)  # the label is the SIGN of feature 0 three rows ago: invisible to a row-wise learner
    tr, te = slice(0, 2400), slice(2400, n)
    params = {"window_bars": 8, "hidden": 16, "epochs": 40, "lr": 1e-2, "seed": 0}
    gru = mb.LEARNERS["torch_gru"][0](X[tr], y[tr], X[te], 2, params)
    flat = mb.LEARNERS["numpy_logit"][0](X[tr], y[tr], X[te], 2, {})
    assert gru.shape == (800, 2) and np.allclose(gru.sum(axis=1), 1.0, atol=1e-5)
    def acc(P):
        return float((P.argmax(1) == y[te]).mean())

    assert acc(flat) < 0.58 and acc(gru) > 0.8, (acc(flat), acc(gru))
    again = mb.LEARNERS["torch_gru"][0](X[tr], y[tr], X[te], 2, params)
    assert np.allclose(gru, again, atol=1e-5)  # seeded: the arm is reproducible


def test_torch_gru_test_windows_never_look_across_the_block_boundary():
    pytest.importorskip("torch")
    rng = np.random.RandomState(2)
    X = rng.normal(size=(1200, 2))
    y = rng.randint(0, 2, 1200)
    p = {"window_bars": 6, "hidden": 8, "epochs": 2, "seed": 3}
    a = mb.LEARNERS["torch_gru"][0](X[:800], y[:800], X[800:], 2, p)
    # a row's output depends only on the rows at or before it in the test block
    c = mb.LEARNERS["torch_gru"][0](X[:800], y[:800], X[800:1000], 2, p)
    assert np.allclose(a[:200], c, atol=1e-5)


def test_torch_gru_is_unavailable_not_silent_without_torch(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    assert "torch" in (mb.probe_learner("torch_gru", {}) or "")
    with pytest.raises(mb.Unavailable):
        mb.LEARNERS["torch_gru"][0](np.zeros((50, 2)), np.zeros(50, int), np.zeros((5, 2)), 2, {})


def _var_frames(tmp_path, n=900, seed=3):
    import pandas as pd
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    base = rng.normal(scale=0.01, size=n)
    own = base + rng.normal(scale=0.004, size=n)
    peer = np.roll(base, -1) * 0.8 + rng.normal(scale=0.004, size=n)     # peer LEADS own by one bar
    pd.DataFrame({"ts": ts, "log_return": peer}).to_json(tmp_path / "peer.jsonl", orient="records", lines=True,
                                                         date_format="iso")
    return pd.DataFrame({"ts": ts, "log_return": own}), {"own": "BTC", "peers": {"ETH": str(tmp_path / "peer.jsonl")},
                                                           "lags": 3, "window": 400, "refit_every": 48}


def test_var_price_vector_is_causal_and_emits_the_vector(tmp_path):
    df, spec = _var_frames(tmp_path)
    a = mb.block_var_price_vector(df, spec)
    assert {"var_ret_BTC", "var_ret_ETH", "var_abs_BTC", "var_abs_ETH", "var_ret_own", "var_abs_own"} <= set(a)
    assert np.isfinite(a["var_ret_own"][-1]) and np.isnan(a["var_ret_own"][:100]).all()
    df2 = df.copy()
    df2.loc[700:, "log_return"] = 9.9                                   # corrupt the FUTURE of own
    b = mb.block_var_price_vector(df2, spec)
    for k in a:
        assert np.allclose(a[k][:700], b[k][:700], equal_nan=True), k


def test_var_price_vector_uses_the_peer_lead(tmp_path):
    df, spec = _var_frames(tmp_path)
    with_peer = mb.block_var_price_vector(df, spec)["var_ret_own"]
    solo = mb.block_var_price_vector(df, {k: v for k, v in spec.items() if k != "peers"})["var_ret_own"]
    nxt = np.roll(df["log_return"].to_numpy(), -1)
    m = np.isfinite(with_peer) & np.isfinite(solo)
    m[-1] = False
    assert np.corrcoef(with_peer[m], nxt[m])[0, 1] > np.corrcoef(solo[m], nxt[m])[0, 1]


def test_common_rows_restricts_every_arm_to_rows_all_side_streams_cover():
    import pandas as pd
    df = mb.synthetic_frame(2400, 5, 1.5)
    df["fcA"] = np.where(np.arange(len(df)) % 4 == 0, df["x0"], np.nan)      # stride-4 stream
    df["fcB"] = np.where(np.arange(len(df)) % 8 == 0, df["x1"], np.nan)      # stride-8 stream
    spec = {"task": "classification", "common_rows": True, "cv": {"folds": 3, "embargo_rows": 4, "min_train_frac": 0.4},
            "dataset": {"ts_col": "ts", "target": "label", "features": ["x2"]}}
    ls = {"a": {"kind": "prior", "feature_blocks": [{"kind": "df_columns", "columns": ["fcA"], "require_finite": True}]},
          "b": {"kind": "prior", "feature_blocks": [{"kind": "df_columns", "columns": ["fcB"], "require_finite": True}]}}
    res = mb.run_group(df, spec, ls, "macro_f1", {})
    assert res["n_common_rows"] == 300                                         # every 8th of 2400
    assert res["arms"]["a"]["windows"]["cv"]["n_test_rows"] == res["arms"]["b"]["windows"]["cv"]["n_test_rows"]


def test_group_placeholder_and_peer_skip_serve_every_symbol(tmp_path):
    import pandas as pd
    df, spec = _var_frames(tmp_path)
    df.attrs["group"] = "BTC"
    spec = dict(spec, own="{group}", peers={"BTC": str(tmp_path / "peer.jsonl"), "ETH": str(tmp_path / "peer.jsonl")})
    out = mb.block_var_price_vector(df, spec)
    assert {"var_ret_BTC", "var_ret_ETH"} <= set(out) and "var_ret_BTC" in out   # own not double-counted
    assert len([k for k in out if k.startswith("var_ret_") and k != "var_ret_own"]) == 2
    side = tmp_path / "side_BTC.jsonl"
    pd.DataFrame({"ts": df["ts"], "fc_ret_med": 1.0}).to_json(side, orient="records", lines=True, date_format="iso")
    j = mb.block_join_columns(df, {"path": str(tmp_path / "side_{group}.jsonl"), "columns": ["fc_ret_med"]})
    assert np.allclose(j["fc_ret_med"], 1.0)
