#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::spend-meter-guard (--self-test + --check).
# Read by A3a for daily-brief section 5. A1 in docs/claude/work/MANAGER-CHECKLIST.json
# is the spec; its `note` records three corrections already paid for — read them
# before changing the shape of what this reports.
"""A1 — THE SPEND METER: usage against the WEEKLY PLAN ALLOWANCE, plus per-lane dollars.

THE QUESTION THIS MODULE ANSWERS, restated because it is easy to build the
wrong thing that *looks* like a budget meter: **what does §5 print on a day
nobody has read the usage meter?** The answer must be a distinguishable "not
read since <timestamp>" — never `0`, never a carried-forward figure presented
as current. Every design choice below serves that one sentence.

TWO POPULATIONS, NEVER BLENDED (the category error this row already caught
twice on 2026-09-21 — see A1's `note`):

  (a) THE CONTROL VARIABLE — usage against the weekly plan allowance, paced
      at the SUSTAINABLE RATE (100 - weekly%) / days to reset (operator,
      2026-10-18; it replaced the 2026-09-21 "10% a day" share). It is a
      PERCENT, not a dollar figure or a token count — Settings -> Usage exposes three percent-of-allowance bars
      (session ~5h, weekly, and a separate weekly bar for Fable) with no
      absolute number anywhere, and the allowance is model-weighted, so
      tokens-per-percent is not a constant. Converting to tokens would read
      as precise and drift silently; this module refuses to.
  (b) PER-LANE DOLLARS (`cost_usd`) — API-equivalent pricing read off session
      metadata. The right signal for COMPARING lanes to each other; the wrong
      denominator for pacing against the plan. Reported BESIDE the percent
      meters, never folded into them.

THE DENOMINATOR IS NOT MACHINE-READABLE, AND THIS MODULE MUST NOT INVENT IT.
Only a human can open Settings -> Usage and read the three bars. So the
percent side of this meter is a TINY ON-DISK RECORD of OPERATOR-ENTERED
READINGS (`docs/claude/work/USAGE-READINGS.jsonl`), append-only, one line per
reading, same house style as `pipeline.py`: a state change is a new line, not
an edit, so two sessions appending concurrently merge cleanly by construction,
and a malformed line is reported as `unreadable`, never silently dropped (a
corrupted log must never read as an empty, healthy one).

⚠️ A READING IS NEVER "CURRENT" — IT IS DATED. `render_section_5` always
prints a reading's `read_at` timestamp and its age alongside the percent, so a
three-day-old 40% cannot be mistaken for today's number. A window with no
reading EVER prints `never recorded`, explicitly, not a bare `0%` — `0` here
would collapse "we have not looked" into "usage is zero", which is exactly the
class of bug `docs/CLAUDE-RULES-CANONICAL.md` § "Collapsed states" names.

TWO WINDOWS BIND, NOT ONE. The weekly cap is what the sustainable rate is
computed from; the ~5-hour SESSION window is what actually walls a lane
mid-run — a burst can exhaust the session window while the weekly meter
still reads green. `render_section_5` always shows both, never one alone.
FABLE carries its own weekly allowance (row E11 decides what is routed there;
this module only reports the pool — it is not spare capacity by default).

PER-LANE DOLLARS: WHAT IS ACTUALLY REACHABLE, ESTABLISHED RATHER THAN GUESSED
-------------------------------------------------------------------------------
`cost_usd` is real and reachable — from an INTERACTIVE session holding the
Claude Code Remote MCP tools (`get_session` / `list_sessions`). It is **NOT**
reachable from a CI runner or a Routine-fired turn. This is not a fresh
finding: it is already established, independently, in two other places in
this repo (REUSED, NOT RE-DERIVED, per `docs/CLAUDE-RULES-CANONICAL.md` §
"Green is not evidence" / obligation 3) —

  * `scripts/ops/render_daily_brief.py` (its own header): *"mcp__* tools are
    unavailable to CI and to Routine-fired turns"* — which is why that
    generator is deliberately NOT a cron and instead a close-out deliverable
    a manager runs and hands observations to via `--session-notes` /
    `--live-sessions`.
  * `.github/workflows/pr-queue-watch.yml` and `scripts/ops/queue_latency.py`:
    *"an mcp__* tool CI does not hold"*, same conclusion, independently
    arrived at for a different consumer.

And confirmed a third way this session: `get_session` / `list_sessions` ARE
callable here, inside this interactive build lane — MEASURED by calling them
directly against this session's own id and its parent, 2026-09-21. No GitHub
Actions secret or workflow in this repo wires a credential for that API to a
CI runner (checked: `grep -rli` over `.github/workflows/`,
`docs/reference/env-vars.md`, `docs/claude/system-actions.md` — the only
hits are the two files above stating the tool is unreachable there).

So: **per-lane dollars follow the SAME observation pattern `render_daily_brief.py`
already uses for its MCP-only inputs.** This module accepts an OPTIONAL
`--session-costs <path>` (a pasted `get_session`/`list_sessions` result, or
`-` for stdin) from a session that holds the tools; absent, it reports
`not_observed` — explicit and manual, never a fabricated `$0.00`.

Self-test:  python3 scripts/ops/spend_meter.py --self-test
Check:      python3 scripts/ops/spend_meter.py --check
Record:     python3 scripts/ops/spend_meter.py --record --window weekly \\
                --percent 68 --read-at 2026-09-21T14:00:00Z --recorded-by operator
Section 5:  python3 scripts/ops/spend_meter.py --section-5 [--session-costs FILE]
Capacity:   python3 scripts/ops/spend_meter.py --capacity [--reset-at ISO] [--pp-per-lane-hour X]
                [--live-open N]
            (step 2 of the manager's operating loop: sustainable rate -> lane count)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# REUSED, NOT RE-DERIVED: the same tolerant parser render_daily_brief.py
# already uses for a pasted MCP observation (handles the `<other-session …>`
# envelope an MCP tool result arrives wrapped in, and the bare-list fallback).
from scripts.ops.session_registry import _load_observation  # noqa: E402

STORE = Path("docs/claude/work/USAGE-READINGS.jsonl")

#: THE THREE DECLARED METERS. Never a fourth invented ad hoc, and
#: `render_section_5` never renders fewer than these three together — the
#: sustainable rate is computed from `weekly`, `session` is what actually walls a
#: lane mid-run, and `fable_weekly` is Fable's own pool.
WINDOWS = ("session", "weekly", "fable_weekly")

_WINDOW_LABEL = {
    "session": "SESSION (~5h) — what actually walls a lane mid-run",
    "weekly": "WEEKLY (main pool) — what the sustainable rate is computed from",
    "fable_weekly": "FABLE WEEKLY — Fable's own pool (routing: E11)",
}

_ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ".replace("Z", "+00:00"),
    "%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
)


class MeterError(ValueError):
    """A refusal to accept a reading. Carries WHICH field and WHY."""


def _parse_ts(s: Any, field_name: str) -> datetime:
    if not isinstance(s, str) or not s.strip():
        raise MeterError(f"{field_name}: must be a non-empty ISO timestamp string")
    text = s.strip()
    for fmt in _ISO_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise MeterError(
        f"{field_name}: {s!r} is not a timestamp this can parse "
        f"(expected one of {_ISO_FORMATS[:3]}…)"
    )


# ── the on-disk record of operator-entered readings ─────────────────────────

def validate_reading(rec: dict, *, now: datetime | None = None) -> dict:
    """Refuse a reading that cannot be trusted as a dated observation.

    ⚠️ Every check here exists because the alternative renders a fabricated
    or misleading number as if it were measured — see the module docstring.
    """
    if not isinstance(rec, dict):
        raise MeterError(f"reading must be an object, got {type(rec).__name__}")

    for key in ("window", "percent", "read_at", "recorded_by"):
        if key not in rec:
            raise MeterError(f"missing required field {key!r}")

    if rec["window"] not in WINDOWS:
        raise MeterError(f"window: must be one of {WINDOWS}, got {rec['window']!r}")

    pct = rec["percent"]
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise MeterError(f"percent: must be a number, got {type(pct).__name__}")
    if not (0.0 <= float(pct) <= 100.0):
        raise MeterError(f"percent: must be within 0..100, got {pct!r}")

    read_at = _parse_ts(rec["read_at"], "read_at")
    now = now or datetime.now(timezone.utc)
    if read_at > now:
        raise MeterError(
            f"read_at: {rec['read_at']!r} is in the future relative to {now.isoformat()} "
            f"— a reading cannot be dated after it was taken"
        )

    if not isinstance(rec["recorded_by"], str) or not rec["recorded_by"].strip():
        raise MeterError(
            "recorded_by: required and non-empty — only a human can read "
            "Settings > Usage, so a reading with no named source is unverifiable"
        )

    if "note" in rec and rec["note"] is not None and not isinstance(rec["note"], str):
        raise MeterError("note: must be a string when present")

    return rec


@dataclass
class LoadResult:
    """⚠️ Three counts, never collapsed. This is a TIME SERIES, not a keyed
    store — unlike `pipeline.py`, records are never folded to "the last one
    per id"; every reading is preserved so a rate can be measured between
    two of them.
    """

    records: list[dict] = field(default_factory=list)
    unreadable: list[tuple[int, str]] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.unreadable


def read_readings(store: Path = STORE) -> LoadResult:
    res = LoadResult()
    if not store.exists():
        return res
    for lineno, raw in enumerate(store.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        try:
            rec = json.loads(line)
            validate_reading(rec, now=datetime.now(timezone.utc) + timedelta(days=1))
        except Exception as exc:  # noqa: BLE001 — the message is the payload
            res.unreadable.append((lineno, f"{type(exc).__name__}: {exc}"))
            continue
        res.records.append(rec)
    return res


def append_reading(rec: dict, store: Path = STORE) -> dict:
    """Validate, then append one record. Atomic; never rewrites history."""
    validate_reading(rec)
    store.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n"
    with open(store, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return rec


def latest_by_window(records: Iterable[dict]) -> dict[str, dict | None]:
    """The most recent reading PER WINDOW, by `read_at` — not by file order,
    since two windows are recorded independently and can arrive interleaved.
    """
    best: dict[str, dict] = {}
    for rec in records:
        w = rec.get("window")
        if w not in WINDOWS:
            continue
        cur = best.get(w)
        if cur is None or _parse_ts(rec["read_at"], "read_at") > _parse_ts(cur["read_at"], "read_at"):
            best[w] = rec
    return {w: best.get(w) for w in WINDOWS}


def _fmt_age(delta: timedelta) -> str:
    total_min = int(delta.total_seconds() // 60)
    if total_min < 0:
        return "in the future (?!)"
    if total_min < 60:
        return f"{total_min}m"
    hours, minutes = divmod(total_min, 60)
    if hours < 48:
        return f"{hours}h{minutes:02d}m"
    days = hours // 24
    return f"{days}d"


def _readings_for_window(records: list[dict], window: str) -> list[dict]:
    return sorted(
        (r for r in records if r.get("window") == window),
        key=lambda r: _parse_ts(r["read_at"], "read_at"),
    )


def _rate_line(records: list[dict], window: str) -> str | None:
    """A measured, drifting rate between the last TWO readings of one window.

    ⚠️ Never computed from a single point — that would fabricate a slope from
    one dot. Labelled MEASURED-AND-DRIFTING, never as the budget: the task
    this repo's own rules warn against is presenting a derived figure with
    the same confidence as the rule it is being compared to.
    """
    rows = _readings_for_window(records, window)
    if len(rows) < 2:
        return None
    a, b = rows[-2], rows[-1]
    t_a, t_b = _parse_ts(a["read_at"], "read_at"), _parse_ts(b["read_at"], "read_at")
    days = (t_b - t_a).total_seconds() / 86400.0
    if days <= 0:
        return None
    rate = (float(b["percent"]) - float(a["percent"])) / days
    return (
        f"  - measured (between the last two `{window}` readings, "
        f"{days:.2f}d apart): **{rate:+.2f} pct/day** — drifting, sanity-check "
        f"only, never the budget"
    )


# ── capacity: step 2 of the manager's operating loop ─────────────────────────
#
# Operator, 2026-10-18: "We want to get as much work as possible out of our budget without
# blowing through it before a reset." The sustainable rate is what is LEFT of the weekly
# allowance spread over what is LEFT of the week -- (100 - weekly%) / days to reset -- turned
# into a lane count with a MEASURED cost per lane-hour. The count is advice for the manager's
# judgment (1..5, at least one lane always runs); this module never enforces a cap.

#: MEASURED 2026-10-18 (USAGE-READINGS.jsonl): weekly 55% at 05:39Z -> 73% at 08:40Z with
#: 6 lanes running = 18 pp / (3.0 h x 6 lanes) = 1.0 pp per lane-hour. One window, one mix of
#: models; re-measure with --pp-per-lane-hour when a better reading exists.
PP_PER_LANE_HOUR = 1.0
LANES_MIN, LANES_MAX = 1, 5
#: readings older than this (relative to the newest) are outside the calibration window
CALIBRATION_WINDOW_H = 24.0


def calibrate_pp_per_lane_hour(records: Iterable[dict], lane_hours: float | None, *,
                               window_h: float = CALIBRATION_WINDOW_H) -> dict:
    """pp per lane-hour from consecutive weekly readings: (last% - first%) / ``lane_hours``, over the
    readings within ``window_h`` of the newest. ``lane_hours`` is the lane-hours run between the first
    and last of those readings (session create/archive times, or the manager's --lane-hours); the
    basis is returned. < 2 readings, no lane-hours, or a non-increasing pair -> the module constant,
    flagged ``inferred`` (a reset between readings makes the pair non-increasing)."""
    fallback = {"value": PP_PER_LANE_HOUR, "basis": "inferred",
                "why": "constant: no usable calibration"}
    wk = sorted((r for r in records if r.get("window") == "weekly"),
                key=lambda r: _parse_ts(r["read_at"], "read_at"))
    if not wk:
        return {**fallback, "why": "constant: no weekly readings"}
    newest = _parse_ts(wk[-1]["read_at"], "read_at")
    win = [r for r in wk if (newest - _parse_ts(r["read_at"], "read_at")).total_seconds() <= window_h * 3600]
    if len(win) < 2:
        return {**fallback, "why": f"constant: {len(win)} reading(s) in the {window_h:.0f}h window"}
    if not lane_hours or lane_hours <= 0:
        return {**fallback, "why": "constant: --lane-hours not given for the window"}
    dpp = float(win[-1]["percent"]) - float(win[0]["percent"])
    if dpp <= 0:
        return {**fallback, "why": "constant: usage did not rise across the window (reset or no change)"}
    return {"value": round(dpp / lane_hours, 3), "basis": "measured",
            "why": f"{win[0]['percent']:.0f}% -> {win[-1]['percent']:.0f}% over {lane_hours:g} lane-hours "
                   f"({len(win)} readings, {win[0]['read_at']} .. {win[-1]['read_at']})"}
#: A reading older than this is the first thing to fix, not a basis for dispatch.
READING_STALE_H = 12.0
_RESET_IN_NOTE = re.compile(r"reset\s+(?:[A-Za-z]{3}\s+)?(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})Z?")

# ── the live-trade-review reserve (docs/plans/live-trade-review-DESIGN.md § 6.4) ────────────
#
# Operator, 2026-10-25: leave enough spare that the live-trade-review routine can always run,
# even just before the reset. R = F + D*(g + c_typ*n) + min(D,1)*(c_stress - c_typ)*max(n, n_peak).
# Every value is the design's PROPOSED default (INFERRED from 38 days of exposure, § 6.1-6.3),
# kept here as module constants until config/live_trade_review.yaml exists (LTR-1); the
# per-tier session costs behind c_typ / c_stress are replaced by measured records later.
RESERVE_FLOOR_PP = 2.0          # F
RESERVE_GATE_PP_DAY = 0.5       # g
RESERVE_TYPICAL_PP_DAY = 0.75   # c_typ, per open package
RESERVE_STRESS_PP_DAY = 2.5     # c_stress, per open package
RESERVE_N_PEAK = 4              # max concurrent real-money packages, last 38 days
#: worst-case roster bound, used as ``n`` when the open count could not be read
RESERVE_ROSTER_BOUND = 12


def reserve_pp(days_left: float, n: int) -> float:
    """The design's § 6.4 reserve for ``days_left`` days and ``n`` open live/prop packages."""
    stress = (RESERVE_STRESS_PP_DAY - RESERVE_TYPICAL_PP_DAY) * max(n, RESERVE_N_PEAK)
    return (RESERVE_FLOOR_PP
            + days_left * (RESERVE_GATE_PP_DAY + RESERVE_TYPICAL_PP_DAY * n)
            + min(days_left, 1.0) * stress)


# Operator, 2026-10-26: the fixed per-package bound above held the manager at 1 lane for hours
# while weekly usage moved ~0.5 pp/h. The reserve is now MEASURED runs/day x pp per run; the
# § 6.4 bound stays as the CEILING (the measured figure may lower the reserve, never raise it).
#: pp of weekly allowance one live-review run costs. INFERRED: the repo holds no per-run cost
#: record (reviews.jsonl carries none) and no USD->pp factor; the manager's 2026-10-26 reading was
#: $0.25-0.70 per run. Override with --review-pp-per-run when a measured figure exists.
REVIEW_PP_PER_RUN = 0.1
REVIEW_RATE_WINDOW_D = 3.0
REVIEW_LOG = Path(__file__).resolve().parents[2] / "comms" / "live_review" / "reviews.jsonl"


def review_runs_per_day(path: Path, *, now: datetime | None = None,
                        window_d: float = REVIEW_RATE_WINDOW_D) -> float | None:
    """MEASURED live-review runs/day over the last ``window_d`` days (rows in reviews.jsonl).
    ``None`` = the log could not be read -- never 0."""
    now = now or datetime.now(timezone.utc)
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    cut, n = now - timedelta(days=window_d), 0
    for ln in lines:
        try:
            if _parse_ts(json.loads(ln)["reviewed_at"], "reviewed_at") >= cut:
                n += 1
        except (ValueError, KeyError, TypeError):
            continue
    return n / window_d


def measured_reserve_pp(days_left: float, runs_per_day: float,
                        pp_per_run: float = REVIEW_PP_PER_RUN) -> float:
    return RESERVE_FLOOR_PP + days_left * (RESERVE_GATE_PP_DAY + runs_per_day * pp_per_run)


def capacity(log: LoadResult, *, reset_at: str | None = None,
             pp_per_lane_hour: float = PP_PER_LANE_HOUR,
             live_open: int | None = None,
             review_runs_day: float | None = None,
             review_pp_per_run: float = REVIEW_PP_PER_RUN,
             now: datetime | None = None) -> dict:
    """The sustainable rate and the lane count it supports, net of the live-review reserve.
    ``live_open`` is the count of open live/prop packages; ``None`` means it could not be read,
    which sizes the reserve at the roster bound and reads ``exposure_unknown`` -- never 0. ``state`` is one of
    ``ok`` / ``never_recorded`` / ``reset_unknown`` / ``reading_from_past_week``; only
    ``ok`` carries numbers -- a missing input is named, never filled with a guess."""
    now = now or datetime.now(timezone.utc)
    rec = latest_by_window(log.records)["weekly"]
    if rec is None:
        return {"state": "never_recorded", "lanes": None}
    read_at = _parse_ts(rec["read_at"], "read_at")
    out = {"weekly_pct": float(rec["percent"]), "read_at": rec["read_at"],
           "reading_age_h": round((now - read_at).total_seconds() / 3600, 2)}
    m = _RESET_IN_NOTE.search(rec.get("note") or "")
    raw_reset = reset_at or (m.group(1).replace(" ", "T") + ":00Z" if m else None)
    if raw_reset is None:
        return {**out, "state": "reset_unknown", "lanes": None}
    reset = _parse_ts(raw_reset, "reset_at")
    if reset <= read_at:
        return {**out, "state": "reading_from_past_week", "reset_at": raw_reset, "lanes": None}
    days_left = max((reset - now).total_seconds() / 86400, 1 / 24)
    # usage since the reading is unknown; spreading the remainder over the time left from NOW
    # is the conservative reading of a dated observation
    if live_open is not None and live_open < 0:
        raise ValueError("live_open must be >= 0")
    n = RESERVE_ROSTER_BOUND if live_open is None else live_open
    remaining = max(100.0 - out["weekly_pct"], 0.0)
    bound = reserve_pp(days_left, n)
    reserve, reserve_src = bound, "bound"
    if review_runs_day is not None:
        reserve = min(bound, measured_reserve_pp(days_left, review_runs_day, review_pp_per_run))
        reserve_src = "measured"
    rate_gross = remaining / days_left
    rate_day = max(remaining - reserve, 0.0) / days_left
    raw_lanes = rate_day / 24 / pp_per_lane_hour
    return {**out, "state": "ok", "reset_at": raw_reset, "days_to_reset": round(days_left, 2),
            "rate_gross_pp_per_day": round(rate_gross, 2),
            "reserve_pp": round(reserve, 2), "reserve_bound_pp": round(bound, 2),
            "reserve_source": reserve_src, "review_runs_per_day": review_runs_day,
            "reserve_basis": {"n": n, "exposure": "exposure_unknown" if live_open is None else "measured"},
            # § 6.6: breached = the remaining allowance is below the reserve. While it is, the
            # live-review routine counts as the operating loop's always-one-lane (operator Q5).
            "reserve_breached": remaining < reserve,
            "rate_pp_per_day": round(rate_day, 2), "pp_per_lane_hour": pp_per_lane_hour,
            "lanes_raw": round(raw_lanes, 2),
            "lanes": min(max(round(raw_lanes), LANES_MIN), LANES_MAX),
            "stale": out["reading_age_h"] > READING_STALE_H}


def render_capacity(c: dict) -> list[str]:
    if c["state"] != "ok":
        why = {
            "never_recorded": "no weekly reading exists",
            "reset_unknown": "the weekly reading names no reset time (pass --reset-at, or record "
                             "the reading with --note \"reset <Day> YYYY-MM-DD HH:MMZ\")",
            "reading_from_past_week": f"the latest reading ({c.get('read_at')}) predates the reset "
                                      f"it names ({c.get('reset_at')}) -- record this week's reading",
        }[c["state"]]
        return [f"CAPACITY: could not compute -- {why}. Record a reading first; meanwhile run "
                f"ONE lane (the floor), never zero and never a guessed count."]
    L = [f"CAPACITY: weekly {c['weekly_pct']:.0f}% as of {c['read_at']} ({c['reading_age_h']:.1f}h old); "
         f"reset {c['reset_at']} ({c['days_to_reset']:.2f}d)",
         f"  sustainable rate (gross) = (100 - {c['weekly_pct']:.0f}) / {c['days_to_reset']:.2f}d = "
         f"{c['rate_gross_pp_per_day']:.1f} pp/day",
         f"  reserve for live review = {c['reserve_pp']:.1f} pp (n_open={c['reserve_basis']['n']}, "
         f"{c['reserve_basis']['exposure']}; {c['reserve_source']}"
         + (f" = {c['review_runs_per_day']:.1f} runs/day, ceiling {c['reserve_bound_pp']:.1f} pp"
            if c['reserve_source'] == 'measured' else "") + ")",
         f"  net rate = (100 - {c['weekly_pct']:.0f} - {c['reserve_pp']:.1f}) / {c['days_to_reset']:.2f}d = "
         f"{c['rate_pp_per_day']:.1f} pp/day",
         f"  at {c['pp_per_lane_hour']:.2f} pp per lane-hour that is {c['lanes_raw']:.2f} lanes "
         f"continuous -> KEEP {c['lanes']} LANES RUNNING (a target, not a cap; floor {LANES_MIN}, "
         f"judgment up to {LANES_MAX}). Below target with queued rows = dispatch now, don't ask."]
    if c["reserve_breached"]:
        L.append(f"  🚩 RESERVE BREACHED: {100 - c['weekly_pct']:.1f} pp left is below the {c['reserve_pp']:.1f} pp "
                 f"reserve. No new non-routine lanes; the live-review routine counts as the operating "
                 f"loop's always-one-lane (design § 6.6, operator Q5).")
    if c["reserve_basis"]["exposure"] == "exposure_unknown":
        L.append("  ⚠️ exposure_unknown: --live-open not given, so n = roster bound "
                 f"({RESERVE_ROSTER_BOUND}); pass the open live/prop package count to size it")
    if c["stale"]:
        L.append(f"  ⚠️ reading is over {READING_STALE_H:.0f}h old -- ask for a fresh one before adding lanes")
    return L


# ── desk scale lines (DESK-10-CAPACITY, extends the LTR-10/LTR-10B reserve lines) ──────────
#
# ONE QUESTION: what does the Claude trading desk cost per decision, per tier, and what does each scale
# option cost per week? Two currencies, never summed: a SESSION (a desk wake, a session-routed judge
# batch) is billed against the PLAN allowance and `cost_usd` is its API-EQUIVALENT price; the API judge
# path spends REAL dollars on the VM's ANTHROPIC_API_KEY under a hard --max-usd. Every line names its
# population and n and carries a src/runtime/provenance.py grade.

#: MEASURED 2026-10-27 by get_session().usage.cost_usd over EVERY hourly-regime `desk-wake` session in
#: list_sessions' newest 100 (tag desk-wake, created 2026-10-26T18:38Z..2026-10-27T03:04Z; the six earlier
#: desk-wake sessions are the build/measure pilots and are excluded). All ten wrote ONE no_trade row, so
#: this is the cost of a no_trade decision; a propose_entry wake is UNMEASURED (none in the population).
DESK_WAKE_SAMPLES: tuple[tuple[str, str, float], ...] = (
    ("session_01A3Nm88rHBBRadhWCzPmmzF", "2026-10-26T18:38:14Z", 0.48571094),
    ("session_01CfG3nc6pV4kzLy1VmpXcjM", "2026-10-26T19:40:56Z", 0.55051114),
    ("session_012ReVAveTvbgcymYisbqhNR", "2026-10-26T20:04:00Z", 0.53107354),
    ("session_017cExCYzxdGqdvvQ3jC6o4R", "2026-10-26T21:04:02Z", 0.49948988),
    ("session_01YWcyBFZJGTa2KDJcokaew6", "2026-10-26T22:03:34Z", 0.76794138),
    ("session_019aGfTdnp8ji7CY4FT1UP92", "2026-10-26T23:02:33Z", 0.48417404),
    ("session_0157fRbXGuAotkcueJQBqkpZ", "2026-10-27T00:03:30Z", 0.95921458),
    ("session_01WpcgHP7tNGfoF77MG54LWF", "2026-10-27T01:03:55Z", 0.81029744),
    ("session_01AFoLuL9Dzjsqk7WKsYjCzb", "2026-10-27T02:04:16Z", 0.62826684),
    ("session_01AFoLuKwtdPDGBowYWWEt2Z", "2026-10-27T03:04:35Z", 0.46478484),
)
WAKES_PER_WEEK_HOURLY = 24 * 7
WAKES_PER_WEEK_15MIN = 4 * 24 * 7
#: the scan packet is built hourly (desk-scan-packet.yml :03), so a 15-minute wake sees each packet 4x
PACKETS_PER_HOUR = 1

#: DESK-18B pilot, 5 sessions x 10 packets, reported by the manager from get_session usage.cost_usd
#: ($16.84 total). NOT re-read this session -- the pilot sessions were not in the 100-session page.
#: An UPPER BOUND on judging (subagents inside a ~290k-token session context), never a price of it.
SESSION_JUDGE_PILOT_USD, SESSION_JUDGE_PILOT_PACKETS = 16.84, 50
#: median masked packet, 40 packets MEASURED 2026-10-26 (DESK-18B-JUDGE-RUN note); protocol length from
#: scripts/research/desk_judge_api's JUDGE-PROTOCOL.md; output tokens are INFERRED (no API run exists yet)
JUDGE_PACKET_CHARS, JUDGE_PROTOCOL_CHARS = 16912, 2397
JUDGE_OUT_TOK_MEAN, JUDGE_OUT_TOK_CEILING = 75, 400
JUDGE_PACKET_COUNTS = (200, 300, 1000)


def _desk_judge_api_prices() -> tuple[dict, float, float, int, int]:
    """(prices $/MTok, chars/token, cache-write multiplier, wrapper chars, max output tokens) read from
    the driver the run-desk-judge action calls, so the estimate cannot drift from what it bills."""
    from scripts.research import desk_judge_api as dja
    return (dict(dja.PRICES), dja.CHARS_PER_TOKEN, dja.CACHE_WRITE_MULT,
            len(dja.USER_TMPL), dja.MAX_OUTPUT_TOKENS)


def desk_wake_stats(samples: Iterable[tuple[str, str, float]] = DESK_WAKE_SAMPLES) -> dict:
    costs = sorted(float(c) for _, _, c in samples)
    if not costs:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    n, mid = len(costs), len(costs) // 2
    return {"n": n, "mean": sum(costs) / n,
            "median": costs[mid] if n % 2 else (costs[mid - 1] + costs[mid]) / 2,
            "min": costs[0], "max": costs[-1]}


def desk_api_usd_per_packet() -> dict:
    """ESTIMATED $/packet on the stateless API path: uncached input (the 2.4k-char protocol is under the
    1,024-token cache minimum, so nothing is cached) + output at the mean and at the ceiling, plus the
    driver's own worst-case guard (every input token a cache write, full max_tokens output)."""
    prices, cpt, cw_mult, wrapper, max_out = _desk_judge_api_prices()
    chars_in = JUDGE_PACKET_CHARS + JUDGE_PROTOCOL_CHARS + wrapper
    in_tok = chars_in / cpt
    base = in_tok * prices["input"]
    return {"in_tokens": round(in_tok), "mean": (base + JUDGE_OUT_TOK_MEAN * prices["output"]) / 1e6,
            "ceiling": (base + JUDGE_OUT_TOK_CEILING * prices["output"]) / 1e6,
            "worst_case_guard": (in_tok * prices["input"] * cw_mult + max_out * prices["output"]) / 1e6}


def desk_scale_lines(samples: Iterable[tuple[str, str, float]] = DESK_WAKE_SAMPLES) -> list[dict]:
    """The desk scale lines. Each: ``label``, ``population``, ``n``, ``usd_per_decision``, ``usd_per_week``
    (a judged run is one-off: its $/week is ONE run per week), ``currency``, ``provenance`` (+ ``note``)."""
    from src.runtime import provenance as prov
    w = desk_wake_stats(samples)
    out: list[dict] = []
    if w["n"]:
        pop = (f"desk-wake sessions 2026-10-26T18:38Z..2026-10-27T03:04Z, all no_trade rows "
               f"(median ${w['median']:.3f}, range ${w['min']:.3f}-${w['max']:.3f})")
        out.append({"label": "hourly wake (24/day)", "population": pop, "n": w["n"],
                    "usd_per_decision": w["mean"], "usd_per_week": w["mean"] * WAKES_PER_WEEK_HOURLY,
                    "currency": "plan-allowance, API-equivalent USD", "provenance": prov.MEASURED,
                    "note": "mean of n wakes x 168/week; a propose_entry wake is unmeasured"})
        out.append({"label": "15-minute wake (96/day)", "population": pop + " -- no wake at this cadence exists",
                    "n": 0, "usd_per_decision": w["mean"], "usd_per_week": w["mean"] * WAKES_PER_WEEK_15MIN,
                    "currency": "plan-allowance, API-equivalent USD", "provenance": prov.ESTIMATED,
                    "note": f"hourly mean x 672/week (assumes cost per wake is cadence-independent); the "
                            f"packet is hourly, so ${w['mean'] * 4 / PACKETS_PER_HOUR:.3f} per NEW packet "
                            f"({4 - PACKETS_PER_HOUR} of 4 wakes see a packet already decided)"})
    api = desk_api_usd_per_packet()
    sess = SESSION_JUDGE_PILOT_USD / SESSION_JUDGE_PILOT_PACKETS
    for npk in JUDGE_PACKET_COUNTS:
        out.append({"label": f"DESK-18 judged run, {npk} packets, API path",
                    "population": f"{api['in_tokens']} in-tokens/packet from the median of 40 packets; "
                                  f"output {JUDGE_OUT_TOK_MEAN} tok mean (ceiling {JUDGE_OUT_TOK_CEILING}: "
                                  f"${api['ceiling'] * npk:.2f}; driver worst-case guard ${api['worst_case_guard'] * npk:.2f})",
                    "n": 0, "usd_per_decision": api["mean"], "usd_per_week": api["mean"] * npk,
                    "currency": "real USD, ANTHROPIC_API_KEY", "provenance": prov.ESTIMATED,
                    "note": "no API run has been made; the first run's usage.jsonl replaces this "
                            "(the manager's VM dry run, not re-run here, projected $5.97 worst case per 200 packets)"})
        out.append({"label": f"DESK-18 judged run, {npk} packets, session path",
                    "population": f"DESK-18B pilot, {SESSION_JUDGE_PILOT_PACKETS} packets in 5 sessions "
                                  f"(manager-reported, not re-read here)",
                    "n": SESSION_JUDGE_PILOT_PACKETS, "usd_per_decision": sess, "usd_per_week": sess * npk,
                    "currency": "plan-allowance, API-equivalent USD", "provenance": prov.MEASURED,
                    "note": "upper bound (~290k-token subagent context per batch); one pilot, one route"})
    return out


def render_desk_scale(lines: list[dict]) -> list[str]:
    L = ["DESK SCALE (per decision and per week; two currencies, never summed):"]
    for d in lines:
        L.append(f"  {d['label']}: ${d['usd_per_decision']:.4f}/decision, ${d['usd_per_week']:.2f}/week "
                 f"[{d['provenance'].upper()}, n={d['n']}, {d['currency']}]")
        L.append(f"      population: {d['population']}")
        L.append(f"      {d['note']}")
    return L


# ── per-lane dollars: an OPTIONAL, session-supplied observation ─────────────

def normalise_lane_costs(raw: Any) -> list[dict]:
    """Keep `session_id` / `title` / `cost_usd` from a pasted
    `get_session`/`list_sessions` result.

    Peels the same wrapper keys `scripts/ops/queue_latency.py::normalise_sessions`
    already proved against a real MCP result (`ccr`/`sessions`/`data`/`results`/
    `items`) rather than writing a second, drifting unwrap — this function adds
    `cost_usd`, which that one has no reason to carry.
    """
    node = raw
    for _ in range(4):
        if not isinstance(node, dict):
            break
        for key in ("sessions", "data", "results", "items", "ccr"):
            inner = node.get(key)
            if isinstance(inner, (list, dict)):
                node = inner
                break
        else:
            break
        if isinstance(node, list):
            break
    if isinstance(node, dict):
        entries = [node]
    elif isinstance(node, list):
        entries = node
    else:
        entries = []

    out: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        row = entry.get("ccr") if isinstance(entry.get("ccr"), dict) else entry
        sid = row.get("id") or row.get("session_id")
        if not isinstance(sid, str) or not sid.strip() or sid in seen:
            continue
        seen.add(sid)
        usage = ((row.get("external_metadata") or {}).get("usage")) or {}
        cost = usage.get("cost_usd")
        out.append({
            "session_id": sid.strip(),
            "title": row.get("title"),
            # ⚠️ `None` when unknown, NEVER `0.0` — a session this account
            # cannot see the full record for (e.g. another user's, relayed
            # inside an `<other-session>` envelope) is "we do not know its
            # cost", not "it cost nothing".
            "cost_usd": cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
            "tags": row.get("tags") if isinstance(row.get("tags"), list) else [],
        })
    return out


# ── rendering: what A3a's section 5 calls ───────────────────────────────────

def render_section_5(
    log: LoadResult,
    *,
    lane_costs: list[dict] | None,
    lane_costs_state: str = "not_observed",
    today: datetime | None = None,
) -> list[str]:
    """Brief section 5 — SPEND. Consumed by A3a.

    `lane_costs_state` follows the same three-state vocabulary
    `render_daily_brief.py` already uses for its MCP-only inputs: `read`
    (an observation was supplied and parsed), `unreadable` (supplied but
    would not parse), `not_observed` (nothing here could look — expected
    outside an interactive/manager session; see the module docstring).
    """
    now = today or datetime.now(timezone.utc)
    L = ["## §5 — SPEND", ""]

    if not log.healthy:
        L += [
            f"> ⚠️ **{len(log.unreadable)} READING(S) COULD NOT BE PARSED** — "
            f"the meters below are a FLOOR over what parsed, not the whole log.",
            "",
        ]
        for lineno, why in log.unreadable[:10]:
            L.append(f"> - line {lineno}: {why}")
        L.append("")

    L += [
        "**(a) THE CONTROL VARIABLE** — usage against the weekly plan "
        "allowance, paced at the sustainable rate. Operator-entered; only a human "
        "can read Settings > Usage. Never `0%` for a window nobody has "
        "read — that would say \"usage is zero\" when the truth is "
        "\"nobody looked\".",
        "",
    ]
    latest = latest_by_window(log.records)
    for w in WINDOWS:
        rec = latest[w]
        L.append(f"- **{_WINDOW_LABEL[w]}**")
        if rec is None:
            L.append(
                "  - **never recorded** — no operator reading exists for this "
                "window. Run `spend_meter.py --record --window "
                f"{w} --percent <p> --read-at <ISO> --recorded-by <who>` "
                "after reading Settings > Usage."
            )
            continue
        read_at = _parse_ts(rec["read_at"], "read_at")
        age = _fmt_age(now - read_at)
        L.append(
            f"  - **{float(rec['percent']):.1f}%** as of `{rec['read_at']}` "
            f"(**{age} old** — recorded by `{rec['recorded_by']}`; this is a "
            f"DATED reading, not a live value)"
        )
        if rec.get("note"):
            L.append(f"  - note: {rec['note']}")
        rate = _rate_line(log.records, w)
        if rate:
            L.append(rate)
    L.append("")
    L += [
        "> Context, restated because it is easy to misread: the pace is the "
        "SUSTAINABLE RATE, (100 - weekly%) / days to reset (operator, "
        "2026-10-18: as much work as possible without blowing through the "
        "allowance before a reset). `--capacity` turns it into a lane count; "
        "the manager's operating loop (manager SKILL.md) uses it. This meter "
        "reports facts; it does not grade them.",
        "",
    ]

    L += [
        "**(b) PER-LANE DOLLARS** (`cost_usd`, API-equivalent pricing) — "
        "context for COMPARING lanes to each other. NEVER the budget "
        "denominator; never blended with (a).",
        "",
    ]
    if lane_costs_state != "read":
        note = {
            "not_observed": (
                "◻️ **not_observed** — `cost_usd` is reachable only from an "
                "interactive session holding `get_session`/`list_sessions` "
                "(the Claude Code Remote MCP tools), never from a CI runner "
                "or a Routine-fired turn — established in "
                "`scripts/ops/render_daily_brief.py` and "
                "`scripts/ops/queue_latency.py`, and reconfirmed by this "
                "module calling those tools directly, 2026-09-21. Supply "
                "`--session-costs <file>` from a manager/build-lane session "
                "that pulled `list_sessions`."
            ),
            "unreadable": (
                "⛔ **unreadable** — `--session-costs` was supplied and would "
                "not parse. **We could not look**, this is not \"no lanes ran\"."
            ),
        }.get(lane_costs_state, f"`{lane_costs_state}`")
        L += [note, ""]
    else:
        rows = lane_costs or []
        known = [r for r in rows if r.get("cost_usd") is not None]
        total = sum(r["cost_usd"] for r in known)
        L.append(
            f"{len(known)} of {len(rows)} lane(s) in the supplied observation "
            f"carry a known `cost_usd`; their sum is **${total:.2f}**."
        )
        if len(known) < len(rows):
            L.append(
                f"  - {len(rows) - len(known)} lane(s) have **no known cost** "
                "(never rendered as $0.00) — excluded from the sum, not "
                "assumed free."
            )
        for r in sorted(known, key=lambda r: r["cost_usd"], reverse=True)[:20]:
            L.append(f"  - `{r['session_id']}` — {r.get('title') or '(untitled)'} "
                     f"· **${r['cost_usd']:.2f}**")
        L.append("")

    L += [
        "> Scope of this meter: attributed to this repo's Claude Code lanes "
        "only. A1's checklist note records a 2026-09-21 measurement that "
        "this was ~= the whole account pool — that mix is NOT re-measured "
        "by this module and may have changed since; verify against "
        "Settings > Usage 'What's using your week' before treating lane "
        "accounting as the total.",
        "",
    ]
    return L


# ─────────────────────────────────────────────────────────────── self-test ──
def _selftest() -> int:
    failures: list[str] = []

    def check(label: str, cond: bool) -> None:
        print(f"  {'PASS' if cond else 'FAIL'}: {label}")
        if not cond:
            failures.append(label)

    def base(**over: Any) -> dict:
        rec = {
            "window": "weekly",
            "percent": 42.0,
            "read_at": "2026-09-21T14:00:00Z",
            "recorded_by": "operator",
        }
        rec.update(over)
        return rec

    now = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)

    print("— reading validation, each refusal named —")
    check("a well-formed reading validates (positive control)",
          validate_reading(base(), now=now) is not None)

    def _raises(fn: Any) -> bool:
        try:
            fn()
        except ValueError:
            return True
        return False

    def refuses(label: str, rec: dict, needle: str) -> None:
        try:
            validate_reading(rec, now=now)
        except MeterError as exc:
            check(f"{label} (says why: {needle!r})", needle in str(exc))
        else:
            check(f"{label} — REFUSED", False)

    refuses("unknown window is refused", base(window="monthly"), "window")
    refuses("percent > 100 is refused", base(percent=142), "percent")
    refuses("percent < 0 is refused", base(percent=-1), "percent")
    refuses("a bool percent is refused (bool is an int subclass)",
            base(percent=True), "percent")
    refuses("an unparseable read_at is refused", base(read_at="soon"), "read_at")
    refuses("a future read_at is refused",
            base(read_at="2026-09-22T00:00:00Z"), "future")
    refuses("an empty recorded_by is refused", base(recorded_by="  "), "recorded_by")
    refuses("a missing field is refused", {"window": "weekly"}, "missing required field")

    print("— fable is a declared window like any other —")
    check("fable_weekly validates", validate_reading(base(window="fable_weekly"), now=now) is not None)

    print("— append-only round trip: EVERY reading kept, never folded —")
    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / "R.jsonl"
        append_reading(base(read_at="2026-09-18T14:00:00Z"), store)
        append_reading(base(read_at="2026-09-21T14:00:00Z", percent=70.0), store)
        append_reading(base(window="session", read_at="2026-09-21T14:30:00Z", percent=12.0), store)
        res = read_readings(store)
        check("all three readings are preserved (time series, not folded)",
              len(res.records) == 3)
        latest = latest_by_window(res.records)
        check("latest_by_window picks the later weekly reading",
              latest["weekly"]["percent"] == 70.0)
        check("…and a window with no reading is None, never a fabricated row",
              latest["fable_weekly"] is None)

        print("— rate: never fabricated from one point, computed from two —")
        check("no rate line from a single reading",
              _rate_line(res.records, "session") is None)
        rate = _rate_line(res.records, "weekly")
        check("a rate line exists once two readings exist, and is labelled measured",
              rate is not None and "measured" in rate and "drifting" in rate)

        print("— malformed line handling —")
        store.write_text(store.read_text() + "{not json\n")
        res2 = read_readings(store)
        check("⚠️ a malformed line is REPORTED, never skipped silently",
              len(res2.unreadable) == 1 and len(res2.records) == 3)
        check("…and healthy is False so nothing can call this clean",
              not res2.healthy)

        empty = read_readings(Path(td) / "missing.jsonl")
        check("a missing store is readable-and-empty, not an error",
              empty.healthy and not empty.records)

    print("— append() refuses on the write path too —")
    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / "R.jsonl"
        try:
            append_reading(base(window="bogus"), store)
        except MeterError:
            check("append_reading() refuses an invalid reading", True)
        else:
            check("append_reading() refuses an invalid reading", False)
        check("…and wrote NOTHING when it refused",
              not store.exists() or store.read_text() == "")

    print("— section 5: the one sentence this module exists to get right —")
    empty_log = LoadResult()
    rendered_empty = "\n".join(render_section_5(empty_log, lane_costs=None, today=now))
    check("⚠️ NEVER a fabricated reading value when nothing has been recorded",
          "**0.0%**" not in rendered_empty and "**0%**" not in rendered_empty)
    check("…every window says it was never recorded",
          rendered_empty.count("never recorded") == len(WINDOWS))
    check("…and per-lane dollars declare not_observed rather than $0.00",
          "not_observed" in rendered_empty and "$0.00" not in rendered_empty)

    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / "R.jsonl"
        stale_ts = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        append_reading(base(read_at=stale_ts, percent=55.0), store)
        log = read_readings(store)
        rendered_stale = "\n".join(render_section_5(log, lane_costs=None, today=now))
        check("a stale reading renders its AGE and is never presented as live",
              "3d old" in rendered_stale and "as of" in rendered_stale)
        check("…a healthy log's section 5 does NOT say 'COULD NOT BE PARSED' "
              "(negative control)",
              "COULD NOT BE PARSED" not in rendered_stale)

        lane_rows = [
            {"session_id": "session_A", "title": "A1 lane", "cost_usd": 3.5, "tags": []},
            {"session_id": "session_B", "title": "unknown-cost lane", "cost_usd": None, "tags": []},
        ]
        rendered_lanes = "\n".join(render_section_5(
            log, lane_costs=lane_rows, lane_costs_state="read", today=now))
        check("supplied lane costs sum only the KNOWN ones and state the population",
              "$3.50" in rendered_lanes and "1 of 2 lane" in rendered_lanes)
        check("…an unknown-cost lane is named as unknown, never folded into $0",
              "no known" in rendered_lanes)

    print("— capacity: the sustainable rate, never a guessed count —")
    cap_now = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
    check("no weekly reading -> never_recorded, no lane count",
          capacity(LoadResult(), now=cap_now) == {"state": "never_recorded", "lanes": None})
    wk = base(window="weekly", percent=73.0, read_at="2026-10-18T08:40:00Z",
              note="operator screenshot; reset Wed 2026-10-21 18:00Z")
    c = capacity(LoadResult(records=[wk]), now=cap_now)
    check("reset time is read from the reading's note",
          c["state"] == "ok" and c["reset_at"] == "2026-10-21T18:00:00Z")
    check("gross rate = (100 - weekly%) / days to reset",
          abs(c["rate_gross_pp_per_day"] - 27 / 3.375) < 0.01)
    check("a low rate still suggests the one-lane floor, never zero", c["lanes"] == 1)
    c2 = capacity(LoadResult(records=[dict(wk, percent=10.0)]), now=cap_now, pp_per_lane_hour=0.2,
                  live_open=0)
    check("a high rate suggests at most 5 lanes (advice for judgment, not a cap)", c2["lanes"] == 5)
    check("a reading with no reset named is reset_unknown, not a guess",
          capacity(LoadResult(records=[dict(wk, note=None)]), now=cap_now)["state"] == "reset_unknown")
    check("a reading older than its own reset is from a past week",
          capacity(LoadResult(records=[wk]), reset_at="2026-10-14T18:00:00Z",
                   now=cap_now)["state"] == "reading_from_past_week")
    check("render names the formula", "(100 - 73)" in "\n".join(render_capacity(c)))

    print("— calibration: pp per lane-hour from readings —")
    rd = [dict(wk, percent=44.0, read_at="2026-10-26T06:14:00Z"), dict(wk, percent=50.0, read_at="2026-10-26T13:27:00Z")]
    k = calibrate_pp_per_lane_hour(rd, 30.0)
    check("measured: 6 pp / 30 lane-hours = 0.2", k["basis"] == "measured" and abs(k["value"] - 0.2) < 1e-9)
    check("one reading -> inferred constant", calibrate_pp_per_lane_hour(rd[:1], 30.0)["basis"] == "inferred"
          and calibrate_pp_per_lane_hour(rd[:1], 30.0)["value"] == PP_PER_LANE_HOUR)
    check("no lane-hours -> inferred", calibrate_pp_per_lane_hour(rd, None)["basis"] == "inferred")
    check("reset between readings (drop) -> inferred",
          calibrate_pp_per_lane_hour([rd[1], dict(rd[0], read_at="2026-10-26T14:00:00Z")], 10.0)["basis"] == "inferred")
    check("old reading outside the window is ignored",
          calibrate_pp_per_lane_hour([dict(rd[0], read_at="2026-10-24T06:00:00Z"), rd[1]], 30.0)["basis"] == "inferred")
    check("no readings -> inferred", calibrate_pp_per_lane_hour([], 5.0)["basis"] == "inferred")
    print("— measured reserve: runs/day x pp per run, capped by the § 6.4 bound —")
    check("measured reserve formula", abs(measured_reserve_pp(3.0, 12.0, 0.1) - (2 + 3 * 1.7)) < 1e-9)
    cmr = capacity(LoadResult(records=[wk]), now=cap_now, live_open=7, review_runs_day=12.0)
    check("measured reserve is below the bound and used", cmr["reserve_source"] == "measured"
          and cmr["reserve_pp"] < cmr["reserve_bound_pp"])
    cmh = capacity(LoadResult(records=[wk]), now=cap_now, live_open=1, review_runs_day=500.0)
    check("a huge measured rate never exceeds the bound (ceiling)", cmh["reserve_pp"] == cmh["reserve_bound_pp"])
    check("no measurement -> bound", capacity(LoadResult(records=[wk]), now=cap_now,
          live_open=7)["reserve_source"] == "bound")
    check("unreadable log -> None, not 0", review_runs_per_day(Path("/nonexistent/x")) is None)
    check("render says KEEP N LANES", "KEEP " in "\n".join(render_capacity(cmr)))
    print("— reserve: headroom for the live-trade-review routine (design § 6.4) —")
    check("design worked value: D=3.19, n=2 -> 15.4 pp", abs(reserve_pp(3.19, 2) - 15.4) < 0.05)
    check("design worked value: last 24h, n=2 -> ~11 pp", abs(reserve_pp(1.0, 2) - 11.0) < 0.05)
    check("final hour, n=2 -> ~2.4 pp (floor + a sliver)", abs(reserve_pp(1 / 24, 2) - 2.4) < 0.05)
    check("reserve is non-decreasing in n", reserve_pp(2.0, 3) > reserve_pp(2.0, 2) > reserve_pp(2.0, 0))
    cm = capacity(LoadResult(records=[wk]), now=cap_now, live_open=2)
    check("a supplied count reads measured, with that n",
          cm["reserve_basis"] == {"n": 2, "exposure": "measured"})
    check("reserve_pp matches the formula", abs(cm["reserve_pp"] - round(reserve_pp(3.375, 2), 2)) < 0.01)
    check("net rate = (100 - weekly% - reserve) / days",
          abs(cm["rate_pp_per_day"] - max(27 - cm["reserve_pp"], 0) / 3.375) < 0.02)
    check("27 pp left > 15.7 pp reserve -> not breached", cm["reserve_breached"] is False)
    cb = capacity(LoadResult(records=[dict(wk, percent=90.0)]), now=cap_now, live_open=2)
    check("10 pp left < reserve -> breached", cb["reserve_breached"] is True)
    check("breached: render says so and names the always-one-lane doctrine",
          "RESERVE BREACHED" in "\n".join(render_capacity(cb))
          and "always-one-lane" in "\n".join(render_capacity(cb)))
    check("breached: net rate is 0 and the suggestion is still the one-lane floor, never zero",
          cb["rate_pp_per_day"] == 0 and cb["lanes"] == 1)
    cu = capacity(LoadResult(records=[wk]), now=cap_now)
    check("no --live-open -> exposure_unknown, n = roster bound, never 0",
          cu["reserve_basis"] == {"n": RESERVE_ROSTER_BOUND, "exposure": "exposure_unknown"})
    check("could-not-look reserves MORE than a measured zero",
          cu["reserve_pp"] > capacity(LoadResult(records=[wk]), now=cap_now, live_open=0)["reserve_pp"])
    check("render prints the one reserve line",
          "reserve for live review = " in "\n".join(render_capacity(cu))
          and "exposure_unknown" in "\n".join(render_capacity(cu)))
    cl = capacity(LoadResult(records=[dict(wk, percent=5.0)]), now=cap_now, live_open=1)
    check("plenty of allowance -> not breached, net rate below gross",
          cl["reserve_breached"] is False and cl["rate_pp_per_day"] < cl["rate_gross_pp_per_day"])
    ds = desk_scale_lines()
    hw = [d for d in ds if d["label"].startswith("hourly")][0]
    check("hourly wake line is MEASURED over the sample, 168/week",
          hw["provenance"] == "measured" and hw["n"] == len(DESK_WAKE_SAMPLES)
          and abs(hw["usd_per_week"] - hw["usd_per_decision"] * 168) < 1e-9)
    check("15-min line is ESTIMATED, n=0, 4x the hourly week",
          [d for d in ds if d["label"].startswith("15-minute")][0]["provenance"] == "estimated"
          and abs([d for d in ds if d["label"].startswith("15-minute")][0]["usd_per_week"] - hw["usd_per_week"] * 4) < 1e-9)
    check("six judged-run lines (3 sizes x 2 routes)", sum("judged run" in d["label"] for d in ds) == 6)
    check("a negative count is refused", _raises(lambda: capacity(LoadResult(records=[wk]),
                                                                  now=cap_now, live_open=-1)))

    print()
    if failures:
        print(f"SELF-TEST FAILED — {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SELF-TEST PASS")
    return 0


