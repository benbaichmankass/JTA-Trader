"""TRADER-RESTART-GATE (operator decision 2026-10-15, Phase 1) — black-box tests
of the per-unit trader gate in ``scripts/deploy_pull_restart.sh``.

A runtime diff restarts every long-running unit; the TRADER restarts only when
the diff since ITS OWN deployed sha touches something it loads: a ``.py`` in its
import closure, a non-``.py`` runtime path, or a ``.py`` outside src/ and
scripts/. Everything fails safe to RESTART.

``git`` and ``systemctl`` are stubbed via PATH; ``python3`` is a stub that runs
the REAL ``scripts/ops/trader_import_closure.py`` (copied into the fake repo,
with a tiny fake package and its generated closure) and no-ops everything else
(pip). Companion to test_deploy_pull_restart_runtime_gate.py.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_pull_restart.sh"
TOOL = REPO_ROOT / "scripts" / "ops" / "trader_import_closure.py"
TRADER = "ict-trader-live.service"
WEB = "ict-web-api.service"


def _stub(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def fake(tmp_path: Path):
    repo = tmp_path / "ict-trading-bot"
    for d in ("scripts/ops", "runtime_logs", "runtime_flags", "src/web", "config"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    (repo / "requirements.txt").write_text("")
    _stub(repo / "scripts" / "install_systemd_units.sh", "#!/bin/bash\nexit 0\n")
    shutil.copy(TOOL, repo / "scripts" / "ops" / "trader_import_closure.py")
    # the fake trader: src.main -> src.core (function-level); src/web is NOT loaded
    (repo / "src" / "__init__.py").write_text("")
    (repo / "src" / "main.py").write_text("def run():\n    from src import core\n")
    (repo / "src" / "core.py").write_text("X = 1\n")
    (repo / "src" / "web" / "__init__.py").write_text("")
    (repo / "src" / "web" / "router.py").write_text("Y = 2\n")
    subprocess.run([sys.executable, str(repo / "scripts/ops/trader_import_closure.py"),
                    "generate", "--root", str(repo)], check=True, capture_output=True)

    patched = (DEPLOY_SCRIPT.read_text()
               .replace('REPO_DIR="/home/ubuntu/ict-trading-bot"', f'REPO_DIR="{repo}"')
               .replace("/usr/bin/python3", "python3"))
    deploy = repo / "scripts" / "deploy_pull_restart.sh"
    deploy.write_text(patched)
    deploy.chmod(0o755)

    bindir = tmp_path / "bin"
    bindir.mkdir()
    counter = tmp_path / "counter"
    counter.write_text("0")
    diff_files = tmp_path / "diff_files"
    diff_files.write_text("")
    verify_rc = tmp_path / "verify_rc"
    verify_rc.write_text("0")
    _stub(bindir / "git", f"""#!/bin/bash
case "$1" in
  rev-parse)
    if [ "$2" = "-q" ]; then exit "$(cat "{verify_rc}")"; fi
    if [ "$2" = "--short" ]; then echo newsha8; exit 0; fi
    n=$(cat "{counter}")
    if [ "$n" = "0" ]; then echo oldsha7; echo 1 > "{counter}"; else echo newsha8; fi ;;
  diff) cat "{diff_files}" ;;
  *) exit 0 ;;
esac
""")
    restart_log = tmp_path / "restart.log"
    trader_state = tmp_path / "trader_state"
    trader_state.write_text("active")
    _stub(bindir / "systemctl", f"""#!/bin/bash
case "$1" in
  --version) echo "systemd 250" ;;
  list-units)
    if [[ "${{*: -1}}" == "ict-*.service" ]]; then
      printf '%s\\n' "{TRADER} loaded active running x" "{WEB} loaded active running x"
    fi ;;
  restart) echo "$2" >> "{restart_log}" ;;
  is-active) if [ "$2" = "{TRADER}" ]; then cat "{trader_state}"; else echo active; fi ;;
  *) exit 0 ;;
