"""prop_candidate_gate refuses a verdict with no population (PI-20261101-HOPS1447-0001).

The runner rejects a verdict.json with no `population` as malformed, which hid a real harness failure behind a
'malformed' record for four confirmation units. An empty population must become indeterminate / producer_failed with a
could_not_look note, never an empty or passing verdict.
"""
from __future__ import annotations

import json

import scripts.research.prop_candidate_gate as g


def test_empty_population_is_refused(tmp_path):
    for pop in (None, "", "   "):
        v = {"verdict": "pass", "read_state": "measured", "n": 7, "population": pop, "note": "x"}
        out = g._write_verdict(tmp_path / "verdict.json", v)
        disk = json.loads((tmp_path / "verdict.json").read_text())
        assert out == disk
        assert disk["verdict"] == "indeterminate" and disk["read_state"] == "producer_failed"
        assert disk["note"].startswith("could_not_look") and disk["population"].strip()


def test_missing_population_key_is_refused(tmp_path):
    out = g._write_verdict(tmp_path / "verdict.json", {"verdict": "fail", "read_state": "measured", "n": 3})
    assert out["verdict"] == "indeterminate" and out["read_state"] == "producer_failed"


def test_a_real_population_passes_through_unchanged(tmp_path):
    v = {"verdict": "fail", "read_state": "measured", "n": 5, "population": "leg n=5", "note": "FAIL: ok"}
    assert g._write_verdict(tmp_path / "verdict.json", v) == v
