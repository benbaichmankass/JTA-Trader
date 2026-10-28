"""Enforced cost-net promotion gate (ML-TRAINING-PRINCIPLES-GAPS, practice M6/M10)
and the deflated Sharpe in the evaluation report (M5).

Planted data: rows where a feature ``sig`` perfectly separates net-R winners
(+1R / +2R) from losers (-1R, the cost-net loss). A model that takes ``sig > 0`` rows
beats take-all / take-none / matched-random; the inverted model (takes the
losers) and a constant model (takes nothing) are refused.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

from ml.experiments.runner import run_experiment
from ml.predictors.base import Predictor
from ml.promotion import cost_gate as cg
from ml.registry.model_registry import CostGateRefused, ModelRegistry
from ml.trainers.base import Trainer


class _SigPredictor(Predictor):
    def __init__(self, state: Mapping[str, Any]):
        self.sign = float(state["sign"])

    def predict(self, row: Mapping[str, Any]) -> float:
        return 1.0 if self.sign * float(row["sig"]) > 0 else 0.0


class GoodTrainer(Trainer):
    PREDICTOR_CLASS = _SigPredictor

    def fit(self, rows, config):
        return {"trainer": f"{__name__}.GoodTrainer", "sign": 1.0}


class BadTrainer(Trainer):
    PREDICTOR_CLASS = _SigPredictor

    def fit(self, rows, config):
        return {"trainer": f"{__name__}.BadTrainer", "sign": -1.0}


def _rows(n: int = 200, basis: str = "net") -> list[dict]:
    out = []
    for i in range(n):
        win = i % 3 == 0  # base rate 1/3 → take-all mean R < 0
        out.append({
            "ts": f"2026-01-01T{i:05d}",
            "sig": 1.0 if win else -1.0,
            "won": 1 if win else 0,
            "r_multiple": (1.0 + (i % 2)) if win else -1.0,
            "label_cost_basis": basis,
            "is_live_trade": False,
        })
    return out


def _setup(tmp_path: Path, trainer: str, *, stage: str = "shadow",
           basis: str = "net", model_id: str = "planted-meta-v1") -> tuple[Path, Path]:
    ds = tmp_path / "ds" / "setup_candidates" / "BTCUSDT" / "1h" / "v001"
    ds.mkdir(parents=True, exist_ok=True)
    (ds / "data.jsonl").write_text("".join(json.dumps(r) + "\n" for r in _rows(basis=basis)))
    cfgs = tmp_path / "configs"
    cfgs.mkdir(exist_ok=True)
    m = cfgs / f"{model_id}.yaml"
    m.write_text(yaml.safe_dump({
        "manifest_version": "v1",
        "model_id": model_id,
        "model_family": "test",
        "trainer": f"{__name__}.{trainer}",
        "trainer_config": {"target_column": "won", "feature_columns": ["sig"]},
        "dataset": {"family": "setup_candidates", "symbol_scope": "BTCUSDT",
                    "timeframe": "1h", "version": "v001"},
        "evaluator": "ml.evaluators.classification.ClassificationEvaluator",
        "evaluator_config": {"target_column": "won", "split_strategy": "holdout",
                             "holdout_fraction": 0.5},
        "target_deployment_stage": stage,
    }))
    return m, tmp_path / "ds"


def _train(tmp_path, manifest, datasets):
    return run_experiment(
        manifest_path=manifest, datasets_root=datasets,
        experiments_root=tmp_path / "exp", registry_root=tmp_path / "reg",
        code_revision="test",
    )


def test_unit_gate_refuses_loser_passes_winner():
    winners = [(True, 1.0)] * 30 + [(False, -1.0)] * 70
    losers = [(False, 1.0)] * 30 + [(True, -1.0)] * 70
    kw = dict(eval_cost_bases={"net": 100}, value_column="r_multiple",
              threshold=0.5, enforced=True)
    ok = cg.evaluate_cost_gate(winners, **kw)
    bad = cg.evaluate_cost_gate(losers, **kw)
    assert ok.passed and not ok.refuses and ok.candidate_value_r == pytest.approx(0.3)
    assert ok.take_all_r == pytest.approx(-0.4) and ok.matched_random_r == pytest.approx(-0.12)
    assert not bad.passed and bad.refuses and "take_none" in bad.reason
    # a better incumbent on the same rows refuses the winner
    champ = [(True, 1.0)] * 30 + [(False, -1.0)] * 70
    tie = cg.evaluate_cost_gate(winners, champion_pairs=champ, **kw)
    assert not tie.passed and "champion" in tie.reason
    # a gross evaluation population can never pass
    gross = cg.evaluate_cost_gate(winners, **{**kw, "eval_cost_bases": {"gross": 100}})
    assert not gross.passed and gross.reason.startswith("eval_not_cost_net")
    # revert switch: computed but not enforced
    off = cg.evaluate_cost_gate(losers, **{**kw, "enforced": False})
    assert not off.passed and not off.refuses


def test_winning_candidate_lands_in_shadow(tmp_path):
    m, ds = _setup(tmp_path, "GoodTrainer")
    art, entry = _train(tmp_path, m, ds)
    assert entry.target_deployment_stage == "shadow"
    assert entry.metrics["cost_gate_passed"] == 1.0
    assert entry.metrics["cost_net_value_r"] > 0
    gate = json.loads((art.experiment_dir / "cost_gate.json").read_text())
    assert gate["applicable"] and gate["passed"] and gate["n_trials"] == 1
    assert gate["psr"] is not None and gate["dsr"] is not None


def test_cost_losing_candidate_lands_at_candidate(tmp_path):
    m, ds = _setup(tmp_path, "BadTrainer")
    _, entry = _train(tmp_path, m, ds)
    assert entry.target_deployment_stage == "candidate"
    assert entry.metrics["cost_gate_passed"] == 0.0
    assert "cost gate refused" in entry.stage_history[0].reason
    reg = ModelRegistry(tmp_path / "reg")
    with pytest.raises(CostGateRefused):
        reg.promote_stage(entry.model_id, "shadow", by="t", reason="t")


def test_gross_dataset_refused(tmp_path):
    m, ds = _setup(tmp_path, "GoodTrainer", basis="gross")
    _, entry = _train(tmp_path, m, ds)
    assert entry.target_deployment_stage == "candidate"


def test_losing_retrain_keeps_incumbent_state(tmp_path):
    m, ds = _setup(tmp_path, "GoodTrainer")
    _, first = _train(tmp_path, m, ds)
    served = first.model_state_path
    m2, _ = _setup(tmp_path, "BadTrainer")
    import time; time.sleep(1.1)  # distinct run_id
    _, second = _train(tmp_path, m2, ds)
    assert second.target_deployment_stage == "shadow"
    assert second.model_state_path == served  # incumbent keeps serving
    assert len(second.runs) == 2
    assert "REFUSED the state swap" in second.history[-1].reason


def test_switch_off_disables_enforcement(tmp_path, monkeypatch):
    from ml.datasets.labeling import cost_policy
    monkeypatch.setattr(cost_policy, "cost_net_enabled", lambda *a, **k: False)
    m, ds = _setup(tmp_path, "BadTrainer")
    _, entry = _train(tmp_path, m, ds)
    assert entry.target_deployment_stage == "shadow"
    assert entry.metrics["cost_gate_enforced"] == 0.0


def test_regime_style_family_not_applicable(tmp_path):
    reg = ModelRegistry(tmp_path / "reg")
    e = reg.register(model_id="regime-x", manifest={
        "dataset": {"family": "market_features"}, "target_deployment_stage": "candidate"},
        model_state_path="x", metrics={}, code_revision="t")
    assert reg.promote_stage(e.model_id, "shadow", by="t", reason="t").target_deployment_stage == "shadow"


def test_pre_gate_cost_family_refused_without_evaluation(tmp_path):
    reg = ModelRegistry(tmp_path / "reg")
    e = reg.register(model_id="old-meta", manifest={
        "dataset": {"family": "setup_candidates"}, "target_deployment_stage": "candidate"},
        model_state_path="x", metrics={"accuracy": 0.8}, code_revision="t")
    with pytest.raises(CostGateRefused, match="no cost-net evaluation"):
        reg.promote_stage(e.model_id, "shadow", by="t", reason="t")
    # rollbacks are never gated
    reg2 = ModelRegistry(tmp_path / "reg2")
    e2 = reg2.register(model_id="old-meta", manifest={
        "dataset": {"family": "setup_candidates"}, "target_deployment_stage": "shadow"},
        model_state_path="x", metrics={}, code_revision="t")
    assert reg2.promote_stage(e2.model_id, "candidate", by="t", reason="t")


def test_dsr_deflates_with_trials():
    xs = [0.6, -0.4, 0.8, -0.2, 0.5, -0.3, 0.7, 0.1, -0.5, 0.9] * 5
    psr = cg.probabilistic_sharpe(xs)
    d1 = cg.deflated_sharpe(xs, 1)
    d50 = cg.deflated_sharpe(xs, 50)
    assert d1 == pytest.approx(psr)
    assert 0 < d50 < d1 < 1
    assert cg.expected_max_sharpe(1, 50) == 0.0
    assert cg.expected_max_sharpe(50, 50) > cg.expected_max_sharpe(5, 50) > 0
