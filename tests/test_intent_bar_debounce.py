"""Per-bar EMISSION debounce in the intent multiplexer — re-entry-storm guard.

Covers PERF-20260601-001: a strategy must emit at most ONE intent per
(symbol, closed-bar bucket), regardless of whether that intent later opens, is
regime-gated, or is risk-rejected. The dispatch-side
``strategy_monocle._same_bar_entry_for_strategy`` guard is DB-backed (it scans
order_packages), so it cannot see a GATED intent that never creates a package —
the live htf_pullback short the regime router drops every tick. This
emission-side guard (``_debounce_emissions``) runs at the once-per-tick
aggregation boundary, BEFORE gating, so it covers that case.

Pure / no live exchange — drives ``_debounce_emissions`` directly with
hand-built intents and a stubbed timeframe lookup so the bucket is
deterministic. The autouse ``_reset_intent_emission_debounce`` conftest fixture
clears the module-level state between tests.
"""
from __future__ import annotations

import sys
import types
from unittest import mock

import pytest

# Pre-import stub for matplotlib so transitive pipeline imports don't crash in
# the lean sandbox env (mirrors tests/test_multi_strategy_intents.py).
if "matplotlib" not in sys.modules:
    _mpl_stub = types.ModuleType("matplotlib")
    _mpl_stub.pyplot = mock.MagicMock()
    sys.modules["matplotlib"] = _mpl_stub
    sys.modules["matplotlib.pyplot"] = mock.MagicMock()

import src.runtime.intent_multiplexer as im  # noqa: E402
from src.runtime.intents import StrategyIntent  # noqa: E402

_STRAT = "htf_pullback_trend_2h"
_BAR_SECONDS = 7200  # 2h
# A timestamp aligned to a 2h bucket boundary, so +offsets below stay in-bucket
# until they cross a full bar (avoids a boundary-straddle flake).
_T0 = (1_000_000_000 // _BAR_SECONDS) * _BAR_SECONDS  # bucket start


def _intent(strategy: str = _STRAT, symbol: str = "BTCUSDT", side: str = "long"):
    entry = 50_000.0
    sl, tp = (entry - 500, entry + 1500) if side == "long" else (entry + 500, entry - 1500)
    return StrategyIntent(
        strategy=strategy, symbol=symbol, side=side, target_qty=0.0,
        entry=entry, sl=sl, tp=tp,
    )


@pytest.fixture(autouse=True)
def _fixed_timeframe(monkeypatch):
    """Resolve a fixed 2h timeframe regardless of YAML; debounce enabled."""
    monkeypatch.setattr(im, "_strategy_timeframe_seconds", lambda name: _BAR_SECONDS)
    monkeypatch.setattr(im, "_bar_debounce_disabled", lambda: False)
    im._LAST_EMITTED_BUCKET.clear()
    yield
    im._LAST_EMITTED_BUCKET.clear()


def _names(intents):
    return [i.strategy for i in intents]


def test_first_emission_passes_through():
    kept = im._debounce_emissions([_intent()], now=_T0)
    assert _names(kept) == [_STRAT]


# GATE-BAR-DEBOUNCE was REMOVED by the operator on 2026-11-12 (decisions page,
# Gates tab; comms/gates/gate_decisions_2026-11-12.json). The emission-side
# debounce shares that gate's STRATEGY_BAR_DEBOUNCE_DISABLED switch, so it no
# longer drops anything: a same-bar repeat is logged and passed on. The four
# tests below used to assert the drop; they now assert pass-through.

def test_repeat_within_same_bar_now_passes():
    """Same 2h bucket → every tick passes (was: only the first)."""
    assert _names(im._debounce_emissions([_intent()], now=_T0)) == [_STRAT]
    assert _names(im._debounce_emissions([_intent()], now=_T0 + 60)) == [_STRAT]
    assert _names(im._debounce_emissions([_intent()], now=_T0 + 7199)) == [_STRAT]


def test_repeat_is_logged(caplog):
    """The observation is kept: the repeat is logged with the gate's name."""
    import logging
    caplog.set_level(logging.DEBUG, logger=im.logger.name)
    im._debounce_emissions([_intent()], now=_T0)
    im._debounce_emissions([_intent()], now=_T0 + 60)
    assert any("GATE-BAR-DEBOUNCE removed" in r.getMessage() for r in caplog.records)


def test_new_bar_still_passes():
    assert _names(im._debounce_emissions([_intent()], now=_T0)) == [_STRAT]
    assert _names(im._debounce_emissions([_intent()], now=_T0 + _BAR_SECONDS)) == [_STRAT]
    assert _names(im._debounce_emissions([_intent()], now=_T0 + _BAR_SECONDS + 60)) == [_STRAT]


def test_distinct_symbols_both_pass_on_repeat():
    both = [_intent(symbol="BTCUSDT"), _intent(symbol="ETHUSDT")]
    assert {i.symbol for i in im._debounce_emissions(both, now=_T0)} == {"BTCUSDT", "ETHUSDT"}
    assert {i.symbol for i in im._debounce_emissions(both, now=_T0 + 60)} == {"BTCUSDT", "ETHUSDT"}


def test_gated_intent_repeat_passes():
    """An intent the regime gate will drop downstream is no longer collapsed
    here; the regime gate (a separate, inventoried gate) decides on its own."""
    assert _names(im._debounce_emissions([_intent(side="short")], now=_T0)) == [_STRAT]
    assert _names(im._debounce_emissions([_intent(side="short")], now=_T0 + 60)) == [_STRAT]


def test_kill_switch_disables_debounce(monkeypatch):
    """STRATEGY_BAR_DEBOUNCE_DISABLED → every tick passes (rollback knob)."""
    monkeypatch.setattr(im, "_bar_debounce_disabled", lambda: True)
    assert _names(im._debounce_emissions([_intent()], now=_T0)) == [_STRAT]
    assert _names(im._debounce_emissions([_intent()], now=_T0 + 60)) == [_STRAT]


def test_unknown_timeframe_is_failopen(monkeypatch):
    """No resolvable timeframe → no debounce (never strands a live signal)."""
    monkeypatch.setattr(im, "_strategy_timeframe_seconds", lambda name: None)
    assert _names(im._debounce_emissions([_intent()], now=_T0)) == [_STRAT]
    assert _names(im._debounce_emissions([_intent()], now=_T0 + 60)) == [_STRAT]
