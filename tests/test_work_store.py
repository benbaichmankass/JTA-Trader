"""WSD-S1-STORE-API: the work store -- validator parity, hash chain, 409, and the 503/401/201 gate.

Parity is tested against the LEGACY validators themselves (``checklist_store.filing_problems``
+ ``fill_defaults`` and ``pipeline.validate``) on the same inputs: the store must refuse
exactly what they refuse, and accept exactly what they accept (design G1, "tightens none").
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from scripts.ops import pipeline
from src.runtime import checklist_store as cs
from src.runtime import work_store as ws

TODAY = date(2026, 11, 5)


@pytest.fixture()
def store(tmp_path):
    return ws.WorkStore(tmp_path / "work_store.db")


def _build(**over):
    d = {"id": "WSD-TEST-1", "kind": "build", "title": "a build", "state": "queued",
         "due_rule": {"kind": "date", "due_date": "2026-11-09"}, "roadmap": ["L-OPS"]}
    d.update(over)
    return d


def _obs(**over):
    d = {"id": "PI-TEST-1", "kind": "observation", "title": "observe x",
         "origin": {"kind": "session", "ref": "s1", "rerun": "python3 x.py"},
         "due_rule": {"kind": "date", "due_date": "2026-11-07"}, "next_action": "check_observation",
         "state": "queued"}
    d.update(over)
    return d


# ── validator parity ───────────────────────────────────────────────────────────


def test_path_is_a_separate_file_beside_the_journal(monkeypatch, tmp_path):
    from src.utils import paths
    monkeypatch.delenv("WORK_STORE_DB", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "x" / "trade_journal.db"))
    assert paths.work_store_db_path() == str(tmp_path / "x" / "work_store.db")
    monkeypatch.setenv("WORK_STORE_DB", str(tmp_path / "w.db"))
    assert paths.work_store_db_path() == str(tmp_path / "w.db")


def test_wal_mode(store):
    with sqlite3.connect(store.path) as c:
        assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_build_fill_defaults_match_checklist(store):
    """checklist.py add fills owner / due_by / roadmap rather than refusing; so does the store."""
    out = store.create({"id": "B-1", "kind": "build", "title": "t", "state": "queued", "priority_rank": 2},
                       by="t", today=TODAY)["item"]
    row = {"id": "B-1", "title": "t", "state": "queued", "owner": None, "due_by": None, "roadmap": None,
           "priority_rank": 2}
    cs.fill_defaults(row, TODAY)
    assert out["owner"] == row["owner"] == "manager"
    assert out["due_rule"]["due_date"] == row["due_by"]
    assert out["roadmap"] == row["roadmap"] == ["unmapped"]
    assert cs.filing_problems(row) == []


@pytest.mark.parametrize("roadmap,reason", [
    (["unmapped", "L-OPS"], None),          # mixes unmapped with milestones
    (["unmapped"], "short"),                # reason < 10 chars
])
def test_build_refusals_match_filing_problems(store, roadmap, reason):
    row = {"state": "queued", "owner": "manager", "due_by": "2026-11-09", "roadmap": roadmap,
           "roadmap_unmapped_reason": reason}
    legacy = cs.filing_problems(row)
    assert legacy, "positive control: the legacy validator refuses this"
    with pytest.raises(ws.WorkStoreValidationError) as e:
        store.create(_build(roadmap=roadmap, roadmap_unmapped_reason=reason), by="t", today=TODAY)
    assert legacy[0] in str(e.value)


def test_build_set_refuses_clearing_like_checklist_set(store):
    v = store.create(_build(), by="t", today=TODAY)["item"]["version"]
    with pytest.raises(ws.WorkStoreValidationError, match="refuses to clear `roadmap`"):
        store.set("WSD-TEST-1", {"roadmap": []}, by="t", expected_version=v, today=TODAY)


def test_build_may_be_set_done_without_reason_as_today(store):
    v = store.create(_build(), by="t", today=TODAY)["item"]["version"]
    out = store.set("WSD-TEST-1", {"state": "done"}, by="t", expected_version=v, today=TODAY)["item"]
    assert out["state"] == "done" and out["due_at"] is None


OBS_CASES = [
    {},                                                                       # valid
    {"origin": {"kind": "session", "ref": "s1"}},                             # no rerun (reason 3)
    {"origin": {"kind": "nope", "ref": "s", "rerun": "r"}},
    {"due_rule": {"kind": "observation"}},                                    # no clears_when (reason 2)
    {"due_rule": {"kind": "date", "due_date": "11/07/2026"}},
    {"due_rule": {"kind": "observation", "clears_when": "x", "check_every_days": 0}},
    {"state": "done"},                                                        # no terminal_reason (reason 4)
    {"state": "queued", "terminal_reason": "closed?"},                        # reason on open state
    {"next_action": None},
    {"state": "in_flight"},                                                   # not a pipeline state
]


@pytest.mark.parametrize("over", OBS_CASES)
def test_observation_parity_with_pipeline_validate(store, over):
    item = _obs(**over)
    try:
        pipeline.validate(ws._as_pipeline_item(item))
        legacy_ok = True
    except pipeline.PipelineError:
        legacy_ok = False
    try:
        store.create(item, by="t", today=TODAY)
        store_ok = True
    except ws.WorkStoreValidationError:
        store_ok = False
    assert store_ok == legacy_ok, over


def test_observation_routed_maps_parent(store):
    store.create(_build(), by="t", today=TODAY)
    out = store.create(_obs(parent_id="WSD-TEST-1"), by="t", today=TODAY)["item"]
    assert ws._as_pipeline_item(out)["state"] == "routed"
    assert ws._as_pipeline_item(out)["routed_to"] == "WSD-TEST-1"


# ── due_at is computed, never accepted ─────────────────────────────────────────


def test_due_at_is_never_accepted_from_a_caller(store):
    with pytest.raises(ws.WorkStoreValidationError, match="computed by the store"):
        store.create(_build(due_at="2000-01-01T00:00:00Z"), by="t", today=TODAY)


def test_due_at_computed(store):
    assert store.create(_build(), by="t", today=TODAY)["item"]["due_at"] == "2026-11-09T00:00:00Z"
    o = store.create(_obs(), by="t", today=TODAY)["item"]
    assert o["due_at"] == "2026-11-07T00:00:00Z"
    # an observation with no cadence is always due (pipeline.is_due) -> due_at = now
    a = store.create(_obs(id="PI-TEST-2", due_rule={"kind": "observation", "clears_when": "x"}),
                     by="t", today=TODAY)["item"]
    assert a["due_at"] == a["created_at"]
    due_ids = {i["id"] for i in store.list_items(due=True)}
    assert "PI-TEST-2" in due_ids


# ── hash chain ─────────────────────────────────────────────────────────────────


def test_hash_chain_links_and_detects_tamper(store):
    v = store.create(_build(), by="t", today=TODAY)["item"]["version"]
    v = store.note("WSD-TEST-1", "hello", by="t", expected_version=v)["item"]["version"]
    store.close("WSD-TEST-1", state="done", reason="finished", by="t", expected_version=v)
    evs = store.events("WSD-TEST-1")
    assert [e["op"] for e in evs] == ["create", "note", "close"]
    assert evs[0]["prev_hash"] == ws.GENESIS_HASH
    assert all(evs[i]["prev_hash"] == evs[i - 1]["hash"] for i in range(1, 3))
    assert store.verify_chain()["ok"] is True
    # append-only: UPDATE/DELETE are refused by trigger
    with sqlite3.connect(store.path) as c, pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE events SET patch='{}' WHERE seq=2")
    # a silent edit (bypassing the trigger) breaks the chain at that seq
    with sqlite3.connect(store.path) as c:
        c.execute("DROP TRIGGER events_no_update")
        c.execute("""UPDATE events SET patch='{"note":"forged"}' WHERE seq=2""")
    chk = store.verify_chain()
    assert chk["ok"] is False and chk["broken_at"] == 2


def test_op_id_replay_is_a_noop(store):
    a = store.create(_build(), by="t", op_id="op-1", today=TODAY)
    b = store.create(_build(), by="t", op_id="op-1", today=TODAY)
    assert b["replayed"] is True and b["item"]["version"] == a["item"]["version"]
    assert len(store.events()) == 1


# ── optimistic concurrency ─────────────────────────────────────────────────────


def test_stale_version_is_409(store):
    store.create(_build(), by="t", today=TODAY)
    store.set("WSD-TEST-1", {"summary": "x"}, by="a", expected_version=1)
    with pytest.raises(ws.ConflictError) as e:
        store.set("WSD-TEST-1", {"summary": "y"}, by="b", expected_version=1)
    assert e.value.current["version"] == 2 and e.value.current["summary"] == "x"


# ── the API: 503 / 401 / 201 / 409 ─────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORK_STORE_DB", str(tmp_path / "api_work_store.db"))
    from src.web.api.main import app
    return TestClient(app)


BODY = {"id": "WSD-API-1", "kind": "build", "title": "api", "state": "queued",
        "due_rule": {"kind": "date", "due_date": "2026-11-09"}, "roadmap": ["L-OPS"], "by": "test"}


def test_api_503_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("WORK_STORE_TOKEN", raising=False)
    assert client.post("/api/bot/work/items", json=BODY).status_code == 503


def test_api_401_without_or_wrong_token(client, monkeypatch):
    monkeypatch.setenv("WORK_STORE_TOKEN", "secret")
    assert client.post("/api/bot/work/items", json=BODY).status_code == 401
    assert client.post("/api/bot/work/items", json=BODY,
                       headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/api/bot/work/items", json=BODY,
                       headers={"Authorization": "Basic secret"}).status_code == 401


def test_api_other_tokens_are_not_accepted(client, monkeypatch):
    """Write-scoped: DASHBOARD_API_TOKEN does not open this route."""
    monkeypatch.setenv("WORK_STORE_TOKEN", "secret")
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "dash")
    assert client.post("/api/bot/work/items", json=BODY,
                       headers={"Authorization": "Bearer dash"}).status_code == 401


def test_api_201_then_read_then_409(client, monkeypatch):
    monkeypatch.setenv("WORK_STORE_TOKEN", "secret")
    auth = {"Authorization": "Bearer secret"}
    r = client.post("/api/bot/work/items", json=BODY, headers=auth)
    assert r.status_code == 201, r.text
    assert r.json()["item"]["version"] == 1 and r.headers["ETag"] == "1"
    # reads are open
    got = client.get("/api/bot/work/items").json()
    assert got["readState"] == "read" and [i["id"] for i in got["items"]] == ["WSD-API-1"]
    ev = client.get("/api/bot/work/items/WSD-API-1/events").json()
    assert ev["chain"]["ok"] is True and ev["events"][0]["op"] == "create"
    # set with the right version, then a stale one -> 409 with the current item
    r = client.post("/api/bot/work/items/WSD-API-1/set", json={"fields": {"summary": "a"}, "by": "x"},
                    headers={**auth, "If-Match": "1"})
    assert r.status_code == 200 and r.json()["item"]["version"] == 2
    r = client.post("/api/bot/work/items/WSD-API-1/set", json={"fields": {"summary": "b"}, "by": "y"},
                    headers={**auth, "If-Match": "1"})
    assert r.status_code == 409 and r.json()["current"]["version"] == 2
    # no If-Match at all is refused, not last-write-wins
    r = client.post("/api/bot/work/items/WSD-API-1/note", json={"text": "n", "by": "x"}, headers=auth)
    assert r.status_code == 422
    r = client.post("/api/bot/work/items/WSD-API-1/close", json={"state": "done", "reason": "ok", "by": "x"},
                    headers={**auth, "If-Match": "2"})
    assert r.status_code == 200 and r.json()["item"]["state"] == "done"
    # a refusal from the carried-over validator is 422
    bad = dict(BODY, id="WSD-API-2", roadmap=["unmapped", "L-OPS"])
    assert client.post("/api/bot/work/items", json=bad, headers=auth).status_code == 422
    # a duplicate create is 409
    assert client.post("/api/bot/work/items", json=dict(BODY, op_id=None), headers=auth).status_code == 409


# ── WSD-S1-PROXY-AUTH-COLLISION: the dedicated X-Work-Store-Token header ────────


def test_api_x_work_store_token_header_is_accepted(client, monkeypatch):
    monkeypatch.setenv("WORK_STORE_TOKEN", "secret")
    r = client.post("/api/bot/work/items", json=dict(BODY, id="WSD-HDR-1"),
                    headers={"X-Work-Store-Token": "secret"})
    assert r.status_code == 201, r.text
    # the header also carries set/note/close
    r = client.post("/api/bot/work/items/WSD-HDR-1/note", json={"text": "n", "by": "x"},
                    headers={"X-Work-Store-Token": "secret", "If-Match": "1"})
    assert r.status_code == 200, r.text


def test_api_bearer_fallback_still_accepted(client, monkeypatch):
    """Deprecated carrier, kept while the environment secret moves headers."""
    monkeypatch.setenv("WORK_STORE_TOKEN", "secret")
    r = client.post("/api/bot/work/items", json=dict(BODY, id="WSD-HDR-2"),
                    headers={"Authorization": "Bearer secret"})
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("headers,detail", [
    ({"X-Work-Store-Token": "nope"}, "bad token"),
    ({"X-Work-Store-Token": "   "}, "empty X-Work-Store-Token"),
    # the dedicated header alone decides: a right Bearer does not rescue a wrong header
    ({"X-Work-Store-Token": "nope", "Authorization": "Bearer secret"}, "bad token"),
    ({}, "missing authorization"),
])
def test_api_header_401_paths(client, monkeypatch, headers, detail):
    monkeypatch.setenv("WORK_STORE_TOKEN", "secret")
    r = client.post("/api/bot/work/items", json=dict(BODY, id="WSD-HDR-401"), headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == detail


def test_api_header_does_not_open_writes_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("WORK_STORE_TOKEN", raising=False)
    r = client.post("/api/bot/work/items", json=BODY, headers={"X-Work-Store-Token": "anything"})
    assert r.status_code == 503


def test_api_header_ignores_a_foreign_bearer_in_authorization(client, monkeypatch):
    """The point of the fix: a session's own Authorization (e.g. DIAG_READ_TOKEN) can ride
    alongside the work-store header without either clobbering the other."""
    monkeypatch.setenv("WORK_STORE_TOKEN", "secret")
    r = client.post("/api/bot/work/items", json=dict(BODY, id="WSD-HDR-3"),
                    headers={"X-Work-Store-Token": "secret", "Authorization": "Bearer diag-token"})
    assert r.status_code == 201, r.text


# ── a closed build created without a roadmap: 500 on the live API, 2026-11-05T07:43Z ──


@pytest.mark.parametrize("state", ["done", "dropped"])
def test_terminal_build_without_roadmap_is_filled_not_500(store, state):
    out = store.create({"id": f"T-{state}", "kind": "build", "title": "closed", "state": state},
                       by="t", today=TODAY)
    assert out["item"]["roadmap"] == ["unmapped"]
    assert len(out["item"]["roadmap_unmapped_reason"]) >= 10
    import json
    assert 'roadmap=["unmapped"]' in json.loads(out["event"]["patch"])["filled"]


def test_store_constraint_is_a_422_not_a_500(store, monkeypatch):
    """Any schema constraint the validator misses surfaces as WorkStoreValidationError."""
    monkeypatch.setattr(ws, "_validate", lambda item, prior, today: item.__setitem__("title", None) or [])
    with pytest.raises(ws.WorkStoreValidationError, match="store constraint"):
        store.create(_build(id="C-1"), by="t", today=TODAY)
    assert store.count_items() == 0 and store.events() == []


def test_api_terminal_build_without_roadmap_is_201(client, monkeypatch):
    monkeypatch.setenv("WORK_STORE_TOKEN", "secret")
    r = client.post("/api/bot/work/items", headers={"X-Work-Store-Token": "secret"},
                    json={"id": "WSD-T-1", "kind": "build", "title": "probe", "state": "dropped", "by": "t"})
    assert r.status_code == 201, r.text


# ── week_lane writable (WORK-STORE-WEEK-LANE-WRITABLE) ──────────────────────────


def test_week_lane_writable_on_create_and_set_and_flows_to_row(store):
    from src.runtime import work_store_import as wsi
    it = store.create(_build(week_lane="surge", extra={"note": "n"}), by="t", today=TODAY)["item"]
    assert it["extra"] == {"note": "n", "week_lane": "surge"}
    it = store.set("WSD-TEST-1", {"week_lane": "throttle"}, by="t", expected_version=it["version"],
                   today=TODAY)["item"]
    assert it["extra"] == {"note": "n", "week_lane": "throttle"}
    assert wsi.to_row(it)["week_lane"] == "throttle"
    it = store.set("WSD-TEST-1", {"week_lane": None}, by="t", expected_version=it["version"],
                   today=TODAY)["item"]
    assert it["extra"] == {"note": "n"}


@pytest.mark.parametrize("bad", ["Surge", "", "weekly", 3])
def test_week_lane_refuses_unknown_values(store, bad):
    it = store.create(_build(), by="t", today=TODAY)["item"]
    with pytest.raises(ws.WorkStoreValidationError, match="week_lane"):
        store.set("WSD-TEST-1", {"week_lane": bad}, by="t", expected_version=it["version"], today=TODAY)


def test_other_unknown_keys_still_refused(store):
    it = store.create(_build(), by="t", today=TODAY)["item"]
    with pytest.raises(ws.WorkStoreValidationError, match="not writable"):
        store.set("WSD-TEST-1", {"bogus": 1}, by="t", expected_version=it["version"], today=TODAY)


def test_row_with_extra_week_lane_is_served_with_week_lane(store):
    """A build item whose extra holds week_lane reaches the served checklist row, the loader's
    row and the route's per-row ``fields`` (the route nests every key verbatim under ``fields``)."""
    from src.runtime import work_read
    from src.web.api.routers import work as work_router
    store.create(_build(extra={"week_lane": "throttle", "note": "n"}), by="t", today=TODAY)
    rows = work_read.checklist_rows(store)
    assert [r["week_lane"] for r in rows] == ["throttle"]
    item = work_router._checklist_item(rows[0], vocabulary=("queued",), registered=None)
    assert item["fields"]["week_lane"] == "throttle"


