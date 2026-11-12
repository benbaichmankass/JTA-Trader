"""MANAGER-VM-DIRECT-OPS: the direct ops channel (src/runtime/ops_actions.py + /api/bot/ops/*)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.runtime import ops_actions as ops

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 12, 6, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("OPS_CHANNEL_DIR", str(tmp_path / "ops"))
    return tmp_path / "ops"


def body(action, params=None, quote=None, **kw):
    b = {"action": action, "params": params or {}, "session": "test-session", "reason": "a test"}
    if quote is not None:
        b["operator_quote"] = quote
    b.update(kw)
    return b


def queued(root):
    return sorted(p.stem for p in (root / "queue").glob("OPS-*.json"))


# ─────────────────────────────────────────────────────────────── submit

def test_tier1_runs_at_once(root):
    job = ops.submit(body("sync-now"), root=root, now=T0)
    assert job["state"] == ops.QUEUED and job["tier"] == 1 and job["authority"] == "tier1_autorun"
    assert queued(root) == [job["job_id"]]
    assert re.match(ops.JOB_ID_RE, job["job_id"])


def test_tier1_waits_when_autorun_is_off(root, monkeypatch):
    monkeypatch.setattr(ops, "TIER1_AUTORUN", False)
    job = ops.submit(body("sync-now"), root=root, now=T0)
    assert job["state"] == ops.AWAITING and job["approval"]["state"] == "offer_queued"


def test_tier2_without_a_quote_awaits_and_the_runner_only_offers(root, ta_root):
    job = ops.submit(body("restart-service", {"service": "ict-web-api"}), root=root, now=T0)
    assert job["state"] == ops.AWAITING and queued(root) == [job["job_id"]]   # queued for the OFFER only
    sent, ran = [], []
    ops.run_queue(root=root, send=lambda t, m: sent.append((t, m)) or True,
                  runners={"run_restart_service": lambda j: ran.append(j) or {"exit": 0}})
    assert not ran and queued(root) == []
    rec = ops.read_job(job["job_id"], root=root)
    assert rec["state"] == ops.AWAITING and rec["approval"]["card_sent"] is True and "token" not in rec["approval"]
    text, markup = sent[0]
    assert "restart-service" in text and job["job_id"] in text
    from src.runtime import trade_approvals as ta
    cbs = [b["callback_data"] for b in markup["inline_keyboard"][0]]
    assert all(ta.CB_RE.match(c) for c in cbs)     # the phase-1 tapv buttons, not a second scheme


def test_tier2_with_the_operators_quote_queues(root):
    job = ops.submit(body("restart-service", {"service": "ict-web-api.service"}, quote="yes, restart the api"),
                     root=root, now=T0)
    assert job["state"] == ops.QUEUED and job["authority"] == "operator_quote"
    assert job["params"] == {"service": "ict-web-api.service"}


@pytest.mark.parametrize("name", ["set-account-mode", "config-edit", "code-edit", "promote"])
def test_tier3_and_config_edits_are_refused_by_name(root, name):
    with pytest.raises(ops.OpsError) as e:
        ops.submit(body(name), root=root)
    assert e.value.status == 403 and "git" in e.value.detail.lower() or "PR" in e.value.detail


def test_an_unported_action_points_at_the_workflow(root):
    with pytest.raises(ops.OpsError) as e:
        ops.submit(body("flatten-bybit-position"), root=root)
    assert e.value.status == 404 and "system-actions" in e.value.detail


@pytest.mark.parametrize("b,frag", [
    ({"action": "sync-now", "reason": "x"}, "session"),
    ({"action": "sync-now", "session": "s"}, "reason"),
    (body("sync-now", {"extra": 1}), "unknown param"),
    (body("restart-service", {"service": "ict-ops-runner"}), "service must be"),
    (body("restart-service", {"service": "sshd"}), "service must be"),
    (body("amend-prop-bracket", {"account": "velotrade_1", "ticket_id": "prop-manual-abcdef"}), "needs new_tp"),
    (body("amend-prop-bracket", {"account": "v 1", "ticket_id": "x", "new_tp": "1"}), "account"),
    (body("directed-action", {"package": "pkg-1", "action": "close"}), "dry_run"),
    (body("directed-action", {"package": "pkg-1", "action": "tighten_sl", "dry_run": True}), "level_required"),
    (body("live-review-row", {"row": {"review_id": "nope"}}), "review_id must look like"),
])
def test_bad_calls_are_400(root, b, frag):
    with pytest.raises(ops.OpsError) as e:
        ops.submit(b, root=root)
    assert e.value.status == 400 and frag in e.value.detail, e.value.detail


def test_a_valid_directed_action_awaits_approval(root):
    job = ops.submit(body("directed-action", {"package": "pkg-6df5f9dfb83e47b8", "action": "close",
                                              "dry_run": True}), root=root, now=T0)
    assert job["state"] == ops.AWAITING and job["params"]["order_package_id"] == "pkg-6df5f9dfb83e47b8"


ROW = {"review_id": "LR-20261112T0600Z-pkg-6df5f9dfb83e47b8", "order_package_id": "pkg-6df5f9dfb83e47b8",
       "recommendation": {"action": "close"}, "disposition": {"route": "recommended"},
       "mechanics": {"verdict": "match"}, "reviewed_at": "2026-11-12T06:00:00Z"}


def test_a_duplicate_review_row_is_409(root):
    row = dict(ROW)
    first = ops.submit(body("live-review-row", {"row": row}), root=root, now=T0)
    assert first["state"] == ops.QUEUED
    with pytest.raises(ops.OpsError) as e:
        ops.submit(body("live-review-row", {"row": row}), root=root, now=T0)
    assert e.value.status == 409 and first["job_id"] in e.value.detail


# ─────────────────────────────────────────────────────────────── the phase-1 ask (trade_approvals)

@pytest.fixture
def ta_root(tmp_path, monkeypatch):
    from src.runtime import trade_approvals as ta
    r = tmp_path / "trade_approvals"
    monkeypatch.setattr(ta, "_root", lambda: r)
    return r


def _awaiting(root, now=T0):
    from src.runtime import trade_approvals as ta
    job = ops.submit(body("restart-service", {"service": "ict-web-api"}), root=root, now=now)
    ops.run_queue(root=root, send=lambda t, m: True)
    token = json.loads(ops.job_path(job["job_id"], root).read_text())["approval"]["token"]
    assert ta.read_pending()["asks"][token]["kind"] == ta.OPS_KIND
    return job, token


def test_approve_queues_the_job_with_the_tap_as_authority(root, ta_root):
    from src.runtime import trade_approvals as ta
    job, token = _awaiting(root)
    out = ta.decide(token, "approve", authorised=True, source="telegram")
    assert out["outcome"] == "approved", out
    rec = ops.read_job(job["job_id"], root=root)
    assert rec["state"] == ops.QUEUED and rec["authority"] == "telegram_approve"
    assert job["job_id"] in rec["operator_quote"] and queued(root) == [job["job_id"]]
    assert not list((ta_root / "spool").rglob("*.json"))      # an ops ask never writes a directed record
    assert ta.decide(token, "approve", authorised=True)["outcome"] == "already_approved"


def test_the_spa_surface_decides_the_same_ask(root, ta_root):
    from src.runtime import trade_approvals as ta
    job, token = _awaiting(root)
    assert ta.decide(token, "approve", authorised=True, source="spa")["outcome"] == "approved"
    assert ops.read_job(job["job_id"], root=root)["authority"] == "spa_approve"


def test_reject_unauthorised_and_expiry(root, ta_root, monkeypatch):
    from src.runtime import trade_approvals as ta
    job, token = _awaiting(root)
    assert ta.decide(token, "approve", authorised=False)["outcome"] == "unauthorized"
    assert ta.decide(token, "reject", authorised=True)["outcome"] == "rejected"
    assert ops.read_job(job["job_id"], root=root)["state"] == ops.REJECTED and queued(root) == []
    job2, token2 = _awaiting(root)
    late = datetime.now(timezone.utc) + timedelta(minutes=ta.expiry_minutes() + 1)
    assert ta.decide(token2, "approve", authorised=True, now=late)["outcome"] == "expired"
    assert ops.read_job(job2["job_id"], root=root, now=late)["state"] == ops.EXPIRED and queued(root) == []


def test_a_trade_ask_is_untouched_by_the_ops_branch(root, ta_root):
    """The ops kind is additive: a live-review ask still writes its directed record on approve."""
    from src.runtime import trade_approvals as ta
    row = dict(ROW, disposition={"route": "operator_ask"}, symbol="SOLUSDT", leg="ml_entry")
    off = ta.offer(row, send=lambda t, m: True)
    assert off["state"] == "offered"
    out = ta.decide(off["token"], "approve", authorised=True)
    assert out["outcome"] == "approved" and out["record_id"]


# ─────────────────────────────────────────────────────────────── the runner

def test_run_queue_drains_and_journals(root):
    a = ops.submit(body("sync-now"), root=root)
    b = ops.submit(body("restart-service", {"service": "ict-web-api"}, quote="ok"), root=root)
    calls = []
    runners = {"run_sync_now": lambda j: calls.append(j["action"]) or {"exit": 0, "stdout_tail": "ok"},
               "run_restart_service": lambda j: calls.append(j["action"]) or {"exit": 1, "detail": "boom"}}
    out = ops.run_queue(root=root, runners=runners)
    assert [j["state"] for j in out] == [ops.DONE, ops.FAILED] or [j["state"] for j in out] == [ops.FAILED, ops.DONE]
    assert sorted(calls) == ["restart-service", "sync-now"]
    assert queued(root) == [] and not list((root / "running").glob("*"))
    assert ops.read_job(a["job_id"], root=root)["state"] == ops.DONE
    assert ops.read_job(b["job_id"], root=root)["result"]["detail"] == "boom"
    events = [json.loads(x)["event"] for x in (root / "journal.jsonl").read_text().splitlines()]
    assert events.count("finished") == 2


def test_a_runner_exception_is_the_jobs_failure_not_the_runners(root):
    ops.submit(body("sync-now"), root=root)
    out = ops.run_queue(root=root, runners={"run_sync_now": lambda j: 1 / 0})
    assert out[0]["state"] == ops.FAILED and "ZeroDivisionError" in out[0]["result"]["detail"]


def test_run_time_refuses_a_tier2_job_without_authority(root):
    job = {"job_id": ops.new_job_id("restart-service", T0), "action": "restart-service", "tier": 2,
           "params": {"service": "ict-web-api.service"}, "state": ops.QUEUED, "operator_quote": None,
           "session": "s", "reason": "r"}
    ops.save_job(job, root)
    out = ops.run_job(job["job_id"], root=root, runners={"run_restart_service": lambda j: {"exit": 0}})
    assert out["state"] == ops.REFUSED


def test_an_interrupted_job_is_marked_failed_not_rerun(root):
    job = ops.submit(body("sync-now"), root=root)
    (root / "running").mkdir(parents=True, exist_ok=True)
    (root / "queue" / f"{job['job_id']}.json").rename(root / "running" / f"{job['job_id']}.json")
    rec = json.loads(ops.job_path(job["job_id"], root).read_text())
    rec["state"] = ops.RUNNING
    ops.save_job(rec, root)
    ops.run_queue(root=root, runners={})
    assert ops.read_job(job["job_id"], root=root)["state"] == ops.FAILED


def test_a_stuck_queue_reads_runner_not_picking_up(root):
    job = ops.submit(body("sync-now"), root=root, now=T0)
    assert ops.read_job(job["job_id"], root=root, now=T0 + timedelta(seconds=30))["read_state"] == "measured"
    late = ops.read_job(job["job_id"], root=root, now=T0 + timedelta(seconds=ops.RUNNER_LAG_S + 5))
    assert late["read_state"] == "runner_not_picking_up"


def test_read_job_rejects_junk_ids(root):
    with pytest.raises(ops.OpsError) as e:
        ops.read_job("../../etc/passwd", root=root)
    assert e.value.status == 400


def test_path_unit_watches_the_modules_queue_dir():
    unit = (ROOT / "deploy" / "ict-ops-runner.path").read_text()
    assert f"DirectoryNotEmpty={ops.VM_OPS_DIR / 'queue'}" in unit
    svc = (ROOT / "deploy" / "ict-ops-runner.service").read_text()
    assert "scripts/ops/ops_runner.py" in svc and "User=ubuntu" in svc
    inst = (ROOT / "scripts" / "install_systemd_units.sh").read_text()
    assert "deploy/*.path" in inst and "enable --now ict-ops-runner.path" in inst


def test_restartable_services_match_set_env_and_exclude_the_runner():
    src = (ROOT / "scripts" / "ops" / "set_env.sh").read_text()
    allowed = re.search(r'ALLOWED_SERVICES="([^"]+)"', src).group(1).split()
    assert set(ops.RESTARTABLE_SERVICES) == set(allowed) - {"none"}
    assert "ict-ops-runner.service" not in ops.RESTARTABLE_SERVICES


# ─────────────────────────────────────────────────────────────── action runners

def test_amend_prop_bracket_answers_not_deployed_without_its_wrapper(monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "ROOT", tmp_path)
    res = ops.run_amend_prop_bracket({"params": {}, "reason": "r", "job_id": "j", "session": "s"})
    assert res["exit"] == 3 and "not_deployed" in res["detail"]


def test_live_review_row_delegates_to_the_direct_submit(tmp_path):
    job = {"params": {"row": dict(ROW)}, "session": "lane-x", "job_id": "OPS-x"}
    d, logs = tmp_path / "direct", tmp_path / "logs"
    logs.mkdir()
    res = ops.run_live_review_row(job, direct_root=d, logs=logs)
    assert res["exit"] == 0, res
    path = d / "comms" / "live_review" / "rows" / f"{ROW['review_id']}.json"
    assert json.loads(path.read_text())["review_id"] == ROW["review_id"]
    again = ops.run_live_review_row(job, direct_root=d, logs=logs)
    assert again["exit"] == 2 and "already submitted" in again["detail"]
    (logs / "direct_rows_state.json").write_text(json.dumps({"seen": ["LR-20261112T0601Z-pkg-6df5f9dfb83e47b8"]}))
    seen = dict(ROW, review_id="LR-20261112T0601Z-pkg-6df5f9dfb83e47b8")
    res = ops.run_live_review_row({"params": {"row": seen}}, direct_root=d, logs=logs)
    assert res["exit"] == 2 and "already handled" in res["detail"]


def test_directed_action_spools_for_the_trader_and_reads_its_receipt(tmp_path):
    """The record is written into the phase-1 spool (the trader's spool-pass runs it); the job reads the receipt.
    The receipt here is produced by the real spool_pass with only the apply stubbed."""
    from scripts.ops import directed_action as dact

    spool, logs = tmp_path / "spool", tmp_path / "logs"
    job = {"job_id": "OPS-20261112T060000Z-directed-action-abcdef", "session": "mgr",
           "operator_quote": "close it now", "params": {"order_package_id": "pkg-6df5f9dfb83e47b8",
                                                       "action": "close", "scope": "package", "dry_run": False}}
    applied = []

    def trader_tick(_s):        # what the live trader's directed thread does every 2 s
        dact.spool_pass(spool, logs=logs, ping=lambda *a: None, apply_fn=lambda rec: applied.append(rec) or {
            "exit": 0, "accounts": [{"account_id": "bybit_2", "executed": True}]})

    res = ops.run_directed_action(job, spool_root=spool, receipts=logs / "receipts.jsonl", wait_s=10,
                                  sleep=trader_tick)
    assert res["exit"] == 0 and res["verdict"] == "applied", res
    assert applied[0]["operator_quote"] == "close it now" and applied[0]["directed_by"] == "ops:mgr"


def test_directed_action_without_a_receipt_says_so(tmp_path):
    job = {"job_id": "j", "session": "mgr", "operator_quote": "q",
           "params": {"order_package_id": "pkg-6df5f9dfb83e47b8", "action": "close", "scope": "package",
                      "dry_run": True}}
    res = ops.run_directed_action(job, spool_root=tmp_path / "s", receipts=tmp_path / "r.jsonl", wait_s=4,
                                  sleep=lambda s: None)
    assert res["exit"] == 3 and res["verdict"] == "no_receipt_yet"
    assert list((tmp_path / "s").rglob("DA-*.json"))


# ─────────────────────────────────────────────────────────────── the API

@pytest.fixture
def client(root, monkeypatch):
    from fastapi.testclient import TestClient

    from src.web.api import main
    monkeypatch.setenv("WORK_STORE_TOKEN", "wst")
    return TestClient(main.app, raise_server_exceptions=False)


def test_api_is_fail_closed(client, monkeypatch):
    assert client.post("/api/bot/ops/actions", json=body("sync-now")).status_code == 401
    assert client.post("/api/bot/ops/actions", json=body("sync-now"),
                       headers={"X-Work-Store-Token": "nope"}).status_code == 401
    monkeypatch.delenv("WORK_STORE_TOKEN")
    assert client.post("/api/bot/ops/actions", json=body("sync-now"),
                       headers={"X-Work-Store-Token": "wst"}).status_code == 503


def test_api_submit_and_read(client):
    h = {"X-Work-Store-Token": "wst"}
    r = client.post("/api/bot/ops/actions", json=body("sync-now"), headers=h)
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    assert client.get(f"/api/bot/ops/jobs/{jid}").status_code == 401
    g = client.get(f"/api/bot/ops/jobs/{jid}", headers=h)
    assert g.status_code == 200 and g.json()["state"] == ops.QUEUED and g.json()["read_state"] == "measured"
    assert client.post("/api/bot/ops/actions", json=body("set-account-mode"), headers=h).status_code == 403
    assert client.post("/api/bot/ops/actions", json=body("nope"), headers=h).status_code == 404
    assert client.get("/api/bot/ops/jobs/OPS-20261112T060000Z-sync-now-000000", headers=h).status_code == 404
