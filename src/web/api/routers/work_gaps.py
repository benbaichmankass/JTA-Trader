"""Tier-1 read endpoint: the two WORK-GAP numbers (WORK-GAP-ALERTS). GET only; authorizes nothing.

``GET /api/bot/work/gaps`` -> ``{gaps: [{gap, n, ids, read_state, population}]}`` from ``scripts/ops/gap_counts.py``.
``n`` is ``null`` (read_state ``could_not_look``) when the source could not be read -- never ``0``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

from src.utils.paths import repo_root

router = APIRouter(prefix="/api/bot/work", tags=["work"])


@router.get("/gaps")
def get_gaps() -> Dict[str, Any]:
    from scripts.ops import gap_counts
    return gap_counts.compute(Path(repo_root()))
