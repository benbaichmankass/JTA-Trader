"""etf-history-pipeline preflight: ssh's stderr banner must not poison the df parse (#22421, #22353),
an unreadable disk fails loudly (readfail, not lowdisk), and issue triggers use `labeled`."""
import os, re, stat, subprocess, textwrap
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parents[1]
WF = REPO / ".github/workflows"


def _script():
    wf = yaml.safe_load((WF / "etf-history-pipeline.yml").read_text())
    step = next(s for s in wf["jobs"][next(iter(wf["jobs"]))]["steps"] if s.get("id") == "disk")
    return step["run"]


def _run(tmp_path, stdout, stderr="", rc=0):
    fake = tmp_path / "bin"; fake.mkdir()
    ssh = fake / "ssh"
    ssh.write_text("#!/bin/bash\n" + (f"printf '%s\\n' {stderr!r} >&2\n" if stderr else "")
                   + f"printf '%b' {stdout!r}\nexit {rc}\n")
    ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "gh_out"; out.touch()
    env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", HOME=str(tmp_path), GITHUB_OUTPUT=str(out),
               TRAINER_IP="1.2.3.4", TRAINER_USER="u")
    (tmp_path / ".ssh").mkdir(exist_ok=True)
    r = subprocess.run(["bash", "-c", _script()], env=env, capture_output=True, text=True)
    return r, out.read_text()


def test_known_hosts_warning_on_stderr_does_not_cause_lowdisk(tmp_path):
    r, out = _run(tmp_path, "  43G  97G  56%\n1234\n",
                  stderr="Warning: Permanently added '1.2.3.4' (ED25519) to the list of known hosts.")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "go=1" in out and "avail=43" in out and "lowdisk" not in out


def test_warning_line_in_stdout_is_ignored_by_the_parse(tmp_path):
    r, out = _run(tmp_path, "Warning: Permanently added 'x' to the list of known hosts.\n  43G  97G  56%\n1234\n")
    assert r.returncode == 0 and "avail=43" in out and "go=1" in out


def test_genuinely_low_disk_is_still_lowdisk(tmp_path):
    r, out = _run(tmp_path, "  9G  97G  91%\n1234\n")
    assert "go=0" in out and "lowdisk=1" in out


def test_unreadable_disk_fails_loudly_not_as_lowdisk(tmp_path):
    r, out = _run(tmp_path, "Warning: nonsense\n", rc=255)
    assert r.returncode != 0
    assert "readfail=1" in out and "lowdisk" not in out and "could not read trainer disk" in r.stdout


def test_issue_triggered_workflows_use_labeled_with_label_name_check():
    for name, label in (("etf-history-pipeline.yml", "etf-history-request"),
                        ("options-snapshot-capture.yml", "options-snapshot-request")):
        text = (WF / name).read_text()
        wf = yaml.safe_load(text)
        on = wf.get("on", wf.get(True))
        assert on["issues"]["types"] == ["labeled"], name
        assert f"github.event.label.name == '{label}'" in text, name
