#!/usr/bin/env python3
"""Decide HOW MUCH of the suite `pytest-run` must execute for a diff (CI-DIET).

`pytest-run` is a REQUIRED check, so it can never carry a `paths:` filter.  It
already short-circuits when a diff touches nothing the suite reads (the
`grep -Eq` relevance filter in `.github/workflows/pytest-run.yml`, pinned by
`tests/test_pytest_run_filter.py`).  That filter is deliberately wide: it
includes `docs/claude/work/checklist/`, `PIPELINE.jsonl`, `research/` and
`comms/` because real tests read those trees.  The consequence, MEASURED over
the 48h ending 2026-10-13: 179 of 233 commits that landed on main (77%) touched
nothing but those data trees (research results, checklist rows, pr-landing /
merge-slot / automerge request files) and every one of them paid the full
~36-minute suite on the PR and again on push-to-main.

A data-only diff cannot change what the other ~1,300 test files observe: they
do not read it.  What it CAN change is the tests that read it.  So for such a
diff this script selects **exactly the test files that mention the data trees**
and the workflow runs those, instead of the whole suite.  Nothing is skipped
that could observe the change; the `guards` job still runs unconditionally.

Output (one `key=value` per line, for `$GITHUB_OUTPUT`):

    mode=full | data
    reason=<one line, shown in the job summary>

`full`: some changed file is relevant to the suite (per the workflow's own
relevance regex) AND is not in the explicit DATA allowlist below.
`data`: every relevant changed file is in the allowlist.

The allowlist is EXPLICIT and pinned by `tests/test_pytest_run_scope.py`; a
path not named here gets the full suite, so the failure direction is "runs
more", never "runs less".
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "pytest-run.yml"

# The explicit data-only allowlist.  Each entry is a diff path the suite reads
# only through a SMALL, nameable set of test files (see TEST_TOKENS).
#
# Deliberately NOT here (these run the full suite):
#   comms/schema/**            -- the suite validates against these templates
#   docs/ARCHITECTURE-CANONICAL.md, docs/CLAUDE-RULES-CANONICAL.md and the other
#   enumerated docs/ readers   -- read as-committed by tests that do not mention
#                                 any token below (see test_pytest_run_filter.COVERED)
#   anything under src/ scripts/ tests/ config/ .github/workflows/ ml/ .claude/
DATA_ALLOWLIST: tuple[str, ...] = (
    r"^docs/claude/work/checklist/",
    r"^docs/claude/work/pipeline/",
    r"^docs/claude/work/PIPELINE\.jsonl$",
    r"^research/queue/[^/]+\.ya?ml$",
    r"^research/results/",
    r"^comms/(?!schema/)",
    r"^\.github/pr-landing/",
    r"^\.github/pr-automerge-requests/",
    r"^\.github/merge-slots/",
)
DATA_RE = re.compile("|".join(DATA_ALLOWLIST))

# A test file is a "data reader" if its text names one of the data trees: by path
# literal, by the module that loads it, or by the quoted path SEGMENT a
# `Path(...) / "comms" / ...` join spells.  Segment spellings are included on
# purpose: the repo has already been bitten by a reader (`os.path.join`) that
# the literal-path scan could not see (tests/test_pytest_run_filter.py).  The
# bare words "checklist" / "pipeline" / "comms" are NOT tokens -- they appear in
# ~190 files that only talk about those things (the ML/trade "pipeline"), and
# selecting on them ran 25% of the suite, measured 2026-10-13 (5,650 tests,
# 21 min) for no added coverage of the data trees.  Over-selecting costs minutes;
# under-selecting is the 'green tick that ran nothing' failure.
TEST_TOKENS = re.compile(
    r"work/checklist|checklist_store|checklist\.py|MANAGER-CHECKLIST|[\"']checklist[\"']|\bchecklist/"
    r"|PIPELINE\.jsonl|work/pipeline|ops/pipeline|ops import pipeline|ops\.pipeline|import pipeline"
    r"|[\"']pipeline[\"']|pipeline\.py"
    r"|research/queue|research_queue|research/results|[\"']queue[\"']|[\"']results[\"']"
    r"|queue_loader|dispatch_queue"
    r"|comms/|[\"']comms[\"']"
    r"|pr-landing|pr-automerge|merge-slots|merge_slot|pr_landing|pr_automerge"
    r"|check_pr_landing|claim_merge",
    re.IGNORECASE,
)
ALWAYS = (
    "tests/test_pytest_run_filter.py",
    "tests/test_pytest_run_scope.py",
)
IGNORED = ("tests/test_main_loop.py",)  # imports the live entrypoint; mirrors pytest-run


def relevance_regex(workflow: Path = WORKFLOW) -> str:
    """The workflow's own `grep -Eq '<re>'` -- the single source of truth."""
    m = re.search(r"grep -Eq '([^']+)'", workflow.read_text())
    if not m:
        raise SystemExit("could not find the relevance grep in pytest-run.yml")
    return m.group(1)


def classify(files: list[str], relevant_re: str) -> tuple[str, str]:
    rel = re.compile(relevant_re)
    files = [f for f in (x.strip() for x in files) if f]
    relevant = [f for f in files if rel.search(f)]
    blocking = [f for f in relevant if not DATA_RE.search(f)]
    if blocking:
        shown = ", ".join(blocking[:3]) + (" ..." if len(blocking) > 3 else "")
        return "full", f"{len(blocking)} changed file(s) outside the data allowlist ({shown}) -> full suite"
    reason = (
        f"all {len(relevant)} suite-relevant changed file(s) are data-only "
        "(checklist/pipeline/research queue+results/comms/pr-landing/merge-slot/automerge) "
        "-> ran every test file that reads those trees; guards run separately"
    )
    return "data", reason


def select_tests(tests_dir: Path | None = None) -> list[str]:
    tests_dir = tests_dir or REPO / "tests"
    out = set(ALWAYS)
    for p in tests_dir.rglob("test_*.py"):
        rel = p.relative_to(REPO).as_posix()
        if rel in IGNORED:
            continue
        try:
            if TEST_TOKENS.search(p.read_text(errors="replace")):
                out.add(rel)
        except OSError:
            continue
    return sorted(x for x in out if (REPO / x).exists())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--select-tests", action="store_true", help="print the data-reader test files and exit")
    ap.add_argument("--workflow", type=Path, default=WORKFLOW)
    args = ap.parse_args(argv)
    if args.select_tests:
        print("\n".join(select_tests()))
        return 0
    mode, reason = classify(sys.stdin.read().splitlines(), relevance_regex(args.workflow))
    print(f"mode={mode}")
    print(f"reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
