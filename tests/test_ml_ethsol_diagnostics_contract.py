"""ml_ethsol_diagnostics.py writes the research-result contract's verdict.json (PI-20261122-SME5WDGR-0004, group C).

RQ-20261102-002 (minedge) and -003 (risk) are DESCRIPTIVE diagnostics (no pass bar) that landed as `producer_failed: no verdict.json` 2-3 times each
with byte-identical outputs. Locked here against the REAL committed result.json files: (1) every mapped verdict.json satisfies script_run's contract,
(2) a fully-read descriptive diagnostic is `measured` + `no_action_warranted` (never `pass`/`fail`: there is no bar), (3) a requested section that did
not read is `no_data` + `indeterminate`, (4) sections that were not requested (`not_run`) do not block, (5) the measured numbers reach the population text.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

import scripts.research.ml_ethsol_diagnostics as d
from scripts.research import script_run as sr

REPO = Path(__file__).resolve().parents[1]
COMMITTED = sorted(glob.glob(str(REPO / "comms/research/RQ-20261102-00[23]/*/result.json")))


def _contract_ok(v: dict) -> None:
    assert v["verdict"] in sr.VERDICTS and v["read_state"] in sr.READ_STATES
    assert str(v["population"]).strip() and "n" in v


def test_real_results_exist():
    assert len(COMMITTED) >= 4


@pytest.mark.parametrize("path", COMMITTED)
def test_real_results_map_to_a_valid_descriptive_contract(path):
    res = json.loads(Path(path).read_text())
    v = d.contract_verdict(res)
    _contract_ok(v)
    assert v["read_state"] == "measured" and v["verdict"] == "no_action_warranted"
    assert v["verdict"] not in ("pass", "fail")
    assert str(res["n"]) in v["population"]
    if res["minedge"].get("read_state") == "ok":
        assert "0.06" in v["population"] and "min net edge" in v["population"]
    if res["risk"].get("read_state") == "ok":
        assert "best EV risk_pct" in v["population"]


def test_a_requested_section_that_did_not_read_is_not_measured():
    res = {"n": 381, "population": "p", "decomp": {"read_state": "not_run"}, "risk": {"read_state": "no_ledger"}, "minedge": {"read_state": "not_run"}}
    v = d.contract_verdict(res)
    _contract_ok(v)
    assert v["read_state"] == "no_data" and v["verdict"] == "indeterminate"


def test_nothing_requested_is_not_measured():
    res = {"n": 5, "population": "p", "decomp": {"read_state": "not_run"}, "risk": {"read_state": "not_run"}, "minedge": {"read_state": "not_run"}}
    v = d.contract_verdict(res)
    _contract_ok(v)
    assert v["read_state"] == "no_data" and v["verdict"] == "indeterminate"
