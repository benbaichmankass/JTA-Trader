"""RESEARCH-WATCHDOG: every check, the could-not-look path of each, self-heal-once, dedupe, resolve."""
import json

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.research import research_watchdog as w

NOW = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
CFG = w.load_config()
TH = CFG["thresholds"]


def ago(m):
    return (NOW - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(i, m, status="completed"):
    return {"id": i, "created_at": ago(m), "status": status}


def job(m, status="completed", concl="success", name="dispatch", started=True):
    return {"name": name, "status": status, "conclusion": concl, "created_at": ago(m), "started_at": ago(m) if started else None}


# ── dispatcher ──
def test_dispatcher_ok_when_dispatch_job_started_recently():
    v = w.check_dispatcher([run(1, 20)], lambda i: [job(20)], NOW, TH)
    assert v["state"] == w.OK and v["evidence"]["minutes_since_dispatch_job_started"] == 20


def test_dispatcher_bad_when_no_run_created_past_limit():
    v = w.check_dispatcher([run(1, 200)], lambda i: [job(200)], NOW, TH)
    assert v["state"] == w.BAD and v["heal"] == "dispatch" and "200" in v["detail"]


def test_dispatcher_bad_when_runs_exist_but_dispatch_job_was_skipped():
    # the dedupe job skipped it: a fresh RUN, no START -- the case a run-level or receipt check calls healthy
    v = w.check_dispatcher([run(1, 10), run(2, 70)], lambda i: [job(10, "completed", "skipped", started=False)], NOW, TH)
    assert v["state"] == w.BAD and "skipped/queued runs are not starts" in v["detail"]


def test_dispatcher_bad_when_job_stuck_running_or_pending():
    v = w.check_dispatcher([run(1, 50, "in_progress")], lambda i: [job(50, "in_progress", None)], NOW, TH)
    assert v["state"] == w.BAD and "running 50 min" in v["detail"]
    v = w.check_dispatcher([run(1, 60, "queued"), run(2, 5)], lambda i: [job(60, "queued", None, started=False)] if i == 1 else [job(5)], NOW, TH)
    assert v["state"] == w.BAD and "queued for 60 min" in v["detail"]


def test_dispatcher_could_not_look_is_never_ok():
    assert w.check_dispatcher(None, lambda i: None, NOW, TH)["state"] == w.CNL
    assert w.check_dispatcher([run(1, 5)], lambda i: None, NOW, TH)["state"] == w.CNL      # jobs unreadable
    assert w.check_dispatcher([], lambda i: [], NOW, TH)["state"] == w.BAD                  # zero runs is a finding, not a pass


# ── dispatcher_fires ──
def test_fires_bad_runnable_but_nothing_started_or_in_flight():
    v = w.check_fires(12, [run(1, 300)], NOW, TH)
    assert v["state"] == w.BAD and v["heal"] == "dispatch"


def test_fires_ok_paths_and_cnl():
    assert w.check_fires(12, [run(1, 300), run(2, 30, "in_progress")], NOW, TH)["state"] == w.OK
    assert w.check_fires(12, [run(1, 10)], NOW, TH)["state"] == w.OK
    assert w.check_fires(0, [], NOW, TH)["state"] == w.OK            # nothing owed
    assert w.check_fires(None, [], NOW, TH)["state"] == w.CNL
    assert w.check_fires(5, None, NOW, TH)["state"] == w.CNL


def test_fires_ignores_ancient_stuck_runs_as_load():
    assert w.check_fires(5, [run(1, 3000, "in_progress")], NOW, TH)["state"] == w.BAD


# ── queue ──
def test_queue_floor_empty_and_unreadable():
    assert w.check_queue(25, TH)["state"] == w.OK
    v = w.check_queue(10, TH)
    assert v["state"] == w.BAD and v["immediate"] and "10 < floor 25" in v["detail"]
    assert "EMPTY" in w.check_queue(0, TH)["detail"]
    assert w.check_queue(None, TH)["state"] == w.CNL


# ── backends ──
def test_backend_idle_with_runnable_is_bad_but_not_without():
    assert w.check_backend("trainer", 0, [], NOW, TH)["state"] == w.OK
    v = w.check_backend("trainer", 5, [run(1, 400)], NOW, TH)
    assert v["state"] == w.BAD and "idle with 5 runnable" in v["detail"]
    assert w.check_backend("trainer", 5, [run(1, 400), run(2, 1, "queued")], NOW, TH)["state"] == w.OK
    assert w.check_backend("trainer", 5, [run(1, 30)], NOW, TH)["state"] == w.OK


def test_backend_could_not_look_variants():
    assert w.check_backend("trainer", None, [], NOW, TH)["state"] == w.CNL
    assert w.check_backend("trainer", 3, None, NOW, TH)["state"] == w.CNL


def test_kaggle_quota_distinguishes_idle_by_quota_from_idle_by_fault():
    assert w.check_backend("kaggle", 2, [], NOW, TH, quota=None)["state"] == w.CNL
    assert w.check_backend("kaggle", 2, [], NOW, TH, quota={"remaining": None})["state"] == w.CNL
    assert w.check_backend("kaggle", 2, [], NOW, TH, quota={"remaining": 1.0, "floor_hours": 3.0})["state"] == w.OK
    assert w.check_backend("kaggle", 2, [], NOW, TH, quota={"remaining": 20.0, "floor_hours": 3.0})["state"] == w.BAD


# ── collector ──
def test_collector_states():
    assert w.check_collector({"landed": [{"unit": "U", "run_id": 1, "age_minutes": 30}]}, TH)["state"] == w.OK
    v = w.check_collector({"landed": [{"unit": "U", "run_id": 1, "age_minutes": 500}]}, TH)
    assert v["state"] == w.BAD and v["heal"] == "dispatch"
    assert w.check_collector({"landed": [], "lost": [{"unit": "U", "run_id": 2, "why": "expired"}]}, TH)["state"] == w.BAD
    assert w.check_collector({"landed": [], "unreadable": [{"run_id": 3}]}, TH)["state"] == w.CNL
    assert w.check_collector({"read_error": "gh failed"}, TH)["state"] == w.CNL
    assert w.check_collector(None, TH)["state"] == w.CNL


# ── stamps ──
def test_stamps_states():
    pr = lambda n, m, ref="automation/research-queue-stamp-1": {"number": n, "created_at": ago(m), "head": {"ref": ref}}
    assert w.check_stamps([pr(1, 30)], NOW, TH)["state"] == w.OK
    v = w.check_stamps([pr(2, 400), pr(3, 400, "feature/x")], NOW, TH)
    assert v["state"] == w.BAD and v["evidence"]["stranded"] == [2]
    assert w.check_stamps(None, NOW, TH)["state"] == w.CNL


# ── incident machine ──
class P(w.FixtureProbe):
    def __init__(self, fx):
        super().__init__(fx)
        self.state_ok = False


def fixture(*, dispatch_age=300, comments=None, pr=77):
    return {"workflow_runs": {w.DISPATCH_WORKFLOW: [run(1, dispatch_age)],
                              **{wf: [run(10 + i, 5)] for i, wf in enumerate(w.RESEARCH_WORKFLOWS)}},
            "run_jobs": {"1": [job(dispatch_age)]}, "open_prs": [], "collector": {"landed": []},
            "ops_flags_pr": pr, "pr_comments": comments if comments is not None else []}


HEALTHY = {"runnable": 30, "by_backend": {}, "unplaceable": 0, "units_total": 99, "unreadable_units": 0, "backends": [],
           "backend_workflows": {}, "router_style_due_not_counted_by_dispatchable": 0, "kaggle_floor_hours": 3.0}


FACTS = {"v": HEALTHY}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    FACTS["v"] = HEALTHY
    monkeypatch.setattr(w, "queue_facts", lambda root, now: FACTS["v"])      # never read the live queue


def cycle(fx, tmp_path, live=True, sleeps=None):
    p = P(fx)
    res = w.run_cycle(p, CFG, now=NOW, ledger=tmp_path / "l.jsonl", live=live, sleep=lambda s: (sleeps or []).append(s))
    return p, res


def test_escalates_once_with_heal_then_dedupes(tmp_path):
    p, res = cycle(fixture(), tmp_path)
    disp = [e for e in res["events"] if e["check"] == "dispatcher"]
    assert disp and disp[0]["event"] == "escalated" and disp[0]["healed_by"] == "dispatch"
    assert [e for e in p.effects if "dispatch" in e] and sum(1 for e in p.effects if e.get("dispatch") == "dispatch") == 1   # ONE re-fire
    posted = [e for e in p.effects if "post_comment" in e]
    assert posted and "<!-- research-watchdog" in posted[0]["body"]
    assert any("ping" in e for e in p.effects)
    # next cycle reads its own comment back: same incident is NOT re-escalated, nor re-healed
    cm = [{"body": e["body"]} for e in p.effects if "post_comment" in e]
    p2, res2 = cycle(fixture(comments=cm), tmp_path / "x")
    assert not [e for e in res2["events"] if e["check"] == "dispatcher"]
    assert not [e for e in p2.effects if e.get("dispatch") == "dispatch"]


def test_resolves_once_when_healthy_again(tmp_path):
    p, res = cycle(fixture(), tmp_path)
    cm = [{"body": e["body"]} for e in p.effects if "post_comment" in e]
    p2, res2 = cycle(fixture(dispatch_age=10, comments=cm), tmp_path / "y")
    r = [e for e in res2["events"] if e["event"] == "resolved" and e["check"] == "dispatcher"]
    assert len(r) == 1
    assert any("resolved" in e.get("ping", "") for e in p2.effects)


def test_queue_below_floor_escalates_immediately_even_if_heal_fired(tmp_path, monkeypatch):
    facts = {"runnable": 3, "by_backend": {}, "unplaceable": 0, "units_total": 9, "unreadable_units": 0, "backends": [],
             "backend_workflows": {}, "router_style_due_not_counted_by_dispatchable": 0, "kaggle_floor_hours": 3.0}
    FACTS["v"] = facts
    p, res = cycle(fixture(dispatch_age=5), tmp_path)
    assert [e for e in res["events"] if e["check"] == "queue" and e["event"] == "escalated"]


def test_dry_run_has_no_effects_and_no_ledger(tmp_path):
    p, res = cycle(fixture(), tmp_path, live=False)
    assert not [e for e in p.effects if "ping" in e or "post_comment" in e]
    assert not (tmp_path / "l.jsonl").exists()


def test_ledger_rows_written_live(tmp_path):
    cycle(fixture(), tmp_path)
    rows = [json.loads(l) for l in (tmp_path / "l.jsonl").read_text().splitlines()]
    assert rows and all({"ts", "event", "check", "incident", "detail"} <= set(r) for r in rows)


def test_could_not_look_is_escalated_not_passed(tmp_path):
    fx = fixture(dispatch_age=5)
    fx["open_prs"] = None
    p, res = cycle(fx, tmp_path)
    ev = [e for e in res["events"] if e["check"] == "stamps"]
    assert ev and ev[0]["state"] == w.CNL


def test_ledger_alone_carries_open_state_when_pr_comments_unreadable(tmp_path):
    cycle(fixture(), tmp_path)           # writes the ledger
    fx = fixture(comments=None)
    fx["pr_comments"] = None
    p2, res2 = cycle(fx, tmp_path)       # same ledger path -> deduped
    assert not [e for e in res2["events"] if e["check"] == "dispatcher" and e["event"] == "escalated"]


def test_config_has_the_operator_thresholds():
    assert TH["dispatcher_no_start_minutes"] == 75 and TH["backend_idle_minutes"] == 60 and TH["runnable_floor"] == 25
