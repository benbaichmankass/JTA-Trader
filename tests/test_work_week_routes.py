"""UI-WQ-WEEK-ROUTES: GET /api/bot/work/items filters + counts + latest_note, and GET /api/bot/work/lanes."""
import pytest
from fastapi.testclient import TestClient

from src.runtime import work_store as ws


def _b(i, **over):
    d = {"id": i, "kind": "build", "title": f"title {i}", "state": "queued",
         "due_rule": {"kind": "date", "due_date": "2026-11-20"}, "roadmap": ["L-OPS"]}
    d.update(over)
    return d


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "w.db"
    monkeypatch.setenv("WORK_STORE_DB", str(db))
    s = ws.WorkStore(db)
    s.create(_b("UI-A", owner="AM-UI (session_x)", extra={"week_lane": "surge"}, priority_rank=2), by="t")
    s.create(_b("UI-B", owner="AM-UI (session_x)", state="in_flight", extra={"week_lane": "surge"}), by="t")
    s.create(_b("ML-A", owner="AM-ML (session_y)", state="blocked", extra={"week_lane": "throttle"}), by="t")
    s.create(_b("OPS-DONE", owner="AM-OPS", state="done", extra={"week_lane": "surge"}), by="t")
    s.create(_b("MGR-1", owner="manager", title="needle in the title"), by="t")
    v = s.get("UI-A")["version"]
    s.note("UI-A", "first note", by="t", expected_version=v)
    v = s.get("UI-A")["version"]
    s.note("UI-A", "latest says haystack", by="t", expected_version=v)
    from src.web.api.main import app
    return TestClient(app)


def _ids(r):
    return sorted(i["id"] for i in r.json()["items"])


def test_state_open_excludes_terminal(client):
    r = client.get("/api/bot/work/items?state=open")
    assert r.status_code == 200 and "OPS-DONE" not in _ids(r) and len(_ids(r)) == 4


def test_owner_prefix_week_lane_and_q(client):
    assert _ids(client.get("/api/bot/work/items?owner_prefix=AM-UI")) == ["UI-A", "UI-B"]
    assert _ids(client.get("/api/bot/work/items?week_lane=throttle")) == ["ML-A"]
    assert _ids(client.get("/api/bot/work/items?q=needle")) == ["MGR-1"]          # title
    assert _ids(client.get("/api/bot/work/items?q=haystack")) == ["UI-A"]         # latest note
    assert _ids(client.get("/api/bot/work/items?q=ui-b")) == ["UI-B"]             # id, case-insensitive


def test_counts_cover_the_whole_filtered_set_not_the_page(client):
    r = client.get("/api/bot/work/items?state=open&counts=1&limit=1").json()
    assert r["returned"] == 1 and r["matched"] == 4
    by = r["counts"]["by_owner_state"]
    assert by["AM-UI"] == {"queued": 1, "in_flight": 1} and by["AM-ML"] == {"blocked": 1}
    assert by["other"] == {"queued": 1}


def test_latest_note_is_the_newest_note_or_none(client):
    items = {i["id"]: i for i in client.get("/api/bot/work/items?latest_note=1").json()["items"]}
    assert items["UI-A"]["latest_note"]["note"] == "latest says haystack"
    assert items["MGR-1"]["latest_note"] is None


def test_bad_state_is_400_and_plain_call_unchanged(client):
    assert client.get("/api/bot/work/items?state=bogus").status_code == 400
    plain = client.get("/api/bot/work/items").json()
    assert "counts" not in plain and "matched" not in plain and plain["total"] == 5


def test_lanes_cards(client):
    r = client.get("/api/bot/work/lanes").json()
    assert r["read_state"] == "read"
    lanes = {ln["am"]: ln for ln in r["lanes"]}
    ui = lanes["AM-UI"]
    assert ui["working_now"]["count"] == 1 and ui["working_now"]["items"][0]["id"] == "UI-B"
    assert ui["next"]["items"][0]["id"] == "UI-A"
    assert lanes["AM-ML"]["stuck"]["count"] == 1
    # every item was created today, so each moved today
    assert ui["moved_today"]["count"] == 2 and ui["headline"] is None and ui["headline_read_state"] == "absent"
    assert r["week_lanes"]["surge"]["total"] == 3 and r["week_lanes"]["surge"]["by_state"]["done"] == 1
    assert list(lanes)[-1] == "other"


def test_unreadable_store_is_503_never_empty(client, monkeypatch):
    from src.web.api.routers import work_items as wi

    def boom():
        raise RuntimeError("db gone")
    monkeypatch.setattr(wi, "_store", boom)
    r = client.get("/api/bot/work/lanes")
    assert r.status_code == 503 and r.json()["lanes"] is None
    r2 = client.get("/api/bot/work/items?state=open&counts=1")
    assert r2.status_code == 503 and r2.json()["items"] is None
