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
