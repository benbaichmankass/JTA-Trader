"""The reset-protocol backup grades the most recent Wednesday, not "today" (a delayed cron run is Thursday)."""
import subprocess

import pytest

SCRIPT = "scripts/ops/last_wednesday.sh"


def _date(now):
    return subprocess.run(["bash", SCRIPT, now], capture_output=True, text=True, check=True).stdout.strip()


@pytest.mark.parametrize("now,want", [
    ("2026-11-05T00:03:00Z", "2026-11-04"),   # Thu 00:03Z, the observed delayed run
    ("2026-11-04T19:00:00Z", "2026-11-04"),   # Wed itself
    ("2026-11-04T00:00:00Z", "2026-11-04"),
    ("2026-11-08T12:00:00Z", "2026-11-04"),   # Sun
    ("2026-11-09T12:00:00Z", "2026-11-04"),   # Mon
    ("2026-11-03T23:59:00Z", "2026-10-28"),   # Tue, before the reset
])
def test_resolves_to_most_recent_wednesday(now, want):
    assert _date(now) == want


def test_workflow_uses_it_not_today():
    wf = open(".github/workflows/reset-protocol-backup.yml").read()
    assert wf.count("scripts/ops/last_wednesday.sh") == 2
    assert 'RESET_DATE="$(date -u +%Y-%m-%d)"' not in wf
