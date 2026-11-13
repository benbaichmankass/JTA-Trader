"""Tier-1 read endpoints: the searchable research catalog (Data Explorer, "Research" sub-tab).

- ``GET /api/bot/research/catalog`` -- every research unit (queued, due, dispatched, running,
  resulted, blocked, retired) with search, facet filters, sorting, pagination, facet counts
  and a "stay on top" block (new since ``since``, stuck, due, recent verdicts).
- ``GET /api/bot/research/catalog/{unit_id}`` -- one unit in full, with its landed result rows.
- ``GET /api/bot/research/registry`` -- the IDEA-level R&D registry (operator 2026-11-12, lane RD-REGISTRY):
  one entry per strategy / ML idea with a computed stage (``src/runtime/rd_registry.py``). Built from the
  catalog above plus the live trainer-mirror ML registry rows; falls back to the committed
  ``comms/research/rd_registry.json`` if the build fails. Additive read route; gates nothing.

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

from src.runtime import rd_registry as rdr
from src.runtime import research_catalog as rc
from src.runtime import research_runs as rr
from src.utils.paths import repo_root
from src.web.api._swr import SWRCache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/research", tags=["research"])

_UNIT_ID_RE = re.compile(r"^RQ-[0-9A-Za-z-]{4,40}$")
_SWR = SWRCache(name="research-catalog", fresh_s=30.0, stale_s=300.0)
_SWR_REG = SWRCache(name="research-registry", fresh_s=300.0, stale_s=1800.0)
_SWR_RUNS = SWRCache(name="research-runs", fresh_s=60.0, stale_s=600.0)


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


def _registry() -> dict[str, Any]:
    root = Path(repo_root())
    live_rows = None
    try:
        from src.web.api.routers import training_center
        reg = training_center.get_registry()
        live_rows = reg.get("rows") if isinstance(reg, dict) else None
    except Exception as exc:  # noqa: BLE001  # allow-silent: falls back to the committed snapshot, stated in read_state.ml_registry
        logger.warning("research registry: live ML registry unreadable: %s", exc)
    doc = rdr.build_registry(root, catalog=_get(), live_registry_rows=live_rows or None)
    doc["cross_check"] = {"ok": None, "problems": None, "note": "run scripts/research/rd_registry.py for the cross-check"}
    doc["servedFrom"] = "built"
    return doc


@router.get("/registry")
def get_registry(
    track: str | None = Query(None, pattern="^(STRATEGY|ML)$"),
    stage: Annotated[list[str] | None, Query()] = None,
    q: str = Query("", max_length=200),
) -> dict[str, Any]:
    """The idea-level R&D registry. Optional filters narrow ``ideas``; ``summary`` is always the whole registry."""
    try:
        doc, _age, swr_state = _SWR_REG.get("registry", _registry)
    except Exception as exc:  # noqa: BLE001  # allow-silent: falls back to the committed file, stated as servedFrom/readState
        logger.warning("research registry build failed: %s", exc)
        path = Path(repo_root()) / "comms" / "research" / "rd_registry.json"
        try:
            import json as _json
            doc = _json.loads(path.read_text(encoding="utf-8"))
            doc["servedFrom"] = f"committed file (live build failed: {type(exc).__name__})"
            swr_state = "fallback"
        except Exception:  # noqa: BLE001  # allow-silent: surfaced as present False + readState unreadable
            return {"present": False, "readState": "unreadable", "reason": type(exc).__name__,
                    "ideas": [], "summary": None}
    stages = set(_csv(stage))
    terms = [t for t in q.lower().split() if t]
    ideas = [i for i in doc.get("ideas") or []
             if (not track or i.get("track") == track) and (not stages or i.get("stage") in stages)
             and all(t in f"{i.get('id')} {i.get('name')} {i.get('stage_reason')}".lower() for t in terms)]
    return {**doc, "present": True, "readState": "read", "cache": swr_state,
            "matched": len(ideas), "ideas": ideas,
            "freshness": "built from the VM working tree (ict-git-sync pulls main ~every 5 min); cached 5 min"}


# ── UI-BACKTEST-LOG-GAPS: the run log (every test run, its result, what we did with it) ─────────────────────────


def _runs() -> dict[str, Any]:
    root = Path(repo_root())
    cat = _get()
    docs: dict[str, dict] = {}
    q = root / "research" / "queue"
    for sub in (q, q / "blocked"):
        if sub.is_dir():
            for p in sorted(sub.glob("*.yaml")):
                doc, _err = rc._load_yaml(p)  # unreadable files are already in the catalog's readErrors
                if doc is not None:
                    docs[str(doc.get("id") or p.stem)] = doc
    return {"rows": rr.build_runs(cat["units"], docs), "readErrors": cat["readErrors"],
            "generatedAt": rc._iso(datetime.now(timezone.utc))}


def _trainer_sweeps() -> dict[str, Any]:
    """The trainer sweep mirror's own age, stated (it is an on-demand producer, not a schedule)."""
    try:
        from src.web.api.routers import backtests as bt
        sw = bt.get_backtest_sweeps(limit=1)
        age = sw.get("mirror_age_seconds")
        return {"read_state": "read" if sw.get("present") else "absent", "mirror_age_seconds": age,
                "mirror_age_days": round(age / 86400, 1) if isinstance(age, (int, float)) else None,
                "route": "/api/bot/backtests/sweeps",
                "note": "scripts/ops/run_backtest_sweep.sh is an ON-DEMAND sweep (run by hand through the trainer "
                        "relay, last for the 2026-05-17 post-incident validation); it is not scheduled, so its "
                        "age is not a broken sync. Research-harness runs are the log above."}
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as read_state unreadable
        return {"read_state": "unreadable", "mirror_age_seconds": None, "mirror_age_days": None,
                "route": "/api/bot/backtests/sweeps", "note": f"could not read: {type(exc).__name__}"}


