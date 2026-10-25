#!/usr/bin/env python3
"""Guard: the soak doctrine (offline edge, live mechanics) must stay intact.

Enforces ``docs/CLAUDE-RULES-CANONICAL.md`` § "Promotion evidence — offline
edge, live mechanics": a paper/shadow soak validates **MECHANICS ONLY** (a
couple of live executions, accruing in **hours**), never gathers
performance/edge over **days–weeks**. The edge is proven OFFLINE (a
live-faithful backtest + the backfill / live-simulator over deep history)
BEFORE anything is wired to a soak account.

This guard exists because the rule kept getting reverted: prior Claude
sessions repeatedly rewrote the ``new-strategy`` skill (the operational
touchpoint a session actually follows for a strategy soak) back to a
"days–weeks soak to confirm the edge" framing — the exact drift that made the
operator watch alt legs "soak for 2–3 weeks" when they should have needed only
1–2 mechanics-confirming executions. Prose fixes alone did not hold; this is
the mechanical backstop.

Fails (exit 1) if:
  A. The canonical binding rule marker is missing from CLAUDE-RULES-CANONICAL.md,
     or the rule no longer states it applies to STRATEGY legs (not just ML).
  B. The new-strategy skill stops framing the soak as a MECHANICS check, or
     drops the cross-reference to the canonical rule.
  C. Any soak-doctrine skill (new-strategy, backtesting) reintroduces the
     banned "days–weeks soak-to-prove-edge" idiom.
  D. A DECISION-GATE SURFACE grades a verdict off LIVE-ACCRUAL evidence
     (see below) beyond the count recorded in the exception ledger.
  E. A LIVE doc, plan or skill teaches a LONG SOAK: a soak measured in days /
     weeks, an n of 3+, an end date / duration / expected rate / power, or a
     cost / live-vs-backtest EXIT (see "CHECK E" below).
  F. A soak contract in docs/claude/work/SOAKS.json is not mechanical
     (soak_state.contract_problems: n_needed > 2, a calendar field, a
     statistical pass/fail rule).
  G. A GENERATOR emits a long soak: soak_state.make_contract, soak_report's
     Stage-1 exit text, and mandate_resolver's soak data task are run and their
     OUTPUT is scanned with the CHECK E patterns.
  H. The rule is not stated exactly ONCE: OPERATING-PLAN § 2 must carry the
     SOAK-RULE-CANONICAL marker once, and CLAUDE.md must quote the operator and
     point at it.

CHECK E–H — WHY (operator, 2026-10-15): "I don't know what, like,
documentation is causing this problem to keep on happening over and over again,
but it needs to be investigated, found, and fixed across the entire repo."
MEASURED that day: the rule "a soak is 1–2 executions" was binding from
2026-07-26, yet 46 of 50 soak contracts wanted n=10 with end dates into 2029.
Checks A–C read three files and banned one idiom ("days–weeks to prove EDGE").
The 2026-09-21 operating reset re-taught the long soak in DIFFERENT words — the
Stage-1 soak "leaves when realized cost per trade matches the modelled cost" —
in OPERATING-PLAN § 2 and the CLAUDE.md ladder, which no check read; a cost
statistic is not "edge", so even a wider idiom scan would have passed it. The
generators (soak_state.make_contract's N_CLOSES = 10 and end_date = n / rate,
the manager skill's contract template, soak-contract-guard REQUIRING n / power
/ end_date) then minted the accrual for every leg. So E scans every live
surface for the SHAPE of a long soak (duration, n, end date, statistical exit),
not for one phrase, and G scans what the generators actually EMIT.

Runs whole-file (not diff-based) so the invariant is enforced on every PR
regardless of what changed.

CHECK D — WHY IT EXISTS, AND WHY A–C COULD NOT HAVE CAUGHT IT
-------------------------------------------------------------
Checks A–C read exactly three files: ``docs/CLAUDE-RULES-CANONICAL.md``,
``.claude/skills/new-strategy/SKILL.md`` and ``.claude/skills/backtesting/
SKILL.md``. That is the guard's ENTIRE reach, and it is a measured fact about
code paths, not merely about which names appear in the source: no other path
opens any other file. So the guard enforced the doctrine's PROSE and reached
none of the CODE that decides anything.

Measured 2026-09-09: ``scripts/ml/strategy_review_packet.py::decide`` — the M7
daily strategy-review gate — graded **52 of 52 legs ``hold`` on every day it
has a committed record for** because it withholds every verdict for want of
live in-window closes. Population, stated: the **7** indexes committed under
``comms/strategy_reviews/`` at ``a77afb8e`` (2026-09-01..09-07), each reading
``graded 52 / actionable 0 / by_action {hold: 52}``, and ``below_evidence_floor
52`` on the six that carry the field. ⚠️ The brief that commissioned this check
said EIGHT days through 09-08; only seven are in the repo, and this docstring
says seven because that is what was counted here. The finding is identical
either way, and the smaller number is the measured one. Its ``Override 4`` is a literal
``shadow_soak_days < 14`` promotion gate — the exact "N days at stage"
construct the canonical rule's clause 3 names as "a policy artifact, not
evidence". The rule has been binding since 2026-07-26 and was contradicted for
those days **unseen**, because the guard that enforces it did not reach the
surface. Operator, 2026-09-09: *"we do NOT rely on live soaking for validating
strategies, only mechanics ... I don't know how many more times I can explain
this to various claudes"*. A further prose reminder is a NON-FIX; this check is
the mechanism.

WHAT IT DETECTS. Not a keyword. For each registered gate function it builds the
AST, resolves LOCAL ALIASES of the banned evidence names to a fixpoint (so
``n = headline.n_closed`` makes ``n`` banned too — a rename cannot evade it),
and reports every ``if``/``elif`` whose TEST reads a live-accrual name and
whose BODY assigns a verdict. That is the canonical rule stated mechanically:
**a verdict must not be control-dependent on calendar/live accrual.**

⚠️ IT DELIBERATELY FLAGS FORCED ``hold`` TOO, not only KILL/PROMOTE. Withholding
a verdict for want of accrual IS the prohibited gate — it is the precise shape
of the 52/52 hold — so a check that only watched the loud verdicts would have
stayed green through every one of those days.

WHY A RATCHET AND NOT A HARD FAIL. The seven live branches are Tier-3 (they
decide what a KILL/DEMOTE rests on) and cannot be changed by a session; a guard
that failed CI on day one would be disabled rather than fixed — the
``check_pr_queue_watch.py`` lesson. So known branches are declared in
``docs/claude/soak-doctrine-exceptions.json`` with a per-surface COUNT, and the
check is an EXACT match: one more than declared FAILS (a new violation), one
fewer FAILS as a stale ledger (so the number can only be walked DOWN as the
Tier-3 fix lands, never silently back up). Raising a count is a visible diff
that must name a reason and an EXISTING backlog row — the entry is VERIFIED,
not presence-only, because a ledger cheaper to lie to than to satisfy is worse
than no ledger (the ``new-table-wiring-guard`` lesson).
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

# The canonical markers that MUST persist (deleting the rule fails CI).
CANON = ROOT / "docs" / "CLAUDE-RULES-CANONICAL.md"
CANON_MECHANICS_MARKER = "A live soak may only prove serving-MECHANICS"
# The generalization to strategy legs (added 2026-07-28) must stay put.
CANON_STRATEGY_MARKER = "applies to STRATEGY legs"

# The skills that govern how a session runs a soak.
SOAK_SKILLS = ["new-strategy", "backtesting"]
# The new-strategy skill owns the lifecycle text, so it must carry the doctrine.
SKILL_MECHANICS_MARKER = "MECHANICS"
SKILL_CANON_REF = "offline edge, live mechanics"

# Banned "soak proves the edge over days–weeks" idioms (case-insensitive).
BANNED = [
    re.compile(r"confirm the backtest\s*\(days", re.I),
    re.compile(r"shadow data mature\s*\(days", re.I),
    re.compile(
        r"(soak|paper data|shadow data|live paper|paper[- ]?soak|live data)"
        r"[^.\n]{0,80}days[^.\n]{0,8}weeks",
        re.I,
    ),
    re.compile(
        r"days[^.\n]{0,8}weeks[^.\n]{0,80}"
        r"(confirm|prove|mature|edge|performance|track record)",
        re.I,
    ),
]


# ---------------------------------------------------------------------------
# Checks E–H — the long-soak SHAPE, on every live surface and generator output.
# ---------------------------------------------------------------------------

#: The ONE statement of the rule (CHECK H). Everything else points at it.
SOAK_CANON_DOC = ROOT / "docs" / "plans" / "OPERATING-PLAN-2026-09-21.md"
SOAK_CANON_MARKER = "SOAK-RULE-CANONICAL"
SOAK_OPERATOR_QUOTE = ("A soak is a mechanical verification that was already proven in "
                       "backtesting, and nothing needs to soak for more than one or two trades.")

#: LIVE instruction surfaces (CHECK E). Globs, relative to the repo root. A dated
#: decision record kept only because a mandate cites it opts out by carrying
#: SUPERSEDED_MARKER (and a banner pointing at the canonical rule).
LIVE_SURFACES = [
    "CLAUDE.md", "ROADMAP.md", "docs/*.md", "docs/plans/*.md", "docs/reference/*.md",
    "docs/integrations/*.md", "docs/roadmap/milestones.yaml",
    "docs/claude/work/SOAK-REPORT.md", "config/mandates.yaml", ".claude/skills/*/SKILL.md",
]
#: A DATED file (``*-YYYY-MM-DD*``) is a record of its day, not a live
#: instruction — EXCEPT these plans, which the instruction hierarchy names as live.
LIVE_DATED = {"docs/plans/OPERATING-PLAN-2026-09-21.md", "docs/plans/RESEARCH-PLAN-2026-09-21.md",
              "docs/plans/work-system-2026-10-04.md"}
_DATED = re.compile(r"-20\d\d-\d\d-\d\d")
#: ROADMAP.md below its generated live block is a history of sprints; only the
#: block (generated from docs/roadmap/milestones.yaml) is the live plan.
ROADMAP_LIVE = ("<!-- ROADMAP-LIVE:BEGIN", "<!-- ROADMAP-LIVE:END -->")
SUPERSEDED_MARKER = "soak-doctrine: superseded-record"
#: Per-line opt-out for a line that names the banned shape in order to forbid it
#: in words the negation filter cannot see. Use sparingly; it is visible in diffs.
LINE_OK_MARKER = "soak-doctrine: ok"

_NUM = r"(?:\d+|two|three|four|five|six|several|few|multiple|multi)"
#: The SHAPE of a long soak, matched per SENTENCE inside any paragraph that
#: mentions a soak (the 2026-09-21 teaching spanned lines: "STAGE 1 Soak … Do
#: the mechanics work, and does realized cost match … Leaves when — … AND
#: realized cost per trade matches the modelled cost"). ``needs_soak`` = the
#: sentence itself must say "soak" (for shapes too common to judge by paragraph).
SOAK_SHAPE = [
    ("a soak measured in days/weeks", True,
     re.compile(rf"(?<![-\w]){_NUM}[- ]?(?:days?|weeks?|months?|wks?)(?![-\w])", re.I)),
    ("a soak sample size of 3+", False,
     re.compile(r"n_needed\W{0,4}(?:[3-9]|\d{2,})\b|\bn needed\b|\bn and (?:its )?power\b|"
                r"\buntil n\s*(?:>=|≥|=)|"
                r"\b(?:needs?|needed|until|requires?|at least|wait\w* for|first)\s+(?:n\s*(?:>=|≥|=)\s*)?"
                r"(?:[3-9]|\d{2,})\s*(?:closes|closed trades|fills|trades|executions|packages)\b|"
                r"(?:>=|≥)\s*(?:[3-9]|\d{2,})\s*(?:closes|closed trades|fills|trades|executions)\b|"
                r"\b(?:[3-9]|\d{2,})\s*(?:fills|closes|trades)\s*(?:per|/)\s*side\b", re.I)),
    ("a soak end date / duration / rate / power", False,
     re.compile(r"\bend[ _-]?date\b|\bduration_days\b|\bsoak duration\b|expected[ _]per[ _]week|"
                r"\bexpected event rate\b|\bevent rate from the backtest\b|\bits power\b", re.I)),
    ("a statistical soak exit (cost / live-vs-backtest)", False,
     re.compile(r"(?:leaves when|exits? when|passes when|pass(?:es)? on|done when|clears when|pass rule|"
                r"pass/fail rule|until)\b[^.;]{0,120}?(?:realized cost|cost[- ]fidelity|\bR3\b|slippage|"
                r"live[- _]vs[- _]backtest)|realized cost (?:per trade )?match(?:es)?|"
                r"with realized cost matching", re.I)),
]
#: A sentence that negates the shape is not a teaching of it ("no end date",
#: "never a sample size", "not soak exit criteria", "retired", "refuses").
_NEGATION = re.compile(r"\b(?:no|not|never|nor|without|refuses?|refused|retired|removed|forbid\w*|"
                       r"banned|rejects?|isn't|cannot|instead of|superseded)\b|⛔", re.I)
#: "soak" as the thing soaking — not a compound naming a tool or a log
#: ("soak grade", "soak_book_grade", "exit_ladder_soak", "soak report").
_SOAK_WORD = re.compile(r"(?<![_\w])soak(?:s|ed|ing)?\b(?![_-]|\s+(?:grade|book|report|log|state|contract|watch))", re.I)
_SENT = re.compile(r"(?<=[.!?;])\s+|\s+[—–]\s+(?=[A-Z])")


def soak_shape_hits(text: str, where: str) -> List[str]:
    """Every sentence of ``text`` that teaches a long soak, as a finding string
    (``where:line``). Paragraph-scoped: a sentence is judged when its paragraph
    mentions a soak; a line carrying LINE_OK_MARKER is skipped."""
    out: List[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        start = i
        while i < len(lines) and lines[i].strip() and not (i > start and lines[i].lstrip().startswith(("|", "- ", "* ", "#"))):
            i += 1
        block = [ln for ln in lines[start:i] if LINE_OK_MARKER not in ln]
        para = " ".join(ln.strip() for ln in block)
        if "soak" not in para.lower():
            continue
        for sent in _SENT.split(para):
            for label, needs_soak, rx in SOAK_SHAPE:
                if needs_soak and not _SOAK_WORD.search(sent):
                    continue
                m = rx.search(sent)
                if not m or _NEGATION.search(sent[max(0, m.start() - 45):m.end()]):
                    continue
                off = next((k for k, ln in enumerate(lines[start:i]) if m.group(0)[:12] in ln), 0)
                out.append(f"{where}:{start + off + 1}: teaches {label}: …{m.group(0)[:80].strip()}… — the "
                           f"soak is MECHANICAL, 1–2 clean trades, no calendar: point at OPERATING-PLAN § 2 "
                           f"\"The soak is MECHANICAL\" instead of restating it")
                break
    return out


def live_surfaces() -> List[Path]:
    seen: Dict[Path, None] = {}
    for g in LIVE_SURFACES:
        for p in sorted(ROOT.glob(g)):
            if p.is_file():
                seen[p] = None
    return list(seen)


def check_live_language() -> List[str]:
    """CHECK E."""
    out: List[str] = []
    for p in live_surfaces():
        rel = _rel(p)
        if _DATED.search(p.name) and rel not in LIVE_DATED:
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        if SUPERSEDED_MARKER in txt:
            continue
        if rel == "ROADMAP.md" and ROADMAP_LIVE[0] in txt:
            a = txt.index(ROADMAP_LIVE[0])
            b = txt.find(ROADMAP_LIVE[1], a)
            head = txt[:a].count("\n")
            txt = "\n" * head + txt[a:b if b > 0 else None]
        out += soak_shape_hits(txt, rel)
    return out


def _import_ops(name: str):
    sys.path.insert(0, str(ROOT / "scripts" / "ops"))
    sys.path.insert(0, str(ROOT))
    import importlib  # noqa: PLC0415
    return importlib.import_module(name)


def check_contracts() -> List[str]:
    """CHECK F."""
    ss = _import_ops("soak_state")
    out = []
    for c in ss.load_contracts():
        out += [f"docs/claude/work/SOAKS.json {c.get('id')}: {p}" for p in ss.contract_problems(c)]
    if ss.MAX_N_NEEDED > 2 or ss.N_DEFAULT > 2:
        out.append("scripts/ops/soak_state.py: MAX_N_NEEDED / N_DEFAULT above 2")
    return out


def generator_outputs() -> List[Tuple[str, str]]:
    """What the soak generators actually EMIT, as (where, text)."""
    ss = _import_ops("soak_state")
    out: List[Tuple[str, str]] = []
    for kind in ("stage1", "shadow"):
        c = ss.make_contract(kind=kind, leg="probe_leg", account="bybit_1", started="2026-10-15")
        out.append((f"soak_state.make_contract({kind})", json.dumps(c, ensure_ascii=False)))
    sr = _import_ops("soak_report")
    out.append(("soak_report.grade_stage1",
                " ".join(str(x) for x in sr.grade_stage1({"disposition": "healthy", "mechanics": {}},
                                                         True, "g"))))
    mr = _import_ops("mandate_resolver")
    out.append(("mandate_resolver._soak_data_task",
                json.dumps(mr._soak_data_task("probe_leg", "bybit_1", "MD-X", "bybit_2"), ensure_ascii=False)))
    return out


def check_generators() -> List[str]:
    """CHECK G."""
    ss = _import_ops("soak_state")
    out: List[str] = []
    for kind in ("stage1", "shadow"):
        c = ss.make_contract(kind=kind, leg="probe_leg", account="bybit_1", started="2026-10-15")
        out += [f"soak_state.make_contract({kind}) emits an inadmissible contract: {p}"
                for p in ss.contract_problems(c)]
    for where, text in generator_outputs():
        out += soak_shape_hits(text.replace("\\n", " "), where)
    return out


def check_canonical_once() -> List[str]:
    """CHECK H."""
    txt = SOAK_CANON_DOC.read_text(encoding="utf-8") if SOAK_CANON_DOC.exists() else ""
    return canon_problems(txt, (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))


def canon_problems(txt: str, claude_md: str) -> List[str]:
    out: List[str] = []
    n = txt.count(SOAK_CANON_MARKER)
    if n != 1:
        out.append(f"{_rel(SOAK_CANON_DOC)} carries the {SOAK_CANON_MARKER} marker {n} time(s); "
                   "the soak rule is stated exactly ONCE, there")
    if SOAK_OPERATOR_QUOTE not in " ".join(txt.split()):
        out.append(f"{_rel(SOAK_CANON_DOC)}: the canonical soak paragraph must quote the operator verbatim")
    cl = " ".join(claude_md.split())
    if SOAK_OPERATOR_QUOTE not in cl or "OPERATING-PLAN-2026-09-21.md" not in cl \
            or "The soak is MECHANICAL" not in cl:
        out.append("CLAUDE.md must carry the short binding soak paragraph: the operator's verbatim "
                   "quote plus a pointer to OPERATING-PLAN § 2 \"The soak is MECHANICAL\"")
    return out


# ---------------------------------------------------------------------------
# Check D — a verdict must not be control-dependent on live/calendar accrual.
# ---------------------------------------------------------------------------

#: The exception ledger. Per-surface COUNTS of already-known banned branches.
EXCEPTIONS = ROOT / "docs" / "claude" / "soak-doctrine-exceptions.json"

#: Backlog files a ledger entry's ``backlog_row`` may be VERIFIED against. The
#: entry is checked, not merely present — see the module docstring.
#: ⚠️ UPDATED 2026-09-21 by the operating reset. The four review backlogs are
#: archived under `docs/archive/2026-09-21-operating-reset/registers/` and the
#: MANAGER CHECKLIST is now the one register, so a ledger entry names a
#: checklist item id (`B4`) instead of a backlog row id. Both shapes read
#: `items[].id`, so the loader below is unchanged. The archived paths stay in
#: this list because `_load_backlog_ids` skips a path that does not exist —
#: dropping them would silently stop verifying any entry that still names one.
BACKLOGS = [
    ROOT / "docs" / "claude" / "work" / "MANAGER-CHECKLIST.json",
    ROOT / "docs" / "claude" / "health-review-backlog.json",
    ROOT / "docs" / "claude" / "performance-review-backlog.json",
    ROOT / "docs" / "claude" / "ml-review-backlog.json",
    ROOT / "docs" / "claude" / "research-review-backlog.json",
]

#: Gate surfaces this check reaches: module path -> the functions that emit a
#: verdict. ⚠️ ADDING A NEW DECISION GATE MEANS ADDING IT HERE. A gate absent
#: from this map is UNREACHED, which is exactly the hole check D was written to
#: close — do not read a clean run as covering a surface not listed.
GATE_SURFACES: Dict[str, Tuple[str, ...]] = {
    "scripts/ml/strategy_review_packet.py": ("decide",),
}

#: Seed names denoting LIVE-OUTCOME or CALENDAR accrual. Local aliases are
#: resolved from these to a fixpoint, so renaming the variable does not evade
#: the check.
ACCRUAL_SEEDS: Set[str] = {
    "n_closed",                    # live closes in the review window
    "MIN_CLOSED_FOR_ACTION",       # the floor those closes are compared to
    "below_evidence_floor",
    "shadow_soak_days",            # "N days at stage" — clause 3, verbatim
    "window_days",
    "observed_close_rate_per_day",  # evidence-horizon outputs: a projection of
    "days_to_floor_point",          # WHEN accrual would suffice is the same
    "days_to_floor_optimistic",     # instrument one level up, and must never
    "days_to_floor_conservative",   # become an input to a verdict.
}

#: The attribute a gate assigns to record its verdict.
VERDICT_ATTR = "action"


def _rel(path: Path) -> str:
    """Repo-relative display path, tolerating a path outside the repo.

    ``Path.relative_to`` RAISES off-root, and this is used inside the guard's
    own error messages — so the failure path would crash instead of reporting,
    turning a finding into a traceback. Found by
    ``tests/test_soak_doctrine_guard.py``.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _names_in(node: ast.AST) -> Set[str]:
    """Every identifier and attribute name read anywhere under *node*."""
    out: Set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
    return out


