"""Research never starves a safety action (manager review, 2026-09-29 01:27Z).

MEASURED before the change: 67 runs queued repo-wide and 12 research compute
runs in progress after one dispatcher cycle fanned the whole queue out, with
every system-action waiting in the same pool. Two caps, both deferrals (never
failures, never stamps): at most 3 research compute runs queued+in progress,
and no fire at all while > 10 runs are queued repo-wide. Plus: the runner's
results land ONE PR per dispatcher cycle (tests/test_research_script_run.py).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.research import dispatch_queue as dq  # noqa: E402

RESEARCH = {"research-script-run.yml": "research-script-run", "e35-bracket-sweep.yml": "e35-bracket-sweep"}


def _runs(names):
    return [{"databaseId": i, "workflowName": n, "status": "x", "createdAt": ""} for i, n in enumerate(names)]


def test_inflight_counts_only_research_workflows_across_queued_and_in_progress():
    r = dq.backpressure(RESEARCH, max_inflight=3, max_queued=10, runs_by_status={
        "queued": _runs(["pytest-run", "research-script-run"]),
        "in_progress": _runs(["e35-bracket-sweep", "session-reaper"])})
    assert r["inflight_research"] == 2 and r["repo_queued"] == 2 and r["block"] is None


def test_the_research_cap_defers_and_says_so():
    r = dq.backpressure(RESEARCH, max_inflight=3, max_queued=10, runs_by_status={
        "queued": [], "in_progress": _runs(["research-script-run"] * 3)})
    assert r["block"] and "3 research compute" in r["block"]


def test_a_saturated_repo_queue_defers_even_with_no_research_in_flight():
    r = dq.backpressure(RESEARCH, max_inflight=3, max_queued=10, runs_by_status={
        "queued": _runs(["pytest-run"] * 11), "in_progress": []})
    assert r["block"] and "queued repo-wide" in r["block"]


def test_a_count_we_could_not_take_is_a_block_not_a_zero():
    r = dq.backpressure(RESEARCH, max_inflight=3, max_queued=10,
                        runs_by_status={"queued": None, "in_progress": []})
    assert r["block"] and "could not count" in r["block"] and r["inflight_research"] is None


def test_the_measured_saturation_of_2026_09_29_would_have_been_deferred():
    """The exact shape the manager measured at 01:27Z: 67 queued, 12 research in flight."""
    inprog = _runs(["research-script-run"] * 6 + ["research-harness-dispatch"] * 2 + ["m20-exit-lever-sweep"] * 2
                   + ["e35-bracket-sweep", "macro-valuation-backfill", "session-reaper"])
    names = dict(RESEARCH, **{"research-harness-dispatch.yml": "research-harness-dispatch",
                              "m20-exit-lever-sweep.yml": "m20-exit-lever-sweep",
                              "macro-valuation-backfill.yml": "macro-valuation-backfill"})
    r = dq.backpressure(names, max_inflight=3, max_queued=10,
                        runs_by_status={"queued": _runs(["pytest-run"] * 67), "in_progress": inprog})
    assert r["inflight_research"] == 12 and r["repo_queued"] == 67 and r["block"]


def test_research_workflow_names_resolve_from_the_committed_queue():
    from scripts.research.research_queue import load_queue
    jobs, err = load_queue(REPO / "research" / "queue")
    assert err is None
    names = dq.research_workflow_names(jobs)
    assert names["research-script-run.yml"] == "research-script-run"
    assert all(v for v in names.values())
    # a session-bound note is never a workflow
    assert not any(" " in k for k in names)


def test_a_fired_cycle_under_pressure_dispatches_nothing_and_stamps_nothing(tmp_path, monkeypatch):
    """PLANTED: with 3 research runs in flight, --fire must call gh workflow run ZERO times."""
    unit = (REPO / "research/queue/RQ-20260928-012.yaml").read_text().replace("status: done", "status: queued\ntheme: infra\npriority: 2")
    unit = unit.replace("last_dispatched_at: '2026-09-28T21:20:36+00:00'", "last_dispatched_at: null")
    q = tmp_path / "queue"
    q.mkdir()
    (q / "RQ-20260928-012.yaml").write_text(unit)
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        raise AssertionError(f"gh must not be called under backpressure: {cmd[:3]}")

    monkeypatch.setattr(dq, "gh_runs", lambda status, limit=200: _runs(["research-script-run"] * 3) if status == "in_progress" else [])
    monkeypatch.setattr(dq.subprocess, "run", fake_run)
    rc = dq.main(["--queue-dir", str(q), "--fire", "--ref", "main", "--json", "--max-research-inflight", "3"])
    assert rc == 0 and calls == []
    assert "last_dispatched_at: null" in (q / "RQ-20260928-012.yaml").read_text()


def test_self_tests_pass():
    for script in ("scripts/research/collect_runner_results.py",):
        proc = subprocess.run([sys.executable, str(REPO / script), "--self-test"], capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_dispatcher_workflow_passes_both_caps():
    """--max-repo-queued rides the command line; the in-flight caps (total + per backend) moved to
    scripts/research/research_compute.yaml with RESEARCH-ROUTER (2026-10-13) -- both must be present."""
    from scripts.research import compute_router as cr
    assert "--max-repo-queued" in (REPO / ".github/workflows/research-queue-dispatch.yml").read_text()
    cfg = cr.load_config()
    assert cfg["limits"]["max_total_inflight"] >= 1
    assert all(b["max_concurrent"] >= 1 for b in cfg["backends"].values())


# ── stuck runs are not load (measured 2026-09-29 06:56Z, first fired cycle after #13907) ──
def test_stuck_runs_older_than_a_day_count_against_neither_cap():
    """All 36 queued runs on 2026-09-29 06:56Z were created on 2026-05-15 (issue-triggered
    vm-* jobs no runner ever served), and the 3 'research runs in flight' were three
    trainer-vm-diag dispatches from the same morning. They deferred every fire and would
    have done so on every cycle until someone cancelled them by hand."""
    from datetime import datetime, timezone
    now = datetime(2026, 9, 29, 6, 56, tzinfo=timezone.utc)
    zombies = [{"databaseId": i, "workflowName": "vm-web-api-recover", "status": "queued",
                "createdAt": "2026-05-15T07:45:37Z"} for i in range(33)]
    zombies += [{"databaseId": 100 + i, "workflowName": "trainer-vm-diag", "status": "queued",
                 "createdAt": "2026-05-15T07:5%d:00Z" % i} for i in range(3)]
    names = {"trainer-vm-diag.yml": "trainer-vm-diag", "e35-bracket-sweep.yml": "e35-bracket-sweep"}
    r = dq.backpressure(names, max_inflight=3, max_queued=10, now=now,
                        runs_by_status={"queued": zombies, "in_progress": []})
    assert r["block"] is None, r
    assert r["repo_queued"] == 0 and r["inflight_research"] == 0 and r["stale_ignored"] == 36
    assert "36 stuck run(s)" in r["detail"]
    # fresh runs still count, exactly as before
    fresh = [{"databaseId": 200 + i, "workflowName": "Guards", "status": "queued",
              "createdAt": "2026-09-29T06:50:00Z"} for i in range(11)]
    r2 = dq.backpressure(names, max_inflight=3, max_queued=10, now=now,
                         runs_by_status={"queued": zombies + fresh, "in_progress": []})
    assert r2["block"] and r2["repo_queued"] == 11 and r2["stale_ignored"] == 36
    live = [{"databaseId": 300 + i, "workflowName": "e35-bracket-sweep", "status": "in_progress",
             "createdAt": "2026-09-29T06:00:00Z"} for i in range(3)]
    r3 = dq.backpressure(names, max_inflight=3, max_queued=10, now=now,
                         runs_by_status={"queued": zombies, "in_progress": live})
    assert r3["block"] and r3["inflight_research"] == 3


def test_an_unreadable_created_at_counts_as_fresh():
    from datetime import datetime, timezone
    now = datetime(2026, 9, 29, 6, 56, tzinfo=timezone.utc)
    rows = [{"databaseId": 1, "workflowName": "e35-bracket-sweep", "status": "queued", "createdAt": "garbage"},
            {"databaseId": 2, "workflowName": "e35-bracket-sweep", "status": "queued"},
            {"databaseId": 3, "workflowName": "e35-bracket-sweep", "status": "queued", "createdAt": "2026-09-29T06:00:00Z"}]
    r = dq.backpressure({"e.yml": "e35-bracket-sweep"}, max_inflight=3, max_queued=10, now=now,
                        runs_by_status={"queued": rows, "in_progress": []})
    assert r["inflight_research"] == 3 and r["stale_ignored"] == 0 and r["block"]


def test_the_stale_window_is_a_flag_the_workflow_can_pass():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "scripts/research/dispatch_queue.py", "--help"],
                         capture_output=True, text=True, cwd=str(REPO)).stdout
    assert "--pressure-stale-hours" in out


# ── same-workflow fires are serialized: one per workflow file per cycle ──────
def _unit_text(uid: str, workflow: str) -> str:
    """A real, power-graded, routable unit from the committed queue (RQ-20260928-016, e35,
    monthly) re-pointed at `workflow`, unstamped and cadence once."""
    import yaml
    d = yaml.safe_load((REPO / "research/queue/RQ-20260928-016.yaml").read_text())
    d.update(id=uid, status="queued", cadence="once", last_dispatched_at=None)
    d.pop("grading", None)
    d["run"] = {"workflow": workflow, "inputs": {"research_unit": uid}}
    return yaml.safe_dump(d, sort_keys=False)


def _fired_cycle(tmp_path, monkeypatch, units, extra_args=()):
    """Run --fire with gh mocked: no pressure, every `gh workflow run` succeeds. Returns the dispatched ids in order."""
    q = tmp_path / "queue"
    q.mkdir()
    for uid, wf in units:
        (q / f"{uid}.yaml").write_text(_unit_text(uid, wf))
    fired = []

    def fake_run(cmd, *a, **k):
        class P:
            returncode = 0
            stdout = ""
            stderr = ""
        if cmd[:3] == ["gh", "workflow", "run"]:
            fired.append(cmd)
        return P()

    monkeypatch.setattr(dq, "gh_runs", lambda status, limit=200: [])
    monkeypatch.setattr(dq, "declared_inputs", lambda *a, **k: {"research_unit", "power_state"})
    from scripts.research import script_run
    monkeypatch.setattr(script_run, "plan", lambda *a, **k: type("P", (), {"ok": True, "errors": []})())
    monkeypatch.setattr(dq.subprocess, "run", fake_run)
    rc = dq.main(["--queue-dir", str(q), "--fire", "--ref", "main", "--json", "--max-research-inflight", "9",
                  *extra_args])
    assert rc == 0
    stamped = sorted(p.stem for p in q.glob("*.yaml") if "last_dispatched_at: null" not in p.read_text())
    return fired, stamped


def test_three_e35_units_due_in_one_cycle_fire_one_and_defer_two(tmp_path, monkeypatch, capsys):
    """PLANTED (2026-09-29 00:53Z): three e35-bracket-sweep fires in one cycle -- the
    concurrency group cancelled the middle one and the survivors' corpus PRs collided."""
    units = [("RQ-20300101-001", "e35-bracket-sweep.yml"), ("RQ-20300101-002", "e35-bracket-sweep.yml"),
             ("RQ-20300101-003", "e35-bracket-sweep.yml"), ("RQ-20300101-004", "m20-exit-lever-sweep.yml")]
    fired, stamped = _fired_cycle(tmp_path, monkeypatch, units)
    assert len(fired) == 2, fired                       # one e35 + one m20
    assert stamped == ["RQ-20300101-001", "RQ-20300101-004"]
    out = capsys.readouterr().out
    assert out.count("already fired 1 unit(s) this cycle") == 2, out


