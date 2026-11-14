"""GET /api/bot/work/pipeline-map -- the trading pipeline map for the Work tab."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web.api.routers import work_pipeline_map as wpm


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(wpm.router)
    return TestClient(app)


def test_serves_the_committed_map():
    r = _client().get("/api/bot/work/pipeline-map")
    assert r.status_code == 200
    body = r.json()
    assert body["read_state"] == "read"
    assert body["path"] == "docs/reference/trading-pipeline-map.md"
    assert "```mermaid" in body["markdown"]
    assert "<!-- BEGIN GENERATED: pipeline_map_numbers.py -->" in body["markdown"]
    assert body["last_commit"]["read_state"] in {"read", "unreadable"}
    assert body["file_mtime"]


def test_missing_file_is_a_state_not_a_5xx(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(wpm, "repo_root", lambda: str(tmp_path))
    body = _client().get("/api/bot/work/pipeline-map").json()
    assert body["read_state"] == "missing"
    assert body["markdown"] is None


def test_registered_on_the_app():
    from src.web.api.main import app
    r = TestClient(app).get("/api/bot/work/pipeline-map")
    assert r.status_code == 200
    assert r.json()["read_state"] == "read"
