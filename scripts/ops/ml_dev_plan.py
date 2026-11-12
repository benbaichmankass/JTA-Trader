#!/usr/bin/env python3
# wiring: manual-only - the plan reader is run on demand (operator Plans page payload via --json, the weekly /ml-review plan loop); tests/test_ml_dev_plan.py runs its self-test.
"""ml_dev_plan -- reader + checker for THE ITERATIVE ML DEV PLAN (docs/plans/ml-dev-plan.yaml).

WHY. The operator asked (2026-11-12, row ML-DEV-PLAN) for the full iterative ML dev plan, "visibile to so i can
monitor/track/edit". The plan file is the edit surface; this script is the read surface: it validates the file, resolves every
line's work-store row and every research/queue unit it names, and prints one line per plan line (or --json for the operator's
Plans page). It is the sibling of scripts/ops/ml_plan_status.py (which still checks docs/plans/ml-plan-items.yaml and is
being moved to the work store by PR #25268); it reads rows the SAME way that PR does, and it flags any open ml-plan-items.yaml
item that no dev-plan line absorbs, so the two files cannot drift apart silently.

FLAGS (report-only; nothing here gates anything -- CLAUDE.md "No new gates"):
  SCHEMA        a line misses a required field, uses a stage outside the one-ladder vocabulary, or has an exhaustion
                condition phrased as an attempt count
  ORPHAN-ROW    the line's `row` does not exist in the work store
  ORPHAN-CARRIER  a `carried_by` row does not exist in the work store
  ROW-CLOSED    the row is done/dropped/killed while the line is still live (stage not retired/failed and no proposed_disposition)
  STALE         the row has not moved in `review_days`
  UNIT-MISSING  an RQ-... ref is not on this checkout (it may sit on an open PR; the line says which) -- info, not a finding
  UNABSORBED    an ml-plan-items.yaml item no dev-plan line lists in `plan_items`
  NO-CONSUMER   info: a model line whose consumer class is none (said plainly; never a finding)

EXIT CODES. 0 clean, 1 findings, 2 COULD NOT LOOK (work store unreachable) -- never 0 when nothing was checked.
Read-only. --validate needs no network (CI-safe).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PLAN = REPO / "docs/plans/ml-dev-plan.yaml"
ITEMS = REPO / "docs/plans/ml-plan-items.yaml"
# The one-ladder / RD-REGISTRY stage vocabulary (src/runtime/rd_registry.py STAGES, PR #25313). Kept as a literal so this
# reader does not depend on that PR landing first; tests/test_ml_dev_plan.py pins it to the module when the module exists.
STAGES = ("idea", "queued", "testing_offline", "failed", "iterating", "passed_waiting", "testing_book", "production",
          "shadow_advisory", "retired", "stuck")
KINDS = ("model", "idea", "slot", "infra")
CONSUMER = ("real_money", "prop", "paper", "none")
SLOTS = tuple(f"D{i}" for i in range(1, 11)) + ("-",)
REQUIRED = ("id", "slot", "track", "kind", "subject", "consumer", "stage", "row", "state", "levers_tried", "levers_ahead",
            "next_weeks", "exhaustion", "owner", "plan_items")
LEVER_REQUIRED = ("lever", "ref", "baseline", "pass", "fail")
CLOSED_ROW = {"done", "dropped", "killed", "retired", "archived", "closed", "cancelled", "superseded"}
TERMINAL_STAGE = {"retired", "failed"}
# "never an attempt count" (programme-review skill, ITERATION LOOP): refuse "after 3 attempts", "5 tries", "N iterations"
ATTEMPT_COUNT = re.compile(r"\b(after\s+)?(\d+|n|N)\s+(attempts?|tries|retries|iterations|more\s+arms)\b", re.IGNORECASE)
RQ = re.compile(r"RQ-\d{8}-[0-9a-z]{4}-\d{2}|RQ-\d{8}-\d{3}")
ID = re.compile(r"^MLP-[A-Z0-9]+(-[A-Z0-9]+)*$")


class RowsUnreadable(Exception):
    """The work store could not be read (never read as "no rows")."""


def load(path: Path = PLAN) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def plan_item_ids(path: Path = ITEMS) -> dict:
    try:
        d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    return {str(i["id"]): i for i in d.get("items") or [] if isinstance(i, dict) and i.get("id")}


def validate(plan: dict, items: dict | None = None) -> list[str]:
    """Schema problems, one string each. Pure; no network."""
    out: list[str] = []
    if not isinstance(plan, dict) or not isinstance(plan.get("lines"), list):
        return ["SCHEMA plan: no `lines` list"]
    weeks = set((plan.get("weeks") or {}).keys())
    seen: set[str] = set()
    for ln in plan["lines"]:
        lid = str(ln.get("id", "?"))
        miss = [k for k in REQUIRED if k not in ln]
        if miss:
            out.append(f"SCHEMA {lid}: missing {','.join(miss)}")
        if not ID.match(lid):
            out.append(f"SCHEMA {lid}: id must look like MLP-<SLOT|TRACK>-<NAME>")
        if lid in seen:
            out.append(f"SCHEMA {lid}: duplicate id")
        seen.add(lid)
        if ln.get("slot") not in SLOTS:
            out.append(f"SCHEMA {lid}: slot {ln.get('slot')!r} not in D1..D10 or '-'")
        if ln.get("kind") not in KINDS:
            out.append(f"SCHEMA {lid}: kind {ln.get('kind')!r} not in {KINDS}")
        if ln.get("stage") not in STAGES:
            out.append(f"SCHEMA {lid}: stage {ln.get('stage')!r} not in the one-ladder vocabulary {STAGES}")
        cons = ln.get("consumer") or {}
        if not isinstance(cons, dict) or cons.get("class") not in CONSUMER:
            out.append(f"SCHEMA {lid}: consumer.class must be one of {CONSUMER} (say `none` plainly)")
        st = ln.get("state") or {}
        if not isinstance(st, dict) or not str(st.get("summary") or "").strip():
            out.append(f"SCHEMA {lid}: state.summary empty")
        for ev in (st.get("evidence") or []) if isinstance(st, dict) else []:
            if ev.get("provenance") not in ("MEASURED", "QUOTED", "ESTIMATED", "UNVERIFIED"):
                out.append(f"SCHEMA {lid}: evidence {ev.get('record')!r} has no MEASURED/QUOTED/ESTIMATED/UNVERIFIED provenance")
        for lv in ln.get("levers_ahead") or []:
            lm = [k for k in LEVER_REQUIRED if not str(lv.get(k) or "").strip()]
            if lm:
                out.append(f"SCHEMA {lid}: lever {str(lv.get('lever'))[:40]!r} missing {','.join(lm)}")
        exh = str(ln.get("exhaustion") or "")
        if not exh.strip():
            out.append(f"SCHEMA {lid}: exhaustion empty")
        elif ATTEMPT_COUNT.search(exh):
            out.append(f"SCHEMA {lid}: exhaustion reads as an attempt count ({ATTEMPT_COUNT.search(exh).group(0)!r})")
        nw = ln.get("next_weeks") or {}
        if not isinstance(nw, dict) or (weeks and not set(nw) <= weeks):
            out.append(f"SCHEMA {lid}: next_weeks keys must be among {sorted(weeks)}")
        if items is not None:
            for pid in ln.get("plan_items") or []:
                if pid not in items:
                    out.append(f"SCHEMA {lid}: plan_items names {pid}, which is not in ml-plan-items.yaml")
    return out


def _store_rows() -> list[dict]:
    """Every row as the WORK STORE holds it, or raise. Same read path as ml_plan_status.py after PR #25268: the local
    work_store.db on the VM, else the live API through scripts/ops/work.py (stdlib only)."""
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "scripts/ops"))
    from src.runtime import work_read

    local = work_read.local_store()
    if local is not None:
        return local.list_items(limit=10 ** 7)
    import work  # scripts/ops/work.py

    return work._all_items(None)


def rows(fetch=None) -> dict:
    try:
        items = fetch() if fetch else _store_rows()
    except Exception as e:  # every failure is "could not look", not "empty"
        raise RowsUnreadable(f"{type(e).__name__}: {e}") from e
    return {r["id"]: r for r in items if isinstance(r, dict) and r.get("id")}


def unit_state(rq: str, repo: Path = REPO):
    for sub in ("", "blocked/"):
        p = repo / "research/queue" / f"{sub}{rq}.yaml"
        if p.exists():
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            g = d.get("grading") or {}
            return {"status": d.get("status") or ("blocked" if sub else "queued"), "verdict": g.get("verdict")}
    if (repo / "research/results" / rq).exists():
        return {"status": "done", "verdict": None}
    return None


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def analyse(plan: dict, rowmap: dict, items: dict, repo: Path = REPO, now=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    lim = int(plan.get("review_days", 7))
    out = []
    absorbed = set()
    for ln in plan["lines"]:
        absorbed |= set(ln.get("plan_items") or [])
        r = rowmap.get(ln["row"])
        flags, info = [], []
        rstate = r.get("state") if r else None
        if r is None:
            flags.append("ORPHAN-ROW")
        else:
            live = ln["stage"] not in TERMINAL_STAGE and not ln.get("proposed_disposition")
            if rstate in CLOSED_ROW and live:
                flags.append("ROW-CLOSED")
            upd = _parse(r.get("updated_at"))
            if upd and (now - upd).days >= lim and rstate not in CLOSED_ROW:
                flags.append("STALE")
        carriers = {}
        for c in ln.get("carried_by") or []:
            cr = rowmap.get(c)
            carriers[c] = cr.get("state") if cr else None
            if cr is None:
                flags.append(f"ORPHAN-CARRIER:{c}")
        refs = sorted({m for lv in (ln.get("levers_ahead") or []) for m in RQ.findall(str(lv.get("ref")))})
        units = {}
        for u in refs:
            s = unit_state(u, repo)
            units[u] = s
            if s is None:
                info.append(f"UNIT-MISSING:{u}")
        if (ln.get("consumer") or {}).get("class") == "none" and ln["kind"] == "model":
            info.append("NO-CONSUMER")
        out.append({
            "id": ln["id"], "slot": ln["slot"], "track": ln["track"], "kind": ln["kind"], "subject": ln["subject"],
            "consumer": ln["consumer"], "stage": ln["stage"], "row": ln["row"], "row_state": rstate,
            "row_updated_at": r.get("updated_at") if r else None, "carried_by": carriers, "owner": ln["owner"],
            "summary": ln["state"].get("summary"), "evidence": ln["state"].get("evidence") or [],
            "levers_tried": ln.get("levers_tried") or [], "levers_ahead": ln.get("levers_ahead") or [], "units": units,
            "next_weeks": ln.get("next_weeks") or {}, "exhaustion": ln["exhaustion"],
            "proposed_disposition": ln.get("proposed_disposition"), "flags": flags, "info": info,
        })
    for iid, it in items.items():
        if iid not in absorbed and str(it.get("state")) in ("open", "parked"):
            out.append({"id": iid, "slot": None, "track": it.get("track"), "kind": "unabsorbed_plan_item", "stage": None,
                        "row": it.get("ref"), "row_state": None, "flags": ["UNABSORBED"], "info": [],
                        "summary": it.get("title")})
    return out


def render_json(plan: dict, res: list[dict], read_state: str) -> dict:
    by_stage, by_slot = {}, {}
    for r in res:
        if r.get("stage"):
            by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + 1
        if r.get("slot"):
            by_slot[r["slot"]] = by_slot.get(r["slot"], 0) + 1
    return {
        "schema": 1, "source": "docs/plans/ml-dev-plan.yaml", "updated": plan.get("updated"), "read_state": read_state,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "weeks": plan.get("weeks"),
        "population": {"lines": len(plan["lines"]), "by_stage": by_stage, "by_slot": by_slot},
        "graded_today": plan.get("graded_today") or [], "labelled_gates_not_planned": plan.get("labelled_gates_not_planned") or [],
        "lines": res,
    }


def self_test() -> int:
    good = {
        "weeks": {"W47": "2026-11-16"}, "review_days": 7,
        "lines": [{
            "id": "MLP-D3-OK", "slot": "D3", "track": "S", "kind": "model", "subject": "m", "consumer": {"class": "real_money"},
            "stage": "production", "row": "ROW-OK", "state": {"summary": "s", "evidence": [{"record": "r", "provenance": "MEASURED"}]},
            "levers_tried": [], "levers_ahead": [{"lever": "l", "ref": "RQ-20990101-abcd-01", "baseline": "b", "pass": "p", "fail": "f"}],
            "next_weeks": {"W47": "x"}, "exhaustion": "the declared read fires and no lever passes", "owner": "AM-ML", "plan_items": ["ML-A"],
        }],
    }
    items = {"ML-A": {"id": "ML-A", "state": "open"}, "ML-B": {"id": "ML-B", "state": "open", "title": "t", "track": "R"}}
    assert validate(good, items) == [], validate(good, items)
    bad = json.loads(json.dumps(good))
    ln = bad["lines"][0]
    ln.update(stage="advisory", exhaustion="retire after 3 attempts", consumer={"class": "maybe"}, next_weeks={"W99": "x"})
    ln["levers_ahead"][0]["baseline"] = ""
    ln["state"]["evidence"][0]["provenance"] = "VIBES"
    ln["plan_items"] = ["ML-NOPE"]
    probs = validate(bad, items)
    for needle in ("stage 'advisory'", "attempt count", "consumer.class", "next_weeks", "missing baseline", "provenance", "ML-NOPE"):
        assert any(needle in p for p in probs), (needle, probs)
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    rowmap = {"ROW-OK": {"id": "ROW-OK", "state": "in_flight", "updated_at": "2026-11-12T00:00:00Z"}}
    res = analyse(good, rowmap, items, now=now)
    assert res[0]["flags"] == [] and "UNIT-MISSING:RQ-20990101-abcd-01" in res[0]["info"], res[0]
    assert any(r["id"] == "ML-B" and r["flags"] == ["UNABSORBED"] for r in res), res
    res2 = analyse(good, {"ROW-OK": {"id": "ROW-OK", "state": "done", "updated_at": "2026-10-01T00:00:00Z"}}, items, now=now)
    assert res2[0]["flags"] == ["ROW-CLOSED"], res2[0]
    res3 = analyse(good, {}, items, now=now)
    assert res3[0]["flags"] == ["ORPHAN-ROW"], res3[0]
    g2 = json.loads(json.dumps(good))
    g2["lines"][0]["carried_by"] = ["ROW-GONE"]
    assert analyse(g2, rowmap, items, now=now)[0]["flags"] == ["ORPHAN-CARRIER:ROW-GONE"]
    res4 = analyse(good, {"ROW-OK": {"id": "ROW-OK", "state": "queued", "updated_at": "2026-10-01T00:00:00Z"}}, items, now=now)
    assert res4[0]["flags"] == ["STALE"], res4[0]

    def down():
        raise OSError("store down")

    try:
        rows(fetch=down)
    except RowsUnreadable:
        pass
    else:
        raise AssertionError("an unreachable store read as empty")
    print("ml_dev_plan self-test: OK (7 of 7 planted schema faults and 5 of 5 planted flags (ORPHAN-ROW, ORPHAN-CARRIER, ROW-CLOSED, STALE, UNABSORBED) detected; the 1 unfaulted line produced 0 flags)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validate", action="store_true", help="schema check only (no network)")
    ap.add_argument("--json", action="store_true", help="the payload the operator's Plans page renders")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--plan", default=str(PLAN))
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    plan = load(Path(a.plan))
    items = plan_item_ids()
    probs = validate(plan, items)
    if a.validate:
        for p in probs:
            print(p)
        print(f"ml_dev_plan --validate: {len(plan.get('lines') or [])} lines, {len(probs)} schema problem(s)")
        return 1 if probs else 0
    try:
        rowmap = rows()
    except RowsUnreadable as e:
        print(f"COULD NOT LOOK work store: {e}", file=sys.stderr)
        if a.json:
            print(json.dumps({"read_state": "could_not_look", "reason": str(e), "source": "docs/plans/ml-dev-plan.yaml"}))
        return 2
    res = analyse(plan, rowmap, items)
    nflag = sum(1 for r in res if r["flags"]) + len(probs)
    if a.json:
        payload = render_json(plan, res, "read")
        payload["schema_problems"] = probs
        print(json.dumps(payload, indent=1, default=str))
    else:
        for p in probs:
            print(p)
        print(f"{'id':32} {'slot':4} {'stage':16} {'consumer':10} {'row':34} {'row_state':16} flags / info")
        for r in res:
            cons = (r.get("consumer") or {}).get("class") if isinstance(r.get("consumer"), dict) else None
            print(f"{r['id'][:32]:32} {r.get('slot') or '—'!s:4} {r.get('stage') or '—'!s:16} {cons or '—'!s:10} "
                  f"{str(r.get('row') or '—')[:34]:34} {r.get('row_state') or '—'!s:16} "
                  f"{' '.join(r['flags'] + r['info']) or 'ok'}")
        print(f"\n{len(plan['lines'])} plan lines; {nflag} with findings (report-only; nothing gates on this).")
    return 1 if nflag else 0


if __name__ == "__main__":
    sys.exit(main())
