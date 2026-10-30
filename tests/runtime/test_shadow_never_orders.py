"""I7 ML-SHADOW-NEVER-ORDERS: a shadow-stage model never changes an order.

Plan docs/plans/ml-live-promotion-plan-2026-10-29.md § 6 I7. The two ML sizing
consumers on the order path (``Coordinator.multi_account_execute``) are:

1. the WS7 advisory downsize (``advisory_sizing``), gated by model stage alone;
2. the conviction apply path (``conviction_sizing.apply_conviction_sizing`` under
   ``CONVICTION_SIZING_MODE=apply``), which reads the ``meta["conviction"]``
   stamp. That stamp blends SHADOW-stage scores (observe-only), so before I7 a
   shadow promotion would have resized orders the day ``apply`` was set.

Both are asserted with a model set that is shadow-only, in the most aggressive
configuration each path has (advisory ``mode: downsize`` with ``size_floor: 0``;
conviction ``apply`` + ``symmetric``): the qty equals the no-model baseline.

Recorded exception, not fixed here (filed): the trend_vol router reads the
FROZEN vol-bucket edges of a shadow-stage regime head when no advisory head
answers (``intents._decision_vol_regime`` falls back to the frozen label from
``regime.vol_detector``, which resolves shadow-stage specs). That is a
threshold frozen at fit time, not a model score, so no shadow PREDICTION moves
an order; but promoting a new head to shadow can make an authored cell start
gating. See the PR for the pipeline row.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.runtime import conviction_sizing as cs
from src.runtime.advisory_sizing import apply_advisory_downsize, compute_advisory_factor
from src.runtime.strategy_signal_builders import conviction_stamp

_LARGE = dict(
    balance_usd=100000.0, available_usd=1_000_000.0,
    total_account_usd=1_000_000.0, leverage=1, market_type="linear",
)


def _shadow_pred(model_id, stage, score):
    from ml.predictors.base import Predictor
    from ml.predictors.shadow import ShadowPredictor

    class _P(Predictor):
        def predict(self, row):
            return score

    return ShadowPredictor(_P(), model_id=model_id, stage=stage, log_path=None)


# ---- 1. advisory downsize -----------------------------------------------------

def test_shadow_only_registry_never_downsizes(monkeypatch):
    import ml.registry.model_registry as mr
    import ml.shadow.factory as fac
    import src.strategy_registry as sr

    monkeypatch.setattr(sr, "_strategy_cfg", lambda name: {
        "advisory_policy": {"mode": "downsize", "size_floor": 0.0, "quorum": 1}})
    monkeypatch.setattr(mr, "ModelRegistry", lambda root: SimpleNamespace(list=lambda: [
        SimpleNamespace(model_id="setup-candidates-metalabel-p2pool-v2",
                        target_deployment_stage="shadow"),
        SimpleNamespace(model_id="trade-outcome-x", target_deployment_stage="candidate"),
    ]))
    # Even if the resolver returned them, a maximally bearish score must not cut.
    monkeypatch.setattr(fac, "resolve_predictors", lambda ids, registry, log_path=None: [
        _shadow_pred(i, "shadow", 0.0) for i in ids])
    pkg = SimpleNamespace(strategy="trend_donchian", symbol="BTCUSDT",
                          direction="long", confidence=0.5, meta={})
    factor, record = compute_advisory_factor(pkg)
    assert factor == 1.0
    assert record["action"] == "no_advisory_models"
    assert apply_advisory_downsize(pkg, 0.5, account_name="bybit_1") == 0.5


def test_the_same_model_at_advisory_does_downsize(monkeypatch):
    """Positive control: the path above is not inert by construction."""
    import ml.registry.model_registry as mr
    import ml.shadow.factory as fac
    import src.strategy_registry as sr

    monkeypatch.setattr(sr, "_strategy_cfg", lambda name: {
        "advisory_policy": {"mode": "downsize", "size_floor": 0.0, "quorum": 1}})
    monkeypatch.setattr(mr, "ModelRegistry", lambda root: SimpleNamespace(list=lambda: [
        SimpleNamespace(model_id="setup-candidates-metalabel-p2pool-v2",
                        target_deployment_stage="advisory")]))
    monkeypatch.setattr(fac, "resolve_predictors", lambda ids, registry, log_path=None: [
        _shadow_pred(i, "advisory", 0.0) for i in ids])
    pkg = SimpleNamespace(strategy="trend_donchian", symbol="BTCUSDT",
                          direction="long", confidence=0.5, meta={})
    factor, _ = compute_advisory_factor(pkg)
    assert factor == 0.0


# ---- 2. conviction apply path -----------------------------------------------

def _pkg_with_stamp(stamp):
    return SimpleNamespace(entry=100.0, sl=90.0, symbol="BTCUSDT", direction="long",
                           strategy="trend_donchian", meta={"conviction": stamp})


def _apply(monkeypatch, tmp_path, stamp):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CONVICTION_SIZING_MODE", "apply")
    monkeypatch.setenv("CONVICTION_SIZING_DIRECTION", "symmetric")
    monkeypatch.delenv("CONVICTION_SIZING_ACCOUNTS", raising=False)
    return cs.apply_conviction_sizing(_pkg_with_stamp(stamp), 0.5,
                                      account_name="bybit_1", **_LARGE)


@pytest.mark.parametrize("shadow_score", [0.0, 0.2, 0.9, 1.0])
def test_shadow_scores_do_not_move_the_applied_size(monkeypatch, tmp_path, shadow_score):
    baseline = conviction_stamp("trend_donchian", 0.6, {}, direction="long")
    with_shadow = conviction_stamp("trend_donchian", 0.6, {
        "trade-outcome-x": {"stage": "shadow", "score": shadow_score},
        "setup-quality-y": {"stage": "shadow", "score": shadow_score},
    }, direction="long")
    # The observe-only blend DOES move (the soak number) ...
    assert with_shadow["conviction"] != baseline["conviction"]
    # ... the order does not.
    assert _apply(monkeypatch, tmp_path, with_shadow) == pytest.approx(
        _apply(monkeypatch, tmp_path, baseline))


def test_advisory_scores_do_move_the_applied_size(monkeypatch, tmp_path):
    """Positive control: an advisory-stage head is still allowed to influence."""
    baseline = conviction_stamp("trend_donchian", 0.6, {}, direction="long")
    with_adv = conviction_stamp("trend_donchian", 0.6, {
        "trade-outcome-x": {"stage": "advisory", "score": 0.05}}, direction="long")
    assert _apply(monkeypatch, tmp_path, with_adv) != pytest.approx(
        _apply(monkeypatch, tmp_path, baseline))


def test_legacy_stamp_fed_by_shadow_is_not_applied(monkeypatch, tmp_path):
    """A stamp written before I7 (no ``influencing`` key) whose provenance shows
    a shadow-stage input is not acted on: the qty is returned unchanged."""
    stamp = conviction_stamp("trend_donchian", 0.6, {
        "trade-outcome-x": {"stage": "shadow", "score": 0.1}}, direction="long")
    stamp.pop("influencing")
    assert _apply(monkeypatch, tmp_path, stamp) == 0.5