def test_the_token_free_runner_is_not_serialized(tmp_path, monkeypatch):
    units = [(f"RQ-20300101-00{i}", "research-script-run.yml") for i in range(1, 4)]
    fired, stamped = _fired_cycle(tmp_path, monkeypatch, units)
    assert len(fired) == 3 and len(stamped) == 3


def test_the_per_workflow_cap_is_a_flag(tmp_path, monkeypatch):
    units = [("RQ-20300101-001", "e35-bracket-sweep.yml"), ("RQ-20300101-002", "e35-bracket-sweep.yml")]
    fired, stamped = _fired_cycle(tmp_path, monkeypatch, units, extra_args=("--max-fires-per-workflow", "2"))
    assert len(fired) == 2 and len(stamped) == 2


def test_only_colliding_workflows_are_serialized():
    assert dq.serialized_workflow("e35-bracket-sweep.yml")            # constant concurrency group + corpus
    assert dq.serialized_workflow("m20-exit-lever-sweep.yml")         # no group, but a whole-file corpus rewrite
    assert dq.serialized_workflow("macro-valuation-backfill.yml")
    assert not dq.serialized_workflow("research-script-run.yml")      # per-unit group, batch-landed
    assert not dq.serialized_workflow("research-harness-dispatch.yml")  # per-run group
    assert not dq.serialized_workflow("no-such-workflow.yml")


