#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::checklist-store-guard (--self-test).
"""BACKFILL PROPOSAL for the filing contract: owner / due_by / roadmap for every open checklist row.

WHY (operator, 2026-11-01, lane CHECKLIST-OWNER-DUE): the contract refuses NEW rows without an owner, a date
and a roadmap ref; the rows filed before it need the same. Mechanical part = owner `manager` where null.
Judgment part = DATES and DROPS: this script only PROPOSES them (a reviewable JSONL + a summary); nothing is
dated or dropped until the manager reviews and runs `--apply`.

THE RULES (declared before the run; every proposed row carries `due_basis` naming the rule that fired):
  R1 in_flight        due today+2 (a lane is on it: confirm or re-date).
  R2 landed_unproven  its own `observation.due_by` if still in the future; else (observation overdue or absent)
                      slotted from today+1 at 25 rows/day, most-overdue observation first.
  R3 queued           ranked rows (priority_rank) first by rank, then unranked rows whose milestone is `active`
                      before the rest; slotted from today+1 at 20 rows/day.
  R4 blocked          today+7 (re-check the typed edge in `blocked_on`).
  roadmap             the row's own `roadmap`; else `docs/roadmap/backfill-2026-10-11.json` (row_fallback);
                      else the id-prefix map below (flagged); else `unmapped` + reason (flagged `roadmap_needs_review`).
  DROP (proposed only, each with its evidence; a dropped row needs a stated reason):
  D1 never touched since the reset: no `updated_at`, state queued, no lane.
  D2 note says `superseded by <ID>` and <ID> exists in the register.
  D3 queued in a `dormant`/`closed` milestone (milestones.yaml), no lane, no priority_rank, no open PR, untouched >= 14 days.
  Everything else is kept and dated -- a row we cannot show is stale is not proposed for drop.

Usage: checklist_backfill_propose.py --propose OUTDIR [--today YYYY-MM-DD]
       checklist_backfill_propose.py --apply FILE [--by SESSION]   (the manager, after review; idempotent)
       checklist_backfill_propose.py --apply-owner [--by SESSION]  (mechanical: owner=manager where null)
       checklist_backfill_propose.py --self-test
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.runtime.checklist_store import DEFAULT_OWNER, TERMINAL, _as_date, effective_due, load  # noqa: E402

LU_PER_DAY, Q_PER_DAY = 25, 20
PREFIX_MAP = (("PROP-", "L-PROP"), ("DESK-", "L-DESK"), ("DATA-", "L-DATA"), ("RESEARCH-OPS-", "L-OPS"))
SUPERSEDED = re.compile(r"superseded by ([A-Z][A-Za-z0-9._-]+)", re.I)


def _age(r: dict, today: date) -> int | None:
    u = r.get("updated_at")
    return (today - date.fromisoformat(u[:10])).days if u else None


def _resolve_roadmap(r: dict, fallback: dict) -> tuple[list[str], str]:
    own = r.get("roadmap")
    own = [own] if isinstance(own, str) else own
    if own:
        return list(own), "own field"
    if fallback.get(r["id"]):
        return [fallback[r["id"]]], "row_fallback (backfill-2026-10-11.json)"
    for pre, ms in PREFIX_MAP:
        if r["id"].startswith(pre):
            return [ms], f"id-prefix heuristic {pre}*"
    return ["unmapped"], "none found"


def propose(rows: list[dict], today: date, ms_status: dict, fallback: dict) -> list[dict]:
    ids = {r["id"]: r for r in rows}
    live = [r for r in rows if r.get("state") not in TERMINAL]
    out: dict[str, dict] = {}
    for r in live:
        rm, rm_basis = _resolve_roadmap(r, fallback)
        out[r["id"]] = {"id": r["id"], "state": r["state"], "title": str(r.get("title") or "")[:120],
                        "owner_now": r.get("owner"), "owner_proposed": r.get("owner") or DEFAULT_OWNER,
                        "due_now": (effective_due(r).isoformat() if effective_due(r) else None),
                        "roadmap_proposed": rm, "roadmap_basis": rm_basis,
                        "roadmap_needs_review": rm == ["unmapped"] or "heuristic" in rm_basis,
                        "age_days": _age(r, today), "action": "date", "due_by_proposed": None,
                        "due_basis": None, "drop_reason": None}
        if rm == ["unmapped"]:
            out[r["id"]]["roadmap_unmapped_reason"] = "no roadmap ref, no row_fallback entry, no id-prefix match: map to a milestone or confirm one-off"
    # ---- drops (D1-D3) ----
    for r in live:
        o, age = out[r["id"]], _age(r, today)
        why = None
        if r["state"] == "queued" and not r.get("lane") and age is None:
            why = "D1 never touched since the reset (no updated_at), queued, no lane"
        elif (m := SUPERSEDED.search(r.get("note") or "")) and m.group(1).rstrip(".,;)") in ids \
                and m.group(1).rstrip(".,;)") != r["id"]:
            why = f"D2 note says 'superseded by {m.group(1).rstrip('.,;)')}' ({ids[m.group(1).rstrip('.,;)')]['state']}); that row exists"
        elif r["state"] == "queued" and not r.get("lane") and r.get("priority_rank") is None and not r.get("prs") \
                and age is not None and age >= 14 and o["roadmap_proposed"] != ["unmapped"] \
                and all(ms_status.get(x) in ("dormant", "closed") for x in o["roadmap_proposed"]):
            why = (f"D3 queued, no lane/rank/PR, untouched {age}d, only in {'/'.join(o['roadmap_proposed'])} "
                   f"(milestone status {'/'.join(ms_status.get(x) for x in o['roadmap_proposed'])})")
        if why:
            o.update(action="drop", drop_reason=why, due_basis="proposed drop")
    # ---- dates (R1-R4) ----
    d1 = today + timedelta(days=1)
    todo = [o for o in out.values() if o["action"] == "date"]
    for o in todo:
        if o["state"] == "in_flight":
            o.update(due_by_proposed=(today + timedelta(days=2)).isoformat(), due_basis="R1 in_flight: confirm or re-date in 2 days")
        elif o["state"] == "blocked":
            o.update(due_by_proposed=(today + timedelta(days=7)).isoformat(), due_basis="R4 blocked: re-check blocked_on in 7 days")

    def slot(group: list[dict], per_day: int, basis: str) -> None:
        for i, o in enumerate(group):
            o.update(due_by_proposed=(d1 + timedelta(days=i // per_day)).isoformat(), due_basis=basis)
    lu = [o for o in todo if o["state"] == "landed_unproven"]
    keep = [o for o in lu if o["due_now"] and date.fromisoformat(o["due_now"]) >= today]
    for o in keep:
        o.update(due_by_proposed=o["due_now"], due_basis="R2 landed_unproven: its own observation date, still in the future")
    late = sorted((o for o in lu if o not in keep), key=lambda o: (o["due_now"] or "9999", o["id"]))
    slot(late, LU_PER_DAY, f"R2 landed_unproven: observation overdue/absent, slotted {LU_PER_DAY}/day from {d1}, most overdue first")
    byid = {r["id"]: r for r in live}
    q = [o for o in todo if o["state"] == "queued"]

    def qkey(o):
        rk = byid[o["id"]].get("priority_rank")
        act = any(ms_status.get(x) == "active" for x in o["roadmap_proposed"])
        return (0 if rk is not None else 1, rk if rk is not None else 0, 0 if act else 1, o["id"])
    slot(sorted(q, key=qkey), Q_PER_DAY, f"R3 queued: ranked, then active-milestone, slotted {Q_PER_DAY}/day from {d1}")
    return sorted(out.values(), key=lambda o: (o["action"], o["due_by_proposed"] or "9999", o["id"]))


def summary(props: list[dict], today: date) -> str:
    L = [f"# Checklist backfill proposal ({today}) -- PROPOSAL ONLY, nothing dated or dropped", "",
         f"Population: {len(props)} non-terminal rows (state not done/dropped) in docs/claude/work/checklist/ on {today}. "
         "Rules R1-R4 / D1-D3: `scripts/ops/checklist_backfill_propose.py` docstring. File: `proposal.jsonl`.", ""]
    c = collections.Counter(p["action"] for p in props)
    L += [f"- propose DATE: {c['date']}  |  propose DROP: {c['drop']}",
          f"- owner null today -> `manager` (mechanical): {sum(1 for p in props if not p['owner_now'])}",
          f"- roadmap needs review (unmapped or id-prefix heuristic): {sum(1 for p in props if p['roadmap_needs_review'])}",
          f"- already overdue under their legacy date (observation.due_by < {today}): "
          f"{sum(1 for p in props if p['due_now'] and p['due_now'] < today.isoformat())}",
          f"- no date at all today: {sum(1 for p in props if not p['due_now'])}", "", "## By state",
          "| state | rows | date | drop | first due | last due |", "|---|---|---|---|---|---|"]
    for st in sorted({p["state"] for p in props}):
        g = [p for p in props if p["state"] == st]
        ds = sorted(p["due_by_proposed"] for p in g if p["due_by_proposed"])
        L.append(f"| {st} | {len(g)} | {sum(p['action']=='date' for p in g)} | {sum(p['action']=='drop' for p in g)} | "
                 f"{ds[0] if ds else '—'} | {ds[-1] if ds else '—'} |")
    L += ["", "## By milestone (a row counts once per milestone it resolves to)", "| milestone | rows | drop | latest proposed due |", "|---|---|---|---|"]
    bym = collections.defaultdict(list)
    for p in props:
        for m in p["roadmap_proposed"]:
            bym[m].append(p)
    for m in sorted(bym, key=lambda k: -len(bym[k])):
        g = bym[m]
        ds = sorted(p["due_by_proposed"] for p in g if p["due_by_proposed"])
        L.append(f"| {m} | {len(g)} | {sum(p['action']=='drop' for p in g)} | {ds[-1] if ds else '—'} |")
    L += ["", "## Proposed drops (each needs the manager's yes; reason is the evidence)"]
    L += [f"- **{p['id']}** [{p['state']}] -- {p['drop_reason']} -- {p['title']}" for p in props if p["action"] == "drop"] or ["- none"]
    L += ["", "## Daily load of the proposed schedule (rows per due date, first 16 days)"]
    load_ = collections.Counter(p["due_by_proposed"] for p in props if p["due_by_proposed"])
    L += [f"- {d}: {n}" for d, n in sorted(load_.items())[:16]]
    return "\n".join(L) + "\n"


def _ms_status() -> dict:
    import yaml  # noqa: PLC0415
    spec = yaml.safe_load((REPO / "docs/roadmap/milestones.yaml").read_text(encoding="utf-8"))
    return {m["id"]: m["status"] for m in spec["milestones"]}


def _fallback() -> dict:
    f = REPO / "docs/roadmap/backfill-2026-10-11.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _apply(lines: list[dict], by: str | None, owner_only: bool) -> int:
    sys.path.insert(0, str(REPO / "scripts" / "ops"))
    import checklist as ck  # noqa: PLC0415
    n = 0
    for p in lines:
        row = ck._store.read_row(p["id"], REPO)
        if row is None or row.get("state") in TERMINAL:
            continue
        f: dict = {}
        if not row.get("owner"):
            f["owner"] = DEFAULT_OWNER
        if not owner_only:
            if p["action"] == "drop":
                f.update(state="dropped", closed_reason=p["drop_reason"])
            else:
                if _as_date(row.get("due_by")) is None and p.get("due_by_proposed"):
                    f["due_by"] = p["due_by_proposed"]
                if not row.get("roadmap"):
                    f["roadmap"] = p["roadmap_proposed"]
                    if p["roadmap_proposed"] == ["unmapped"]:
                        f["roadmap_unmapped_reason"] = p.get("roadmap_unmapped_reason")
        if f:
            new = dict(row, **f)
            if not owner_only and new.get("state") not in TERMINAL and (why := ck.filing_problems(new)):
                print(f"backfill: SKIPPED {p['id']}: {'; '.join(why)}")
                continue
            ck._commit_row(new, REPO, ck._require_seeded(REPO), by)  # owner-only writes are legal on a not-yet-dated legacy row
            n += 1
    print(f"backfill: wrote {n} row(s)")
    return 0


def _self_test() -> int:
    ok = True

    def c(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    t = date(2026, 11, 1)
    rows = [{"id": "F", "state": "in_flight", "updated_at": "2026-10-31T00:00:00Z", "roadmap": ["L-OPS"]},
            {"id": "U1", "state": "landed_unproven", "updated_at": "2026-10-31T00:00:00Z", "roadmap": ["L-OPS"], "observation": {"due_by": "2026-11-09T00:00Z"}},
            {"id": "U2", "state": "landed_unproven", "updated_at": "2026-10-31T00:00:00Z", "roadmap": ["L-OPS"], "observation": {"due_by": "2026-10-01"}},
            {"id": "Q1", "state": "queued", "updated_at": "2026-10-31T00:00:00Z", "priority_rank": 1, "roadmap": ["L-OPS"]},
            {"id": "Q2", "state": "queued", "updated_at": "2026-10-31T00:00:00Z", "roadmap": ["M29"]},
            {"id": "OLD", "state": "queued", "roadmap": ["L-OPS"]},
            {"id": "SUP", "state": "queued", "updated_at": "2026-10-31T00:00:00Z", "note": "superseded by Q1", "roadmap": ["L-OPS"]},
            {"id": "STALE", "state": "queued", "updated_at": "2026-10-01T00:00:00Z", "roadmap": ["M29"]},
            {"id": "NOMAP", "state": "queued", "updated_at": "2026-10-31T00:00:00Z"},
            {"id": "DONE", "state": "done"}]
    ps = {p["id"]: p for p in propose(rows, t, {"L-OPS": "active", "M29": "dormant"}, {})}
    c("terminal rows are not in the population", "DONE" not in ps)
    c("R1 in_flight = today+2", ps["F"]["due_by_proposed"] == "2026-11-03")
    c("R2 future observation date is kept", ps["U1"]["due_by_proposed"] == "2026-11-09")
    c("R2 overdue observation is re-slotted from tomorrow", ps["U2"]["due_by_proposed"] == "2026-11-02")
    c("R3 ranked queued before unranked", ps["Q1"]["due_by_proposed"] <= ps["Q2"]["due_by_proposed"])
    c("D1 never-touched queued row -> drop", ps["OLD"]["action"] == "drop" and ps["OLD"]["drop_reason"].startswith("D1"))
    c("D2 superseded-by an existing row -> drop", ps["SUP"]["action"] == "drop" and ps["SUP"]["drop_reason"].startswith("D2"))
    c("D3 stale in a dormant milestone -> drop", ps["STALE"]["action"] == "drop" and ps["STALE"]["drop_reason"].startswith("D3"))
    c("a fresh row in a dormant milestone is KEPT", ps["Q2"]["action"] == "date")
    c("no ref anywhere -> unmapped + flagged", ps["NOMAP"]["roadmap_proposed"] == ["unmapped"] and ps["NOMAP"]["roadmap_needs_review"])
    c("every non-drop row gets a date", all(p["due_by_proposed"] for p in ps.values() if p["action"] == "date"))
    c("owner null -> manager", ps["F"]["owner_proposed"] == "manager")
    print("checklist-backfill-propose self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--propose", metavar="OUTDIR")
    ap.add_argument("--apply", metavar="FILE")
    ap.add_argument("--apply-owner", action="store_true")
    ap.add_argument("--today")
    ap.add_argument("--by")
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).date()
    if a.self_test:
        return _self_test()
    if a.propose:
        props = propose(load()["items"], today, _ms_status(), _fallback())
        out = Path(a.propose)
        out.mkdir(parents=True, exist_ok=True)
        (out / "proposal.jsonl").write_text("".join(json.dumps(p, sort_keys=True) + "\n" for p in props), encoding="utf-8")
        (out / "summary.md").write_text(summary(props, today), encoding="utf-8")
        print(f"wrote {len(props)} proposals -> {out}")
        return 0
    if a.apply or a.apply_owner:
        lines = [json.loads(x) for x in Path(a.apply).read_text(encoding="utf-8").splitlines() if x.strip()] if a.apply \
            else [{"id": r["id"], "action": "date"} for r in load()["items"] if r.get("state") not in TERMINAL]
        return _apply(lines, a.by, owner_only=bool(a.apply_owner))
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
