"""Work topics (WORK-TOPIC-TAXONOMY): a row's subject, COMPUTED from its ``roadmap`` ref.

Operator 2026-11-11 ~08:15Z: topics such as ML, Strategies, Trading pipeline, Prop with an optional subtopic,
derived from the existing roadmap ref plus a topic map (no free text), shown as chips and a group/filter in the
console work queue. Design: ``docs/design/ui-workplan-2026-11.md`` § 10; map: ``docs/roadmap/topics.yaml``
(guard ``topic-map-guard``).

``topic_for(refs)`` -> ``{"topic", "subtopic", "topics", "basis"}`` where ``basis`` is
``roadmap`` (the first ref that maps decides; ``topics`` lists every mapped topic, in ref order),
``unmapped`` (no ref, or only ``unmapped`` / unknown ids: topic = the map's ``unmapped_topic``), or
``could_not_look`` (the map file could not be read: topic ``None``, rendered "—", never a guess).
Pure apart from the cached file read; never raises.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

TOPICS_RELPATH = "docs/roadmap/topics.yaml"
BASIS_ROADMAP, BASIS_UNMAPPED, BASIS_COULD_NOT_LOOK = "roadmap", "unmapped", "could_not_look"


def _repo() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> Dict[str, Any]:
    import yaml

    doc = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(doc.get("milestones"), dict):
        raise ValueError("topics.yaml: `milestones` is not a mapping")
    return doc


def load_map(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    p = Path(path) if path else _repo() / TOPICS_RELPATH
    try:
        return _load(str(p), p.stat().st_mtime)
    except Exception as exc:  # noqa: BLE001 -- could not look, never a fabricated topic
        logger.warning("work_topics: map unreadable (%s): %s", p, exc)
        return None


def _refs(roadmap: Any) -> List[str]:
    if roadmap is None:
        return []
    if isinstance(roadmap, str):
        return [roadmap]
    if isinstance(roadmap, Iterable):
        return [str(r) for r in roadmap if r]
    return []


def topic_for(roadmap: Any, topic_map: Optional[Dict[str, Any]] = None, *, path: Optional[Path] = None) -> Dict[str, Any]:
    m = topic_map if topic_map is not None else load_map(path)
    if m is None:
        return {"topic": None, "subtopic": None, "topics": [], "basis": BASIS_COULD_NOT_LOOK}
    ms = m.get("milestones") or {}
    hits = [ms[r] for r in _refs(roadmap) if isinstance(ms.get(r), dict)]
    if not hits:
        return {"topic": m.get("unmapped_topic") or "Unmapped", "subtopic": None, "topics": [], "basis": BASIS_UNMAPPED}
    topics: List[str] = []
    for h in hits:
        if h.get("topic") and h["topic"] not in topics:
            topics.append(h["topic"])
    return {"topic": hits[0].get("topic"), "subtopic": hits[0].get("subtopic"), "topics": topics, "basis": BASIS_ROADMAP}


__all__ = ["topic_for", "load_map", "TOPICS_RELPATH", "BASIS_ROADMAP", "BASIS_UNMAPPED", "BASIS_COULD_NOT_LOOK"]
