"""etf-history-pipeline preflight: ssh's stderr banner must not poison the df parse (#22421, #22353),
an unreadable disk fails loudly (readfail, not lowdisk), and issue triggers use `labeled`."""

import os
import stat
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WF = REPO / ".github/workflows"


def _script():
    wf = yaml.safe_load((WF / "etf-history-pipeline.yml").read_text())
    step = next(
        s for s in wf["jobs"][next(iter(wf["jobs"]))]["steps"] if s.get("id") == "disk"
    )
    return step["run"]


def _run(tmp_path, stdout, stderr="", rc=0):
    fake = tmp_path / "bin"
    fake.mkdir()
    ssh = fake / "ssh"
    ssh.write_text(
        "#!/bin/bash\n"
        + (f"printf '%s\\n' {stderr!r} >&2\n" if stderr else "")
        + f"printf '%b' {stdout!r}\nexit {rc}\n"
    )
    ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "gh_out"
    out.touch()
    env = dict(
        os.environ,
        PATH=f"{fake}:{os.environ['PATH']}",
        HOME=str(tmp_path),
        GITHUB_OUTPUT=str(out),
        TRAINER_IP="1.2.3.4",
        TRAINER_USER="u",
    )
    (tmp_path / ".ssh").mkdir(exist_ok=True)
    r = subprocess.run(
        ["bash", "-c", _script()], env=env, capture_output=True, text=True, check=False
    )
    return r, out.read_text()


def test_known_hosts_warning_on_stderr_does_not_cause_lowdisk(tmp_path):
    r, out = _run(
        tmp_path,
        "  43G  97G  56%\n1234\n",
        stderr="Warning: Permanently added '1.2.3.4' (ED25519) to the list of known hosts.",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "go=1" in out and "avail=43" in out and "lowdisk" not in out


def test_warning_line_in_stdout_is_ignored_by_the_parse(tmp_path):
    r, out = _run(
        tmp_path,
        "Warning: Permanently added 'x' to the list of known hosts.\n  43G  97G  56%\n1234\n",
    )
    assert r.returncode == 0 and "avail=43" in out and "go=1" in out


def test_genuinely_low_disk_is_still_lowdisk(tmp_path):
    _r, out = _run(tmp_path, "  9G  97G  91%\n1234\n")
    assert "go=0" in out and "lowdisk=1" in out


def test_unreadable_disk_fails_loudly_not_as_lowdisk(tmp_path):
    r, out = _run(tmp_path, "Warning: nonsense\n", rc=255)
    assert r.returncode != 0
    assert (
        "readfail=1" in out
        and "lowdisk" not in out
        and "could not read trainer disk" in r.stdout
    )


def test_issue_triggered_workflows_use_labeled_with_label_name_check():
    for name, label in (
        ("etf-history-pipeline.yml", "etf-history-request"),
        ("options-snapshot-capture.yml", "options-snapshot-request"),
    ):
        text = (WF / name).read_text()
        wf = yaml.safe_load(text)
        on = wf.get("on", wf.get(True))
        # Issue fan-out phase 2 (PI-20261112-FANOUT2-0001): the issue event reaches these
        # workflows through issue-router.yml as one repository_dispatch per ADDED label, so
        # `labeled` (never `opened`, #22406) is now the dispatch type `labeled:<label>`.
        assert "issues" not in on, f"{name}: should be routed, not on raw issue events"
        assert on["repository_dispatch"]["types"] == [f"labeled:{label}"], name
        assert f"github.event.client_payload.label.name == '{label}'" in text, name


def test_options_snapshot_installs_pyyaml_and_probe_fails_loudly():
    """#22442: capture_options_snapshot imports data_universe -> yaml; the install step lacked pyyaml and `| tee` (no pipefail)
    hid the crash, so the probe 'succeeded' with an empty probe.json."""
    wf = yaml.safe_load((WF / "options-snapshot-capture.yml").read_text())
    steps = wf["jobs"]["options-snapshot"]["steps"]
    install = next(s for s in steps if s.get("name") == "Install deps")
    assert "pyyaml" in install["run"]
    probe = next(s for s in steps if str(s.get("name", "")).startswith("Probe"))
    assert "pipefail" in probe["run"]


def test_concurrency_is_job_level_so_skipped_issue_events_cannot_cancel_a_real_request():
    for name in ("etf-history-pipeline.yml", "options-snapshot-capture.yml"):
        wf = yaml.safe_load((WF / name).read_text())
        assert "concurrency" not in wf, (
            f"{name}: workflow-level concurrency lets skipped events cancel a pending real run"
        )
        job = next(iter(wf["jobs"].values()))
        assert job["concurrency"]["cancel-in-progress"] is False


def test_backfill_continues_itself_and_has_a_backstop_schedule():
    text = (WF / "etf-history-pipeline.yml").read_text()
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True))
    assert {"cron": "37 */6 * * *"} in on["schedule"]
    assert wf["permissions"]["actions"] == "write"
    steps = next(iter(wf["jobs"].values()))["steps"]
    cont = next(s for s in steps if s.get("id") == "cont")
    assert "gh workflow run etf-history-pipeline.yml -f mode=backfill" in cont["run"]
    assert (
        "NO progress" in cont["run"]
    )  # a no-progress run is never re-dispatched in a hot loop
    red = next(s for s in steps if str(s.get("name", "")).startswith("Red flag"))
    assert (
        "steps.cont.outputs.continuing" in red["if"]
    )  # intermediate runs with pending series are not red
    assert "--max-new 60 --workers 6" in text


