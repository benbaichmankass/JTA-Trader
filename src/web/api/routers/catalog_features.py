"""Tier-1 read endpoint: the features catalog (``GET /api/bot/catalog/features``).

Projects ``docs/reference/signal-catalog.yaml`` joined with the ``model.json`` feature lists under
``ml/served`` and ``ml/candidates`` (public repo files, no DB, no secrets -> ungated, like
``/api/bot/research/catalog``). Coverage is computed live by ``src.runtime.feature_catalog_coverage``.
Freshness is not measured per input here: ``freshness.state`` is ``unmeasured`` with null
``last_value_at`` / ``age_s`` (render "—", never "fresh").
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from src.runtime.feature_catalog_coverage import build_features_view
from src.utils.paths import repo_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/catalog", tags=["catalog"])


@router.get("/features")
def get_features() -> dict[str, Any]:
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        return build_features_view(Path(repo_root()), as_of)
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as read_state "unreadable" + exception type
        logger.warning("features catalog build failed: %s", exc)
        return {"as_of": as_of, "catalog_generated": None, "read_state": "unreadable",
                "reason": type(exc).__name__, "features": [], "coverage": None}
