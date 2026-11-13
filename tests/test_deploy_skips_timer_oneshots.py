"""GITSYNC-SLOW-ONESHOTS: timer-owned oneshots whose run takes minutes must be in
deploy_pull_restart.sh's DEFAULT_SKIP, because `systemctl restart` on a oneshot
runs it synchronously inside the deploy's restart loop (measured 2026-11-12:
work-digest ~6.5 min + work-report ~7.5 min per deploy, so a 900 s sync-now
timed out)."""
from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy_pull_restart.sh"


def _default_skip() -> set[str]:
    m = re.search(r'^DEFAULT_SKIP="([^"]*)"', SCRIPT.read_text(), re.M)
    assert m, "DEFAULT_SKIP assignment not found"
    return set(m.group(1).split())


def test_slow_timer_oneshots_are_skipped_by_default():
    skip = _default_skip()
    for unit in ("ict-work-digest.service", "ict-work-report.service"):
        assert unit in skip, f"{unit} would run synchronously on every deploy"


def test_long_running_money_units_are_not_skipped():
    skip = _default_skip()
    for unit in ("ict-trader-live.service", "ict-web-api.service", "ict-telegram-bot.service"):
        assert unit not in skip
