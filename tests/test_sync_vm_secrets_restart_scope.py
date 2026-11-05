"""sync_vm_secrets.sh restarts only the units that read the changed keys.

2026-11-05: rotating WORK_STORE_TOKEN (read only by the web API) restarted
ict-trader-live at 09:30:46Z with "cause: unknown", and the next tick breached the
60 s exit-eval restart gap. The planning functions are extracted from the shipped
script and run in bash, so this exercises the real code. Synthetic values only.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/ops/sync_vm_secrets.sh"


def _fns() -> str:
    text = SCRIPT.read_text()
    m = re.search(r'^WEB_API_ONLY_KEYS="[^"]*"\n', text, re.M)
    assert m, "WEB_API_ONLY_KEYS not found"
    out = [m.group(0)]
    for name in ("_changed_names", "_restart_scope"):
        f = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
        assert f, f"{name} not found"
        out.append(f.group(0))
    return "\n".join(out)


def _bash(code: str, **env) -> str:
    r = subprocess.run(["bash", "-c", _fns() + "\n" + code],
                       env={"PATH": "/usr/bin:/bin", **env}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_changed_names_reports_names_only(tmp_path):
    b, e = tmp_path / "bak", tmp_path / "env"
    b.write_text("A=1\nWORK_STORE_TOKEN=old-secret\nC=3\n")
    e.write_text("A=1\nWORK_STORE_TOKEN=new-secret\nC=3\nD=4\n")
    out = _bash('_changed_names "$B" "$E" A WORK_STORE_TOKEN C D', B=str(b), E=str(e))
    assert out == "WORK_STORE_TOKEN D"
    assert "secret" not in out.lower().replace("work_store_token", "")


@pytest.mark.parametrize("names,scope", [
    ("WORK_STORE_TOKEN", "web-api"),                      # the 2026-11-05 rotation
    ("BYBIT_API_KEY_1", "trader+web-api"),                # a trader key
    ("WORK_STORE_TOKEN BYBIT_API_KEY_1", "trader+web-api"),  # mixed -> both
    ("DASHBOARD_API_TOKEN", "trader+web-api"),            # not declared web-only -> both
    ("", "trader+web-api"),                               # unattributed -> never under-restart
])
def test_restart_scope(names, scope):
    assert _bash(f"_restart_scope {names}") == scope


def test_web_api_only_keys_are_not_read_outside_the_web_api():
    """The list's safety property: no trader-side code reads a key in it."""
    keys = re.search(r'^WEB_API_ONLY_KEYS="([^"]*)"', SCRIPT.read_text(), re.M).group(1).split()
    assert keys, "list is empty"
    for key in keys:
        readers = [p for p in (ROOT / "src").rglob("*.py")
                   if key in p.read_text(errors="ignore") and "src/web/" not in p.as_posix()]
        assert not readers, f"{key} is read outside src/web/: {readers}"


def test_trader_restart_writes_a_named_cause_intent():
    """The restart ping must name the sync, not 'cause: unknown'."""
    text = SCRIPT.read_text()
    i_intent = text.index("trader_restart_intent.json")
    i_restart = text.index("sudo systemctl restart ict-trader-live")
    assert i_intent < i_restart, "the intent must be written BEFORE the trader restarts"
    assert '"cause": "manual", "by": "sync-vm-secrets' in text


def test_intent_shape_is_what_restart_cause_reads(tmp_path):
    """Render the script's printf and feed it to restart_cause.determine()."""
    import time
    from src.runtime import restart_cause as rc
    line = re.search(r"printf '(\{\"cause\".*?)\\n'", SCRIPT.read_text()).group(1)
    rendered = line.replace("%s", "WORK_STORE_TOKEN BYBIT_API_KEY_1", 1).replace("%s", str(int(time.time())), 1)
    (tmp_path / "runtime_logs").mkdir()
    (tmp_path / "runtime_logs" / rc.INTENT_NAME).write_text(rendered)
    json.loads(rendered)
    out = rc.determine(tmp_path, journal=["Stopping ict-trader-live.service", "Stopped ict-trader-live.service"],
                       uptime_s=99999)
    assert out.cause == "manual" and "sync-vm-secrets (changed: WORK_STORE_TOKEN BYBIT_API_KEY_1)" in out.detail


def test_notify_run_classifies_sync_vm_secrets():
    """The sync ping used to fall through to '*) UNKNOWN ACTION' at urgent priority."""
    text = (ROOT / "scripts/ops/notify_run.sh").read_text()
    assert re.search(r"^\s+sync-vm-secrets\)\n", text, re.M)
