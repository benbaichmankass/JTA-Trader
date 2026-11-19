"""Land-time dedupe of the research-results batch (2026-11-19: #27097/#27103/#27111/#27119 closed unmerged).

The collect step checks open batch PRs at the START of a cycle; the batch lands ~12 min later by which time the previous
cycle's batch PR is open. `prune_pending` re-asks at landing time and drops those runs from the working tree.
The replay below fails on the old code (no land-time step existed: both cycles stage the same run)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import scripts.research.collect_runner_results as c


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "README").write_text("x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _stage(root: Path, unit: str, run: int) -> None:
    (root / f"research/results/{unit}/{run}.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (root / f"research/results/{unit}/{run}.jsonl").write_text("{}\n")
    d = root / f"comms/research/{unit}/{run}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "run-manifest.json").write_text("{}")


def test_alternating_cycles_replay(tmp_path):
    """Cycle B collected run 1 and 2 at 02:42:04; cycle A's PR (run 1, 3) opened 02:42:19. B's land step re-asks."""
    root = _repo(tmp_path)
    _stage(root, "RQ-X-01", 1)
    _stage(root, "RQ-X-02", 2)
    util = root / "comms/research/utilization/9.json"
    util.parent.mkdir(parents=True)
    util.write_text("{}")
    assert c.batch_count(root) == 2
    pruned = c.prune_pending(root, {("RQ-X-01", 1), ("RQ-X-99", 7)})   # 99/7 not staged here: ignored
    assert [(p["unit"], p["run_id"]) for p in pruned] == [("RQ-X-01", 1)]
    assert not (root / "research/results/RQ-X-01/1.jsonl").exists()
    assert not (root / "comms/research/RQ-X-01/1").exists() or not any((root / "comms/research/RQ-X-01/1").rglob("*.json"))
    assert (root / "research/results/RQ-X-02/2.jsonl").exists()          # the unduplicated run still lands
    assert util.exists()                                                  # the utilization receipt is carried through
    assert c.batch_count(root) == 1


def test_whole_batch_pruned_leaves_zero(tmp_path):
    root = _repo(tmp_path)
    _stage(root, "RQ-X-01", 1)
    c.prune_pending(root, {("RQ-X-01", 1)})
    assert c.batch_count(root) == 0


def test_tracked_file_is_never_deleted(tmp_path):
    root = _repo(tmp_path)
    _stage(root, "RQ-X-01", 1)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "already on main")
    assert c.prune_pending(root, {("RQ-X-01", 1)}) == []
    assert (root / "research/results/RQ-X-01/1.jsonl").exists()


def test_nothing_pending_changes_nothing(tmp_path):
    root = _repo(tmp_path)
    _stage(root, "RQ-X-01", 1)
    assert c.prune_pending(root, set()) == []
    assert c.batch_count(root) == 1


def test_workflow_wires_the_land_time_check():
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/research-queue-dispatch.yml").read_text()
    i = wf.index("--prune-pending")
    j = wf.index("id: batch")
    assert i < j and "steps.prune.outputs.count != '0'" in wf