def test_hf_storage_limit_is_described_in_full_and_not_retried():
    """Run 41552388391 chunks 3-4: the reason ('Private storage limit reached') sat after a newline that str(e)[:300] cut off,
    and the upload was retried with sleeps although waiting can never free space."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hf_publish_t", REPO / "scripts" / "data_lake" / "hf_publish.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Resp:
        status_code = 403

    class Quota(Exception):
        response = Resp()

    q = Quota(
        "(Request ID: Root=1-abc)\n\n403 Forbidden: Private storage limit reached for user bentzbk, please upgrade your plan"
    )
    msg, retryable = mod.describe_hf_error(q)
    assert (
        "Private storage limit reached for user bentzbk" in msg
        and "HTTP 403" in msg
        and "Quota" in msg
    )
    assert retryable is False
    assert mod.describe_hf_error(RuntimeError("HTTP 500 gateway timeout"))[1] is True
    assert "LAKE=0" in (WF / "etf-history-pipeline.yml").read_text()


def test_etf_lake_publish_is_off_by_default_with_one_switch():
    """Operator decision 2026-11-03: the TRAINER is the ETF 1m store of record; HF lake publish is OFF (one switch), so an
    expected storage-quota refusal cannot turn every run red."""
    text = (WF / "etf-history-pipeline.yml").read_text()
    wf = yaml.safe_load(text)
    assert wf["env"]["ETF_LAKE_PUBLISH"] == "0"
    fetch = next(
        s for s in next(iter(wf["jobs"].values()))["steps"] if s.get("id") == "fetch"
    )
    assert (
        '"${ETF_LAKE_PUBLISH:-0}" = "1"' in fetch["run"]
    )  # the lake attempt is gated on the switch
    assert "TRAINER" in fetch["name"] and "OFF by default" in fetch["name"]
    assert (
        'rsync -a --partial -e "$SSH" chunk/ "$DEST"' in fetch["run"]
    )  # lake off => the chunk is pushed to the trainer in full
    assert (
        "$(date" in fetch["run"] and "-lt 10" in fetch["run"]
    )  # the 10 GB mid-run stop floor is unchanged
    assert "-ge 15" in text  # and so is the 15 GB start floor
