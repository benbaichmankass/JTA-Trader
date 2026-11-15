"""UI-BACKTEST-LOG-GAPS: the run log and its computed 'what we did'."""
from __future__ import annotations

from src.runtime import research_runs as rr


def U(uid, verdict=None, status="result", title="t"):
    return {"id": uid, "verdict": verdict, "status": status, "title": title, "theme": "x", "kind": "experiment",
            "readState": "measured", "lastActivity": "2026-11-10T00:00:00Z", "rule": {"id": f"RULE-{uid}"},
            "resultNote": "note"}


UNITS = [U("RQ-20261101-001", "fail"), U("RQ-20261101-002", "pass"), U("RQ-20261101-003", "indeterminate"),
         U("RQ-20261101-004", "fail"), U("RQ-20261101-005", None, status="queued"),
         U("RQ-20261101-006", "pass"), U("RQ-20261101-007", "pass")]
DOCS = {
    "RQ-20261101-001": {"grading": {"graded_at": "2026-11-02T00:00:00Z"}},
    # iteration authored from 001's result (named inside a longer string)
    "RQ-20261101-005": {"iteration": {"from_result": "research/results/RQ-20261101-001/x.jsonl"}},
    # 002 names its own confirmation unit; 007 says it confirms 006
    "RQ-20261101-002": {"grading": {"graded_at": "2026-11-03T00:00:00Z", "confirm_unit": "RQ-20261101-006"}},
    "RQ-20261101-007": {"grading": {"confirms": "RQ-20261101-006"}},
    # 004 depends on 003's result
    "RQ-20261101-004": {"requires_result": {"unit": "RQ-20261101-003"},
                        "grading": {"disposition": "closed by PR #1"}},
}


def test_follow_ups_are_computed_from_links():
    rows = {r["id"]: r for r in rr.build_runs(UNITS, DOCS)}
    assert "RQ-20261101-005" not in rows  # no verdict, not a run
    w1 = rows["RQ-20261101-001"]["what_we_did"]
    assert w1["state"] == "acted" and w1["follow_ups"][0]["id"] == "RQ-20261101-005"
    assert w1["follow_ups"][0]["relation"] == "iteration" and w1["follow_ups"][0]["status"] == "queued"
    assert rows["RQ-20261101-002"]["what_we_did"]["follow_ups"][0] | {} == {
        "id": "RQ-20261101-006", "relation": "confirmation", "status": "result", "verdict": "pass", "title": "t"}
    assert {f["id"] for f in rows["RQ-20261101-006"]["what_we_did"]["follow_ups"]} == {"RQ-20261101-007"}
    assert rows["RQ-20261101-003"]["what_we_did"]["follow_ups"][0]["relation"] == "depends_on_result"
    w4 = rows["RQ-20261101-004"]["what_we_did"]
    assert w4 == {"state": "recorded", "follow_ups": [], "disposition": "closed by PR #1", "retired_reason": None}
    assert rows["RQ-20261101-007"]["what_we_did"]["state"] == "none_recorded"


def test_order_and_query_counts():
    rows = rr.build_runs(UNITS, DOCS)
    keys = [max(r["graded_at"] or "", r["last_activity"] or "") for r in rows]
    assert keys == sorted(keys, reverse=True)
    out = rr.query_runs(rows, verdict=["pass"], what=[], q="", since=None, limit=50, offset=0)
    assert out["total"] == 6 and out["matched"] == 3
    assert sum(out["counts"]["by_verdict"].values()) == out["total"]
    assert sum(out["counts"]["by_what_we_did"].values()) == out["total"]
    assert rr.query_runs(rows, verdict=[], what=["recorded"], q="", since=None, limit=50, offset=0)["matched"] == 1
    assert rr.query_runs(rows, verdict=[], what=[], q="", since="2026-11-11", limit=50, offset=0)["matched"] == 0
    assert rr.query_runs(rows, verdict=[], what=[], q="", since="2026-11-10", limit=50, offset=0)["matched"] == 6
    assert len(rr.query_runs(rows, verdict=[], what=[], q="", since=None, limit=2, offset=1)["runs"]) == 2


def test_route_shape(monkeypatch):
    from fastapi.testclient import TestClient

    from src.web.api.main import app
    from src.web.api.routers import research_catalog as rcr
    monkeypatch.setattr(rcr, "_runs", lambda: {"rows": rr.build_runs(UNITS, DOCS), "readErrors": [],
                                               "generatedAt": "2026-11-13T00:00:00Z"})
    rcr._SWR_RUNS.clear()
    c = TestClient(app)
    body = c.get("/api/bot/research/runs", params={"what": "acted"}).json()
    assert body["readState"] == "read" and body["total"] == 6 and body["matched"] == 4
    assert "trainer_sweeps" in body and body["trainer_sweeps"]["route"] == "/api/bot/backtests/sweeps"
    assert c.get("/api/bot/research/runs", params={"what": "bogus"}).status_code == 400
    monkeypatch.setattr(rcr, "_runs", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    rcr._SWR_RUNS.clear()
    bad = c.get("/api/bot/research/runs").json()
    assert bad["readState"] == "unreadable" and bad["runs"] is None and bad["total"] is None
    rcr._SWR_RUNS.clear()
