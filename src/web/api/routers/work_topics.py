"""Tier-1 read endpoint: work TOPICS (WORK-TOPIC-TAXONOMY, backend half).

``GET /api/bot/work/topics`` -> the milestone -> topic/subtopic map (``docs/roadmap/topics.yaml``) applied to every checklist
row's ``roadmap`` ref, as an ``id -> {topic, subtopic}`` index the SPA joins to the work queue by row id (topic chips, group-by,
filter), plus per-topic counts. Topic is COMPUTED, never typed on a row. A row whose roadmap refs name no mapped milestone (none,
``unmapped``, or an id missing from the map) reads ``Unmapped`` -- visible, counted, with the offending refs listed.

A row with several milestones takes the FIRST one that maps (its refs are ordered by the filer). Research queue units and pipeline
items carry the same ``roadmap`` ref but are NOT indexed here yet (reading hundreds of unit files per request is its own decision).
Informs grouping only; authorizes nothing. GET only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from fastapi import APIRouter

from src.utils.paths import repo_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/work", tags=["work"])

UNMAPPED = "Unmapped"
TERMINAL = ("done", "dropped")


def load_topic_map(root: Path) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    """-> ({milestone_id: {topic, subtopic}}, all milestone ids in milestones.yaml). Raises on an unreadable file."""
    topics = (yaml.safe_load((root / "docs/roadmap/topics.yaml").read_text(encoding="utf-8")) or {}).get("topics") or {}
    ms = (yaml.safe_load((root / "docs/roadmap/milestones.yaml").read_text(encoding="utf-8")) or {}).get("milestones") or []
    return ({str(k): {"topic": str(v["topic"]), "subtopic": str(v.get("subtopic") or "")}
             for k, v in topics.items() if isinstance(v, dict) and v.get("topic")},
            [str(m["id"]) for m in ms if isinstance(m, dict) and m.get("id")])


def topic_for(roadmap: Any, tmap: Dict[str, Dict[str, str]]) -> Optional[Dict[str, str]]:
    """First mapped milestone in a row's ``roadmap`` list (or one string), with the milestone it came from; else None."""
    refs = [roadmap] if isinstance(roadmap, str) else (roadmap if isinstance(roadmap, list) else [])
    for ref in refs:
        if isinstance(ref, str) and ref in tmap:
            return {**tmap[ref], "milestone": ref}
    return None


def build(rows: List[Dict[str, Any]], tmap: Dict[str, Dict[str, str]], milestone_ids: List[str]) -> Dict[str, Any]:
    index: Dict[str, Dict[str, Any]] = {}
    counts: Dict[Tuple[str, str], Dict[str, int]] = {}
    unmapped_refs: Dict[str, int] = {}
    for r in rows:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        hit = topic_for(r.get("roadmap"), tmap)
        topic, sub = (hit["topic"], hit["subtopic"]) if hit else (UNMAPPED, "")
        index[str(r["id"])] = {"topic": topic, "subtopic": sub, "milestone": hit["milestone"] if hit else None}
        c = counts.setdefault((topic, sub), {"n_open": 0, "n_total": 0})
        c["n_total"] += 1
        c["n_open"] += 0 if r.get("state") in TERMINAL else 1
        if not hit:
            refs = r.get("roadmap") if isinstance(r.get("roadmap"), list) else [r.get("roadmap")]
            for ref in refs or [None]:
                key = str(ref) if ref else "(no roadmap ref)"
                unmapped_refs[key] = unmapped_refs.get(key, 0) + 1
    by_topic: Dict[str, Dict[str, Any]] = {}
    for (topic, sub), c in sorted(counts.items()):
        t = by_topic.setdefault(topic, {"topic": topic, "n_open": 0, "n_total": 0, "subtopics": []})
        t["n_open"] += c["n_open"]
        t["n_total"] += c["n_total"]
        if sub:
            t["subtopics"].append({"subtopic": sub, **c})
    missing = sorted(set(milestone_ids) - set(tmap))
    return {"topics": sorted(by_topic.values(), key=lambda t: t["topic"]), "rows": index,
            "unmapped": {"n_rows": by_topic.get(UNMAPPED, {}).get("n_total", 0), "refs": dict(sorted(unmapped_refs.items()))},
            "coverage": {"n_milestones": len(milestone_ids), "n_mapped": len(set(milestone_ids) & set(tmap)),
                         "milestones_without_topic": missing, "topics_for_unknown_milestones": sorted(set(tmap) - set(milestone_ids))}}


@router.get("/topics")
def get_topics() -> Dict[str, Any]:
    from src.runtime import checklist_store
    root = Path(repo_root())
    as_of = datetime.now(timezone.utc).isoformat()
    try:
        tmap, milestone_ids = load_topic_map(root)
    except Exception:  # noqa: BLE001  # allow-silent: a stated read_state, not a 5xx
        logger.warning("work/topics: topic map unreadable", exc_info=True)
        return {"as_of": as_of, "read_state": "map_unreadable", "topics": [], "rows": {}, "unmapped": None, "coverage": None}
    try:
        rows = [r for r in checklist_store.load(root).get("items", []) if isinstance(r, dict)]
    except Exception:  # noqa: BLE001  # allow-silent: a stated read_state, never an empty list that reads as "no work"
        logger.warning("work/topics: rows unreadable", exc_info=True)
        return {"as_of": as_of, "read_state": "rows_unreadable", "topics": [], "rows": {}, "unmapped": None,
                "coverage": {"n_milestones": len(milestone_ids), "n_mapped": len(set(milestone_ids) & set(tmap)),
                             "milestones_without_topic": sorted(set(milestone_ids) - set(tmap)),
                             "topics_for_unknown_milestones": sorted(set(tmap) - set(milestone_ids))}}
    return {"as_of": as_of, "read_state": "measured", "n_rows": len(rows), **build(rows, tmap, milestone_ids)}
