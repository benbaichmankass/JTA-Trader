#!/usr/bin/env python3
"""no-action-rate-cap-guard: no in-trade action is capped per bar or per time window.

Operator 2026-10-29 ~10:45Z, verbatim (row ``REMOVE-PER-BAR-CAP``): *"Why is there a cap for the reviewer?
What's the point of having active management and then specifically limiting how active that management can
be? When was a cap even approved? ... we need to make sure this isn't being implemented anywhere"*.

A session wrote "at most one amend per package per closed bar" into the live-trade-review design's noise-floor
bullet (PR #20088); it was built as ``live_review_intent.R_RATE`` (LTR-6R #20139) and copied into the trade
actions, the auto-mandate bounds (``one_action_per_bar``), the mandates file, the skill and the canonical doc.
No operator decision approved it. It was removed everywhere; the ONE duplicate guard is idempotency per
review_id / directed record id (``live_review_intent.R_DUPLICATE``).

Two checks, so a re-introduction fails CI whichever way it is spelled:

1. **Text.** Every file of the in-trade action paths and the docs/skills/mandates that state their rules
   (:data:`SCOPE`) is scanned for the cap's identifiers and its prose (:data:`PATTERNS`). A line that carries
   ``REMOVE-PER-BAR-CAP`` is exempt: it records the removal (a struck history line, a changelog row).
2. **Structure.** The gate functions (:data:`GATES`) may not read ``bar_ts`` or any ``last_*bar*`` name: a gate
   that compares the bar is a per-bar cap whatever its constant is called. ``bar_ts`` stays on the intent as
   PROVENANCE only (the bar an action was taken on, written to the journal).

Not in scope, deliberately (each a different guard, listed in the row): the ``min_buffer_atr`` noise floor (a
DISTANCE from the mark, not a count); the review-wake cooldown (``live_review_due`` / ``live_review_wake``:
how often a REVIEW is woken, not how many actions a review may take); the strategy's own closed-bar trail
replay (``phone_trail.last_bar``, ``prop_trail``); the exit head's once-per-closed-bar scoring (the model's
trained cadence); and alert/ping cooldowns.

Usage: ``python3 scripts/ci/check_no_action_rate_cap.py [--self-test]``. Exit 0 clean, 1 a violation.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

REPO = Path(__file__).resolve().parents[2]
EXEMPT_TAG = "REMOVE-PER-BAR-CAP"

#: The in-trade action paths and the documents that state their rules. Globs, so a new file in a family is in.
SCOPE = (
    "src/runtime/live_review*.py", "scripts/ops/live_review*.py", "src/runtime/ltr_*.py",
    "src/runtime/directed_actions.py", "scripts/ops/directed_action.py", "scripts/ops/desk_intake.py",
    "src/units/accounts/risk.py", "src/units/accounts/alpaca_amend.py", "src/prop/prop_amend_gate.py",
    "src/runtime/exit_head_apply.py", "src/runtime/bracket_advisor.py",
    "config/mandates.yaml", "config/live_trade_review.yaml",
    ".claude/skills/live-trade-review/*.md", ".claude/skills/trading-desk/*.md",
    ".claude/skills/exit-refinement/*.md",
    "docs/ARCHITECTURE-CANONICAL.md", "docs/plans/live-trade-review-DESIGN.md",
    "docs/plans/claude-trading-desk-DESIGN.md", "docs/claude/system-actions.md",
)

_NOUN = r"(?:amend|action|applied action|apply|applies|tighten|move|change|adjustment|modification)s?"
#: (name, regex). Case-insensitive.
PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = tuple((n, re.compile(p, re.I)) for n, p in (
    ("identifier", r"\bR_RATE\b|one_action_per_bar|one_amend_per|\bauto_bar\b|last_amend_bar|last_review_bar"
                   r"|max_(?:actions|amends)_per|(?:actions|amends)_per_(?:bar|hour|day|window)"
                   r"|(?:action|amend)_(?:cooldown|rate_limit|throttle)"),
    ("prose: N actions per bar", r"(?:\bone|\b1|at most one|<=\s*1|≤\s*1)\s+" + _NOUN
                                 + r"\s+per\s+(?:package|account|leg|ticket|trade|closed bar|bar|hour|day)\b"),
    ("prose: actions per package per bar", _NOUN + r"\s+per (?:package|account|leg)(?:/account)? per (?:closed )?bar"),
    # "no per-bar action cap" (the removal's own wording) is not a cap: the negation is excluded.
    ("prose: action cap", r"(?<!no per-bar )(?<!no )\b(?:action|amend)[- ](?:count[- ])?"
                          r"(?:cap|rate[- ]limit|cooldown|throttle)\b"),
))

#: (path, function names) whose bodies may not read the bar.
GATES = (
    ("src/runtime/live_review_intent.py", ("decide_amend", "decide_action", "is_duplicate")),
    ("scripts/ops/live_review_apply.py", ("auto_bound_refusal", "_decide_trade_action")),
    ("src/prop/prop_amend_gate.py", ("decide_prop",)),
    ("src/units/accounts/risk.py", ("approve_amend", "approve_action")),
)
_BAR_NAME = re.compile(r"^(?:bar_ts|last_\w*bar\w*)$")


def files() -> List[Path]:
    out = set()
    for g in SCOPE:
        out.update(p for p in REPO.glob(g) if p.is_file())
    return sorted(out)


def scan_text(path: str, text: str) -> List[str]:
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        if EXEMPT_TAG in line:
            continue
        for name, rx in PATTERNS:
            m = rx.search(line)
            if m:
                hits.append(f"{path}:{n}: {name}: {m.group(0)!r}")
                break
    return hits


def scan_gates(path: str, src: str, names: Iterable[str]) -> List[str]:
    tree = ast.parse(src)
    want, seen, hits = set(names), set(), []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in want:
            seen.add(node.name)
            for sub in ast.walk(node):
                ident = (sub.attr if isinstance(sub, ast.Attribute) else sub.id if isinstance(sub, ast.Name)
                         else sub.value if isinstance(sub, ast.Constant) and isinstance(sub.value, str) else None)
                if ident and _BAR_NAME.match(ident):
                    hits.append(f"{path}:{getattr(sub, 'lineno', node.lineno)}: gate {node.name}() reads "
                                f"{ident!r} -- a gate that compares the bar is a per-bar cap")
    hits += [f"{path}: gate {n}() not found (renamed? update GATES so it stays checked)" for n in sorted(want - seen)]
    return hits


def run() -> List[str]:
    hits: List[str] = []
    fs = files()
    if not fs:
        return ["no file in SCOPE exists: the guard would check nothing"]
    me = Path(__file__).resolve()
    for p in fs:
        if p.resolve() == me:
            continue
        hits += scan_text(str(p.relative_to(REPO)), p.read_text(errors="replace"))
    for rel, names in GATES:
        hits += scan_gates(rel, (REPO / rel).read_text(), names)
    return hits


def self_test() -> int:
    """Planted positives MUST be caught, controls MUST pass, and the live scope must be non-empty."""
    fails = []
    positives = [
        'R_RATE = "one_amend_per_package_per_bar"',
        "    if view.last_amend_bar == intent.bar_ts:",
        "- one_action_per_bar -- at most one applied action per package per closed bar",
        "tighten-only, the noise floor, one amend per package per bar, the account mode",
        "the TP a live target, one action per bar)",
        "<= 1 amend per package per closed bar",
        "at most one amend per package/account per bar",
        "two amends per package per closed bar",
        "MAX_ACTIONS_PER_HOUR = 2",
        "an amend cooldown of 30 minutes",
    ]
    for line in positives:
        if not scan_text("planted", line):
            fails.append(f"NOT caught: {line!r}")
    controls = [
        "one amend per package per bar [removed 2026-10-29, operator, row REMOVE-PER-BAR-CAP]",
        "the min_buffer_atr noise floor: at least 1.0 x ATR beyond the mark",
        "At most one review per package per closed bar of that leg's timeframe",
        "ONE ping per action naming the review_id",
        "an identical recommendation never applies twice (idempotency per review_id)",
    ]
    for line in controls:
        if scan_text("control", line):
            fails.append(f"false positive: {line!r}")
    gate_bad = "def decide_amend(intent, view):\n    if intent.bar_ts == view.last_amend_bar:\n        return 1\n"
    if len(scan_gates("planted", gate_bad, ["decide_amend"])) < 2:
        fails.append("gate check missed a bar comparison")
    if scan_gates("planted", "def decide_amend(intent, view):\n    return intent.review_id\n", ["decide_amend"]):
        fails.append("gate check flagged a clean gate")
    if scan_gates("planted", "def other():\n    pass\n", ["decide_amend"]) == []:
        fails.append("gate check did not flag a missing gate")
    n = len(files())
    if n < 15:
        fails.append(f"SCOPE resolves to only {n} files: a glob stopped matching")
    for f in fails:
        print(f"::error::no-action-rate-cap self-test: {f}")
    print(f"no-action-rate-cap self-test: {len(positives)} positives, {len(controls)} controls, "
          f"3 gate cases, {n} files in scope -> {'FAIL' if fails else 'ok'}")
    return 1 if fails else 0


def main(argv: List[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    hits = run()
    for h in hits:
        print(f"::error::{h}")
    print(f"no-action-rate-cap-guard: {len(files())} files, {sum(len(n) for _, n in GATES)} gates -> "
          f"{len(hits)} violation(s)")
    if hits:
        print("No in-trade action may be capped per bar / time window (operator 2026-10-29, row "
              "REMOVE-PER-BAR-CAP). The duplicate guard is idempotency per review_id (live_review_intent.R_DUPLICATE).")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
