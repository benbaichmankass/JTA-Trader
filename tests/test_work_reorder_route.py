"""WORK-REORDER-ROUTE: POST /api/bot/work/reorder (session-gated, writes only the moved row) + snapshot order."""
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
    """rows: (id, rank, state); register order (extra._seq) follows list order, as an imported register's."""
    s = ws.WorkStore(str(path))
    for n, (rid, rank, state) in enumerate(rows, start=1):
        f = {"id": rid, "kind": "build", "title": rid, "state": state, "owner": "m", "extra": {"_seq": n}}
        if rank is not None:
            f["priority_rank"] = rank
        s.create(f, by="test")
    return s


def _snap(s):
    return {r["id"]: (r["priority_rank"], (r.get("extra") or {}).get("queue_pos"), r["version"])
            for r in s.list_items(kind="build", limit=10 ** 6)}


def _order(s, ids=None):
    from src.web.api.work_reorder import display_key
    rows = [r for r in s.list_items(kind="build", limit=10 ** 6) if ids is None or r["id"] in ids]
    return [r["id"] for r in sorted(rows, key=display_key)]


def _press(c, body):
    r = c.post(URL, json=body)
    return r


def _auth():
    main.app.dependency_overrides[require_session] = lambda: {"email": "operator"}
    return TestClient(main.app)


def _rank(s, rid):
    return s.get(rid)["priority_rank"]


def test_a_move_writes_only_the_moved_row_and_never_touches_other_ranks(db):
    # Rank is a priority CLASS shared by many rows: A,B,C all class 2; X class 3.
    s = _store(db, [("A", 2, "queued"), ("B", 2, "queued"), ("C", 2, "queued"), ("X", 3, "queued")])
    before = _snap(s)
    r = _auth().post(URL, json={"id": "C", "direction": "up", "over": "B"})
    assert r.status_code == 200, r.text
    after = _snap(s)
    assert r.json()["changed"] == ["C"]
    assert [i for i in before if after[i][2] != before[i][2]] == ["C"]          # one row written
    assert all(after[i][0] == before[i][0] for i in before)                      # every rank unchanged
    assert _order(s) == ["A", "C", "B", "X"]
    assert s.get("C")["updated_by"] == "operator-spa"


def test_down_and_edges_use_neighbour_plus_minus_one(db):
    s = _store(db, [("A", 2, "queued"), ("B", 2, "queued")])
    assert _auth().post(URL, json={"id": "A", "direction": "down", "over": "B"}).status_code == 200
    assert _order(s) == ["B", "A"] and _snap(s)["A"][1] == 3.0                    # B's pos 2, +1 at the edge
    assert _auth().post(URL, json={"id": "A", "direction": "up", "over": "B"}).status_code == 200
    assert _order(s) == ["A", "B"] and _snap(s)["A"][1] == 1.0


def test_cross_class_move_takes_overs_rank(db):
    s = _store(db, [("A", 1, "queued"), ("B", 3, "queued"), ("C", 3, "queued")])
    r = _auth().post(URL, json={"id": "A", "direction": "down", "over": "C"})      # A leaves class 1 for class 3
    assert r.status_code == 200 and r.json()["changed"] == ["A"]
    snap = _snap(s)
    assert snap["A"][0] == 3 and snap["B"][0] == 3 and snap["C"][0] == 3
    assert _order(s) == ["B", "C", "A"]
    # ...and back up across the boundary: directly above B, in class 3 still (rank := over's rank).
    assert _auth().post(URL, json={"id": "A", "direction": "up", "over": "B"}).status_code == 200
    assert _order(s) == ["A", "B", "C"]


def test_null_queue_pos_uses_register_order_and_null_rank_class(db):
    s = _store(db, [("A", None, "queued"), ("B", None, "queued"), ("C", None, "queued"), ("R", 1, "queued")])
    assert [r for r in _order(s)] == ["R", "A", "B", "C"]
    r = _auth().post(URL, json={"id": "C", "direction": "up", "over": "A"})        # null class: rank stays null
    assert r.status_code == 200 and r.json()["changed"] == ["C"]
    assert _order(s) == ["R", "C", "A", "B"] and _snap(s)["C"][0] is None
    # a null-rank row moved over a ranked row takes that rank
    assert _auth().post(URL, json={"id": "B", "direction": "down", "over": "R"}).status_code == 200
    assert _snap(s)["B"][0] == 1 and _order(s)[:2] == ["R", "B"]


def test_hidden_row_between_does_not_matter(db):
    # The card shows A, B, C; X (in_flight, hidden) sits between them in the full order.
    s = _store(db, [("A", 2, "queued"), ("X", 2, "in_flight"), ("B", 2, "queued"), ("C", 2, "queued")])
    assert _auth().post(URL, json={"id": "C", "direction": "up", "over": "A"}).status_code == 200
    o = _order(s)
    assert o.index("C") + 1 == o.index("A")                                        # directly above A


