"""vm-net-fix.yml opens nothing by default and never opens 8001 (SEC-8001-FOLLOWUPS).

Operator decisions page m3 (2026-11-12): ict-web-api binds 127.0.0.1:8001 and is
reached only through Caddy's HTTPS front. Before this fix the workflow defaulted to
opening TCP/8001 (``inputs.port`` default and a ``|| '8001'`` job-env fallback), and
its issue path compared ``github.event_name`` to ``issues`` although that path
arrives as ``repository_dispatch``, so every issue-triggered run opened 8001
whatever port its body named. One careless dispatch would have undone the lockdown.

The resolve step's shell is EXTRACTED from the workflow at test time and executed,
never copied here (``tests/test_diag_token_workflows.py`` § the same lesson).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WF = REPO / ".github" / "workflows" / "vm-net-fix.yml"


def _doc() -> dict:
    return yaml.safe_load(WF.read_text())


def _on(doc: dict) -> dict:
    # PyYAML reads the bare key `on` as boolean True.
    return doc.get("on") or doc.get(True)


def _resolve_script() -> str:
    for st in _doc()["jobs"]["fix"]["steps"]:
        if st.get("id") == "resolve":
            return st["run"]
    raise AssertionError("vm-net-fix.yml has no step id=resolve")


def _run(tmp_path, *, event: str, port_input: str = "", body: str = ""):
    env_file = tmp_path / "gh_env"
    env_file.touch()
    script = _resolve_script().replace("${{ github.event_name }}", event)
    proc = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "EVENT_NAME": event, "DASHBOARD_PORT": port_input,
             "ISSUE_BODY": body, "GITHUB_ENV": str(env_file)},
        capture_output=True, text=True, check=False,
    )
    written = dict(ln.split("=", 1) for ln in env_file.read_text().splitlines() if "=" in ln)
    return proc, written.get("DASHBOARD_PORT")


def test_no_default_port_anywhere():
    doc = _doc()
    port = _on(doc)["workflow_dispatch"]["inputs"]["port"]
    assert "default" not in port, "inputs.port must have no default"
    assert port.get("required") is True
    job_env = doc["jobs"]["fix"]["env"]["DASHBOARD_PORT"]
    assert "8001" not in job_env, f"job env must not fall back to 8001: {job_env!r}"
    text = WF.read_text()
    assert "${1:-8001}" not in text, "the remote script must not default to 8001"


@pytest.mark.parametrize("event,port_input,body", [
    ("workflow_dispatch", "", ""),
    ("repository_dispatch", "", "Operator approved. Opening the firewall."),
    ("repository_dispatch", "8001", ""),        # dispatch has no inputs; body names none
])
def test_naming_no_port_opens_nothing(tmp_path, event, port_input, body):
    proc, port = _run(tmp_path, event=event, port_input=port_input, body=body)
    assert proc.returncode != 0
    assert port is None
    assert "opens nothing by default" in proc.stdout + proc.stderr


@pytest.mark.parametrize("event,port_input,body", [
    ("workflow_dispatch", "8001", ""),
    ("workflow_dispatch", "08001", ""),
    ("repository_dispatch", "", "port: 8001"),
    ("repository_dispatch", "", "Please\n  PORT: 8001\n"),
])
def test_8001_is_refused(tmp_path, event, port_input, body):
    proc, port = _run(tmp_path, event=event, port_input=port_input, body=body)
    assert proc.returncode != 0
    assert port is None
    assert "refusing to open 8001" in proc.stdout + proc.stderr


@pytest.mark.parametrize("event,port_input,body,want", [
    ("workflow_dispatch", "443", "", "443"),
    ("repository_dispatch", "", "port: 443", "443"),      # issue path really parses now
    ("repository_dispatch", "", "first\nport: 80\nport: 443", "80"),
])
def test_named_port_resolves(tmp_path, event, port_input, body, want):
    proc, port = _run(tmp_path, event=event, port_input=port_input, body=body)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert port == want


@pytest.mark.parametrize("bad", ["0", "65536", "abc", "123456789012345678901234"])
def test_invalid_port_is_refused(tmp_path, bad):
    proc, port = _run(tmp_path, event="workflow_dispatch", port_input=bad)
    assert proc.returncode != 0 and port is None