@router.get("/runs")
def get_runs(
    verdict: Annotated[list[str] | None, Query()] = None,
    what: Annotated[list[str] | None, Query()] = None,
    q: str = Query("", max_length=200),
    since: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Every research/backtest run that produced a verdict, newest first, with what was done with it.

    ``what`` filters on ``what_we_did.state`` (``acted`` / ``recorded`` / ``none_recorded``); ``counts`` are over
    the whole log. An unreadable catalog is ``readState: unreadable`` with ``runs: null``, never an empty log.
    """
    try:
        data, _age, swr_state = _SWR_RUNS.get("runs", _runs)
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as readState unreadable + runs null
        logger.warning("research runs build failed: %s", exc)
        return {"present": False, "readState": "unreadable", "reason": type(exc).__name__, "total": None,
                "matched": None, "runs": None, "counts": None, "trainer_sweeps": _trainer_sweeps()}
    bad = [w for w in _csv(what) if w not in rr.WHAT_STATES]
    if bad:
        raise HTTPException(status_code=400, detail=f"what must be among {list(rr.WHAT_STATES)}")
    out = rr.query_runs(data["rows"], verdict=_csv(verdict), what=_csv(what), q=q, since=since,
                        limit=limit, offset=offset)
    return {**out, "present": True, "readState": "partial" if data["readErrors"] else "read",
            "readErrors": data["readErrors"], "generatedAt": data["generatedAt"], "cache": swr_state,
            "population": "every research/queue unit (incl. blocked/) whose catalog row carries a verdict",
            "what_we_did_basis": "follow-up units linked by iteration.from_result, requires_result.unit, "
                                 "grading.confirm_unit / grading.confirms; plus grading.disposition and retired_reason "
                                 "(prose). none_recorded = no such link on the record, NOT 'nobody acted'.",
            "trainer_sweeps": _trainer_sweeps()}