def test_repeated_moves_converge_and_cost_at_most_two_writes(db):
    import random
    ids = [f"R{i}" for i in range(8)]
    s = _store(db, [(i, 2, "queued") for i in ids])
    c, rnd = _auth(), random.Random(7)
    for _ in range(60):
        a, b = rnd.sample(ids, 2)
        d = rnd.choice(["up", "down"])
        before_ev = len(s.events())
        before = _order(s)
        r = c.post(URL, json={"id": a, "direction": d, "over": b})
        assert r.status_code in (200, 409), r.text
        if r.status_code == 200:
            assert len(s.events()) - before_ev <= 2 and len(r.json()["changed"]) <= 2
            o = _order(s)
            assert o.index(a) == (o.index(b) - 1 if d == "up" else o.index(b) + 1), (a, d, b, o)
            assert sorted(o) == sorted(before)
        else:
            assert r.json()["error"] == "no_change" and _order(s) == before
    assert all(v[0] == 2 for v in _snap(s).values())                               # class never disturbed


def test_equal_positions_get_room_with_a_second_write(db):
    s = _store(db, [("A", 2, "queued"), ("B", 2, "queued"), ("C", 2, "queued")])
    for rid in ("A", "B"):                                                          # same queue_pos on two rows
        it = s.get(rid)
        s.set(rid, {"extra": {**it["extra"], "queue_pos": 5.0}}, by="test", expected_version=it["version"])
    r = _auth().post(URL, json={"id": "C", "direction": "up", "over": "B"})
    assert r.status_code == 200 and len(r.json()["changed"]) == 2
    o = _order(s)
    assert o.index("C") + 1 == o.index("B")


def test_no_over_moves_within_the_rows_own_list(db):
    s = _store(db, [("Q1", 1, "queued"), ("F1", 2, "in_flight"), ("Q2", 3, "queued")])
    r = _auth().post(URL, json={"id": "Q2", "direction": "up"})
    assert r.status_code == 200 and r.json()["over"] == "Q1" and r.json()["changed"] == ["Q2"]
    assert _snap(s)["F1"][2] == 1 and _order(s, {"Q1", "Q2"}) == ["Q2", "Q1"]
    assert _auth().post(URL, json={"id": "Q2", "direction": "up"}).json()["error"] == "at_top"
    assert _auth().post(URL, json={"id": "Q1", "direction": "down"}).json()["error"] == "at_bottom"


def test_refusals_are_explicit_json_and_write_nothing(db):
    s = _store(db, [("A", 1, "queued"), ("B", 2, "queued"), ("D", 9, "done")])
    before = _snap(s)
    c = _auth()
    for body, code, err in [
        ({"id": "A", "direction": "up", "over": "A"}, 400, "same_id"),
        ({"id": "A", "direction": "up", "over": "NOPE"}, 404, "unknown_over"),
        ({"id": "NOPE", "direction": "up", "over": "A"}, 404, "unknown_id"),
        ({"id": "NOPE", "direction": "up"}, 404, "unknown_id"),
        ({"id": "A", "direction": "up", "over": "D"}, 422, "refused"),
        ({"id": "D", "direction": "up", "over": "A"}, 422, "refused"),
        ({"id": "A", "direction": "up", "over": "B"}, 409, "no_change"),
        ({"id": "B", "direction": "up", "over": "A", "version": 99}, 409, "version_conflict"),
        ({"id": "A", "direction": "sideways", "over": "B"}, 400, "bad_direction"),
        ({"direction": "up"}, 400, "bad_body"),
        ({"id": "A", "direction": "up", "over": 5}, 400, "bad_body"),
    ]:
        r = c.post(URL, json=body)
        assert r.status_code == code and r.json()["error"] == err and r.json()["accepted"] is False, (body, r.text)
        assert r.json()["detail"]
    assert _snap(s) == before


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


def test_snapshot_lists_sort_by_the_same_key(db):
    s = _store(db, [("X", None, "in_flight"), ("Y", 7, "in_flight"), ("Z", 2, "in_flight"),
                    ("Q1", 3, "queued"), ("Q2", 3, "queued"), ("Q3", None, "queued")])
    c = _auth()
    body = c.get("/api/bot/work/snapshot").json()
    assert [r["id"] for r in body["openNow"]] == ["Z", "Y", "X"]
    assert [r["id"] for r in body["next"]] == ["Q1", "Q2", "Q3"]
    assert c.post(URL, json={"id": "Q2", "direction": "up", "over": "Q1"}).status_code == 200
    work_router._snapshot_cache = None
    body = c.get("/api/bot/work/snapshot").json()
    assert [r["id"] for r in body["next"]] == ["Q2", "Q1", "Q3"]                    # a move shows on the card
    assert body["next"][0]["queuePos"] is not None
