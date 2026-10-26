"""_patch_env_var must write secret values literally (SECRETS-SED-ESCAPE).

Synthetic values only. The function is extracted from the real scripts and run
in bash against a temp .env, so the test exercises the shipped code.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ["scripts/ops/sync_vm_secrets.sh", "scripts/ops/rotate_account_keys.sh"]

VALUES = [
    "a|b",
    "x|y|z",
    "a&b&&c",
    "back\\slash\\\\x",
    "p/q/r",
    "with space and  two",
    "it's \"quoted\" `tick` $dollar",
    "eq=ual=s",
    "|",
    "&",
    "\\&|/",
]


def _functions(script: str) -> str:
    text = (ROOT / script).read_text()
    out = []
    for name in ("_write_env_var", "_patch_env_var"):
        m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
        assert m, f"{name} not found in {script}"
        out.append(m.group(0))
    return "\n".join(out)


def _patch(script: str, env: Path, name: str, value: str) -> subprocess.CompletedProcess:
    code = _functions(script) + '\n_patch_env_var "$NAME" "$VALUE" "$ENVF"\n'
    return subprocess.run(
        ["bash", "-c", code],
        env={"NAME": name, "VALUE": value, "ENVF": str(env), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("value", VALUES)
def test_update_writes_value_literally(tmp_path, script, value):
    env = tmp_path / ".env"
    env.write_text("BEFORE=1\nFOO_KEY=old\nFOO_KEY_2=keep\nAFTER=2\n")
    r = _patch(script, env, "FOO_KEY", value)
    assert r.returncode == 0, r.stderr
    assert value not in r.stdout + r.stderr  # never echoed
    assert env.read_text() == f"BEFORE=1\nFOO_KEY={value}\nFOO_KEY_2=keep\nAFTER=2\n"


@pytest.mark.parametrize("script", SCRIPTS)
def test_append_and_idempotent(tmp_path, script):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    assert _patch(script, env, "NEW_KEY", "v|&\\/").returncode == 0
    first = env.read_text()
    assert first == "A=1\nNEW_KEY=v|&\\/\n"
    assert _patch(script, env, "NEW_KEY", "v|&\\/").returncode == 0
    assert env.read_text() == first


def test_unchanged_value_skips_write_in_sync_script(tmp_path):
    env = tmp_path / ".env"
    env.write_text("K=a|b\n")
    r = _patch(SCRIPTS[0], env, "K", "a|b")
    assert "unchanged" in r.stdout and env.read_text() == "K=a|b\n"


def test_file_mode_preserved(tmp_path):
    env = tmp_path / ".env"
    env.write_text("K=old\n")
    env.chmod(0o600)
    _patch(SCRIPTS[0], env, "K", "n|w")
    assert env.stat().st_mode & 0o777 == 0o600


def test_control_old_sed_path_fails_on_pipe(tmp_path):
    """The pre-fix expression (sed with '|' delimiter) corrupts/fails on '|'."""
    env = tmp_path / ".env"
    env.write_text("K=old\n")
    code = (
        'esc=$(printf %s "$VALUE" | sed \'s/[\\/&]/\\\\&/g\'); '
        'sed -i "s|^K=.*|K=${esc}|" "$ENVF"'
    )
    r = subprocess.run(
        ["bash", "-c", code],
        env={"VALUE": "a|b", "ENVF": str(env), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )
    assert r.returncode != 0 or env.read_text() != "K=a|b\n"
