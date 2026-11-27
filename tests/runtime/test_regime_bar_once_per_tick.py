"""TICK-REGIME-BAR-ONCE: the live regime-bar pass resolves the registry once per TTL, not once per symbol.

pipeline.run_pipeline calls emit_regime_bar_predictions once per SYMBOL pass; before 2026-11-27 every
call re-resolved the registry (~43 s of a ~125 s, 41-symbol tick). Only the RESOLVE is memoised: every
call still scores every head group, so every symbol's head is scored on every bar close.
"""
from __future__ import annotations

import json
import os
import time as _t

from src.runtime import regime_bar_scoring as R
from tests.runtime.test_regime_bar_scoring import _candles, _regime_predictor, _spec

SYMBOLS = [f"SYM{i:02d}USDT" for i in range(41)]


def _live(monkeypatch, clock_values, resolver):
    monkeypatch.setattr(R, "_RESOLVE_MEMO", {})
    monkeypatch.setattr(R, "_REGIME_BAR_SEEN", {})
    monkeypatch.setattr(R, "_REGIME_FETCH_WALL", {})
    monkeypatch.setenv("REGIME_BAR_SCORING_BUDGET_S", "0")
    monkeypatch.delenv("REGIME_BAR_SCORING_DISABLED", raising=False)
    it = iter(clock_values)
    monkeypatch.setattr(R.time, "monotonic", lambda: next(it))
    calls = []
    monkeypatch.setattr(R, "_resolve_regime_predictors", lambda root, lp: calls.append(1) or resolver(root, lp))
    return calls


def test_all_41_symbols_scored_on_a_bar_close_with_one_resolve(monkeypatch, tmp_path):
    monkeypatch.delenv("REGIME_BAR_RESOLVE_TTL_S", raising=False)
    log = tmp_path / "shadow.jsonl"
    preds = [_regime_predictor(f"{s}-regime-5m", _spec(symbol=s), log) for s in SYMBOLS]
    calls = _live(monkeypatch, [100.0 + i * 0.4 for i in range(41)], lambda r, lp: preds)
    bar = {"ts": 1_000}
    fetch = lambda s, tf: _candles(last_ts=bar["ts"])
    for _ in SYMBOLS:                                    # one tick = 41 symbol passes, as the pipeline calls it
        R.emit_regime_bar_predictions({}, log_path=log, fetch_fn=fetch)
    assert len(calls) == 1                               # one resolve, not 41
    scored = [json.loads(x)["model_id"] for x in log.read_text().splitlines()]
    assert sorted(scored) == sorted(p.model_id for p in preds)   # every symbol's head, exactly once


def test_next_bar_is_scored_for_every_symbol_after_the_ttl(monkeypatch, tmp_path):
    monkeypatch.delenv("REGIME_BAR_RESOLVE_TTL_S", raising=False)
    log = tmp_path / "shadow.jsonl"
    preds = [_regime_predictor(f"{s}-regime-5m", _spec(symbol=s), log) for s in SYMBOLS]
    calls = _live(monkeypatch, [100.0, 400.0], lambda r, lp: preds)
    bar = {"ts": 1_000}
    fetch = lambda s, tf: _candles(last_ts=bar["ts"])
    R.emit_regime_bar_predictions({}, log_path=log, fetch_fn=fetch)
    bar["ts"] = 1_300
    R._REGIME_FETCH_WALL.clear()                         # the 5m fetch gate has elapsed
    R.emit_regime_bar_predictions({}, log_path=log, fetch_fn=fetch)
    assert len(calls) == 2
    assert len(log.read_text().splitlines()) == 2 * len(SYMBOLS)


def test_ttl_zero_restores_resolve_on_every_call(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_BAR_RESOLVE_TTL_S", "0")
    calls = _live(monkeypatch, [100.0, 100.1, 100.2], lambda r, lp: [])
    for _ in range(3):
        R.emit_regime_bar_predictions({}, log_path=tmp_path / "s.jsonl")
    assert len(calls) == 3


def test_bad_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("REGIME_BAR_RESOLVE_TTL_S", "nope")
    assert R._resolve_ttl_seconds() == R._DEFAULT_RESOLVE_TTL_S


def test_a_registry_stage_change_propagates_on_the_first_resolve_after_the_ttl(monkeypatch, tmp_path):
    """A registry rewrite (the mirror publish on a promotion) is re-resolved on the first call past the
    TTL; the fingerprint-keyed predictor cache is unchanged, so fresh objects come back."""
    from tests.runtime.test_registry_fingerprint import TestPredictorCacheInvalidation

    monkeypatch.delenv("REGIME_BAR_RESOLVE_TTL_S", raising=False)
    root = TestPredictorCacheInvalidation()._registry_with_one_entry(tmp_path)
    log = tmp_path / "shadow.jsonl"
    monkeypatch.setattr(R, "_PREDICTOR_CACHE", {})
    seen = []
    real = R._resolve_regime_predictors
    _live(monkeypatch, [100.0, 110.0, 121.0], lambda r, lp: seen.append(real(r, lp)) or seen[-1])
    R.emit_regime_bar_predictions({}, registry_root=root, log_path=log, fetch_fn=lambda s, tf: None)
    for f in root.glob("*.json"):
        t = _t.time() + 5
        os.utime(f, (t, t))
    R.emit_regime_bar_predictions({}, registry_root=root, log_path=log, fetch_fn=lambda s, tf: None)  # in TTL
    R.emit_regime_bar_predictions({}, registry_root=root, log_path=log, fetch_fn=lambda s, tf: None)  # past TTL
    assert len(seen) == 2 and seen[1] is not seen[0]
