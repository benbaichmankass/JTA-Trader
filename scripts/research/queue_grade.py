#!/usr/bin/env python3
# wiring: .github/workflows/research-queue-grade.yml (cron + dispatch); scripts/ci/check_pr_landing.py --verify
"""Grade ran units MECHANICALLY from their committed results, and say when a
result is not machine-gradable instead of guessing.

WHY THIS EXISTS (operator, 2026-09-28, relayed by the manager)
---------------------------------------------------------------
Eight units ran between 2026-09-22 and 2026-09-28 and sat `queued` with their
results on `main` until a session graded them by hand (PR #13735). A queue
that runs 24/7 without a session needs its results read without one too.

WHAT IT DOES
------------
For every `research/queue/*.yaml` with `status: queued` and a
`last_dispatched_at` stamp, it collects the committed evidence the unit's
`lands:` block points at and applies ONE of two machine graders:

  * E5 rows  -- `research/results/<unit>/*.jsonl` (the research-result
    contract). The producer already applied the unit's pre-registered rule
    per row (that is what an E5 verdict IS), so the mechanical read is
    UNANIMITY: >= lands.min_rows rows, every row `read_state: measured`, and
    every verdict the same one of pass / fail / no_action_warranted.
  * e35 corpus -- `docs/research/e35-bracket-corpus.jsonl` rows tagged with
    the unit id, for units whose rule id starts with
    `RULE-TPL-E35-BRACKET-`: PASS if any cell reads `is_oos_pass` with
    base_oos_trades >= 39; no_action_warranted if none does at >= 39;
    indeterminate below 39.

Then it lands the disposition on the unit file as TEXT EDITS (the same
line-level discipline `dispatch_queue._stamp` uses, so nothing else in the
file moves):

  * pass / no_action_warranted -> `status: done` + a `grading:` block naming
    the verdict, the rows, and the evidence paths;
  * pass on a TEMPLATE cell     -> also a DISCOVERY, not a confirmation
    (RESEARCH-CONFIRM-FRESH-WINDOW, operator 2026-10-16): the grader ADDS exactly
    one fresh-window confirmation unit (`confirmation_unit`: same rule, same run,
    evidence confined to data after the PASS run, `requires_result` on the PASS,
    `not_before` once that data can exist) and the block says `discovery:
    unconfirmed`, `confirm_unit`, `selected_from_cells` (the multiple-testing
    denominator). Programme nodes are excluded: their DAG owns confirmation.
    A recurring cell's later PASS reuses that one unit. The confirmation reads
    `confirmed` only when it passes on one of the parent's passing cells;
  * HOLDOUT (operator 2026-10-16, "Holdout re-run"): when the run itself held
    the latest span back before selection (rows carry
    `measurement.holdout.confirmation`), discovery and confirmation came from
    ONE run: the block records confirmed / not_replicated / underpowered and
    NO further unit opens. A PASS that did not hold out, on a workflow in
    `_HOLDOUT_INPUTS` (m20), opens a holdout RE-RUN that dispatches now
    instead of a forward wait; a forward wait (sized per leg from the measured
    OOS trade rate, `forward_wait_days`) remains only for harnesses with a
    window input and no holdout input. An existing confirmation for the PASS
    is reused, never duplicated, and a forward-wait unit that never fired is
    retired as superseded by a live holdout re-run of the same PASS;
  * fail on a DETERMINISTIC template cell (or confirmation unit) -> `status:
    done`, verdict fail, NO same-window replay (it reproduces the same number).
    A FAIL closes a cell, never a family: the family-retirement protocol
    (#18557) owns retirement;
  * fail, first time, on any other auto unit, or a non-deterministic template
    cell (`confirm_fail`)       -> NOT a kill: `last_dispatched_at: null`
    (re-queued for a confirmatory run) + `grading.confirmatory_run: 1`;
  * fail, second time           -> `status: done`, verdict fail, both runs
    named. The confirmatory pass reads ONLY rows landed since the
    re-dispatch (`last_dispatched_at` after the reset); with none yet it is
    not due, and a confirmatory PASS (or anything but fail) makes the two
    runs {fail, pass}: not unanimous -> `needs_review`, never closed either
    way by the grader;
  * anything else (mixed verdicts, a producer_failed row, too few rows,
    not_applicable, indeterminate) -> `grading.needs_review: true` with the
    reason; status unchanged, so a session's `needs_review` bucket is
    `grep -l "needs_review: true" research/queue/*.yaml`.
  * a recurring-cadence unit (weekly/monthly) is never closed: only
    `grading.latest` is refreshed, and a fail is recorded, not re-queued (the
    cadence re-asks anyway).

HAND-WRITTEN UNITS WHOSE ROWS ATTEST THEIR OWN RULE (RESEARCH-GRADE-BACKLOG, 2026-10-15)
--------------------------------------------------------------------------------------
Until 2026-10-15 a hand-written unit was graded only if it opted in with
`grading: {auto: true}`, and no step of the loop ever closed the rest:
research-ops READ their results (its record lists the verdicts) but its
queue edits hold for a human (E57), and this grader skipped them. MEASURED on
main 55bb4fdd: 140 queued hand-written units had result rows, 130 of them with
EVERY row stamped with the unit's own `decision_rule.id` -- i.e. the producer
(script_run / harness_dispatch_result / ml_bakeoff) graded the run under that
unit's registered rule. Those are the units this path now grades:

  * `cadence: once`, not `generated`, no `grading.auto`;
  * every E5 row for the unit carries `decision_rule.id` equal to the unit's
    own, non-empty rule id (a row from a generic producer -- e.g.
    RULE-E7-HARNESS-DISPATCHABLE or RULE-M20-EXIT-LEVER-IS-OOS-GATE -- is NOT
    an application of the unit's rule and leaves the unit to a session);
  * grading is then the same unanimity read as above, with ONE difference: a
    FAIL closes the unit (`status: done`, verdict fail). The confirmatory
    re-run is the template grader's policy for mechanically generated cells;
    it is not part of a session-registered rule, and re-dispatching a
    deterministic replay over the same fixed window reproduces the same number
    at the cost of a dispatcher slot. The block says `attested: <rule id>`.

DETERMINISM. The `grading:` block is a pure function of (the unit at the
merge-base, the rows at HEAD, `graded_at`), so `check_pr_landing.py` can
re-run `--verify` at a PR's merge-base and demand the same bytes before a
grade PR self-lands. A grade nobody can reproduce holds for a human.

Tier-1 research tooling: reads research/results + corpora, writes only
research/queue/RQ-*.yaml (modifies graded units; adds only the confirmation
units they open, which `--verify` re-derives byte-for-byte). Never touches
config/, src/ or a live path.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))
QUEUE = Path("research/queue")
RESULTS = Path("research/results")
E35_CORPUS = Path("docs/research/e35-bracket-corpus.jsonl")
E35_FLOOR = 39
# RESEARCH-LOOP-AUDIT RC5 (2026-10-15, docs/research/research-loop-audit-2026-10-15.md § 2a):
# a recurring e35 unit graded indeterminate at base_oos_trades < floor/3 cannot reach the floor
# on its own cadence (MEASURED: 19 monthly daily-bar legs at OOS n 0-11, adding ~1 trade/month),
# so re-asking it monthly spends a runner slot to learn nothing. It is NOT retired (refinement-
# first, operator 2026-09-27): the grader stretches the re-ask to RECHECK_DAYS via its own
# grading block, which dispatch_queue.due() honours. The unit's registered fields never move.
INFEASIBLE_FRACTION = 3
RECHECK_DAYS = 90
MECHANICAL = ("pass", "fail", "no_action_warranted")
_RECURRING = ("daily", "weekly", "monthly")


def _yaml():
    import yaml
    return yaml


def _parse_ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ── evidence collection ─────────────────────────────────────────────────────
def e5_rows(root: Path, unit_id: str, since: Optional[datetime]) -> List[Tuple[str, Dict[str, Any]]]:
    out = []
    for f in sorted((root / RESULTS / unit_id).glob("*.jsonl")) if (root / RESULTS / unit_id).is_dir() else []:
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            ts = _parse_ts(r.get("generated_at") or (r.get("run") or {}).get("started_at"))
            # With a window, a row that cannot be dated cannot be placed in it:
            # excluded, never assumed new (review fix 2026-09-29).
            if since and (ts is None or ts < since):
                continue
            out.append((f.relative_to(root).as_posix(), r))
    return out


def rule_attested(root: Path, unit_id: str, unit: Dict[str, Any]) -> bool:
    """True when a hand-written `once` unit's E5 rows ALL carry its own rule id.

    That stamp is how a producer says it graded the run under this unit's
    registered rule; a generic producer rule id (or none) means it did not, so
    the unit stays with a session. No rows -> False (nothing to attest)."""
    rid = str((unit.get("decision_rule") or {}).get("id") or "").strip()
    if not rid or str(unit.get("cadence") or "once") != "once":
        return False
    seen = 0
    for _f, r in e5_rows(root, unit_id, None):
        rule = r.get("decision_rule") if isinstance(r.get("decision_rule"), dict) else {}
        if str(rule.get("id") or r.get("decision_rule_id") or "").strip() != rid:
            return False
        seen += 1
    return seen > 0


def session_owned(unit: Dict[str, Any]) -> bool:
    """True when a hand-written unit's disposition belongs to a session, so the attested
    path must not touch it (RESEARCH-LOOP-AUDIT RC1 delta, 2026-10-15): it opted out with
    `grading: {auto: false}`, or it carries ANY `grading:` block a session wrote (no
    `auto: true`) -- a hand grade, a needs-review note, a triage verdict. Without this the
    attested path would overwrite a human read whenever the rows happen to attest."""
    g = unit.get("grading")
    return isinstance(g, dict) and g.get("auto") is not True


def confirm_fail(unit: Dict[str, Any]) -> bool:
    """True when an attested hand-written unit's first FAIL should be re-run once before it
    closes (manager, 2026-10-15 06:58Z): only when a re-run can produce a DIFFERENT number --
    an ML training run (`ml_bakeoff:` block), a unit that declares top-level `seeds` /
    `n_seeds` (stochastic content it controls), or an explicit `grading.confirm_fail: true`.
    A deterministic replay over a fixed window -- including a simulation whose argv pins its
    seeds -- reproduces the identical number, so re-running it only spends a runner slot."""
    g = unit.get("grading") if isinstance(unit.get("grading"), dict) else {}
    return bool(g.get("confirm_fail") is True or isinstance(unit.get("ml_bakeoff"), dict)
                or unit.get("seeds") is not None or unit.get("n_seeds") is not None)


def _declared_runs(lands: Dict[str, Any]) -> int:
    """`lands.runs: N` -- a unit designed as N dispatches (the RQ-20260928-005 fan-out shape)
    is not graded until N result files landed; `lands.min_rows` still counts rows."""
    try:
        return int(lands.get("runs") or 1)
    except (TypeError, ValueError):
        return 1


def e35_rows(root: Path, unit_id: str) -> List[Dict[str, Any]]:
    p = root / E35_CORPUS
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if unit_id not in ln:
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("research_unit") == unit_id:
            out.append(r)
    return out


# ── graders (pure) ──────────────────────────────────────────────────────────
def grade_e5(rows: List[Tuple[str, Dict[str, Any]]], min_rows: int) -> Dict[str, Any]:
    n = len(rows)
    files = sorted({f for f, _ in rows})
    if n < max(1, min_rows):
        return {"verdict": None, "reason": f"{n} result row(s) on main, lands.min_rows is {min_rows}", "rows": n, "files": files}
    # ⚠️ A `producer_failed` row is "we looked and it broke", not a result, so it cannot
    # veto a `measured` row from a LATER run of the same unit. Until 2026-10-04 any mix
    # read "read_state not unanimously measured" -> needs_review forever: MEASURED, the 3
    # prop-fit units whose first run died and whose re-run measured (RQ-20260928-025/-026/
    # -029) and RQ-20260930-501 (a malformed verdict.json, then a clean pass) never closed.
    # When at least one measured row exists, grade the measured rows and NAME the failures
    # skipped; with none, every state still lands in the reason as before.
    measured = [(f, r) for f, r in rows if str(r.get("read_state")) == "measured"]
    superseded = n - len(measured) if measured else 0
    if measured:
        rows = measured
    # ⚠️ A `wiring_only` row RE-GRADED by a later row of the SAME run is superseded by
    # it. `wiring_only` means "measured, but the producer could not apply the unit's
    # rule"; when a later row for the same `produced_by.run_id` carries a mechanical
    # verdict (scripts/research/regrade_wiring_only_results.py appends one from the
    # landed measurement, never editing the original), the original is the record of
    # the producer's failure, not a second opinion on the measurement. MEASURED
    # 2026-10-06: 8 rows across 6 units landed wiring_only because the result job had
    # no PyYAML; without this, {wiring_only, fail} read "not unanimous" forever.
    regraded = {str((r.get("produced_by") or {}).get("run_id") or "") for _, r in rows
                if str(r.get("verdict")) in MECHANICAL + ("indeterminate",)}
    kept = [(f, r) for f, r in rows
            if not (str(r.get("verdict")) == "wiring_only"
                    and str((r.get("produced_by") or {}).get("run_id") or "") in regraded)]
    superseded += len(rows) - len(kept)
    rows = kept
    n = len(rows)
    states = sorted({str(r.get("read_state")) for _, r in rows})
    verdicts = sorted({str(r.get("verdict")) for _, r in rows})
    if states != ["measured"]:
        return {"verdict": None, "reason": f"read_state not unanimously measured: {states}", "rows": n, "files": files}
    if len(verdicts) != 1 or verdicts[0] not in MECHANICAL + ("indeterminate",):
        return {"verdict": None, "reason": f"verdicts not unanimous-mechanical: {verdicts}", "rows": n, "files": files}
    tail = f" ({superseded} earlier producer_failed / re-graded wiring_only row(s) superseded)" if superseded else ""
    return {"verdict": verdicts[0], "reason": f"{n} row(s), all measured, all {verdicts[0]}{tail}", "rows": n, "files": files,
            **_selection(rows)}


def _selection(rows: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """What a fresh-window confirmation needs from the rows that were graded: how many cells the
    verdict was selected from (`measurement.cells_swept`, summed; None unless EVERY row says), the
    passing cells (`measurement.passing_cells`, union), and the newest row timestamp -- the last
    moment of data the run could have seen."""
    swept: Optional[int] = 0
    cells: set = set()
    seen: Optional[datetime] = None
    holdout: Optional[Dict[str, Any]] = None
    oos_n: Optional[int] = 0
    split: Optional[datetime] = None
    for _f, r in rows:
        m = r.get("measurement") if isinstance(r.get("measurement"), dict) else {}
        if holdout is None and isinstance(m.get("holdout"), dict):
            holdout = m["holdout"]
        try:
            oos_n = None if oos_n is None or m.get("base_trades_OOS") is None else oos_n + int(m["base_trades_OOS"])
        except (TypeError, ValueError):
            oos_n = None
        sp = _parse_ts(m.get("split"))
        if sp and (split is None or sp < split):
            split = sp
        try:
            swept = None if swept is None or m.get("cells_swept") is None else swept + int(m["cells_swept"])
        except (TypeError, ValueError):
            swept = None
        if isinstance(m.get("passing_cells"), list):
            cells.update(str(c) for c in m["passing_cells"])
        ts = _parse_ts(r.get("generated_at") or (r.get("run") or {}).get("started_at"))
        if ts and (seen is None or ts > seen):
            seen = ts
    out = {"cells_swept": swept if rows else None, "passing_cells": sorted(cells),
           "seen_until": seen.isoformat() if seen else None}
    if holdout is not None:
        out["holdout"] = holdout
    if rows and oos_n and split and seen and seen > split:
        out["oos_trades_per_day"] = round(oos_n / max(1.0, (seen - split).total_seconds() / 86400), 6)
    return out


def grade_e35(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"verdict": None, "reason": "no corpus rows tagged with this unit", "rows": 0, "files": [E35_CORPUS.as_posix()]}
    n_oos = max((int(r.get("base_oos_trades") or 0) for r in rows), default=0)
    passing = sorted({f"{r.get('leg')}:{r.get('cell')}" for r in rows if r.get("gate_verdict") == "is_oos_pass"})
    if n_oos < E35_FLOOR:
        return {"verdict": "indeterminate", "reason": f"base_oos_trades {n_oos} < {E35_FLOOR} (unresolvable_at_current_n)",
                "rows": len(rows), "files": [E35_CORPUS.as_posix()], "passing_cells": passing, "base_oos_trades": n_oos}
    if passing:
        return {"verdict": "pass", "reason": f"{len(passing)} cell(s) is_oos_pass at base_oos_trades {n_oos}: {passing[:6]}",
                "rows": len(rows), "files": [E35_CORPUS.as_posix()], "passing_cells": passing, "cells_swept": len(rows)}
    return {"verdict": "no_action_warranted", "reason": f"0 of {len(rows)} cells is_oos_pass at base_oos_trades {n_oos}",
            "rows": len(rows), "files": [E35_CORPUS.as_posix()], "passing_cells": []}


# ── fresh-window confirmation (RESEARCH-CONFIRM-FRESH-WINDOW, operator 2026-10-16) ──
#: FORWARD-WAIT fallback only (a harness with a window input but no holdout input): the wait is
#: sized per leg from its measured OOS trade rate to the rule's floor (`forward_wait_days`); this
#: constant is used only when the rate cannot be read. MEASURED 2026-10-16 (PI-20261016-QOTFUEXV-0003):
#: a flat 60 days reached the 25-trade floor for none of the 13 m20 PASS legs.
CONFIRM_WAIT_DAYS = 60
CONFIRM_WAIT_MAX_DAYS = 366
#: Workflows with a PRE-REGISTERED HOLDOUT input (operator decision 2026-10-16, "Holdout re-run"):
#: discovery and confirmation in ONE run, so a PASS that did not hold out is re-run with it NOW
#: instead of waiting for data to accrue. Preferred over `_FRESH_WINDOW_INPUTS` when both exist.
_HOLDOUT_INPUTS = {
    "m20-exit-lever-sweep.yml": {"holdout_frac": "0.25"},
}
_HOLDOUT_POLICY = ("operator 2026-10-16 (popup, 'Holdout re-run'): \"From now on, each sweep holds back the "
                   "most recent ~25% of history before it chooses settings, then tests the winner on that "
                   "held-back part, so discovery and confirmation come from one run with no wait. The 13 "
                   "current passes get re-run that way now, within days. Cost: each choice is made on 25% "
                   "less data.\"")
#: FORWARD-WAIT workflows (a window input, no holdout input): workflow -> fn(after) giving the input
#: overrides that confine the evidence to data after the PASS run. EMPTY today: m20 confirms by
#: holdout re-run (`_HOLDOUT_INPUTS`), and no other harness can express a window yet
#: (PI-20261016-QOTFUEXV-0002). A PASS on a workflow in neither map gets its confirmation unit
#: authored `blocked` with the reason, never a same-window re-run labelled fresh.
_FRESH_WINDOW_INPUTS: Dict[str, Any] = {}
_POLICY = ("operator 2026-10-16 (popup, 'Yes, adopt'): a single-window PASS on a template cell is a "
           "discovery; it opens exactly one fresh-window confirmation unit before it can feed any Tier-3 proposal")


def template_cell(unit: Dict[str, Any]) -> bool:
    """A cell generated from a research/templates family. Programme nodes (`programme:*`) are not:
    their DAG registers its own confirmation nodes (P3's best-of-3 -> one fresh window)."""
    gen = unit.get("generated")
    return isinstance(gen, dict) and not str(gen.get("family") or "").startswith("programme:")


def confirmation_of(unit: Dict[str, Any]) -> Optional[str]:
    c = unit.get("confirmation")
    return str(c.get("of")) if isinstance(c, dict) and c.get("of") else None


def confirm_unit_id(parent_id: str, graded_at: str) -> str:
    """Deterministic (E58 --verify re-derives it): hashed-scheme id dated on the grading day, h4 from
    the parent id. Hashed ids are exempt from the 001-899 / 900-999 bands (research-queue-id-bands)."""
    import hashlib
    h4 = hashlib.sha256(f"confirm:{parent_id}".encode()).hexdigest()[:4]
    return f"RQ-{graded_at.replace('-', '')[:8]}-{h4}-01"


def _swap_id(obj: Any, old: str, new: str) -> Any:
    if isinstance(obj, str):
        return obj.replace(old, new)
    if isinstance(obj, list):
        return [_swap_id(x, old, new) for x in obj]
    if isinstance(obj, dict):
        return {k: _swap_id(v, old, new) for k, v in obj.items()}
    return obj


def confirmation_roadmap(unit: Dict[str, Any]) -> Optional[List[str]]:
    """The roadmap milestone(s) a confirmation unit carries -- it is a NEW queue unit, and
    roadmap-map-guard refuses one without (`enforce_units_from`). The parent's own `roadmap`, else the
    milestone its template family maps to (queue_replenish.FAMILY_ROADMAP, the generator's one map),
    else None: then no unit is authored at all."""
    rm = unit.get("roadmap")
    rm = [rm] if isinstance(rm, str) else rm
    if isinstance(rm, list) and [m for m in rm if str(m).strip()]:
        return [str(m) for m in rm if str(m).strip()]
    from scripts.research.queue_replenish import FAMILY_ROADMAP  # noqa: PLC0415 -- one map, lazily
    fam = FAMILY_ROADMAP.get(str((unit.get("generated") or {}).get("family") or ""))
    return [str(m) for m in fam] if fam else None


def forward_wait_days(unit: Dict[str, Any], g: Dict[str, Any]) -> Tuple[int, str]:
    """(days, basis) a forward-wait confirmation waits: until the leg's measured OOS trade rate
    can have accrued the rule's floor (`power.expected_n`, else 25), clamped to a year. The flat
    CONFIRM_WAIT_DAYS only when no rate was reported."""
    floor = (unit.get("power") or {}).get("expected_n")
    floor = floor if isinstance(floor, int) and not isinstance(floor, bool) and floor > 0 else 25
    rate = g.get("oos_trades_per_day")
    if isinstance(rate, (int, float)) and rate > 0:
        import math
        days = min(CONFIRM_WAIT_MAX_DAYS, max(1, int(math.ceil(floor / rate))))
        return days, f"{floor} trades at the measured {rate:.4f} OOS trades/day"
    return CONFIRM_WAIT_DAYS, "no OOS trade rate reported; flat fallback"


def confirmation_mode(unit: Dict[str, Any]) -> Optional[str]:
    """holdout_rerun / forward_wait for a confirmation unit (units authored before modes existed
    carry `window.mode: most_recent_disjoint` and are forward-wait); None otherwise."""
    c = unit.get("confirmation")
    if not isinstance(c, dict):
        return None
    return str(c.get("mode") or "forward_wait")


def confirmation_unit(unit: Dict[str, Any], g: Dict[str, Any], child_id: str,
                      header: Optional[str] = None) -> str:
    """The ONE fresh-window confirmation unit a template-cell PASS opens. Same decision rule (id,
    statistic, rule text, registration) and same run as the PASS, re-pointed at the child id; the
    window is confined to data after the PASS run's last row when the workflow can say so
    (`_FRESH_WINDOW_INPUTS`), else the unit is `blocked` and says why. A pure function of (the parent
    unit, the graded rows, the id), so `--verify` reproduces it byte-for-byte."""
    yaml = _yaml()
    pid = str(unit.get("id"))
    after = _parse_ts(g.get("seen_until")) or _parse_ts(unit.get("last_dispatched_at"))
    run = _swap_id(unit.get("run") or {}, pid, child_id)
    wf = str(run.get("workflow") or "")
    if wf in _HOLDOUT_INPUTS:
        return _holdout_rerun_unit(unit, g, child_id, run, header)
    window_fn = _FRESH_WINDOW_INPUTS.get(wf)
    wait_days, wait_basis = forward_wait_days(unit, g)
    blocked = None
    if after is None:
        blocked = "the PASS run's data end is unknown (no dated row, no stamp), so no disjoint window can be named"
    elif window_fn is None:
        blocked = (f"workflow {wf or '(none)'} has no input that confines the evidence to data after "
                   f"{after.isoformat()}; wire one (queue_grade._FRESH_WINDOW_INPUTS) and unblock this unit")
    else:
        run = {**run, "inputs": {**(run.get("inputs") or {}), **window_fn(after)}}
    n_cells = g.get("cells_swept")
    selected = (f"{n_cells} cell(s)" if isinstance(n_cells, int) else
                "an unrecorded number of cells (the producer did not report cells_swept)")
    cells = list(g.get("passing_cells") or [])
    out: Dict[str, Any] = {
        "id": child_id,
        "title": f"Fresh-window confirmation of {pid}: {unit.get('title')}",
        "status": "blocked" if blocked else "queued",
        "cadence": "once",
    }
    skip = {"id", "title", "status", "cadence", "generated", "grading", "last_dispatched_at",
            "requires_result", "not_before", "confirmation", "run", "dispatch_precondition"}
    for k, v in unit.items():
        if k not in skip:
            out[k] = _swap_id(v, pid, child_id) if k == "lands" else v
    out["roadmap"] = confirmation_roadmap(unit)
    out["question"] = (f"CONFIRMATION of {pid}'s PASS on a window it did not see (data after "
                       f"{after.isoformat() if after else 'UNKNOWN'}), under the SAME registered rule: "
                       f"{unit.get('question')}")
    out["run"] = run
    out["requires_result"] = {"unit": pid, "verdict": "pass"}
    if after is not None:
        out["not_before"] = (after + timedelta(days=wait_days)).isoformat()
    out["confirmation"] = {
        "of": pid,
        "mode": "forward_wait",
        "policy": _POLICY,
        "window": {"after": after.isoformat() if after else None, "mode": "most_recent_disjoint",
                   "wait_days": wait_days, "wait_basis": wait_basis},
        "selected_from_cells": n_cells if isinstance(n_cells, int) else None,
        "passing_cells": cells,
        "note": (f"{pid} PASSED on one window, selected from {selected}; passing cell(s) {cells[:6] or 'not named'}. "
                 "That count is the multiple-testing denominator (row RESEARCH-TRIAL-LEDGER). This unit re-asks "
                 "on fresh data only; it CONFIRMS when it passes on at least one of those cells, and until then "
                 f"{pid} may not feed a Tier-3 proposal."),
    }
    if blocked:
        out["blocked_reason"] = blocked
    out["grading"] = {"auto": True}
    return (header or _GRADER_HEADER.format(pid=pid)) + yaml.safe_dump(out, sort_keys=False, width=100,
                                                                       allow_unicode=True)


_GRADER_HEADER = ("# AUTHORED by scripts/research/queue_grade.py: the one confirmation of {pid}'s PASS\n"
                  "# (RESEARCH-CONFIRM-FRESH-WINDOW). Self-lands only while `queue_grade.py --verify` reproduces it.\n")


def _holdout_rerun_unit(unit: Dict[str, Any], g: Dict[str, Any], child_id: str, run: Dict[str, Any],
                        header: Optional[str]) -> str:
    """The confirmation of a PASS that did NOT hold out, on a workflow that can: the SAME run
    re-dispatched NOW with the pre-registered holdout (`_HOLDOUT_INPUTS`). Discovery is re-done on
    the earlier span, ONLY the cells it selects are graded once on the held-back latest span, and
    the result rows carry `measurement.holdout.confirmation`. No wait, no not_before."""
    yaml = _yaml()
    pid = str(unit.get("id"))
    wf = str(run.get("workflow") or "")
    inputs = {**(run.get("inputs") or {}), **_HOLDOUT_INPUTS[wf]}
    if isinstance(g.get("holdout_frac"), str):
        inputs["holdout_frac"] = g["holdout_frac"]
    run = {**run, "inputs": inputs}
    n_cells = g.get("cells_swept")
    cells = list(g.get("passing_cells") or [])
    out: Dict[str, Any] = {"id": child_id,
                           "title": f"Holdout re-run of {pid}: {unit.get('title')}",
                           "status": "queued", "cadence": "once"}
    skip = {"id", "title", "status", "cadence", "generated", "grading", "last_dispatched_at",
            "requires_result", "not_before", "confirmation", "run", "dispatch_precondition"}
    for k, v in unit.items():
        if k not in skip:
            out[k] = _swap_id(v, pid, child_id) if k == "lands" else v
    out["roadmap"] = confirmation_roadmap(unit)
    out["question"] = (f"HOLDOUT RE-RUN of {pid}'s single-window PASS: with the latest ~"
                       f"{inputs['holdout_frac']} of each leg's history held back BEFORE selection, does a "
                       "cell still clear the SAME registered gate on the earlier span, and does it hold on the "
                       f"held-back span? Original question: {unit.get('question')}")
    out["run"] = run
    out["requires_result"] = {"unit": pid, "verdict": "pass"}
    out["confirmation"] = {
        "of": pid, "mode": "holdout_rerun", "policy": _HOLDOUT_POLICY,
        "holdout_frac": inputs["holdout_frac"],
        "selected_from_cells": n_cells if isinstance(n_cells, int) else None,
        "passing_cells": cells,
        "note": (f"{pid} PASSED on one full-history window, selected from "
                 f"{n_cells if isinstance(n_cells, int) else 'an unrecorded number of'} cell(s); passing "
                 f"{cells[:6] or 'not named'}. This re-run CONFIRMS only when a cell selected on the earlier "
                 "span passes on the held-back span (measurement.holdout.confirmation == confirmed); "
                 "not_replicated closes the configuration, never the family. Until then "
                 f"{pid} may not feed a Tier-3 proposal." + (f" {g['holdout_note']}" if g.get("holdout_note") else "")),
    }
    out["grading"] = {"auto": True}
    return (header or _GRADER_HEADER.format(pid=pid)) + yaml.safe_dump(out, sort_keys=False, width=100,
                                                                       allow_unicode=True)


def decide(unit: Dict[str, Any], g: Dict[str, Any], graded_at: str,
           attested: bool = False) -> Optional[Dict[str, Any]]:
    """The disposition for one unit, or None when nothing is to be written.
    Returns {"status": new|None, "reset_stamp": bool, "grading": block, "spawn": child id|None}.
    `attested`: a hand-written `once` unit whose rows all carry its own rule id
    (see the module docstring) -- a FAIL closes it instead of re-queueing."""
    d = _decide(unit, g, graded_at, attested)
    if d is None:
        return None
    d.setdefault("spawn", None)
    gb = d["grading"]
    prior = unit.get("grading") if isinstance(unit.get("grading"), dict) else {}
    parent = confirmation_of(unit)
    held = g.get("holdout") if isinstance(g.get("holdout"), dict) else None
    hconf = held.get("confirmation") if held else None
    if hconf and gb.get("verdict") in ("pass", "no_action_warranted"):
        # PRE-REGISTERED HOLDOUT in THIS run (operator 2026-10-16): discovery and confirmation came
        # from one run, so no further unit is opened. `no_discovery` on a re-run means the PASS was
        # not re-found on the earlier span -- not replicated. `error` is for a session.
        conf = {"confirmed": "confirmed", "underpowered": "underpowered", "not_replicated": "not_replicated",
                "no_discovery": "not_replicated"}.get(str(hconf))
        hold = {k: held.get(k) for k in ("boundary", "share_used", "state", "base_trades", "selected_from",
                                         "confirmation", "confirmed_cells")}
        if conf is None:
            d.update(status=None, reset_stamp=False)
            gb.update({"verdict": None, "needs_review": True, "holdout": hold,
                       "note": f"holdout confirmation {hconf!r} is not a grade -- a session reads the run"})
            return d
        if parent:
            gb.update({"confirms": parent, "confirmation": conf, "holdout": hold,
                       "note": (f"holdout re-run of {parent}: {conf} (selected from {held.get('selected_from')} "
                                f"cell(s), holdout from {held.get('boundary')}, base n {held.get('base_trades')})."
                                + (" A FAIL closes the configuration, never the family." if conf == "not_replicated" else ""))})
            return d
        if template_cell(unit) and gb.get("verdict") == "pass":
            gb.update({"discovery": conf, "confirmation": conf, "holdout": hold,
                       "selected_from_cells": held.get("selected_from"),
                       "note": (f"discovery on the span before {held.get('boundary')}, confirmation on the held-back "
                                f"span in the SAME run: {conf}. Only `confirmed` may feed a Tier-3 proposal.")})
            if prior.get("confirm_unit"):
                gb["confirm_unit"] = prior["confirm_unit"]
            return d
    if prior.get("confirm_unit"):
        # exactly ONE confirmation per discovery: a recurring cell's later PASS reuses it
        gb["confirm_unit"] = prior["confirm_unit"]
        gb.setdefault("discovery", prior.get("discovery") or "unconfirmed")
    elif template_cell(unit) and gb.get("verdict") == "pass":
        child = confirm_unit_id(str(unit.get("id")), graded_at)
        n = g.get("cells_swept")
        gb.update({"discovery": "unconfirmed", "confirm_unit": child,
                   "selected_from_cells": n if isinstance(n, int) else None,
                   "note": (f"single-window PASS selected from {n if isinstance(n, int) else 'an unrecorded number of'} "
                            f"cell(s): a discovery, not a confirmation. {child} re-asks on a disjoint window; "
                            "no Tier-3 proposal from this unit until it CONFIRMS")})
        d["spawn"] = child
    if parent and gb.get("verdict") == "pass":
        want = set((unit.get("confirmation") or {}).get("passing_cells") or [])
        got = set(g.get("passing_cells") or [])
        if want and got and not (want & got):
            d.update(status=None, reset_stamp=False)
            gb.update({"verdict": None, "needs_review": True,
                       "note": f"passed on {sorted(got)[:6]}, none of {parent}'s passing cells {sorted(want)[:6]}: "
                               "a NEW discovery on fresh data, not a confirmation -- a session reads it"})
        else:
            gb.update({"confirms": parent, "confirmation": "confirmed",
                       "note": f"fresh-window PASS under the same rule: {parent}'s discovery is CONFIRMED"})
    elif parent and gb.get("verdict") == "fail":
        gb.update({"confirms": parent, "confirmation": "not_replicated"})
    if gb.get("needs_review"):
        # RESEARCH-GRADING-BACKLOG-1016: a session's triage of a needs_review unit is its
        # `grading.owner` (+ `owner_reason`), which result_disposition_check counts as owned. Until
        # this, every 6-hourly pass rebuilt the block from `base` and erased the owner, so a
        # generated recurring unit fell back to needs_review_unowned within hours of its triage.
        # Kept only while the unit still needs review; a mechanical verdict supersedes it.
        for k in ("owner", "owner_reason"):
            if str(prior.get(k) or "").strip():
                gb[k] = prior[k]
    return d


def _decide(unit: Dict[str, Any], g: Dict[str, Any], graded_at: str,
            attested: bool = False) -> Optional[Dict[str, Any]]:
    cadence = str(unit.get("cadence") or "once")
    prior = unit.get("grading") if isinstance(unit.get("grading"), dict) else {}
    base = {"auto": True, "graded_at": graded_at, "grader": "scripts/research/queue_grade.py",
            "decision_rule_id": str((unit.get("decision_rule") or {}).get("id") or ""),
            "rows": g.get("rows"), "evidence": g.get("files"), "reason": g.get("reason")}
    if attested:
        base["attested"] = base["decision_rule_id"]
    v = g.get("verdict")
    if (v == "fail" and cadence not in _RECURRING and not confirm_fail(unit)
            and (isinstance(unit.get("generated"), dict) or confirmation_of(unit))
            and int(prior.get("confirmatory_run") or 0) < 1):
        # RESEARCH-CONFIRM-FRESH-WINDOW (b): a deterministic harness re-run over the same window
        # reproduces the same number, so the template's same-window replay only spent a slot
        # (MEASURED on main 2026-10-16: 0 of 176 generated units ever took it). A FAIL closes the
        # cell; it never retires the family -- the family-retirement protocol (#18557) owns that.
        return {"status": "done", "reset_stamp": False,
                "grading": {**base, "verdict": "fail",
                            "note": "deterministic harness: FAIL closes this cell with no same-window replay; "
                                    "it does not retire the family (family-retirement protocol, #18557)"}}
    if attested and v == "fail" and cadence not in _RECURRING and not confirm_fail(unit):
        return {"status": "done", "reset_stamp": False,
                "grading": {**base, "verdict": "fail",
                            "note": "hand-written unit, every row graded under its own registered rule: "
                                    "FAIL closes it (no template confirmatory re-run)"}}
    if v is None:
        if g.get("rows", 0) == 0 and not g.get("reason", "").startswith("read_state"):
            return None    # nothing landed yet -- not due, not a finding
        return {"status": None, "reset_stamp": False,
                "grading": {**base, "verdict": None, "needs_review": True}}
    if cadence in _RECURRING:
        n_oos = g.get("base_oos_trades")
        if v == "indeterminate" and isinstance(n_oos, int) and n_oos * INFEASIBLE_FRACTION < E35_FLOOR:
            # Infeasible at this cadence: a mechanical outcome, not a human read -- so no needs_review.
            return {"status": None, "reset_stamp": False,
                    "grading": {**base, "verdict": v, "latest": True, "power": "infeasible_at_cadence",
                                "recheck_after_days": RECHECK_DAYS,
                                "note": f"base_oos_trades {n_oos} < floor {E35_FLOOR}/{INFEASIBLE_FRACTION}: the "
                                        f"{cadence} re-ask cannot reach the floor; re-checked every {RECHECK_DAYS} "
                                        "days instead (not retired)"}}
        return {"status": None, "reset_stamp": False,
                "grading": {**base, "verdict": v, "latest": True, "needs_review": v == "indeterminate"}}
    if int(prior.get("confirmatory_run") or 0) >= 1 and v != "fail":
        # The confirmatory run did not repeat the FAIL: {fail, v} is not
        # unanimous, so a session reads both runs (review fix 2026-09-29).
        return {"status": None, "reset_stamp": False,
                "grading": {**base, "verdict": None, "needs_review": True, "confirmatory_run": 1,
                            "first_fail": prior.get("first_fail") or prior.get("reason"),
                            "note": f"confirmatory run read {v!r} after a first FAIL: {{fail, {v}}} is not "
                                    "unanimous -> needs_review, not closed"}}
    if v in ("pass", "no_action_warranted"):
        return {"status": "done", "reset_stamp": False, "grading": {**base, "verdict": v}}
    if v == "indeterminate" and not prior.get("confirmatory_run"):
        # ⚠️ `indeterminate` (UNDERPOWERED / NULL) is a branch the unit's own rule registered
        # BEFORE the run, and a `once` unit never runs again -- so leaving it `queued` closed
        # nothing and parked it in needs_review forever (MEASURED 2026-10-04: 33 prop-fit
        # units, n=57 < the 88 floor, stayed queued for 6 days). The unit is COMPLETE; what
        # it is NOT is a pass or a kill, which `verdict: indeterminate` + `awaiting` says in
        # the record itself. Getting the missing data is the follow-up, not this unit's job.
        return {"status": "done", "reset_stamp": False,
                "grading": {**base, "verdict": "indeterminate", "awaiting": "more_data",
                            "note": "indeterminate is the pre-registered under-powered/null outcome: "
                                    "complete, but NOT a pass and NOT a kill"}}
    if v == "fail":
        if int(prior.get("confirmatory_run") or 0) >= 1:
            return {"status": "done", "reset_stamp": False,
                    "grading": {**base, "verdict": "fail", "confirmatory_run": 1,
                                "first_fail": prior.get("first_fail") or prior.get("reason"),
                                "note": "two consecutive FAIL passes; closed as fail (never on one pass)"}}
        return {"status": None, "reset_stamp": True,
                "grading": {**base, "verdict": "fail", "confirmatory_run": 1, "first_fail": g.get("reason"),
                            "note": "first FAIL: re-queued for a confirmatory run (last_dispatched_at reset), not killed"}}
    return {"status": None, "reset_stamp": False,
            "grading": {**base, "verdict": v, "needs_review": True}}


# ── text edits ──────────────────────────────────────────────────────────────
def apply_text(text: str, d: Dict[str, Any]) -> str:
    yaml = _yaml()
    lines = text.rstrip("\n").split("\n")
    # drop an existing top-level grading: block
    out: List[str] = []
    skipping = False
    for ln in lines:
        if ln.startswith("grading:"):
            skipping = True
            continue
        if skipping and (ln.startswith((" ", "\t")) or ln.strip() == ""):
            continue
        skipping = False
        out.append(ln)
    for i, ln in enumerate(out):
        if d["status"] and re.match(r"^status:\s", ln):
            out[i] = f"status: {d['status']}"
        if d["reset_stamp"] and ln.startswith("last_dispatched_at:"):
            out[i] = "last_dispatched_at: null"
    block = yaml.safe_dump({"grading": d["grading"]}, sort_keys=True, width=100, allow_unicode=True)
    return "\n".join(out).rstrip("\n") + "\n" + block


def grade_unit(root: Path, unit_id: str, text: str, graded_at: str) -> Optional[str]:
    """New text for the unit file, or None when nothing is to be written."""
    res = grade_unit_full(root, unit_id, text, graded_at)
    return res[0] if res else None


def confirmations_for(root: Path, parent_id: str) -> List[Dict[str, Any]]:
    """Every queue unit that is a confirmation of `parent_id`: [{id, mode, status}], holdout first.
    A pure read of the tree (E58 --verify re-derives it at HEAD)."""
    yaml = _yaml()
    out = []
    for path in sorted((root / QUEUE).glob("*.yaml")):
        t = path.read_text(encoding="utf-8")
        if "confirmation:" not in t or parent_id not in t:
            continue
        try:
            u = yaml.safe_load(t) or {}
        except yaml.YAMLError:
            continue
        if isinstance(u, dict) and confirmation_of(u) == parent_id:
            out.append({"id": str(u.get("id") or path.stem), "mode": confirmation_mode(u),
                        "status": str(u.get("status") or "")})
    return sorted(out, key=lambda x: (x["mode"] != "holdout_rerun", x["id"]))


def _superseded_by(root: Path, unit: Dict[str, Any]) -> Optional[str]:
    """A forward-wait confirmation that has not fired is superseded by a live holdout re-run of the
    same PASS (operator 2026-10-16, "Holdout re-run"): the id of that re-run, else None."""
    pid = confirmation_of(unit)
    if not pid or confirmation_mode(unit) != "forward_wait" or unit.get("status") not in ("queued", "blocked") \
            or unit.get("last_dispatched_at"):
        return None
    live = [c for c in confirmations_for(root, pid)
            if c["mode"] == "holdout_rerun" and c["status"] not in ("retired",) and c["id"] != unit.get("id")]
    return live[0]["id"] if live else None


def grade_unit_full(root: Path, unit_id: str, text: str,
                    graded_at: str) -> Optional[Tuple[str, Optional[Tuple[str, str]]]]:
    """(new unit text, (child id, child text) | None), or None when nothing is to be written. The
    child is the fresh-window confirmation unit a template-cell PASS opens (`confirmation_unit`)."""
    yaml = _yaml()
    unit = yaml.safe_load(text)
    if isinstance(unit, dict) and (sup := _superseded_by(root, unit)):
        new = apply_text(text, {"status": "retired", "reset_stamp": False, "grading": {
            "auto": True, "graded_at": graded_at, "grader": "scripts/research/queue_grade.py",
            "superseded_by": sup, "verdict": None,
            "note": (f"forward-wait confirmation superseded by the holdout re-run {sup} of the same PASS "
                     "(operator 2026-10-16, 'Holdout re-run'); never dispatched")}})
        return (new, None) if new != text else None
    if not isinstance(unit, dict) or unit.get("status") != "queued" or not unit.get("last_dispatched_at"):
        return None
    # ⚠️ ONLY units whose rule is mechanical by construction are graded here:
    # template-generated ones (`generated:`) or hand-written ones that opt in
    # with `grading: {auto: true}`. A hand-written fan-out unit (RQ-20260928-005
    # wants 3 legs over 3 dispatches with lands.min_rows 1 per run) would be
    # misread from its first row, and a session's multi-run design is not
    # this grader's to second-guess -- it stays in the session's queue.
    auto = isinstance(unit.get("generated"), dict) or \
        (isinstance(unit.get("grading"), dict) and unit["grading"].get("auto") is True)
    if isinstance(unit.get("generated"), dict) and session_owned(unit):
        # A generated unit is auto-graded, but a session's hand grade (`auto: false` / a verdict
        # block without `auto: true`) is a human read the 6-hourly pass must not erase: run
        # 39062231812 reverted #18783's gradings on RQ-20261016-027/-028 to needs_review/unowned.
        return None
    attested = False
    if not auto:
        if session_owned(unit):
            return None    # opted out, or a session already dispositioned it -- never overwrite a human read
        attested = rule_attested(root, unit_id, unit)
        if not attested:
            return None
    elif not isinstance(unit.get("generated"), dict) and (unit.get("grading") or {}).get("attested"):
        # An attested pass writes `grading: {auto: true, attested: ...}`, so the NEXT pass arrives
        # here as `auto`. Re-check the rows rather than drop the stamp: without this, pass 2 erased
        # `attested` and a later FAIL fell back to the template's confirmatory re-run (seen on
        # run 38742167761: RQ-20260927-003 / RQ-20261007-009 lost the stamp).
        attested = rule_attested(root, unit_id, unit)
    prior = unit.get("grading") if isinstance(unit.get("grading"), dict) else {}
    confirmatory = int(prior.get("confirmatory_run") or 0) >= 1
    # A recurring unit reads only its latest cadence window. A confirmatory
    # pass (re-queued after a first FAIL) reads only rows landed since the
    # re-dispatch -- re-reading run 1's own rows would "confirm" the FAIL with
    # itself (review fix 2026-09-29).
    since = _parse_ts(unit.get("last_dispatched_at")) if (unit.get("cadence") in _RECURRING or confirmatory) else None
    rule_id = str((unit.get("decision_rule") or {}).get("id") or "")
    lands = unit.get("lands") or {}
    if rule_id.startswith("RULE-TPL-E35-BRACKET-"):
        g = grade_e35(e35_rows(root, unit_id))
    else:
        rows = e5_rows(root, unit_id, since)
        if confirmatory and isinstance(prior.get("evidence"), list):
            # The first pass's evidence files were READ by it: a confirmatory pass that
            # re-reads them "confirms" the FAIL with itself. `since` alone did not stop
            # that when the stamp was repaired to run 1's own generated_at (ts == since
            # is not < since) -- RQ-20261015-4941-01/-02, 2026-10-16.
            read = {str(e) for e in prior["evidence"]}
            rows = [(f, r) for f, r in rows if f not in read]
        g = grade_e5(rows, int(lands.get("min_rows") or 1))
    if confirmatory and not g.get("rows"):
        return None    # the confirmatory run has not landed anything yet -- not due
    runs = _declared_runs(lands)
    if runs > 1 and not confirmatory and unit.get("cadence") not in _RECURRING and len(g.get("files") or []) < runs:
        return None    # a declared multi-dispatch unit: not every run has landed yet -- not due
    d = decide(unit, g, graded_at, attested=attested)
    if d is None:
        return None
    child: Optional[Tuple[str, str]] = None
    pid = str(unit.get("id"))
    if d.get("spawn"):
        reuse = [c for c in confirmations_for(root, pid) if c["id"] != d["spawn"] and c["status"] != "retired"]
        if reuse:
            # A confirmation for this PASS already exists (a session-authored holdout re-run, or one an
            # earlier grade opened): exactly ONE per discovery, so point at it and open nothing.
            n = d["grading"].get("selected_from_cells")
            d["grading"]["confirm_unit"] = reuse[0]["id"]
            d["grading"]["note"] = (f"single-window PASS selected from {n if isinstance(n, int) else 'an unrecorded number of'} "
                                    f"cell(s): a discovery, not a confirmation. Its confirmation is already open: "
                                    f"{reuse[0]['id']} ({reuse[0]['mode']}); no Tier-3 proposal from this unit until it CONFIRMS")
            d["spawn"] = None
    elif d["grading"].get("confirm_unit") and not d["grading"].get("holdout"):
        live = [c for c in confirmations_for(root, pid) if c["mode"] == "holdout_rerun" and c["status"] != "retired"]
        if live and live[0]["id"] != d["grading"]["confirm_unit"]:
            d["grading"]["confirm_unit"] = live[0]["id"]   # a forward-wait one was superseded
    if d.get("spawn") and confirmation_roadmap(unit) is None:
        # Never author a unit roadmap-map-guard refuses: a session names the milestone.
        d["grading"].pop("confirm_unit", None)
        d["grading"].update({"needs_review": True,
                             "note": "PASS is a discovery, but no roadmap milestone is known for its confirmation "
                                     "unit (the unit carries none and its family is not in "
                                     "queue_replenish.FAMILY_ROADMAP) -- a session authors it"})
        d["spawn"] = None
    if d.get("spawn"):
        cid = d["spawn"]
        taken = root / QUEUE / f"{cid}.yaml"
        other = None
        if taken.is_file():
            try:
                other = confirmation_of(yaml.safe_load(taken.read_text(encoding="utf-8")) or {})
            except yaml.YAMLError:
                other = "(unreadable)"
        if taken.is_file() and other != unit.get("id"):
            # 1-in-65,536 hash collision with an unrelated unit: never overwrite it -- a session decides
            d["grading"].pop("confirm_unit", None)
            d["grading"].update({"needs_review": True,
                                 "note": f"PASS is a discovery, but confirmation id {cid} is taken by another unit"})
        else:
            child = (cid, confirmation_unit(unit, g, cid))
    new = apply_text(text, d)
    if new == text:
        return None
    # the edit must still parse and must have changed only what it claims
    back = yaml.safe_load(new)
    assert isinstance(back, dict) and back.get("id") == unit.get("id")
    if child:
        cu = yaml.safe_load(child[1])
        assert isinstance(cu, dict) and cu.get("id") == child[0] and confirmation_of(cu) == unit.get("id")
    return new, child


def run(root: Path, *, graded_at: str, write: bool) -> Dict[str, Any]:
    changed = []
    spawned = []
    for path in sorted((root / QUEUE).glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        res = grade_unit_full(root, path.stem, text, graded_at)
        if res is None:
            continue
        new, child = res
        g = _yaml().safe_load(new).get("grading") or {}
        changed.append({"id": path.stem, "verdict": g.get("verdict"), "status": _yaml().safe_load(new).get("status"),
                        "needs_review": bool(g.get("needs_review")), "reason": g.get("reason")})
        if child:
            spawned.append({"id": child[0], "confirms": path.stem,
                            "status": _yaml().safe_load(child[1]).get("status")})
        if write:
            path.write_text(new, encoding="utf-8")
            if child:
                (root / QUEUE / f"{child[0]}.yaml").write_text(child[1], encoding="utf-8")
    return {"graded_at": graded_at, "changed": changed, "spawned": spawned, "written": write}


# ── verify ──────────────────────────────────────────────────────────────────
def _git(root: Path, *args: str) -> Tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    return p.returncode, p.stdout


def verify(root: Path, base: str) -> List[str]:
    rc, mb = _git(root, "merge-base", base, "HEAD")
    mb = mb.strip()
    if rc != 0 or not mb:
        return [f"merge-base with {base} unreadable"]
    rc, out = _git(root, "diff", "--name-status", "--no-renames", mb, "HEAD", "--", QUEUE.as_posix())
    if rc != 0:
        return ["queue diff unreadable"]
    problems = []
    lines = [ln.partition("\t") for ln in out.strip().splitlines()]
    added = {path for status, _, path in lines if status == "A"}
    expected_children: Dict[str, str] = {}
    for status, _, path in lines:
        if status == "A":
            continue    # only a confirmation unit a graded parent opens, checked below
        if status != "M":
            problems.append(f"{path}: {status} -- the grader only MODIFIES existing units "
                            "(and ADDS the one confirmation unit a graded PASS opens)")
            continue
        rc, base_text = _git(root, "show", f"{mb}:{path}")
        if rc != 0:
            problems.append(f"{path}: base version unreadable")
            continue
        head_text = (root / path).read_text(encoding="utf-8")
        g = (_yaml().safe_load(head_text) or {}).get("grading") or {}
        graded_at = str(g.get("graded_at") or "")
        res = grade_unit_full(root, Path(path).stem, base_text, graded_at)
        if (res[0] if res else None) != head_text:
            problems.append(f"{path}: does not reproduce from the merge-base unit + HEAD results at graded_at {graded_at!r}")
            continue
        if res and res[1]:
            expected_children[f"{QUEUE.as_posix()}/{res[1][0]}.yaml"] = res[1][1]
    for path in sorted(added):
        want = expected_children.get(path)
        if want is None:
            problems.append(f"{path}: A -- not the confirmation unit of any unit this diff grades")
        elif (root / path).read_text(encoding="utf-8") != want:
            problems.append(f"{path}: does not reproduce as its parent's confirmation unit (hand-edited?)")
    for path in sorted(set(expected_children) - added):
        problems.append(f"{path}: the grade opens this confirmation unit but the diff does not add it")
    return problems


def health(root: Path, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Runnable count (= what the dispatcher would fire within the next cycle,
    see `queue_replenish.runnable`), the looser `queued` count beside it, and
    hours since the last dispatch -- the alarm's inputs."""
    from scripts.research.queue_replenish import dispatchable, existing_units, runnable
    units, bad = existing_units(root)
    now = now or datetime.now(timezone.utc)
    queued = sorted(uid for uid, u in units.items() if dispatchable(u))
    stamps = [t for u in units.values() if (t := _parse_ts(u.get("last_dispatched_at")))]
    last = max(stamps) if stamps else None
    review = sorted(uid for uid, u in units.items() if isinstance(u.get("grading"), dict) and u["grading"].get("needs_review"))
    return {"runnable": len(runnable(units, now=now)), "queued": len(queued), "units": len(units), "unreadable": bad,
            "last_dispatched_at": last.isoformat() if last else None,
            "hours_since_last_dispatch": round((now - last).total_seconds() / 3600, 1) if last else None,
            "needs_review": review}


# ── self-test ───────────────────────────────────────────────────────────────
def _self_test() -> int:
    import tempfile
    row = lambda v, rs="measured": ("research/results/U/1.jsonl", {"verdict": v, "read_state": rs})  # noqa: E731
    assert grade_e5([row("pass"), row("pass")], 2)["verdict"] == "pass"
    assert grade_e5([row("pass")], 2)["verdict"] is None
    assert grade_e5([row("pass"), row("fail")], 1)["verdict"] is None
    assert grade_e5([row("not_applicable", "producer_failed")], 1)["verdict"] is None
    assert grade_e5([row("fail")], 1)["verdict"] == "fail"
    # a producer_failed row is superseded by a later measured one; alone it still is not a result
    g = grade_e5([row("not_applicable", "producer_failed"), row("pass")], 1)
    assert g["verdict"] == "pass" and "superseded" in g["reason"], g
    assert grade_e5([row("not_applicable", "producer_failed"), row("not_applicable", "producer_failed")], 1)["verdict"] is None
    assert grade_e5([row("indeterminate")], 1)["verdict"] == "indeterminate"
    assert grade_e5([row("indeterminate"), row("pass")], 1)["verdict"] is None   # measured but not unanimous
    assert grade_e35([{"gate_verdict": "is_oos_pass", "base_oos_trades": 49, "leg": "l", "cell": "c"}])["verdict"] == "pass"
    assert grade_e35([{"gate_verdict": "is_oos_fail", "base_oos_trades": 49}])["verdict"] == "no_action_warranted"
    assert grade_e35([{"gate_verdict": "is_oos_pass", "base_oos_trades": 10}])["verdict"] == "indeterminate"
    assert grade_e35([])["verdict"] is None
    u = {"cadence": "once", "decision_rule": {"id": "R"}, "generated": {"key": "k"}}
    assert decide(u, {"verdict": "pass", "rows": 1, "files": [], "reason": "r"}, "2030-01-01")["status"] == "done"
    # RESEARCH-CONFIRM-FRESH-WINDOW (b): a deterministic cell's first FAIL closes (planted) ...
    d = decide(u, {"verdict": "fail", "rows": 1, "files": [], "reason": "r"}, "2030-01-01")
    assert d["status"] == "done" and not d["reset_stamp"] and "confirmatory_run" not in d["grading"], d
    # ... a non-deterministic one (declared seeds) keeps the one confirmatory replay (clean)
    un = {**u, "n_seeds": 5}
    d = decide(un, {"verdict": "fail", "rows": 1, "files": [], "reason": "r"}, "2030-01-01")
    assert d["status"] is None and d["reset_stamp"] and d["grading"]["confirmatory_run"] == 1
    d2 = decide({**un, "grading": {"confirmatory_run": 1}}, {"verdict": "fail", "rows": 1, "files": [], "reason": "r"}, "2030-01-01")
    assert d2["status"] == "done" and d2["grading"]["verdict"] == "fail"
    di = decide(u, {"verdict": "indeterminate", "rows": 1, "files": [], "reason": "r"}, "2030-01-01")
    assert di["status"] == "done" and di["grading"]["awaiting"] == "more_data" and not di["grading"].get("needs_review"), di
    dr = decide({**u, "cadence": "monthly"}, {"verdict": "indeterminate", "rows": 1, "files": [], "reason": "r"}, "2030-01-01")
    assert dr["status"] is None and dr["grading"]["needs_review"], dr   # a recurring unit is never closed
    d3 = decide({**u, "grading": {"confirmatory_run": 1}}, {"verdict": "pass", "rows": 1, "files": [], "reason": "r"}, "2030-01-01")
    assert d3["status"] is None and d3["grading"]["needs_review"] and "not unanimous" in d3["grading"]["note"], d3
    assert decide({**u, "cadence": "monthly"}, {"verdict": "fail", "rows": 1, "files": [], "reason": "r"}, "2030-01-01")["status"] is None
    # RC5: an infeasible recurring e35 read stretches the re-ask, no needs_review; a near-floor one does not
    di5 = decide({**u, "cadence": "monthly"}, {"verdict": "indeterminate", "rows": 1, "files": [], "reason": "r", "base_oos_trades": 5}, "2030-01-01")
    assert di5["grading"]["recheck_after_days"] == RECHECK_DAYS and not di5["grading"].get("needs_review") and di5["status"] is None, di5
    di29 = decide({**u, "cadence": "monthly"}, {"verdict": "indeterminate", "rows": 1, "files": [], "reason": "r", "base_oos_trades": 29}, "2030-01-01")
    assert di29["grading"]["needs_review"] and "recheck_after_days" not in di29["grading"], di29
    assert decide(u, {"verdict": None, "rows": 0, "files": [], "reason": "0 result row(s)"}, "2030-01-01") is None
    assert decide(u, {"verdict": None, "rows": 2, "files": [], "reason": "verdicts not unanimous"}, "2030-01-01")["grading"]["needs_review"]
    # a session's owner survives a re-grade that still needs review, and drops once a verdict lands
    uo = {**u, "cadence": "weekly", "grading": {"auto": True, "needs_review": True, "owner": "ROW-X", "owner_reason": "why"}}
    do = decide(uo, {"verdict": None, "rows": 1, "files": [], "reason": "verdicts not unanimous-mechanical"}, "2030-01-01")
    assert do["grading"]["owner"] == "ROW-X" and do["grading"]["owner_reason"] == "why", do
    dp = decide(uo, {"verdict": "pass", "rows": 1, "files": [], "reason": "r"}, "2030-01-01")
    assert "owner" not in dp["grading"], dp

    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / QUEUE).mkdir(parents=True)
        (r / RESULTS / "RQ-20300101-001").mkdir(parents=True)
        unit_text = ("id: RQ-20300101-001\ntitle: t   # keep me\nstatus: queued\ncadence: once\ngrading:\n  auto: true\n"
                     "decision_rule:\n  id: RULE-X\nlands:\n  store: research/results/\n  min_rows: 2\n"
                     "last_dispatched_at: '2030-01-01T00:00:00+00:00'\n")
        (r / QUEUE / "RQ-20300101-001.yaml").write_text(unit_text)
        assert grade_unit(r, "RQ-20300101-001", unit_text, "2030-01-02") is None          # nothing landed
        (r / RESULTS / "RQ-20300101-001" / "1.jsonl").write_text(
            json.dumps({"verdict": "pass", "read_state": "measured"}) + "\n" + json.dumps({"verdict": "pass", "read_state": "measured"}) + "\n")
        new = grade_unit(r, "RQ-20300101-001", unit_text, "2030-01-02")
        assert new and "status: done" in new and "# keep me" in new and "grading:" in new, new
        assert grade_unit(r, "RQ-20300101-001", new, "2030-01-02") is None   # done units are left alone
        # a first FAIL re-queues; the second closes
        (r / RESULTS / "RQ-20300101-001" / "1.jsonl").write_text(json.dumps({"verdict": "fail", "read_state": "measured"}) + "\n" +
                                                                json.dumps({"verdict": "fail", "read_state": "measured"}) + "\n")
        t1 = grade_unit(r, "RQ-20300101-001", unit_text, "2030-01-02")
        assert "last_dispatched_at: null" in t1 and "confirmatory_run: 1" in t1 and "status: queued" in t1, t1
        t1b = t1.replace("last_dispatched_at: null", "last_dispatched_at: '2030-01-03T00:00:00+00:00'")
        # PLANTED DEFECT (review 2026-09-29): the confirmatory pass must NOT re-read
        # run 1's rows and call them a second FAIL -- undated / older rows are not
        # the confirmatory run's, so with nothing new the unit is simply not due.
        assert grade_unit(r, "RQ-20300101-001", t1b, "2030-01-04") is None
        old1 = json.dumps({"verdict": "fail", "read_state": "measured", "generated_at": "2030-01-01T12:00:00Z"})
        (r / RESULTS / "RQ-20300101-001" / "1.jsonl").write_text(old1 + "\n" + old1 + "\n")
        assert grade_unit(r, "RQ-20300101-001", t1b, "2030-01-04") is None
        # a dated FAIL from the confirmatory run closes it; a dated PASS -> needs_review
        new2 = json.dumps({"verdict": "fail", "read_state": "measured", "generated_at": "2030-01-03T12:00:00Z"})
        (r / RESULTS / "RQ-20300101-001" / "2.jsonl").write_text(new2 + "\n" + new2 + "\n")
        t2 = grade_unit(r, "RQ-20300101-001", t1b, "2030-01-04")
        assert "status: done" in t2 and "verdict: fail" in t2 and "two consecutive" in t2, t2
        pass2 = json.dumps({"verdict": "pass", "read_state": "measured", "generated_at": "2030-01-03T12:00:00Z"})
        (r / RESULTS / "RQ-20300101-001" / "2.jsonl").write_text(pass2 + "\n" + pass2 + "\n")
        t2p = grade_unit(r, "RQ-20300101-001", t1b, "2030-01-04")
        assert "needs_review: true" in t2p and "status: queued" in t2p and "not unanimous" in t2p, t2p
        (r / RESULTS / "RQ-20300101-001" / "2.jsonl").unlink()
        # grading block replaces, never stacks
        assert t2.count("grading:") == 1
        # mixed -> needs_review, status untouched
        (r / RESULTS / "RQ-20300101-001" / "1.jsonl").write_text(json.dumps({"verdict": "pass", "read_state": "measured"}) + "\n" +
                                                                json.dumps({"verdict": "fail", "read_state": "measured"}) + "\n")
        t3 = grade_unit(r, "RQ-20300101-001", unit_text, "2030-01-02")
        assert "needs_review: true" in t3 and "status: queued" in t3
        assert health(r)["needs_review"] == []   # only what is written counts
        # verify(): reproduced passes, hand-edited fails
        subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(r), check=True, capture_output=True)  # noqa: E731
        (r / RESULTS / "RQ-20300101-001" / "1.jsonl").write_text(json.dumps({"verdict": "pass", "read_state": "measured"}) + "\n" +
                                                                json.dumps({"verdict": "pass", "read_state": "measured"}) + "\n")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("checkout", "-q", "-b", "g")
        res = run(r, graded_at="2030-01-02", write=True)
        assert res["changed"] and res["changed"][0]["status"] == "done"
        git("commit", "-q", "-am", "grade")
        assert verify(r, "main") == [], verify(r, "main")
        p = r / QUEUE / "RQ-20300101-001.yaml"
        p.write_text(p.read_text().replace("verdict: pass", "verdict: fail"))
        git("commit", "-q", "-am", "tamper")
        assert any("does not reproduce" in x for x in verify(r, "main"))
    # hand-written units: graded only when every row attests the unit's own rule id
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / QUEUE).mkdir(parents=True)
        d = r / RESULTS / "RQ-20300101-002"
        d.mkdir(parents=True)
        hand = ("id: RQ-20300101-002\nstatus: queued\ncadence: once\ndecision_rule:\n  id: RULE-H\n"
                "lands:\n  min_rows: 1\nlast_dispatched_at: '2030-01-01T00:00:00+00:00'\n")
        own = lambda v, rid="RULE-H": json.dumps({"verdict": v, "read_state": "measured", "decision_rule": {"id": rid}})  # noqa: E731
        (d / "1.jsonl").write_text(own("fail", "RULE-GENERIC") + "\n")
        assert grade_unit(r, "RQ-20300101-002", hand, "2030-01-02") is None      # generic producer rule: not attested
        (d / "1.jsonl").write_text(own("fail") + "\n" + own("fail", "RULE-GENERIC") + "\n")
        assert grade_unit(r, "RQ-20300101-002", hand, "2030-01-02") is None      # one foreign row spoils it
        (d / "1.jsonl").write_text(own("fail") + "\n")
        tf = grade_unit(r, "RQ-20300101-002", hand, "2030-01-02")
        assert "status: done" in tf and "verdict: fail" in tf and "attested: RULE-H" in tf and \
            "last_dispatched_at: '2030" in tf, tf                                 # FAIL closes, no re-queue
        (d / "1.jsonl").write_text(own("pass") + "\n")
        assert "status: done" in grade_unit(r, "RQ-20300101-002", hand, "2030-01-02")
        (d / "1.jsonl").write_text(own("indeterminate") + "\n")
        assert "awaiting: more_data" in grade_unit(r, "RQ-20300101-002", hand, "2030-01-02")
        (d / "1.jsonl").write_text(json.dumps({"verdict": "not_applicable", "read_state": "producer_failed",
                                                "decision_rule": {"id": "RULE-H"}}) + "\n")
        tn = grade_unit(r, "RQ-20300101-002", hand, "2030-01-02")
        assert "needs_review: true" in tn and "attested: RULE-H" in tn, tn
        # pass 2 of that unit (now `grading: {auto: true, attested}`) keeps the stamp, and a FAIL still closes it
        (d / "1.jsonl").write_text(json.dumps({"verdict": "not_applicable", "read_state": "producer_failed",
                                                "decision_rule": {"id": "RULE-H"}}) + "\n" + own("fail") + "\n")
        t2 = grade_unit(r, "RQ-20300101-002", tn, "2030-01-03")
        assert t2 and "attested: RULE-H" in t2 and "status: done" in t2 and "verdict: fail" in t2, t2
        # an ML training run (or declared seeds / confirm_fail) re-runs its first FAIL once instead of closing
        (d / "1.jsonl").write_text(own("fail") + "\n")
        tml = grade_unit(r, "RQ-20300101-002", hand + "ml_bakeoff:\n  family: f\n", "2030-01-02")
        assert tml and "status: queued" in tml and "last_dispatched_at: null" in tml and "confirmatory_run: 1" in tml, tml
        assert "last_dispatched_at: null" in grade_unit(r, "RQ-20300101-002", hand + "n_seeds: 5\n", "2030-01-02")
        weekly = hand.replace("cadence: once", "cadence: weekly")
        (d / "1.jsonl").write_text(own("pass") + "\n")
        assert grade_unit(r, "RQ-20300101-002", weekly, "2030-01-02") is None   # recurring hand units stay a session's
        # RC1 delta (2026-10-15): an attested unit that opted out, or that a session already graded, is never touched
        assert grade_unit(r, "RQ-20300101-002", hand + "grading:\n  auto: false\n", "2030-01-02") is None
        assert grade_unit(r, "RQ-20300101-002", hand + "grading:\n  verdict: fail\n  by: a session\n", "2030-01-02") is None
        # ... also a TEMPLATE-GENERATED unit: a session's hand grade survives the pass (2026-10-17 regression)
        gen = hand + "generated:\n  template: t\n"
        assert grade_unit(r, "RQ-20300101-002", gen + "grading:\n  auto: false\n  verdict: fail\n", "2030-01-02") is None
        assert grade_unit(r, "RQ-20300101-002", gen, "2030-01-02") is not None     # ungraded generated unit still graded
        # ... including a TEMPLATE-generated unit a session opted out (runs 39062231812 reverted two such hand grades)
        gen = hand + "generated:\n  template: t\ngrading:\n  auto: false\n  verdict: fail\n"
        assert grade_unit(r, "RQ-20300101-002", gen, "2030-01-02") is None
        # ... and a declared multi-dispatch unit waits for every run's result FILE (2 rows in 1 file, runs: 2)
        (d / "1.jsonl").write_text(own("pass") + "\n" + own("pass") + "\n")
        multi = hand.replace("  min_rows: 1\n", "  min_rows: 1\n  runs: 2\n")
        assert grade_unit(r, "RQ-20300101-002", multi, "2030-01-02") is None
        (d / "2.jsonl").write_text(own("pass") + "\n")
        assert "status: done" in (grade_unit(r, "RQ-20300101-002", multi, "2030-01-02") or "")
    print("queue_grade self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--date", default=None, help="graded_at (YYYY-MM-DD, default today UTC)")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--health", action="store_true", help="print the queue-health numbers as JSON")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    # `--verify --base` grades a COMMIT RANGE, so the verdict is about the
    # committed tree. Say so when that is not the tree you edited
    # (tests/test_dirty_tree_notice.py; notice only, no exit-code change).
    sys.path.insert(0, str(_REPO / "scripts" / "ci"))
    import _dirty_tree  # noqa: E402,PLC0415 -- path shim above
    _dirty_tree.warn()
    if args.self_test:
        return _self_test()
    if args.health:
        print(json.dumps(health(_REPO), indent=2))
        return 0
    if args.verify:
        problems = verify(_REPO, args.base)
        for p in problems:
            print(f"::error::queue_grade --verify: {p}")
        print("queue_grade --verify: " + ("OK" if not problems else f"FAIL ({len(problems)})"))
        return 1 if problems else 0
    day = args.date or datetime.now(timezone.utc).date().isoformat()
    res = run(_REPO, graded_at=day, write=args.write)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"queue_grade ({'WROTE' if args.write else 'dry run'}, graded_at {day}): {len(res['changed'])} unit(s) changed")
        for c in res["changed"]:
            print(f"  {c['id']}  status={c['status']}  verdict={c['verdict']}  needs_review={c['needs_review']}  {c['reason']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
