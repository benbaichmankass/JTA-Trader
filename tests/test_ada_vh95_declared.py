"""ada_pullback_2h config pins: the HOLDOUT-CONFIRMED configuration (C7) and its Stage-2 placement.

History: VH95 (vol_skip_above_pctl 0.95) was declared 2026-10-18 (RQ-20261018-002). 2026-11-06 (Tier-3, operator popups
"Yes, rebuild and promote (Recommended)" + "Holdout governs; promote", via Manager 2026-11-06a) the key is REMOVED: the leg
runs the configuration its holdout confirmed (RQ-20261016-077e-04 C7; comms/strategy_evidence/ada_pullback_2h.json) and is
back on bybit_2 + bybit_portfolio (DSR probation, not a gate). The resolved params are read through the live unit (an unknown
key passes through order_package silently, so reading the config alone proves nothing).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from src.units.strategies import htf_pullback_trend_2h as hp

ROOT = Path(__file__).resolve().parents[1]


def _ada_block():
    cfg = yaml.safe_load((ROOT / "config" / "strategies.yaml").read_text())
    return cfg["strategies"]["ada_pullback_2h"]


def test_holdout_confirmed_c7_reaches_live_params():
    block = _ada_block()
    assert "vol_skip_above_pctl" not in block      # C7 did not carry VH95 (removed 2026-11-06)
    params = hp._resolve_params(block)
    assert not params.get("vol_skip_above_pctl")   # the unit default (off), not 0.95
    assert params["vol_skip_below_pctl"] == 0.1
    assert params["vol_pctl_window"] == 200
    assert params["adx_min"] == 28.0
    assert params["atr_stop_mult"] == 1.5 and params["trail_mult"] == 5.0
    assert params["pullback_frac"] == 0.618


def test_leg_on_both_halves_of_the_stage_2_pair_and_off_general_paper():
    # 2026-11-06 HOLDOUT-GOVERNS (operator option 3 "Holdout governs; promote"; supersedes the same day's PROD-LEGS-DSR-DECISION
    # removal): ada_pullback_2h is on BOTH halves of the Stage-2 pair together and off bybit_1 (production is not on general
    # paper). Pinned so a half-move (live without mirror) fails here.
    accts = yaml.safe_load((ROOT / "config" / "accounts.yaml").read_text())
    accts = accts.get("accounts", accts)
    assert "ada_pullback_2h" in accts["bybit_2"]["strategies"]
    assert "ada_pullback_2h" in accts["bybit_portfolio"]["strategies"]
    assert "ada_pullback_2h" not in accts["bybit_1"]["strategies"]
