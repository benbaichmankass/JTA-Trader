"""queue_grade under the pre-registered holdout (operator decision 2026-10-16, "Holdout re-run").

Planted/clean pairs:
  * an m20 PASS that did NOT hold out opens one holdout RE-RUN that dispatches now (no not_before);
    a PASS whose rows already carry a holdout confirmation opens nothing;
  * holdout confirmed -> `confirmed`; holdout fail / not re-discovered -> `not_replicated`
    (closes the configuration, never the family); underpowered -> `underpowered`;
  * an existing confirmation for the PASS is reused, never duplicated;
  * a forward-wait confirmation that never fired is retired as superseded by a live holdout
    re-run of the same PASS, and left alone when there is none; --verify reproduces the retirement.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from scripts.research import queue_grade as qg

PID = "RQ-20300101-001"


def _parent(cadence="once"):
    return (f"id: {PID}\ntitle: 'M20 sweep: leg_x'\nstatus: queued\ncadence: {cadence}\nkind: experiment\n"
            "theme: live_strategy\npriority: 3\nquestion: Does a lever clear the gate on leg_x?\n"
            "power:\n  expected_n: 25\n"
            "decision_rule:\n  id: RULE-X\n  statistic: per cell delta\n  rule: PASS iff a cell clears\n"
            "  registered_at: '2030-01-01'\n  registered_before_run: true\n"
            f"run:\n  workflow: m20-exit-lever-sweep.yml\n  inputs:\n    legs: leg_x\n    research_unit: {PID}\n"
            "lands:\n  store: research/results/\n  min_rows: 1\n"
            "generated:\n  family: m20-exit-lever\n  key: m20-exit-lever:leg=leg_x\n"
            "last_dispatched_at: '2030-01-01T00:00:00+00:00'\n")


def _rows(r: Path, uid: str, verdict: str, holdout=None, cells=("c1",)):
    d = r / "research" / "results" / uid
    d.mkdir(parents=True, exist_ok=True)
    m = {"cells_swept": 17, "passing_cells": list(cells) if verdict == "pass" else []}
    if holdout:
        m["holdout"] = {"boundary": "2029-06-01", "share_used": 0.25, "state": "ok", "base_trades": 40,
                        "selected_from": 17, "confirmation": holdout, "confirmed_cells": ["c1"] if holdout == "confirmed" else []}
    (d / "1.jsonl").write_text(json.dumps({"verdict": verdict, "read_state": "measured",
                                           "generated_at": "2030-01-01T06:00:00Z", "measurement": m}) + "\n")


def _repo(tmp_path):
    (tmp_path / "research" / "queue").mkdir(parents=True)
    return tmp_path


def test_pass_without_holdout_opens_a_holdout_rerun_that_dispatches_now(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    parent_text, (cid, ctext) = qg.grade_unit_full(r, PID, _parent(), "2030-01-02")
    cu = yaml.safe_load(ctext)
    assert cu["status"] == "queued" and "not_before" not in cu
    assert cu["confirmation"]["mode"] == "holdout_rerun" and cu["confirmation"]["of"] == PID
    assert cu["run"]["inputs"]["holdout_frac"] == "0.25" and cu["run"]["inputs"]["research_unit"] == cid
    assert "Holdout re-run" in cu["confirmation"]["policy"]
    assert yaml.safe_load(parent_text)["grading"]["confirm_unit"] == cid


def test_pass_whose_run_held_out_opens_nothing(tmp_path):
    r = _repo(tmp_path)
    for conf, want in (("confirmed", "confirmed"), ("not_replicated", "not_replicated"),
                       ("underpowered", "underpowered")):
        _rows(r, PID, "pass", holdout=conf)
        res = qg.grade_unit_full(r, PID, _parent(), "2030-01-02")
        g = yaml.safe_load(res[0])["grading"]
        assert res[1] is None and g["confirmation"] == want and g["discovery"] == want, (conf, g)
        assert "confirm_unit" not in g


def test_holdout_rerun_child_grades_confirmed_or_not_replicated(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    _p, (cid, ctext) = qg.grade_unit_full(r, PID, _parent(), "2030-01-02")
    ran = ctext.replace("status: queued", "status: queued\nlast_dispatched_at: '2030-01-03T00:00:00+00:00'")
    for verdict, hconf, want in (("pass", "confirmed", "confirmed"), ("pass", "not_replicated", "not_replicated"),
                                 ("no_action_warranted", "no_discovery", "not_replicated"),
                                 ("pass", "underpowered", "underpowered")):
        _rows(r, cid, verdict, holdout=hconf)
        u = yaml.safe_load(qg.grade_unit(r, cid, ran, "2030-01-04"))
        assert u["status"] == "done" and u["grading"]["confirmation"] == want and u["grading"]["confirms"] == PID, \
            (verdict, hconf, u["grading"])
        if want == "not_replicated":
            assert "never the family" in u["grading"]["note"]


def test_existing_confirmation_is_reused_not_duplicated(tmp_path):
    r = _repo(tmp_path)
    _rows(r, PID, "pass")
    existing = qg.confirmation_unit(yaml.safe_load(_parent()), {"cells_swept": 17, "passing_cells": ["c1"]},
                                    "RQ-20300101-abcd-01")
    (r / "research" / "queue" / "RQ-20300101-abcd-01.yaml").write_text(existing)
    res = qg.grade_unit_full(r, PID, _parent(), "2030-01-02")
    assert res[1] is None and yaml.safe_load(res[0])["grading"]["confirm_unit"] == "RQ-20300101-abcd-01"


def _forward_unit(uid="RQ-20300101-f0f0-01"):
    return (f"id: {uid}\ntitle: fw\nstatus: queued\ncadence: once\ntheme: live_strategy\npriority: 3\n"
            "question: q\nrun:\n  workflow: m20-exit-lever-sweep.yml\nlands:\n  store: research/results/\n"
            f"requires_result:\n  unit: {PID}\n  verdict: pass\nnot_before: '2030-03-01T00:00:00+00:00'\n"
            f"confirmation:\n  of: {PID}\n  window:\n    mode: most_recent_disjoint\n    wait_days: 60\n"
            "grading:\n  auto: true\n")


def test_forward_wait_superseded_by_a_holdout_rerun_and_left_alone_without_one(tmp_path):
    r = _repo(tmp_path)
    fw = _forward_unit()
    (r / "research" / "queue" / "RQ-20300101-f0f0-01.yaml").write_text(fw)
    assert qg.grade_unit_full(r, "RQ-20300101-f0f0-01", fw, "2030-01-02") is None      # clean: nothing supersedes it
    h = qg.confirmation_unit(yaml.safe_load(_parent()), {"cells_swept": 17}, "RQ-20300101-abcd-01")
    (r / "research" / "queue" / "RQ-20300101-abcd-01.yaml").write_text(h)
    new, child = qg.grade_unit_full(r, "RQ-20300101-f0f0-01", fw, "2030-01-02")        # planted: superseded
    u = yaml.safe_load(new)
    assert child is None and u["status"] == "retired" and u["grading"]["superseded_by"] == "RQ-20300101-abcd-01"
    # a forward unit that already FIRED is never retired under it
    fired = fw.replace("grading:", "last_dispatched_at: '2030-01-01T00:00:00+00:00'\ngrading:")
    assert qg._superseded_by(r, yaml.safe_load(fired)) is None


def _git(r, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(r), check=True, capture_output=True)


def test_verify_reproduces_a_supersede(tmp_path):
    r = _repo(tmp_path)
    q = r / "research" / "queue"
    (q / "RQ-20300101-f0f0-01.yaml").write_text(_forward_unit())
    (q / "RQ-20300101-abcd-01.yaml").write_text(
        qg.confirmation_unit(yaml.safe_load(_parent()), {"cells_swept": 17}, "RQ-20300101-abcd-01"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "checkout", "-q", "-b", "g")
    res = qg.run(r, graded_at="2030-01-02", write=True)
    assert [c["id"] for c in res["changed"]] == ["RQ-20300101-f0f0-01"]
    _git(r, "commit", "-q", "-am", "grade")
    assert qg.verify(r, "main") == []
