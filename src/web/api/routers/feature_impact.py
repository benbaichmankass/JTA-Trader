"""Tier-1 read endpoints: the FEATURE-IMPACT heat map (FEATURE-IMPACT-MAP, UI backend half).

Reads the ML lane's M1 long table (PR #24916): ``comms/feature_impact/latest.json`` -> ``<run_id>.jsonl`` (schema
``feature_impact/1``; one row per model x side x feature x measure, ``symbol: "pooled"``). Until that file exists on the
serving tree every route answers ``read_state: "no_run"`` with empty cells -- the SPA renders dashes, never zeros.

* ``GET /api/bot/feature-impact/heatmap?by=asset_class|ml_type|stage&measure=gain_share|split_share&stage=``
  feature-FAMILY x ``by`` cells. A cell is the MEAN, over the (model, side) booster sets that fall in it, of that booster
  set's total share held by the family (shares sum to 1 within a booster set, so a family's share is well defined).
  ``n`` = booster sets behind the cell, ``n_col`` = booster sets in its column, ``coverage`` = n / n_col (a family a
  model does not use has no row, so cells average over the models that use it). A family with zero splits in a model is a MEASURED 0.0 (the producer says so);
  a (family, col) pair with no booster set is simply absent -- never a 0.
* ``GET /api/bot/feature-impact/detail?family=&asset_class=&measure=`` feature x model cells for the drill-down.
  v0 is pooled per model (``symbol: "pooled"``, 1h): per-symbol / per-timeframe cells need M2 and are NOT here.
* ``GET /api/bot/feature-impact/invest`` the "where to invest in data collection" ranking: ``not_computed`` in v0
  (needs M2 rank IC + catalog coverage + collection cost; the plan's rule registers before use). Dashes.

Importance is NOT edge (model-internal split/gain share on the model's own training population): every payload says so.
GET only; behind the site gate with no special-casing.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException

from src.utils.paths import repo_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/feature-impact", tags=["bot"])

MEASURES = ("gain_share", "split_share")
BY = ("asset_class", "ml_type", "stage")
CAVEAT = ("model-internal importance on each model's own pooled training population -- NOT edge, NOT per symbol; "
          "model-free rank IC (M2) and ablation (M3) are not in v0")


def _load(root: Path) -> Tuple[str, Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """-> (read_state, latest.json summary, rows). ``no_run`` when no run exists; ``unreadable`` when it cannot be read."""
    latest = root / "comms" / "feature_impact" / "latest.json"
    if not latest.is_file():
        return "no_run", None, []
    try:
        summary = json.loads(latest.read_text(encoding="utf-8"))
        data = root / "comms" / "feature_impact" / str(summary["file"])
        rows = [json.loads(line) for line in data.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:  # noqa: BLE001  # allow-silent: a stated read_state, not a 5xx
        logger.warning("feature-impact: run unreadable", exc_info=True)
        return "unreadable", None, []
    return str(summary.get("read_state") or "measured"), summary, rows


def _usable(rows: List[Dict[str, Any]], measure: str, stage: Optional[str]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("measure") == measure and r.get("read_state") == "measured"
            and isinstance(r.get("value"), (int, float)) and r.get("feature_family")
            and (stage is None or r.get("stage") == stage)]


def family_shares(rows: List[Dict[str, Any]]) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
    """{(model_id, side): {meta..., "families": {family: total share}}} for the (already filtered) rows."""
    out: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for r in rows:
        k = (r.get("model_id"), r.get("side"))
        d = out.setdefault(k, {"asset_class": r.get("asset_class"), "ml_type": r.get("ml_type"),
                               "stage": r.get("stage"), "families": defaultdict(float)})
        d["families"][r["feature_family"]] += float(r["value"])
    return out


def build_heatmap(rows: List[Dict[str, Any]], *, by: str, measure: str, stage: Optional[str]) -> Dict[str, Any]:
    sets = family_shares(_usable(rows, measure, stage))
    acc: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    n_col: Dict[str, int] = defaultdict(int)
    for d in sets.values():
        col = d.get(by)
        if col is None:
            continue
        n_col[str(col)] += 1
        for fam, share in d["families"].items():
            acc[(fam, str(col))].append(share)
    # `coverage` = booster sets that carry the family / booster sets in the column. A family a model does not use has NO
    # row (not a measured 0), so a cell averages only over the models that use it: a column's cells sum to 1 only when
    # every model in it has every family. Low coverage means "one model's number", not "the column's number".
    cells = [{"row": fam, "col": col, "value": round(sum(v) / len(v), 6), "n": len(v), "n_col": n_col[col],
              "coverage": round(len(v) / n_col[col], 4), "provenance": "MEASURED", "read_state": "measured"}
             for (fam, col), v in sorted(acc.items())]
    return {"rows": sorted({c["row"] for c in cells}), "cols": sorted({c["col"] for c in cells}), "cells": cells,
            "n_booster_sets": len(sets)}


def build_detail(rows: List[Dict[str, Any]], *, family: Optional[str], asset_class: Optional[str], measure: str,
                 stage: Optional[str]) -> Dict[str, Any]:
    use = [r for r in _usable(rows, measure, stage) if (not family or r["feature_family"] == family)
           and (not asset_class or r.get("asset_class") == asset_class)]
    cells = [{"row": r.get("feature"), "col": f"{r.get('model_id')}:{r.get('side')}", "value": round(float(r["value"]), 6),
              "n": r.get("n_obs"), "family": r["feature_family"], "stage": r.get("stage"), "symbol": r.get("symbol"),
              "timeframe": r.get("timeframe"), "provenance": r.get("provenance") or "MEASURED",
              "read_state": "measured", "source_artifact": r.get("source_artifact")} for r in use]
    return {"rows": sorted({c["row"] for c in cells}), "cols": sorted({c["col"] for c in cells}), "cells": cells,
            "resolution": {"symbol": "pooled", "note": "per-symbol / per-timeframe cells need M2 (not in v0)"}}


def _envelope(read_state: str, summary: Optional[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    return {"as_of": datetime.now(timezone.utc).isoformat(), "read_state": read_state,
            "run_id": (summary or {}).get("run_id"), "computed_at": (summary or {}).get("computed_at"),
            "coverage": (summary or {}).get("coverage"), "caveat": CAVEAT, **extra}


def _check(measure: str) -> None:
    if measure not in MEASURES:
        raise HTTPException(status_code=400, detail=f"unknown measure {measure!r}; valid: {list(MEASURES)}")


@router.get("/heatmap")
def get_heatmap(by: str = "asset_class", measure: str = "gain_share", stage: Optional[str] = None) -> Dict[str, Any]:
    _check(measure)
    if by not in BY:
        raise HTTPException(status_code=400, detail=f"unknown by {by!r}; valid: {list(BY)}")
    state, summary, rows = _load(Path(repo_root()))
    body = build_heatmap(rows, by=by, measure=measure, stage=stage) if rows else {
        "rows": [], "cols": [], "cells": [], "n_booster_sets": 0}
    return _envelope(state, summary, group="family", by=by, measure=measure, stage=stage, **body)


@router.get("/detail")
def get_detail(family: Optional[str] = None, asset_class: Optional[str] = None, measure: str = "gain_share",
               stage: Optional[str] = None) -> Dict[str, Any]:
    _check(measure)
    state, summary, rows = _load(Path(repo_root()))
    body = build_detail(rows, family=family, asset_class=asset_class, measure=measure, stage=stage) if rows else {
        "rows": [], "cols": [], "cells": [], "resolution": {"symbol": "pooled"}}
    return _envelope(state, summary, family=family, asset_class=asset_class, measure=measure, stage=stage, **body)


@router.get("/invest")
def get_invest() -> Dict[str, Any]:
    """Not computed in v0: the ranking needs M2 rank IC, catalog coverage and collection cost. Never a made-up order."""
    state, summary, _rows = _load(Path(repo_root()))
    return _envelope("not_computed", summary, items=[], source_read_state=state,
                     reason="needs M2 rank IC + catalog coverage/freshness + collection cost; the ranking rule must be "
                            "registered before use (plan section 15.6 / Q7)")