# ── yield to infra (GH-CAPACITY-INFRA-FIRST, operator 2026-10-15) ────────────────────────────────────────
INFRA = ["system-actions", "phone-executor-apk"]


def test_a_queued_infra_run_defers_every_research_fire():
    r = dq.backpressure(RESEARCH, max_inflight=3, max_queued=10, infra_names=INFRA,
                        runs_by_status={"queued": _runs(["system-actions"]), "in_progress": []})
    assert r["block"] and "infra" in r["block"] and "system-actions" in r["block"]
    assert r["infra_queued"] == 1


def test_infra_already_running_does_not_block():
    """Only a WAITING infra run is starved by a new research job; one already on a runner is not."""
    r = dq.backpressure(RESEARCH, max_inflight=3, max_queued=10, infra_names=INFRA,
                        runs_by_status={"queued": _runs(["pytest-run"]), "in_progress": _runs(["system-actions"])})
    assert r["block"] is None and r["infra_queued"] == 0


def test_a_stale_queued_infra_ghost_does_not_block_forever():
    """Measured 2026-10-15: vm-web-api-recover/vm-cloud-fix runs created 2026-05-15 still read `queued`."""
    old = [{"databaseId": 1, "workflowName": "system-actions", "status": "queued", "createdAt": "2026-05-15T07:45:37Z"}]
    r = dq.backpressure(RESEARCH, max_inflight=3, max_queued=10, infra_names=INFRA,
                        runs_by_status={"queued": old, "in_progress": []})
    assert r["block"] is None and r["infra_queued"] == 0


