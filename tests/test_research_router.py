"""RESEARCH-ROUTER: compute classes, capacity/quota-aware placement, value ranking (token-free dispatcher)."""
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from scripts.research import compute_router as cr
from scripts.research import dispatch_queue as dq
from scripts.research import kaggle_run, script_run
from scripts.research.research_queue import QueueJob, validate

REPO = Path(__file__).resolve().parents[1]
CFG = cr.load_config()
NOW = datetime(2030, 1, 10, 12, tzinfo=timezone.utc)
TH = {"share_window_hours": 48, "aging_hours": 72,
      "themes": {"live_strategy": {"weight": 4}, "regime": {"weight": 5}}}
QUOTA = ("resource  used   remaining  total   refreshAt            \n"
         "--------  -----  ---------  ------  -------------------  \n"
         "GPU       0.02h  29.98h     30.00h  2026-10-17T00:00:00  \n"
         "TPU       0.00h  20.00h     20.00h  2026-10-17T00:00:00  \n")


def unit(compute=None, workflow=None, routing=None, **kw):
    e = {"id": "RQ-20300110-001", "status": "queued", "cadence": "once", "theme": "live_strategy",
         "priority": 2, "run": {"inputs": {"research_unit": "RQ-20300110-001"}}}
    if workflow:
        e["run"]["workflow"] = workflow
    if compute:
        e["compute"] = compute
    if routing is not None:
        e["routing"] = routing
    e.update(kw)
    return e


def job(i, **kw):
    e = unit(**kw)
    e["id"] = f"RQ-20300110-{i:03d}"
    return QueueJob(path=Path(f"{e['id']}.yaml"), raw=e)


def test_config_loads_and_buckets_sum_to_one():
    assert abs(sum(CFG["value"]["buckets"].values()) - 1.0) < 1e-9
    assert set(CFG["classes"]) >= {"cpu_light", "cpu_long", "needs_vm_data", "gpu", "gpu_preferred"}
    for name, b in CFG["backends"].items():
        assert (REPO / ".github/workflows" / b["workflow"]).is_file(), name


def test_explicit_workflow_beats_compute_class():
    r = cr.plan(unit(compute="gpu", workflow="research-script-run.yml"), CFG)
    assert (r.ok, r.backend, r.source) == (True, "github_runner", "explicit")


def test_class_resolves_to_its_backend_and_workflow():
    for cls, be in [("cpu_light", "github_runner"), ("needs_vm_data", "trainer"), ("gpu", "kaggle")]:
        routing = {"needs_gpu": cls == "gpu", "needs_trainer_resident_data": cls == "needs_vm_data"}
        r = cr.plan(unit(compute=cls, routing=routing), CFG)
        assert r.ok and r.backend == be and r.workflow == CFG["backends"][be]["workflow"], (cls, r)


def test_auto_derives_the_class_from_routing_and_refuses_a_contradiction():
    assert cr.plan(unit(compute="auto", routing={"needs_gpu": True}), CFG).cls == "gpu"
    assert cr.plan(unit(compute="auto", routing={"est_minutes": 90}), CFG).cls == "cpu_long"
    assert cr.plan(unit(compute="auto", routing={"est_minutes": 5}), CFG).cls == "cpu_light"
    bad = cr.plan(unit(compute="gpu", routing={"needs_gpu": False}), CFG)
    assert not bad.ok and "must agree" in bad.error
    assert not cr.plan(unit(compute="auto"), CFG).ok                      # no routing block: never a guess
    assert not cr.plan(unit(compute="warp_drive"), CFG).ok
    assert not cr.plan(unit(), CFG).ok                                    # neither workflow nor compute


def test_runpod_is_never_auto_routed():
    # ML-DATA-OFF-TRAINER (operator 2026-10-13 (d)): RunPod is a ledger-capped FALLBACK, never a class's first choice.
    assert CFG["backends"]["runpod"]["auto_route"] == "fallback"
    assert all(c["backends"][0] != "runpod" for c in CFG["classes"].values())


def test_capacity_makes_a_unit_wait_and_a_fallback_class_moves_on():
    st = cr.BackendState(quota_hours=29.98)
    st.inflight["github_runner"] = 3
    w = cr.resolve(unit(compute="cpu_light"), CFG, st)
    assert w.ok and w.wait and "at capacity" in w.reason
    st.inflight["kaggle"] = 1
    f = cr.resolve(unit(compute="gpu_preferred", routing={"needs_gpu": False}), CFG, st)
    assert f.wait                                                          # both full
    st.inflight["github_runner"] = 0
    f = cr.resolve(unit(compute="gpu_preferred"), CFG, st)
    assert f.ok and not f.wait and f.backend == "github_runner" and "fallback" in f.reason


