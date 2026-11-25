"""exit_lever_ablation arm-key reachability (PI-20261119-FILLW47B-0013, RESEARCH-UNBLOCK-BUILDS-W48).

An arm key whose change leaves the harness argv byte-identical cannot reach the backtest. Planted/clean:
  * ict_scalp: such a key is routed through the harness's --cfg-set channel (the argv now differs), while a
    key the builder already forwards is left alone;
  * any other harness: the arm is REFUSED, never run as the baseline under its own label;
  * backtest_ict_scalp.apply_cfg_overrides: set / unset / refuse an unknown key; empty = the same dict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]
import exit_lever_ablation as e  # noqa: E402
import backtest_ict_scalp as bis  # noqa: E402

import yaml  # noqa: E402

_LEGS = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text(encoding="utf-8"))
_LEGS = _LEGS.get("strategies", _LEGS)
# the real leg block (classify() keys on it); the two displacement keys pinned so the arms below always differ
SCALP = {**_LEGS["ict_scalp_sol_5m"], "displacement_atr_mult": 1.3, "min_displacement_body_to_range": 0.55}


def _route(base, arms, leg="ict_scalp_sol_5m"):
    specs = [e.parse_arm(a) for a in arms]
    return e.route_unforwarded_keys(leg, base, specs, csv="<d>", resample=str(base.get("timeframe")))


def test_ict_scalp_unforwarded_key_is_routed_and_changes_the_argv():
    specs, routed, refused = _route(SCALP, ["A=", "disp_hi=displacement_atr_mult=1.625"])
    assert refused == [] and routed == {"disp_hi": ["--cfg-set=displacement_atr_mult=1.625"]}
    lab, sets, uns, extra = specs[1]
    assert extra == ["--cfg-set", "displacement_atr_mult=1.625"]
    tf = str(SCALP.get("timeframe"))
    a0, _ = e.build_arm_argv("ict_scalp_sol_5m", SCALP, "<d>", tf, "<e>", "<j>", [], None, None)
    a1, _ = e.build_arm_argv("ict_scalp_sol_5m", e.arm_cfg(SCALP, sets, uns), "<d>", tf, "<e>", "<j>", extra, None, None)
    assert a1 != a0 and a1[-2:] == ["--cfg-set", "displacement_atr_mult=1.625"]


def test_two_routed_keys_are_both_kept():
    specs, routed, _ = _route(SCALP, ["X=displacement_atr_mult=1.6;min_displacement_body_to_range=0.7"])
    a1, _ = e.build_arm_argv("ict_scalp_sol_5m", SCALP, "<d>", str(SCALP.get("timeframe")), "<e>", "<j>", specs[0][3],
                             None, None)
    assert a1.count("--cfg-set") == 2
    assert "displacement_atr_mult=1.6" in a1 and "min_displacement_body_to_range=0.7" in a1


def test_unchanged_value_and_baseline_arm_route_nothing():
    _specs, routed, refused = _route(SCALP, ["A=", "same=displacement_atr_mult=1.3"])
    assert routed == {} and refused == []


def test_non_cfg_set_harness_refuses_an_unforwarded_key():
    trend = {**_LEGS["trend_donchian_1h"], "zz_unused": 1}
    _specs, routed, refused = _route(trend, ["A=", "dead=zz_unused=5"], leg="trend_donchian_1h")
    assert len(refused) == 1 and "zz_unused" in refused[0] and "cannot reach the backtest" in refused[0]
    _specs, routed, refused = _route(trend, ["A=", f"live=donchian={int(trend['donchian']) + 7}"], leg="trend_donchian_1h")
    assert refused == [] and routed == {}       # a forwarded key: untouched


def test_apply_cfg_overrides():
    cfg = {"displacement_atr_mult": 1.3}
    assert bis.apply_cfg_overrides(cfg, [], []) is cfg
    out = bis.apply_cfg_overrides(cfg, ["displacement_atr_mult=1.625", "min_displacement_body_to_range=0.4"], [])
    assert out == {"displacement_atr_mult": 1.625, "min_displacement_body_to_range": 0.4} and cfg == {"displacement_atr_mult": 1.3}
    assert bis.apply_cfg_overrides(cfg, [], ["displacement_atr_mult"]) == {}
    with pytest.raises(ValueError):
        bis.apply_cfg_overrides(cfg, ["not_a_unit_key=1"], [])
    with pytest.raises(ValueError):
        bis.apply_cfg_overrides(cfg, ["novalue"], [])
