#!/usr/bin/env python3
"""Refresh or retire CONFLICTED research-queue stamp PRs, every dispatcher cycle.

AUTOMATION-DATACOMMIT-CONFLICT (manager-approved design, 2026-11-19). The dispatcher lands its stamps
through ``commit-to-main`` with ``verify-merged: "false"``, so commit-to-main's stale-branch refresh --
the one place ``resolve_stamp_conflicts.py`` runs -- never runs for a stamp PR. A stamp PR that a later
stamp PR beat to main conflicts on ``last_dispatched_at`` and sits until the 6 h stale-closer (MEASURED
48 h to 2026-11-19 ~11:20Z: 7 of the 11 stale open automation PRs were stamp PRs in that state).

For each open ``automation/research-queue-stamp*`` PR that GitHub reports unmergeable (``mergeable`` is
false): merge ``origin/main`` into its branch and resolve the conflict with the existing resolver (the
later stamp wins; a cleared stamp beats a stamp; anything that is not a pure stamp conflict is refused).
Then:

* ``superseded``     -- after the merge the branch changes nothing under research/queue/ vs main (main
  already carries the same or later stamps): the PR is CLOSED with a pointer. Nothing is lost.
* ``refreshed``      -- the branch still carries a newer stamp: the merge is pushed to the bot's own
  branch so its armed auto-merge can land it.
* ``not_stamp_only`` -- the conflict is not a pure stamp conflict: merge aborted, PR left for the 6 h
  closer, reason printed (never resolved by guessing).

Never fails the job: per-PR containment, and a failed listing prints "could not list" (could not look),
never "nothing to do".

Usage: refresh_stamp_prs.py [--repo OWNER/NAME] [--cwd WORKTREE] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))
import resolve_stamp_conflicts as rsc  # noqa: E402

PREFIX = "automation/research-queue-stamp"
_BOT = ("-c", "user.name=github-actions[bot]", "-c", "user.email=github-actions[bot]@users.noreply.github.com")


def _git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def refresh_branch(cwd: Path, branch: str, *, remote: str = "origin", push: bool = True) -> tuple[str, str]:
    """Merge ``remote/main`` into ``remote/branch``; return (outcome, detail). Leaves HEAD detached."""
    _git("fetch", "-q", remote, "main", branch, cwd=cwd)
    _git("checkout", "-q", "--detach", f"{remote}/{branch}", cwd=cwd)
    m = _git(*_BOT, "merge", "--no-edit", "-q", f"{remote}/main", cwd=cwd, check=False)
    if m.returncode != 0:
        conflicted = _git("diff", "--name-only", "--diff-filter=U", cwd=cwd).stdout.split()
        prev = os.getcwd()
        try:
            os.chdir(cwd)
            rc = rsc.main(conflicted) if conflicted else 1
        finally:
            os.chdir(prev)
        if rc != 0:
            _git("merge", "--abort", cwd=cwd, check=False)
            return "not_stamp_only", f"conflicted {conflicted or '(merge failed without a conflict)'}"
        _git("add", "--", *conflicted, cwd=cwd)
        _git(*_BOT, "commit", "-q", "--no-edit", cwd=cwd)
    left = _git("diff", "--name-only", f"{remote}/main", "HEAD", "--", "research/queue", cwd=cwd).stdout.split()
    if not left:
        return "superseded", "main already carries the same or later stamps for every unit"
    if push:
        _git("push", "-q", remote, f"HEAD:refs/heads/{branch}", cwd=cwd)
    return "refreshed", f"{len(left)} unit(s) still carry a newer stamp: {' '.join(left[:8])}"


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Refresh or retire conflicted research-queue stamp PRs.")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cwd", default=str(ROOT),
                    help="a SEPARATE worktree to merge in (the dispatcher's own tree holds unlanded stamps)")
    a = ap.parse_args(argv)
    try:
        raw = _gh(["api", f"repos/{a.repo}/pulls?state=open&per_page=100", "--paginate", "--jq",
                   f'.[] | select(.head.ref | startswith("{PREFIX}")) | "\\(.number) \\(.head.ref)"'])
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"refresh-stamp-prs: could not list open PRs (could not look): {exc}")
        return 0
    prs = [ln.split(" ", 1) for ln in raw.splitlines() if ln.strip()]
    counts: dict[str, int] = {}
    for num, ref in prs:
        try:
            mergeable = _gh(["api", f"repos/{a.repo}/pulls/{num}", "--jq", ".mergeable"]).strip()
            if mergeable != "false":  # true, or null = GitHub still computing: leave it this cycle
                counts["mergeable_or_unknown"] = counts.get("mergeable_or_unknown", 0) + 1
                continue
            outcome, detail = refresh_branch(Path(a.cwd), ref, push=not a.dry_run)
            print(f"#{num} {ref}: {outcome} -- {detail}")
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome == "superseded" and not a.dry_run:
                _gh(["pr", "close", num, "--repo", a.repo, "--comment",
                     ("Closed by the research dispatcher (AUTOMATION-DATACOMMIT-CONFLICT): superseded. After "
                      "merging main, this branch changes no research/queue unit, because main already carries the "
                      "same or later dispatch stamps. Nothing is lost.")])
        except (subprocess.CalledProcessError, OSError, ValueError) as exc:  # one PR never blocks the others
            print(f"#{num} {ref}: error -- {exc}")
            counts["error"] = counts.get("error", 0) + 1
    print(f"refresh-stamp-prs: {len(prs)} open stamp PR(s); {json.dumps(counts, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
