"""The five console tabs: shape, auth gating, the data_query allowlist. Fake live VM; temp sqlite DBs."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.console_connector import data, server, tabs

REPO = Path(__file__).resolve().parents[2]
ENVELOPE = ("as_of", "read_state", "population", "provenance")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("CONSOLE_CONNECTOR_AUTH", raising=False)
    monkeypatch.delenv("DIAG_READ_TOKEN", raising=False)
    server.CACHE._entries.clear()
    yield
    server.CACHE._entries.clear()


def _call(name, args=None):
    out = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": name, "arguments": args or {}}})
    return out["result"]["structuredContent"]


# ── auth gating ─────────────────────────────────────────────────────────
def test_gated_tools_not_listed_without_google(monkeypatch):
    names = {t["name"] for t in server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    assert {"workplan", "ml_roadmap"} <= names
    assert not (server.GATED_TOOLS & names)
    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    names = {t["name"] for t in server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    assert server.GATED_TOOLS <= names


@pytest.mark.parametrize("mode", [None, "", "none", "GOOGLE-ish", "false"])
def test_gated_call_refused_unless_exactly_google(monkeypatch, mode):
    if mode is not None:
        monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", mode)
    called = []
    monkeypatch.setattr(tabs, "FETCH", lambda *a: called.append(a))
    for name in sorted(server.GATED_TOOLS):
        out = _call(name, {"table": "trades"})
        assert out["read_state"] == "auth_required" and out["population"]["rows_scanned"] is None
        assert "rows" not in out and "sections" not in out
    assert called == []  # nothing was read


def test_auth_required_is_not_cached(monkeypatch):
    assert _call("data_query")["read_state"] == "auth_required"
    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    monkeypatch.setenv("TRADE_JOURNAL_DB", "/nonexistent/j.db")
    monkeypatch.setenv("TRAINER_STORE_DB", "/nonexistent/t.db")
    assert _call("data_query")["read_state"] != "auth_required"


# ── 1. workplan / 2. ml_roadmap (public register data) ──────────────────
def test_workplan_shape():
    out = _call("workplan", {"limit": 5})
    assert all(k in out for k in ENVELOPE) and out["read_state"] == "read"
    assert out["weekly_planning"]["id"] == "WEEKLY-PLANNING"
    assert len(out["overdue"]) <= 5 and out["population"]["window"]["from"] <= out["population"]["window"]["to"]
    assert out["usage"]["read_state"] in ("read", "could_not_look")
    if out["usage"]["read_state"] == "read":
        assert "capacity" in out["usage"] and "weekly" in out["usage"]["latest_by_window"]


def test_workplan_unreadable_register_is_could_not_look(monkeypatch):
    monkeypatch.setattr(data, "_load_checklist", lambda repo: (_ for _ in ()).throw(OSError("gone")))
    out = tabs.workplan(REPO)
    assert out["read_state"] == "could_not_look" and out["population"]["rows_scanned"] is None


def test_ml_roadmap_shape():
    out = _call("ml_roadmap", {"limit": 5})
    assert all(k in out for k in ENVELOPE)
    assert set(out["sections"]) == {"milestones", "plan_status", "rows"}
    ms = out["sections"]["milestones"]["items"]
    assert ms and all(m["goal"] == "G4" or m["id"].startswith("L-ML") for m in ms)
    assert all(r["id"].startswith(("ML-", "REGIME-", "EXIT-HEAD", "TP-PREDICT", "FUNDING-OI"))
               for r in out["sections"]["rows"]["items"])


# ── 3. performance / 4. system_health (fake live VM) ────────────────────
def _perf(window):
    leg = {"name": "xrp_pullback_2h", "trades": 3, "wins": 1, "totalPnl": -2.0, "totalR": -1.0, "rTradeCount": 3,
           "pnlCoverage": 1.0}
    book = {"totalTrades": 3, "totalPnl": -2.0, "perStrategy": [leg]}
    return {**book, "paper": {**book, "perStrategy": [dict(leg, name="p_leg")]}, "paperPortfolio": book}


def _fake(path, token):
    if path.startswith("/api/bot/performance?window="):
        return _perf(path.split("=")[1])
    if path.startswith("/api/bot/performance/recent"):
        raise OSError("recent down")
    if path.startswith("/api/bot/shadow/stats"):
        return {"records": [{"model_id": "m1", "stage": "shadow", "count": 5, "score_mean": 0.5}], "count": 1}
    if path.startswith("/api/bot/ml/registry"):
        return {"rows": [{"model_id": "m1", "status": "shadow", "metrics": {"f1": 0.6, "blob": {"x": 1}}}], "count": 1}
    raise AssertionError(path)


def test_performance_shape_and_partial_never_zero(monkeypatch):
    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    monkeypatch.setattr(tabs, "FETCH", _fake)
    out = _call("performance")
    assert all(k in out for k in ENVELOPE) and out["read_state"] == "partial"
    legs = out["sections"]["legs"]["books"]["real_money"]["legs"]["xrp_pullback_2h"]
    assert set(legs) == {"7d", "30d", "all"} and legs["7d"]["trades"] == 3
    assert "p_leg" in out["sections"]["legs"]["books"]["paper"]["legs"]
    assert out["sections"]["live_vs_backtest"]["read_state"] == "could_not_look"
    m = out["sections"]["ml_models"]["models"][0]
    assert m["model_id"] == "m1" and m["metrics"] == {"f1": 0.6} and m["shadow"]["count"] == 5


def test_performance_window_failure_is_none_not_zero(monkeypatch):
    def f(path, token):
        if "window=30d" in path:
            raise OSError("boom")
        return _fake(path, token)
    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    monkeypatch.setattr(tabs, "FETCH", f)
    legs = _call("performance")["sections"]["legs"]
    assert legs["read_state"] == "partial" and "30d" in legs["errors"]
    assert legs["books"]["real_money"]["legs"]["xrp_pullback_2h"]["30d"] is None


def test_system_health_token_header_and_could_not_look(monkeypatch):
    seen = []

    def f(path, token):
        seen.append((path, token))
        if token is None:
            raise AssertionError("diag path read without a token")
        if path.endswith("/services"):
            return [{"unit": "ict-trader-live.service", "state": "active"}]
        if path.startswith("/api/diag/journalctl"):
            return {"lines": ["Nov 05 Started ict-trader-live.service", "Main process exited, code=killed"],
                    "read_state": "complete", "truncated": False}
        if path.endswith("/status"):
            return {"heartbeat": {"ok": 1}, "status": {}, "vm_health": {"cpu": 5.0, "memory": 40.0, "disk": 30.0}}
        return {"x": 1}

    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    monkeypatch.setenv("DIAG_READ_TOKEN", "tok")
    monkeypatch.setattr(tabs, "FETCH", f)
    monkeypatch.setattr(tabs, "_local_vm", lambda: {"cpu": 1.0, "memory": 2.0, "disk": 3.0})
    out = _call("system_health")
    s = out["sections"]
    assert all(k in out for k in ENVELOPE) and all(t == "tok" for _, t in seen)
    assert s["services"]["value"][0]["state"] == "active"
    assert s["restarts_today"]["count"] == 1 and len(s["restarts_today"]["causes"]) == 1
    assert s["vm_resources"]["vms"]["live"]["cpu"] == 5.0 and s["vm_resources"]["vms"]["trainer"]["disk"] == 3.0
    assert s["vm_resources"]["vms"]["gateway"]["read_state"] == "could_not_look"
    assert out["read_state"] == "partial"  # gateway unreadable is stated, not hidden


def test_system_health_without_diag_token(monkeypatch):
    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    monkeypatch.setattr(tabs, "FETCH", lambda *a: pytest.fail("must not fetch"))
    monkeypatch.setattr(tabs, "_local_vm", lambda: {"cpu": None, "memory": None, "disk": None})
    s = _call("system_health")["sections"]
    assert s["services"]["read_state"] == "could_not_look" and "DIAG_READ_TOKEN" in s["services"]["error"]
    assert s["services"]["value"] is None


def test_http_token_sent_in_both_headers(monkeypatch):
    sent = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def fake_open(req, timeout):
        sent.update({k.lower(): v for k, v in req.header_items()})
        return R()
    monkeypatch.setattr(tabs.urllib.request, "urlopen", fake_open)
    tabs._http_get("/api/diag/version", "tok")
    assert sent["x-diag-token"] == "tok" and sent["authorization"] == "Bearer tok"
    sent.clear()
    tabs._http_get("/api/bot/performance", None)
    assert "x-diag-token" not in sent and "authorization" not in sent


# ── 5. data_query ───────────────────────────────────────────────────────
@pytest.fixture
def dbs(tmp_path, monkeypatch):
    j = tmp_path / "trade_journal.db"
    c = sqlite3.connect(j)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, strategy_name TEXT, account_id TEXT, "
              "pnl REAL, closed_at TEXT)")
    c.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?)",
                  [(i, "BTCUSDT" if i % 2 else "ETHUSDT", "leg_a", "bybit_2" if i < 600 else "bybit_1", i * 0.1,
                    f"2026-10-{1 + i % 28:02d}T00:00:00") for i in range(1, 701)])
    c.execute("CREATE TABLE device_tokens (id INTEGER PRIMARY KEY, token TEXT)")
    c.execute("INSERT INTO device_tokens VALUES (1, 'fcm-raw')")
    c.execute("CREATE TABLE not_listed (id INTEGER PRIMARY KEY, v TEXT)")
    c.execute("CREATE TABLE insights_usage (id INTEGER PRIMARY KEY, input_tokens INTEGER)")
    c.execute("INSERT INTO insights_usage VALUES (1, 7)")
    # stand-in for a future allowlisted table that carries a credential column (named so the schema guard
    # does not mistake it for a production table)
    c.execute("CREATE TABLE zz_scratch (id INTEGER PRIMARY KEY, api_key TEXT, Token TEXT, note TEXT)")
    c.execute("INSERT INTO zz_scratch VALUES (1, 'SECRET', 'SECRET2', 'ok')")
    c.commit()
    c.close()
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(j))
    monkeypatch.setenv("TRAINER_STORE_DB", str(tmp_path / "absent.db"))
    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    from src.web.api.routers import db_explorer as ex
    monkeypatch.setattr(ex, "_TABLE_ALLOWLIST", ex._TABLE_ALLOWLIST | {"zz_scratch"})
    return j


def test_catalog_lists_only_allowlist_and_no_secret_columns(dbs):
    out = _call("data_query")
    tables = {c["table"]: c["columns"] for c in out["catalog"]}
    assert set(tables) == {"trades", "insights_usage", "zz_scratch"}  # device_tokens, not_listed invisible
    assert tables["zz_scratch"] == ["id", "note"]  # api_key / Token dropped by the deny-by-name pattern
    assert "input_tokens" in tables["insights_usage"]  # a COUNT is not a secret
    assert out["read_state"] == "partial" and "trainer_store" in out["unavailable_dbs"]


@pytest.mark.parametrize("t", ["device_tokens", "not_listed", "sqlite_master", 'trades"; DROP TABLE trades;--'])
def test_non_allowlisted_table_refused(dbs, t):
    out = _call("data_query", {"table": t})
    assert out["rows"] == [] and "allowlist" in out["error"]
    assert sqlite3.connect(dbs).execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 700


def test_rows_never_contain_secret_column(dbs):
    out = _call("data_query", {"table": "zz_scratch"})
    assert out["rows"] == [{"id": 1, "note": "ok"}]
    # and it is not filterable/orderable either, so it cannot be probed through the filter
    assert "api_key" not in out["columns"] and _call("data_query", {"table": "zz_scratch", "time_column": "api_key"})["rows"]


def test_provenance_states_snapshot_age(dbs):
    out = _call("data_query", {"table": "trades", "limit": 1})
    assert out["provenance"]["db_file"] == str(dbs) and 0 <= out["provenance"]["db_file_age_s"] < 600


def test_limit_clamped_to_500(dbs):
    out = _call("data_query", {"table": "trades", "limit": 100000})
    assert out["population"]["returned"] == 500 and out["population"]["limit_state"] == "clamped_to_max"
    assert out["population"]["matched_total"] == 700 and out["population"]["truncated"] is True
    assert _call("data_query", {"table": "trades", "limit": "junk"})["population"]["limit"] == 100


def test_filters_account_leg_symbol_dates(dbs):
    out = _call("data_query", {"table": "trades", "account": "bybit_1", "symbol": "BTCUSDT", "limit": 500})
    assert out["population"]["matched_total"] == 50 and out["filters_applied"] == {"account": "account_id", "symbol": "symbol"}
    assert all(r["account_id"] == "bybit_1" and r["symbol"] == "BTCUSDT" for r in out["rows"])
    out = _call("data_query", {"table": "trades", "since": "2026-10-05", "until": "2026-10-06"})
    assert out["filters_applied"]["since"] == "closed_at" and all(r["closed_at"].startswith("2026-10-05") for r in out["rows"])


def test_filter_values_are_bound_not_interpolated(dbs):
    out = _call("data_query", {"table": "trades", "symbol": "x' OR '1'='1"})
    assert out["population"]["matched_total"] == 0
    assert "error" in _call("data_query", {"table": "trades", "since": "1; DROP TABLE trades"})


def test_inapplicable_filter_is_refused_not_dropped(dbs):
    out = _call("data_query", {"table": "insights_usage", "symbol": "BTCUSDT"})
    assert out["rows"] == [] and "does not apply" in out["error"]


def test_connection_is_read_only(dbs):
    out = _call("data_query", {"table": "trades", "order": "asc", "limit": 1})
    assert out["order"] == {"column": "closed_at", "dir": "asc"} and out["rows"][0]["closed_at"].startswith("2026-10-01")
    ro = sqlite3.connect(f"file:{dbs}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM trades")


def test_no_database_on_host_is_could_not_look(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("TRAINER_STORE_DB", str(tmp_path / "b.db"))
    out = _call("data_query", {"table": "trades"})
    assert out["read_state"] == "could_not_look" and out["rows"] == []


# ── inbox options[] ─────────────────────────────────────────────────────
def test_options_helper():
    assert data._options({"options": ["A", {"label": "B"}, "", 3]}) == ["A", "B"]
    assert data._options({"choices": [{"label": "Yes"}]}) == ["Yes"]
    assert data._options({}) is None and data._options({"options": []}) is None and data._options(None) is None


def test_inbox_items_carry_options_key():
    out = data.inbox(REPO, limit=200)
    for sec in ("decisions_checklist", "asks_pipeline"):
        items = out["sections"][sec]["items"]
        assert items and all("options" in i for i in items)


# ── system_catalog (public: committed config only) ─────────────────────
def test_system_catalog_is_public_and_projects_committed_files():
    names = {t["name"] for t in server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    assert "system_catalog" in names and "system_catalog" not in server.GATED_TOOLS
    out = _call("system_catalog", {"signals_limit": 5})
    assert all(k in out for k in ENVELOPE)
    legs = out["sections"]["legs"]
    assert legs["read_state"] == "read" and legs["items"]
    assert {r["status"] for r in legs["items"]} <= {"testing", "production", "inactive"}
    assert sum(legs["population"]["by_status"].values()) == len(legs["items"]) == legs["population"]["legs"]
    sig = out["sections"]["signals"]
    assert len(sig["items"]) == 5 and sig["population"]["truncated"] is True
    assert out["sections"]["ml_models"]["items"]


def test_system_catalog_missing_source_is_could_not_look_not_empty(tmp_path):
    out = tabs.system_catalog(tmp_path)
    assert out["read_state"] == "could_not_look"
    for sec in out["sections"].values():
        assert sec["read_state"] == "could_not_look" and "items" not in sec and sec["reason"]


# ── closed-this-week + week_lane totals (CONSOLE-WORKPLAN-SYNC) ───────────
def _row(i, state, lane, updated):
    return {"id": i, "title": i, "state": state, "week_lane": lane, "updated_at": updated}


def test_week_start_is_latest_wednesday_1800z():
    from datetime import datetime, timezone
    thu = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)   # Thursday
    assert data._iso(data.week_start(thu)) == "2026-11-04T18:00:00Z"
    wed_early = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    assert data._iso(data.week_start(wed_early)) == "2026-10-28T18:00:00Z"
    fri = datetime(2026, 11, 6, 23, 0, tzinfo=timezone.utc)
    assert data._iso(data.week_start(fri)) == "2026-11-04T18:00:00Z"


def test_closed_this_week_counts_and_window(monkeypatch):
    from datetime import date, datetime, timezone
    now = datetime(2026, 11, 6, 23, 0, tzinfo=timezone.utc)
    items = [_row("a", "done", "surge", "2026-11-05T01:00:00Z"),
             _row("b", "landed_unproven", "surge", "2026-11-06T01:00:00Z"),
             _row("c", "done", "surge", "2026-11-03T01:00:00Z"),      # before the reset: excluded
             _row("d", "dropped", "throttle", "2026-11-05T01:00:00Z"),
             _row("e", "in_flight", "throttle", "2026-11-06T01:00:00Z"),
             _row("f", "done", "throttle", None)]                      # no stamp: excluded, never guessed
    out = data.closed_this_week(items, now, date(2026, 11, 6))
    assert out["read_state"] == "read" and out["population"]["closed_rows"] == 3
    assert out["counts_by_week_lane"] == {"surge": {"done": 1, "landed_unproven": 1}, "throttle": {"dropped": 1}}
    tot = data.week_lane_totals(items)
    assert tot["surge"]["total"] == 3 and tot["throttle"]["by_state"]["in_flight"] == 1


def test_work_rows_and_workplan_add_fields_keep_old_shape():
    wr = data.work_rows(REPO)
    assert {"due", "in_flight", "blocked", "queued", "open_other"} <= set(wr["sections"])
    assert wr["closed_this_week"]["read_state"] == "read" and "week_lane_totals" in wr
    wp = tabs.workplan(REPO, 5)
    assert "closed_this_week" in wp and "week_lane_totals" in wp and "weekly_planning" in wp
    # totals equal a direct register count
    direct = {}
    for r in data._load_checklist(REPO)["items"]:
        if r.get("week_lane"):
            direct[r["week_lane"]] = direct.get(r["week_lane"], 0) + 1
    assert {k: v["total"] for k, v in wr["week_lane_totals"].items()} == direct


# ── work_items (C3): the console Work tab on the live work store ──
def _store_item(i, state="queued", by="Manager Session 2026-11-11a", src=None):
    it = {"id": f"X-{i}", "kind": "build", "title": f"t{i}", "state": state, "owner": "manager",
          "updated_at": f"2026-11-12T07:{40 + i:02d}:00Z", "updated_by": by, "version": 1,
          "blocked_on": [{"kind": "work_item", "ref": "Y"}] if i == 0 else [], "extra": {}}
    if src:
        it["extra"]["_source"] = src
    return it


def test_work_items_recent_passes_since_and_slims(monkeypatch):
    seen = []

    def f(path, tok):
        seen.append(path)
        return {"readState": "read", "items": [_store_item(1), _store_item(0, src="checklist")], "total": 2700,
                "canonical": False, "note": "S1"}
    monkeypatch.setattr(tabs, "FETCH", f)
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    out = tabs.work_items({"view": "recent", "since_hours": 2, "limit": 5})
    assert out["read_state"] == "read" and out["count"] == 2
    assert "since=" in seen[0] and "limit=5" in seen[0] and seen[0].startswith("/api/bot/work/items?")
    assert out["items"][0]["by"] == "Manager Session 2026-11-11a" and out["items"][0]["source"] == "store"
    assert out["items"][1]["source"] == "checklist" and out["items"][1]["blocked_on"] == ["Y"]
    assert out["population"]["store_items_total"] == 2700 and out["canonical"] is True  # S4 freeze is committed


def test_work_items_open_merges_states_newest_first(monkeypatch):
    def f(path, tok):
        st = path.split("state=")[1].split("&")[0]
        return {"readState": "read", "items": [_store_item(len(st) % 10, state=st)], "total": 9}
    monkeypatch.setattr(tabs, "FETCH", f)
    out = tabs.work_items({"view": "open", "limit": 3})
    assert out["count"] == 3 and set(out["population"]["per_state"]) == set(tabs.OPEN_ITEM_STATES)
    ts = [i["updated_at"] for i in out["items"]]
    assert ts == sorted(ts, reverse=True)


def test_work_items_events_and_failures(monkeypatch):
    monkeypatch.setattr(tabs, "FETCH", lambda p, t: {"events": [{"seq": 1, "op": "create", "by": "s"}],
                                                      "chain": {"ok": True}})
    ev = tabs.work_items({"item_id": "A B"})
    assert ev["read_state"] == "read" and ev["events"][0]["op"] == "create" and "A%20B" in ev["upstream"]
    monkeypatch.setattr(tabs, "FETCH", lambda p, t: {"readState": "could_not_look", "items": None, "error": "db"})
    out = tabs.work_items({"view": "due"})
    assert out["read_state"] == "could_not_look" and out["items"] is None and out["count"] is None
    bad = tabs.work_items({"view": "state", "state": "x; drop"})
    assert bad["read_state"] == "could_not_look"


def test_work_items_sends_service_bearer_when_present(monkeypatch):
    toks = []
    monkeypatch.setattr(tabs, "FETCH", lambda p, t: toks.append(t) or {"readState": "read", "items": [], "total": 0})
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "x")
    tabs.work_items({"view": "due"})
    assert toks == ["x"]


# ── after the S4 freeze: register reads come from the live store, not the frozen export ──
@pytest.mark.store_register
def test_frozen_register_reads_live_store(monkeypatch):
    from src.console_connector import data as D
    monkeypatch.setattr(D, "register_source", lambda repo: "work_store")
    item = {"id": "LIVE-ROW", "kind": "build", "title": "from the store", "state": "in_flight", "owner": "m",
            "lane": None, "tier": 1, "roadmap": ["L-OPS"], "due_rule": None, "due_at": None, "prs": [],
            "blocked_on": [], "updated_at": "2026-11-12T07:49:35Z", "updated_by": "UI lane", "version": 3,
            "priority_rank": None, "extra": {"_seq": 5, "_source": "checklist", "note": "n"}}
    calls = []

    def fake(url):
        calls.append(url)
        return {"readState": "read", "items": [item] if "kind=build" in url else []}
    monkeypatch.setattr(D, "STORE_FETCH", fake)
    out = D.work_rows(REPO, "in_flight", 5)
    assert out["read_state"] == "read" and out["provenance"]["register_source"] == "work_store"
    assert [r["id"] for r in out["sections"]["in_flight"]] == ["LIVE-ROW"]
    n = len(calls)
    D.work_rows(REPO, "all", 5)
    assert len(calls) == n, "second read inside the TTL must come from the shared cache"


@pytest.mark.store_register
def test_frozen_register_store_down_is_could_not_look(monkeypatch):
    from src.console_connector import data as D
    monkeypatch.setattr(D, "register_source", lambda repo: "work_store")
    monkeypatch.setattr(D, "STORE_FETCH", lambda url: {"readState": "could_not_look", "items": None, "error": "db"})
    out = D.work_rows(REPO, "all", 5)
    assert out["read_state"] == "could_not_look" and out["population"]["rows_scanned"] is None
