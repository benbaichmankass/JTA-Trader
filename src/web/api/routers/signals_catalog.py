"""Tier-1 read endpoint: the signals catalog (``GET /api/bot/signals/catalog``).

The SPA's Signals Catalog tab (operator, p5 note: "I don't see the signals catalog and features heat
map here"). It serves every input in ``docs/reference/signal-catalog.yaml`` (row SIGNAL-CATALOG) joined
with the strategies and served/candidate models that read it -- the same join ``/api/bot/catalog/features``
uses (``src.runtime.feature_catalog_coverage.build_features_view``) -- plus each input's name and
timeframe from the catalog, filters, paging and a by-family/kind roll-up for the tab's grouping. The
feature heat map stays at ``/api/bot/feature-impact/heatmap``.

Public repo files only (no DB, no secrets), so it is ungated like ``/research/catalog``; CORS is the
app's middleware. Every reply carries ``read_state`` (``read`` | ``unreadable``), ``as_of``, the catalog's
own ``generated`` date, ``provenance`` and the ``population`` it was computed over. Health/freshness are
``unmeasured`` per input today: a null ``last_value_at`` renders "—", never "fresh".
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Query

from src.runtime.feature_catalog_coverage import build_features_view
from src.utils.paths import repo_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/signals", tags=["catalog"])

CATALOG = Path("docs/reference/signal-catalog.yaml")
CONSUMERS = ("any", "strategy", "model", "none")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_signals_catalog(root: Path, *, family: str | None = None, kind: str | None = None, q: str | None = None,
                          consumer: str = "any", limit: int = 200, offset: int = 0) -> dict[str, Any]:
    as_of = _now()
    raw = yaml.safe_load((root / CATALOG).read_text(encoding="utf-8")) or {}
    view = build_features_view(root, as_of)
    extra = {i.get("id"): i for i in (raw.get("inputs") or []) if isinstance(i, dict)}
    items = []
    for f in view.get("features") or []:
        src = extra.get(f.get("id")) or {}
        items.append({**f, "name": src.get("name"), "timeframe": src.get("timeframe")})
    total = len(items)
    groups: dict[tuple[str, str], int] = {}
    for it in items:
        k = (str(it.get("family")), str(it.get("kind")))
        groups[k] = groups.get(k, 0) + 1

    def keep(it: dict) -> bool:
        if family and it.get("family") != family:
            return False
        if kind and it.get("kind") != kind:
            return False
        s, m = bool(it.get("used_by_strategies")), bool(it.get("used_by_models"))
        if consumer == "strategy" and not s or consumer == "model" and not m or consumer == "none" and (s or m):
            return False
        if q:
            needle = q.lower()
            hay = " ".join(str(it.get(k) or "") for k in ("id", "name", "definition", "source_code")).lower()
            if needle not in hay:
                return False
        return True

    matched = [it for it in items if keep(it)]
    page = matched[offset: offset + limit]
    with_consumer = sum(1 for it in items if it.get("used_by_strategies") or it.get("used_by_models"))
    return {
        "as_of": as_of, "read_state": view.get("read_state") or "read",
        "catalog_generated": raw.get("generated"), "catalog_version": raw.get("catalog_version"),
        "provenance": {"source": [str(CATALOG), "ml/served/*/model.json", "ml/candidates/*/model.json"],
                       "measure": "MEASURED", "join": "src.runtime.feature_catalog_coverage.build_features_view"},
        "population": {"inputs": total, "matched": len(matched), "returned": len(page), "offset": offset,
                       "limit": limit, "next_offset": offset + limit if offset + limit < len(matched) else None,
                       "with_consumer": with_consumer, "without_consumer": total - with_consumer,
                       "read_errors": view.get("read_errors")},
        "filters": {"family": family, "kind": kind, "q": q, "consumer": consumer},
        "groups": [{"family": f, "kind": k, "count": n} for (f, k), n in sorted(groups.items())],
        "coverage": view.get("coverage"),
        "health_vocabulary": raw.get("health_vocabulary"),
        "items": page,
        "heatmap": "/api/bot/feature-impact/heatmap",
    }


@router.get("/catalog")
def get_signals_catalog(family: str | None = Query(default=None, max_length=64),
                        kind: str | None = Query(default=None, max_length=64),
                        q: str | None = Query(default=None, max_length=120),
                        consumer: str = Query(default="any"),
                        limit: int = Query(default=200, ge=1, le=500),
                        offset: int = Query(default=0, ge=0)) -> dict[str, Any]:
    """Every signal-catalog input with its consumers; filter by family / kind / consumer / text, paged."""
    if consumer not in CONSUMERS:
        consumer = "any"
    try:
        return build_signals_catalog(Path(repo_root()), family=family, kind=kind, q=q, consumer=consumer,
                                     limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as read_state "unreadable" + the exception type
        logger.warning("signals catalog build failed: %s", exc)
        return {"as_of": _now(), "read_state": "unreadable", "reason": type(exc).__name__, "items": None,
                "population": {"inputs": None}, "groups": None, "coverage": None}
