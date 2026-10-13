#!/usr/bin/env python3
# wiring: .github/workflows/branch-sync.yml (runs `main()`), tests/test_branch_sync.py
"""Merge `main` into open self-landing PR branches that are only BEHIND.

WHY (row AUTO-BRANCH-SYNC, plan act M-a): the manager hand-merged main into ~24 open PRs on
2026-10-08. GitHub's `update-branch` does the same MERGE COMMIT with no checkout.

WHAT IT WILL TOUCH - all must hold (`eligible`, pure):
  open, not draft, base main, same-repo `claude/*` head, no `landing:hold` label,
  its own landing declaration is `tier 1 / landing self`, no changed file is a Tier-2/3
  path (the guard's own lists), and `mergeable_state == behind` (clean but behind).
WHAT IT NEVER DOES: rebase, force-push, resolve a conflict, or touch a hold / Tier-2/3 PR.
A `dirty` (conflicting) eligible PR gets ONE comment per head sha and is left alone.

NEEDS A PAT. A branch updated with the built-in GITHUB_TOKEN raises no `pull_request` event,
so the new head would carry NO checks (the failure `claude-pr-automerge.yml`'s header measured).
Without `BRANCH_PROTECTION_TOKEN` this refuses to update anything and says so.
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_pr_landing as cpl  # noqa: E402

HOLD_LABEL = "landing:hold"
MAX_UPDATES = 10
MARKER = "<!-- branch-sync:{sha} -->"


def _barred(files: list[str]) -> list[str]:
    return [f for f in files if any(fnmatch.fnmatch(f, g) for g in cpl.TIER3_PATHS + cpl.TIER2_PATHS)]


def eligible(pr: dict, decl: dict | None, files: list[str], repo: str) -> tuple[bool, str]:
    """Pure. `pr` is a pulls API object, `decl` the parsed landing json at its head (or None)."""
    head = pr.get("head") or {}
    if pr.get("state") != "open":
        return False, "not open"
    if pr.get("draft"):
        return False, "draft"
    if (pr.get("base") or {}).get("ref") != "main":
        return False, "base is not main"
    if (head.get("repo") or {}).get("full_name") != repo:
        return False, "fork"
    if not str(head.get("ref", "")).startswith("claude/"):
        return False, "not a claude/* branch"
    if any(lb.get("name") == HOLD_LABEL for lb in pr.get("labels") or []):
        return False, "labelled landing:hold"
    if not decl:
        return False, "no readable landing declaration"
    if decl.get("tier") != 1 or decl.get("landing") != "self":
        return False, f"declares tier {decl.get('tier')!r} landing {decl.get('landing')!r}, not tier 1 self"
    bad = _barred(files)
    if bad:
        return False, "touches Tier-2/3 paths: " + ", ".join(bad[:3])
    return True, "ok"


def plan(state: str | None) -> str:
    return {"behind": "update", "dirty": "comment"}.get(state or "", "skip")


class Gh:
    def __init__(self, repo: str):
        self.repo = repo

    def api(self, method: str, path: str, **fields):
        cmd = ["gh", "api", "-X", method, f"repos/{self.repo}/{path}"]
        for k, v in fields.items():
            cmd += ["-f", f"{k}={v}"]
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if p.returncode:
            raise RuntimeError(p.stderr.strip() or p.stdout.strip())
        return json.loads(p.stdout) if p.stdout.strip() else None


def landing_decl(gh, pr: dict) -> dict | None:
    slug = cpl.branch_slug(pr["head"]["ref"])
    try:
        blob = gh.api("GET", f"contents/{cpl.LANDING_DIR}/{slug}.json?ref={pr['head']['sha']}")
        return json.loads(base64.b64decode(blob["content"]))
    except (RuntimeError, KeyError, ValueError):
        return None


def run(gh, repo: str, have_pat: bool, sleep=time.sleep, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    if not have_pat:
        return [("REFUSED: BRANCH_PROTECTION_TOKEN absent. A GITHUB_TOKEN update would leave the new head "
                 "with no checks, so nothing was updated.")]
    updated = 0
    for item in gh.api("GET", "pulls?state=open&base=main&per_page=100") or []:
        n = item["number"]
        pr = gh.api("GET", f"pulls/{n}")
        if pr.get("mergeable_state") in (None, "unknown"):
            sleep(5)
            pr = gh.api("GET", f"pulls/{n}")
        files = [f["filename"] for f in gh.api("GET", f"pulls/{n}/files?per_page=100") or []]
        ok, why = eligible(pr, landing_decl(gh, pr), files, gh.repo)
        if not ok:
            log.append(f"#{n} skip: {why}")
            continue
        action = plan(pr.get("mergeable_state"))
        sha = pr["head"]["sha"]
        if action == "update":
            if updated >= MAX_UPDATES:
                log.append(f"#{n} deferred: per-run cap {MAX_UPDATES}")
                continue
            if not dry_run:
                try:
                    gh.api("PUT", f"pulls/{n}/update-branch", expected_head_sha=sha)
                except RuntimeError as exc:      # 422 on conflict / head moved: leave it alone
                    log.append(f"#{n} update refused: {exc}")
                    continue
            updated += 1
            log.append(f"#{n} updated (merge commit of main into {pr['head']['ref']})")
        elif action == "comment":
            mark = MARKER.format(sha=sha)
            seen = any(mark in (c.get("body") or "") for c in gh.api("GET", f"issues/{n}/comments?per_page=100") or [])
            if seen:
                log.append(f"#{n} conflicts with main (already commented for this head)")
            else:
                if not dry_run:
                    gh.api("POST", f"issues/{n}/comments",
                           body=f"{mark}\nbranch-sync: this PR conflicts with `main`, so it was not updated "
                                f"automatically. Merge `main` into the branch and resolve the conflict by hand.")
                log.append(f"#{n} conflicts with main: commented")
        else:
            log.append(f"#{n} skip: mergeable_state={pr.get('mergeable_state')!r}")
    return log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    for line in run(Gh(a.repo), a.repo, bool(os.environ.get("BRANCH_PROTECTION_TOKEN")), dry_run=a.dry_run):
        print(f"branch-sync: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
