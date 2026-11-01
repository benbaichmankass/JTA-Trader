"""Push-to-main runs of the four heavy checks skip bot-data-only commits (runner census 2026-11-01).

The four checks (and branch-sync, work-digest) carry one `push.paths-ignore` list. Pinned here: identical in all six; disjoint from every committed
path the test suite reads (so a data file a test asserts over can never skip the push run); `pull_request` is untouched
(no guard is skipped on any PR); a code/config/workflow file in a commit makes the whole commit run.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = ("pytest-run", "guards", "repo-inventory", "pytest-collect")
SIX = WORKFLOWS + ("branch-sync", "work-digest")   # D: the same list gates branch-sync and work-digest pushes


def _on(wf: str) -> dict:
    d = yaml.safe_load((REPO / ".github/workflows" / f"{wf}.yml").read_text())
    return d.get(True) or d.get("on")


def _rx(glob: str) -> re.Pattern:
    return re.compile("^" + re.escape(glob).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$")


def _ignores_all(files: list[str], globs: list[str]) -> bool:
    rx = [_rx(g) for g in globs]
    return bool(files) and all(any(r.match(f) for r in rx) for f in files)


def test_the_six_lists_are_identical():
    lists = {wf: _on(wf)["push"]["paths-ignore"] for wf in SIX}
    first = lists[WORKFLOWS[0]]
    assert first and all(v == first for v in lists.values()), lists
    assert _on("pytest-run")["push"]["branches"] == ["main"]


def test_pull_requests_have_no_path_filter():
    for wf in WORKFLOWS:
        pr = _on(wf)["pull_request"]
        assert "paths" not in pr and "paths-ignore" not in pr, wf


def test_no_ignored_glob_matches_a_path_the_suite_reads():
    spec = importlib.util.spec_from_file_location("_prf", REPO / "tests/test_pytest_run_filter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    read = sorted(mod._committed_readers_any_tree())
    globs = _on("pytest-run")["push"]["paths-ignore"]
    hits = {g: [r for r in read if _rx(g).match(r)] for g in globs}
    assert not {g: v for g, v in hits.items() if v}, hits


def test_classification_examples():
    globs = _on("pytest-run")["push"]["paths-ignore"]
    landing = [".github/merge-slots/automation-data-commit-1-1.json", ".github/pr-landing/automation-data-commit-1-1.json",
               ".github/pr-automerge-requests/automation-data-commit-1-1.txt", "comms/desk/role_grade.json"]
    assert _ignores_all(landing, globs)
    assert _ignores_all(["comms/research/RQ-20261101-e5b1-14/verdict.json", "research/results/_unattributed/x.jsonl"], globs)
    for code in ("scripts/ops/x.py", "src/main.py", "config/strategies.yaml", ".github/workflows/guards.yml",
                 "tests/test_x.py", "comms/live_review/reviews.jsonl", "research/queue/RQ-20261031-a4e7-05.yaml"):
        assert not _ignores_all(landing + [code], globs), code
    assert not _ignores_all([], globs)
