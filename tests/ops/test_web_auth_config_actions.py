"""init-web-session-pepper and passkey-enrol-code (UI-UPGRADE-1-AUTH-CONFIG).

Load-bearing assertions: the pepper is generated once and NEVER overwritten, its
value (and the enrolment code) never reaches stdout/stderr/argv/audit, and the
code reaches only the SYSTEM ping.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PEPPER_SH = REPO / "scripts" / "ops" / "init_web_session_pepper.sh"
ENROL_SH = REPO / "scripts" / "ops" / "passkey_enrol_code_action.sh"
ENROL_PY = REPO / "scripts" / "ops" / "passkey_enrol_code.py"

STUBS = {
    "sudo": 'echo "sudo $*" >> "$SIM/argv.log"; [ "$1" = "-n" ] && shift; exec "$@"',
    "systemctl": 'echo "systemctl $*" >> "$SIM/argv.log"; '
                 'case "$1" in is-active) echo active ;; esac; exit 0',
}


@pytest.fixture()
def sim(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        p = bin_dir / name
        p.write_text("#!/usr/bin/env bash\n" + body + "\n")
        p.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "argv.log").write_text("")
    web_env = tmp_path / "web-api.env"
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", SIM=str(tmp_path),
               REPO_DIR=str(repo), WEB_API_ENV_FILE=str(web_env))
    return {"tmp": tmp_path, "env": env, "web_env": web_env, "repo": repo}


def _run_pepper(sim) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(PEPPER_SH)], capture_output=True, text=True, env=sim["env"])


def _pepper_in(path: Path) -> str:
    m = re.search(r"^WEB_SESSION_PEPPER=(.*)$", path.read_text(), re.M)
    return m.group(1) if m else ""


def test_pepper_set_when_absent_without_leaking_value(sim):
    sim["web_env"].write_text("OTHER=keep\n# comment\n")
    r = _run_pepper(sim)
    assert r.returncode == 0, r.stderr
    value = _pepper_in(sim["web_env"])
    assert re.fullmatch(r"[0-9a-f]{64}", value)          # 32 bytes hex, generated on-host
    assert "OTHER=keep" in sim["web_env"].read_text() and "# comment" in sim["web_env"].read_text()
    assert "PEPPER=set" in r.stdout
    argv = (sim["tmp"] / "argv.log").read_text()
    assert "restart ict-web-api.service" in argv
    for surface in (r.stdout, r.stderr, argv):
        assert value not in surface


def test_pepper_never_overwritten_and_no_restart(sim):
    sim["web_env"].write_text("WEB_SESSION_PEPPER=existing-value-123\n")
    r = _run_pepper(sim)
    assert r.returncode == 0, r.stderr
    assert _pepper_in(sim["web_env"]) == "existing-value-123"
    assert "PEPPER=already_present" in r.stdout
    assert "restart" not in (sim["tmp"] / "argv.log").read_text()
    assert "existing-value-123" not in r.stdout + r.stderr


def test_empty_pepper_is_replaced(sim):
    sim["web_env"].write_text("WEB_SESSION_PEPPER=\nOTHER=1\n")
    r = _run_pepper(sim)
    assert r.returncode == 0, r.stderr
    assert re.fullmatch(r"[0-9a-f]{64}", _pepper_in(sim["web_env"]))
    assert sim["web_env"].read_text().count("WEB_SESSION_PEPPER=") == 1


def test_missing_env_file_is_refused_not_created(sim):
    r = _run_pepper(sim)
    assert r.returncode == 1
    assert not sim["web_env"].exists()


@pytest.mark.parametrize("where,expected", [("web", "present"), ("repo", "present"), (None, "absent")])
def test_allowed_email_presence_only(sim, where, expected):
    sim["web_env"].write_text("WEB_SESSION_PEPPER=x\n" + ("ALLOWED_EMAIL=op@example.com\n" if where == "web" else ""))
    if where == "repo":
        (sim["repo"] / ".env").write_text("ALLOWED_EMAIL=op@example.com\n")
    r = _run_pepper(sim)
    assert f"ALLOWED_EMAIL={expected}" in r.stdout
    assert "op@example.com" not in r.stdout + r.stderr


def test_enrol_code_goes_only_to_system_ping(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WEB_SESSION_PEPPER", "p" * 64)
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "j.db"))
    monkeypatch.syspath_prepend(str(REPO))
    monkeypatch.syspath_prepend(str(REPO / "scripts"))
    import send_ping
    sent = []
    monkeypatch.setattr(send_ping, "enqueue", lambda body, priority="normal", target="trader", **k: sent.append((body, target)))
    spec = importlib.util.spec_from_file_location("passkey_enrol_code", ENROL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 0
    out = capsys.readouterr()
    assert out.out.strip() == "sent, valid 15 min"
    (body, target), = sent
    assert target == "system"
    code = re.search(r"\b[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}\b", body).group(0)
    assert code not in out.out + out.err
    from src.web.api import web_sessions
    assert web_sessions.consume_enrol_code(code) is True      # the pinged code is real


def test_enrol_code_without_pepper_reports_unavailable(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("WEB_SESSION_PEPPER", raising=False)
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "j.db"))
    monkeypatch.syspath_prepend(str(REPO))
    monkeypatch.syspath_prepend(str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location("passkey_enrol_code", ENROL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 2
    assert "auth_unavailable" in capsys.readouterr().out


def test_scripts_parse_and_never_echo_secrets():
    for sh in (PEPPER_SH, ENROL_SH):
        assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0
    assert "token_hex" in PEPPER_SH.read_text()
    assert "print(code)" not in ENROL_PY.read_text()