def test_without_infra_names_the_old_behaviour_is_unchanged():
    r = dq.backpressure(RESEARCH, max_inflight=3, max_queued=10,
                        runs_by_status={"queued": _runs(["system-actions"]), "in_progress": []})
    assert r["block"] is None


def test_every_configured_infra_workflow_name_exists():
    """A renamed workflow would silently drop out of the yield: gh matches on the `name:` field."""
    import yaml
    cfg = yaml.safe_load((REPO / "scripts/research/research_compute.yaml").read_text())
    names = cfg["limits"]["infra_workflows"]
    assert "system-actions" in names and "phone-executor-apk" in names
    have = {yaml.safe_load(p.read_text()).get("name") for p in (REPO / ".github/workflows").glob("*.yml")}
    missing = [n for n in names if n not in have]
    assert not missing, missing


# ── an unmanaged workflow cannot take a managed backend's slot (RESEARCH-DISPATCH-STALL-1016) ──
def _fired_workflows(fired):
    return [c[3] for c in fired]


def test_unmanaged_units_do_not_take_the_slots_of_a_managed_backend(tmp_path, monkeypatch):
    """MEASURED 2026-10-16: 08:10Z/08:51Z fired 8 research-harness-dispatch.yml units (no backend in
    research_compute.yaml) and deferred trainer + kaggle_cpu units on 'research compute cap 8 reached' with
    both backends at 0 in flight. Managed units are offered the shared cap first; unmanaged keep the rest."""
    units = [(f"RQ-20300101-00{i}", "research-harness-dispatch.yml") for i in range(1, 4)] + \
            [("RQ-20300101-009", "research-script-run-kaggle-cpu.yml")]
    fired, stamped = _fired_cycle(tmp_path, monkeypatch, units, extra_args=("--max-research-inflight", "2"))
    wfs = _fired_workflows(fired)
    assert len(fired) == 2 and "research-script-run-kaggle-cpu.yml" in wfs, wfs
    assert "RQ-20300101-009" in stamped


