"""PI-20261118-JFWRQYOV-0001: the research dispatcher re-arms itself.

MEASURED 2026-11-18: the workflow_run REFILL never fires for runs the dispatcher starts (they are created by
github-actions[bot] through GITHUB_TOKEN), and schedule-keeper only runs on a push to main, so cycles were hours apart
and each fired ~5 short units. The `rearm` job is the heartbeat that depends on neither. These tests pin its shape.
"""
from __future__ import annotations

from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "research-queue-dispatch.yml"


def _wf():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_rearm_job_follows_dispatch_and_has_no_shared_group():
    job = _wf()["jobs"]["rearm"]
    assert job["needs"] == ["dispatch"]
    # no `concurrency:` on purpose: it must not hold the dispatch group while it sleeps
    assert "concurrency" not in job
    assert job["permissions"]["actions"] == "write"
    assert job["runs-on"] == "ubuntu-latest"  # B13: research never lands on the ops pool


def test_rearm_runs_after_a_failed_cycle_but_not_after_a_skipped_or_cancelled_one():
    cond = _wf()["jobs"]["rearm"]["if"]
    assert "always()" in cond
    assert "needs.dispatch.result != 'skipped'" in cond
    assert "needs.dispatch.result != 'cancelled'" in cond


def test_rearm_redispatches_this_workflow_on_main_and_does_not_count_an_open_previous_cycle():
    text = "\n".join(s.get("run", "") for s in _wf()["jobs"]["rearm"]["steps"])
    assert "gh workflow run research-queue-dispatch.yml --ref main" in text
    # an in_progress run is the previous cycle's land job: counting it would end the chain after one hop
    jq = next(ln for ln in text.splitlines() if 'select(.status=="queued"' in ln)
    assert "in_progress" not in jq
    # short wait with work left, long heartbeat wait without
    assert "wait_s=150" in text and "wait_s=1800" in text


def test_dispatch_job_exports_the_summary_counts_the_rearm_reads():
    wf = _wf()
    outs = wf["jobs"]["dispatch"]["outputs"]
    assert "dispatched" in outs and "deferred" in outs
    flag = next(s for s in wf["jobs"]["dispatch"]["steps"] if s.get("id") == "flag")
    assert "dispatched=" in flag["run"] and "deferred=" in flag["run"]


def test_a_bot_dispatch_still_fires():
    """The re-armed run is a workflow_dispatch by the bot; the fire gate must keep treating that as FIRE."""
    env = _wf()["jobs"]["dispatch"]["env"]["FIRE"]
    assert "github.actor == 'github-actions[bot]'" in env
