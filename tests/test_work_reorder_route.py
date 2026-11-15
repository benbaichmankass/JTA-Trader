"""WORK-REORDER-ROUTE: POST /api/bot/work/reorder (session-gated atomic rank swap) + snapshot order."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.runtime import work_store as ws
from src.web.api import main
from src.web.api.auth import require_session
from src.web.api.routers import work as work_router

URL = "/api/bot/work/reorder"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "work_store.db"
    monkeypatch.setenv("WORK_STORE_DB", str(path))
    work_router._snapshot_cache = None
    yield path
    work_router._snapshot_cache = None
    main.app.dependency_overrides.pop(require_session, None)


def _store(path, rows):
    s = ws.WorkStore(str(path))
    for rid, rank, state in rows:
        f = {"id": rid, "kind": "build", "title": rid, "state": state, "owner": "m"}
        if rank is not None:
            f["priority_rank"] = rank
        s.create(f, by="test")
    return s


def _auth():
    main.app.dependency_overrides[require_session] = lambda: {"email": "operator"}
    return TestClient(main.app)


def _rank(s, rid):
    return s.get(rid)["priority_rank"]


def test_atomic_swap_of_ranked_neighbours(db):
    s = _store(db, [("A", 1, "queued"), ("B", 2, "queued"), ("C", 3, "queued")])
    r = _auth().post(URL, json={"id": "C", "direction": "up"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] and body["renumbered"] is False and sorted(body["changed"]) == ["B", "C"]
    assert (_rank(s, "A"), _rank(s, "B"), _rank(s, "C")) == (1, 3, 2)
    assert s.get("C")["updated_by"] == "operator-spa" and s.get("B")["version"] == 2
    assert [o["id"] for o in body["order"]] == ["A", "C", "B"]
    assert s.verify_chain().get("ok", True)


def test_down_swaps_with_next(db):
    s = _store(db, [("A", 1, "queued"), ("B", 2, "queued")])
    assert _auth().post(URL, json={"id": "A", "direction": "down"}).status_code == 200
    assert (_rank(s, "A"), _rank(s, "B")) == (2, 1)


def test_null_ranks_are_assigned_so_a_move_always_works(db):
    s = _store(db, [("A", 1, "queued"), ("B", None, "queued"), ("C", None, "queued")])
    r = _auth().post(URL, json={"id": "C", "direction": "up"})
    assert r.status_code == 200, r.text
    assert r.json()["renumbered"] is True
    # order was A, B, C (nulls last, register order); C moves above B; every row now has a rank.
    assert (_rank(s, "A"), _rank(s, "C"), _rank(s, "B")) == (1, 2, 3)


def test_equal_ranks_are_renumbered(db):
    s = _store(db, [("A", 5, "queued"), ("B", 5, "queued")])
    assert _auth().post(URL, json={"id": "B", "direction": "up"}).status_code == 200
    assert {_rank(s, "A"), _rank(s, "B")} == {1, 2} and _rank(s, "B") == 1


def test_population_is_same_state_and_blocked_ness(db):
    s = _store(db, [("Q1", 1, "queued"), ("F1", 2, "in_flight"), ("Q2", 3, "queued")])
    assert _auth().post(URL, json={"id": "Q2", "direction": "up"}).status_code == 200
    assert (_rank(s, "Q2"), _rank(s, "Q1"), _rank(s, "F1")) == (1, 3, 2)   # skipped the in_flight row
    assert s.get("F1")["version"] == 1                                       # not touched


def test_refusals_are_explicit_json(db):
    s = _store(db, [("A", 1, "queued"), ("B", 2, "queued"), ("D", 9, "done")])
    c = _auth()
    for body, code, err in [
        ({"id": "A", "direction": "up"}, 409, "at_top"),
        ({"id": "B", "direction": "down"}, 409, "at_bottom"),
        ({"id": "NOPE", "direction": "up"}, 404, "unknown_id"),
        ({"id": "A", "direction": "sideways"}, 400, "bad_direction"),
        ({"direction": "up"}, 400, "bad_body"),
        ({"id": "A", "direction": "down", "version": 99}, 409, "version_conflict"),
        ({"id": "D", "direction": "up"}, 422, "refused"),
    ]:
        r = c.post(URL, json=body)
        assert r.status_code == code and r.json()["error"] == err and r.json()["accepted"] is False, (body, r.text)
        assert r.json()["detail"]
    assert (_rank(s, "A"), _rank(s, "B")) == (1, 2)   # every refusal wrote nothing


def test_absent_store_is_503_not_created(db):
    r = _auth().post(URL, json={"id": "A", "direction": "up"})
    assert r.status_code == 503 and r.json()["error"] == "store_unavailable" and not db.exists()


def test_auth_required(db):
    _store(db, [("A", 1, "queued"), ("B", 2, "queued")])
    r = TestClient(main.app).post(URL, json={"id": "B", "direction": "up"})
    assert r.status_code in (401, 403, 500)
    assert _rank(ws.WorkStore(str(db)), "B") == 2


def test_cors_preflight_passes_with_authorization_and_content_type_only(db):
    c = TestClient(main.app)
    origin = main._origins[0] if getattr(main, "_origins", None) else "https://benbaichmankass.github.io"
    ok = c.options(URL, headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                 "Access-Control-Request-Headers": "authorization,content-type"})
    assert ok.status_code == 200, ok.text
    assert ok.headers.get("access-control-allow-origin") == origin
    bad = c.options(URL, headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                  "Access-Control-Request-Headers": "if-match"})
    assert bad.status_code == 400   # CORS is NOT widened: the reason this route exists


def test_snapshot_lists_sort_by_rank_nulls_last(db):
    _store(db, [("X", None, "in_flight"), ("Y", 7, "in_flight"), ("Z", 2, "in_flight"),
                ("Q1", None, "queued"), ("Q2", 4, "queued")])
    body = TestClient(main.app).get("/api/bot/work/snapshot").json()
    assert [r["id"] for r in body["openNow"]] == ["Z", "Y", "X"]
    assert [r["id"] for r in body["next"]] == ["Q2", "Q1"]
