"""GET /api/bot/work/pipeline-map and src/runtime/pipeline_map.py -- the generated pipeline map."""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.runtime import pipeline_map as pm
from src.web.api.routers import work_pipeline_map as wpm

REPO = Path(__file__).resolve().parents[1]


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(wpm.router)
    return TestClient(app)


def test_build_fills_every_marker_from_its_source():
    md = pm.build(REPO, live=None, live_state="not read (test)")
    assert "<!-- GEN:" not in md                      # every marker replaced
    for name in pm.GENERATORS:
        assert f"<!-- BEGIN GEN:{name} -->" in md
    assert "generator failed" not in md
    assert "```mermaid" in md
    assert "Live read-state: **not read (test)**" in md   # an unread live source is stated, never zero


def test_drift_check_flags_a_missing_path(tmp_path: Path):
    # positive control: plant a path that does not exist in a copy of the skeleton
    root = tmp_path
    for rel in ("config", "docs/reference", "src", "scripts", "deploy", "ml", "comms"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / pm.SKELETON_REL, root / pm.SKELETON_REL)
    skel = (root / pm.SKELETON_REL).read_text(encoding="utf-8")
    (root / pm.SKELETON_REL).write_text(skel + "\nSee `src/runtime/no_such_module.py`.\n", encoding="utf-8")
    md = pm.build(root, live=None, live_state="not read (test)")
    assert "`src/runtime/no_such_module.py`" in md.split("BEGIN GEN:checks")[1]
    assert "no longer exist" in md


def test_route_builds_live_and_caches(monkeypatch):
    monkeypatch.setattr(wpm, "_live_performance", lambda: (None, "not read (test)"))
    wpm._cache.update(at=0.0, body=None)
    c = _client()
    body = c.get("/api/bot/work/pipeline-map").json()
    assert body["read_state"] == "read" and body["source"] == "live"
    assert body["live_state"] == "not read (test)"
    assert "<!-- BEGIN GEN:legs -->" in body["markdown"]
    assert body["last_commit"]["read_state"] in {"read", "unreadable"}
    again = c.get("/api/bot/work/pipeline-map").json()
    assert again["built_at"] == body["built_at"]          # served from cache


def test_route_falls_back_to_snapshot_when_build_fails(monkeypatch):
    monkeypatch.setattr(wpm, "_live_performance", lambda: (None, "not read (test)"))
    monkeypatch.setattr(pm, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    wpm._cache.update(at=0.0, body=None)
    body = _client().get("/api/bot/work/pipeline-map?refresh=true").json()
    assert body["source"] == "snapshot" and "boom" in body["build_error"]
    assert body["read_state"] in {"read", "missing"}


def test_registered_on_the_app(monkeypatch):
    from src.web.api.main import app
    monkeypatch.setattr(wpm, "_live_performance", lambda: (None, "not read (test)"))
    wpm._cache.update(at=0.0, body=None)
    r = TestClient(app).get("/api/bot/work/pipeline-map")
    assert r.status_code == 200 and r.json()["read_state"] == "read"


def test_structured_steps_loops_and_elements():
    d = pm.build_structured(REPO, live=None, live_state="not read (test)")
    steps = d["steps"]
    assert [s["n"] for s in steps] == sorted(s["n"] for s in steps) and len(steps) >= 11   # ordered spine
    assert all(s["technical"] and s["trading"] for s in steps)                              # both columns filled
    # a generated trading element from a source of truth, and a technical element resolved to a repo path
    assert any(e["kind"] == "leg" for s in steps for e in s["trading"])
    assert any(e["kind"] == "account" for s in steps for e in s["trading"])
    paths = [e["path"] for s in steps for e in s["technical"] if e.get("path") and e["path"].endswith(".py")]
    assert paths and all((REPO / p).exists() for p in paths[:20])
    ids = {s["id"] for s in steps}
    assert d["loops"] and all(lp["from"] in ids and lp["to"] in ids for lp in d["loops"])  # loops tie to real steps
    assert len({lp["id"] for lp in d["loops"]}) == len(d["loops"])
    # no secrets / balances in the payload


def test_route_serves_structured(monkeypatch):
    monkeypatch.setattr(wpm, "_live_performance", lambda: (None, "not read (test)"))
    wpm._cache.update(at=0.0, body=None)
    body = _client().get("/api/bot/work/pipeline-map").json()
    assert body["structured"]["steps"] and body["structured"]["loops"] and body["markdown"]
