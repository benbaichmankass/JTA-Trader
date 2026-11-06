"""ada_pullback_2h VH95 (vol_skip_above_pctl 0.95) Tier-3 packet pins.

The declared value must reach the live unit's resolved params (an unknown key
passes through order_package silently, so reading the config alone proves
nothing). Since 2026-11-06 (PROD-LEGS-DSR-DECISION) the leg is a TESTING leg on bybit_1, off the Stage-2 pair.
Evidence: research/results/RQ-20261018-002/ (rule RULE-RQ2026101665ff06-REGIME-VOLHOT-CONFIRM).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from src.units.strategies import htf_pullback_trend_2h as hp

ROOT = Path(__file__).resolve().parents[1]


def _ada_block():
    cfg = yaml.safe_load((ROOT / "config" / "strategies.yaml").read_text())
    return cfg["strategies"]["ada_pullback_2h"]


def test_declared_vh95_reaches_live_params_and_keeps_the_tested_arm():
    block = _ada_block()
    params = hp._resolve_params(block)
    assert params["vol_skip_above_pctl"] == 0.95
    # The tested arm B differed from VH95 ONLY in this key (RQ-20261018-002 arm params).
    assert params["vol_skip_below_pctl"] == 0.1
    assert params["vol_pctl_window"] == 200
    assert params["adx_min"] == 28.0
    assert params["atr_stop_mult"] == 1.5 and params["trail_mult"] == 5.0
    assert params["pullback_frac"] == 0.618


def test_leg_moved_off_the_stage_2_pair_onto_the_demo_floor():
    # 2026-11-06 PROD-LEGS-DSR-DECISION (operator popup "Re-measure, then move (Rec.)"): ada_pullback_2h failed the trial
    # ledger's DSR > 0.95 AND BHY-haircut > 0 bar (docs/research/prod-legs-dsr-2026-11-06.md), so it left BOTH halves of the
    # Stage-2 pair together and trades as a TESTING leg on bybit_1. Pinned so a half-move (live without mirror) fails here.
    accts = yaml.safe_load((ROOT / "config" / "accounts.yaml").read_text())
    accts = accts.get("accounts", accts)
    assert "ada_pullback_2h" not in accts["bybit_2"]["strategies"]
    assert "ada_pullback_2h" not in accts["bybit_portfolio"]["strategies"]
    assert "ada_pullback_2h" in accts["bybit_1"]["strategies"]
