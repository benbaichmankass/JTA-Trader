"""GET /api/diag/research_runs (WSD-S6D-RESEARCH-RESULTS, design D7).

The trainer's research results store as mirrored into ``trainer_store.db`` (``research_runs``):
dispatch stamps, result records and grades, newest first, with the freshness of the mirror file
and of the ingest. Read-only (a stale sidecar is rebuilt from the mirror, exactly as a Data
Explorer read does). Tier 1, same diag token gate as ``routers/diag.py``.

A SEPARATE router on purpose: ``routers/diag.py`` is in the live trader's import closure
(config/trader_import_closure.txt), and importing ``src.units.db.trainer_store`` from it would put
the mirror ingester in that closure, so every trainer_store edit would restart the trader.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.units.db.trainer_store import research_runs_view
from src.web.api.routers.diag import _require_diag_token

router = APIRouter(prefix="/api/diag", tags=["diag"])


@router.get("/research_runs")
def get_research_runs(request: Request, unit: str | None = None, kind: str | None = None,
                      limit: int = 50) -> dict[str, Any]:
    _require_diag_token(request)
    if unit is not None and not re.fullmatch(r"RQ-[0-9A-Za-z-]{3,40}", unit):
        raise HTTPException(status_code=400, detail="unit must look like RQ-YYYYMMDD-...")
    if kind is not None and kind not in ("dispatch", "result", "grade"):
        raise HTTPException(status_code=400, detail="kind must be dispatch | result | grade")
    return research_runs_view(unit=unit, kind=kind, limit=limit)
