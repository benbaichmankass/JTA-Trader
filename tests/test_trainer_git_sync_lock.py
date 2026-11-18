"""GIT-SYNC-PRUNE-STUCK: scripts/ops/trainer_git_sync.sh and deploy_pull_restart.sh share one lock around their git
mutations (MEASURED 2026-11-16 21:53:11Z: the unlocked trainer sync collided with ict-git-sync on .git/index.lock)."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "trainer_git_sync.sh"


def _git_stub(tmp_path: Path) -> tuple[Path, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "git.log"
    stub = bindir / "git"
    stub.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit 0\n')
    stub.chmod(0o755)
    return bindir, log


def _run(tmp_path: Path, lock: Path, wait: str, bindir: Path):
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "REPO_ROOT": str(tmp_path),
           "SYNC_LOCK_FILE": str(lock), "SYNC_LOCK_WAIT_S": wait}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30)


def test_free_lock_runs_fetch_then_checkout(tmp_path):
    bindir, log = _git_stub(tmp_path)
    res = _run(tmp_path, tmp_path / "jta-sync.lock", "5", bindir)
    assert res.returncode == 0, res.stderr
    cmds = log.read_text().splitlines()
    assert cmds[0].startswith("fetch") and cmds[1].startswith("checkout"), cmds


def test_held_lock_times_out_exits_zero_and_runs_no_git(tmp_path):
    bindir, log = _git_stub(tmp_path)
    lock = tmp_path / "jta-sync.lock"
    holder = subprocess.Popen(["flock", str(lock), "sleep", "20"])
    try:
        time.sleep(0.5)
        res = _run(tmp_path, lock, "1", bindir)
    finally:
        holder.kill()
        holder.wait()
    assert res.returncode == 0, res.stderr
    assert "skipping this tick" in res.stdout
    assert not log.exists()
