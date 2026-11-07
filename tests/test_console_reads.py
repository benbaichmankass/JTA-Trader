"""Console connector read path: reply sizes, research_queue, wake_toggles read (2026-11-07, console stuck on Waiting)."""
import json

from src.console_connector import server as s
from src.runtime import wake_toggles as wt


def test_initial_wake_switch_state(tmp_path):
    st = wt.read_local(tmp_path / "w.json")
    assert st["read_state"] == "defaults"
    assert st["toggles"] == {"desk_wake": False, "desk_trigger_wake": False, "short_hold": False,
                             "desk_could_not_build": False, "ltr_paper": False, "ltr_real_money": True,
                             "ltr_prop": True, "alert_watch": True}
    (tmp_path / "bad.json").write_text("{nope")
    bad = wt.read_local(tmp_path / "bad.json")
    assert bad["read_state"] == "could_not_look" and bad["toggles"] is None and wt.is_on("desk_wake", bad)


def test_get_route_reads_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("RUNTIME_STATE_DIR", str(tmp_path))
    from src.web.api.main import app
    c = TestClient(app)
    g = c.get("/api/bot/wake-toggles").json()
    assert g["read_state"] == "defaults" and len(g["rows"]) == 8
    assert c.post("/api/bot/wake-toggles", json={"key": "desk_wake", "on": True}).status_code == 405  # read-only here


def test_research_queue_tool():
    r = s.call_tool("research_queue", {"status": "blocked", "theme": "all", "limit": 5})
    assert r["read_state"] in ("read", "partial") and r["population"]["units_scanned"] > 0
    assert all(x["status"] == "blocked" for x in r["rows"])
    assert set(r["counts"]) == {"by_status", "by_theme_group", "by_compute"}


def test_connector_has_no_write_tool():
    names = [t["name"] for t in s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
    assert "set_wake_toggle" not in names and {"research_queue", "wake_toggles"} <= set(names)


def test_replies_stay_small_for_the_pages_calls():
    for name, args in [("work_rows", {"view": "all", "limit": 6}), ("workplan", {"limit": 6}), ("ml_roadmap", {"limit": 15}),
                       ("system_catalog", {"signals_limit": 10}), ("research_queue", {"status": "pipeline", "limit": 30}),
                       ("inbox", {"limit": 25})]:
        out = s.call_tool(name, args)
        assert len(json.dumps(out, default=str)) <= s.REPLY_BUDGET and "oversize" not in out, name
    wr = s.call_tool("work_rows", {"view": "in_flight", "limit": 3})["closed_this_week"]
    assert len(wr["rows"]) <= 15 and wr["population"]["closed_rows"] >= len(wr["rows"])
