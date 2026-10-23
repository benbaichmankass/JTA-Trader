"""DECISION-BAR-MATCH (operator 2026-10-22, "Split: 3 to closed, 2 stay"): adding
`decision_bar: closed` to xrp_pullback_2h / ada_pullback_2h / trend_donchian_eth_prop is
INERT to their committed Stage-0 records -- the harness argv is byte-identical with and
without the key (the Stage-0 harnesses decide on the closed bar by construction), and the
leg still grades `faithful`. This is the checked reason
scripts/ops/refresh_strategy_evidence_fingerprint.py requires before re-stamping
`config_fingerprint`. An explicit `forming` is NOT modelled and must stay an omission.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]
import regime_debt_matrix as rdm  # noqa: E402

LEGS = ["xrp_pullback_2h", "ada_pullback_2h", "trend_donchian_eth_prop"]
STRATS = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())["strategies"]


def _cmd(leg, cfg):
    return rdm.build_harness_cmd(leg, cfg, rdm.classify(cfg), "x.csv", "2h", "e.jsonl", "j.json")


@pytest.mark.parametrize("leg", LEGS)
def test_closed_key_is_declared_and_inert_to_the_harness(leg):
    cfg = dict(STRATS[leg])
    assert str(cfg.get("decision_bar")).lower() == "closed"
    without = {k: v for k, v in cfg.items() if k != "decision_bar"}
    argv, faithful, omitted = _cmd(leg, cfg)
    argv0, faithful0, omitted0 = _cmd(leg, without)
    assert argv == argv0
    assert (faithful, omitted) == (faithful0, omitted0) == (True, [])


@pytest.mark.parametrize("leg", LEGS)
def test_explicit_forming_is_still_an_omission(leg):
    cfg = dict(STRATS[leg], decision_bar="forming")
    _, faithful, omitted = _cmd(leg, cfg)
    assert not faithful and "decision_bar" in omitted
