"""Tier-1 read endpoint: the INSIGHTS LEDGER (INSIGHTS-LEDGER).

``GET /api/bot/work/ledger?topic=&subtopic=&outcome=&roadmap=`` -> the pipeline items that carry ``kind: "insight"``
(``scripts/ops/pipeline.py`` validates them), each with its typed links resolved to LIVE state:

* ``row``  -> the checklist/work-store row's state + title (``checklist_store.load``);
* ``unit`` -> ``research/queue/<id>.yaml`` exists or not;
* ``pr``   -> not resolved (a PR's state is GitHub's; ``state: null``, ``read_state: "not_checked"``).

A link that does not resolve is reported ``dangling`` -- visible here, not a CI gate (adding a gate needs the operator's
permission). An insight with no ``topic`` groups under ``Unmapped`` (visible, so the gap is a to-do). Not a new store:
this is a filter over ``docs/claude/work/pipeline/``. GET only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from src.utils.paths import repo_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/work", tags=["work"])

UNMAPPED = "Unmapped"
_FIELDS = ("id", "claim", "population", "provenance", "evidence", "topic", "subtopic", "roadmap", "outcome",
           "state", "terminal_reason", "what")


def _resolve_links(links: List[Dict[str, str]], rows: Optional[Dict[str, Dict[str, Any]]], root: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for lk in links:
        t, i = lk.get("type"), lk.get("id")
        d: Dict[str, Any] = {"type": t, "id": i, "state": None, "title": None, "read_state": "not_checked"}
        if t == "row":
            if rows is None:
                d["read_state"] = "rows_unreadable"
            elif i in rows:
                d.update(state=rows[i].get("state"), title=rows[i].get("title"), read_state="resolved")
            else:
                d["read_state"] = "dangling"
        elif t == "unit":
            d["read_state"] = "resolved" if (root / "research" / "queue" / f"{i}.yaml").exists() else "dangling"
        out.append(d)
    return out


@router.get("/ledger")
def get_ledger(topic: Optional[str] = None, subtopic: Optional[str] = None, outcome: Optional[str] = None,
               roadmap: Optional[str] = None) -> Dict[str, Any]:
    from scripts.ops import pipeline
    from src.runtime import checklist_store
    root = Path(repo_root())
    as_of = datetime.now(timezone.utc).isoformat()
    try:
        res = pipeline.read_log(root / pipeline.STORE)
    except Exception:  # noqa: BLE001  # allow-silent: an unreadable store is a stated read_state, not a 5xx
        logger.warning("work/ledger: pipeline store unreadable", exc_info=True)
        return {"as_of": as_of, "read_state": "store_unreadable", "insights": [], "by_topic": [], "population": None}
    try:
        rows: Optional[Dict[str, Dict[str, Any]]] = {r["id"]: r for r in checklist_store.load(root).get("items", [])
                                                     if isinstance(r, dict) and r.get("id")}
    except Exception:  # noqa: BLE001  # allow-silent: rows unreadable -> links say rows_unreadable, never "dangling"
        logger.warning("work/ledger: checklist rows unreadable", exc_info=True)
        rows = None
    every = [it for it in res.items.values() if it.get("kind") == "insight"]
    want = {"topic": topic, "subtopic": subtopic, "outcome": outcome, "roadmap": roadmap}

    def keep(it: Dict[str, Any]) -> bool:
        for k, v in want.items():
            if v is None:
                continue
            have = it.get(k)
            if k == "topic" and have is None:
                have = UNMAPPED
            if have != v:
                return False
        return True

    shown = [it for it in every if keep(it)]
    insights = []
    for it in sorted(shown, key=lambda x: str(x.get("id"))):
        d = {k: it.get(k) for k in _FIELDS}
        d["topic"] = it.get("topic") or UNMAPPED
        d["links"] = _resolve_links(it.get("links") or [], rows, root)
        d["n_dangling"] = sum(1 for lk in d["links"] if lk["read_state"] == "dangling")
        insights.append(d)
    by_topic: Dict[str, int] = {}
    for d in insights:
        by_topic[d["topic"]] = by_topic.get(d["topic"], 0) + 1
    return {"as_of": as_of, "read_state": "partial" if res.unreadable else "measured",
            "n_unreadable_records": len(res.unreadable), "insights": insights,
            "by_topic": [{"topic": t, "n": n} for t, n in sorted(by_topic.items())],
            "population": {"source": "docs/claude/work/pipeline (kind=insight, latest record per id)",
                           "n_insights_total": len(every), "n_shown": len(insights),
                           "filters": {k: v for k, v in want.items() if v is not None},
                           "link_states": "row -> work store, unit -> research/queue file, pr -> not checked"}}
