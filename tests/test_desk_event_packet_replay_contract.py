"""desk_event_packet_replay.py writes a contract-valid verdict.json (PI-20261122-SME5WDGR-0004, group D).

RQ-20261112-e4a7-01 landed `producer_failed: verdict.json malformed: verdict 'S3_NOT_CLEARED' not in (pass, fail, ...)`: the script wrote the
rule's own vocabulary into the contract's field and no `n`. Locked against the REAL committed verdict.json of that unit: (1) the mapped
file satisfies script_run's contract, (2) S3_NOT_CLEARED -> fail with the registered word kept, (3) every rule word maps, an unknown one
never becomes pass/fail, (4) the measured fields are untouched.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

import scripts.research.desk_event_packet_replay as d
from scripts.research import script_run as sr

REPO = Path(__file__).resolve().parents[1]
COMMITTED = sorted(glob.glob(str(REPO / "comms/research/RQ-20261112-e4a7-01/*/verdict.json")))


def _ok(v):
    assert v["verdict"] in sr.VERDICTS and v["read_state"] in sr.READ_STATES
    assert str(v["population"]).strip() and "n" in v


def test_real_result_exists():
    assert COMMITTED


@pytest.mark.parametrize("path", COMMITTED)
def test_real_result_maps_to_a_valid_contract(path):
    res = json.loads(Path(path).read_text())
    if res.get("verdict") not in d._CONTRACT_VERDICT:     # an already-mapped file (a re-run on the fixed script)
        pytest.skip("already mapped")
    v = d.contract_verdict(res)
    _ok(v)
    assert v["verdict_word"] == res["verdict"] and v["verdict"] == d._CONTRACT_VERDICT[res["verdict"]]
    assert v["n"] == res["S3"]["n"]
    for k in ("S3", "controls_ok", "bar", "population"):
        assert v[k] == res[k]


def test_every_rule_word_maps_and_unknown_never_promotes():
    base = {"read_state": "measured", "population": "p", "S3": {"n": 5}}
    for word, want in (("S3_CLEARED", "pass"), ("S3_NOT_CLEARED", "fail"), ("INDETERMINATE", "indeterminate"), ("INDETERMINATE_INSTRUMENT", "indeterminate"), ("WEIRD", "indeterminate")):
        v = d.contract_verdict(dict(base, verdict=word))
        _ok(v)
        assert v["verdict"] == want and v["verdict_word"] == word
