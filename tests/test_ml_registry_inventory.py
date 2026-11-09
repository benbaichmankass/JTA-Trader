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
    assert {"overlay-td-v1", "exit-head-donchian-1h-v1", "ml-entry-tp-revision-v1"} <= set(by_id)
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
