"""LTR-APPLY-DISPATCH: a committed live-review row -> the per-account apply.

Operator popup ~07:12Z 2026-10-26, verbatim "Yes, top of the queue
(Recommended)": a Tier-2 lane wires the reviewed tighten_sl decisions into an
apply run. These tests pin the dispatcher (scripts/ops/live_review_dispatch.py).
It hands a row to live_review_apply.py only when MD-LIVE-TIGHTEN-SL's
package-level clauses hold on the COMMITTED row, it is idempotent per
review_id, and it adds no order path: the apply script, run as its own
process, still decides every account.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

import pytest

from scripts.ops import live_review_apply as lra
from scripts.ops import live_review_dispatch as d
from src.runtime import live_review_rows as rows_lib


@pytest.fixture(autouse=True)
def _legacy_tighten_path(monkeypatch):
    """These tests exercise the tighten mechanics kept for the record and for a revert. Production makes a
    tighten advice only (rows_lib.ADVICE_ONLY_ACTIONS, operator 2026-10-28); tests/test_tighten_advice_only.py
    covers that with the real value."""
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", ())

RID = "LR-20261026T0800Z-pkg-aaaa"
TABLE = "comms/live_review/tables/LR-20261026T0800Z-pkg-aaaa.json"

TABLE_ROW: Dict[str, Any] = {
    "review_id": RID, "order_package_id": "pkg-aaaa", "leg": "ada_pullback_2h",
    "accounts": ["bybit_2", "bybit_portfolio"],
    "mechanics": {"verdict": "match", "evidence": "agree"},
    "outcome_table_source": TABLE, "packet_sha": "ab" * 32,
    "recommendation": {"action": "tighten_sl", "level": 0.2101, "level_atr": 1.5, "ev_delta_r": -0.12,
                       "worst_case_delta_r": 0.9, "basis": "preference_within_bound",
                       "confidence": "measured", "evidence_source": "table"},
    "apply_policy": {"bound_r": 0.25, "within_bound": True, "tighten_r": 0.12},
    "account_reads": [{"account_id": "bybit_2", "account_class": "real_money", "read": "would_apply", "evidence": "x"},
                      {"account_id": "bybit_portfolio", "account_class": "paper", "read": "would_apply", "evidence": "x"}],
    "disposition": {"route": "recommended", "mandate": None, "action_issue": None,
                    "applied_at": None, "verified_readback": None},
}
MEASURED = json.dumps({"read_state": "measured", "n_floor": 20})


def _judged(row: Dict[str, Any]) -> Dict[str, Any]:
    r = copy.deepcopy(row)
    r["recommendation"].update(basis="judgement", evidence_source="judgement", judgement_confidence=0.62,
                               reason="stalled under the swing high", ev_delta_r=None, worst_case_delta_r=None,
                               confidence="anecdote")
    return r


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A fake git HEAD (path -> text), a recorded apply runner and VM-local state files."""
    w: Dict[str, Any] = {"files": {d.REVIEWS_PATH: json.dumps(TABLE_ROW) + "\n", TABLE: MEASURED},
                         "calls": [], "rc": 0, "pings": [], "writeback": None}
    monkeypatch.setattr(d, "_committed_text", lambda path, ref="HEAD": w["files"].get(path))
    monkeypatch.setattr(d, "DISPATCH_STATE", tmp_path / "dispatch_state.json")
    monkeypatch.setattr(d, "APPLIED_LOG", tmp_path / "applied.jsonl")
    monkeypatch.setattr(d, "_ping", lambda row, line: w["pings"].append(line))

    def run_apply(argv: List[str]) -> int:
        w["calls"].append(argv)
        if w["writeback"] is not None and "--apply" in argv:
            from datetime import datetime, timezone
            with (tmp_path / "applied.jsonl").open("a") as fh:
                fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **w["writeback"]}) + "\n")
        return w["rc"]

    monkeypatch.setattr(d, "_run_apply", run_apply)
    return w


def _set_row(world, row):
    world["files"][d.REVIEWS_PATH] = json.dumps(row) + "\n"


APPLIED_WB = {"review_id": RID, "applied": True,
              "account_reads": [{"account_id": "bybit_2", "account_class": "bybit", "read": "would_apply",
                                 "evidence": "approve_amend:approve:within_bounds"}],
              "accounts_applied": [{"account_id": "bybit_2", "level": 0.2101,
                                    "executor": {"result": "applied", "venue_after": 0.2101}}],
              "disposition": {"route": "auto_applied", "mandate": "MD-LIVE-TIGHTEN-SL", "verified_readback": True}}


# ------------------------------------------------------------------ positive paths

