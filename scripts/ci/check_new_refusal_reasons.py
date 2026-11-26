#!/usr/bin/env python3
"""WARN when a PR diff ADDS a new refusal / limit reason in a validator, writer, or risk / intake path.

WHY (operator popup 2026-11-26, verbatim: "Yes, warn only (Recommended)"). A new refusal string or enum member in a
validator, a writer or the risk / intake path is a new way for the system to say no. Those are how gates get added without
anyone deciding to add one (docs/CLAUDE-RULES-CANONICAL.md § "No new gates without the operator's permission"). This check
makes the addition VISIBLE on the PR so the author and the reviewer see it; it decides nothing.

WHAT IT READS. The PR's added lines (`git diff --unified=0 <base>...HEAD`), in `.py` files under `src/` or `scripts/` whose path
names a validator, writer, risk or intake surface (PATH_RE). On an ADDED line it flags:
  * a quoted string of >= 6 characters on a line that also names a refusal / limit word (REASON_WORD_RE: refus, reject, deny,
    denied, blocked, exceed, over_limit, limit, cap, not allowed, forbidden, invalid), or
  * a new UPPER_SNAKE enum member / constant assigned a string (`NAME = "name"`) in such a file, on a line with that word.
Each hit prints `::warning file=...,line=...::` so it annotates the PR's Files tab. Test files, scripts/ci and docs are out of scope.

HEURISTIC, STATED: it reads text, not meaning. It will flag some lines that are not refusals (a log message that mentions a
limit) and miss a refusal built from parts. The annotation says what it saw; a human decides. It is deliberately noisy-low, not exact.

Gates this adds or changes: NONE. WARNING ONLY. Exit code is 0 in every case, including a git failure, a missing base and an
unexpected exception (each of those prints a ::notice:: and exits 0). It must never block a merge. Do not add `--enforce`.

Run:
    python3 scripts/ci/check_new_refusal_reasons.py --base origin/main
    python3 scripts/ci/check_new_refusal_reasons.py --self-test
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for the shared dirty-tree notice

#: a validator / writer / risk / intake surface, by path (src/ and scripts/ .py only; scripts/ci is excluded below)
PATH_RE = re.compile(
    r"^(?:src|scripts)/.*(?:validat|writer|risk|intake|refus|guard_rail|limits?)[^/]*\.py$|"
    r"^(?:src|scripts)/.*/(?:risk|intake|validat\w*|writers?)/[^/]+\.py$|"
    r"^src/.*_gate\.py$"
)
EXCLUDE_RE = re.compile(r"^(?:tests/|docs/|scripts/ci/|research/)|/tests?/|(?:^|/)test_[^/]*\.py$")
REASON_WORD_RE = re.compile(
    r"refus|reject|deny|denied|blocked|exceed|over_limit|\blimit|\bcap\b|not allowed|forbidden|invalid", re.I)
STRING_RE = re.compile(r"""(?P<q>['"])(?P<body>[^'"\\]{6,})(?P=q)""")
CONST_RE = re.compile(r"""^\s*[A-Z][A-Z0-9_]{3,}\s*=\s*['"][^'"]{3,}['"]""")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
COMMENT_RE = re.compile(r"^\s*(#|\"\"\"|''')")
#: a log / print / argparse-help / env-knob line names a limit without being a refusal reason
LOG_RE = re.compile(r"^\s*(?:logger|log|logging|print|warnings\.warn)\b|\bhelp\s*=|_int_knob\(|environ|getenv")


def in_scope(path: str) -> bool:
    return bool(path.endswith(".py") and PATH_RE.match(path) and not EXCLUDE_RE.search(path))


def flag_line(path: str, text: str) -> Optional[str]:
    """Why an ADDED line looks like a new refusal / limit reason, or None."""
    if COMMENT_RE.match(text) or LOG_RE.search(text):
        return None
    if not REASON_WORD_RE.search(text):
        return None
    if CONST_RE.match(text):
        return "new reason constant / enum member"
    m = STRING_RE.search(text)
    if m:
        return f"new refusal / limit string {m.group('body')[:60]!r}"
    return None


def parse_added(diff: str) -> Iterable[Tuple[str, int, str]]:
    """``(path, new_line_no, text)`` for every added line of a ``--unified=0`` diff."""
    path, ln = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
            continue
        m = HUNK_RE.match(raw)
        if m:
            ln = int(m.group(1))
            continue
        if path is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            yield path, ln, raw[1:]
            ln += 1


def scan_diff(diff: str) -> List[Tuple[str, int, str]]:
    out = []
    for path, ln, text in parse_added(diff):
        if not in_scope(path):
            continue
        why = flag_line(path, text)
        if why:
            out.append((path, ln, why))
    return out


def _git_diff(base: str) -> str:
    return subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", "--no-renames", f"{base}...HEAD", "--", "src", "scripts"],
        cwd=REPO, capture_output=True, text=True, timeout=120, check=True).stdout


