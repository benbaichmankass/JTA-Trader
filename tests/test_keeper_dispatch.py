"""KEEPER-VM-FLOOR: scripts/ops/keeper_dispatch.sh behaviour, with a fake curl (no network, no token).

The script must: stay inert (exit 0) with no env file; log only the HTTP status; never put
the token on curl's command line; exit 1 ONCE on 401/403 and then latch; never fail on other
statuses.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "keeper_dispatch.sh"
FAKE_TOKEN = "fake-test-token-not-real"


def _fake_curl(bindir: Path, status: str) -> Path:
    """A curl that records its argv and stdin, and prints the given HTTP status."""
    log = bindir / "curl.log"
    stdin_log = bindir / "curl.stdin"
    curl = bindir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$@" > "{log}"\n'
        f'cat > "{stdin_log}"\n'
        f'printf "%s" "{status}"\n'
    )
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    return log


def _run(tmp_path: Path, status: str, *, with_token: bool = True):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    argv_log = _fake_curl(bindir, status)
    env_file = tmp_path / "gh-dispatch.env"
    if with_token and not env_file.exists():  # an unchanged env file keeps a latch in force
        env_file.write_text(f"GH_DISPATCH_TOKEN={FAKE_TOKEN}\n")
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "KEEPER_DISPATCH_ENV_FILE": str(env_file),
        "KEEPER_DISPATCH_LATCH": str(tmp_path / "state" / "denied"),
    }
    p = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    return p, argv_log, tmp_path / "state" / "denied"


def test_inert_without_env_file(tmp_path):
    p, argv_log, _ = _run(tmp_path, "204", with_token=False)
    assert p.returncode == 0
    assert "inert" in p.stdout
    assert not argv_log.exists(), "no call is made without a token"


def test_204_dispatches_and_logs_status_only(tmp_path):
    p, argv_log, latch = _run(tmp_path, "204")
    assert p.returncode == 0 and "HTTP 204" in p.stdout
    argv = argv_log.read_text()
    assert "actions/workflows/schedule-keeper.yml/dispatches" in argv
    assert FAKE_TOKEN not in argv, "the token must never be on curl's command line"
    assert FAKE_TOKEN not in p.stdout + p.stderr, "the token must never be logged"
    assert (tmp_path / "bin" / "curl.stdin").read_text().startswith("Authorization: Bearer ")
    assert not latch.exists()


def test_403_fails_once_then_latches(tmp_path):
    p1, _, latch = _run(tmp_path, "403")
    assert p1.returncode == 1 and "lacks Actions write" in p1.stdout
    assert latch.exists()
    p2, _, _ = _run(tmp_path, "403")
    assert p2.returncode == 0 and "latched" in p2.stdout


def test_latch_clears_when_env_file_is_replaced(tmp_path):
    _run(tmp_path, "401")
    latch = tmp_path / "state" / "denied"
    os.utime(latch, (1, 1))  # the env file was replaced after the refusal: latch is now older
    p, _, latch = _run(tmp_path, "204")
    assert p.returncode == 0 and "HTTP 204" in p.stdout and not latch.exists()


def test_other_status_never_fails(tmp_path):
    p, _, latch = _run(tmp_path, "500")
    assert p.returncode == 0 and "not confirmed" in p.stdout
    assert not latch.exists()


def _run_active(tmp_path: Path, queued: str, in_progress: str, *, skip: bool = True, status: str = "204",
                queued_all: str | None = None, in_progress_all: str | None = None):
    """A curl that answers runs?status= reads with a total_count body: ``queued`` / ``in_progress`` for the
    windowed read (created>=), ``*_all`` (default: same) for the unwindowed one; the dispatch gets ``status``."""
    qa = queued if queued_all is None else queued_all
    ia = in_progress if in_progress_all is None else in_progress_all
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    calls = bindir / "calls.log"
    curl = bindir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        'url=""; for a in "$@"; do case "$a" in http*) url="$a";; esac; done\n'
        f'echo "$url" >> "{calls}"\n'
        "cat >/dev/null\n"
        'case "$url" in\n'
        f'  *status=queued*created=*) printf \'{{"total_count": {queued}}}\';;\n'
        f'  *status=queued*) printf \'{{"total_count": {qa}, "workflow_runs": []}}\';;\n'
        f'  *status=in_progress*created=*) printf \'{{"total_count": {in_progress}}}\';;\n'
        f'  *status=in_progress*) printf \'{{"total_count": {ia}}}\';;\n'
        f'  *) printf "%s" "{status}";;\nesac\n'
    )
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    env_file = tmp_path / "gh-dispatch.env"
    env_file.write_text(f"GH_DISPATCH_TOKEN={FAKE_TOKEN}\n")
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(tmp_path),
           "KEEPER_DISPATCH_ENV_FILE": str(env_file), "KEEPER_DISPATCH_LATCH": str(tmp_path / "state" / "denied"),
           "KEEPER_DISPATCH_WORKFLOW": "live-review-wake.yml"}
    if skip:
        env["KEEPER_DISPATCH_SKIP_IF_ACTIVE"] = "1"
    p = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    return p, (calls.read_text().splitlines() if calls.exists() else [])


def test_skip_if_active_skips_when_a_recent_run_is_queued(tmp_path):
    p, calls = _run_active(tmp_path, "1", "0")
    assert p.returncode == 0 and "skip: 1 run(s) of live-review-wake.yml created in the last 45 min" in p.stdout
    assert not any(c.endswith("/dispatches") for c in calls), "no dispatch while a recent one is queued"
    assert any("created=%3E%3D" in c for c in calls), "the count is windowed"
    assert FAKE_TOKEN not in p.stdout + p.stderr


def test_skip_if_active_dispatches_when_idle(tmp_path):
    p, calls = _run_active(tmp_path, "0", "0")
    assert p.returncode == 0 and "dispatched live-review-wake.yml (HTTP 204)" in p.stdout
    assert sum(c.endswith("/actions/workflows/live-review-wake.yml/dispatches") for c in calls) == 1


def test_a_stuck_old_queued_run_never_silences_the_wake(tmp_path):
    """Manager 2026-11-19: zombie queued runs never start; one stuck run must not skip the clock forever."""
    p, calls = _run_active(tmp_path, "0", "0", queued_all="1")
    assert "dispatched live-review-wake.yml (HTTP 204)" in p.stdout
    assert "ignoring 1 queued run(s) of live-review-wake.yml created before" in p.stdout, "the stuck run is logged"


def test_skip_if_active_unreadable_count_still_dispatches(tmp_path):
    p, calls = _run_active(tmp_path, "x", "x")
    assert "could not read queued runs" in p.stdout and "HTTP 204" in p.stdout


def test_default_never_reads_active_runs(tmp_path):
    p, calls = _run_active(tmp_path, "5", "5", skip=False)
    assert "HTTP 204" in p.stdout and not any("runs?status=" in c for c in calls)


def _run_rate(tmp_path: Path, rate_body: str):
    """A curl that answers GET /rate_limit with ``rate_body`` and the dispatch with 204."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    calls = bindir / "calls.log"
    curl = bindir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        'url=""; for a in "$@"; do case "$a" in http*) url="$a";; esac; done\n'
        f'echo "$url" >> "{calls}"\n'
        "cat >/dev/null\n"
        'case "$url" in\n'
        f"  */rate_limit) printf '%s' '{rate_body}';;\n"
        '  *) printf "%s" "204";;\nesac\n'
    )
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    env_file = tmp_path / "gh-dispatch.env"
    if not env_file.exists():  # an unchanged env file keeps a latch in force
        env_file.write_text(f"GH_DISPATCH_TOKEN={FAKE_TOKEN}\n")
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(tmp_path),
           "KEEPER_DISPATCH_ENV_FILE": str(env_file), "KEEPER_DISPATCH_LATCH": str(tmp_path / "state" / "denied")}
    p = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    return p, (calls.read_text().splitlines() if calls.exists() else [])


def test_pat_rate_sample_logs_the_core_budget_and_still_dispatches(tmp_path):
    body = '{"resources": {"core": {"limit": 5000, "used": 4123, "remaining": 877, "reset": 1795644000}}}'
    p, calls = _run_rate(tmp_path, body)
    assert "pat_rate core used=4123 remaining=877 limit=5000 reset=2026-11-25T" in p.stdout
    assert "HTTP 204" in p.stdout
    assert calls[0].endswith("/rate_limit") and calls[-1].endswith("/dispatches")
    assert FAKE_TOKEN not in p.stdout + p.stderr


def test_unreadable_rate_limit_is_logged_and_never_blocks_the_dispatch(tmp_path):
    p, calls = _run_rate(tmp_path, "not json")
    assert "pat_rate could not read GET /rate_limit" in p.stdout
    assert p.returncode == 0 and "HTTP 204" in p.stdout


def test_a_latched_token_is_not_used_for_the_rate_sample(tmp_path):
    _run(tmp_path, "403")
    p, calls = _run_rate(tmp_path, "{}")
    assert "latched" in p.stdout and not any(c.endswith("/rate_limit") for c in calls)
