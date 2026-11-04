"""CI-STREAMLINE (2026-11-03): a red SCHEDULED backstop of main still reaches the due list.

pytest-run and guards lost their push-to-main triggers; their post-merge grading of main is a scheduled run.
`src_red_main_runs` must read it, or removing the push runs would have silenced the main-is-red alarm.
"""
from __future__ import annotations

import datetime
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))
R = pytest.importorskip("render_due_list")


def _stub(monkeypatch, push_runs, sched):
    def fake(path, *a, **k):
        if "/commits?" in path:
            return []
        for wf, runs in sched.items():
            if f"/workflows/{wf}/runs" in path:
                return {"workflow_runs": runs}
        return {"workflow_runs": push_runs}
    monkeypatch.setattr(R, "_gh", fake)


def _run(name, conclusion, created, event="schedule"):
    return {"name": name, "status": "completed", "conclusion": conclusion, "event": event,
            "head_sha": "a" * 40, "created_at": created, "html_url": "u"}


def test_red_scheduled_guards_backstop_is_a_row(monkeypatch):
    _stub(monkeypatch, [], {"guards.yml": [_run("Guards", "failure", "2026-11-04T02:29:00Z")], "pytest-run.yml": []})
    res = R.src_red_main_runs(REPO, datetime.date.today(), token="t")
    assert res.state == "read"
    assert any("Guards" in str(r) for r in res.rows), res.rows


def test_a_newer_green_backstop_supersedes_an_old_red_push_run(monkeypatch):
    _stub(monkeypatch, [_run("pytest-run", "failure", "2026-11-03T20:00:00Z", event="push")],
          {"pytest-run.yml": [_run("pytest-run", "success", "2026-11-04T02:13:00Z")], "guards.yml": []})
    res = R.src_red_main_runs(REPO, datetime.date.today(), token="t")
    assert not any("pytest-run" in str(r) for r in res.rows), res.rows


def test_the_backstops_are_the_two_scheduled_post_merge_checks():
    assert set(R.BACKSTOP_WORKFLOWS) == {"pytest-run.yml", "guards.yml"}


def test_a_keeper_dispatched_backstop_counts_and_pr_runs_do_not(monkeypatch):
    runs = [_run("Guards", "success", "2026-11-04T05:00:00Z", event="pull_request"),
            _run("Guards", "failure", "2026-11-04T04:29:00Z", event="workflow_dispatch")]
    _stub(monkeypatch, [], {"guards.yml": runs, "pytest-run.yml": []})
    res = R.src_red_main_runs(REPO, datetime.date.today(), token="t")
    assert any("Guards" in str(r) for r in res.rows), res.rows
