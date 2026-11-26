"""RESEARCH-LEVER-FAMILY-REACH (part a): config-exact twin units for the lever families an ARM cannot express.

A different symbol or bar size is a different trade set, so it has no paired control; each twin is its own unit graded absolute
(Stage-0 rule). Contract:
  * twin choice is pure config + the lever map: same harness class, same asset class, own symbol excluded, coarser bar sizes only,
    nothing for a family the map already reads as tested, nothing for a harness exit_lever_ablation cannot run config-exact;
  * every generated point has a UNIQUE key, renders to the same bytes twice, leaves no placeholder unresolved, and carries a complete
    `iteration:` block (so the unit counts as a live iteration of its leg);
  * the command is a real exit_lever_ablation invocation: one arm `A=`, the twin flag, the absolute Stage-0 grade;
  * a twin PASS/FAIL is a lever-map reading, never a promotion (stated in the registered rule).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]

import twin_design as td  # noqa: E402

from scripts.research import queue_replenish as qr  # noqa: E402

DAY = "2026-11-26"


def test_pure_selftest_passes():
    assert td._self_test() == 0


@pytest.fixture(scope="module")
def facts():
    return qr.repo_facts(REPO)


@pytest.fixture(scope="module")
def templates():
    return {t["family"]: (path, sha, t) for path, sha, t in qr.load_templates(REPO) if t["family"].startswith("leg-twin-")}


def test_both_twin_templates_load(templates):
    assert set(templates) == {"leg-twin-symbol", "leg-twin-timeframe"}


@pytest.mark.parametrize("family", ["leg-twin-symbol", "leg-twin-timeframe"])
def test_points_are_unique_deterministic_and_fully_resolved(templates, facts, family):
    path, sha, tpl = templates[family]
    pts = qr.expand(tpl, facts)
    assert pts, "no twin point on the live roster (guards a vacuous loop)"
    keys = [qr.point_key(family, p) for p in pts]
    assert len(keys) == len(set(keys)), "two points share a dedupe key"
    for p in pts[:6]:
        a = qr.render(tpl, path, sha, p, "RQ-20261126-twin-01", DAY)
        assert a == qr.render(tpl, path, sha, p, "RQ-20261126-twin-01", DAY)
        assert not qr.unresolved_placeholders(a)
        u = yaml.safe_load(a)
        it = u["iteration"]
        assert it["subject"] == p["leg"] and it["subject_kind"] == "strategy_leg" and it["due_by"] and it["attempt"] == 1
        assert u["levers_declared"] == [("symbol_set" if family.endswith("symbol") else "timeframe")]
        assert u["decision_rule"]["registered_before_run"] is True
        assert "never gate" in u["decision_rule"]["what_it_does_not_do"] or "lever-map reading" in u["decision_rule"]["rule"]


def test_symbol_twins_never_use_the_legs_own_symbol_and_stay_in_class(templates, facts):
    _, _, tpl = templates["leg-twin-symbol"]
    for p in qr.expand(tpl, facts):
        assert p["twin"] != p["symbol"]
        assert td.asset_class(p["twin"]) == td.asset_class(p["symbol"])
        assert p["harness"] in td.HARNESS


def test_timeframe_twins_are_strictly_coarser(templates, facts):
    _, _, tpl = templates["leg-twin-timeframe"]
    for p in qr.expand(tpl, facts):
        assert td.TF_ORDER.index(p["twin"]) > td.TF_ORDER.index(p["timeframe"])


def test_the_command_is_a_real_absolute_ablation_run(templates, facts):
    help_text = subprocess.run([sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--help"],
                               capture_output=True, text=True, check=False).stdout
    for family, flag in (("leg-twin-symbol", "--symbol"), ("leg-twin-timeframe", "--timeframe")):
        path, sha, tpl = templates[family]
        p = qr.expand(tpl, facts)[0]
        cmd = yaml.safe_load(qr.render(tpl, path, sha, p, "RQ-20261126-twin-01", DAY))["run"]["command"]
        assert cmd[cmd.index(flag) + 1] == p["twin"] and flag in help_text
        assert cmd[cmd.index("--arm") + 1] == "A=" and cmd.count("--arm") == 1          # one arm: no paired control exists
        assert cmd[cmd.index("--grade") + 1] == "stage0" and cmd[cmd.index("--baseline") + 1] == "A"
        import exit_lever_ablation as ela
        assert ela.parse_arm("A=")[1:] == ({}, [], [])


def test_a_leg_whose_map_reads_the_family_as_tested_gets_no_twin(tmp_path):
    roster = {"x_pb": {"symbol": "XUSDT", "timeframe": "2h"}, "y_pb": {"symbol": "YUSDT", "timeframe": "2h"}}
    cfgs = {k: {"pullback_frac": 0.5, "trend_lookback": 60} for k in roster}
    assert td.symbol_twins("x_pb", roster, cfgs, {"manifest": {"symbol_set": "untested"}}) == ["YUSDT"]
    assert td.symbol_twins("x_pb", roster, cfgs, {"manifest": {"symbol_set": "tested"}}) == []
    assert td.timeframe_twins("x_pb", roster, cfgs, {"manifest": {"timeframe": "tested"}}) == []


def test_the_default_target_is_still_zero_so_the_cron_expands_nothing():
    # STOP-GENERATED-AUTHORING: adding templates must not turn the floor-filler back on
    assert qr._default_target() == 0
