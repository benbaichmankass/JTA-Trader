"""RESEARCH-WATCHDOG: every check, the could-not-look path of each, self-heal-once, dedupe, resolve."""
import json

import pytest
from datetime import datetime, timedelta, timezone

from scripts.research import research_watchdog as w

NOW = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
CFG = w.load_config()
_REAL_QUEUE_FACTS = w.queue_facts
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


def test_fires_counts_every_workflow_a_runnable_unit_routes_to():
    # MEASURED 2026-10-16 09:36Z: the dispatcher fired 8 research-harness-dispatch.yml runs at 08:57Z (in flight),
    # but the watchdog listed only the four research-script-run* files and escalated "no research compute run
    # started for 160 min". Workflows named by queue_facts' compute_workflows must be listed and counted.
    harness = "research-harness-dispatch.yml"
    assert harness in w.compute_workflows({"compute_workflows": [harness]})
    assert set(w.RESEARCH_WORKFLOWS) <= set(w.compute_workflows(None))         # unreadable facts keep the floor
    fx = {"workflow_runs": {w.DISPATCH_WORKFLOW: [run(1, 20)], harness: [run(50, 40, "in_progress")],
                            **{wf: [run(10 + i, 160)] for i, wf in enumerate(w.RESEARCH_WORKFLOWS)}},
          "run_jobs": {"1": [job(20)]}}
    facts = dict(HEALTHY, compute_workflows=[harness])
    fires = next(v for v in w.evaluate(w.FixtureProbe(fx), CFG, NOW, facts) if v["check"] == "dispatcher_fires")
    assert fires["state"] == w.OK and harness in fires["evidence"]["workflows_counted"]
    without = next(v for v in w.evaluate(w.FixtureProbe(fx), CFG, NOW, dict(HEALTHY)) if v["check"] == "dispatcher_fires")
    assert without["state"] == w.BAD                                            # the 09:36Z false escalation, reproduced


def test_queue_facts_names_the_workflows_runnable_units_resolve_to():
    # reads the checked-in queue (the autouse fixture patches the module attribute, not this captured original)
    f = _REAL_QUEUE_FACTS(w._REPO, datetime.now(timezone.utc))
    assert f is not None and isinstance(f["compute_workflows"], list) and f["compute_workflows"]
    assert all((w._REPO / ".github" / "workflows" / wf).is_file() for wf in f["compute_workflows"])


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
    def pr(n, m, ref="automation/research-queue-stamp-1"):
        return {"number": n, "created_at": ago(m), "head": {"ref": ref}}

    assert w.check_stamps([pr(1, 30)], NOW, TH)["state"] == w.OK
    v = w.check_stamps([pr(2, 400), pr(3, 400, "feature/x")], NOW, TH)
    assert v["state"] == w.BAD and v["evidence"]["stranded"] == [2]
    assert w.check_stamps(None, NOW, TH)["state"] == w.CNL


def test_conflicted_automation_pr_is_named_not_idle():
    def pr(n, m, ref):
        return {"number": n, "created_at": ago(m), "head": {"ref": ref}}

    prs = [pr(18004, 80, "automation/research-queue-stamp-38519778952-1"), pr(18014, 80, "automation/trainer-capture-watch-1"),
           pr(5, 80, "automation/x"), pr(6, 10, "automation/y"), pr(7, 80, "feature/z")]
    st = {18004: "dirty", 18014: "dirty", 5: "clean", 6: "dirty", 7: "dirty"}
    v = w.check_conflicted_automation(prs, st.get, NOW, TH)
    assert v["state"] == w.BAD and v["evidence"]["conflicting"] == [18004, 18014]
    assert "#18004" in v["detail"] and "stamp" in v["detail"]
    # young (6) and non-automation (7) conflicts are not named; clean is OK
    assert w.check_conflicted_automation(prs[2:], st.get, NOW, TH)["state"] == w.OK
    # could-not-look is never OK
    assert w.check_conflicted_automation(prs, lambda n: None, NOW, TH)["state"] == w.CNL
    assert w.check_conflicted_automation(None, st.get, NOW, TH)["state"] == w.CNL


