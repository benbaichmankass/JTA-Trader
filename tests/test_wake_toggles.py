"""Console wake switches: defaults, fail-open, per-class LTR, route auth, suppression receipts."""
import sys
from pathlib import Path

import pytest

from src.runtime import wake_toggles as wt

ROOT = Path(__file__).resolve().parents[1]
CLS = {"bybit_2": "real_money", "breakout_2": "prop", "bybit_1": "testing_paper", "alpaca_portfolio": "paper_portfolio"}.get


def test_initial_state_matches_operator_spec(tmp_path):
    st = wt.read_local(tmp_path / "w.json")
    assert st["read_state"] == "defaults"
    assert st["toggles"] == {"desk_wake": False, "desk_trigger_wake": False, "short_hold": False,
                             "desk_could_not_build": False, "ltr_paper": False, "ltr_real_money": True,
                             "ltr_prop": True, "alert_watch": True}


def test_flip_persists_logs_who_and_unreadable_posts(tmp_path):
    p = tmp_path / "w.json"
    st = wt.set_toggle("desk_wake", True, "operator-console", p)
    assert st["toggles"]["desk_wake"] is True and st["detail"]["desk_wake"]["changed_by"] == "operator-console"
    assert wt.read_local(p)["toggles"]["desk_wake"] is True  # survives a fresh read (a restart)
    flips = wt.recent_flips(path=p)
    assert flips[0]["key"] == "desk_wake" and flips[0]["old"] is False and flips[0]["new"] is True
    p.write_text("{not json")
    bad = wt.read_local(p)
    assert bad["read_state"] == "could_not_look" and bad["toggles"] is None
    assert wt.is_on("ltr_real_money", bad) and wt.is_on("desk_wake", bad)  # a doubt posts, even for an off switch
    with pytest.raises(KeyError):
        wt.set_toggle("nope", True, "x", p)


def test_ltr_entry_per_class_and_mixed_never_half_silenced():
    st = {"toggles": wt._defaults()}
    real = {"accounts": ["bybit_2"]}
    prop = {"accounts": ["breakout_2"]}
    paper = {"accounts": ["bybit_1"]}
    mixed = {"accounts": ["bybit_1", "bybit_2"]}
    f = lambda e: wt.ltr_entry_on(e, st, CLS)  # noqa: E731
    assert f(real) and f(prop) and not f(paper) and f(mixed)
    st["toggles"]["ltr_real_money"] = False
    assert not f(real) and f(prop) and not f(mixed)
    assert wt.ltr_entry_on({"accounts": ["mystery"]}, {"toggles": wt._defaults()}, CLS)  # unknown rides real money


def test_label_names_only_classes_present():
    assert wt.ltr_label([{"accounts": ["bybit_1"]}], CLS) == "paper"
    assert wt.ltr_label([{"accounts": ["bybit_2"]}, {"accounts": ["breakout_2"]}], CLS) == "real-money/prop"
    assert wt.ltr_label([{"accounts": ["bybit_2"]}, {"accounts": ["bybit_1"]}], CLS) == "real-money/paper"


def test_apply_toggles_drops_paper_keeps_packets_logs_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("RUNTIME_LOGS_DIR", str(tmp_path / "l"))
    monkeypatch.delenv("WAKE_TOGGLES_REMOTE", raising=False)
    wt._logged.clear()
    sys.path.insert(0, str(ROOT / "scripts" / "ops"))
    import live_review_wake as w
    monkeypatch.setattr("src.runtime.telegram_policy.account_class", lambda a, accounts=None: CLS(a, "unknown_account"))
    p = {"kind": "wake", "entries": [
        {"order_package_id": "P1", "event": "e", "level": "1", "accounts": ["bybit_1"]},
        {"order_package_id": "P2", "event": "e", "level": "1", "accounts": ["bybit_2"]}]}
    bundles = {"P1": {"state": "built"}, "P2": {"state": "built"}}
    dropped = w.apply_toggles(p, bundles)
    assert [e["order_package_id"] for e in dropped] == ["P1"]
    assert [e["order_package_id"] for e in p["entries"]] == ["P2"] and list(bundles) == ["P2"] and p["kind"] == "wake"
    assert "suppressed_by_wake_toggle" in wt.suppressed_log_path().read_text()
    p2 = {"kind": "wake", "entries": [{"order_package_id": "P1", "event": "e", "level": "1", "accounts": ["bybit_1"]}]}
    w.apply_toggles(p2, {"P1": {}})
    assert p2["kind"] == "quiet"


def test_route_get_and_post_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("RUNTIME_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "tok")
    from src.web.api.main import app
    c = TestClient(app)
    g = c.get("/api/bot/wake-toggles").json()
    assert g["read_state"] == "defaults" and len(g["rows"]) == 8
    assert c.post("/api/bot/wake-toggles", json={"key": "desk_wake", "on": True}).status_code == 401
    h = {"Authorization": "Bearer tok"}
    assert c.post("/api/bot/wake-toggles", json={"key": "nope", "on": True}, headers=h).status_code == 400
    r = c.post("/api/bot/wake-toggles", json={"key": "desk_wake", "on": True, "by": "op"}, headers=h).json()
    assert r["toggles"]["desk_wake"] is True and r["recent_flips"][0]["by"] == "op"
    assert c.get("/api/bot/wake-toggles").json()["toggles"]["desk_wake"] is True


def test_connector_research_queue_and_write_tool_gating(monkeypatch):
    from src.console_connector import server as s
    r = s.call_tool("research_queue", {"status": "blocked", "theme": "all", "limit": 5})
    assert r["read_state"] in ("read", "partial") and r["population"]["units_scanned"] > 0
    assert all(x["status"] == "blocked" for x in r["rows"]) and set(r["counts"]) == {"by_status", "by_theme_group", "by_compute"}
    monkeypatch.delenv("WAKE_TOGGLES_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("CONSOLE_CONNECTOR_AUTH", raising=False)
    assert not s.write_enabled() and s.call_tool("set_wake_toggle", {"key": "desk_wake", "on": True})["read_state"] == "auth_required"
    assert "set_wake_toggle" not in [t["name"] for t in s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    monkeypatch.setenv("WAKE_TOGGLES_WRITE_TOKEN", "t")
    assert "set_wake_toggle" in [t["name"] for t in s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]


def test_connector_replies_stay_small_for_the_pages_calls():
    """Console stuck on 'Waiting' (2026-11-07): closed_this_week alone was 167 KB. Every call the page makes must
    stay under the reply budget."""
    import json
    from src.console_connector import server as s
    for name, args in [("work_rows", {"view": "all", "limit": 6}), ("workplan", {"limit": 6}), ("ml_roadmap", {"limit": 15}),
                       ("system_catalog", {"signals_limit": 10}), ("research_queue", {"status": "pipeline", "limit": 30}),
                       ("inbox", {"limit": 25})]:
        out = s.call_tool(name, args)
        assert len(json.dumps(out, default=str)) <= s.REPLY_BUDGET and "oversize" not in out, name
    wr = s.call_tool("work_rows", {"view": "in_flight", "limit": 3})["closed_this_week"]
    assert len(wr["rows"]) <= 15 and wr["population"]["closed_rows"] >= len(wr["rows"]) and wr["counts_by_week_lane"] is not None
