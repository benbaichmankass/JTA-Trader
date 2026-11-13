"""VM-CHANGE-LEDGER: the VM change ledger on the ops jobs store, the write ping, the token dual-accept, the brief."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.runtime import ops_actions as ops
from src.web.api import work_store_rotation as wsr

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 12, 6, 0, 0, tzinfo=timezone.utc)
QUOTE = "Build it"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("OPS_CHANNEL_DIR", str(tmp_path / "ops"))
    return tmp_path / "ops"


def body(action, params=None, quote=QUOTE, **kw):
    b = {"action": action, "params": params or {}, "session": "lane-x", "reason": "a test", "operator_quote": quote}
    b.update(kw)
    return b


def run(root, b, result=None, notify=None):
    job = ops.submit(b, root=root, now=T0)
    spec = ops.REGISTRY[b["action"]]
    runners = dict(ops.RUNNERS)
    if result is not None:
        runners[spec.run] = lambda j: dict(result)
    ops.run_queue(root=root, runners=runners, notify=notify or (lambda t: True))
    return ops.read_job(job["job_id"], root=root)


def ledger(root):
    return ops.read_ledger(root)[0]


# ─────────────────────────────────────────────────────────────── what gets a row

def test_read_only_exec_appends_nothing_and_does_not_ping(root):
    pings = []
    j = run(root, body("exec", {"cmd": "cat /etc/hostname; df -h / | tail -1"}), {"exit": 0},
            notify=lambda t: pings.append(t) or True)
    assert j["state"] == ops.DONE and "ledger" not in j and not pings
    assert ledger(root) == []


def test_undeclared_writing_exec_is_recorded_pending_by_heuristic(root):
    j = run(root, body("exec", {"cmd": "sudo tee /etc/logrotate.d/x <<< y"}), {"exit": 0})
    assert j["ledger"] == "recorded"
    (rec,) = ledger(root)
    assert rec["event"] == "change" and rec["job_id"] == j["job_id"] and rec["durable_in_repo"] == "pending"
    assert rec["classified_by"] == "heuristic" and rec["authority"] == {"kind": "operator_quote", "quote": QUOTE}
    assert rec["session"] == "lane-x" and rec["reason"] == "a test" and rec["revert"]


def test_declaration_wins_over_the_heuristic_both_ways(root):
    run(root, body("exec", {"cmd": "sudo rm -f /tmp/scratch"}, change={"writes": False}), {"exit": 0})
    assert ledger(root) == []
    run(root, body("exec", {"cmd": "python3 scripts/x.py"},
                   change={"writes": True, "summary": "rewrote x", "touched": ["/etc/x"], "revert": "restore x",
                           "durable_in_repo": "not_needed"}), {"exit": 0})
    (rec,) = ledger(root)
    assert rec["classified_by"] == "declared" and rec["summary"] == "rewrote x" and rec["touched"] == ["/etc/x"]
    assert rec["durable_in_repo"] == "not_needed" and rec["revert"] == "restore x"


def test_a_bad_durable_value_reads_pending_never_hides_the_change(root):
    run(root, body("exec", {"cmd": "x"}, change={"writes": True, "durable_in_repo": "nope"}), {"exit": 0})
    assert ledger(root)[0]["durable_in_repo"] == "pending"


def test_failed_writes_are_recorded_and_refused_jobs_are_not(root):
    run(root, body("exec", {"cmd": "sudo systemctl restart foo"}), {"exit": 1, "detail": "boom"})
    assert ledger(root)[0]["outcome"] == ops.FAILED
    ops.submit(body("exec", {"cmd": "sudo systemctl restart foo"}, quote=None), root=root, now=T0)  # awaits approval
    assert len(ledger(root)) == 1


def test_set_env_records_before_after_and_a_revert(root):
    j = run(root, body("set-env", {"key": "PROP_PHONE_MODE_X_1", "value": "off", "service": "none"}),
            {"exit": 0, "before": "live"})
    (rec,) = ledger(root)
    assert rec["before"] == "live" and rec["after"] == "off" and rec["durable_in_repo"] == "not_needed"
    assert rec["touched"] == ["env:shared:PROP_PHONE_MODE_X_1"] and "PROP_PHONE_MODE_X_1=live" in rec["revert"]
    assert j["write_ping"] == "sent"


def test_message_and_report_actions_never_record(root):
    run(root, body("status-check", quote=None), {"exit": 0, "stdout_tail": "ok"})
    run(root, body("send-ping", {"message": "hi"}, quote=None), {"exit": 0})
    assert ledger(root) == []


def test_every_registry_action_declares_a_ledger_policy():
    for a in ops.REGISTRY.values():
        assert a.ledger in ("never", "always", "exec"), a.name
        assert a.durable_default in ops.DURABLE_STATES, a.name
    assert ops.REGISTRY["exec"].ledger == "exec" and ops.REGISTRY["exec"].durable_default == "pending"
    assert ops.REGISTRY["set-env"].ledger == "always"


# ─────────────────────────────────────────────────────────────── the ping is a notification, never a gate

def test_write_ping_carries_job_session_command_and_authority(root):
    pings = []
    cmd = "sudo sed -i s/a/b/ /etc/x; " + "y" * 400
    j = run(root, body("exec", {"cmd": cmd}), {"exit": 0}, notify=lambda t: pings.append(t) or True)
    (text,) = pings
    assert j["job_id"] in text and "lane-x" in text and QUOTE in text and "regardless" in text
    assert cmd[:ops.PING_CMD_CHARS] in text and cmd[:ops.PING_CMD_CHARS + 1] not in text


def test_a_failing_ping_never_stops_the_job(root):
    def boom(_t):
        raise RuntimeError("telegram down")
    ran = []
    job = ops.submit(body("exec", {"cmd": "sudo rm /tmp/x"}), root=root, now=T0)
    ops.run_queue(root=root, runners={**ops.RUNNERS, "run_exec": lambda j: ran.append(1) or {"exit": 0}},
                  notify=boom)
    rec = ops.read_job(job["job_id"], root=root)
    assert ran == [1] and rec["state"] == ops.DONE and rec["write_ping"] == "not_delivered"


def test_the_sender_is_registered_with_the_channel_map():
    from src.runtime import telegram_channels as tc
    assert tc.SENDERS.get("src/runtime/ops_actions.py") == ("system_action",)


# ─────────────────────────────────────────────────────────────── backfill / fold / view

def test_backfill_then_fold_then_view(root):
    run(root, body("ledger-backfill", {"job_id": "OPS-20261112T204454Z-exec-e9f0f4", "at": "2026-11-12T20:45:57Z",
                                       "action": "exec", "summary": "syslog cap", "touched": ["/etc/x"],
                                       "revert": "restore backup", "durable_in_repo": "pending",
                                       "authority": "operator quote"}, quote=None))
    v = ops.ledger_view(root, now=T0 + timedelta(days=2))
    (e,) = v["entries"]
    assert e["durable_in_repo"] == "pending" and e["fold_due"] and v["counts"]["fold_due"] == 1
    j = run(root, body("ledger-fold", {"job_id": "OPS-20261112T204454Z-exec-e9f0f4", "durable_in_repo": "folded",
                                       "ref": "deploy/logrotate/ict-syslog-cap"}, quote=None))
    assert j["state"] == ops.DONE
    v = ops.ledger_view(root, now=T0 + timedelta(days=2))
    (e,) = v["entries"]
    assert e["durable_in_repo"] == "folded" and e["fold_ref"] == "deploy/logrotate/ict-syslog-cap" and not e["fold_due"]
    assert v["counts"] == {"entries": 1, "pending": 0, "folded": 1, "not_needed": 0, "fold_due": 0}
    assert [r["event"] for r in ledger(root)] == ["backfill", "fold"]      # append-only: nothing rewritten


def test_fold_of_an_unknown_entry_fails_and_folded_needs_a_ref(root):
    j = run(root, body("ledger-fold", {"job_id": "LEDGER-20261112T000000Z-abcdef", "durable_in_repo": "not_needed"},
                       quote=None))
    assert j["state"] == ops.FAILED and "no ledger entry" in j["result"]["detail"]
    with pytest.raises(ops.OpsError) as e:
        ops.submit(body("ledger-fold", {"job_id": "LEDGER-20261112T000000Z-abcdef", "durable_in_repo": "folded"}),
                   root=root, now=T0)
    assert "ref" in e.value.detail


def test_backfill_mints_an_id_and_requires_the_essentials(root):
    with pytest.raises(ops.OpsError):
        ops.submit(body("ledger-backfill", {"summary": "x"}), root=root, now=T0)
    j = run(root, body("ledger-backfill", {"summary": "x", "revert": "y", "durable_in_repo": "not_needed",
                                           "authority": "z"}, quote=None))
    assert j["result"]["ledger_job_id"].startswith("LEDGER-")


def test_fresh_pending_is_not_due_yet(root):
    run(root, body("exec", {"cmd": "sudo rm /tmp/x"}), {"exit": 0})
    assert ops.ledger_view(root)["counts"]["fold_due"] == 0
    assert ops.ledger_view(root, now=datetime.now(timezone.utc) + timedelta(hours=25))["counts"]["fold_due"] == 1


def test_read_states_say_whether_we_looked(tmp_path):
    assert ops.read_ledger(tmp_path / "nope")[1] == "could_not_look"
    (tmp_path / "ops").mkdir()
    assert ops.read_ledger(tmp_path / "ops")[1] == "absent"
    (tmp_path / "ops" / "ledger.jsonl").write_text('{"job_id":"A","event":"change"}\nnot json\n')
    recs, st, bad = ops.read_ledger(tmp_path / "ops")
    assert st == "measured" and len(recs) == 1 and bad == 1


# ─────────────────────────────────────────────────────────────── the heuristic, on today's real commands

@pytest.mark.parametrize("cmd,writes", [
    ("set -e; sudo cp -a /etc/logrotate.d/rsyslog /var/backups/x && sudo sed -i '/a/d' /etc/logrotate.d/rsyslog", True),
    ("printf 'a' | sudo tee /etc/logrotate.d/ict-syslog-cap >/dev/null", True),
    ("sudo logrotate -f /etc/logrotate.d/ict-syslog-cap", True),
    ("echo x >> /home/ubuntu/ict-trading-bot/.env", True),
    ("git gc --prune=now", True),
    ("sudo systemctl restart ict-web-api", True),
    ("git rev-parse --short HEAD; hostname; uptime", False),
    ("pgrep -af 'git (gc|repack)' || echo NO_GC; ls -la .git/gc.log 2>&1; du -sh .git; df -h / | tail -1", False),
    ("cat /etc/logrotate.d/rsyslog 2>/dev/null; journalctl -u x -n 40 --no-pager", False),
    ("systemctl is-active ict-web-api; git log -3 --oneline", False),
])
def test_looks_mutating(cmd, writes):
    assert ops.looks_mutating(cmd) is writes


# ─────────────────────────────────────────────────────────────── token rotation, VM side

def test_stage_token_rotation_copies_current_to_prev_and_never_prints_it(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nWORK_STORE_TOKEN=s3cret-value\nB=2\n")
    env.chmod(0o600)
    res = wsr.stage(env, now=T0)
    text = env.read_text()
    assert res["exit"] == 0 and "WORK_STORE_TOKEN_PREV=s3cret-value" in text and "WORK_STORE_TOKEN=s3cret-value" in text
    assert "WORK_STORE_TOKEN_PREV_UNTIL=2026-11-15T06:00:00Z" in text and "A=1" in text and "B=2" in text
    assert "s3cret" not in json.dumps(res) and (env.stat().st_mode & 0o777) == 0o600
    assert wsr.stage(env, now=T0)["exit"] == 0   # idempotent
    assert env.read_text().count("WORK_STORE_TOKEN_PREV=") == 1


def test_stage_refuses_without_a_current_token(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    assert wsr.stage(env, now=T0)["exit"] == 2


def test_dual_accept_honours_prev_only_until_its_expiry(monkeypatch):
    from src.web.api.routers import work_items as wi
    monkeypatch.setenv("WORK_STORE_TOKEN", "new")
    monkeypatch.setenv("WORK_STORE_TOKEN_PREV", "old")
    monkeypatch.setenv("WORK_STORE_TOKEN_PREV_UNTIL", "2026-11-15T06:00:00Z")
    before, after = T0.timestamp(), (T0 + timedelta(days=4)).timestamp()
    assert wi.accepted_work_store_tokens(before) == ["new", "old"]
    assert wi.accepted_work_store_tokens(after) == ["new"]
    monkeypatch.setenv("WORK_STORE_TOKEN_PREV_UNTIL", "garbage")
    assert wi.accepted_work_store_tokens(before) == ["new"]                # no open-ended second token
    monkeypatch.delenv("WORK_STORE_TOKEN")
    assert wi.accepted_work_store_tokens(before) == []                     # PREV alone never configures writes


def test_route_accepts_prev_during_the_window(monkeypatch):
    from fastapi import HTTPException
    from src.web.api.routers import work_items as wi
    monkeypatch.setenv("WORK_STORE_TOKEN", "new")
    monkeypatch.setenv("WORK_STORE_TOKEN_PREV", "old")
    monkeypatch.setenv("WORK_STORE_TOKEN_PREV_UNTIL", "2099-01-01T00:00:00Z")
    wi._require_work_store_token(None, "old")
    wi._require_work_store_token(None, "new")
    with pytest.raises(HTTPException) as e:
        wi._require_work_store_token(None, "other")
    assert e.value.status_code == 401


# ─────────────────────────────────────────────────────────────── surfaces

def test_pipeline_vm_ledger_due_shape_and_brief_lines(root):
    from scripts.ops import pipeline
    from scripts.ops import render_daily_brief as rdb
    run(root, body("exec", {"cmd": "sudo rm /tmp/x"}), {"exit": 0})
    view = ops.ledger_view(root, now=datetime.now(timezone.utc) + timedelta(days=2))
    (item,) = pipeline.vm_ledger_due(view)
    assert item["id"].startswith("VMLEDGER-OPS-") and item["next_action"] in pipeline.NEXT_ACTIONS
    assert item["origin"]["rerun"] and item["due_when"]["clears_when"]
    lines = "\n".join(rdb.vm_ledger_lines(view))
    assert "1 due" in lines and item["id"] in lines
    assert "COULD NOT LOOK" in "\n".join(rdb.vm_ledger_lines({"read_state": "could_not_look"}))
    assert pipeline.vm_ledger_due({"read_state": "unreadable"}) == []


def test_ledger_route_is_token_gated_and_filters_pending(root, monkeypatch):
    from fastapi.testclient import TestClient
    from src.web.api.main import app
    monkeypatch.setenv("WORK_STORE_TOKEN", "tok")
    run(root, body("exec", {"cmd": "sudo rm /tmp/x"}), {"exit": 0})
    run(root, body("exec", {"cmd": "sudo rm /tmp/y"}, change={"writes": True, "durable_in_repo": "not_needed"}),
        {"exit": 0})
    c = TestClient(app)
    assert c.get("/api/bot/ops/ledger").status_code == 401
    r = c.get("/api/bot/ops/ledger", headers={"X-Work-Store-Token": "tok"})
    assert r.status_code == 200 and r.json()["counts"]["entries"] == 2 and r.json()["read_state"] == "measured"
    r = c.get("/api/bot/ops/ledger?pending=1", headers={"X-Work-Store-Token": "tok"})
    assert [e["durable_in_repo"] for e in r.json()["entries"]] == ["pending"]


def test_every_set_env_key_pattern_is_documented():
    doc = (ROOT / "docs" / "reference" / "env-vars.md").read_text()
    for rx, _vals in ops.SET_ENV_KEYS:
        stem = rx.pattern.lstrip("^").split("[")[0]
        assert stem in doc, f"{stem}* is writable through set-env but not documented in docs/reference/env-vars.md"


def test_syslog_cap_fold_back_is_in_deploy():
    cap = (ROOT / "deploy" / "logrotate" / "ict-syslog-cap").read_text()
    assert cap.startswith("/var/log/syslog\n") and "maxsize 200M" in cap and "rotate 7" in cap and "daily" in cap
    assert "install_syslog_cap.sh" in (ROOT / "scripts" / "deploy_pull_restart.sh").read_text()
