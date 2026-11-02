"""RESEARCH-TEMPLATES-STRUCTURED (2026-11-01): the generated units of the six research/templates families carry a STRUCTURED LEVER
DESIGN by default (OPERATING-PLAN § 2 "THE research workflow"). One unit is generated from each template on a REAL subject of the
committed rosters, and its arms are asserted -- not the template text. Defaults, never refusals: a subject with no variable lever
still renders (control arm alone + design_gap)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
from scripts.research import lever_design as ld  # noqa: E402
from scripts.research import queue_replenish as q  # noqa: E402

DAY = "2026-11-01"


@pytest.fixture(scope="module")
def facts():
    return q.repo_facts(REPO)


@pytest.fixture(scope="module")
def templates():
    return {t["family"]: (p, sha, t) for p, sha, t in q.load_templates(REPO)}


def _unit(templates, facts, family, pick=0):
    path, sha, tpl = templates[family]
    pts = q.expand(tpl, facts)
    assert pts, f"{family}: no points"
    return yaml.safe_load(q.render(tpl, path, sha, pts[pick], "RQ-20261101-901", DAY)), pts[pick], tpl


def _arms(unit):
    cmd = [str(x) for x in unit["run"]["command"]]
    return [cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i] == "--arm"]


def test_roster_walkforward_control_plus_one_factor_variants(templates, facts):
    u, pt, _ = _unit(templates, facts, "roster-walkforward")
    arms = _arms(u)
    assert arms[0] == "A=", arms                                     # the base is the control arm
    assert len(arms) >= 2 and all(a.partition("=")[2].count("=") == 1 for a in arms[1:])   # each variant sets ONE key
    assert "@ARMS@" not in u["run"]["command"] and "sweep" in u["run"]["command"]
    assert u["design"] == "structured" and u["levers_declared"]
    it = u["iteration"]
    assert it["subject"] == pt["leg"] and it["design"]["levers"][pt["leg"]] == u["levers_declared"][0]
    assert it["multiple_testing"]["variants_vs_control"] == len(arms) - 1 and it["multiple_testing"]["arms_counted"] == len(arms)
    assert it["design"]["why_this_lever"][pt["leg"]] and it["due_by"] == "2026-11-15"
    assert u["generated"]["key"].endswith("lever_key=" + pt["lever"])   # a new lever is a NEW unit, never an edit
    assert u["decision_rule"]["registered_before_run"] is True


def test_every_roster_walkforward_point_renders_and_chooses_from_the_map(templates, facts):
    path, sha, tpl = templates["roster-walkforward"]
    for pt in q.expand(tpl, facts):
        d = json.loads(pt["design_json"])
        assert d["lever"] and d["lever_basis"] in ("untested_family", "attribution", "unresolved_shape", "least_tested"), (pt["leg"], d)
        mp = ld.read_map(REPO, pt["leg"])
        if d["lever_basis"] == "untested_family":                       # an untested family is chosen first
            assert (mp.get("manifest") or {}).get(d["lever"], "untested") != "tested", pt["leg"]
        yaml.safe_load(q.render(tpl, path, sha, pt, "RQ-20261101-902", DAY))


def test_prop_fit_prices_all_sizing_arms_in_one_unit(templates, facts):
    u, _pt, _ = _unit(templates, facts, "prop-fit-breakout")
    arms = _arms(u)
    assert arms[0].startswith("A=--sizing balance --risk-pct 0.010") and len(arms) == 5
    assert "arms_pass_bar" in u["run"]["command"] and u["design"] == "structured" and u["levers_declared"] == ["sizing_vs_cost"]
    assert u["iteration"]["multiple_testing"]["arms_counted"] == 5
    assert "sizing_arm" not in u["generated"]["key"]


def test_leg_corpus_carries_the_registered_arms_per_leg(templates, facts):
    u, _pt, _ = _unit(templates, facts, "leg-corpus-s1")
    cmd = [str(x) for x in u["run"]["command"]]
    arms_by_leg = json.loads(cmd[cmd.index("--arms-json") + 1])
    assert arms_by_leg and all(v[0] == ["A", ""] for v in arms_by_leg.values())
    assert u["design"] == "structured" and u["iteration"]["subject"]


@pytest.mark.parametrize("family,lever,k", [("m20-exit-lever", "exit", 7), ("e35-bracket", "exit", 198)])
def test_internal_sweeps_state_their_design(templates, facts, family, lever, k):
    u, _, _ = _unit(templates, facts, family)
    assert u["design"] == "structured" and u["levers_declared"] == [lever]
    assert u["iteration"]["multiple_testing"]["variants_vs_control"] == k and u["iteration"]["subject_kind"] == "strategy_leg"


def test_macro_valuation_cadence_siblings_are_structured_but_not_attributable(templates, facts):
    path, sha, tpl = templates["macro-valuation"]
    units = [yaml.safe_load(q.render(tpl, path, sha, p, "RQ-20261101-903", DAY)) for p in q.expand(tpl, facts)]
    assert sorted(u["design_arms"]["this_arm"] for u in units) == ["30", "7", "91"]
    assert [u["design_arms"]["is_control"] for u in units if u["design_arms"]["this_arm"] == "7"] == [True]
    assert all(u["design"] == "structured" and u["design_arms"]["attributable"] is False for u in units)


def test_no_variable_lever_is_a_default_not_a_refusal():
    blk = ld.design_block("s", "strategy_leg", {"timeframe": "1d", "symbols": ["X"]}, {}, ["entry", "exit"])
    assert blk["arms"] == [["A", ""]] and blk["design_gap"] and blk["lever"] is None


def test_verify_reproduces_generated_units(templates, facts):
    """the byte-for-byte re-render `queue_replenish.py --verify` relies on is stable for the new params"""
    path, sha, tpl = templates["roster-walkforward"]
    pt = q.expand(tpl, facts)[0]
    a = q.render(tpl, path, sha, pt, "RQ-20261101-904", DAY)
    gen = yaml.safe_load(a)["generated"]["params"]
    assert q.render(tpl, path, sha, dict(gen), "RQ-20261101-904", DAY) == a