def test_a_table_row_is_handed_to_the_apply_with_the_20259_interface(world):
    world["writeback"] = APPLIED_WB
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "dispatched" and res["exit"] == 0
    argv = world["calls"][0]
    pairs = dict(zip(argv[::2], argv[1::2]))
    assert pairs["--package"] == "pkg-aaaa" and float(pairs["--new-sl"]) == 0.2101
    assert pairs["--review-id"] == RID and pairs["--evidence"] == TABLE
    assert pairs["--mandate"] == "MD-LIVE-TIGHTEN-SL" and pairs["--mechanics"] == "match"
    assert pairs["--basis"] == "table" and float(pairs["--expected-cost-r"]) == -0.12
    assert float(pairs["--worst-case-delta-r"]) == 0.9 and pairs["--packet-sha"] == "ab" * 32
    assert argv[-1] == "--apply" and "--confidence" not in argv
    # the per-account verdict with the venue read-back is reported
    assert any("bybit_2" in ln and "APPLIED" in ln and "venue_after=0.2101" in ln for ln in res["accounts"])


def test_a_judgement_row_carries_confidence_and_reason(world):
    _set_row(world, _judged(TABLE_ROW))
    world["files"][TABLE] = json.dumps({"read_state": "insufficient_n"})   # a thin table is fine for judgement
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "dispatched"
    argv = world["calls"][0]
    pairs = dict(zip(argv[::2], argv[1::2]))
    assert pairs["--basis"] == "judgement" and float(pairs["--confidence"]) == 0.62
    assert pairs["--reason"] == "stalled under the swing high" and "--expected-cost-r" not in argv


def test_without_apply_the_apply_script_runs_as_a_dry_run_and_records_nothing(world):
    res = d.dispatch(RID, apply=False)
    assert world["calls"][0][-1] == "--dry-run" and res["exit"] == 0
    assert not d.DISPATCH_STATE.exists()


def test_the_last_committed_row_with_the_id_wins():
    older = dict(TABLE_ROW, mechanics={"verdict": "mismatch", "evidence": "x"})
    text = json.dumps(older) + "\n" + json.dumps(TABLE_ROW) + "\n"
    row, _ = d.find_row(text, RID)
    assert row["mechanics"]["verdict"] == "match"


# ------------------------------------------------------------------ negative controls

@pytest.mark.parametrize("mutate, clause", [
    (lambda r: r["recommendation"].update(action="hold"), "not_tighten_sl:hold"),
    (lambda r: r["recommendation"].update(action="no_recommendation", basis="insufficient_n"), "not_tighten_sl"),
    (lambda r: r["mechanics"].update(verdict="mismatch"), "mechanics_mismatch"),
    (lambda r: r["mechanics"].update(verdict="could_not_look"), "mechanics_could_not_look"),
    (lambda r: r["disposition"].update(route="operator_ask"), "route_operator_ask"),
    (lambda r: r["recommendation"].update(level=None), "level_missing"),
    (lambda r: r["recommendation"].update(ev_delta_r=-0.4), "table_ev_outside_bound"),
    (lambda r: r["recommendation"].update(worst_case_delta_r=0.0), "table_worst_case_not_improved"),
    (lambda r: r["recommendation"].update(basis="insufficient_n", evidence_source=None), "basis_insufficient_n"),
])
def test_a_row_failing_a_mandate_clause_is_refused_and_nothing_is_sent(world, mutate, clause):
    row = copy.deepcopy(TABLE_ROW)
    mutate(row)
    _set_row(world, row)
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "refused" and res["exit"] == d.EXIT_REFUSED
    assert clause in res["detail"]
    assert world["calls"] == []


def test_a_table_row_on_a_thin_table_is_refused(world):
    world["files"][TABLE] = json.dumps({"read_state": "insufficient_n"})
    res = d.dispatch(RID, apply=True)
    assert "table_not_measured:insufficient_n" in res["detail"] and world["calls"] == []


@pytest.mark.parametrize("mutate, clause", [
    (lambda r: r["recommendation"].pop("judgement_confidence"), "judgement_confidence_missing"),
    (lambda r: r["recommendation"].update(judgement_confidence=1.4), "judgement_confidence_missing"),
    (lambda r: r["recommendation"].update(judgement_confidence=True), "judgement_confidence_missing"),
    (lambda r: r["recommendation"].update(reason="  "), "judgement_reason_missing"),
    (lambda r: r["recommendation"].update(basis="preference_within_bound"), "basis_evidence_source_disagree"),
])
def test_a_judgement_row_without_its_fields_is_refused(world, mutate, clause):
    row = _judged(TABLE_ROW)
    mutate(row)
    _set_row(world, row)
    res = d.dispatch(RID, apply=True)
    assert clause in res["detail"] and world["calls"] == []


def test_a_loosen_is_never_decided_here_but_by_each_accounts_risk_manager(world):
    """The row cannot express "loosen": a tighten_sl level that would loosen is
    passed through, and the apply's approve_amend refuses it per account
    (R_LOOSENS, tests/test_live_review_apply.py). Here: the refusal exit is
    reported, and since nothing was sent the review_id stays retryable."""
    world["rc"] = d.EXIT_REFUSED
    world["writeback"] = {"review_id": RID, "applied": False, "account_reads": [
        {"account_id": "bybit_2", "account_class": "bybit", "read": "refused_by_account_risk",
         "evidence": "approve_amend:refuse:would_loosen"}], "accounts_applied": [], "disposition": {}}
    res = d.dispatch(RID, apply=True)
    assert res["exit"] == d.EXIT_REFUSED and any("would_loosen" in ln for ln in res["accounts"])
    st = json.loads(d.DISPATCH_STATE.read_text())
    assert st["dispatched"][RID]["sent"] is False
    d.dispatch(RID, apply=True)
    assert len(world["calls"]) == 2


