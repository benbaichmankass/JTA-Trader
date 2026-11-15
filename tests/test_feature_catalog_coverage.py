from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.runtime.feature_catalog_coverage import (
    build_features_view,
    compute_coverage,
    load_disk_models,
)


def _tree(tmp: Path) -> Path:
    (tmp / "docs/reference").mkdir(parents=True)
    (tmp / "docs/reference/signal-catalog.yaml").write_text(yaml.safe_dump({
        "generated": "2026-10-08",
        "inputs": [
            {"id": "ml_feature.log_return", "name": "log_return", "family": "ml", "kind": "ml_feature",
             "definition": "d", "source": "s", "used_by": ["see ml_models[].features"], "health": {"state": "unmeasured"}},
            {"id": "candle.open", "name": "open", "family": "strategy", "kind": "candle",
             "definition": "d", "source": "s", "used_by": ["ict_scalp"], "health": {"state": "measured"}},
            {"id": "x.orphan", "name": "orphan", "family": "strategy", "kind": "k", "used_by": [], "health": {}},
        ],
        "ml_models": [{"model_id": "old", "target_deployment_stage": "shadow", "features": ["log_return"]}],
    }))
    for rel, mid, feats in (("ml/served/a", "new-a", ["log_return", "ret_24"]), ("ml/candidates/b", "old", ["open"])):
        (tmp / rel).mkdir(parents=True)
        (tmp / rel / "model.json").write_text(json.dumps({"model_id": mid, "features": feats}))
    (tmp / "ml/served/bad").mkdir()
    (tmp / "ml/served/bad/model.json").write_text("{not json")
    return tmp


def test_diff(tmp_path):
    root = _tree(tmp_path)
    disk, errors = load_disk_models(root)
    assert len(disk) == 2 and len(errors) == 1
    cat = yaml.safe_load((root / "docs/reference/signal-catalog.yaml").read_text())
    cov = compute_coverage(cat, disk)
    assert cov["models_missing_from_catalog"] == ["new-a"]
    assert cov["features_missing_per_model"] == {"new-a": ["ret_24"]}
    assert cov["unused_catalog_inputs"] == ["x.orphan"]


def test_view(tmp_path):
    v = build_features_view(_tree(tmp_path), "T")
    assert v["read_state"] == "partial" and v["catalog_generated"] == "2026-10-08"
    c = v["coverage"]
    assert (c["n_features"], c["n_with_consumer"], c["n_models_in_registry"], c["n_models_missing_from_catalog"]) == (3, 2, 2, 1)
    lr = next(f for f in v["features"] if f["id"] == "ml_feature.log_return")
    assert {m["model_id"] for m in lr["used_by_models"]} == {"new-a", "old"}
    assert lr["freshness"] == {"state": "unmeasured", "last_value_at": None, "age_s": None}


def test_route_live_repo():
    from fastapi.testclient import TestClient

    from src.web.api.main import app

    r = TestClient(app).get("/api/bot/catalog/features")
    assert r.status_code == 200
    j = r.json()
    on_disk = len(list(Path("ml/served").glob("*/model.json")) + list(Path("ml/candidates").glob("*/model.json")))
    assert j["read_state"] in ("read", "partial")
    assert j["coverage"]["n_models_in_registry"] == on_disk
    assert j["coverage"]["n_features"] == len(j["features"]) > 0
