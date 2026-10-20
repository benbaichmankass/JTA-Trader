"""FRONTIER-LEVER-CONFORMAL: the conformal-abstention scorer (score-stream twin of ml_bakeoff).

Pinned: (1) the finite-sample conformal quantile; (2) on EXCHANGEABLE data the set keeps nominal coverage
inside rolling windows and both abstention rules keep the matched share (the self-test); (3) the registered
rule's branches, including that an unmatched coverage level can neither pass nor fail; (4) the moved unit
RQ-20261016-65ff-25 plans through script_run and its verdict.json shape is accepted as `measured`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.research import conformal_abstain_eval as ce  # noqa: E402
from scripts.research import script_run  # noqa: E402

UNIT = "RQ-20261016-65ff-25"


def test_finite_sample_quantile():
    assert ce.conformal_quantile(np.array([0.1, 0.2]), 0.05) == float("inf")
    assert ce.conformal_quantile(np.arange(1, 101) / 100.0, 0.10) == pytest.approx(0.91)
    assert ce.conformal_quantile(np.array([]), 0.1) == float("inf")


def test_plain_threshold_keeps_the_requested_share():
    rng = np.random.default_rng(0)
    P = rng.dirichlet(np.ones(3), size=5000)
    t = ce.tune_threshold(P, 0.7)
    assert abs((P.max(axis=1) >= t).mean() - 0.7) < 0.01


def test_self_test_exchangeable_data_is_valid_and_matched():
    assert ce._self_test() == 0


def _group(enough=True, matched=True, gain=True, valid=True):
    return {"arm_status": "ok", "enough_windows": enough, "coverage_matched_all_levels": matched,
            "gain_all_levels": gain, "valid_all_levels": valid,
            "group_pass": enough and matched and gain and valid,
            "group_fail": enough and matched and not (gain and valid)}


def test_rule_branches():
    cfg = {"rule": {"pass_symbols_min": 2, "fail_symbols_min": 2}}
    assert ce.evaluate_rule({"A": _group(), "B": _group(), "C": _group(gain=False)}, cfg)["verdict"] == "pass"
    assert ce.evaluate_rule({"A": _group(gain=False), "B": _group(valid=False), "C": _group()}, cfg)["verdict"] == "fail"
    # an unmatched level is not a comparison: it blocks FAIL as well as PASS
    v = ce.evaluate_rule({"A": _group(gain=False, matched=False), "B": _group(valid=False, matched=False), "C": _group()}, cfg)
    assert v["verdict"] == "indeterminate"
    assert ce.evaluate_rule({"A": _group(enough=False), "B": _group(), "C": _group()}, cfg)["verdict"] == "indeterminate"
    assert ce.evaluate_rule({"A": {"arm_status": "unavailable"}, "B": _group(), "C": _group()}, cfg)["verdict"] == "indeterminate"


def test_unit_plans_and_a_verdict_lands_measured(tmp_path):
    unit_path = REPO / "research" / "queue" / f"{UNIT}.yaml"
    raw = yaml.safe_load(unit_path.read_text())
    assert raw["run"]["command"][1] == "scripts/research/conformal_abstain_eval.py"
    assert raw["conformal"]["learner"] in raw["ml_bakeoff"]["learners"]
    p = script_run.plan(UNIT, run_id="t1", queue_dir=REPO / "research" / "queue")
    assert p.ok, p.errors
    # a measured verdict from the engine on injected exchangeable data, pushed through the real deriver
    bakeoff = {"dataset": {"kind": "synthetic", "ts_col": "ts", "target": "label", "features": ["x0", "x1", "x2", "x3"]},
               "cv": {"folds": 4, "embargo_rows": 10, "min_train_frac": 0.4},
               "learners": {"logit": {"kind": "numpy_logit"}}}
    gdata = {g: ce._linear_synthetic(6000, 3 + i) for i, g in enumerate(("A", "B"))}
    v = ce.run_unit_spec(bakeoff, {"learner": "logit", "window_days": 7, "min_window_rows": 200, "min_windows": 2},
                         unit=UNIT, gdata=gdata)
    assert v["read_state"] == "measured" and v["verdict"] in ("pass", "fail", "indeterminate")
    (REPO / p.out_dir).mkdir(parents=True, exist_ok=True)
    try:
        (REPO / p.out_dir / "verdict.json").write_text(json.dumps(v, default=str))
        (REPO / p.out_dir / "run-manifest.json").write_text(json.dumps(
            {"commands": [{"index": 0, "argv": p.commands[0], "exit_code": 0}], "all_ok": True}))
        rec = script_run.derive_record(p)
    finally:
        import shutil
        shutil.rmtree(REPO / "comms" / "research" / UNIT / "t1", ignore_errors=True)
        try:
            (REPO / "comms" / "research" / UNIT).rmdir()
        except OSError:
            pass
    assert rec["read_state"] == "measured" and rec["verdict"] == v["verdict"]
    assert rec["decision_rule_id"] == raw["decision_rule"]["id"]
