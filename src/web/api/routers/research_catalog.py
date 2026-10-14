"""Tier-1 read endpoints: the searchable research catalog (Data Explorer, "Research" sub-tab).

- ``GET /api/bot/research/catalog`` -- every research unit (queued, due, dispatched, running,
  resulted, blocked, retired) with search, facet filters, sorting, pagination, facet counts
  and a "stay on top" block (new since ``since``, stuck, due, recent verdicts).
- ``GET /api/bot/research/catalog/{unit_id}`` -- one unit in full, with its landed result rows.

Projected ONLY from files committed to this public repo (``research/queue``, ``research/results``,
``research/THEMES.yaml``, ``docs/roadmap/milestones.yaml``) -- no DB, no secrets, no new table, so it
is exempt from the new-table-wiring guard and is **ungated Tier 1**, the same class as
``/api/bot/roadmap`` and ``/api/bot/work``: anyone can already read these files on GitHub, so a login
would add friction and no protection. The money-DB Data Explorer routes (``/api/bot/db/*``) stay
``require_session``. The pure projection lives in ``src/runtime/research_catalog.py``.

Freshness: read from the VM working tree, which ``ict-git-sync`` pulls from ``main`` ~every 5 min, so
the catalog is as fresh as the last push to ``main`` plus that interval.
A file that cannot be parsed is reported in ``readErrors`` -- never silently dropped.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from src.runtime import research_catalog as rc
from src.utils.paths import repo_root
from src.web.api._swr import SWRCache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/research", tags=["research"])

_UNIT_ID_RE = re.compile(r"^RQ-[0-9A-Za-z-]{4,40}$")
_SWR = SWRCache(name="research-catalog", fresh_s=30.0, stale_s=300.0)


def _catalog() -> dict[str, Any]:
    cat = rc.build_catalog(Path(repo_root()))
    cat["generatedAt"] = rc._iso(datetime.now(timezone.utc))
    return cat


def _get() -> dict[str, Any]:
    data, _age, _state = _SWR.get("catalog", _catalog)
    return data


def _csv(values: list[str] | None) -> list[str]:
    return [p for v in (values or []) for p in v.split(",") if p]


@router.get("/catalog")
def get_catalog(
    q: str = Query("", max_length=200),
    theme: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    verdict: Annotated[list[str] | None, Query()] = None,
    goal: Annotated[list[str] | None, Query()] = None,
    backend: Annotated[list[str] | None, Query()] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    stuck: Annotated[list[str] | None, Query()] = None,
    sort: str = Query("lastActivity"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    since: str | None = Query(None, max_length=40),
    created_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    created_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    """Search/filter/sort/paginate the catalog. Multi-value facets accept repeats or CSV."""
    try:
        cat = _get()
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as readState "unreadable" + exception type, never as an empty list
        logger.warning("research catalog build failed: %s", exc)
        return {"present": False, "readState": "unreadable", "reason": type(exc).__name__,
                "total": None, "matched": None, "items": [], "facets": {}, "readErrors": []}
    filters = {"theme": _csv(theme), "status": _csv(status), "verdict": _csv(verdict),
               "goal": _csv(goal), "backend": _csv(backend), "kind": _csv(kind), "stuck": _csv(stuck)}
    out = rc.query_catalog(cat["units"], q=q, filters=filters, sort=sort, order=order,
                           limit=limit, offset=offset, created_from=created_from, created_to=created_to)
    out.update({
        "present": True,
        "readState": "partial" if cat["readErrors"] else "read",
        "readErrors": cat["readErrors"],
        "roadmapAvailable": cat["roadmapAvailable"],
        "generatedAt": cat.get("generatedAt"),
        "stayOnTop": rc.stay_on_top(cat["units"], since),
        "freshness": "read from the VM working tree; ict-git-sync pulls main ~every 5 min",
    })
    return out


@router.get("/catalog/{unit_id}")
def get_catalog_unit(unit_id: str) -> dict[str, Any]:
    """One unit in full: the catalog row plus its landed result rows (newest first)."""
    if not _UNIT_ID_RE.match(unit_id):
        raise HTTPException(status_code=400, detail="invalid unit id")
    cat = _get()
    unit = next((u for u in cat["units"] if u["id"] == unit_id), None)
    if unit is None:
        return {"present": False, "id": unit_id, "readState": "partial" if cat["readErrors"] else "read"}
    rows, _files = rc.read_results(unit_id, Path(repo_root()) / "research" / "results")
    return {"present": True, "id": unit_id, "unit": unit,
            "resultRows": [{k: v for k, v in r.items() if k != "_file"} | {"file": r.get("_file")}
                           for r in rows[:20]],
            "resultRowsTruncated": len(rows) > 20}