esac
""")
    _stub(bindir / "sudo", '#!/bin/bash\nwhile [[ "$1" == -* ]]; do shift; done\nexec "$@"\n')
    _stub(bindir / "python3", f"""#!/bin/bash
case "$1" in
  *trader_import_closure.py) exec "{sys.executable}" "$@" ;;
  *) exit 0 ;;
esac
""")
    return {"repo": repo, "deploy": deploy, "bindir": bindir, "restart_log": restart_log,
            "diff_files": diff_files, "verify_rc": verify_rc, "trader_state": trader_state,
            "trader_marker": repo / "runtime_logs" / "deployed_sha_trader.txt",
            "marker": repo / "runtime_logs" / "deployed_sha.txt",
            "intent": repo / "runtime_logs" / "trader_restart_intent.json"}


def _run(fake, env_extra=None):
    env = {**os.environ, "PATH": f"{fake['bindir']}:/usr/bin:/bin"}
    env.update(env_extra or {})
    return subprocess.run(["bash", str(fake["deploy"])], capture_output=True, text=True,
                          env=env, timeout=60)


def _restarted(fake):
    p = fake["restart_log"]
    return [ln.strip() for ln in p.read_text().splitlines()] if p.exists() else []


def _with_trader_marker(fake, sha="tradersha1"):
    fake["trader_marker"].write_text(sha + "\n")


def test_non_closure_src_py_skips_the_trader_but_not_the_web_api(fake):
    _with_trader_marker(fake)
    fake["diff_files"].write_text("src/web/router.py\n")
    res = _run(fake)
    assert res.returncode == 0, res.stderr
    assert _restarted(fake) == [WEB]
    assert "Trader restart gate: skip" in res.stdout
    # the skipped trader KEEPS its own older sha; every other unit advances
    assert fake["trader_marker"].read_text().strip() == "tradersha1"
    assert fake["marker"].read_text().strip() == "newsha8"
    assert not fake["intent"].exists()


def test_scripts_ops_tool_outside_the_closure_skips_the_trader(fake):
    _with_trader_marker(fake)
    fake["diff_files"].write_text("scripts/ops/some_cli.py\ndocs/x.md\n")
    res = _run(fake)
    assert res.returncode == 0, res.stderr
    assert TRADER not in _restarted(fake)


@pytest.mark.parametrize("path,why", [
    ("src/core.py", "in_closure"),                       # (a) the trader loads it
    ("config/strategies.yaml", "non_py_runtime"),         # (b)
    ("requirements.txt", "non_py_runtime"),               # (b)
    ("ml/model.py", "py_outside_src_scripts"),            # (c)
    ("tools/x.py", "py_outside_src_scripts"),             # (c)
])
def test_trader_loaded_or_unknown_paths_restart_the_trader(fake, path, why):
    _with_trader_marker(fake)
    fake["diff_files"].write_text(f"src/web/router.py\n{path}\n")
    res = _run(fake)
    assert res.returncode == 0, res.stderr
    assert TRADER in _restarted(fake)
    assert why in res.stdout
    assert fake["trader_marker"].read_text().strip() == "newsha8"


def test_cause_intent_counts_from_the_traders_own_sha(fake):
    _with_trader_marker(fake, "tradersha1")
    fake["diff_files"].write_text("src/core.py\n")
    res = _run(fake)
    assert res.returncode == 0, res.stderr
    intent = json.loads(fake["intent"].read_text())
    assert intent["from"] == "tradersha1"
    assert intent["sha"] == "newsha8"
    assert intent["unit"] == TRADER


# ---- fail-safe: when unsure, restart --------------------------------------

def test_no_trader_marker_restarts(fake):
    fake["diff_files"].write_text("src/web/router.py\n")
    res = _run(fake)
    assert TRADER in _restarted(fake), res.stdout
    assert "no resolvable trader deploy marker" in res.stdout
    assert fake["trader_marker"].read_text().strip() == "newsha8"


def test_unresolvable_trader_marker_restarts(fake):
    _with_trader_marker(fake)
    fake["verify_rc"].write_text("1")
    fake["diff_files"].write_text("src/web/router.py\n")
    res = _run(fake)
    assert TRADER in _restarted(fake), res.stdout


def test_missing_closure_file_restarts(fake):
    _with_trader_marker(fake)
    (fake["repo"] / "config" / "trader_import_closure.txt").unlink()
    fake["diff_files"].write_text("src/web/router.py\n")
    res = _run(fake)
    assert TRADER in _restarted(fake), res.stdout
    assert "missing or unreadable" in res.stdout


def test_unparsable_closure_file_restarts(fake):
    _with_trader_marker(fake)
    (fake["repo"] / "src" / "core.py").write_text("def broken(:\n")
    fake["diff_files"].write_text("src/web/router.py\n")
    res = _run(fake)
    assert TRADER in _restarted(fake), res.stdout


def test_stale_committed_closure_cannot_cause_a_skip(fake):
    """A file the live walk finds but the committed list lacks still restarts."""
    _with_trader_marker(fake)
    (fake["repo"] / "src" / "main.py").write_text(
        "def run():\n    from src import core\n    from src.web import router\n")
    fake["diff_files"].write_text("src/web/router.py\n")
    res = _run(fake)
    assert TRADER in _restarted(fake), res.stdout
    assert "committed closure is stale" in res.stdout


def test_gate_tool_missing_restarts(fake):
    _with_trader_marker(fake)
    (fake["repo"] / "scripts" / "ops" / "trader_import_closure.py").unlink()
    fake["diff_files"].write_text("src/web/router.py\n")
    res = _run(fake)
    assert TRADER in _restarted(fake), res.stdout


def test_stopped_trader_is_never_skipped(fake):
    """The deploy's revive of a crashed trader is kept."""
    _with_trader_marker(fake)
    fake["trader_state"].write_text("failed")
    fake["diff_files"].write_text("src/web/router.py\n")
    res = _run(fake)
    assert TRADER in _restarted(fake), res.stdout