def test_kaggle_quota_floor_and_unreadable_quota_wait_instead_of_routing_blind():
    gpu = unit(compute="gpu", routing={"needs_gpu": True, "est_minutes": 60})
    ok = cr.resolve(gpu, CFG, cr.BackendState(quota_hours=29.98))
    assert ok.ok and not ok.wait and ok.backend == "kaggle"
    low = cr.resolve(gpu, CFG, cr.BackendState(quota_hours=2.5, quota_refresh="2026-10-17T00:00:00"))
    assert low.wait and "floor" in low.reason and "2026-10-17" in low.reason
    blind = cr.resolve(gpu, CFG, cr.BackendState(quota_hours=None))
    assert blind.wait and "unreadable" in blind.reason


def test_parse_quota_reads_the_observed_kaggle_table_and_never_invents_a_number():
    q = cr.parse_quota(QUOTA)
    assert (q["remaining"], q["used"], q["total"], q["refresh"]) == (29.98, 0.02, 30.0, "2026-10-17T00:00:00")
    assert cr.parse_quota("nonsense")["remaining"] is None
    assert cr.read_quota_file("/nonexistent/x")["remaining"] is None


def test_value_score_uses_declared_value_and_states_its_derivation():
    a = cr.score(unit(value={"usd_at_stake_per_month": 900, "confidence": 0.5, "bucket": "own_losses"},
                      routing={"est_minutes": 60}), CFG, aging_steps=0, fires={})
    b = cr.score(unit(routing={"est_minutes": 60}), CFG, aging_steps=0, fires={})   # prio-2 default: $100, conf 0.3
    assert a["rank_value"] > b["rank_value"] * 10
    assert "$900" in a["derivation"] and "conf 0.5" in a["derivation"] and "prio2 default" in b["derivation"]
    cheap = cr.score(unit(routing={"est_minutes": 10}), CFG, aging_steps=0, fires={})
    dear = cr.score(unit(routing={"est_minutes": 300}), CFG, aging_steps=0, fires={})
    assert cheap["rank_value"] > dear["rank_value"] > 0                              # cost divides, but compressed: (1+h)


def test_bucket_boost_steers_toward_the_underserved_bucket_within_clamps():
    fires = {"own_losses": 9, "frontier": 1}
    assert cr.bucket_boost("frontier", fires, CFG) == 1.0 * min(2.0, max(0.5, 0.10 / 0.10))
    assert cr.bucket_boost("structural", fires, CFG) == 2.0                # never fired: top clamp
    assert cr.bucket_boost("own_losses", fires, CFG) == 0.5                # 0.30/0.90 = .33 -> floor 0.5
    assert cr.bucket_boost("own_losses", {}, CFG) == 1.0                   # empty window: neutral


def test_fair_order_ranks_by_value_per_cost_within_a_theme_and_theme_share_still_holds():
    big = job(1, workflow="research-script-run.yml", value={"usd_at_stake_per_month": 2000, "confidence": 0.6},
              routing={"est_minutes": 60})
    small = job(2, workflow="research-script-run.yml", routing={"est_minutes": 10})
    mid = job(3, workflow="research-script-run.yml", value={"usd_at_stake_per_month": 300}, routing={"est_minutes": 30})
    order = [j.id for j in dq.fair_order([small, mid, big], NOW, TH, CFG)]
    assert order[0] == big.id and order[-1] == small.id
    assert big.raw["_rank"]["derivation"].startswith("score ")
    other = job(9, workflow="research-script-run.yml", theme="regime")
    # MONEY FIRST (operator 2026-10-18): across themes too, value decides -- `other` (regime, no value block and
    # the default est, 18.75) sorts after big (750), mid (75) and small (32.1) of live_strategy; before 2026-10-18
    # the cross-theme round-robin put it second. Theme share now only breaks an equal score
    # (tests/test_research_dispatch_money_first.py).
    order = [j.id for j in dq.fair_order([small, mid, big, other], NOW, TH, CFG)]
    assert order == [big.id, mid.id, small.id, other.id]


