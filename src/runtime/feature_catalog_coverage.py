"""Feature-catalog coverage: diff the model feature lists on disk against the signal catalog.

Pure read path (Tier 1). Shared by ``scripts/ops/feature_catalog_coverage.py`` and
``GET /api/bot/catalog/features`` so the coverage numbers are computed, never asserted.

Models on disk = ``ml/served/*/model.json`` (stage ``served``) and ``ml/candidates/*/model.json``
(stage ``candidate``). The catalog side = ``docs/reference/signal-catalog.yaml`` ``inputs[]`` and
``ml_models[]`` (which already carries the ``ml/configs`` manifest feature lists, so manifests are
covered through the catalog's own ``ml_models``, not re-parsed here).
A feature is *covered* when its bare name equals an input ``name`` / the suffix of an input ``id``
or appears in some ``ml_models[].features`` list.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

CATALOG_REL = "docs/reference/signal-catalog.yaml"
_STAGE_DIRS = (("ml/served", "served"), ("ml/candidates", "candidate"))


def load_catalog(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / CATALOG_REL).read_text()) or {}


def load_disk_models(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ([{model_id, stage, path, features}], read_errors)."""
    models: list[dict[str, Any]] = []
    errors: list[str] = []
    for rel, stage in _STAGE_DIRS:
        for p in sorted((root / rel).glob("*/model.json")):
            try:
                d = json.loads(p.read_text())
                feats = d.get("features")
                if not isinstance(feats, list):
                    raise TypeError("no features list")
                models.append({"model_id": d.get("model_id") or p.parent.name, "stage": stage,
                               "path": str(p.relative_to(root)), "features": [str(f) for f in feats]})
            except Exception as exc:  # noqa: BLE001  # allow-silent: reported in read_errors, never dropped
                errors.append(f"{p.relative_to(root)}: {type(exc).__name__}: {exc}")
    return models, errors


def _bare(input_id: str) -> str:
    return input_id.split(".", 1)[1] if "." in input_id else input_id


def compute_coverage(catalog: dict[str, Any], disk_models: list[dict[str, Any]]) -> dict[str, Any]:
    inputs = catalog.get("inputs") or []
    cat_models = catalog.get("ml_models") or []
    known = {str(i.get("name")) for i in inputs} | {_bare(str(i.get("id"))) for i in inputs}
    for m in cat_models:
        known.update(str(f) for f in m.get("features") or [])
    cat_model_ids = {m.get("model_id") for m in cat_models}

    missing_models = sorted(m["model_id"] for m in disk_models if m["model_id"] not in cat_model_ids)
    features_missing = {}
    for m in disk_models:
        miss = [f for f in m["features"] if f not in known]
        if miss:
            features_missing[m["model_id"]] = miss
    used_names = {f for m in disk_models for f in m["features"]}
    for m in cat_models:
        used_names.update(str(f) for f in m.get("features") or [])
    unused_inputs = sorted(
        str(i["id"]) for i in inputs
        if not i.get("used_by") and str(i.get("name")) not in used_names and _bare(str(i["id"])) not in used_names
    )
    return {
        "n_models_on_disk": len(disk_models),
        "n_models_in_catalog": len(cat_models),
        "models_missing_from_catalog": missing_models,
        "features_missing_per_model": features_missing,
        "n_features_missing": len({f for v in features_missing.values() for f in v}),
        "unused_catalog_inputs": unused_inputs,
    }


def build_features_view(root: Path, as_of: str) -> dict[str, Any]:
    catalog = load_catalog(root)
    disk, errors = load_disk_models(root)
    cov = compute_coverage(catalog, disk)
    by_feature: dict[str, list[dict[str, str]]] = {}
    for m in disk:
        for f in m["features"]:
            by_feature.setdefault(f, []).append({"model_id": m["model_id"], "stage": m["stage"]})
    for m in catalog.get("ml_models") or []:
        for f in m.get("features") or []:
            row = {"model_id": m.get("model_id"), "stage": m.get("target_deployment_stage")}
            lst = by_feature.setdefault(str(f), [])
            if row["model_id"] not in {r["model_id"] for r in lst}:
                lst.append(row)
    features = []
    for i in catalog.get("inputs") or []:
        users = i.get("used_by") or []
        strategies = [u for u in users if not str(u).startswith("see ")]
        models = by_feature.get(str(i.get("name"))) or by_feature.get(_bare(str(i["id"]))) or []
        features.append({
            "id": i.get("id"), "family": i.get("family"), "kind": i.get("kind"),
            "definition": i.get("definition"), "source_code": i.get("source"),
            "used_by_strategies": strategies, "used_by_models": models,
            "health_state": (i.get("health") or {}).get("state"),
            "freshness": {"state": "unmeasured", "last_value_at": None, "age_s": None},
        })
    n_consumer = sum(1 for f, i in zip(features, catalog.get("inputs") or [])
                     if f["used_by_strategies"] or f["used_by_models"] or i.get("used_by"))
    return {
        "as_of": as_of,
        "catalog_generated": str(catalog.get("generated")) if catalog.get("generated") is not None else None,
        "read_state": "partial" if errors else "read",
        "read_errors": errors,
        "features": features,
        "coverage": {
            "n_features": len(features),
            "n_with_consumer": n_consumer,
            "n_models_in_registry": cov["n_models_on_disk"],
            "n_models_missing_from_catalog": len(cov["models_missing_from_catalog"]),
            "models_missing_from_catalog": cov["models_missing_from_catalog"],
            "n_features_missing_from_catalog": cov["n_features_missing"],
        },
    }

