"""REFILL (2026-11-03): a finished research run asks for a dispatch cycle, and a recent run is evidence of dispatch.

Pins: (1) the run-name carries the unit id on every research-script-run workflow; (2) fired_run_units/unit_pending_by_run
close the gap between a fire and its stamp PR / result row, so a faster cadence cannot double-fire; (3) the workflow_run
trigger lists only the research-script-run family (never the dispatcher itself: no loop), shares the ONE FIRE decision,
and is rate-limited by the `gap` step. No new gate: nothing here changes a cap, the infra yield or what may trade."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "research"))
import dispatch_queue as dq

WF = ROOT / ".github" / "workflows"
FAMILY = ["research-script-run", "research-script-run-data", "research-script-run-kaggle",
          "research-script-run-kaggle-cpu", "research-script-run-trainer"]
NOW = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)


def _wf(name):
    return yaml.safe_load((WF / f"{name}.yml").read_text())


@pytest.mark.parametrize("name", FAMILY)
def test_every_research_run_names_its_unit(name):
    rn = _wf(name).get("run-name", "")
    assert "inputs.research_unit" in rn, f"{name}: in-flight runs would not expose their unit"


def _api(runs_by_file):
    def api(path):
        for f, runs in runs_by_file.items():
            if f"/{f}/runs" in path:
                return None if runs is None else {"workflow_runs": runs}
        return {"workflow_runs": []}
    return api


def test_fired_run_units_takes_the_newest_run_per_unit():
    def t(m):
        return (NOW - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")

    api = _api({"research-script-run.yml": [
        {"display_title": "research-script-run RQ-20261102-5e03-01", "created_at": t(30)},
        {"display_title": "research-script-run RQ-20261102-5e03-01", "created_at": t(5)},
        {"display_title": "research-script-run RQ-20261025-005", "created_at": t(90)},
        {"display_title": "some unrelated title", "created_at": t(1)}]})
    out = dq.fired_run_units(NOW, api)
    assert set(out) == {"RQ-20261102-5e03-01", "RQ-20261025-005"}
    assert out["RQ-20261102-5e03-01"] == NOW - timedelta(minutes=5)


def test_an_unreadable_run_list_is_none_not_empty():
    assert dq.fired_run_units(NOW, _api({"research-script-run-kaggle.yml": None})) is None


def test_a_run_newer_than_stamp_and_result_marks_the_unit_pending():
    run = NOW - timedelta(minutes=5)
    assert dq.unit_pending_by_run({"last_dispatched_at": None}, run, None)
    assert dq.unit_pending_by_run({"last_dispatched_at": (NOW - timedelta(hours=2)).isoformat()}, run, None)


def test_a_stamp_or_result_at_or_after_the_run_hands_the_unit_back_to_its_cadence():
    run = NOW - timedelta(minutes=5)
    assert not dq.unit_pending_by_run({"last_dispatched_at": (run + timedelta(seconds=1)).isoformat()}, run, None)
    assert not dq.unit_pending_by_run({"last_dispatched_at": None}, run, run)
    assert not dq.unit_pending_by_run({"last_dispatched_at": None}, None, None)


def test_workflow_run_trigger_lists_only_the_research_run_family():
    on = _wf("research-queue-dispatch")[True]
    wr = on["workflow_run"]
    assert sorted(wr["workflows"]) == sorted(FAMILY)
    assert "research-queue-dispatch" not in wr["workflows"], "the dispatcher must not trigger itself"
    assert wr["types"] == ["completed"]


def test_the_fire_decision_still_lives_in_one_env_and_admits_workflow_run():
    d = _wf("research-queue-dispatch")["jobs"]["dispatch"]
    assert "workflow_run" in d["env"]["FIRE"]
    assert "workflow_run" in d["if"]
    assert d["concurrency"]["group"] == "research-queue-dispatch"


def test_a_workflow_run_cycle_is_rate_limited_by_a_gap_step():
    j = _wf("research-queue-dispatch")["jobs"]["dedupe"]
    assert "workflow_run" in j["if"]
    gap = [s for s in j["steps"] if s.get("id") == "gap"]
    assert len(gap) == 1 and gap[0]["if"] == "github.event_name == 'workflow_run'"
    assert "600" in gap[0]["run"], "10-minute floor between cycles"
    assert "steps.gap.outputs.skip" in j["outputs"]["skip"]
