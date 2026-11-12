"""UI-WQ-PLANS-ROUTES: GET /api/bot/ml/plan and POST /api/bot/work/plan-edits."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.runtime import work_store as ws
from src.web.api import main
from src.web.api.auth import require_session
from src.web.api.routers import work_plans as wp


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "work_store.db"
    monkeypatch.setenv("WORK_STORE_DB", str(path))
    wp._cache = None
    yield path
    wp._cache = None
    main.app.dependency_overrides.pop(require_session, None)


def _seed(path):
    s = ws.WorkStore(str(path))
    for rid in ("FRONTIER-RESEARCH", "ML-DEV-PLAN", "REGIME-PROGRAM"):
        s.create({"id": rid, "kind": "build", "title": rid, "state": "in_flight", "owner": "AM-ML"}, by="test")
    return s


def test_plan_joins_live_rows(db):
    _seed(db)
    body = TestClient(main.app).get("/api/bot/ml/plan").json()
    assert body["read_state"] == "read" and body["rows_read_state"] == "read"
    assert body["population"]["items"] == len(body["items"]) > 0
    assert sum(body["population"]["items_by_track"].values()) == body["population"]["items"]
    r1 = next(i for i in body["items"] if i["id"] == "ML-R1")
    assert r1["ref"] == "REGIME-PROGRAM" and r1["ref_state"] == "in_flight" and r1["flags"] == []
    # A row ref the store does not hold, read from a readable store, IS an orphan.
    assert any("ORPHAN" in i["flags"] for i in body["items"] if i["ref_kind"] == "row")
    assert body["dev_plan"]["read_state"] == "read"
    assert body["dev_plan"]["population"]["lines"] == body["population"]["dev_plan_lines"]


def test_absent_store_is_partial_and_never_orphans(db):
    assert not db.exists()
    body = TestClient(main.app).get("/api/bot/ml/plan").json()
    assert body["read_state"] == "partial" and body["rows_read_state"] == "absent"
    rows = [i for i in body["items"] if i["ref_kind"] == "row"]
    assert rows and all(i["ref_state"] is None and i["flags"] == [] for i in rows)
    assert all(i["ref_read_state"] == "absent" for i in rows)
    assert all(ln["flags"] is None for ln in body["dev_plan"]["lines"])
    assert not db.exists(), "a read must never create the store"


def test_plan_edit_requires_a_session(db):
    _seed(db)
    r = TestClient(main.app).post("/api/bot/work/plan-edits",
                                  json={"section": "frontier", "kind": "add", "text": "x"})
    assert r.status_code in (401, 500)


def test_plan_edit_add_and_edit_file_observations(db):
    s = _seed(db)
    main.app.dependency_overrides[require_session] = lambda: {"email": "operator"}
    c = TestClient(main.app)
    r = c.post("/api/bot/work/plan-edits", json={"section": "frontier", "kind": "add", "text": "Try a TSFM on funding."})
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["kind"] == "observation" and item["parent_id"] == "FRONTIER-RESEARCH" and item["state"] == "queued"
    assert item["extra"]["plan_edit"] == {"section": "frontier", "item_id": None, "kind": "add",
                                          "text": "Try a TSFM on funding.", "status": "new", "reply": None}
    r = c.post("/api/bot/work/plan-edits",
               json={"section": "ml_plan", "kind": "edit", "item_id": "REGIME-PROGRAM", "text": "Close it."})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["parent_id"] == "REGIME-PROGRAM"
    kids = s.list_items(parent="REGIME-PROGRAM", kind="observation")
    assert len(kids) == 1 and kids[0]["extra"]["plan_edit"]["kind"] == "edit"


def test_plan_edit_validation(db):
    _seed(db)
    main.app.dependency_overrides[require_session] = lambda: {"email": "operator"}
    c = TestClient(main.app)
    url = "/api/bot/work/plan-edits"
    assert c.post(url, json={"section": "bogus", "kind": "add", "text": "x"}).status_code == 400
    assert c.post(url, json={"section": "frontier", "kind": "rename", "text": "x"}).status_code == 400
    assert c.post(url, json={"section": "frontier", "kind": "add", "text": "  "}).status_code == 400
    assert c.post(url, json={"section": "frontier", "kind": "edit", "text": "x"}).status_code == 400
    assert c.post(url, json={"section": "frontier", "kind": "edit", "item_id": "NOPE", "text": "x"}).status_code == 404
    assert c.post(url, json={"section": "frontier", "kind": "add", "text": "x" * 5000}).status_code == 400