def test_without_managed_first_the_harness_takes_every_slot(tmp_path, monkeypatch):
    """The 2026-10-16 condition, reproduced: fair order alone gives every slot to the unmanaged units."""
    monkeypatch.setattr(dq, "managed_first", lambda jobs, cfg: jobs)
    units = [(f"RQ-20300101-00{i}", "research-harness-dispatch.yml") for i in range(1, 4)] + \
            [("RQ-20300101-009", "research-script-run-kaggle-cpu.yml")]
    fired, _ = _fired_cycle(tmp_path, monkeypatch, units, extra_args=("--max-research-inflight", "2"))
    assert _fired_workflows(fired) == ["research-harness-dispatch.yml"] * 2


# ── workflow_run listener runs do not count toward the repo-queued cap (manager decision 2026-10-16) ──
def _evruns(pairs, age_min=5):
    from datetime import datetime, timedelta, timezone
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [{"databaseId": i, "workflowName": n, "status": "queued", "createdAt": ts, "event": ev}
            for i, (n, ev) in enumerate(pairs)]


def test_the_measured_listener_flood_of_2026_10_16_no_longer_defers_every_fire():
    """09:37Z: 27 fresh queued runs, mostly claude-run-failure-alert (workflow_run), deferred every fire."""
    queued = _evruns([("claude-run-failure-alert", "workflow_run")] * 20 + [("pytest-run", "pull_request")] * 4
                     + [("pr-landing hold-merge alarm", "push")] * 2 + [("work-digest", "push")])
    r = dq.backpressure(RESEARCH, max_inflight=8, max_queued=10, runs_by_status={"queued": queued, "in_progress": []})
    assert r["block"] is None and r["repo_queued"] == 7 and r["listener_queued_ignored"] == 20, r
    assert "20 workflow_run listener run(s) not counted" in r["detail"]


def test_competing_runs_over_the_cap_still_defer():
    queued = _evruns([("pytest-run", "pull_request")] * 11 + [("claude-run-failure-alert", "workflow_run")] * 5)
    r = dq.backpressure(RESEARCH, max_inflight=8, max_queued=10, runs_by_status={"queued": queued, "in_progress": []})
    assert r["block"] and "11 workflow runs are queued repo-wide" in r["block"]


def test_a_queued_infra_listener_still_makes_research_yield():
    # system-actions-cancel-guard is BOTH a workflow_run listener and an infra workflow: the yield is unchanged
    queued = _evruns([("system-actions-cancel-guard", "workflow_run")])
    r = dq.backpressure(RESEARCH, max_inflight=8, max_queued=10, runs_by_status={"queued": queued, "in_progress": []},
                        infra_names=["system-actions-cancel-guard"])
    assert r["block"] and "infra run(s) queued" in r["block"]


def test_ghost_runs_older_than_a_day_and_listeners_are_both_ignored():
    queued = _evruns([("vm-web-api-recover", "issues")] * 37, age_min=60 * 24 * 150) + \
             _evruns([("claude-run-failure-alert", "workflow_run")] * 13)
    r = dq.backpressure(RESEARCH, max_inflight=8, max_queued=10, runs_by_status={"queued": queued, "in_progress": []})
    assert r["block"] is None and r["repo_queued"] == 0 and r["stale_ignored"] == 37


def test_gh_runs_asks_for_the_event_field(monkeypatch):
    seen = {}

    def fake_run(cmd, *a, **k):
        seen["cmd"] = cmd
        return type("P", (), {"returncode": 0, "stdout": "[]", "stderr": ""})()
    monkeypatch.setattr(dq.subprocess, "run", fake_run)
    assert dq.gh_runs("queued") == []
    assert "event" in seen["cmd"][seen["cmd"].index("--json") + 1].split(",")


def test_the_failure_alert_listener_is_created_only_for_main_runs():
    """(b) of the 2026-10-16 decision: PR CI completions must not create claude-run-failure-alert runs."""
    import yaml
    d = yaml.safe_load((REPO / ".github/workflows/claude-run-failure-alert.yml").read_text())
    wr = (d.get(True) or d["on"])["workflow_run"]
    assert wr.get("branches") == ["main"] and "pytest-run" in wr["workflows"]


