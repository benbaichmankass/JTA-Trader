"""The backtest / research run log (UI-BACKTEST-LOG-GAPS; operator spec 2026-11-09 S&M: "Backtesting = a log
of every test run, its result and what we did with it").

Pure projection over two things already on the tree: the research catalog's units
(``src/runtime/research_catalog.py``, one per ``research/queue`` unit with its verdict) and the unit files' own
link fields. **"What we did" is computed from links the units already carry, never typed by hand here:**

- ``iteration``: a later unit whose ``iteration.from_result`` names this unit (an iteration authored from it).
- ``depends_on_result``: a later unit whose ``requires_result.unit`` is this unit (work gated on this result).
- ``confirmation``: this unit's ``grading.confirm_unit``, or a unit whose ``grading.confirms`` is this unit.
- ``disposition``: this unit's ``grading.disposition`` (prose, labelled as prose).
- ``retired``: this unit's ``retired_reason`` (prose).

``what_we_did.state`` is ``acted`` (at least one follow-up unit), ``recorded`` (only a disposition / retirement
note) or ``none_recorded``. ``none_recorded`` is a finding about the record, NOT a claim that nobody acted: an
action taken outside the queue (a config PR, a checklist row) leaves no link this projection can read.

Gates this adds or changes: none.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

RQ_RE = re.compile(r"RQ-\d{8}-[0-9A-Za-z]{3,4}-\d{2}|RQ-\d{8}-\d{3}")
WHAT_STATES = ("acted", "recorded", "none_recorded")


def _ids(v: Any) -> list[str]:
    return RQ_RE.findall(v) if isinstance(v, str) else []


def follow_up_index(docs: dict[str, dict]) -> dict[str, list[dict[str, str]]]:
    """unit id -> [{id, relation}] of units that act on its result. Built from every unit file's links."""
    out: dict[str, list[dict[str, str]]] = {}

    def add(target: str, uid: str, relation: str) -> None:
        if target == uid:
            return
        lst = out.setdefault(target, [])
        if not any(x["id"] == uid and x["relation"] == relation for x in lst):
            lst.append({"id": uid, "relation": relation})

    for uid, d in docs.items():
        it = d.get("iteration") if isinstance(d.get("iteration"), dict) else {}
        for t in _ids(it.get("from_result")):
            add(t, uid, "iteration")
        rr = d.get("requires_result")
        for r in (rr if isinstance(rr, list) else [rr]):
            if isinstance(r, dict):
                for t in _ids(r.get("unit")):
                    add(t, uid, "depends_on_result")
        g = d.get("grading") if isinstance(d.get("grading"), dict) else {}
        for t in _ids(g.get("confirm_unit")):
            add(uid, t, "confirmation")
        for t in _ids(g.get("confirms")):
            add(t, uid, "confirmation")
    return out


def _what_we_did(uid: str, doc: dict, follow: dict[str, list[dict[str, str]]],
                 units: dict[str, dict]) -> dict[str, Any]:
    g = doc.get("grading") if isinstance(doc.get("grading"), dict) else {}
    ups = []
    for f in follow.get(uid, []):
        u = units.get(f["id"]) or {}
        ups.append({**f, "status": u.get("status"), "verdict": u.get("verdict"), "title": u.get("title")})
    disp = g.get("disposition") if isinstance(g.get("disposition"), str) else None
    retired = doc.get("retired_reason") if isinstance(doc.get("retired_reason"), str) else None
    state = "acted" if ups else ("recorded" if (disp or retired) else "none_recorded")
    return {"state": state, "follow_ups": ups, "disposition": disp, "retired_reason": retired}


def build_runs(units: Iterable[dict], docs: dict[str, dict]) -> list[dict[str, Any]]:
    """One row per unit that carries a verdict (a run that produced a result), newest first by the later of
    ``graded_at`` and the catalog's ``lastActivity``."""
    by_id = {u["id"]: u for u in units}
    follow = follow_up_index(docs)
    rows = []
    for uid, u in by_id.items():
        if not u.get("verdict"):
            continue
        doc = docs.get(uid) or {}
        g = doc.get("grading") if isinstance(doc.get("grading"), dict) else {}
        graded_at = g.get("graded_at")
        rows.append({
            "id": uid, "title": u.get("title"), "theme": u.get("theme"), "kind": u.get("kind"),
            "status": u.get("status"), "verdict": u.get("verdict"), "read_state": u.get("readState"),
            "graded_at": str(graded_at) if graded_at is not None else None,
            "last_activity": u.get("lastActivity"),
            "rule_id": (u.get("rule") or {}).get("id"),
            "result_note": u.get("resultNote"),
            "what_we_did": _what_we_did(uid, doc, follow, by_id),
        })
    rows.sort(key=lambda r: (max(r["graded_at"] or "", r["last_activity"] or ""), r["id"]), reverse=True)
    return rows


def query_runs(rows: list[dict], *, verdict: list[str], what: list[str], q: str, since: str | None,
               limit: int, offset: int) -> dict[str, Any]:
    terms = [t for t in q.lower().split() if t]

    def keep(r: dict) -> bool:
        if verdict and str(r["verdict"]) not in verdict:
            return False
        if what and r["what_we_did"]["state"] not in what:
            return False
        if since and not max(r["graded_at"] or "", r["last_activity"] or "") >= since:
            return False
        hay = f"{r['id']} {r['title']} {r['theme']} {r['result_note']}".lower()
        return all(t in hay for t in terms)

    hit = [r for r in rows if keep(r)]
    by_verdict: dict[str, int] = {}
    by_what = {s: 0 for s in WHAT_STATES}
    for r in rows:
        by_verdict[str(r["verdict"])] = by_verdict.get(str(r["verdict"]), 0) + 1
        by_what[r["what_we_did"]["state"]] += 1
    return {"total": len(rows), "matched": len(hit), "runs": hit[offset:offset + limit],
            "counts": {"by_verdict": by_verdict, "by_what_we_did": by_what}}