# ── phone heartbeat ──
def test_phone_heartbeat_maps_the_shared_probe_and_never_passes_unknown():
    assert w.check_phone_heartbeat({"status": "ok", "detail": "fresh"}, TH)["state"] == w.OK
    v = w.check_phone_heartbeat({"status": "breached", "detail": "breakout_2: last phone heartbeat 31 min ago"}, TH)
    assert v["state"] == w.BAD and "31 min" in v["detail"] and v["heal"] is None
    assert w.check_phone_heartbeat({"status": "unknown", "detail": "mode unreadable"}, TH)["state"] == w.CNL
    assert w.check_phone_heartbeat(None, TH)["state"] == w.CNL
    assert w.check_phone_heartbeat({"status": "weird"}, TH)["state"] == w.CNL


def test_phone_limit_equals_the_probe_limit_and_probe_agrees_with_it():
    from datetime import timedelta as td

    from scripts.ops import prop_silence as ps
    assert TH["phone_heartbeat_max_minutes"] == ps.HEARTBEAT_MAX_MIN
    now = NOW
    def fetch(age):
        return lambda path: ("read", {"phone_heartbeat": {"at": (now - td(minutes=age)).isoformat()}})
    live = lambda acct: "live"            # noqa: E731
    assert ps.probe_phone_heartbeat(now, fetch(3), live)["status"] == ps.OK
    assert ps.probe_phone_heartbeat(now, fetch(25), live)["status"] == ps.BREACHED
    assert ps.probe_phone_heartbeat(now, fetch(25), lambda a: "dry_run")["status"] == ps.OK     # not live -> not required


def test_phone_breach_escalates_once_then_recovery_resolves(tmp_path):
    fx = fixture(dispatch_age=5)
    fx["phone_probe"] = {"status": "breached", "detail": "breakout_2: last phone heartbeat 40 min ago"}
    p, res = cycle(fx, tmp_path)
    ev = [e for e in res["events"] if e["check"] == "phone_heartbeat"]
    assert len(ev) == 1 and ev[0]["event"] == "escalated"
    assert sum(1 for e in p.effects if "ping" in e and "phone_heartbeat" in e["ping"]) == 1      # ONE telegram
    cm = [{"body": e["body"]} for e in p.effects if "post_comment" in e]
    again, res2 = cycle(dict(fixture(dispatch_age=5, comments=cm), phone_probe=fx["phone_probe"]), tmp_path / "z")
    assert not [e for e in res2["events"] if e["check"] == "phone_heartbeat"]                    # deduped
    ok_fx = dict(fixture(dispatch_age=5, comments=cm), phone_probe={"status": "ok", "detail": "fresh"})
    rec, res3 = cycle(ok_fx, tmp_path / "y")
    assert [e for e in res3["events"] if e["check"] == "phone_heartbeat" and e["event"] == "resolved"]
    assert any("resolved" in e.get("ping", "") for e in rec.effects)


# ── incident machine ──
class P(w.FixtureProbe):
    def __init__(self, fx):
        super().__init__(fx)
        self.state_ok = False


def fixture(*, dispatch_age=300, comments=None, pr=77):
    return {"workflow_runs": {w.DISPATCH_WORKFLOW: [run(1, dispatch_age)],
                              **{wf: [run(10 + i, 5)] for i, wf in enumerate(w.RESEARCH_WORKFLOWS)}},
            "run_jobs": {"1": [job(dispatch_age)]}, "open_prs": [], "collector": {"landed": []},
            "ops_flags_pr": pr, "pr_comments": comments if comments is not None else [],
            "phone_probe": {"status": "ok", "detail": "fresh"}}


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
    rows = [json.loads(ln) for ln in (tmp_path / "l.jsonl").read_text().splitlines()]
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


def test_backend_underutilised_is_a_non_alerting_reading():
    v = w.check_backend("github_runner", 4, [run(1, 1, "in_progress")], NOW, TH, max_concurrent=3)
    assert v["state"] == w.OK and v["evidence"]["underutilised"] is True and v["heal"] is None
    full = [run(i, 1, "in_progress") for i in range(3)]
    assert "underutilised" not in w.check_backend("github_runner", 4, full, NOW, TH, max_concurrent=3)["evidence"]
    assert "underutilised" not in w.check_backend("github_runner", 4, full, NOW, TH)["evidence"]


