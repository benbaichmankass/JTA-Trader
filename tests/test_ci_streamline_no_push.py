"""CI-STREAMLINE (operator 2026-11-03): no required check re-runs on push to main.

Operator, verbatim: "We definitely don't need to run checks on code that was already approved." A push-to-main run of
pytest-run / guards / pytest-collect / repo-inventory re-tested a tree whose PR had already run the same check.

What replaces the push run, pinned here so the post-merge net cannot silently disappear:
  * pytest-run: the scheduled backstop (full suite on main when HEAD's code is not already graded), every 2 h.
  * guards: a scheduled `--all` run of main every 2 h, never cancelled.
  * pytest-collect: covered by the pytest-run backstop, which collects the whole tree.
  * repo-inventory: advisory; nothing replaces it.
The PR and merge_group triggers are untouched, so every required check still reports on every PR.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WF = REPO / ".github" / "workflows"
FOUR = ("pytest-run", "guards", "pytest-collect", "repo-inventory")


def _on(name: str) -> dict:
    d = yaml.safe_load((WF / f"{name}.yml").read_text())
    return d.get(True) or d.get("on")


def test_no_push_trigger_on_the_four():
    for wf in FOUR:
        assert "push" not in _on(wf), f"{wf}.yml re-runs on push to main -- the duplicate CI-STREAMLINE removed"


def test_prs_and_merge_queue_still_run_every_required_check():
    for wf in ("pytest-run", "guards", "pytest-collect"):
        on = _on(wf)
        assert "pull_request" in on and "merge_group" in on, wf
        assert "paths" not in (on["pull_request"] or {}), "a required check with a paths filter stays pending forever"
        assert "workflow_dispatch" in on, wf


def test_pytest_run_backstop_is_scheduled():
    on = _on("pytest-run")
    assert [c["cron"] for c in on["schedule"]] == ["13 */2 * * *"]


def test_guards_backstop_is_scheduled_whole_tree_and_never_cancelled():
    on = _on("guards")
    assert [c["cron"] for c in on["schedule"]] == ["29 */2 * * *"]
    text = (WF / "guards.yml").read_text()
    assert 'push|workflow_dispatch|schedule) EXTRA="--all"' in text, "a scheduled guards run must be --all (its diff is empty)"
    cc = yaml.safe_load(text)["concurrency"]
    assert cc["cancel-in-progress"] == "${{ github.event_name != 'schedule' }}"


def test_keeper_does_not_re_create_the_30_minute_cadence():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_sk", REPO / "scripts/ops/schedule_keeper.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.TARGETS["pytest-run.yml"]["starved_min"] >= 120
