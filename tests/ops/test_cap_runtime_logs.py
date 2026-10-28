"""cap-vm-logs / runtime_logs: only stale rotated logs are candidates; everything else is untouchable."""
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "ops"))
import cap_runtime_logs as c  # noqa: E402

OLD = time.time() - 60 * 86400


def _mk(root, rel, age=OLD, size=10):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    os.utime(p, (age, age))
    return p


def test_only_stale_rotated_logs_are_candidates(tmp_path):
    keep = [_mk(tmp_path, "trade_journal.db"), _mk(tmp_path, "x.sqlite-wal"),
            _mk(tmp_path, "operator_actions/a.log"), _mk(tmp_path, "pending_claude_pings/p.log"),
            _mk(tmp_path, "live.jsonl"), _mk(tmp_path, "fresh.log", age=time.time())]
    gone = [_mk(tmp_path, "svc.log", size=100), _mk(tmp_path, "shadow_predictions.2026-08-01.jsonl"),
            _mk(tmp_path, "sub/old.jsonl.gz"), _mk(tmp_path, "svc.log.1")]
    victims, totals = c.plan(tmp_path, 30)
    assert sorted(p for p, _ in victims) == sorted(gone)
    assert all(k.exists() for k in keep) and totals


def test_symlink_is_never_followed_or_deleted(tmp_path):
    target = _mk(tmp_path, "real.db")
    link = tmp_path / "old.log"
    link.symlink_to(target)
    assert c.plan(tmp_path, 30)[0] == []


def test_dry_run_deletes_nothing_and_apply_deletes_exactly_the_plan(tmp_path):
    f = _mk(tmp_path, "svc.log")
    keep = _mk(tmp_path, "live.jsonl")
    assert c.main(["--root", str(tmp_path), "--days", "30"]) == 0 and f.exists()
    assert c.main(["--root", str(tmp_path), "--days", "30", "--apply"]) == 0
    assert not f.exists() and keep.exists()


def test_wrapper_syntax_and_dry_run_default():
    w = REPO / "scripts/ops/cap_vm_logs_action.sh"
    assert subprocess.run(["bash", "-n", str(w)]).returncode == 0
    src = w.read_text()
    assert 'APPLY}" != "true"' in src and "exit 4" in src
