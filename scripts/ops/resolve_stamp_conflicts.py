#!/usr/bin/env python3
"""Resolve a merge conflict that is ONLY a dispatch stamp.

`commit-to-main`'s stale-branch refresh merges `main` into an automation
branch.  Two research-queue stamp PRs that stamp the same unit conflict on one
line, `last_dispatched_at`, and nothing else (STAMP-RACE-2: 5 of 14 red
dispatcher `land` jobs 2026-10-10/11).  The right answer is mechanical -- the
later stamp -- so this resolves it, and refuses anything else.

Usage (mid-merge, in the repo):  resolve_stamp_conflicts.py FILE [FILE ...]

All-or-nothing: if ANY file differs between the two sides in more than its
`last_dispatched_at` line, or is not a `research/queue/*.yaml` unit, nothing is
written and the exit code is 1.  Exit 0 means every file was rewritten with the
side carrying the later stamp; the caller does `git add` + `git commit`.
"""
from __future__ import annotations

import re
import subprocess
import sys

_STAMP = re.compile(r"^last_dispatched_at:\s*(.*?)\s*$", re.M)


def _stage(n: int, path: str) -> str | None:
    r = subprocess.run(["git", "show", f":{n}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _stamp(text: str) -> str | None:
    m = _STAMP.search(text)
    return m.group(1).strip("'\"") if m else None


def resolve(path: str, ours: str, theirs: str) -> str | None:
    """Return the winning side's text, or None if this is not a pure stamp conflict."""
    if not (path.startswith("research/queue/") and path.endswith(".yaml")):
        return None
    if _STAMP.sub("", ours) != _STAMP.sub("", theirs):
        return None
    a, b = _stamp(ours), _stamp(theirs)
    if a is None and b is None:
        return None
    # ISO-8601 UTC strings of one format sort chronologically; a missing stamp loses.
    return ours if (b is None or (a is not None and a >= b)) else theirs


def main(paths: list[str]) -> int:
    if not paths:
        return 1
    plan: dict[str, str] = {}
    for p in paths:
        ours, theirs = _stage(2, p), _stage(3, p)
        if ours is None or theirs is None:
            return 1
        won = resolve(p, ours, theirs)
        if won is None:
            return 1
        plan[p] = won
    for p, text in plan.items():
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
