"""schedule-keeper: the slot/dedupe logic, and that every TARGET is wired.

A target the keeper dispatches WITHOUT a dedupe job would run twice per slot
(once dispatched, once when GitHub's late cron arrives). A dedupe job whose
main job does not `needs:` it decides nothing. Both halves are pinned here.
"""
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))
import schedule_keeper as sk  # noqa: E402


def test_self_test_passes():
    r = subprocess.run([sys.executable, "scripts/ops/schedule_keeper.py", "--self-test"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_target_exists_is_scheduled_and_dedupes():
    for wf in sk.TARGETS:
        path = REPO / ".github" / "workflows" / wf
        assert path.exists(), wf
        d = yaml.safe_load(path.read_text())
        on = d.get(True) or d.get("on")
        assert on.get("schedule"), f"{wf} has no schedule"
        assert "workflow_dispatch" in on, f"{wf} cannot be dispatched by the keeper"
        for c in sk.workflow_crons(str(path)):
            sk.parse_cron(c)  # the keeper's grammar must cover every target cron
        jobs = d["jobs"]
        if sk.TARGETS[wf].get("self_dedupes"):
            # declared idempotent per slot; the reason must be real text, and such a target
            # must not ALSO carry a half-wired dedupe job
            assert len(sk.TARGETS[wf]["self_dedupes"]) > 20, wf
            assert "dedupe" not in jobs, f"{wf}: declare self_dedupes OR a dedupe job, not both"
            continue
        assert "dedupe" in jobs, f"{wf} lacks the dedupe job"
        assert jobs["dedupe"]["if"] == "github.event_name == 'schedule'"
        others = [k for k in jobs if k != "dedupe"]
        for k in others:
            needs = jobs[k].get("needs")
            needs = [needs] if isinstance(needs, str) else (needs or [])
            if "dedupe" in needs:
                cond = str(jobs[k].get("if", ""))
                assert "!cancelled()" in cond and "needs.dedupe.outputs.skip != 'true'" in cond, (
                    f"{wf}:{k} must fail OPEN (!cancelled()) and honour skip")
        assert any("dedupe" in (jobs[k].get("needs") or []) for k in others), (
            f"{wf}: no job needs dedupe, so the skip decides nothing")


def test_keeper_workflow_pages_only_on_its_paging_cron():
    d = yaml.safe_load((REPO / ".github/workflows/schedule-keeper.yml").read_text())
    crons = [s["cron"] for s in d[True]["schedule"]]
    page = [s for s in d["jobs"]["keep"]["steps"] if s.get("name", "").startswith("Page")][0]
    assert any(c in page["if"] for c in crons)
    assert "push" in d[True], "the keeper must not depend only on the scheduler it compensates for"


def test_research_slo_is_kept_planted_and_clean():
    """research-slo's `41 */2` cron never fired (2026-10-16): it must stay a keeper target.

    planted: the real target is registered with a 2-hourly-fit stale window and a declared dedupe.
    clean: a workflow that is NOT a target (a made-up one) is absent, so the check can fail.
    """
    t = sk.TARGETS["research-slo.yml"]
    assert t["stale_hours"] == 3
    assert t["self_dedupes"]
    assert "research-slo-not-a-real-workflow.yml" not in sk.TARGETS