def test_nothing_starves_a_long_waiting_low_value_unit_sorts_first_in_its_theme():
    old = job(1, workflow="research-script-run.yml", priority=3, routing={"est_minutes": 300},
              last_dispatched_at=None)
    old.raw["id"] = "RQ-20291201-001"                                      # id-date ~41 days before NOW
    rich = job(2, workflow="research-script-run.yml", value={"usd_at_stake_per_month": 5000, "confidence": 0.9},
               routing={"est_minutes": 10})
    order = dq.fair_order([rich, old], NOW, TH, CFG)
    assert order[0] is old and old.raw["_rank"]["starved"]


def test_without_cfg_the_old_priority_order_is_unchanged():
    hi = job(1, workflow="research-script-run.yml", priority=1)
    lo = job(2, workflow="research-script-run.yml", priority=3)
    assert [j.id for j in dq.fair_order([lo, hi], NOW, TH)] == [hi.id, lo.id]


def test_a_compute_only_unit_validates_and_a_bad_class_or_value_does_not():
    base = {"id": "RQ-20300110-001", "title": "t", "question": "q", "cadence": "once", "status": "queued",
            "theme": "live_strategy", "priority": 2, "lands": {"store": "research/results/"}}
    assert validate({**base, "compute": "gpu"}) == []
    assert any("compute" in e for e in validate({**base, "compute": "warp"}))
    assert validate({**base, "compute": "cpu_light", "value": {"usd_at_stake_per_month": 100, "confidence": 0.4,
                                                              "bucket": "frontier"}}) == []
    assert any("value.confidence" in e for e in validate({**base, "compute": "gpu", "value": {"confidence": 3}}))
    assert any("bucket" in e for e in validate({**base, "compute": "gpu", "value": {"bucket": "vibes"}}))
    assert any("run.workflow" in e for e in validate(dict(base)))


def _write_unit(q: Path, uid: str, **extra):
    d = {"id": uid, "title": "t", "question": "q", "status": "queued", "cadence": "once", "theme": "live_strategy",
         "priority": 2, "kind": "deterministic", "why_not_inferential": "deterministic grader over a fixed ledger",
         "lands": {"store": "research/results/"},
         "run": {"command": ["python3", "scripts/research/script_run.py", "--self-test"],
                 "inputs": {"research_unit": uid}},
         "decision_rule": {"id": "R", "registered_at": "2030-01-01"}}
    d.update(extra)
    (q / f"{uid}.yaml").write_text(yaml.safe_dump(d, sort_keys=False))


