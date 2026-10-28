#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::review-followthrough (--self-test); called by
#   every review's Layer 0 and as the first agenda item of Thursday planning
#   (.claude/skills/manager/SKILL.md § "Weekly planning", step 0).
"""REVIEW FOLLOW-THROUGH — does what a review files actually get DONE?

WHY (operator, 2026-10-28): "ensuring that there's a clear pipeline for any
follow-up tasks or insights or new ideas that come out of those reviews to
actually be turned into work tasks that we will definitely get to." MEASURED
the same day (`pipeline.py --stats`, 2,344 items): 1,011 open, 505 due, 606
`routed`, 54 unrouted (oldest 94 d); 838 killed vs 495 done. Filing works.
Getting to it does not. This script grades each review SOURCE on its own
follow-through, so a review starts by grading its prior follow-ups and
Thursday planning starts from the numbers, not from a feeling.

POPULATION, stated because the store has no `source` field:
  * pipeline items (`scripts/ops/pipeline.py`, the only reader) and
  * checklist rows (`src.runtime.checklist_store`, the only reader).
  The source is CLASSIFIED from text the record already carries -- id,
  origin.kind/ref for an item; id, title and the first 300 chars of note for
  a row -- by the ordered patterns in `SOURCES`. Everything that matches none
  is `other`, and the per-source counts always SUM TO THE TOTAL (asserted), so
  a pattern that silently stops matching shows up as `other` growing, never as
  a source going quiet.

DATES, and their limits:
  * filed  = the YYYYMMDD in the id; else the first record's filename stamp
    (items) / `updated_at` (rows, a LATER bound). `undated` is counted.
  * closed = the filename stamp of an item's first terminal record; for a row
    its `updated_at` when state is done/dropped (a later bound -- a later
    note moves it). Items migrated 2026-09-24 carry that migration stamp, so
    a pre-migration close reads as 09-24 (only matters for windows > 34 d).

PER SOURCE it reports two things, never collapsed:
  cohort  -- filed in the trailing window: filed, done, killed, open, and the
             share closed (done or killed) within N days of filing.
  backlog -- everything still open now, any age: open, median age, share due
             (items) / past observation.due_by (rows), no-owner count, and the
             oldest open records.
"no owner" = an open item that is not `routed`, or routed to an owner
`pipeline.owner_of` cannot resolve to a checklist row, research unit or PR;
an open row whose `owner` is empty or names nobody (`_NO_OWNER`).

Usage:
  python3 scripts/ops/review_followthrough.py                       # all sources, 7 d window
  python3 scripts/ops/review_followthrough.py --source health-review --window-days 7
  python3 scripts/ops/review_followthrough.py --json
  python3 scripts/ops/review_followthrough.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pipeline  # noqa: E402

#: Ordered: the first match wins, so the more specific pattern comes first
#: (perf-followup before performance-review, frontier before ml-review).
#: `research-review` is the performance review's research half (its SKILL).
SOURCES: list[tuple[str, str]] = [
    ("perf-followup", r"perf[-_ ]?follow|PERF-FU\b|PERF-FU-"),
    ("performance-review", r"performance[-_ ]review|PERF-REVIEW|perf[-_]review|research[-_ ]review"),
    ("frontier", r"frontier"),
    ("ml-review", r"\bml[-_ ]review|ML-REVIEW|ML-RESEARCH-W|ML-READ-"),
    ("health-review", r"health[-_ ]review|HEALTH-REVIEW"),
    ("weekly-audit", r"weekly[-_ ]audit|WEEKLY-AUDIT|^AUD-20\d{6}-(?!CA-)"),
    ("programme-review", r"programme[-_ ]review|PROGRAMME-REVIEW|research/programmes"),
    ("research-ops", r"research[-_ ]ops|RESEARCH-OPS"),
    ("ltr", r"live[-_ ]trade[-_ ]review|\bLTR-?\d|live_review"),
    ("desk", r"trading[-_ ]desk|\bDESK-|claude_desk"),
    # Not reviews, kept as named buckets so `other` stays interpretable.
    ("soak-watch", r"SOAK-WATCH|^PI-SOAK-"),
    ("code-audit", r"code[-_ ]audit|\bCA-[AB]\d\d"),
    ("system-audit", r"system[-_ ]audit"),
]
REVIEW_SOURCES = [n for n, _ in SOURCES if n not in ("soak-watch", "code-audit", "system-audit")]
OTHER = "other"
_COMPILED = [(n, re.compile(r, re.IGNORECASE)) for n, r in SOURCES]
_ROW_OPEN = ("queued", "in_flight", "blocked", "landed_unproven")
_ROW_CLOSED = ("done", "dropped")
#: Owner text that names nobody (MEASURED 2026-10-28: 4 open rows read "unassigned").
_NO_OWNER = ("", "unassigned", "none", "null", "tbd", "-", "—")
_STAMP = re.compile(r"^(\d{8})T")


def classify(text: str) -> str:
    for name, rx in _COMPILED:
        if rx.search(text):
            return name
    return OTHER


def _d(s) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")[:19]).date() \
            if "T" in str(s) else date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _stamp_date(fname: str) -> date | None:
    m = _STAMP.match(fname or "")
    return date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:])) if m else None


# ── normalise both stores to one record shape ────────────────────────────────
def pipeline_records(store: Path = pipeline.STORE, rows: dict | None = None,
                     today: date | None = None) -> tuple[list[dict], dict]:
    """-> (records, read_state). One record per item: kind, id, source, state,
    open, filed, closed, due, owner (bool), what."""
    res = pipeline.read_log(store)
    first_seen: dict[str, date] = {}
    first_terminal: dict[str, date] = {}
    if store.is_dir():
        for path in sorted(store.glob(f"*{pipeline.RECORD_SUFFIX}")):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                rec = None  # counted by read_log as unreadable
            if not isinstance(rec, dict):
                continue
            iid, d = rec.get("id"), _stamp_date(path.name)
            if not isinstance(iid, str) or d is None:
                continue
            first_seen.setdefault(iid, d)
            if rec.get("state") in pipeline.TERMINAL_STATES:
                first_terminal.setdefault(iid, d)
    rows = rows or {}
    out = []
    for it in res.items.values():
        o = it.get("origin") or {}
        src = classify(" ".join([it["id"], str(o.get("kind", "")), str(o.get("ref", ""))]))
        state = it.get("state")
        is_open = state in pipeline.OPEN_STATES
        if state == "routed":
            kind, _ = pipeline.owner_of(it, rows, _unit_exists)
            owned = kind != "unresolved"
        else:
            owned = not is_open
        out.append({
            "store": "pipeline", "id": it["id"], "source": src, "state": state,
            "open": is_open, "filed": pipeline.filed_date(it) or first_seen.get(it["id"]),
            "closed": first_terminal.get(it["id"]) if not is_open else None,
            "due": is_open and pipeline.is_due(it, today), "owned": owned,
            "what": str(it.get("what", ""))[:110],
        })
    return out, {"items": len(res.items), "unreadable": len(res.unreadable),
                 "state": "read" if res.healthy else "unreadable"}


def _unit_exists(uid: str) -> bool:
    return (REPO_ROOT / "research" / "queue" / f"{uid}.yaml").exists()


def checklist_records(data: dict, today: date | None = None) -> list[dict]:
    today = today or datetime.now(timezone.utc).date()
    out = []
    for r in data.get("items") or []:
        rid = str(r.get("id", ""))
        src = classify(" ".join([rid, str(r.get("title", "")), str(r.get("note", ""))[:300]]))
        state = r.get("state")
        is_open = state in _ROW_OPEN
        upd = _d(r.get("updated_at"))
        due_by = _d((r.get("observation") or {}).get("due_by")) if isinstance(r.get("observation"), dict) else None
        out.append({
            "store": "checklist", "id": rid, "source": src, "state": state, "open": is_open,
            "filed": pipeline.filed_date({"id": rid}) or upd,
            "closed": upd if state in _ROW_CLOSED else None,
            "due": bool(is_open and due_by and due_by <= today),
            "owned": (not is_open) or str(r.get("owner") or "").strip().lower() not in _NO_OWNER,
            "what": str(r.get("title", ""))[:110],
        })
    return out


# ── the grade ────────────────────────────────────────────────────────────────
def grade(records: list[dict], today: date, window_days: int = 7,
          closed_within_days: int = 7, oldest: int = 5) -> dict:
    start = today - timedelta(days=window_days)
    by: dict[str, dict] = {}
    names = [n for n, _ in SOURCES] + [OTHER]
    for n in names:
        by[n] = {"cohort": {"filed": 0, "done": 0, "killed": 0, "open": 0,
                            "closed_within_n": 0, "undated": 0},
                 "backlog": {"open": 0, "due": 0, "no_owner": 0, "ages": [], "oldest": []}}
    for r in records:
        s = by[r["source"]]
        if r["filed"] is None:
            s["cohort"]["undated"] += 1
        elif r["filed"] >= start:
            c = s["cohort"]
            c["filed"] += 1
            if r["open"]:
                c["open"] += 1
            elif r["state"] == "done":
                c["done"] += 1
            else:
                c["killed"] += 1  # pipeline killed / checklist dropped
            if not r["open"] and r["closed"] and (r["closed"] - r["filed"]).days <= closed_within_days:
                c["closed_within_n"] += 1
        if r["open"]:
            b = s["backlog"]
            b["open"] += 1
            b["due"] += int(r["due"])
            b["no_owner"] += int(not r["owned"])
            age = (today - r["filed"]).days if r["filed"] else None
            if age is not None:
                b["ages"].append(age)
            b["oldest"].append((age if age is not None else -1, r))
    total = sum(v["backlog"]["open"] for v in by.values())
    assert total == sum(1 for r in records if r["open"]), "per-source open must sum to total"
    result = {}
    for n, v in by.items():
        c, b = v["cohort"], v["backlog"]
        ages = b.pop("ages")
        olds = sorted(b.pop("oldest"), key=lambda t: -t[0])[:oldest]
        result[n] = {
            "cohort": {**c, "closed_within_n_share": _share(c["closed_within_n"], c["filed"])},
            "backlog": {**b, "median_age_days": statistics.median(ages) if ages else None,
                        "due_share": _share(b["due"], b["open"]),
                        "oldest": [{"id": r["id"], "store": r["store"], "age_days": a if a >= 0 else None,
                                    "state": r["state"], "owned": r["owned"], "what": r["what"]}
                                   for a, r in olds]},
        }
    return result


def _share(a: int, b: int):
    return round(a / b, 3) if b else None


def _fmt(x, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x:.0%}" if pct else f"{x:g}"


def render(g: dict, meta: dict, sources: list[str]) -> str:
    w, n = meta["window_days"], meta["closed_within_days"]
    lines = [f"REVIEW FOLLOW-THROUGH  as of {meta['today']}  window {w} d  closed-within {n} d",
             (f"POPULATION: {meta['pipeline_items']} pipeline items (store {meta['pipeline_state']}, "
              f"{meta['pipeline_unreadable']} unreadable) + {meta['checklist_rows']} checklist rows; "
              f"source classified from id/origin/title text (see SOURCES)"),
             "",
             f"{'source':<19}| cohort(filed {w}d): filed done kill open ≤{n}d | backlog(now): open due% med-age no-owner",
             "-" * 104]
    for s in sources:
        c, b = g[s]["cohort"], g[s]["backlog"]
        lines.append(f"{s:<19}| {c['filed']:>17} {c['done']:>4} {c['killed']:>4} {c['open']:>4} "
                     f"{_fmt(c['closed_within_n_share'], True):>4} | {b['open']:>17} {_fmt(b['due_share'], True):>4} "
                     f"{_fmt(b['median_age_days']):>7} {b['no_owner']:>8}")
    for s in sources:
        olds = g[s]["backlog"]["oldest"]
        if not olds:
            continue
        lines.append(f"\noldest open — {s}:")
        for o in olds:
            lines.append(f"  {_fmt(o['age_days']):>4}d {o['store'][:4]} {o['state']:<15} "
                         f"{'' if o['owned'] else 'NO-OWNER '}{o['id']}  {o['what'][:70]}")
    return "\n".join(lines)


def run(today: date, window_days: int, closed_within_days: int, oldest: int,
        source: str | None) -> tuple[dict, dict]:
    from src.runtime import checklist_store
    data = checklist_store.load()
    rows = {r["id"]: r for r in data.get("items") or [] if r.get("id")}
    precs, pstate = pipeline_records(rows=rows, today=today)
    crecs = checklist_records(data, today)
    g = grade(precs + crecs, today, window_days, closed_within_days, oldest)
    meta = {"today": today.isoformat(), "window_days": window_days,
            "closed_within_days": closed_within_days, "pipeline_items": pstate["items"],
            "pipeline_state": pstate["state"], "pipeline_unreadable": pstate["unreadable"],
            "checklist_rows": len(crecs)}
    if source:
        g = {source: g[source]}
    return g, meta


# ── self-test: a positive control for every source and every metric ──────────
def _selftest() -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    samples = {
        "perf-followup": "lane PERF-FOLLOWUP-W43 perf-followup track 3",
        "performance-review": "PERF-REVIEW-W41 /performance-review",
        "frontier": "ML-FRONTIER-PREP frontier scan",
        "ml-review": "ml-review 2026-10-04",
        "health-review": "docs/archive/.../health-review-backlog.json#BL-1",
        "weekly-audit": "WEEKLY-AUDIT-2026-10-19 C8",
        "programme-review": "research programme review docs/research/programmes/x.md",
        "research-ops": "research-ops 2026-10-26 20:47Z (RESEARCH-OPS-20261026-2047)",
        "ltr": "LTR-4 live-trade-review",
        "desk": "DESK-13 trading-desk",
        "soak-watch": "SOAK-WATCH 2026-10-04",
        "code-audit": "code audit 2026-09-27 lane CA-A07",
        "system-audit": "docs/audits/system-audit-2026-09-29.md#j",
    }
    for want, text in samples.items():
        check(classify(text) == want, f"classify({text!r}) -> {classify(text)}, want {want}")
    check(classify("AUD-20261019-ROUTED-TO-CLOSED-ROW") == "weekly-audit", "AUD- row id")
    check(classify("AUD-20260927-CA-A02-halt") == "code-audit", "code-audit AUD id must not be weekly-audit")
    check(classify("lane NEWS-HIST-REPLAY") == OTHER, "unmatched text must be other")
    check(set(samples) == {n for n, _ in SOURCES}, "every SOURCES entry has a positive control")

    today = date(2026, 10, 28)

    def rec(src, state, filed, closed=None, open_=None, due=False, owned=True):
        o = state in ("queued", "due", "routed", "in_flight") if open_ is None else open_
        return {"store": "pipeline", "id": f"X-{src}-{state}-{filed}", "source": src, "state": state,
                "open": o, "filed": filed, "closed": closed, "due": due, "owned": owned, "what": "w"}

    def d(n):
        return today - timedelta(days=n)
    recs = [rec("health-review", "done", d(3), d(2)),            # cohort, closed in 1 d
            rec("health-review", "killed", d(5), d(5)),          # cohort, closed in 0 d
            rec("health-review", "done", d(6), d(6) + timedelta(days=10)),  # cohort, slow (future ok)
            rec("health-review", "routed", d(2), due=True),      # cohort open, due
            rec("health-review", "queued", d(40), due=True, owned=False),  # backlog only, oldest
            rec("health-review", "queued", None, owned=False),   # undated
            rec("desk", "done", d(30), d(1))]                     # outside window
    g = grade(recs, today, window_days=7, closed_within_days=7, oldest=2)
    hc, hb = g["health-review"]["cohort"], g["health-review"]["backlog"]
    check(hc["filed"] == 4 and hc["done"] == 2 and hc["killed"] == 1 and hc["open"] == 1,
          f"cohort counts wrong: {hc}")
    check(hc["closed_within_n"] == 2 and hc["closed_within_n_share"] == 0.5, f"closed-within wrong: {hc}")
    check(hc["undated"] == 1, "undated must be counted, not dropped")
    check(hb["open"] == 3 and hb["due"] == 2 and hb["no_owner"] == 2, f"backlog wrong: {hb}")
    check(hb["median_age_days"] == 21, f"median age of [2, 40] = 21, got {hb['median_age_days']}")
    check(hb["oldest"][0]["age_days"] == 40 and len(hb["oldest"]) == 2, f"oldest wrong: {hb['oldest']}")
    check(g["desk"]["cohort"]["filed"] == 0, "a record filed outside the window is not in the cohort")
    check(g["frontier"]["backlog"]["median_age_days"] is None and
          g["frontier"]["cohort"]["closed_within_n_share"] is None, "empty source must render —, not 0")
    check(_fmt(None) == "—" and _fmt(21.0) == "21" and _fmt(0.5, True) == "50%", "formatting")

    rows = checklist_records({"items": [
        {"id": "AUD-20261019-X", "title": "t", "note": "", "state": "queued", "owner": None},
        {"id": "PERF-1", "title": "From PERF-REVIEW-W41", "note": "", "state": "done",
         "owner": "manager", "updated_at": "2026-10-20T00:00:00Z"},
        {"id": "Z", "title": "t", "note": "", "state": "queued", "owner": "unassigned"},
        {"id": "Y", "title": "landed", "note": "", "state": "landed_unproven", "owner": "lane",
         "updated_at": "2026-10-01T00:00:00Z", "observation": {"due_by": "2026-10-10"}}]}, today)
    check(rows[0]["source"] == "weekly-audit" and rows[0]["open"] and not rows[0]["owned"]
          and rows[0]["filed"] == date(2026, 10, 19), f"row 0 wrong: {rows[0]}")
    check(rows[1]["source"] == "performance-review" and rows[1]["closed"] == date(2026, 10, 20), "row 1")
    check(not rows[2]["owned"], "owner 'unassigned' is no owner")
    check(rows[3]["due"] and rows[3]["open"], "landed_unproven past due_by is open and due")

    # Smoke run against the live stores: must read, and sources must sum to total.
    try:
        _, meta = run(today, 7, 7, 3, None)
        check(meta["pipeline_state"] == "read", "live pipeline store unreadable")
        check(meta["pipeline_items"] > 0 and meta["checklist_rows"] > 0,
              "live smoke run read zero records — the probe cannot see the store")
    except Exception as exc:  # noqa: BLE001
        fails.append(f"live smoke run raised {type(exc).__name__}: {exc}")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"review_followthrough self-test: {'FAIL' if fails else 'ok'} ({len(fails)} failure(s))")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--closed-within-days", type=int, default=7)
    ap.add_argument("--oldest", type=int, default=5, help="oldest open records listed per source")
    ap.add_argument("--source", choices=[n for n, _ in SOURCES] + [OTHER])
    ap.add_argument("--all-sources", action="store_true",
                    help="also print the non-review buckets (soak-watch, code-audit, system-audit, other)")
    ap.add_argument("--today", help="YYYY-MM-DD (default: UTC today)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _selftest()
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    g, meta = run(today, a.window_days, a.closed_within_days, a.oldest, a.source)
    if a.json:
        print(json.dumps({"meta": meta, "sources": g}, indent=2, default=str))
        return 0
    order = [a.source] if a.source else (list(g) if a.all_sources else REVIEW_SOURCES)
    print(render(g, meta, order))
    return 0


if __name__ == "__main__":
    sys.exit(main())
