"""DIRECT-OPS-SWEEP: parameterless read-only § 2 reports on the direct ops channel."""
from __future__ import annotations

import pytest

from src.runtime import ops_actions as ops

REPORTS = {"status-check": "status_check.sh", "disk-usage-report": "disk_usage_report.sh",
           "list-listening-ports": "list_listening_ports.sh"}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("OPS_CHANNEL_DIR", str(tmp_path / "ops"))
    return tmp_path / "ops"


@pytest.mark.parametrize("name", sorted(REPORTS))
def test_report_is_tier1_and_its_wrapper_is_in_the_tree(name):
    spec = ops.REGISTRY[name]
    assert spec.tier == 1 and spec.extra["script"] == REPORTS[name]
    assert (ops.ROOT / "scripts" / "ops" / REPORTS[name]).is_file()


@pytest.mark.parametrize("name", sorted(REPORTS))
def test_report_takes_no_params(root, name):
    with pytest.raises(ops.OpsError) as e:
        ops.submit({"action": name, "params": {"script": "../../bin/sh"}, "session": "s", "reason": "r"},
                   root=root)
    assert e.value.status == 400 and "unknown param script" in e.value.detail
    job = ops.submit({"action": name, "params": {}, "session": "s", "reason": "r"}, root=root)
    assert job["state"] == ops.QUEUED


def test_runner_runs_the_registry_script_only(monkeypatch):
    seen = {}
    monkeypatch.setattr(ops, "_script", lambda argv, env, t: seen.update(argv=argv, env=env) or
                        {"exit": 0, "stdout_tail": "ok"})
    res = ops.run_report({"action": "disk-usage-report", "params": {}})
    assert res["exit"] == 0 and seen["argv"][-1].endswith("scripts/ops/disk_usage_report.sh") and seen["env"] == {}
