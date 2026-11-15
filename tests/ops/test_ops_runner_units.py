"""OPS-RUNNER-START-LIMIT: a burst of ops jobs must never rate-limit the runner into a stalled channel.

Measured 2026-11-12T22:36:42Z: 13 back-to-back submissions started the path-activated oneshot more than systemd's
default 5 times in 10 s; ``start-limit-hit`` left ict-ops-runner.path failed and every later job queued.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _unit_section(text: str) -> str:
    m = re.search(r"^\[Unit\]\n(.*?)(?=^\[)", text, re.M | re.S)
    assert m, "no [Unit] section"
    return m.group(1)


def test_runner_and_watch_are_never_start_rate_limited():
    for name in ("ict-ops-runner.service", "ict-ops-runner.path"):
        unit = _unit_section((ROOT / "deploy" / name).read_text())
        assert re.search(r"^StartLimitIntervalSec=0$", unit, re.M), name


def test_installer_resets_a_failed_watch_before_re_enabling_it():
    sh = (ROOT / "scripts" / "install_systemd_units.sh").read_text()
    block = sh[sh.index("enable --now ict-ops-runner.path (ops channel queue watch)"):]
    reset, enable = block.find("reset-failed ict-ops-runner.service ict-ops-runner.path"), block.find(
        'systemctl enable --now ict-ops-runner.path')
    assert 0 <= reset < enable
