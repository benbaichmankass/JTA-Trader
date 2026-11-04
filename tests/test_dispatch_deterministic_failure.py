"""PI-20261103-BCZDXJNR-0002: a unit whose script completed WITHOUT a verdict.json is not re-armed until the script changes.

Every other non-verdict cause keeps the existing MAX_NONVERDICT_RETRIES retry, and anything git cannot answer falls back
to that retry (never a silent stop on a guess).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dq_det", REPO / "scripts" / "research" / "dispatch_queue.py")
dq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dq)

NOTE = "producer_failed: no verdict.json. The script ran but did not grade its own output against RULE-X"


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "gate.py").write_text("print(1)\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "a")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()
    return tmp_path, sha


def _row(root, uid, note, sha, tool="python3 scripts/gate.py"):
    d = root / "results" / uid
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.jsonl").write_text(json.dumps({"read_state": "producer_failed", "note": note, "generated_at": "2026-11-03T10:00:00Z",
                                           "produced_by": {"tool": tool, "commit_sha": sha, "run_id": "1"}}) + "\n")
    return root / "results"


ENTRY = {"id": "RQ-1", "run": {"workflow": "research-script-run.yml", "inputs": {"command": "python3 scripts/gate.py --x 1"}}}


def test_blocks_when_script_unchanged(repo):
    root, sha = repo
    why = dq.deterministic_failure_block(ENTRY, "RQ-1", _row(root, "RQ-1", NOTE, sha), root)
    assert why and dq.UNCHANGED_SINCE_FAILURE_MARK in why and "scripts/gate.py" in why


def test_rearms_once_the_script_changes(repo):
    root, sha = repo
    res = _row(root, "RQ-1", NOTE, sha)
    (root / "scripts" / "gate.py").write_text("print(2)\n")
    _git(root, "commit", "-qam", "fix")
    assert dq.deterministic_failure_block(ENTRY, "RQ-1", res, root) is None


def test_a_changed_command_rearms(repo):
    root, sha = repo
    other = {"id": "RQ-1", "run": {"inputs": {"command": "python3 scripts/other.py"}}}
    assert dq.deterministic_failure_block(other, "RQ-1", _row(root, "RQ-1", NOTE, sha), root) is None


@pytest.mark.parametrize("note", ["producer_failed: cmd exit=1", "producer_failed: no run-manifest.json", ""])
def test_other_causes_keep_the_ordinary_retry(repo, note):
    root, sha = repo
    assert dq.deterministic_failure_block(ENTRY, "RQ-1", _row(root, "RQ-1", note, sha), root) is None


def test_unknown_sha_falls_back_to_retry(repo):
    root, _ = repo
    assert dq.deterministic_failure_block(ENTRY, "RQ-1", _row(root, "RQ-1", NOTE, "0" * 40), root) is None


def test_wired_into_is_due_before_the_retry_branch():
    src = (REPO / "scripts" / "research" / "dispatch_queue.py").read_text()
    body = src[src.index("def _is_due("):]
    assert body.index("deterministic_failure_block(entry, uid)") < body.index("attempts = nonverdict_attempts(uid)")