@pytest.mark.parametrize("lane", ["surge", "throttle", "after_reset", "standing"])
def test_week_lane_accepts_after_reset_and_keeps_standing(store, lane):
    it = store.create(_build(), by="t", today=TODAY)["item"]
    out = store.set("WSD-TEST-1", {"week_lane": lane}, by="t", expected_version=it["version"], today=TODAY)["item"]
    assert out["extra"]["week_lane"] == lane


def test_api_meta_set_get_needs_token(client, monkeypatch):
    """WSD-S4-READERS-FLIP: the register header's last_review lives in the store."""
    monkeypatch.setenv("WORK_STORE_TOKEN", "secret")
    assert client.get("/api/bot/work/meta/last_review").status_code == 404
    assert client.post("/api/bot/work/meta/last_review", json={"value": {"a": 1}, "by": "x"}).status_code == 401
    h = {"X-Work-Store-Token": "secret"}
    r = client.post("/api/bot/work/meta/last_review", json={"value": {"a": 1}, "by": "x"}, headers=h)
    assert r.status_code == 200 and r.json()["meta"]["version"] == 1, r.text
    r = client.get("/api/bot/work/meta/last_review")
    assert r.json()["meta"]["value"] == {"a": 1}
    assert client.post("/api/bot/work/meta/items", json={"value": 1, "by": "x"}, headers=h).status_code == 422
