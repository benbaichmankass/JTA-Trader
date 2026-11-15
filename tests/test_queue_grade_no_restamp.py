"""AUD-20261019-RESEARCH-SLO-RED (2026-11-12): a re-grade that changes nothing but the date is not written.

The daily mechanical grade re-stamped `grading.graded_at` on ~200 unchanged units (#25060: 196 files), which made
research_slo's grade_latency_p90_d read a same-day grading as 6 d late and inflated every graded_at window.
Planted/clean pair: an unchanged re-grade returns None (stamp kept); a new result row re-grades with the new date.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.research import queue_grade as qg

UID = "RQ-20300101-002"


def _unit() -> str:
    return (f"id: {UID}\ntitle: 'weekly leg_x walk-forward'\nstatus: queued\ncadence: weekly\nkind: experiment\n"
            "theme: live_strategy\npriority: 3\nquestion: Does leg_x clear the gate?\n"
            "decision_rule:\n  id: RULE-X\n  statistic: delta net_R\n  rule: PASS iff it clears\n"
            "  registered_at: '2030-01-01'\n  registered_before_run: true\n"
            "run:\n  workflow: some.yml\n  inputs:\n    legs: leg_x\n"
            "lands:\n  store: research/results/\n  min_rows: 1\n"
            "generated:\n  family: fam\n  key: fam:leg=leg_x\n"
            "last_dispatched_at: '2030-01-01T00:00:00+00:00'\n")


def _row(root: Path, name: str, at: str) -> None:
    d = root / "research" / "results" / UID
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jsonl").write_text(json.dumps({"verdict": "fail", "read_state": "measured", "generated_at": at,
                                                 "measurement": {}}) + "\n")


def test_unchanged_regrade_keeps_the_original_stamp(tmp_path):
    (tmp_path / "research" / "queue").mkdir(parents=True)
    _row(tmp_path, "1", "2030-01-01T06:00:00Z")
    first = qg.grade_unit_full(tmp_path, UID, _unit(), "2030-01-01")
    assert first is not None
    text = first[0]
    assert yaml.safe_load(text)["grading"]["graded_at"] == "2030-01-01"
    # planted: the next day's pass sees the same rows -> nothing to write, the stamp stays 2030-01-01
    assert qg.grade_unit_full(tmp_path, UID, text, "2030-01-02") is None
    # clean: a new result row is a new grading, stamped the day it is read
    _row(tmp_path, "2", "2030-01-08T06:00:00Z")
    again = qg.grade_unit_full(tmp_path, UID, text, "2030-01-08")
    assert again is not None and yaml.safe_load(again[0])["grading"]["graded_at"] == "2030-01-08"


def test_recurring_hand_written_unit_with_self_attesting_rows_is_graded(tmp_path):
    """A hand-written daily unit whose rows all carry its own rule id is graded (it was never read before);
    a row with another rule id leaves it with a session."""
    (tmp_path / "research" / "queue").mkdir(parents=True)
    text = _unit().replace("generated:\n  family: fam\n  key: fam:leg=leg_x\n", "").replace("cadence: weekly", "cadence: daily")
    d = tmp_path / "research" / "results" / UID
    d.mkdir(parents=True)
    row = {"verdict": "pass", "read_state": "measured", "generated_at": "2030-01-01T06:00:00Z",
           "decision_rule": {"id": "RULE-X"}, "measurement": {}}
    (d / "1.jsonl").write_text(json.dumps(row) + "\n")
    res = qg.grade_unit_full(tmp_path, UID, text, "2030-01-01")
    assert res is not None
    u = yaml.safe_load(res[0])
    assert u["status"] == "queued" and u["grading"]["verdict"] == "pass" and u["grading"]["attested"] == "RULE-X"
    (d / "1.jsonl").write_text(json.dumps({**row, "decision_rule": {"id": "RULE-GENERIC"}}) + "\n")
    assert qg.grade_unit_full(tmp_path, UID, text, "2030-01-01") is None
