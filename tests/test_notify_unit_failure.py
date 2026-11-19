"""FIX-SA-08: the failed-unit alert logs every failure and pings once per cooldown."""
from __future__ import annotations

import json

from scripts.ops import notify_unit_failure as n


T0 = 10_000_000.0


def test_first_failure_pings_and_repeat_within_cooldown_is_suppressed(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr("scripts.send_ping.enqueue", lambda body, priority="normal", target="trader": sent.append((body, priority)))
    monkeypatch.setattr(n, "_unit_facts", lambda u: {"Result": "exit-code", "ExecMainStatus": "1"})
    assert n.run("ict-x.service", now=T0, logs=tmp_path) == "pinged"
    assert n.run("ict-x.service", now=T0 + 60, logs=tmp_path) == "suppressed"
    assert n.run("ict-y.service", now=T0 + 61, logs=tmp_path) == "pinged"   # other unit unaffected
    assert n.run("ict-x.service", now=T0 + n.COOLDOWN_S + 1, logs=tmp_path) == "pinged"
    assert len(sent) == 3 and all(p == "high" for _, p in sent) and "ict-x.service" in sent[0][0]
    rows = [json.loads(ln) for ln in (tmp_path / "unit_failures.jsonl").read_text().splitlines()]
    assert [r["pinged"] for r in rows] == [True, False, True, True]   # every failure logged, not only pinged ones


def test_bad_argument_and_exceptions_never_raise(tmp_path, monkeypatch, capsys):
    assert n.main([]) == 0 and n.main(["a b; rm -rf /"]) == 0
    monkeypatch.setattr(n, "run", lambda u: (_ for _ in ()).throw(RuntimeError("boom")))
    assert n.main(["ict-x.service"]) == 0
    assert "boom" in capsys.readouterr().err


def test_unit_failures_log_is_readable_through_the_diag_relay():
    """OA-16(b): the file the OnFailure handler writes must be on the diag
    log_file allowlist at the SAME path, or FIX-SA-08 cannot be observed."""
    from scripts.ops import notify_unit_failure
    from src.web.api.routers import diag

    # Compare against the WRITER's own resolver, not the expression the
    # allowlist entry is built from (manager review of #16389).
    assert diag._LOG_FILES["unit_failures"] == notify_unit_failure._logs_dir() / "unit_failures.jsonl"


# PI-20261004-GCFA5DOR-0010 (a): on the TRAINER nothing drains the local ping queue, so
# the trainer template sets UNIT_FAILURE_FORWARD=live and the ping is copied to the live VM.

class _R:
    def __init__(self, rc):
        self.returncode = rc


def test_forward_copies_the_ping_to_the_live_queue(tmp_path, monkeypatch):
    ping = tmp_path / "p1.json"
    ping.write_text("{}")
    calls = []
    monkeypatch.setenv("LIVE_VM_IP", "host.example")
    out = n.forward_to_live(ping, tmp_path, run=lambda argv, **kw: (calls.append(argv), _R(0))[1])
    assert out == "forwarded"
    assert calls[0][0] == "scp" and calls[0][-1].endswith("/pending_pings/p1.json")
    assert calls[0][-1].startswith("ubuntu@host.example:")
    rows = [json.loads(ln) for ln in (tmp_path / "unit_failures.jsonl").read_text().splitlines()]
    assert rows[-1]["forward"] == "forwarded"


def test_forward_failure_is_recorded_and_never_raises(tmp_path, monkeypatch):
    ping = tmp_path / "p2.json"
    ping.write_text("{}")
    monkeypatch.setenv("LIVE_VM_IP", "host.example")
    assert n.forward_to_live(ping, tmp_path, run=lambda argv, **kw: _R(1)) == "forward_failed"

    def boom(argv, **kw):
        raise OSError("no scp")
    assert n.forward_to_live(ping, tmp_path, run=boom) == "forward_failed"


def test_live_host_falls_back_to_the_unit_that_already_declares_it(monkeypatch):
    monkeypatch.delenv("LIVE_VM_IP", raising=False)
    assert n._live_vm_ip()  # read from deploy/trainer/ict-promotion-readiness.service, no second copy


def test_run_forwards_only_when_the_template_asks(tmp_path, monkeypatch):
    ping = tmp_path / "q.json"
    ping.write_text("{}")
    monkeypatch.setattr("scripts.send_ping.enqueue", lambda body, priority="normal", target="trader": ping)
    monkeypatch.setattr(n, "_unit_facts", lambda u: {"Result": "exit-code", "ExecMainStatus": "1"})
    seen = []
    monkeypatch.setattr(n, "forward_to_live", lambda p, logs: seen.append(p) or "forwarded")
    monkeypatch.delenv("UNIT_FAILURE_FORWARD", raising=False)
    assert n.run("ict-a.service", now=T0, logs=tmp_path) == "pinged" and seen == []
    monkeypatch.setenv("UNIT_FAILURE_FORWARD", "live")
    assert n.run("ict-b.service", now=T0, logs=tmp_path) == "pinged" and seen == [ping]


def test_trainer_template_forwards_and_installer_covers_timer_oneshots():
    from pathlib import Path
    root = Path(n.REPO_ROOT)
    tpl = (root / "deploy" / "trainer" / "ict-notify-failure@.service").read_text()
    assert "Environment=UNIT_FAILURE_FORWARD=live" in tpl and "notify_unit_failure.py %i" in tpl
    inst = (root / "scripts" / "ops" / "install_trainer_onfailure.sh").read_text()
    assert "deploy/dropins/onfailure.conf" in inst and "deploy/trainer/ict-notify-failure@.service" in inst


def test_forward_record_carries_returncode_and_redacted_stderr(tmp_path, monkeypatch):
    """2026-11-19: the 04:05Z probe logged a bare forward_failed. The record now says why."""
    ping = tmp_path / "p3.json"
    ping.write_text("{}")
    monkeypatch.setenv("LIVE_VM_IP", "10.1.2.3")

    class _Err:
        returncode = 255
        stderr = "ubuntu@10.1.2.3: Permission denied (publickey).\r\nlost connection to 192.168.0.9\n"

    assert n.forward_to_live(ping, tmp_path, run=lambda argv, **kw: _Err()) == "forward_failed"
    row = json.loads((tmp_path / "unit_failures.jsonl").read_text().splitlines()[-1])
    assert row["returncode"] == 255
    assert "Permission denied (publickey)" in row["stderr"]
    assert "10.1.2.3" not in row["stderr"] and "192.168.0.9" not in row["stderr"]
    assert "<live-host>" in row["stderr"]

    def boom(argv, **kw):
        raise OSError("no scp at 10.1.2.3")
    n.forward_to_live(ping, tmp_path, run=boom)
    row = json.loads((tmp_path / "unit_failures.jsonl").read_text().splitlines()[-1])
    assert row["returncode"] is None and row["error"] == "OSError: no scp at <live-host>"
