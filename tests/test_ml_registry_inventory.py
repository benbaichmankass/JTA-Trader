"""Route additions for GET /api/bot/ml/registry (lane ML-REGISTRY-CONSOLIDATE): served/candidate/overlay rows, slot on every row, by_slot."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
TRADING = {"ml-decision-entry-v1", "ml-decision-entry-v2", "ml-entry-eq-v1", "ml-entry-eq-struct-ens5-v1"}


@pytest.fixture
def feed(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNTIME_LOGS_DIR", str(tmp_path / "runtime_logs"))
    monkeypatch.setenv("ICT_REPO_ROOT", str(REPO))
    from src.web.api import main as api_main
    return TestClient(api_main.app).get("/api/bot/ml/registry").json()


def test_trading_models_overlay_exit_head_present(feed):
    by_id = {r["model_id"]: r for r in feed["rows"]}
    assert TRADING <= set(by_id)
    assert {"overlay-td-v1", EXIT_HEAD_PIN, "ml-entry-tp-revision-v1"} <= set(by_id)
    assert by_id["ml-entry-eq-struct-ens5-v1"]["source"] == "candidate"
    assert by_id["ml-decision-entry-v1"]["stage_from_config"] == "live"
    assert by_id["ml-entry-eq-struct-ens5-v1"]["consuming_accounts"] == ["alpaca_live", "alpaca_portfolio"]
    assert feed["inventory_read_state"] == "ok" and feed["total_count"] == len(feed["rows"]) and feed["count"] == feed["mirror_count"]


def test_every_row_has_slot_and_name(feed):
    assert all(r.get("slot") and r.get("display_name") for r in feed["rows"])


def test_by_slot_shape(feed):
    bs = feed["by_slot"]
    assert [k for k in bs][:10] == [f"D{i}" for i in range(1, 11)]
    assert bs["D1"]["empty"] is True
    foxhound = bs["D3"]["breeds"]["Foxhound"]
    entry = next(c for c in foxhound if c["lineage"] == "ml-decision-entry")
    assert {v["model_id"] for v in entry["variants"]} >= {"ml-decision-entry-v1", "ml-decision-entry-v2"}
    assert entry["status"] == "live"
    assert bs["D4"]["breeds"]["Beagle"][0]["variants"][0]["model_id"] == "overlay-td-v1"
    assert any(c["status"] == "live" for c in bs["D7"]["breeds"]["Labrador"])


def test_guard_passes_and_self_tests():
    for args in (["--self-test"], []):
        r = subprocess.run([sys.executable, "scripts/ci/check_ml_registry_consistency.py", *args],
                           cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


# ---- ML-REGISTRY-SERVED-MODELS-NO-STAGE (2026-11-12) ------------------------------------------------------------
# The 8 served/inventory ids the UI-SPA lane found with target_deployment_stage null next to a LIVE/SHADOW bucket.
# The refit sibling is whatever ml/served/ENTRY_SERVED.json serves (it moves on every graded promotion, e.g. #26288:
# r20261106 -> r20261115), so it is read from the pointer, never hard-coded.
_PTR = __import__("json").loads((REPO / "ml/served/ENTRY_SERVED.json").read_text())["artifact_dir"]
SERVED_SIBLING = "ml-decision-entry-" + _PTR.split("entry_")[-1]
SERVED_8 = TRADING | {SERVED_SIBLING, "ml-entry-tp-revision-v1", "overlay-td-v1", "exit-head-donchian-1h-v1"}


# The exit head is whatever config/strategies.yaml pins on the donchian legs (it moves on every graded retrain, e.g.
# #26906: v1 -> v2-neg25), so it is read from the pin, never hard-coded.
_PINS = {s.get("exit_head_model") for s in __import__("yaml").safe_load((REPO / "config/strategies.yaml").read_text())
         .get("strategies", {}).values() if isinstance(s, dict) and s.get("exit_head_model")}
assert len(_PINS) == 1, _PINS
EXIT_HEAD_PIN = _PINS.pop()
SERVED_8 = (SERVED_8 - {"exit-head-donchian-1h-v1"}) | {EXIT_HEAD_PIN}


def test_served_models_carry_stage_and_headline_metric(feed):
    by_id = {r["model_id"]: r for r in feed["rows"]}
    for mid in SERVED_8:
        r = by_id[mid]
        assert r["target_deployment_stage"], mid
        assert r["stage_read_state"] == "declared" and r["stage_source"] == "ml/served/SERVED_MODELS.yaml", mid
        hm = r["headline_metric"]
        assert hm and hm["provenance"] == "MEASURED" and hm["source"] and hm["n"], mid


def test_undeclared_inventory_row_renders_dash_not_a_guess():
    from src.runtime import ml_serving_inventory as inv

    row = {"model_id": "not-declared-v1"}
    inv.apply_served_declaration(row, {})
    assert row["target_deployment_stage"] is None and row["headline_metric"] is None
    assert row["stage_read_state"] == "undeclared"
