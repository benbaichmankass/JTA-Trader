"""UI-WQ-DECISIONS-ROUTE: planning questions on work-store items, and the SPA's
session-gated write ``POST /api/bot/work/decision/session``.

Positive controls first: a question written on a store item must APPEAR in the
inbox before the tests assert anything about its grading, and the session route
must accept the operator's session before its refusals mean anything.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.runtime import work_decisions as wd
from src.runtime import work_store as ws
from src.web.api import main
from src.web.api.auth import require_session
from src.web.api.routers import work as wk

QUESTION = {
    "id": "PLAN-Q1",
    "title": "Which lane goes first?",
    "evidence": "Two lanes are ready; one slot.",
    "options": [{"key": "a", "label": "Lane A"}, {"key": "b", "label": "Lane B"}],
    "recommended": "b",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "work"
    for sub in ("intents", "objects", "steps"):
        (root / sub).mkdir(parents=True)
    monkeypatch.setattr(wk, "_work_dir", lambda: root)
    monkeypatch.setattr(wk, "_intents_dir", lambda: root / "intents")
    monkeypatch.setattr(wk, "_objects_dir", lambda: root / "objects")
    monkeypatch.setattr(wk, "_steps_dir", lambda: root / "steps")
    monkeypatch.setattr(wk, "_checklist_path", lambda: root / "MANAGER-CHECKLIST.json")
    monkeypatch.setattr(wk, "_pipeline_store_path", lambda: root / "PIPELINE.jsonl")
    transit = tmp_path / "transit.jsonl"
    monkeypatch.setattr(wk, "transit_log_path", lambda: transit)
    monkeypatch.setattr(wd, "transit_log_path", lambda: transit)
    db = tmp_path / "work_store.db"
    monkeypatch.setenv("WORK_STORE_DB", str(db))
    wk._CACHE.clear()
    yield db, transit
    wk._CACHE.clear()
    main.app.dependency_overrides.pop(require_session, None)


def _seed(db, *, requests=(QUESTION,), state="queued"):
    s = ws.WorkStore(str(db))
    s.create({"id": "UI-PLAN", "kind": "build", "title": "Planning", "state": state,
              "owner": "AM-UI", "extra": {"week_lane": "surge"}}, by="test")
    s.set("UI-PLAN", {"decision_requests": list(requests)}, by="test", expected_version=1)
    return s


def _signed_in():
    main.app.dependency_overrides[require_session] = lambda: {"email": "operator"}
    return TestClient(main.app)


def test_a_store_question_appears_with_title_evidence_and_recommendation(env):
    db, _ = env
    s = _seed(db)
    # The by-name write merged into extra; week_lane survived.
    assert s.get("UI-PLAN")["extra"]["week_lane"] == "surge"
    body = TestClient(main.app).get("/api/bot/work/decisions").json()
    assert body["sources"]["workStore"] == {"state": "read", "error": None, "itemsWithRequests": 1}
    [req] = body["requests"]
    assert req["objectId"] == "UI-PLAN" and req["id"] == "PLAN-Q1"
    assert req["source"] == "work_store"
    assert req["question"] == "Which lane goes first?"
    assert req["evidence"] == "Two lanes are ready; one slot."
    assert req["recommended"] == "b"
    assert req["allowsFreeText"] is True  # "Other" on every question
    assert req["answerState"] == wd.NOT_SUBMITTED
    assert body["summary"]["byAnswerState"][wd.NOT_SUBMITTED] == 1
    assert body["summary"]["waitingOnYouTotal"] == 1


def test_recommended_naming_no_written_option_is_null(env):
    db, _ = env
    _seed(db, requests=({**QUESTION, "recommended": "zzz"},))
    [req] = TestClient(main.app).get("/api/bot/work/decisions").json()["requests"]
    assert req["recommended"] is None


def test_absent_store_is_absent_not_read(env):
    db, _ = env
    assert not db.exists()
    body = TestClient(main.app).get("/api/bot/work/decisions").json()
    assert body["sources"]["workStore"]["state"] == "absent"
    assert body["sources"]["workStore"]["itemsWithRequests"] is None
    assert not db.exists(), "a read must never create the store"


def test_decision_requests_write_is_validated(env):
    db, _ = env
    s = ws.WorkStore(str(db))
    s.create({"id": "UI-X", "kind": "build", "title": "x", "state": "queued"}, by="test")
    with pytest.raises(ws.WorkStoreValidationError):
        s.set("UI-X", {"decision_requests": [{"title": "no id"}]}, by="test", expected_version=1)
    with pytest.raises(ws.WorkStoreValidationError):
        s.set("UI-X", {"decision_requests": "not a list"}, by="test", expected_version=1)


def test_session_route_requires_a_session(env):
    db, _ = env
    _seed(db)
    r = TestClient(main.app).post("/api/bot/work/decision/session",
                                  json={"object_id": "UI-PLAN", "request_id": "PLAN-Q1", "chosen": "a"})
    assert r.status_code in (401, 500)  # 500 only when the test env has no auth config


def test_session_write_goes_in_transit_without_the_service_token(env, monkeypatch):
    db, transit = env
    _seed(db)
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    c = _signed_in()
    r = c.post("/api/bot/work/decision/session",
               json={"object_id": "UI-PLAN", "request_id": "PLAN-Q1",
                     "chosen": "b", "free_text": "go", "submitted_by": "spoofed"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["answerState"] == wd.IN_TRANSIT and out["source"] == "work_store"
    assert "work item UI-PLAN" in out["note"]
    [row] = [json.loads(ln) for ln in transit.read_text().splitlines() if ln.strip()]
    assert row["submitted_by"] == "operator-spa"  # never the body's value, never an email
    [req] = c.get("/api/bot/work/decisions").json()["requests"]
    assert req["answerState"] == wd.IN_TRANSIT
    gate = c.get("/api/bot/work/decisions").json()["writeGate"]
    assert gate["acceptsWrites"] is False  # the token route is closed...
    assert gate["session"]["acceptsWrites"] is True  # ...the SPA route is not
    assert gate["session"]["path"] == "/api/bot/work/decision/session"


def test_session_write_validates_like_the_token_route(env):
    db, _ = env
    _seed(db)
    c = _signed_in()
    url = "/api/bot/work/decision/session"
    assert c.post(url, json={"object_id": "UI-PLAN", "request_id": "PLAN-Q1", "chosen": "c"}).status_code == 400
    assert c.post(url, json={"object_id": "UI-PLAN", "request_id": "PLAN-Q1"}).status_code == 400
    assert c.post(url, json={"object_id": "UI-PLAN", "request_id": "NOPE", "chosen": "a"}).status_code == 404
    assert c.post(url, json={"object_id": "NO-ITEM", "request_id": "PLAN-Q1", "chosen": "a"}).status_code == 404


def test_committed_on_the_item_is_409_and_graded_committed(env):
    db, _ = env
    answer = {"chosen": "b", "answered_at": "2026-11-12T23:00:00Z", "submission_id": "x", "committed_by": "mgr"}
    _seed(db, requests=({**QUESTION, "answer": answer},))
    c = _signed_in()
    r = c.post("/api/bot/work/decision/session",
               json={"object_id": "UI-PLAN", "request_id": "PLAN-Q1", "chosen": "a"})
    assert r.status_code == 409
    [req] = c.get("/api/bot/work/decisions").json()["requests"]
    assert req["answerState"] == wd.COMMITTED
