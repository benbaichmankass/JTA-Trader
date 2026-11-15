"""Console connector: MCP envelope, read-only tool surface, collapsed states, shared cache budget."""
from __future__ import annotations

import json

from src.console_connector import data, server


def _call(name, args=None, mid=1):
    return server.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                          "params": {"name": name, "arguments": args or {}}})


def test_initialize_echoes_protocol_and_declares_tools():
    r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-03-26"}})
    assert r["result"]["protocolVersion"] == "2025-03-26"
    assert "tools" in r["result"]["capabilities"]


def test_notification_has_no_response():
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_every_tool_is_declared_read_only():
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in tools} == {"hello", "work_rows", "inbox", "work_items", "workplan", "ml_roadmap", "system_catalog",
                                      "research_queue", "wake_toggles"}  # set_wake_toggle only with sign-in + write token
    for t in tools:
        assert t["annotations"]["readOnlyHint"] is True
        assert t["annotations"]["destructiveHint"] is False


def test_unknown_tool_and_method_are_errors_not_empty_results():
    assert _call("drop_table")["error"]["code"] == -32602
    assert server.handle({"jsonrpc": "2.0", "id": 9, "method": "resources/list"})["error"]["code"] == -32601


def test_work_rows_reads_the_real_register_with_population():
    out = _call("work_rows", {"limit": 2})["result"]["structuredContent"]
    assert out["read_state"] == "read"
    pop = out["population"]
    assert pop["rows_scanned"] > 0 and pop["live_rows"] <= pop["rows_scanned"]
    assert set(out["sections"]) == {"due", "in_flight", "blocked", "queued", "open_other"}
    for name, rows in out["sections"].items():
        assert len(rows) <= 2
        assert pop["truncated"][name] == (pop["counts"][name] > 2)
        for r in rows:
            assert r["state"] in data.LIVE_STATES


def test_work_rows_unreadable_register_is_could_not_look(tmp_path, monkeypatch):
    def boom(repo):
        raise OSError("checklist unreadable")
    monkeypatch.setattr(data, "_load_checklist", boom)
    out = data.work_rows(tmp_path)
    assert out["read_state"] == "could_not_look"
    assert out["population"]["rows_scanned"] is None
    assert out["sections"] == {}


def test_inbox_unserved_sections_say_could_not_look_never_zero():
    out = _call("inbox", {"limit": 1})["result"]["structuredContent"]
    alerts = out["sections"]["alerts"]
    assert alerts["read_state"] == "could_not_look" and alerts["count"] is None
    assert out["sections"]["decisions_checklist"]["read_state"] == "read"


def test_work_items_upstream_down_is_could_not_look_never_empty(monkeypatch):
    from src.console_connector import tabs

    def down(*a):
        raise OSError("connection refused")
    monkeypatch.setattr(tabs, "FETCH", down)
    monkeypatch.setattr(server, "CACHE", data.TTLCache())
    wi = _call("work_items", {"view": "due", "limit": 3})["result"]["structuredContent"]
    assert wi["read_state"] == "could_not_look" and wi["count"] is None and wi["items"] is None


def test_shared_cache_builds_each_key_once_per_ttl():
    t = [0.0]
    c = data.TTLCache(clock=lambda: t[0])
    n = {"builds": 0}

    def build():
        n["builds"] += 1
        return n["builds"]
    assert c.get("k", 30, build) == 1
    t[0] = 10
    assert c.get("k", 30, build) == 1  # 100 viewers inside one TTL cost one build
    t[0] = 31
    assert c.get("k", 30, build) == 2
    assert n["builds"] == 2


def test_tool_result_is_json_text_and_structured():
    r = _call("hello", {"name": "t"})["result"]
    assert json.loads(r["content"][0]["text"]) == r["structuredContent"]
    assert r["structuredContent"]["hello"] == "hello, t"


def test_http_post_mcp_round_trip():
    """The real HTTP route, not just handle(): a JSON-RPC POST must reach the tool (regression: 422)."""
    from fastapi.testclient import TestClient

    client = TestClient(server.create_app())
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "hello", "arguments": {"name": "http"}}})
    assert r.status_code == 200
    assert r.json()["result"]["structuredContent"]["hello"] == "hello, http"
    assert client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    assert client.get("/mcp").status_code == 405


def test_work_rows_serves_week_lane_roadmap_writeback_and_undated_rows(monkeypatch, tmp_path):
    rows = [
        {"id": "A", "title": "a", "state": "queued", "week_lane": "surge", "roadmap": ["L-OPS"], "writeback": "w"},
        {"id": "B", "title": "b", "state": "queued", "roadmap": "none: planning lane"},  # no due date
        {"id": "C", "title": "c", "state": "landed_unproven"},
        {"id": "D", "title": "d", "state": "queued", "due_by": "2999-01-01"},
        {"id": "E", "title": "e", "state": "done"},
    ]
    monkeypatch.setattr(data, "_load_checklist", lambda repo: {"items": rows})
    out = data.work_rows(tmp_path, "all", 50)
    s = out["sections"]
    assert {r["id"] for r in s["open_other"]} == {"A", "B", "C"}   # queued without a due date + landed_unproven
    assert [r["id"] for r in s["queued"]] == ["D"]                 # dated queued rows stay in queued
    allrows = [r for sec in s.values() for r in sec]
    a = next(r for r in allrows if r["id"] == "A")
    assert a["week_lane"] == "surge" and a["roadmap"] == ["L-OPS"] and a["writeback"] == "w"
    b = next(r for r in allrows if r["id"] == "B")
    assert "week_lane" in b and b["week_lane"] is None             # key present, null: "not in the plan"
    assert b["roadmap"] == "none: planning lane"
    assert "E" not in {r["id"] for r in allrows}                   # done rows are not live
    assert data.work_rows(tmp_path, "open_other", 50)["sections"].keys() == {"open_other"}


def test_work_rows_offset_pages_a_section_to_completion(monkeypatch, tmp_path):
    rows = [{"id": f"R{i:03d}", "title": "t", "state": "queued"} for i in range(7)]  # 7 undated queued -> open_other
    monkeypatch.setattr(data, "_load_checklist", lambda repo: {"items": rows})
    seen, off, guard = [], 0, 0
    while off is not None and guard < 10:
        out = data.work_rows(tmp_path, "open_other", 3, offset=off)
        pop = out["population"]
        seen += [r["id"] for r in out["sections"]["open_other"]]
        assert pop["counts"]["open_other"] == 7 and pop["offset"] == off   # total is stable across pages
        off = pop["next_offset"]["open_other"]
        guard += 1
    assert seen == [f"R{i:03d}" for i in range(7)] and guard == 3          # 3 + 3 + 1, last page next_offset None
    last = data.work_rows(tmp_path, "open_other", 3, offset=6)["population"]
    assert last["truncated"]["open_other"] is False and last["next_offset"]["open_other"] is None


def test_work_rows_offset_is_served_and_part_of_the_cache_key():
    a = _call("work_rows", {"view": "open_other", "limit": 1, "offset": 0})["result"]["structuredContent"]
    b = _call("work_rows", {"view": "open_other", "limit": 1, "offset": 1})["result"]["structuredContent"]
    assert a["population"]["offset"] == 0 and b["population"]["offset"] == 1
    if a["sections"]["open_other"] and b["sections"]["open_other"]:
        assert a["sections"]["open_other"][0]["id"] != b["sections"]["open_other"][0]["id"]