def test_force_restart_bypasses_the_gate(fake):
    _with_trader_marker(fake)
    fake["diff_files"].write_text("src/web/router.py\n")
    res = _run(fake, {"DEPLOY_FORCE_RESTART": "1"})
    assert TRADER in _restarted(fake), res.stdout


def test_non_runtime_skip_path_leaves_the_trader_marker_alone(fake):
    _with_trader_marker(fake)
    fake["diff_files"].write_text("docs/x.md\n")
    assert _run(fake).returncode == 0
    assert _restarted(fake) == []
    assert fake["trader_marker"].read_text().strip() == "tradersha1"
    assert fake["marker"].read_text().strip() == "newsha8"


def test_phone_executor_only_diff_restarts_nothing(fake):
    """tools/phone-executor/ is Android source built on a GitHub runner; a
    phone-only merge must not bounce the trader (or any unit)."""
    _with_trader_marker(fake)
    fake["diff_files"].write_text(
        "tools/phone-executor/app/src/main/assets/exec.js\n"
        "tools/phone-executor/test/exec_check.js\n")
    res = _run(fake)
    assert res.returncode == 0, res.stderr
    assert _restarted(fake) == []
    assert "Non-runtime commit" in res.stdout
    assert fake["trader_marker"].read_text().strip() == "tradersha1"


def test_phone_executor_plus_web_api_change_skips_only_the_trader(fake):
    _with_trader_marker(fake)
    fake["diff_files"].write_text(
        "tools/phone-executor/app/src/main/assets/exec.js\nsrc/web/router.py\n")
    res = _run(fake)
    assert res.returncode == 0, res.stderr
    assert _restarted(fake) == [WEB]
    assert "Trader restart gate: skip" in res.stdout
