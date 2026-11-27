"""TICK-REGIME-BAR-ONCE: the symbol-agnostic live regime pass runs at most once per interval.

pipeline.run_pipeline calls emit_regime_bar_predictions once per SYMBOL pass; before
2026-11-27 a 41-symbol tick re-resolved the registry 41x (~43 s of a ~125 s tick).
"""
from __future__ import annotations

from src.runtime import regime_bar_scoring as R


def _arm(monkeypatch, clock_values):
    calls = []
    monkeypatch.setattr(R, "_LAST_LIVE_PASS", [float("-inf")])
    it = iter(clock_values)
    monkeypatch.setattr(R.time, "monotonic", lambda: next(it))
    monkeypatch.setattr(R, "_resolve_regime_predictors", lambda root, lp: calls.append(1) or [])
    monkeypatch.delenv("REGIME_BAR_SCORING_DISABLED", raising=False)
    return calls


def test_live_pass_runs_once_per_interval_not_once_per_symbol(monkeypatch, tmp_path):
    monkeypatch.delenv("REGIME_BAR_MIN_INTERVAL_S", raising=False)
    calls = _arm(monkeypatch, [100.0 + i * 0.5 for i in range(41)] + [131.0])
    for _ in range(41):                                   # one tick: 41 symbol passes in ~20 s
        R.emit_regime_bar_predictions({}, log_path=tmp_path / "s.jsonl")
    assert len(calls) == 1
    R.emit_regime_bar_predictions({}, log_path=tmp_path / "s.jsonl")   # next tick, 31 s later
    assert len(calls) == 2


def test_interval_zero_restores_every_call(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_BAR_MIN_INTERVAL_S", "0")
    calls = _arm(monkeypatch, [100.0, 100.1, 100.2])
    for _ in range(3):
        R.emit_regime_bar_predictions({}, log_path=tmp_path / "s.jsonl")
    assert len(calls) == 3


def test_bad_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("REGIME_BAR_MIN_INTERVAL_S", "nope")
    assert R._min_interval_seconds() == R._DEFAULT_MIN_INTERVAL_S


def test_injected_predictors_are_never_throttled(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_LAST_LIVE_PASS", [1e18])     # "just ran"
    monkeypatch.setattr(R.time, "monotonic", lambda: 1e18)
    calls = []
    monkeypatch.setattr(R, "_resolve_regime_predictors", lambda root, lp: calls.append(1) or [])
    assert R.emit_regime_bar_predictions({}, predictors=[]) == 0
    assert calls == []


def test_a_registry_stage_change_propagates_on_the_next_due_pass(monkeypatch, tmp_path):
    """The throttle never caches predictors: the first pass due after a registry
    rewrite (the mirror publish on a promotion) re-resolves, i.e. a real stage
    change reaches scoring within one interval (<= the next tick)."""
    import os
    import time as _t

    from tests.runtime.test_registry_fingerprint import TestPredictorCacheInvalidation

    root = TestPredictorCacheInvalidation()._registry_with_one_entry(tmp_path)
    log = tmp_path / "shadow.jsonl"
    monkeypatch.setattr(R, "_PREDICTOR_CACHE", {})
    monkeypatch.setattr(R, "_LAST_LIVE_PASS", [float("-inf")])
    monkeypatch.delenv("REGIME_BAR_MIN_INTERVAL_S", raising=False)
    monkeypatch.delenv("REGIME_BAR_SCORING_DISABLED", raising=False)
    clock = iter([100.0, 110.0, 131.0])
    monkeypatch.setattr(R.time, "monotonic", lambda: next(clock))
    seen = []
    real = R._resolve_regime_predictors
    monkeypatch.setattr(R, "_resolve_regime_predictors", lambda r, lp: seen.append(real(r, lp)) or [])

    R.emit_regime_bar_predictions({}, registry_root=root, log_path=log)    # t=100: due
    for f in root.glob("*.json"):                                           # stage rewrite
        t = _t.time() + 5
        os.utime(f, (t, t))
    R.emit_regime_bar_predictions({}, registry_root=root, log_path=log)    # t=110: throttled
    R.emit_regime_bar_predictions({}, registry_root=root, log_path=log)    # t=131: due
    assert len(seen) == 2 and seen[1] is not seen[0]                         # fresh resolution