def test_a_row_not_on_main_yet_is_could_not_look(world):
    world["files"][d.REVIEWS_PATH] = json.dumps(dict(TABLE_ROW, review_id="LR-other")) + "\n"
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "could_not_look" and res["exit"] == d.EXIT_UNREADABLE and world["calls"] == []


def test_unreadable_reviews_file_is_could_not_look(world):
    world["files"].pop(d.REVIEWS_PATH)
    assert d.dispatch(RID, apply=True)["exit"] == d.EXIT_UNREADABLE


def test_uncommitted_evidence_is_refused(world):
    world["files"].pop(TABLE)
    res = d.dispatch(RID, apply=True)
    assert "evidence_not_committed" in res["detail"] and world["calls"] == []


# ------------------------------------------------------------------ idempotency + notification

def test_a_duplicate_review_id_after_an_apply_is_refused(world):
    world["writeback"] = APPLIED_WB
    assert d.dispatch(RID, apply=True)["exit"] == 0
    again = d.dispatch(RID, apply=True)
    assert again["verdict"] == "refused" and "duplicate_review_id" in again["detail"]
    assert len(world["calls"]) == 1


def test_an_apply_failed_counts_as_sent_and_is_not_redispatched(world):
    world["rc"] = d.EXIT_FAILED
    assert d.dispatch(RID, apply=True)["exit"] == d.EXIT_FAILED
    assert "duplicate_review_id" in d.dispatch(RID, apply=True)["detail"]
    assert len(world["calls"]) == 1


def test_could_not_look_inside_the_apply_is_retryable(world):
    world["rc"] = d.EXIT_UNREADABLE
    d.dispatch(RID, apply=True)
    d.dispatch(RID, apply=True)
    assert len(world["calls"]) == 2


def test_a_dry_run_never_blocks_a_later_apply(world):
    world["writeback"] = APPLIED_WB
    d.dispatch(RID, apply=False)
    assert d.dispatch(RID, apply=True)["exit"] == 0
    assert [c[-1] for c in world["calls"]] == ["--dry-run", "--apply"]


def test_a_money_row_refusal_pings_once_per_review_id(world):
    row = copy.deepcopy(TABLE_ROW)
    row["mechanics"]["verdict"] = "mismatch"
    _set_row(world, row)
    d.dispatch(RID, apply=True)
    d.dispatch(RID, apply=True)
    assert len(world["pings"]) == 1 and "mechanics_mismatch" in world["pings"][0]


def test_a_paper_only_refusal_does_not_ping(world):
    row = copy.deepcopy(TABLE_ROW)
    row["mechanics"]["verdict"] = "mismatch"
    for a in row["account_reads"]:
        a["account_class"] = "paper"
    _set_row(world, row)
    d.dispatch(RID, apply=True)
    assert world["pings"] == []


def test_a_dry_run_refusal_does_not_ping(world):
    row = copy.deepcopy(TABLE_ROW)
    row["recommendation"]["action"] = "hold"
    _set_row(world, row)
    d.dispatch(RID, apply=False)
    assert world["pings"] == []


# ------------------------------------------------------------------ contract with live_review_apply.py

def test_the_argv_matches_the_apply_scripts_parser_or_fails_closed(monkeypatch):
    """Built against PR #20259's interface. With #20259 merged, live_review_apply
    accepts every flag the dispatcher sends. Without it, argparse rejects the
    unknown flags (SystemExit 2) and nothing runs. Both are asserted, so merge
    order cannot produce a half-wired apply."""
    monkeypatch.setattr(lra, "_open_db", lambda: object())
    monkeypatch.setattr(lra, "_strategies", lambda: {})
    monkeypatch.setattr(lra, "_accounts", lambda: {})
    monkeypatch.setattr(lra, "_get_package", lambda db, pkg: None)   # no package -> nothing is touched
    for row in (TABLE_ROW, _judged(TABLE_ROW)):
        plan, refusal = d.check_row(row, MEASURED)
        assert refusal is None
        argv = d.apply_argv(plan, apply=False)
        src = open(lra.__file__).read()
        if '"--basis"' in src:
            assert lra.main(argv) == lra.EXIT_OK
        else:
            with pytest.raises(SystemExit) as e:
                lra.main(argv)
            assert e.value.code == 2


def test_the_action_wrapper_runs_the_dispatcher():
    text = open("scripts/ops/live_review_apply_action.sh").read()
    assert "scripts/ops/live_review_dispatch.py" in text
    assert 'ARGS+=(--apply)' in text and "ACTION_REVIEW_ID:?" in text
