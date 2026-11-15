"""Re-armed units are graded only on rows newer than the re-arm (2026-11-15 research-queue-grade incident).

`rearmed_at` (dispatch_queue, RESEARCH-FLOW 2026-11-02) disowns every row that landed before it: those rows came
from a defect that has since been fixed. The grader read them anyway for one-shot units (window None) and wrote a
needs_review grade on RQ-20261112-8d20-02 from the pre-fix row 43646720569. Planted/clean pair below.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.research import queue_grade as qg

UID = "RQ-20300101-003"


def _unit(rearmed: str | None) -> str:
    text = (f"id: {UID}\ntitle: 'one-shot unit'\nstatus: queued\ncadence: once\nkind: experiment\n"
            "theme: live_strategy\npriority: 3\nquestion: Does it clear?\n"
            "decision_rule:\n  id: RULE-Y\n  statistic: delta net_R\n  rule: PASS iff it clears\n"
            "  registered_at: '2030-01-01'\n  registered_before_run: true\n"
            "run:\n  workflow: some.yml\n  inputs:\n    legs: leg_y\n"
            "lands:\n  store: research/results/\n  min_rows: 1\n"
            "generated:\n  family: fam\n  key: fam:leg=leg_y\n")
    if rearmed:
        text += f"rearmed_at: '{rearmed}'\n"
    return text + "last_dispatched_at: '2030-01-02T07:54:00+00:00'\n"


def _row(root: Path, name: str, at: str, rs: str = "not_attempted", verdict=None) -> None:
    d = root / "research" / "results" / UID
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jsonl").write_text(json.dumps({"verdict": verdict, "read_state": rs, "generated_at": at,
                                                 "measurement": {}}) + "\n")


def test_pre_rearm_row_is_not_graded(tmp_path):
    (tmp_path / "research" / "queue").mkdir(parents=True)
    _row(tmp_path, "old", "2030-01-01T23:00:00Z")                       # landed before the fix
    # clean control: without a re-arm the same row IS read (and lands a needs_review grade)
    plain = qg.grade_unit_full(tmp_path, UID, _unit(None), "2030-01-02")
    assert plain is not None and yaml.safe_load(plain[0])["grading"].get("needs_review") is True
    # planted: re-armed after that row -> the row is disowned, nothing is graded
    assert qg.grade_unit_full(tmp_path, UID, _unit("2030-01-02T02:30:00+00:00"), "2030-01-02") is None


def test_post_rearm_row_is_graded(tmp_path):
    (tmp_path / "research" / "queue").mkdir(parents=True)
    _row(tmp_path, "old", "2030-01-01T23:00:00Z")
    _row(tmp_path, "new", "2030-01-02T09:00:00Z", rs="measured", verdict="fail")
    res = qg.grade_unit_full(tmp_path, UID, _unit("2030-01-02T02:30:00+00:00"), "2030-01-02")
    assert res is not None
    g = yaml.safe_load(res[0])["grading"]
    assert g["evidence"] == ["research/results/RQ-20300101-003/new.jsonl"] and g.get("needs_review") is not True