def _dry(tmp_path, monkeypatch, units, quota=None, fire=False, runs=None):
    q = tmp_path / "queue"
    q.mkdir()
    for uid, kw in units:
        _write_unit(q, uid, **kw)
    fired = []

    class P:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(dq, "gh_runs", lambda status, limit=200: (runs or {}).get(status, []))
    monkeypatch.setattr(dq.subprocess, "run", lambda cmd, *a, **k: (fired.append(cmd), P())[1])
    monkeypatch.setattr(dq, "RESULTS_ROOT", tmp_path / "results")
    args = ["--queue-dir", str(q), "--json", "--ref", "main"]
    if quota is not None:
        qf = tmp_path / "quota.txt"
        qf.write_text(quota)
        args += ["--kaggle-quota-file", str(qf)]
    if fire:
        args += ["--fire"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        dq.main(args)
    return {d["id"]: d for d in json.loads(buf.getvalue())["decisions"]}, fired


GPU_ROUTE = {"needs_gpu": True, "needs_trainer_resident_data": False, "peak_memory_gb": 4, "est_minutes": 60}
CPU_ROUTE = {"needs_gpu": False, "needs_trainer_resident_data": False, "peak_memory_gb": 2, "est_minutes": 10}


def test_dispatcher_dry_run_routes_each_class_and_prints_the_derivation(tmp_path, monkeypatch):
    units = [("RQ-20300110-001", {"compute": "gpu", "routing": GPU_ROUTE}),
             ("RQ-20300110-002", {"compute": "cpu_light", "routing": CPU_ROUTE}),
             ("RQ-20300110-003", {"compute": "gpu", "routing": CPU_ROUTE})]       # contradicts its own routing
    dec, _ = _dry(tmp_path, monkeypatch, units, quota=QUOTA)
    a, b, c = dec["RQ-20300110-001"], dec["RQ-20300110-002"], dec["RQ-20300110-003"]
    assert a["backend"] == "kaggle" and b["backend"] == "github_runner"
    assert a["compute_source"] == "class" and a["compute_class"] == "gpu"      # the class decided, not an injected workflow
    assert a["value_derivation"].startswith("score ") and "kaggle" in a["placement"]
    assert c["outcome"] == dq.BLOCKED_ROUTE and "must agree" in c["route_reason"]


def test_gpu_unit_waits_when_quota_is_unknown_or_below_floor_and_never_blocks_the_cpu_unit(tmp_path, monkeypatch):
    units = [("RQ-20300110-001", {"compute": "gpu", "routing": GPU_ROUTE}),
             ("RQ-20300110-002", {"compute": "cpu_light", "routing": CPU_ROUTE})]
    for quota, needle in [(None, "unreadable"), (QUOTA.replace("29.98h", " 2.00h"), "floor")]:
        dec, _ = _dry(tmp_path / ("q" + str(bool(quota))), monkeypatch, units, quota=quota) \
            if (tmp_path / ("q" + str(bool(quota)))).mkdir() is None else (None, None)
        assert dec["RQ-20300110-001"]["outcome"] == dq.DEFERRED and needle in dec["RQ-20300110-001"]["reason"]
        assert dec["RQ-20300110-002"]["outcome"] == "would_dispatch"


def test_fire_dispatches_the_resolved_workflow_for_a_compute_only_unit(tmp_path, monkeypatch):
    monkeypatch.setattr(dq, "pending_stamp_units", lambda api=None: {})
    monkeypatch.setattr(dq, "declared_inputs", lambda *a, **k: ["research_unit", "power_state"])
    monkeypatch.setattr(script_run, "plan", lambda *a, **k: type("P", (), {"ok": True, "errors": []})())
    dec, fired = _dry(tmp_path, monkeypatch, [("RQ-20300110-002", {"compute": "cpu_light", "routing": CPU_ROUTE})],
                      fire=True)
    wf = [c for c in fired if c[:3] == ["gh", "workflow", "run"]]
    assert wf and wf[0][3] == "research-script-run.yml", fired
    assert dec["RQ-20300110-002"]["outcome"] == dq.DISPATCHED


def test_script_run_plan_accepts_a_compute_only_unit_and_the_kaggle_workflow(tmp_path):
    q = tmp_path / "queue"
    q.mkdir()
    _write_unit(q, "RQ-20300110-001", compute="gpu", routing=GPU_ROUTE)
    p = script_run.plan("RQ-20300110-001", run_id="1", queue_dir=q)
    assert p.ok, p.errors
    q2 = tmp_path / "queue2"
    q2.mkdir()
    _write_unit(q2, "RQ-20300110-001", run={"workflow": "research-script-run-kaggle.yml",
                                            "command": ["python3", "scripts/research/script_run.py", "--self-test"],
                                            "inputs": {"research_unit": "RQ-20300110-001"}})
    assert script_run.plan("RQ-20300110-001", run_id="1", queue_dir=q2).ok
    assert script_run.units_targeting_runner(q2) == ["RQ-20300110-001"]


def test_kaggle_workflow_keeps_the_runner_contract():
    wf = yaml.safe_load((REPO / ".github/workflows/research-script-run-kaggle.yml").read_text())
    on = wf.get("on") or wf.get(True)
    assert sorted(on["workflow_dispatch"]["inputs"]) == ["power_state", "research_unit"]
    assert wf["permissions"] == {"contents": "read"}
    assert wf["concurrency"]["group"] == "research-script-run-kaggle"
    text = (REPO / ".github/workflows/research-script-run-kaggle.yml").read_text()
    assert "${{ secrets." in text and text.count("secrets.") == 1 and "KAGGLE_API_TOKEN" in text
    assert "enable_internet" in (REPO / "scripts/research/kaggle_run.py").read_text()


def test_kaggle_bundle_is_the_tracked_repo_plus_the_unit_and_refuses_a_bad_unit(tmp_path):
    q = REPO / "research" / "queue"
    uid = next(p.stem for p in sorted(q.glob("RQ-*.yaml")) if script_run.plan(p.stem, run_id="1").ok)
    out = tmp_path / "b"
    info = kaggle_run.bundle(uid, "1", "someone", out, repo=REPO)
    assert info["files"] > 100 and (out / "repo.tar.gz").stat().st_size > 1000
    meta = json.loads((out / "dataset-metadata.json").read_text())
    assert meta["isPrivate"] is True and meta["id"] == "someone/metis-research-bundle"
    km = json.loads((tmp_path / "b-kernel" / "kernel-metadata.json").read_text())
    assert km["enable_internet"] == "false" and km["enable_gpu"] == "true" and km["is_private"] == "true"
    assert json.loads((out / "spec.json").read_text())["unit"] == uid
    with pytest.raises(SystemExit):
        kaggle_run.bundle("RQ-20300110-001", "1", "someone", tmp_path / "x", repo=REPO)


def test_collector_recognises_the_kaggle_artifact_name():
    from scripts.research import collect_runner_results as col
    m = col._ARTIFACT_RE.match("research-script-run-kaggle-RQ-20261013-9da8-01-123456")
    assert m and m.group(1) == "RQ-20261013-9da8-01" and m.group(2) == "123456"
    assert "research-script-run-kaggle.yml" in col.COLLECTED_WORKFLOWS


# ── utilization + idle-capacity fill (operator 2026-10-13: get the most out of every resource) ─────────────
def test_utilization_record_has_explicit_read_state_and_week_rolls_up(tmp_path):
    from scripts.research import research_utilization as ru
    assert ru._self_test() == 0


def test_idle_fill_pulls_an_opted_in_recurring_unit_forward_only_into_free_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(dq, "pending_stamp_units", lambda api=None: {})
    monkeypatch.setattr(dq, "declared_inputs", lambda *a, **k: ["research_unit", "power_state"])
    monkeypatch.setattr(script_run, "plan", lambda *a, **k: type("P", (), {"ok": True, "errors": []})())
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    units = [("RQ-20300110-002", {"compute": "cpu_light", "routing": CPU_ROUTE, "cadence": "daily",
                                  "last_dispatched_at": recent, "idle_fill": True}),
             ("RQ-20300110-003", {"compute": "cpu_light", "routing": CPU_ROUTE, "cadence": "daily",
                                  "last_dispatched_at": recent})]                   # not opted in: stays put
    dec, fired = _dry(tmp_path, monkeypatch, units, fire=True,
                      runs={"in_progress": [{"workflowName": "x", "createdAt": datetime.now(timezone.utc).isoformat()}]})
    assert dec["RQ-20300110-002"]["outcome"] == dq.DISPATCHED and dec["RQ-20300110-002"]["idle_fill"] is True
    assert dec["RQ-20300110-003"]["outcome"] == dq.NOT_DUE
    # no free capacity -> no fill: three runner runs already in flight
    busy = [{"workflowName": "research-script-run", "createdAt": datetime.now(timezone.utc).isoformat()}] * 3
    dec2, _ = _dry(tmp_path / "b", monkeypatch, units, fire=True, runs={"in_progress": busy}) \
        if (tmp_path / "b").mkdir() is None else (None, None)
    assert dec2["RQ-20300110-002"]["outcome"] != dq.DISPATCHED


def test_authored_units_rank_before_generated_ones_inside_a_theme():
    # RESEARCH-ENGINE-1016: a generated sweep with a large declared value used to outrank an authored unit
    # (the 1.25 hand_written_boost was the only preference). Authored first, theme shares unchanged.
    gen = job(1, workflow="research-script-run.yml", value={"usd_at_stake_per_month": 5000, "confidence": 0.9},
              routing={"est_minutes": 10}, generated={"family": "e35-bracket", "key": "k"})
    hand = job(2, workflow="research-script-run.yml", routing={"est_minutes": 60})
    assert [j.id for j in dq.fair_order([gen, hand], NOW, TH, CFG)] == [hand.id, gen.id]


def test_a_recurring_unit_waits_from_when_it_came_due_not_from_its_last_stamp():
    # A monthly re-run stamped 31 days ago has been DUE one day: it is not starved (240 h) and must not
    # jump an authored unit; it read as waiting 744 h -> starved -> first in its theme until 2026-10-16.
    stamp = (NOW - timedelta(days=31)).isoformat()
    monthly = job(1, workflow="research-script-run.yml", cadence="monthly", last_dispatched_at=stamp,
                  generated={"family": "m20-exit-lever", "key": "k"})
    hand = job(2, workflow="research-script-run.yml")
    order = dq.fair_order([monthly, hand], NOW, TH, CFG)
    assert order[0] is hand and not monthly.raw["_rank"]["starved"] and monthly.raw["_rank"]["waited_h"] == 24.0
    assert dq._due_since(monthly.raw, monthly.id) == NOW - timedelta(days=1)
    # due long enough, it still gets served first: nothing starves
    monthly.raw["last_dispatched_at"] = (NOW - timedelta(days=41)).isoformat()
    assert dq.fair_order([monthly, hand], NOW, TH, CFG)[0] is monthly
