"""AUTO-LANDING-FILES: land_pr.py writes landing files the guard accepts, and never under-declares."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ci"))
sys.path.insert(0, str(REPO / "scripts" / "ops"))
spec = importlib.util.spec_from_file_location("land_pr", REPO / "scripts" / "ops" / "land_pr.py")
lp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)
cpl = lp.cpl

WHY = "docs-only change for the landing helper test; no runtime touched"


def git(root, *a):
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "scripts/ci").mkdir(parents=True)
    (tmp_path / cpl.GUARD_REL).write_text("# guard stub\n")
    (tmp_path / "README.md").write_text("x\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def branch_with(root, branch, files):
    git(root, "checkout", "-q", "-b", branch)
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("change\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "work")


def land_and_commit(root, branch, **kw):
    res = lp.land(root, branch, "main", "session_test", WHY, **kw)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "landing files")
    return res


def test_tier1_self_passes_the_real_guard_and_keeps_the_lane_prefix(repo):
    branch = "lane/auto-demo"
    branch_with(repo, branch, ["docs/note.md"])
    res = land_and_commit(repo, branch)
    assert res["slug"] == "lane-auto-demo"          # the prefix is NOT dropped
    assert sorted(res["files"]) == [
        ".github/merge-slots/lane-auto-demo.json",
        ".github/pr-automerge-requests/lane-auto-demo.txt",
        ".github/pr-landing/lane-auto-demo.json",
    ]
    state, fails, _ = cpl.check(repo, "main", branch)
    assert (state, fails) == ("declared_self_land", [])


def test_claude_prefix_is_dropped_only_there(repo):
    branch = "claude/auto-demo"
    branch_with(repo, branch, ["docs/note.md"])
    assert land_and_commit(repo, branch)["slug"] == "auto-demo"
    assert cpl.check(repo, "main", branch)[1] == []


@pytest.mark.parametrize("path,tier,reason", [
    ("config/strategies.yaml", 3, "tier_2_3_needs_approval"),
    ("src/runtime/pipeline.py", 2, "tier_2_3_needs_approval"),
    ("scripts/ci/check_pr_landing.py", 1, "changes_landing_machinery"),
    ("scripts/some_loose_tool.py", 1, "unvouchable_paths"),
])
def test_never_declares_a_lower_tier_than_the_guard_and_the_guard_accepts_it(repo, path, tier, reason):
    branch = "claude/auto-hold"
    branch_with(repo, branch, [path])
    res = land_and_commit(repo, branch)
    d = res["declaration"]
    assert (d["tier"], d["landing"], d["hold_reason"]) == (tier, "hold", reason)
    # a hold arms nothing (R10) and claims no slot
    assert res["files"] == [".github/pr-landing/auto-hold.json"]
    state, fails, _ = cpl.check(repo, "main", branch)
    assert fails == [], fails
    assert state in ("declared_hold", "declared_needs_approval")


def test_tier_flag_can_only_raise(repo):
    branch = "claude/auto-raise"
    branch_with(repo, branch, ["docs/note.md"])
    d = lp.land(repo, branch, "main", "s", WHY, min_tier=2, dry_run=True)["declaration"]
    assert (d["tier"], d["landing"]) == (2, "hold")
    branch_with_cfg = "claude/auto-no-lower"
    git(repo, "checkout", "-q", "main")
    branch_with(repo, branch_with_cfg, ["config/strategies.yaml"])
    d = lp.land(repo, branch_with_cfg, "main", "s", WHY, min_tier=1, dry_run=True)["declaration"]
    assert d["tier"] == 3


def test_short_why_and_unreadable_diff_refuse(repo):
    branch = "claude/auto-refuse"
    branch_with(repo, branch, ["docs/note.md"])
    with pytest.raises(lp.LandError):
        lp.land(repo, branch, "main", "s", "short", dry_run=True)
    with pytest.raises(lp.LandError):
        lp.land(repo, branch, "no-such-base", "s", WHY, dry_run=True)


def test_dry_run_writes_nothing(repo):
    branch = "claude/auto-dry"
    branch_with(repo, branch, ["docs/note.md"])
    lp.land(repo, branch, "main", "s", WHY, dry_run=True)
    assert not (repo / ".github").exists()