# ── starvation floor (lane RESEARCH-DISPATCH-STARVATION-1028) ──
# MEASURED 2026-10-28: 06:04Z (41 queued) and 07:10Z (25 queued) deferred every due unit with 0 research in flight
# and 20/20 hosted-runner slots held by PR / push CI; the last fire was 05:12Z -> the watchdog saw 141 min idle.
def _jobs_with_stamp(stamp):
    return [type("J", (), {"raw": {"last_dispatched_at": stamp}})()]


def _repo_queued_block():
    queued = _evruns([("pytest-run", "pull_request")] * 12)
    return dq.backpressure(RESEARCH, max_inflight=8, max_queued=10, runs_by_status={"queued": queued, "in_progress": []})


def test_a_repo_queued_block_lifts_once_nothing_was_dispatched_for_the_floor():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    p = _repo_queued_block()
    assert p["block_kind"] == "repo_queued" and p["block"]
    why = dq.starvation_override(p, _jobs_with_stamp((now - timedelta(minutes=118)).isoformat()), now, 1.5)
    assert why and "starvation floor" in why and "2.0 h" in why and p["block"] is None


def test_a_recent_dispatch_keeps_the_block():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    p = _repo_queued_block()
    assert dq.starvation_override(p, _jobs_with_stamp((now - timedelta(minutes=52)).isoformat()), now, 1.5) is None
    assert p["block"] and "starvation_override" not in p


def test_no_stamp_anywhere_counts_as_starved_and_zero_disables_the_floor():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    assert dq.starvation_override(_repo_queued_block(), _jobs_with_stamp(None), now, 1.5)
    assert dq.starvation_override(_repo_queued_block(), _jobs_with_stamp(None), now, 0) is None


def test_infra_yield_and_an_unreadable_gh_are_never_lifted():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    infra = dq.backpressure(RESEARCH, max_inflight=8, max_queued=10, infra_names=["system-actions"],
                            runs_by_status={"queued": _evruns([("system-actions", "workflow_dispatch")]), "in_progress": []})
    assert infra["block"] and dq.starvation_override(infra, _jobs_with_stamp(None), now, 1.5) is None and infra["block"]
    blind = dq.backpressure(RESEARCH, max_inflight=8, max_queued=10, runs_by_status={"queued": None, "in_progress": []})
    assert dq.starvation_override(blind, _jobs_with_stamp(None), now, 1.5) is None and blind["block"]


def test_a_starved_saturated_cycle_fires_exactly_one_unit(tmp_path, monkeypatch):
    """END TO END: 12 queued CI runs, 3 due units, no stamps -> the floor fires ONE, not three, and stamps it."""
    units = [(f"RQ-20300101-00{i}", "research-script-run.yml") for i in range(1, 4)]
    q = tmp_path / "queue"
    q.mkdir()
    for uid, wf in units:
        (q / f"{uid}.yaml").write_text(_unit_text(uid, wf))
    fired = []

    def fake_run(cmd, *a, **k):
        class P:
            returncode = 0
            stdout = ""
            stderr = ""
        if cmd[:3] == ["gh", "workflow", "run"]:
            fired.append(cmd)
        return P()

    queued = _evruns([("pytest-run", "pull_request")] * 12)
    monkeypatch.setattr(dq, "gh_runs", lambda status, limit=200: queued if status == "queued" else [])
    monkeypatch.setattr(dq, "declared_inputs", lambda *a, **k: {"research_unit", "power_state"})
    from scripts.research import script_run
    monkeypatch.setattr(script_run, "plan", lambda *a, **k: type("P", (), {"ok": True, "errors": []})())
    monkeypatch.setattr(dq.subprocess, "run", fake_run)
    rc = dq.main(["--queue-dir", str(q), "--fire", "--ref", "main", "--json"])
    assert rc == 0
    assert len(fired) == 1, fired
    # the same cycle with the floor disabled dispatches nothing: the pre-fix behaviour, reproduced
    fired.clear()
    for uid, wf in units:
        (q / f"{uid}.yaml").write_text(_unit_text(uid, wf))
    assert dq.main(["--queue-dir", str(q), "--fire", "--ref", "main", "--json", "--starvation-hours", "0"]) == 0
    assert fired == []
