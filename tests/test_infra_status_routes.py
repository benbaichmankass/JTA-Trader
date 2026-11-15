"""GET /api/bot/health/infra and /api/bot/work/testing-queue."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.web.api import main as api_main
from src.web.api.routers import infra_status as ist

NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _touch(path, age_s=0.0, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    t = time.time() - age_s
    os.utime(path, (t, t))


@pytest.fixture
def env(tmp_path, monkeypatch):
    logs, root = tmp_path / "runtime_logs", tmp_path / "repo"
    logs.mkdir()
    (root / "config").mkdir(parents=True)
    (root / "config" / "accounts.yaml").write_text(
        "accounts:\n  ib_paper:\n    exchange: interactive_brokers\n    mode: live\n"
        "  bybit_2:\n    exchange: bybit\n    mode: live\n")
    monkeypatch.setattr(ist, "runtime_logs_dir", lambda: logs)
    monkeypatch.setattr(ist, "repo_root", lambda: str(root))
    monkeypatch.setattr(ist, "trade_journal_db_path", lambda: tmp_path / "j.db")
    return tmp_path, logs, root


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


def _by(body):
    return {c["component"]: c for c in body["components"]}


def test_nothing_readable_is_could_not_look_never_ok(env, client):
    body = client.get("/api/bot/health/infra").json()
    assert [c["component"] for c in body["components"]] == [
        "trader_vm", "ib_gateway", "phone_app", "trainer_vm", "kaggle", "hugging_face"]
    assert {c["state"] for c in body["components"]} == {"could_not_look"}
    assert body["read_state"] == "could_not_look"
    assert all(c["as_of"] is None and c["age_s"] is None for c in body["components"])
    assert body["summary"]["ok"] == 0 and body["summary"]["could_not_look"] == 6


def test_trader_heartbeat_states(env, client):
    _, logs, _ = env
    _touch(logs / "heartbeat.txt", age_s=5)
    assert _by(client.get("/api/bot/health/infra").json())["trader_vm"]["state"] == "ok"
    _touch(logs / "heartbeat.txt", age_s=10 * 86400)
    c = _by(client.get("/api/bot/health/infra").json())["trader_vm"]
    assert c["state"] == "down" and c["age_s"] > 86400


def test_ib_gateway_from_reachability_latch(env, client):
    _, logs, _ = env
    latch = logs / "account_reachability_alert_state.json"

    def put(row, last=NOW):
        latch.write_text(json.dumps({"__last_check__": last.isoformat(), "ib_paper": row}))
        return _by(client.get("/api/bot/health/infra").json())["ib_gateway"]

    assert put({"down": False, "consecutive_down": 0})["state"] == "ok"
    assert put({"down": False, "consecutive_down": 1})["state"] == "degraded"
    assert put({"down": True, "consecutive_down": 3})["state"] == "down"
    stale = put({"down": False, "consecutive_down": 0}, last=NOW - timedelta(hours=3))
    assert stale["state"] == "could_not_look"          # a stale 'ok' is NOT ok


def test_ib_gateway_no_row_for_ib_account_is_could_not_look(env, client):
    _, logs, _ = env
    (logs / "account_reachability_alert_state.json").write_text(
        json.dumps({"__last_check__": NOW.isoformat(), "bybit_2": {"down": False}}))
    assert _by(client.get("/api/bot/health/infra").json())["ib_gateway"]["state"] == "could_not_look"


def test_phone_app(env, client):
    tmp, _, _ = env
    db = tmp / "j.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE device_tokens (id INTEGER PRIMARY KEY, token TEXT, "
                 "platform TEXT, last_seen_at TEXT)")
    conn.commit()
    assert _by(client.get("/api/bot/health/infra").json())["phone_app"]["state"] == "down"
    conn.execute("INSERT INTO device_tokens VALUES (1,'t','android',?)", (_iso(NOW),))
    conn.commit()
    assert _by(client.get("/api/bot/health/infra").json())["phone_app"]["state"] == "ok"
    conn.execute("UPDATE device_tokens SET last_seen_at=?",
                 (_iso(NOW - timedelta(days=30)),))
    conn.commit()
    conn.close()
    assert _by(client.get("/api/bot/health/infra").json())["phone_app"]["state"] == "down"


def test_trainer_vm_mirror_age(env, client):
    _, logs, _ = env
    p = logs / "trainer_mirror" / "trainer_status.json"
    _touch(p, age_s=60, text=json.dumps({"last_cycle": {"outcome": "complete", "failed": 0}}))
    c = _by(client.get("/api/bot/health/infra").json())["trainer_vm"]
    assert c["state"] == "ok" and "complete" in c["detail"]
    _touch(p, age_s=1800, text="{}")
    assert _by(client.get("/api/bot/health/infra").json())["trainer_vm"]["state"] == "degraded"
    _touch(p, age_s=86400, text="{}")
    assert _by(client.get("/api/bot/health/infra").json())["trainer_vm"]["state"] == "down"


def test_kaggle_and_hf_records(env, client):
    _, _, root = env
    k = root / "comms" / "backups" / "kaggle_latest.json"
    k.parent.mkdir(parents=True)
    good = {"kinds": {"models": {"last_attempt_at": _iso(NOW - timedelta(hours=2)),
                                 "ok": True, "consecutive_failures": 0}}}
    k.write_text(json.dumps(good))
    assert _by(client.get("/api/bot/health/infra").json())["kaggle"]["state"] == "ok"
    good["kinds"]["models"]["ok"] = False
    k.write_text(json.dumps(good))
    assert _by(client.get("/api/bot/health/infra").json())["kaggle"]["state"] == "down"
    h = root / "comms" / "data_lake" / "health_latest.json"
    h.parent.mkdir(parents=True)
    h.write_text(json.dumps({"generated_at": _iso(NOW - timedelta(hours=3)),
                             "summary": {"ok": 5, "warn": 2, "fail": 0}}))
    assert _by(client.get("/api/bot/health/infra").json())["hugging_face"]["state"] == "ok"
    h.write_text(json.dumps({"generated_at": _iso(NOW - timedelta(days=10)),
                             "summary": {"ok": 5, "warn": 2, "fail": 0}}))
    c = _by(client.get("/api/bot/health/infra").json())["hugging_face"]
    assert c["state"] == "degraded" and "STALE" in c["detail"]


# ---------------------------------------------------------------- testing queue
def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_testing_queue_could_not_look_has_null_count(env, client):
    body = client.get("/api/bot/work/testing-queue").json()
    assert body["read_state"] == "could_not_look" and body["n_running"] is None
    assert body["running"] == [] and body["hf_jobs"]["read_state"] == "could_not_look"


def test_testing_queue_running_cycle_and_inflight_dispatch(env, client):
    _, logs, root = env
    mirror = logs / "trainer_mirror"
    _write_jsonl(mirror / "training_cycle.jsonl", [
        {"ts": _iso(NOW - timedelta(hours=9)), "status": "cycle_start"},
        {"ts": _iso(NOW - timedelta(hours=8)), "status": "cycle_end"},
        {"ts": _iso(NOW - timedelta(minutes=20)), "status": "cycle_start"},
    ])
    _write_jsonl(mirror / "research" / "research_runs.jsonl", [
        {"unit_id": "RQ-20261112-aaaa-01", "kind": "dispatch", "at": _iso(NOW - timedelta(hours=1)),
         "workflow": "research-script-run-kaggle"},
        {"unit_id": "RQ-20261112-bbbb-01", "kind": "dispatch", "at": _iso(NOW - timedelta(hours=3))},
        {"unit_id": "RQ-20261112-bbbb-01", "kind": "result", "at": _iso(NOW - timedelta(hours=2))},
        {"unit_id": "RQ-20261110-cccc-01", "kind": "dispatch", "at": _iso(NOW - timedelta(days=3))},
    ])
    q = root / "research" / "queue"
    q.mkdir(parents=True)
    (q / "RQ-20261112-aaaa-01.yaml").write_text("id: x\ntitle: 'Kaggle sweep A'\n")
    body = client.get("/api/bot/work/testing-queue").json()
    assert body["read_state"] == "read" and body["n_running"] == 2
    kinds = {r["id"]: r for r in body["running"]}
    unit = kinds["RQ-20261112-aaaa-01"]
    assert unit["infra"] == "kaggle" and unit["title"] == "Kaggle sweep A"
    assert any(r["kind"] == "trainer_cycle" for r in body["running"])
    assert "RQ-20261112-bbbb-01" not in kinds and "RQ-20261110-cccc-01" not in kinds


def test_orphan_cycle_start_is_not_running(env, client):
    _, logs, _ = env
    _write_jsonl(logs / "trainer_mirror" / "training_cycle.jsonl",
                 [{"ts": _iso(NOW - timedelta(hours=20)), "status": "cycle_start"}])
    body = client.get("/api/bot/work/testing-queue").json()
    assert body["running"] == [] and body["read_state"] == "partial"
    assert body["n_running"] == 0
    assert "orphan" in body["sources"][0]["detail"]
