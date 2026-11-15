"""DIRECT-OPS-SWEEP: send-ping on the direct ops channel (no labelled issue)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.runtime import ops_actions as ops

T0 = datetime(2026, 11, 12, 17, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("OPS_CHANNEL_DIR", str(tmp_path / "ops"))
    return tmp_path / "ops"


def body(params):
    return {"action": "send-ping", "params": params, "session": "test-session", "reason": "a test"}


def test_tier1_ping_queues_at_once_with_defaults(root):
    job = ops.submit(body({"message": "hello"}), root=root, now=T0)
    assert job["state"] == ops.QUEUED and job["tier"] == 1
    assert job["params"] == {"message": "hello", "priority": "normal", "target": "claude", "kind": "",
                             "why": "", "unproven": ""}


@pytest.mark.parametrize("params,frag", [
    ({}, "message"),
    ({"message": "  "}, "message"),
    ({"message": "x" * (ops.PING_MAX_CHARS + 1)}, "at most"),
    ({"message": "m", "priority": "loud"}, "priority"),
    ({"message": "m", "target": "everyone"}, "target"),
    ({"message": "m", "kind": "state-change", "why": "w"}, "kind"),
    ({"message": "m", "kind": "decision"}, "why"),
    ({"message": "m", "unproven": "u"}, "unproven"),
    ({"message": "m", "chat_id": "1"}, "unknown param"),
])
def test_bad_ping_params_are_400_never_a_silent_default(root, params, frag):
    with pytest.raises(ops.OpsError) as e:
        ops.submit(body(params), root=root, now=T0)
    assert e.value.status == 400 and frag in e.value.detail


def _run(monkeypatch, stdout, code=0):
    seen = {}

    def fake(argv, env, timeout_s):
        seen.update(argv=argv, env=env)
        return {"exit": code, "stdout_tail": stdout}
    monkeypatch.setattr(ops, "_script", fake)
    job = {"job_id": "OPS-x", "params": ops._v_ping({"message": "hi", "kind": "decision", "why": "w",
                                                     "priority": "high"})[0]}
    return ops.run_send_ping(job), seen


def test_runner_threads_the_workflow_env_into_the_wrapper(monkeypatch):
    res, seen = _run(monkeypatch, "send-ping queued")
    assert seen["argv"][-1].endswith("scripts/ops/send_ping_action.sh")
    assert seen["env"]["ACTION_MESSAGE"] == "hi" and seen["env"]["ACTION_KIND"] == "decision"
    assert seen["env"]["ACTION_PRIORITY"] == "high" and seen["env"]["ACTION_TARGET"] == "claude"
    assert res["verdict"] == "queued"


def test_a_withheld_ping_is_not_reported_as_sent(monkeypatch):
    res, _ = _run(monkeypatch, "send-ping WITHHELD by the class limiter: window")
    assert res["verdict"] == "withheld"


def test_a_failed_wrapper_has_no_verdict(monkeypatch):
    res, _ = _run(monkeypatch, "ERROR", code=1)
    assert res["exit"] == 1 and "verdict" not in res


def test_the_wrapper_exists():
    assert (ops.ROOT / "scripts" / "ops" / "send_ping_action.sh").is_file()
