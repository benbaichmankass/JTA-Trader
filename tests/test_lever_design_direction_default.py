"""RESEARCH-LEVER-FAMILY-REACH (part b): `direction` is reachable by the weekly lever generator through a declared default.

Before this change `lever_design` only offered families with a numeric config key or a `declared:` block, so `direction` was never
swept. Contract:
  * a trend or pullback harness leg gets a `direction` family whose arms are the harness flag `--side-filter long|short`;
  * an arm equal to the leg's own `side_filter` is dropped (a long-only leg gets only `short`);
  * a leg's own `declared:` block wins for the family;
  * a leg the harness classifier cannot route gets no default (a default, never a refusal);
  * `session` / `sizing_vs_cost` / `symbol_set` / `timeframe` get NO default here (venue-specific or not an arm-minus-A lever);
  * every arm spec parses through exit_lever_ablation.parse_arm into a raw harness flag.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]

import lever_design as ld  # noqa: E402

FAMS = ["entry", "exit", "filter", "regime_gating", "timeframe", "symbol_set", "direction", "session", "sizing_vs_cost"]
PB = {"symbols": ["X"], "timeframe": "2h", "trend_lookback": 60, "pullback_lookback": 12, "pullback_frac": 0.5}
TR = {"symbols": ["X"], "timeframe": "4h", "donchian": 20}
ALL_TESTED_BUT_DIRECTION = {"manifest": {f: ("untested" if f == "direction" else "tested") for f in FAMS}}


def test_default_declared_covers_trend_and_pullback_only():
    assert set(ld.default_declared(PB)) == {"direction"}
    assert set(ld.default_declared(TR)) == {"direction"}
    assert ld.default_declared({"symbols": ["X"], "timeframe": "1d"}) == {}      # unclassifiable: no default, no error
    for fam in ("session", "sizing_vs_cost", "symbol_set", "timeframe"):
        assert all(fam not in spec for spec in [ld.default_declared(PB)]), fam


def test_direction_is_picked_and_arms_are_raw_flags():
    blk = ld.design_block("leg", "strategy_leg", PB, ALL_TESTED_BUT_DIRECTION, FAMS)
    assert blk["lever"] == "direction" and blk["lever_basis"] == "untested_family"
    assert blk["arms"] == [["A", ""], ["side_long", "--side-filter=long"], ["side_short", "--side-filter=short"]], blk["arms"]
    assert blk["k_variants"] == 2 and "design_gap" not in blk


def test_a_long_only_leg_gets_only_the_short_arm():
    blk = ld.design_block("leg", "strategy_leg", {**TR, "side_filter": "long"}, ALL_TESTED_BUT_DIRECTION, FAMS)
    assert [a for a, _ in blk["arms"]] == ["A", "side_short"], blk["arms"]


def test_a_legs_own_declared_block_wins_for_the_family():
    own = {**ALL_TESTED_BUT_DIRECTION, "declared": {"direction": [{"key": "--side-filter", "values": ["short"]}]}}
    blk = ld.design_block("leg", "strategy_leg", PB, own, FAMS)
    assert [s for _, s in blk["arms"]] == ["", "--side-filter=short"], blk["arms"]


def test_unclassifiable_leg_still_reports_a_design_gap_not_a_failure():
    blk = ld.design_block("leg", "strategy_leg", {"timeframe": "1d"}, ALL_TESTED_BUT_DIRECTION, FAMS)
    assert blk["lever"] is None and blk["arms"] == [["A", ""]] and blk["design_gap"]


def test_existing_numeric_levers_are_unchanged_by_the_default():
    # an untested numeric family still wins on policy order (entry before direction): the default only ADDS a candidate family
    m = {"manifest": {f: "untested" for f in FAMS}}
    blk = ld.design_block("leg", "strategy_leg", PB, m, FAMS)
    assert blk["lever"] == "entry"


def test_every_default_arm_parses_to_a_raw_harness_flag():
    import exit_lever_ablation as ela
    blk = ld.design_block("leg", "strategy_leg", PB, ALL_TESTED_BUT_DIRECTION, FAMS)
    parsed = [ela.parse_arm(f"{a}={s}") for a, s in blk["arms"][1:]]
    assert [p[3] for p in parsed] == [["--side-filter", "long"], ["--side-filter", "short"]]
    assert all(not p[1] and not p[2] for p in parsed)          # no config-key set / unset: a pure harness flag


def test_the_whole_roster_designs_without_error_and_direction_is_reachable_somewhere():
    import yaml
    cfgs = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    cfgs = cfgs.get("strategies", cfgs)
    reachable = 0
    for leg, cfg in cfgs.items():
        if not isinstance(cfg, dict):
            continue
        blk = ld.design_block(leg, "strategy_leg", cfg, {"manifest": {f: ("untested" if f == "direction" else "tested") for f in FAMS}}, FAMS)
        reachable += blk["lever"] == "direction"
    assert reachable > 0, "no roster leg can reach the direction family"