def _self_test() -> int:
    bad = 0

    def check(name: str, cond: bool) -> None:
        nonlocal bad
        if not cond:
            bad += 1
            print(f"FAIL {name}")

    check("path in scope: validator", in_scope("src/runtime/order_validator.py"))
    check("path in scope: risk dir", in_scope("src/units/risk/manager.py"))
    check("path in scope: intake", in_scope("scripts/ops/desk_intake.py"))
    check("path out: test", not in_scope("tests/test_risk.py"))
    check("path out: ci", not in_scope("scripts/ci/check_risk_basis_agreement.py"))
    check("path out: unrelated", not in_scope("src/runtime/pipeline.py"))
    check("flag string", flag_line("x", '    return None, "refused: exceeds the daily cap"') is not None)
    check("flag const", flag_line("x", '    OVER_CAP = "over_cap_refused"') is not None)
    check("no flag: comment", flag_line("x", '    # refused: exceeds the daily cap') is None)
    check("no flag: logger", flag_line("x", '    logger.debug("silent refusal alert: limit hit %s", x)') is None)
    check("path in scope: src gate", in_scope("src/runtime/broker_shorting_gate.py"))
    check("path out: research gate", not in_scope("scripts/research/prop_gate.py"))
    check("no flag: no reason word", flag_line("x", '    name = "hello world"') is None)
    diff = (
        "diff --git a/src/runtime/order_validator.py b/src/runtime/order_validator.py\n"
        "--- a/src/runtime/order_validator.py\n+++ b/src/runtime/order_validator.py\n"
        "@@ -10,0 +11,2 @@ def f():\n"
        '+    x = 1\n+    return False, "rejected: notional exceeds limit"\n'
        "diff --git a/tests/test_x.py b/tests/test_x.py\n--- a/tests/test_x.py\n+++ b/tests/test_x.py\n"
        "@@ -1,0 +2 @@\n"
        '+    assert "rejected: notional exceeds limit"\n'
    )
    hits = scan_diff(diff)
    check("diff: one hit", len(hits) == 1)
    check("diff: right line", hits and hits[0][:2] == ("src/runtime/order_validator.py", 12))
    print(f"check-new-refusal-reasons --self-test: {bad} failure(s)")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    try:
        import _dirty_tree  # noqa: PLC0415 -- path shim above; the shared notice (a --base guard grades a commit range)
        _dirty_tree.warn()
        if a.self_test:
            # a broken self-test is a bug in THIS file; it still must not block a merge, so report and exit 0
            rc = _self_test()
            if rc:
                print("::warning::check-new-refusal-reasons: --self-test failed (warning only; exit 0)")
            return 0
        if not a.base:
            print("::notice::check-new-refusal-reasons: no --base given, nothing to compare (warning only; exit 0)")
            return 0
        hits = scan_diff(_git_diff(a.base))
        print(f"check-new-refusal-reasons: base={a.base} possible_new_refusal_reasons={len(hits)}")
        for path, ln, why in hits:
            print(f"::warning file={path},line={ln}::new refusal/limit reason added ({why}). A new refusal is a new gate "
                  "unless the operator asked for it: say so in the PR body under 'Gates this adds or changes'. "
                  "Warning only; nothing is blocked.")
        print("check-new-refusal-reasons: " + ("none seen" if not hits else "WARNING ONLY (not enforced): see the annotations above"))
    except Exception as exc:  # noqa: BLE001 -- warn-only by contract: nothing here may fail a PR
        print(f"::notice::check-new-refusal-reasons: could not read the diff ({type(exc).__name__}: {str(exc)[:120]}); "
              "warning only, exit 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
