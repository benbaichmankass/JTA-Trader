"""Safety check on self-hosted runner use (row GH-CAPACITY-INFRA-RUNNER, operator popup 2026-11-03 ~10:07Z).

The repo is PUBLIC, so a self-hosted runner must never execute code from outside a pull request it trusts.
Binding rule: only workflows triggered by workflow_dispatch / issues / schedule / workflow_run may route a job to
the `jta-infra` self-hosted runner (literally, via `self-hosted`, or via vars.INFRA_RUNS_ON). Any workflow with a
pull_request / pull_request_target / push / issue_comment / merge_group / workflow_call trigger that references
it fails here. This is a guard on RUNNER USE, not a gate on trading or merging.
"""
from __future__ import annotations

from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"
ALLOWED = {"workflow_dispatch", "issues", "schedule", "workflow_run"}
MARKERS = ("self-hosted", "jta-infra", "INFRA_RUNS_ON")


def _triggers(doc: dict) -> set[str]:
    on = doc.get(True, doc.get("on"))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set((on or {}).keys())


def violations(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text())
    out = []
    bad = _triggers(doc) - ALLOWED
    for name, job in (doc.get("jobs") or {}).items():
        ro = str(job.get("runs-on", ""))
        if any(m in ro for m in MARKERS) and bad:
            out.append(f"{path.name}:{name} targets the self-hosted runner but triggers on {sorted(bad)}")
    on = doc.get(True, doc.get("on"))
    if isinstance(on, dict) and "workflow_run" in on and any(
        any(m in str(j.get("runs-on", "")) for m in MARKERS) for j in (doc.get("jobs") or {}).values()
    ):
        wr = on["workflow_run"] or {}
        # A workflow_run job always runs main's workflow file; it must not check out the triggering head.
        if "github.event.workflow_run.head_sha" in path.read_text() or "workflow_run.head_branch" in path.read_text():
            out.append(f"{path.name}: workflow_run job on the self-hosted runner references the triggering head ref")
        _ = wr
    return out


def test_no_untrusted_trigger_reaches_the_self_hosted_runner():
    found = [v for p in sorted(WF.glob("*.y*ml")) for v in violations(p)]
    assert not found, "\n".join(found)


def test_the_guard_catches_a_pull_request_workflow(tmp_path):
    p = tmp_path / "bad.yml"
    p.write_text("on: [pull_request]\njobs:\n  x:\n    runs-on: [self-hosted, jta-infra]\n    steps: []\n")
    assert violations(p)
    p.write_text("on:\n  pull_request_target:\njobs:\n  x:\n    runs-on: ${{ fromJSON(vars.INFRA_RUNS_ON || '\"ubuntu-latest\"') }}\n    steps: []\n")
    assert violations(p)
    p.write_text("on:\n  workflow_dispatch:\n  issues:\njobs:\n  x:\n    runs-on: [self-hosted, jta-infra]\n    steps: []\n")
    assert not violations(p)


def test_the_moved_set_is_what_was_approved():
    """Positive control: the guard's probe finds the approved workflows (a negative needs a denominator)."""
    users = {p.name for p in WF.glob("*.y*ml") if any(m in p.read_text() for m in ("INFRA_RUNS_ON", "jta-infra"))
             and any(any(m in str(j.get("runs-on", "")) for m in MARKERS)
                     for j in (yaml.safe_load(p.read_text()).get("jobs") or {}).values())}
    assert users == {
        "system-actions.yml", "vm-diag-snapshot.yml", "trainer-vm-diag.yml", "diag-relay-sweep.yml",
        "infra-runner-smoke.yml",
    }
    # B13 (COMPUTE-ALLOCATION): the 3 research workflows left the ops pool; research never reads vars.INFRA_RUNS_ON.
    assert not [u for u in users if u.startswith("research-")]


def test_ci_stays_hosted():
    for name in ("guards.yml", "pytest-run.yml", "pytest-collect.yml"):
        p = WF / name
        if p.exists():
            assert not any(m in p.read_text() for m in MARKERS), name
