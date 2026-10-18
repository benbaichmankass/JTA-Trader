"""RESEARCH-CONFIRM-FRESH-WINDOW (operator decision 2026-10-16, popup "Yes, adopt").

(a) A single-window PASS on a template cell is a discovery: the grader opens EXACTLY ONE fresh-window
    confirmation unit (a window the PASS did not see) whose note names how many cells the PASS was
    selected from, and the cell may not feed a Tier-3 proposal until that unit CONFIRMS.
(b) A deterministic template cell's first FAIL closes without the same-window replay; a
    non-deterministic one (declared seeds / ml_bakeoff / grading.confirm_fail) keeps it.

Every rule is tested as a planted/clean pair.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from scripts.ops import roadmap_map
from scripts.research import dispatch_queue as dq
from scripts.research import queue_grade as qg

PID = "RQ-20300101-001"
PASS_AT = "2030-01-01T06:00:00Z"
FW = "fw-sweep.yml"   # a stub workflow with a fresh-window input and NO holdout input


@pytest.fixture(autouse=True)
def _forward_window_workflow(monkeypatch):
    monkeypatch.setitem(qg._FRESH_WINDOW_INPUTS, FW,
                        lambda after: {"split_mode": "date", "split": after.date().isoformat()})


def _unit(*, workflow: str = "m20-exit-lever-sweep.yml", cadence: str = "once", family: str = "m20-exit-lever",
          extra: str = "") -> str:
    return (f"id: {PID}\ntitle: 'M20 sweep: leg_x'\nstatus: queued\ncadence: {cadence}\nkind: experiment\n"
            "theme: live_strategy\npriority: 3\nquestion: Does a lever clear the gate on leg_x?\n"
            "decision_rule:\n  id: RULE-X\n  statistic: per cell delta net_R\n  rule: PASS iff a cell clears\n"
            "  registered_at: '2030-01-01'\n  registered_before_run: true\n"
            f"run:\n  workflow: {workflow}\n  inputs:\n    legs: leg_x\n    split_mode: oos-trades\n"
            f"    research_unit: {PID}\n"
            "lands:\n  store: research/results/\n  min_rows: 1\n"
            f"generated:\n  family: {family}\n  key: {family}:leg=leg_x\n"
            f"{extra}last_dispatched_at: '2030-01-01T00:00:00+00:00'\n")


def _rows(root: Path, uid: str, verdict: str, cells=("c1",), swept: int = 17, at: str = PASS_AT,
          **measurement) -> None:
    d = root / "research" / "results" / uid
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.jsonl").write_text(json.dumps({
        "verdict": verdict, "read_state": "measured", "generated_at": at,
        "measurement": {"cells_swept": swept, "passing_cells": list(cells) if verdict == "pass" else [],
                        **measurement}}) + "\n")


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "research" / "queue").mkdir(parents=True)
    return tmp_path


# ── (a) a PASS opens exactly one fresh-window confirmation ──────────────────────────────────────
def test_template_pass_spawns_exactly_one_disjoint_window_confirmation(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    res = qg.grade_unit_full(r, PID, _unit(workflow=FW), "2030-01-02")
    assert res is not None
    parent_text, child = res
    parent = yaml.safe_load(parent_text)
    assert parent["status"] == "done"
    g = parent["grading"]
    assert g["verdict"] == "pass" and g["discovery"] == "unconfirmed" and g["selected_from_cells"] == 17
    assert child is not None and g["confirm_unit"] == child[0] == qg.confirm_unit_id(PID, "2030-01-02")
    cu = yaml.safe_load(child[1])
    assert cu["status"] == "queued" and cu["cadence"] == "once"
    assert cu["requires_result"] == {"unit": PID, "verdict": "pass"}
    # disjoint window: OOS starts at the PASS run's data end, and it cannot fire before data accrues
    assert cu["run"]["inputs"]["split_mode"] == "date" and cu["run"]["inputs"]["split"] == "2030-01-01"
    assert cu["confirmation"]["mode"] == "forward_wait"
    assert cu["run"]["inputs"]["research_unit"] == cu["id"]
    assert datetime.fromisoformat(cu["not_before"]) > datetime(2030, 1, 1, 6, tzinfo=timezone.utc)
    assert cu["confirmation"]["of"] == PID and cu["confirmation"]["selected_from_cells"] == 17
    assert "17 cell(s)" in cu["confirmation"]["note"]
    # same pre-registered rule, unchanged
    assert cu["decision_rule"] == yaml.safe_load(_unit())["decision_rule"]
    assert "generated" not in cu and "last_dispatched_at" not in cu and cu["grading"] == {"auto": True}
    # exactly one: the closed parent is never graded again
    assert qg.grade_unit_full(r, PID, parent_text, "2030-01-03") is None


def test_forward_wait_is_sized_per_leg_from_its_trade_rate(tmp_path):
    """A flat wait could not reach the floor for any of the 13 m20 PASSes (PI-20261016-QOTFUEXV-0003)."""
    r = _repo(tmp_path)
    # 50 OOS trades over the 500 days from split to PASS = 0.1/day -> 25 trades need 250 days
    _rows(r, PID, "pass", base_trades_OOS=50, split="2028-08-20")
    _p, child = qg.grade_unit_full(r, PID, _unit(workflow=FW), "2030-01-02")
    w = yaml.safe_load(child[1])["confirmation"]["window"]
    assert 245 <= w["wait_days"] <= 255 and "measured" in w["wait_basis"], w
    _rows(r, PID, "pass")                                  # no rate reported -> flat fallback, said so
    _p, child = qg.grade_unit_full(r, PID, _unit(workflow=FW), "2030-01-02")
    w = yaml.safe_load(child[1])["confirmation"]["window"]
    assert w["wait_days"] == qg.CONFIRM_WAIT_DAYS and "fallback" in w["wait_basis"]


def test_recurring_template_pass_reuses_its_one_confirmation(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    first = qg.grade_unit_full(r, PID, _unit(cadence="monthly", workflow=FW), "2030-01-02")
    assert first and first[1] is not None and yaml.safe_load(first[0])["status"] == "queued"
    # next month's PASS: the confirmation already exists -> carried forward, NOT a second one
    _rows(r, PID, "pass", at="2030-02-01T06:00:00Z")
    again = qg.grade_unit_full(r, PID, first[0].replace("2030-01-01T00:00:00+00:00", "2030-02-01T00:00:00+00:00"),
                               "2030-02-02")
    assert again is not None and again[1] is None
    assert yaml.safe_load(again[0])["grading"]["confirm_unit"] == first[1][0]


def test_workflow_without_a_window_input_gets_a_blocked_confirmation_not_a_same_window_rerun(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    _parent, child = qg.grade_unit_full(r, PID, _unit(workflow="research-script-run.yml"), "2030-01-02")
    cu = yaml.safe_load(child[1])
    assert cu["status"] == "blocked" and "no input that confines" in cu["blocked_reason"]
    assert cu["run"]["inputs"]["split_mode"] == "oos-trades"      # untouched: nothing claims a fresh window


def test_non_template_pass_opens_nothing(tmp_path):
    """Clean side of (a): a programme node (its DAG owns confirmation) and a hand opt-in unit."""
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    prog = qg.grade_unit_full(r, PID, _unit(family="programme:P3"), "2030-01-02")
    assert prog and prog[1] is None and "confirm_unit" not in yaml.safe_load(prog[0])["grading"]
    hand = _unit().replace("generated:\n  family: m20-exit-lever\n  key: m20-exit-lever:leg=leg_x\n",
                           "grading:\n  auto: true\n")
    res = qg.grade_unit_full(r, PID, hand, "2030-01-02")
    assert res and res[1] is None


# ── grading the confirmation itself ─────────────────────────────────────────────────────────────
def _child(r: Path) -> tuple:
    _rows(r, PID, "pass")
    _p, (cid, text) = qg.grade_unit_full(r, PID, _unit(workflow=FW), "2030-01-02")
    return cid, text.replace("status: queued", "status: queued\nlast_dispatched_at: '2030-03-05T00:00:00+00:00'")


def test_confirmation_pass_on_the_same_cell_confirms(tmp_path):
    r = _repo(tmp_path)
    cid, text = _child(r)
    _rows(r, cid, "pass", cells=("c1", "c9"), at="2030-03-05T06:00:00Z")
    g = yaml.safe_load(qg.grade_unit(r, cid, text, "2030-03-06"))
    assert g["status"] == "done" and g["grading"]["confirmation"] == "confirmed" and g["grading"]["confirms"] == PID


def test_confirmation_pass_on_other_cells_is_a_new_discovery_not_a_confirmation(tmp_path):
    r = _repo(tmp_path)
    cid, text = _child(r)
    _rows(r, cid, "pass", cells=("c9",), at="2030-03-05T06:00:00Z")
    res = qg.grade_unit_full(r, cid, text, "2030-03-06")
    u = yaml.safe_load(res[0])
    assert u["status"] == "queued" and u["grading"]["needs_review"] and res[1] is None


def test_confirmation_fail_closes_not_replicated_without_replay(tmp_path):
    r = _repo(tmp_path)
    cid, text = _child(r)
    _rows(r, cid, "fail", at="2030-03-05T06:00:00Z")
    new = qg.grade_unit(r, cid, text, "2030-03-06")
    u = yaml.safe_load(new)
    assert u["status"] == "done" and u["grading"]["confirmation"] == "not_replicated"
    assert "last_dispatched_at: null" not in new


# ── (b) no same-window replay of a deterministic FAIL ───────────────────────────────────────────
def test_deterministic_template_fail_closes_without_replay(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "fail")
    new = qg.grade_unit(r, PID, _unit(), "2030-01-02")
    u = yaml.safe_load(new)
    assert u["status"] == "done" and u["grading"]["verdict"] == "fail"
    assert u["last_dispatched_at"] and "confirmatory_run" not in u["grading"]
    assert "family-retirement" in u["grading"]["note"]


def test_non_deterministic_template_fail_keeps_its_replay(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "fail")
    for extra in ("n_seeds: 5\n", "ml_bakeoff:\n  family: f\n"):
        u = yaml.safe_load(qg.grade_unit(r, PID, _unit(extra=extra), "2030-01-02"))
        assert u["status"] == "queued" and u["last_dispatched_at"] is None and u["grading"]["confirmatory_run"] == 1


# ── dispatcher honours not_before ───────────────────────────────────────────────────────────────
def test_dispatcher_waits_for_not_before():
    e = {"id": "RQ-20300101-abcd-01", "status": "queued", "cadence": "once", "not_before": "2030-03-02T00:00:00+00:00",
         "run": {"workflow": "x.yml"}}
    due, why = dq._is_due(e, datetime(2030, 3, 1, tzinfo=timezone.utc))
    assert not due and "not_before" in why
    due, why = dq._is_due({**e, "not_before": "soon"}, datetime(2030, 3, 1, tzinfo=timezone.utc))
    assert not due and "unparseable" in why
    due, why = dq._is_due(e, datetime(2030, 3, 3, tzinfo=timezone.utc))
    assert "not_before" not in why


# ── E58 --verify: the added confirmation reproduces; anything else added does not ───────────────
def _git(r: Path, *a: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(r), check=True, capture_output=True)


def test_verify_vouches_the_spawned_confirmation_and_refuses_a_tampered_one(tmp_path):
    r = _repo(tmp_path)
    (r / "research" / "queue" / f"{PID}.yaml").write_text(_unit())   # m20 -> a holdout re-run child
    _rows(r, PID, "pass")
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "checkout", "-q", "-b", "g")
    res = qg.run(r, graded_at="2030-01-02", write=True)
    assert len(res["spawned"]) == 1
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "grade")
    assert qg.verify(r, "main") == []
    child = r / "research" / "queue" / f"{res['spawned'][0]['id']}.yaml"
    child.write_text(child.read_text().replace("holdout_frac: '0.25'", "holdout_frac: '0.05'"))
    _git(r, "commit", "-q", "-am", "tamper")
    assert any("does not reproduce as its parent's confirmation" in p for p in qg.verify(r, "main"))
    _git(r, "checkout", "-q", "HEAD~1")
    (r / "research" / "queue" / "RQ-20300101-999.yaml").write_text("id: RQ-20300101-999\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "smuggle")
    assert any("not the confirmation unit" in p for p in qg.verify(r, "main"))
    _git(r, "rm", "-q", str(child))
    _git(r, "commit", "-q", "-m", "drop child")
    assert any("does not add it" in p for p in qg.verify(r, "main"))


# ── roadmap-map-guard: an authored confirmation unit must pass it (manager, 2026-10-16, #18611) ──
def _guard_problems(units: dict) -> list:
    spec = {"enforce_units_from": "20000101"}
    return [p for p in roadmap_map.diff_problems(spec, {}, {}, units, {}, {}) if "roadmap" in p]


def test_authored_confirmation_unit_passes_the_roadmap_guard(tmp_path):
    """Clean: the unit inherits the family's milestone (queue_replenish.FAMILY_ROADMAP)."""
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    _p, (cid, text) = qg.grade_unit_full(r, PID, _unit(workflow=FW), "2030-01-02")
    cu = yaml.safe_load(text)
    assert cu["roadmap"] == ["M20"]
    assert _guard_problems({cid: cu}) == []
    # the parent's own ref wins over the family map
    own = _unit(workflow=FW).replace("lands:", "roadmap:\n- L-ATM\nlands:")
    _p, (_cid2, text2) = qg.grade_unit_full(r, PID, own, "2030-01-02")
    assert yaml.safe_load(text2)["roadmap"] == ["L-ATM"]


def test_no_milestone_means_no_unit_and_needs_review(tmp_path):
    """Planted: a unit the guard would refuse (no roadmap, unknown family) is never authored."""
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    bare = _unit(workflow=FW, family="no-such-family")
    assert _guard_problems({"RQ-20300101-abcd-01": {"id": "x"}})   # the guard does refuse a unit without one
    parent_text, child = qg.grade_unit_full(r, PID, bare, "2030-01-02")
    g = yaml.safe_load(parent_text)["grading"]
    assert child is None and g["needs_review"] and "roadmap" in g["note"] and "confirm_unit" not in g


def test_m20_pass_authors_a_holdout_rerun_not_a_forward_wait_and_it_passes_the_guard(tmp_path):
    """Operator 2026-10-16 'Holdout re-run': an m20 PASS gets a holdout re-run (no wait), and that
    unit carries the family milestone, so roadmap-map-guard accepts it."""
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    _parent, (cid, text) = qg.grade_unit_full(r, PID, _unit(), "2030-01-02")
    cu = yaml.safe_load(text)
    assert cu["confirmation"]["mode"] == "holdout_rerun" and "not_before" not in cu
    assert cu["roadmap"] == ["M20"] and _guard_problems({cid: cu}) == []