# ── windowed backend (the trainer queue, ML-DATA-OFF-TRAINER) ──
WIN = ["03:00-05:00", "07:00-24:00"]
DAY = NOW.replace(hour=0, minute=0)


def _at(h, m=0):
    return DAY + timedelta(hours=h, minutes=m)


def _run(now, minutes_ago, status="completed", i=1):
    return {"id": i, "created_at": (now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": status}


def test_trainer_idle_outside_its_window_is_waiting_not_an_incident():
    # 02:04Z 2026-10-14: 7 runnable, nothing started for 120+ min -> the real false alarm
    now = _at(2, 4)
    v = w.check_backend("trainer", 7, [_run(now, 400)], now, TH, windows=WIN)
    assert v["state"] == w.OK and "waiting for window (opens 03:00Z)" in v["detail"], v
    now = _at(6, 0)                                                      # the catch-up hour
    v = w.check_backend("trainer", 7, [_run(now, 400)], now, TH, windows=WIN)
    assert v["state"] == w.OK and "07:00Z" in v["detail"], v


def test_trainer_idle_inside_its_window_still_escalates_after_the_limit_from_open():
    lim = int(TH["backend_idle_minutes"])
    # positive control: window opened hours ago, nothing started -> BAD
    now = _at(12, 0)
    v = w.check_backend("trainer", 7, [_run(now, 4000)], now, TH, windows=WIN)
    assert v["state"] == w.BAD and v["heal"] == "dispatch" and "counted from window open" in v["detail"], v
    # inside the limit of the opening -> OK even though the last run is ancient
    now = _at(7, 0) + timedelta(minutes=lim - 1)
    assert w.check_backend("trainer", 7, [_run(now, 4000)], now, TH, windows=WIN)["state"] == w.OK
    # past the limit from the opening -> BAD
    now = _at(7, 0) + timedelta(minutes=lim + 1)
    assert w.check_backend("trainer", 7, [_run(now, 4000)], now, TH, windows=WIN)["state"] == w.BAD


def test_trainer_fit_rule_no_unit_fits_the_remaining_window_is_waiting():
    now = _at(23, 50)
    v = w.check_backend("trainer", 3, [_run(now, 4000)], now, TH, windows=WIN, min_need_minutes=22.5)
    assert v["state"] == w.OK and "fits" in v["detail"], v
    now = _at(23, 30)                                                    # positive control: it fits, nothing started
    assert w.check_backend("trainer", 3, [_run(now, 4000)], now, TH, windows=WIN, min_need_minutes=22.5)["state"] == w.BAD


def test_windows_do_not_hide_an_active_run_or_change_unwindowed_backends():
    now = _at(2, 0)
    assert w.check_backend("trainer", 5, [_run(now, 400), _run(now, 1, "queued", 2)], now, TH, windows=WIN)["state"] == w.OK
    assert w.check_backend("github_runner", 5, [_run(now, 400)], now, TH)["state"] == w.BAD     # no windows -> unchanged


def test_the_router_config_declares_the_trainer_windows_the_watchdog_reads():
    from scripts.research import compute_router as cr
    assert cr.load_config()["backends"]["trainer"]["queue"]["windows_utc"] == WIN


# ── due now vs due within the refill horizon (EXITS-OVERNIGHT-1021, 2026-10-22) ──
def test_backend_with_only_not_yet_due_units_is_ok_not_idle():
    # the 2026-10-21 23:20Z false escalation: the weekly census was due at 04:43Z, inside the 6 h refill horizon
    v = w.check_backend("trainer", 0, [run(1, 984)], NOW, TH, due_later=1)
    assert v["state"] == w.OK and "none is due yet" in v["detail"]
    assert v["evidence"]["due_within_refill_horizon"] == 1
    assert w.check_backend("trainer", 1, [run(1, 984)], NOW, TH, due_later=0)["state"] == w.BAD


def test_queue_facts_due_now_never_exceeds_the_horizon_count():
    f = _REAL_QUEUE_FACTS(w._REPO, datetime.now(timezone.utc))
    assert f is not None
    for be, n in f["by_backend_due_now"].items():
        assert n <= f["by_backend"].get(be, 0)
