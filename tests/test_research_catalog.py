"""Contract tests for the research catalog projection + router (DATA-EXPLORER)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.runtime import research_catalog as rc

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def _unit(root: Path, uid: str, blocked: bool = False, **kw):
    d = root / "research" / "queue" / ("blocked" if blocked else "")
    d.mkdir(parents=True, exist_ok=True)
    doc = {"id": uid, "title": f"title {uid}", "question": "does X beat Y?", "status": "queued",
           "cadence": "once", "kind": "experiment", "theme": "regime", "priority": 2,
           "run": {"workflow": "w.yml", "inputs": {"legs": "eth_4h", "symbol": "ETHUSDT"}},
           "lands": {"store": "docs/x.jsonl"}}
    doc.update(kw)
    (d / f"{uid}.yaml").write_text(yaml.safe_dump(doc))


def _result(root: Path, uid: str, **kw):
    d = root / "research" / "results" / uid
    d.mkdir(parents=True, exist_ok=True)
    row = {"generated_at": "2026-10-12T10:00:00Z", "read_state": "measured", "verdict": "pass",
           "measurement": {"n": 49, "net_r": 1.5, "nested": {"a": 1}},
           "population": {"description": "OOS", "n": 49},
           "produced_by": {"run_url": "https://example/run/1", "tool": "t.py"}}
    row.update(kw)
    with (d / "1.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "docs" / "roadmap").mkdir(parents=True)
    (tmp_path / "docs" / "roadmap" / "milestones.yaml").write_text(yaml.safe_dump({
        "goals": {"G2": {"name": "Prop income"}},
        "milestones": [{"id": "L-PROP", "goal": "G2", "name": "Prop legs", "status": "active"}]}))
    _unit(tmp_path, "RQ-20261001-001", roadmap=["L-PROP"])
    _unit(tmp_path, "RQ-20261002-001", last_dispatched_at="2026-10-13T01:00:00Z")   # dispatched 11h ago
    _unit(tmp_path, "RQ-20261003-001", status="done")
    _result(tmp_path, "RQ-20261003-001")
    _unit(tmp_path, "RQ-20261004-001", blocked=True, blocked_on={"what": "needs the harness"})
    (tmp_path / "research" / "queue" / "RQ-20261005-001.yaml").write_text("{: not yaml")
    return tmp_path


def _build(tree):
    return rc.build_catalog(tree, now=NOW)


def test_every_file_is_counted_or_reported(tree):
    cat = _build(tree)
    assert len(cat["units"]) == 4
    assert [e["path"] for e in cat["readErrors"]] == ["research/queue/RQ-20261005-001.yaml"]


def test_status_derivation(tree):
    by = {u["id"]: u for u in _build(tree)["units"]}
    assert by["RQ-20261003-001"]["status"] == "result" and by["RQ-20261003-001"]["verdict"] == "pass"
    assert by["RQ-20261004-001"]["status"] == "blocked" and by["RQ-20261004-001"]["stuck"]
    d = by["RQ-20261002-001"]
    assert d["status"] == "dispatched" and d["stuck"] and "no landed result" in d["stuckReason"]
    assert by["RQ-20261001-001"]["status"] in {"due", "queued"}   # dispatcher's own call, not guessed


def test_roadmap_resolution_metrics_and_null_handling(tree):
    by = {u["id"]: u for u in _build(tree)["units"]}
    ref = by["RQ-20261001-001"]["roadmap"][0]
    assert ref["id"] == "L-PROP" and ref["goal"] == "G2" and ref["goalName"] == "Prop income"
    r = by["RQ-20261003-001"]
    assert r["metrics"] == {"n": 49, "net_r": 1.5}          # nested dict dropped, scalars kept
    assert r["dataUsed"]["dataInputs"] == {"legs": "eth_4h", "symbol": "ETHUSDT"}
    assert by["RQ-20261001-001"]["verdict"] is None and by["RQ-20261001-001"]["rule"] is None


def test_search_filter_sort_paginate_and_facets(tree):
    units = _build(tree)["units"]
    assert rc.query_catalog(units, q="ETHUSDT")["matched"] == 4
    assert rc.query_catalog(units, q="no-such-token")["matched"] == 0
    out = rc.query_catalog(units, filters={"status": ["result"]})
    assert [u["id"] for u in out["items"]] == ["RQ-20261003-001"]
    assert out["facets"]["status"]["result"] == 1 and out["facets"]["status"]["blocked"] == 1
    # a facet's own counts ignore its own selection (so it can be widened)
    assert out["facets"]["status"].get("blocked") == 1
    page = rc.query_catalog(units, sort="id", order="asc", limit=2, offset=1)
    assert [u["id"] for u in page["items"]] == ["RQ-20261002-001", "RQ-20261003-001"]
    assert page["total"] == 4 and page["matched"] == 4


def test_stay_on_top(tree):
    units = _build(tree)["units"]
    top = rc.stay_on_top(units, "2026-10-12T00:00:00Z")
    assert top["sinceKnown"] and top["new"]["count"] >= 1
    assert {u["id"] for u in top["stuck"]["items"]} >= {"RQ-20261002-001", "RQ-20261004-001"}
    assert top["recentVerdicts"][0]["id"] == "RQ-20261003-001"
    first = rc.stay_on_top(units, None)       # first visit: 'new' is NOT computed, never reported as 0
    assert first["sinceKnown"] is False and first["new"] is None


def test_missing_queue_dir_is_an_error_not_empty(tmp_path):
    cat = rc.build_catalog(tmp_path, now=NOW)
    assert cat["units"] == [] and cat["readErrors"]


def test_live_tree_positive_control():
    """The real queue: a known resulted unit must come back resulted with a verdict (probe can find a positive)."""
    cat = rc.build_catalog(REPO)
    by = {u["id"]: u for u in cat["units"]}
    assert len(by) > 100
    u = by["RQ-20260922-003"]
    assert u["status"] == "result" and u["verdict"] == "pass"
    assert u["links"]["results"], "result file links expected"


def test_router_endpoints():
    from fastapi.testclient import TestClient

    from src.web.api.main import app
    c = TestClient(app)
    r = c.get("/api/bot/research/catalog", params={"limit": 5, "status": "result"})
    assert r.status_code == 200
    body = r.json()
    assert body["present"] and body["total"] > 100 and len(body["items"]) == 5
    assert all(i["status"] == "result" for i in body["items"])
    assert c.get("/api/bot/research/catalog/RQ-20260922-003").json()["present"] is True
    assert c.get("/api/bot/research/catalog/RQ-00000000-000").json()["present"] is False
    assert c.get("/api/bot/research/catalog/..%2Fetc").status_code in (400, 404)
    assert c.get("/api/bot/research/catalog", params={"order": "sideways"}).status_code == 422
