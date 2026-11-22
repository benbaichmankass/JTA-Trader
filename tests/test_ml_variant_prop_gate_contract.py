"""ml_variant_prop_gate.py writes the research-result contract's verdict.json (PI-20261122-SME5WDGR-0004, group C).

The gate used to write only result.json, so a gate that ran to completion and graded landed as `producer_failed: no verdict.json`
(RQ-20261103-001..009, each fired 2-3 times with byte-identical outputs). Locked here, against the REAL committed result.json files
(not planted dicts): (1) every mapped verdict.json satisfies script_run's contract (verdict in VERDICTS, read_state in READ_STATES,
non-empty population, `n` present), (2) the decision is preserved (a FAIL stays `fail`, never promoted), (3) a result that graded
nothing (`no_variant_ledger`, `n_below_floor`) is `no_data`, never `measured`, (4) a PASS maps to `pass`.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

import scripts.research.ml_variant_prop_gate as g
from scripts.research import script_run as sr

REPO = Path(__file__).resolve().parents[1]
COMMITTED = sorted(glob.glob(str(REPO / "comms/research/RQ-20261103-00*/*/result.json")))


def _contract_ok(v: dict) -> None:
    assert v["verdict"] in sr.VERDICTS
    assert v["read_state"] in sr.READ_STATES
    assert str(v["population"]).strip()
    assert "n" in v


def test_committed_results_exist_to_test_against():
    assert len(COMMITTED) >= 9, "the real result.json files are the fixture; without them this test is vacuous"


@pytest.mark.parametrize("path", COMMITTED)
def test_real_results_map_to_a_valid_contract_and_keep_the_decision(path):
    res = json.loads(Path(path).read_text())
    v = g.contract_verdict(res)
    _contract_ok(v)
    if res.get("read_state") == "graded":
        assert v["read_state"] == "measured"
        assert v["verdict"] == str(res["verdict"]).lower()
        assert v["n"] == res["n"]
        for firm in res["verdict_by_firm"]:
            assert firm in v["population"]
    else:
        assert v["read_state"] == "no_data" and v["verdict"] == "indeterminate"


def test_no_ledger_and_below_floor_are_not_measured():
    for res in ({"rule": "R", "variant": "x", "read_state": "no_variant_ledger", "verdict": "INDETERMINATE", "missing_piece": "emit ledger"},
                {"rule": "R", "variant": "x", "read_state": "n_below_floor", "n": 5, "floor": 88, "verdict": "INDETERMINATE"}):
        v = g.contract_verdict(res)
        _contract_ok(v)
        assert v["read_state"] == "no_data" and v["verdict"] == "indeterminate"


def test_pass_maps_to_pass_and_unknown_never_promotes():
    res = {"rule": "R", "variant": "x", "read_state": "graded", "verdict": "PASS", "n": 300, "verdict_by_firm": {"breakout_2": "PASS"}}
    assert g.contract_verdict(res)["verdict"] == "pass"
    odd = dict(res, verdict="WEIRD")
    assert g.contract_verdict(odd)["verdict"] == "indeterminate"


def test_emit_writes_both_files(tmp_path):
    res = {"rule": "R", "variant": "x", "read_state": "graded", "verdict": "FAIL", "n": 201, "verdict_by_firm": {"breakout_2": "FAIL"}}
    g._emit(tmp_path, res)
    assert json.loads((tmp_path / "result.json").read_text()) == res
    _contract_ok(json.loads((tmp_path / "verdict.json").read_text()))
