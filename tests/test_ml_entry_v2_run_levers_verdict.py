"""ml_entry_v2_run.write_verdict covers every `levers`-mode result shape (PI-20261122-SME5WDGR-0004, group D2).

The four `levers` units (b604-01, b607-01, b608-01, a508-01) each ran on the runner 3-5 times and landed `producer_failed: no verdict.json`. The ML-PRIMARY-3 lane
(2026-11-15) mapped the `arms` shape (b604, b607); the `levels` shape (b608: winning_stack) and the `flags` shape (a508: per-symbol attribution) were still
unmapped. Locked here against the REAL committed ML-RECIPE local results (comms/research/<unit>/local-*/result.json), copied in as <unit>_result.json (the name the
runner path writes): (1) every verdict.json satisfies script_run's contract, (2) the mapping follows the registered rule's own words, (3) a missing winning stack is
`fail`, never `pass`, (4) a508's descriptive attribution is `no_action_warranted`, (5) an unrecognised shape writes nothing (returns False), it is not guessed.
"""
from __future__ import annotations

import glob
import json
import shutil
from pathlib import Path

import pytest

import scripts.research.ml_entry_v2_run as r
from scripts.research import script_run as sr

REPO = Path(__file__).resolve().parents[1]


def _real(unit: str) -> Path:
    hits = sorted(glob.glob(str(REPO / f"comms/research/{unit}/local-*/result.json")))
    assert hits, f"the committed local result for {unit} is the fixture; without it this test is vacuous"
    return Path(hits[-1])


def _run(tmp_path, unit, src: Path | None = None, data: dict | None = None):
    if data is not None:
        (tmp_path / f"{unit}_result.json").write_text(json.dumps(data))
    else:
        shutil.copy(src, tmp_path / f"{unit}_result.json")
    ok = r.write_verdict(unit, tmp_path)
    v = json.loads((tmp_path / "verdict.json").read_text()) if (tmp_path / "verdict.json").exists() else None
    return ok, v


def _contract(v):
    assert v["verdict"] in sr.VERDICTS and v["read_state"] in sr.READ_STATES
    assert str(v["population"]).strip() and "n" in v


@pytest.mark.parametrize("unit,want", [
    ("RQ-20261101-b604-01", "indeterminate"),     # R1 isotonic indeterminate (a fold with 200 decisions), binned remap no_win: no arm wins, one could not decide
    ("RQ-20261101-b607-01", "pass"),              # R1/R2 single and E2/E3 ensembles WIN
    ("RQ-20261101-b608-01", "pass"),              # winning stack S3_R2_gate_24
    ("RQ-20261101-a508-01", "no_action_warranted"),  # per-symbol attribution, no pass bar
])
def test_real_local_results_map_to_the_registered_outcome(tmp_path, unit, want):
    ok, v = _run(tmp_path, unit, src=_real(unit))
    assert ok and v is not None
    _contract(v)
    assert v["read_state"] == "measured" and v["verdict"] == want
    assert isinstance(v["n"], int) and v["n"] > 1000        # the dev-fold population (about 72k decisions per seed), never null with measured


def test_b608_winning_stack_is_named_in_the_population(tmp_path):
    ok, v = _run(tmp_path, "RQ-20261101-b608-01", src=_real("RQ-20261101-b608-01"))
    assert "S3_R2_gate_24" in v["population"]


def test_no_winning_stack_is_a_fail_not_a_pass(tmp_path):
    d = json.loads(_real("RQ-20261101-b608-01").read_text())
    d["winning_stack"] = None
    ok, v = _run(tmp_path, "RQ-20261101-b608-01", data=d)
    assert ok and v["verdict"] == "fail"
    _contract(v)


def test_all_no_win_arms_are_a_fail(tmp_path):
    d = {"arms": {"base": {"verdict": "base", "n": [100]}, "A": {"verdict": "no_win", "n": [100]}, "B": {"verdict": "no_win", "n": [90]}}}
    ok, v = _run(tmp_path, "RQ-X", data=d)
    assert ok and v["verdict"] == "fail"
    _contract(v)


def test_an_unrecognised_shape_is_not_guessed(tmp_path):
    ok, v = _run(tmp_path, "RQ-X", data={"something": "else"})
    assert ok is False and v is None
