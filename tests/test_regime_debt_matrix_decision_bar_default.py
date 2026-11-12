"""An ABSENT ``decision_bar`` is the runtime default, ``forming`` -- not ``closed``.

PI-20261030-QEJFFIDN-0002 / row EVIDENCE-DECISION-BAR-DEFAULT. ``build_harness_cmd``
only treated an EXPLICIT ``decision_bar: forming`` as an omitted lever, but the live
builders read ``str(vcfg.get("decision_bar") or "forming")``
(src/runtime/intent_multiplexer.py, strategy_signal_builders.py). A leg declaring
nothing trades the forming bar and was graded ``faithful`` on closed-bar numbers
(trend_donchian_eth_4h, trend_donchian_sol_prop).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "research"))
_spec = importlib.util.spec_from_file_location(
    "regime_debt_matrix", ROOT / "scripts" / "research" / "regime_debt_matrix.py")
rdm = importlib.util.module_from_spec(_spec)
sys.modules["regime_debt_matrix"] = rdm
_spec.loader.exec_module(rdm)

_TREND = {"model": "donchian", "symbols": ["ETHUSDT"], "timeframe": "4h", "donchian": 20,
          "atr_period": 14, "atr_stop_mult": 2.0, "trail_mult": 5.0, "min_confidence": 0.0}
_PB = {"model": "pullback", "symbols": ["XRPUSDT"], "timeframe": "2h", "trend_lookback": 40,
       "pullback_lookback": 10, "pullback_frac": 0.5, "atr_period": 14, "atr_stop_mult": 2.5,
       "trail_mult": 5.0, "min_confidence": 0.0}


def _build(cfg, harness):
    return rdm.build_harness_cmd("leg", cfg, harness, "d.csv", "4h", "e.jsonl", "j.json")


@pytest.mark.parametrize("harness,base", [("trend", _TREND), ("pullback", _PB)])
@pytest.mark.parametrize("extra,omits", [
    ({}, True),                              # absent == runtime default == forming
    ({"decision_bar": None}, True),
    ({"decision_bar": ""}, True),
    ({"decision_bar": "forming"}, True),
    ({"decision_bar": "FORMING"}, True),
    ({"decision_bar": "closed"}, False),     # what the harness does by construction
    ({"decision_bar": "Closed"}, False),
])
def test_decision_bar_default_is_forming(harness, base, extra, omits):
    _argv, faithful, omitted = _build({**base, **extra}, harness)
    assert ("decision_bar" in omitted) is omits
    assert faithful is (not omits)