def _check(store: Path) -> int:
    """Validate every reading in the real store. Used by the guard."""
    res = read_readings(store)
    if res.unreadable:
        print(f"::error::spend_meter: {len(res.unreadable)} UNREADABLE reading(s):")
        for lineno, why in res.unreadable:
            print(f"  line {lineno}: {why}")
        return 1
    latest = latest_by_window(res.records)
    print(json.dumps(
        {w: (r["read_at"] if r else None) for w, r in latest.items()},
        indent=2, sort_keys=True,
    ))
    print(f"spend_meter: clean — {len(res.records)} reading(s) validated")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--check", action="store_true", help="validate every reading in the store")
    ap.add_argument("--store", default=str(STORE))

    ap.add_argument("--record", action="store_true", help="append one operator-entered reading")
    ap.add_argument("--window", choices=WINDOWS)
    ap.add_argument("--percent", type=float)
    ap.add_argument("--read-at", help="ISO timestamp for WHEN the operator read Settings > Usage")
    ap.add_argument("--recorded-by", default="operator")
    ap.add_argument("--note", default=None)

    ap.add_argument("--section-5", action="store_true", help="render brief section 5")
    ap.add_argument("--capacity", action="store_true",
                    help="sustainable rate and suggested lane count (manager operating loop, step 2)")
    ap.add_argument("--reset-at", default=None, help="weekly reset time (ISO); else read from the reading's note")
    ap.add_argument("--pp-per-lane-hour", type=float, default=None,
                    help="override; default = calibrated from readings + --lane-hours, else the constant (inferred)")
    ap.add_argument("--lane-hours", type=float, default=None,
                    help="lane-hours run between the first and last weekly reading in the last 24h")
    ap.add_argument("--live-open", type=int, default=None,
                    help="with --capacity: open live/prop packages (from live_review_due); "
                         "absent = exposure_unknown (reserve sized at the roster bound)")
    ap.add_argument("--review-log", default=str(REVIEW_LOG),
                    help="with --capacity: live-review log used to MEASURE runs/day")
    ap.add_argument("--review-pp-per-run", type=float, default=REVIEW_PP_PER_RUN)
    ap.add_argument("--json", action="store_true", help="with --capacity: print the dict")
    ap.add_argument("--session-costs", default=None,
                     help="path to a pasted get_session/list_sessions result, or '-' for stdin")
    args = ap.parse_args(argv)

    if args.self_test:
        return _selftest()

    store = Path(args.store)

    if args.check:
        return _check(store)

    if args.record:
        if not (args.window and args.percent is not None and args.read_at):
            print("spend_meter: --record needs --window --percent --read-at", file=sys.stderr)
            return 2
        try:
            rec = append_reading({
                "window": args.window,
                "percent": args.percent,
                "read_at": args.read_at,
                "recorded_by": args.recorded_by,
                "note": args.note,
            }, store)
        except MeterError as exc:
            print(f"spend_meter: REFUSED — {exc}", file=sys.stderr)
            return 1
        print(f"spend_meter: recorded {rec['window']} {rec['percent']}% "
              f"as of {rec['read_at']} (by {rec['recorded_by']})")
        return 0

    if args.capacity:
        if args.live_open is not None and args.live_open < 0:
            print("spend_meter: --live-open must be >= 0", file=sys.stderr)
            return 2
        log = read_readings(store)
        cal = ({"value": args.pp_per_lane_hour, "basis": "operator override", "why": "--pp-per-lane-hour"}
               if args.pp_per_lane_hour is not None
               else calibrate_pp_per_lane_hour(log.records, args.lane_hours))
        c = capacity(log, reset_at=args.reset_at,
                     pp_per_lane_hour=cal["value"], live_open=args.live_open,
                     review_runs_day=review_runs_per_day(Path(args.review_log)),
                     review_pp_per_run=args.review_pp_per_run)
        c["pp_per_lane_hour_basis"] = cal["basis"]
        c["pp_per_lane_hour_why"] = cal["why"]
        desk = desk_scale_lines()
        if args.json:
            print(json.dumps({**c, "desk_scale": desk}, indent=2))
        else:
            print("\n".join(render_capacity(c)))
            print(f"  pp/lane-hour basis: {cal['basis']} -- {cal['why']}")
            print("\n".join(render_desk_scale(desk)))
        return 0

    if args.section_5:
        log = read_readings(store)
        lane_costs: list[dict] | None = None
        lane_state = "not_observed"
        if args.session_costs:
            try:
                raw = _load_observation(args.session_costs)
                lane_costs = normalise_lane_costs(raw) if raw is not None else []
                lane_state = "read"
            except (OSError, ValueError):
                lane_state = "unreadable"
        print("\n".join(render_section_5(log, lane_costs=lane_costs, lane_costs_state=lane_state)))
        return 0 if log.healthy else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
