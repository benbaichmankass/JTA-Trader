"""DESK-18E mechanics probe: <= PROBE_MAX labelled demo trades (2, then 3 on the operator's 2026-10-28 A2 re-authorization), no EV claim, excluded from every edge statistic."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.ops import desk_intake as di
from src.units.strategies import claude_desk as cd

cdr = di.cdr
dw = cdr.desk_write
SCHEMA = json.loads(cdr.DECISION_SCHEMA.read_text())
NOW = datetime(2026, 10, 26, 9, 6, tzinfo=timezone.utc)
SCOPE = {"enabled": True, "execution": "live", "symbols": ["ETHUSDT"]}
DRAFT = {"action": "propose_entry", "mechanics_probe": True, "confidence": "anecdote", "basis": "mechanics",
         "judge_prior": None, "rationale": "mechanics probe: plumbing test, no claim of edge", "weighed": [],
         "proposal": {"symbol": "ETHUSDT", "side": "long", "horizon_bars": 12,
                      "entry": {"type": "market", "level": 100.0, "good_till_bars": 2},
                      "stop": {"level": 97.0, "basis": "swing_level"},
                      "tp": {"level": 104.0, "basis": "swing_level", "p_hit": 0.4},
                      "expected_r_net": None, "thesis": "mechanics probe", "max_hold_min": 45}}


def compile_(draft=DRAFT, scope=SCOPE, probe_rows=0):
    p = copy.deepcopy(cdr.GOOD_SCAN)
    ptr = {"packet_id": p["meta"]["packet_id"], "packet_sha": cdr.packet_sha(p)}
    return dw.compile_row(copy.deepcopy(draft), ptr, p, SCHEMA, now=NOW, skill_sha=None, scope=scope, probe_rows=probe_rows), p


def test_a_probe_row_is_live_no_ev_claim_and_excluded_from_training(tmp_path):
    row, p = compile_()
    assert row["label_source"] == "live" and row["intent_id"] and row["judge_prior"] is None
    assert row["proposal"]["expected_r_net"] is None
    assert row["training"] == {"train_eligible": False, "gate_eligible": False, "exclusion_reasons": ["mechanics_probe"]}
    assert dw.row_problems(row, p, SCHEMA) == []
    (tmp_path / f"{p['meta']['packet_id']}.json").write_text(json.dumps(p))
    assert cdr.decision_problems(row, SCHEMA, tmp_path) == []
    assert cdr.expected_training(row)[:2] == (False, False)


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["proposal"].update(expected_r_net=0.1), "no EV claim"),
    (lambda d: d.update(judge_prior=0.4), "no EV claim"),
    (lambda d: d.update(confidence="suggestive"), "anecdote"),
    (lambda d: d.update(action="no_trade"), "propose_entry"),
])
def test_a_probe_with_an_ev_claim_or_wrong_shape_is_refused(mutate, needle):
    d = copy.deepcopy(DRAFT)
    mutate(d)
    with pytest.raises(dw.Refused) as e:
        compile_(d)
    assert needle in " ".join(e.value.problems)


def test_a_probe_must_be_on_a_leg_symbol_and_is_capped():
    with pytest.raises(dw.Refused):
        compile_(scope=dict(SCOPE, symbols=["AVAXUSDT"]))
    compile_(probe_rows=dw.PROBE_MAX - 1)
    with pytest.raises(dw.Refused) as e:
        compile_(probe_rows=dw.PROBE_MAX)
    assert "cap" in " ".join(e.value.problems)


def test_a_normal_proposal_still_needs_its_ev_claim():
    d = copy.deepcopy(DRAFT)
    d.pop("mechanics_probe")
    d.update(basis="ev_positive", confidence="suggestive", judge_prior=0.4)
    d["proposal"]["expected_r_net"] = 0.1
    row, p = compile_(d)
    assert dw.row_problems(row, p, SCHEMA) == []
    row["proposal"]["expected_r_net"] = None
    assert any("expected_r_net" in x for x in dw.row_problems(row, p, SCHEMA))


def test_the_guard_refuses_a_probe_row_past_the_cap(tmp_path):
    row, p = compile_()
    dec = tmp_path / "decisions.jsonl"
    rows = []
    for i in range(dw.PROBE_MAX + 1):
        r = copy.deepcopy(row)
        r["decision_id"] = f"DD-X{i}"
        rows.append(json.dumps(r))
    dec.write_text("\n".join(rows) + "\n")
    out = cdr.findings(decisions=dec, touches=tmp_path / "t.jsonl", packets=tmp_path / "pk", outcomes=tmp_path / "o.jsonl",
                       consumed=tmp_path / "c.jsonl")
    assert any(f"exceed the cap of {dw.PROBE_MAX}" in x for x in out)


def test_intake_refuses_a_probe_while_a_real_money_account_carries_the_leg():
    row, _ = compile_()
    args = dict(problems=[], packet={}, gate=None, leg_rostered=True, leg_symbols=["ETHUSDT"])
    assert di.classify(row, carrying=["bybit_1"], **args)[0] == "accepted"
    assert di.classify(row, carrying=["bybit_1", "bybit_2"], **args)[0] == "refused"
    assert di.classify(row, carrying=None, **args)[0] == "refused"


def test_the_package_is_minimum_confidence_and_marked():
    row, _ = compile_()
    acc = {"decision_id": row["decision_id"], "intent_id": row["intent_id"], "proposal": row["proposal"], "mechanics_probe": True}
    pkg = cd.order_package({"confidence": 0.5}, acc)
    assert pkg["confidence"] == cd.PROBE_CONFIDENCE and pkg["meta"]["mechanics_probe"] is True
    normal = cd.order_package({"confidence": 0.5}, dict(acc, mechanics_probe=False))
    assert normal["confidence"] == 0.5 and normal["meta"]["mechanics_probe"] is False


def test_outcomes_never_replay_a_probe():
    src = (Path(__file__).resolve().parents[1] / "scripts/ops/desk_outcomes.py").read_text()
    assert 'd.get("basis") == "mechanics"' in src and "excluded from edge replay" in src