def _accrual_closure(fn: ast.FunctionDef) -> Set[str]:
    """ACCRUAL_SEEDS plus every local alias of one, to a fixpoint."""
    banned = set(ACCRUAL_SEEDS)
    for _ in range(16):  # bounded; converges far sooner in practice
        grew = False
        for node in ast.walk(fn):
            targets: List[ast.expr] = []
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None:
                continue
            if not (_names_in(value) & banned):
                continue
            for t in targets:
                if isinstance(t, ast.Name) and t.id not in banned:
                    banned.add(t.id)
                    grew = True
        if not grew:
            break
    return banned


def _assigns_verdict(body: List[ast.stmt]) -> bool:
    """True if *body* assigns the verdict attribute (e.g. ``decision.action``)."""
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Attribute) and t.attr == VERDICT_ATTR:
                        return True
            elif isinstance(node, ast.AnnAssign):
                t = node.target
                if isinstance(t, ast.Attribute) and t.attr == VERDICT_ATTR:
                    return True
    return False


def find_accrual_gated_verdicts(
    source: str, func_names: Tuple[str, ...]
) -> List[Tuple[int, str, str]]:
    """Return (lineno, function, evidence-names) for each banned branch.

    A branch is banned when its TEST reads a live/calendar-accrual name and its
    BODY assigns a verdict — i.e. the verdict is control-dependent on accrual.
    """
    tree = ast.parse(source)
    wanted = set(func_names)
    hits: List[Tuple[int, str, str]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name not in wanted:
            continue
        banned = _accrual_closure(fn)
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            used = _names_in(node.test) & banned
            if used and _assigns_verdict(node.body):
                hits.append((node.lineno, fn.name, ", ".join(sorted(used))))
    return sorted(set(hits))


def _load_backlog_ids() -> Set[str]:
    ids: Set[str] = set()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.runtime import checklist_store as _ck  # noqa: PLC0415
    for path in BACKLOGS:
        is_ck = _ck.is_checklist_path(path)  # monolith, or per-row store once cut over
        if not (_ck.exists(path) if is_ck else path.exists()):
            continue
        try:
            data = (_ck.load_path(path) if is_ck
                    else json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        rows = data.get("items") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                ids.add(row["id"])
    return ids


def check_gate_surfaces() -> Tuple[List[str], List[str]]:
    """Check D. Returns (errors, notices)."""
    errors: List[str] = []
    notices: List[str] = []

    ledger: Dict[str, dict] = {}
    if EXCEPTIONS.exists():
        try:
            raw = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
            ledger = {
                k: v for k, v in (raw.get("surfaces") or {}).items()
                if isinstance(v, dict)
            }
        except (OSError, ValueError) as exc:
            errors.append(
                f"{_rel(EXCEPTIONS)} is unreadable ({exc}). An "
                "unreadable ledger is 'we could not look', never 'nothing is "
                "declared' — refusing rather than passing."
            )
            return errors, notices

    backlog_ids = _load_backlog_ids()

    for rel, func_names in GATE_SURFACES.items():
        path = ROOT / rel
        if not path.exists():
            errors.append(
                f"{rel} is registered in GATE_SURFACES but does not exist. A "
                "gate surface that vanished must be de-registered deliberately, "
                "not skipped silently."
            )
            continue
        try:
            hits = find_accrual_gated_verdicts(
                path.read_text(encoding="utf-8"), func_names
            )
        except SyntaxError as exc:
            errors.append(f"{rel} could not be parsed for check D: {exc}")
            continue

        entry = ledger.get(rel, {})
        allowed = entry.get("known_accrual_gated_branches")
        if not isinstance(allowed, int):
            allowed = 0
        found = len(hits)

        if found > allowed:
            detail = "; ".join(f"line {ln} ({fn}, reads: {ev})" for ln, fn, ev in hits)
            errors.append(
                f"{rel}: {found} verdict branch(es) are control-dependent on "
                f"live/calendar accrual, but the ledger declares {allowed}. "
                f"Branches: {detail}. A verdict must not be gated on accrual "
                "(CLAUDE-RULES-CANONICAL.md § 'Promotion evidence — offline "
                "edge, live mechanics', clause 3: 'No gate may require "
                "calendar-time accrual to prove edge'). Prove the edge OFFLINE. "
                f"If a branch here is genuinely new and Tier-3-blocked, raising "
                f"{_rel(EXCEPTIONS)} needs a reason AND an existing "
                "backlog row — it is not a way to silence the check."
            )
        elif found < allowed:
            errors.append(
                f"{rel}: the ledger declares {allowed} accrual-gated verdict "
                f"branch(es) but only {found} remain. The ledger is STALE — "
                f"lower it to {found}. It ratchets DOWN only, so a repaired "
                "surface can never leave headroom for the violation to return "
                "unseen."
            )
        elif found:
            row = entry.get("backlog_row")
            if not isinstance(row, str) or row not in backlog_ids:
                errors.append(
                    f"{rel}: the ledger declares {found} known accrual-gated "
                    f"branch(es) but its backlog_row {row!r} is not a row in any "
                    "review backlog. The exception is VERIFIED, not "
                    "presence-only: an entry naming a row that does not exist "
                    "is how a real finding gets silenced."
                )
            else:
                detail = "; ".join(f"L{ln} ({ev})" for ln, fn, ev in hits)
                notices.append(
                    f"{rel}: {found} KNOWN accrual-gated verdict branch(es) "
                    f"[{detail}] — declared in "
                    f"{_rel(EXCEPTIONS)}, tracked by {row}. This is "
                    "a live contradiction of the canonical rule, held open "
                    "because the repair is Tier-3. It is NOT compliance."
                )

    return errors, notices


def self_test() -> int:
    """Planted defects for CHECKS E–H: every one must be caught, every control
    must stay quiet. A green guard run proves nothing on its own here — it was
    green through the whole 2026-09-21..10-15 re-teaching."""
    ok = True

    def ck(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    planted = {
        "soak for 3 weeks": "Put the leg on bybit_1 and let it soak for 3 weeks.",
        "a 14-day shadow soak": "Then a fresh 14-day shadow soak before any promotion talk.",
        "cost exit (the 2026-09-21 ladder, across lines)":
            "STAGE 1   Soak   bybit_1\n  Do the mechanics work?\n  Leaves when — orders place, AND realized "
            "cost\n  per trade matches the modelled cost.",
        "contract with rate, n and power, end date (the 2026-10-04 rule 3)":
            "3. **Every soak carries a contract.** It states what it verifies, the expected\n"
            "   event rate from the backtest, the n and power it needs, an **end date**.",
        "n_needed: 10": "Each soak contract sets n_needed: 10 closes.",
        "needs at least 10 closes": "A soak needs at least 10 closes per leg.",
        "R3 fills per side": "The soak clears when R3 sees 10 fills per side.",
        "prop soak with realized cost matching": "a Stage-1 soak on bybit_1 with realized cost matching the backtest",
    }
    for label, text in planted.items():
        ck(f"planted: {label} is caught", soak_shape_hits(text, "t"))
    canon = SOAK_CANON_DOC.read_text(encoding="utf-8")
    a = canon.find("### The soak is MECHANICAL")
    controls = {
        "the canonical paragraph itself": canon[a:canon.find("**Stage 2 is one stage", a)],
        "an observe-only log's row count": "`exit_ladder_soak` has shipped — n=277 rows so far.",
        "a soak GRADE's staleness": "R5 weekly soak grade lands | newest record >= 8 days old",
        "a negated calendar": "A soak has no end date, no duration and never a sample size.",
        "a pipeline id": "open items: PI-20260922-R5-STAGE0-VERDICT-FLIPS-ON-A-9-DAY-WINDOW-SHIFT soaking",
        "a demotion window": "reads the leg's LAST 40 closed trades; returns it to the Stage-1 soak book",
        "an ok-marked line": "a soak for 3 weeks <!-- soak-doctrine: ok -->",
    }
    for label, text in controls.items():
        ck(f"control: {label} stays quiet", not soak_shape_hits(text, "t"))
    ss = _import_ops("soak_state")
    old = {"id": "SOAK-stage1-bybit_1-x", "leg": "x", "account": "bybit_1", "kind": "stage1",
           "verifies": "v", "metric": "m", "n_needed": 10, "power": "R3 floor", "started": "2026-10-01",
           "end_date": "2026-12-11", "pass_rule": "R3 verdict consistent: CI95 upper <= modelled + 2 bps",
           "fail_rule": "f", "design": "too_long"}
    ck("CHECK F: the retired accrual contract shape is refused", len(ss.contract_problems(old)) >= 4)
    ck("CHECK F: the generator's contract is admissible",
       ss.contract_problems(ss.make_contract(kind="stage1", leg="x", account="bybit_1", started="2026-10-01")) == [])
    ck("CHECK G: current generator outputs are clean", check_generators() == [])
    ck("CHECK G: an emitted '>=10 fills per side' would be caught",
       soak_shape_hits("Soak clears when it has 10 fills per side (RULE-R3).", "g"))
    good_cl = f"... {SOAK_OPERATOR_QUOTE} ... OPERATING-PLAN-2026-09-21.md § 2 \"The soak is MECHANICAL\""
    ck("CHECK H: the real canon passes", canon_problems(canon, good_cl) == [])
    ck("CHECK H: a second canonical marker is refused",
       canon_problems(canon + SOAK_CANON_MARKER, good_cl) != [])
    ck("CHECK H: CLAUDE.md without the pointer is refused", canon_problems(canon, SOAK_OPERATOR_QUOTE) != [])
    print("soak-doctrine self-test (E–H):", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
    errors: list[str] = []

    canon = CANON.read_text(encoding="utf-8") if CANON.exists() else ""
    if CANON_MECHANICS_MARKER not in canon:
        errors.append(
            "CLAUDE-RULES-CANONICAL.md is missing the binding rule marker "
            f"'{CANON_MECHANICS_MARKER}' (§ 'Promotion evidence — offline edge, "
            "live mechanics'). The soak-is-mechanics-only rule must not be removed."
        )
    if CANON_STRATEGY_MARKER not in canon:
        errors.append(
            "CLAUDE-RULES-CANONICAL.md § 'Promotion evidence' must state that the "
            f"rule '{CANON_STRATEGY_MARKER}' (not just ML models) — a strategy "
            "paper-soak is a mechanics check, not a performance test."
        )

    for name in SOAK_SKILLS:
        p = ROOT / ".claude" / "skills" / name / "SKILL.md"
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        for rx in BANNED:
            m = rx.search(txt)
            if m:
                errors.append(
                    f".claude/skills/{name}/SKILL.md reintroduces the banned "
                    f"soak-as-performance idiom: ...{m.group(0)[:90].strip()}... — "
                    "a soak proves MECHANICS (1–2 live executions, hours), not edge "
                    "over days–weeks. The edge is decided OFFLINE before the soak."
                )
        if name == "new-strategy":
            if SKILL_MECHANICS_MARKER not in txt:
                errors.append(
                    ".claude/skills/new-strategy/SKILL.md must frame the paper/shadow "
                    "soak as a MECHANICS check (the word 'MECHANICS' is missing from "
                    "the lifecycle)."
                )
            if SKILL_CANON_REF not in txt:
                errors.append(
                    ".claude/skills/new-strategy/SKILL.md must cross-reference the "
                    f"canonical rule ('{SKILL_CANON_REF}')."
                )

    d_errors, d_notices = check_gate_surfaces()
    errors.extend(d_errors)
    errors.extend(check_live_language())
    errors.extend(check_contracts())
    errors.extend(check_generators())
    errors.extend(check_canonical_once())

    if errors:
        print("SOAK-DOCTRINE GUARD FAILED:\n")
        for e in errors:
            print("  - " + e)
        print(
            "\nDoctrine (CLAUDE-RULES-CANONICAL.md § 'Promotion evidence — offline "
            "edge, live mechanics'): performance/edge is proven OFFLINE (a "
            "live-faithful backtest + the backfill/live-simulator over deep history) "
            "BEFORE any soak. A soak validates MECHANICS only — that the live "
            "executions match the simulator — needing 1–2 executions (hours). Never "
            "frame a soak as gathering performance over days–weeks; if a leg reaches "
            "soak without an adequate offline edge proof, the gap is the missing "
            "backtest, not more soak time."
        )
        return 1

    for n in d_notices:
        print("soak-doctrine: KNOWN OPEN VIOLATION — " + n)
    print("soak-doctrine guard: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
