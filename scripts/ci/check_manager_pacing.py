#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::manager-pacing-guard (--self-test, then the scan).
"""Guard: the manager's pacing doctrine stays the operating loop, not the one it replaced.

Operator, 2026-10-18 (MANAGER-PACING-STRUCTURAL): *"We want to get as much work as possible out of
our budget without blowing through it before a reset"* — at least one lane, up to five by judgment,
no hard caps. Until that day the manager skill taught the opposite: spend the daily share, run into
the margin, launch lanes in parallel, check in hourly, treat Fable as an unused second pool. Each
operator correction was patched as one more line, and the next manager read the old ones. Same
pattern as `check_soak_doctrine.py`: the rule is stated ONCE (manager SKILL.md § "The operating
loop") and this scan keeps the retired idioms out of every live surface.

Fails (exit 1) if:
  A. a live doc, skill or the spend meter carries a RETIRED idiom (RETIRED below);
  B. the manager skill loses its "## The operating loop" section, or "Start of session" stops
     pointing at it.

Usage: check_manager_pacing.py [--self-test]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ".claude/skills/manager/SKILL.md"
SURFACES = ("CLAUDE.md", "docs/CLAUDE-RULES-CANONICAL.md", "docs/plans/OPERATING-PLAN-2026-09-21.md",
            "scripts/ops/spend_meter.py", "docs/claude/work/LANE-WATCHDOG-PROMPT.md")
SURFACE_GLOBS = (".claude/skills/*/SKILL.md",)

#: (pattern, why it is retired). Matched case-insensitively, whitespace-tolerant.
RETIRED = (
    (r"dispatch\s+in\s+parallel", "lanes are dispatched one slot at a time by capacity (loop step 3)"),
    (r"spend\s+the\s+daily\s+budget", "the pace is the sustainable rate (loop step 2), not a daily share to spend"),
    (r"into\s+the\s+(?:resulting\s+)?(?:30%\s+)?margin\s+is\s+authori[sz]ed",
     "running into the margin is not a licence; the rate spreads what is left to the reset"),
    (r"hourly\s+while\s+lanes\s+run", "the check-in runs the operating loop every 3 h, not hourly"),
    (r"second\s+budget,?\s+and\s+it\s+is\s+unused", "Fable is not free capacity; it counts in loop step 2"),
    (r"one-lane\s+rule", "never defined; dispatch is by capacity (loop step 3)"),
)


def surfaces(root: Path = ROOT) -> list[Path]:
    out = [root / s for s in SURFACES if (root / s).is_file()]
    for g in SURFACE_GLOBS:
        out += sorted(p for p in root.glob(g) if p not in out)
    return out


def retired_hits(text: str, where: str) -> list[str]:
    out = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for pat, why in RETIRED:
            if re.search(pat, line, re.I):
                out.append(f"{where}:{lineno}: retired pacing idiom /{pat}/ — {why}")
    # a phrase can wrap across two lines; scan the flattened text for misses
    flat = re.sub(r"\s+", " ", text)
    for pat, why in RETIRED:
        if re.search(pat, flat, re.I) and not any(f"/{pat}/" in h for h in out):
            out.append(f"{where}: retired pacing idiom /{pat}/ (wrapped across lines) — {why}")
    return out


def loop_problems(skill_text: str) -> list[str]:
    out = []
    if not re.search(r"^## The operating loop\b", skill_text, re.M):
        out.append(f"{SKILL}: the '## The operating loop' section is missing")
    m = re.search(r"^## Start of session\n(.*?)(?=^## )", skill_text, re.M | re.S)
    if not m or '§ "The operating loop"' not in m.group(1):
        out.append(f"{SKILL}: '## Start of session' no longer points at § \"The operating loop\"")
    return out


def scan(root: Path = ROOT) -> list[str]:
    problems = []
    for p in surfaces(root):
        problems += retired_hits(p.read_text(encoding="utf-8"), str(p.relative_to(root)))
    skill = root / SKILL
    problems += loop_problems(skill.read_text(encoding="utf-8")) if skill.is_file() else [f"{SKILL}: missing"]
    return problems


def self_test() -> int:
    ok = True

    def ck(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    plants = [
        "- **Archive on merge; dispatch in parallel** (one message, many lanes).",
        "**Spend the daily budget. Passing into the\nmargin is authorized.**",
        "spending into the resulting 30% margin is AUTHORIZED",
        "- **Check-in cadence follows activity.** Hourly while lanes run, 3-hourly when none do.",
        "⚠️ **THERE IS A SECOND BUDGET, AND IT IS UNUSED.**",
        "dispatch ML rows by capacity under the one-lane rule;",
    ]
    for t in plants:
        ck(f"plant caught: {t[:50]!r}", bool(retired_hits(t, "x")))
    ck("a phrase wrapped across lines is caught", bool(retired_hits("dispatch in\nparallel", "x")))
    controls = [
        "Lanes are dispatched one slot at a time by capacity (§ \"The operating loop\", step 3).",
        "The \"Manager lane check-in\" routine runs the loop every 3 h; there is no hourly check-in.",
        "Fable has its own weekly bar; it is not free capacity.",
        "`ict-work-digest.timer`, hourly. This is THE Telegram carrier.",
    ]
    for t in controls:
        ck(f"control passes: {t[:50]!r}", not retired_hits(t, "x"))
    good = '## Start of session\n\n0. **Run § "The operating loop"**\n\n## The operating loop\n\nx\n'
    ck("a skill with the loop and the pointer is clean", loop_problems(good) == [])
    ck("a skill without the loop section fails",
       any("section is missing" in m for m in loop_problems(good.replace("## The operating loop\n", ""))))
    ck("a Start of session without the pointer fails",
       any("no longer points" in m for m in loop_problems(good.replace('§ "The operating loop"', "x"))))
    ck("the live surfaces include the manager skill and the spend meter",
       {SKILL, "scripts/ops/spend_meter.py"} <= {str(p.relative_to(ROOT)) for p in surfaces()})
    print("manager-pacing self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    problems = scan()
    for p in problems:
        print(f"::error::{p}")
    print(f"manager-pacing: {'clean' if not problems else f'{len(problems)} problem(s)'} "
          f"over {len(surfaces())} live surface(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
