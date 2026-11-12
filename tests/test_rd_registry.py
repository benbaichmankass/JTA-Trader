"""RD-REGISTRY self-test: one planted positive per stage, the attribution rules, and the route.

Operator 2026-11-12 (lane RD-REGISTRY). The registry is a read projection; these tests pin that every stage
is reachable from fields alone and that a null stays null.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.runtime import rd_registry as rdr

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def U(uid, status="result", verdict=None, at="2026-11-10T00:00:00Z", stuck=False, title="", **kw):
    return {"id": uid, "status": status, "verdict": verdict, "latestResultAt": at if verdict else None,
            "lastActivity": at, "stuck": stuck, "stuckReason": "dispatched with no landed result" if stuck else None,
            "blockedReason": kw.get("blocked"), "resultNote": kw.get("note"), "title": title,
            "dataUsed": {"population": "planted", "n": 10}, "metrics": {"net_r": 1.5}, "theme": "live_strategy"}


# ── offline stages, planted one by one ───────────────────────────────────────────────────────
def test_offline_stage_planted_positives():
    cases = {
        "idea": [],
        "iterating": [U("a", verdict="fail"), U("b", status="queued")],
        "failed": [U("a", verdict="fail", note="lost net of cost")],
        "passed_waiting": [U("a", verdict="pass")],
        "testing_offline": [U("a", status="dispatched")],
        "queued": [U("a", status="queued")],
    }
    for want, units in cases.items():
        assert rdr.offline_stage(units)[0] == want, want
    st, reason, _ = rdr.offline_stage([U("a", status="dispatched", stuck=True)])
    assert st == "stuck" and "no landed result" in reason
    st, reason, _ = rdr.offline_stage([U("a", status="blocked", blocked="waits on X")])
    assert st == "stuck" and reason == "waits on X"
    st, reason, _ = rdr.offline_stage([U("a", verdict="indeterminate")])
    assert st == "stuck" and "indeterminate" in reason
    assert rdr.offline_stage([U("a", status="retired")])[0] == "stuck"
    # failed reason carries the result note; the latest graded verdict wins over an older pass
    st, reason, latest = rdr.offline_stage([U("old", verdict="pass", at="2026-10-01T00:00:00Z"),
                                            U("new", verdict="fail", at="2026-11-01T00:00:00Z", note="lost")])
    assert (st, reason, latest["id"]) == ("failed", "lost", "new")


# ── whole build on a planted tree: every stage appears ──────────────────────────────────────
def _w(root: Path, rel: str, obj) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj) if rel.endswith(".json") else yaml.safe_dump(obj), encoding="utf-8")


def _tree(root: Path) -> dict:
    _w(root, "config/strategies.yaml", {"strategies": {
        "leg_retired": {"enabled": False}, "leg_prod": {"execution": "live"}, "leg_paper": {"execution": "live"},
        "leg_floating": {"execution": "shadow"}}})
    _w(root, "config/accounts.yaml", {"accounts": {
        "bybit_1": {"strategies": ["leg_paper"]}, "bybit_2": {"strategies": ["leg_prod"]},
        "bybit_portfolio": {"strategies": ["leg_prod"]}}})
    _w(root, "comms/ml_consolidation/2026-11-11.json", {"as_of": "2026-11-11T00:00Z", "models": [
        {"model_id": "m-live-v1", "bucket": "LIVE", "slot": "D2", "display": "Collie-9"},
        {"model_id": "m-shadow-v1", "bucket": "SHADOW"},
        {"model_id": "m-offline-v1", "bucket": "OFFLINE"},
        {"model_id": "m-unused-v1", "bucket": "OFFLINE"}]})
    _w(root, "docs/plans/ml-plan-items.yaml", {"items": [
        {"id": "ML-K", "track": "S", "state": "killed", "ref": "ROW-K", "title": "killed idea"},
        {"id": "ML-P", "track": "S", "state": "parked", "ref": "ROW-P", "title": "parked idea", "close": "needs a new class"},
        {"id": "ML-U", "track": "X", "state": "open", "ref": "RQ-20261101-001", "title": "unit idea"},
        {"id": "ML-B", "track": "D", "state": "done", "ref": "ROW-B", "title": "a pure build"}]})
    _w(root, "research/programmes/01-x.yaml", {"programme": "P1", "nodes": [
        {"id": "P1-Q-new", "goal": "G1", "roadmap": [], "value": {}, "needs_authoring": "register the next test"},
        {"id": "P1-Q-done", "goal": "G1", "roadmap": [], "value": {}, "needs_authoring": "AUTHORED 2026-10-01"}]})
    _w(root, "research/programmes/06-infra.yaml", {"programme": "P6", "nodes": [
        {"id": "P6-Q-build", "goal": "G9", "roadmap": [], "value": {}, "needs_authoring": "a build"}]})
    for uid, extra in {"RQ-20261101-001": {}, "RQ-20261101-002": {"iteration": {"subject": "new_hypo", "subject_kind": "strategy_leg"}},
                       "RQ-20261101-003": {}, "RQ-20261101-004": {}, "RQ-20261101-005": {},
                       "RQ-20261101-006": {"programme_node": {"programme": "P1", "node": "P1-Q-node"}}}.items():
        _w(root, f"research/queue/{uid}.yaml", {"id": uid, "title": "t", **extra})
    units = [U("RQ-20261101-001", verdict="pass"),                                   # ML-U -> passed_waiting
             U("RQ-20261101-002", status="dispatched"),                              # hypothesis -> testing_offline
             U("RQ-20261101-003", verdict="fail", title="leg_floating sweep"),       # floating leg -> iterating (with 004)
             U("RQ-20261101-004", status="queued", title="leg_floating rerun"),
             U("RQ-20261101-005", verdict="fail", title="m-offline-v1 bake-off", note="no lift"),  # offline model -> failed
             U("RQ-20261101-006", status="queued"),                                  # programme node -> queued
             U("RQ-20261101-007", status="queued", title="unrelated infra")]         # unattributed
    return {"units": units, "readErrors": [], "roadmapAvailable": True}


def test_every_stage_has_a_planted_positive(tmp_path):
    doc = rdr.build_registry(tmp_path, now=NOW, catalog=_tree(tmp_path))
    by = {i["id"]: i for i in doc["ideas"]}
    want = {
        "strategy:leg_retired": "retired", "strategy:leg_prod": "production", "strategy:leg_paper": "testing_book",
        "strategy:leg_floating": "iterating", "ml:m-live-v1": "shadow_advisory", "ml:m-shadow-v1": "shadow_advisory",
        "ml:m-offline-v1": "failed", "mlplan:ML-K": "retired", "mlplan:ML-P": "stuck", "mlplan:ML-U": "passed_waiting",
        "hypothesis:new_hypo": "testing_offline", "question:P1-Q-new": "idea", "question:P1-Q-node": "queued",
    }
    for iid, stage in want.items():
        assert by[iid]["stage"] == stage, (iid, by[iid]["stage"], by[iid]["stage_reason"])
    assert set(rdr.STAGES) <= {i["stage"] for i in doc["ideas"]}
    # not ideas: an unused OFFLINE model, a done pure build, an AUTHORED node, a data-infra node
    for absent in ("ml:m-unused-v1", "mlplan:ML-B", "question:P1-Q-done", "question:P6-Q-build"):
        assert absent not in by
    s = doc["summary"]
    assert s["units"] == {**s["units"], "total": 7, "attributed": 6, "unattributed": 1}
    assert s["unattributed_units"]["count"] == 1
    assert sum(s["per_track"].values()) == s["ideas"] == len(doc["ideas"])
    assert s["excluded"]["data_infra_programme_nodes"] == 1
    assert by["ml:m-live-v1"]["name"] == "Collie-9" and by["ml:m-live-v1"]["stage_reason"].startswith("advisory")
    assert by["mlplan:ML-P"]["stage_reason"].startswith("parked: needs a new class")
    assert by["ml:m-offline-v1"]["stage_reason"].endswith("no lift")
    assert by["ml:m-offline-v1"]["latest_result"]["population"] == "planted"
    assert doc["read_state"]["ml_registry"]["state"] == "snapshot"
    assert rdr.cross_check(doc, tmp_path) == []


def test_nulls_stay_null(tmp_path):
    doc = rdr.build_registry(tmp_path, now=NOW, catalog=_tree(tmp_path))
    by = {i["id"]: i for i in doc["ideas"]}
    idea = by["question:P1-Q-new"]
    assert idea["latest_result"] is None and idea["last_activity"] is None and idea["open_units"] is None
    assert by["strategy:leg_paper"]["stage0_evidence"] is None      # no evidence file: null, never 0
    assert doc["read_state"]["strategy_evidence"]["state"] == "missing"


def test_live_registry_rows_win_over_snapshot(tmp_path):
    cat = _tree(tmp_path)
    doc = rdr.build_registry(tmp_path, now=NOW, catalog=cat, live_registry_rows=[
        {"model_id": "m-new-v2", "deployment_bucket": "SHADOW", "display_name": "Beagle-1"}])
    assert doc["read_state"]["ml_registry"]["state"] == "ok"
    ids = {i["id"] for i in doc["ideas"]}
    assert "ml:m-new-v2" in ids and "ml:m-live-v1" not in ids


def test_stage_change_vs_previous(tmp_path):
    cat = _tree(tmp_path)
    prev = {"ideas": [{"id": "strategy:leg_paper", "stage": "passed_waiting"}]}
    doc = rdr.build_registry(tmp_path, now=NOW, catalog=cat, previous=prev)
    assert doc["summary"]["stage_changes_since_previous"] == [
        {"id": "strategy:leg_paper", "from": "passed_waiting", "to": "testing_book"}]


def test_rules_are_published_and_cover_every_stage():
    assert {r["stage"] for r in rdr.STAGE_RULES} == set(rdr.STAGES)


def test_route_filters(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.web.api.main import app
    from src.web.api.routers import research_catalog as router_mod
    doc = rdr.build_registry(tmp_path, now=NOW, catalog=_tree(tmp_path))
    monkeypatch.setattr(router_mod, "_registry", lambda: {**doc, "servedFrom": "built"})
    router_mod._SWR_REG.clear()
    c = TestClient(app)
    r = c.get("/api/bot/research/registry", params={"track": "ML", "stage": "shadow_advisory"})
    assert r.status_code == 200
    body = r.json()
    assert body["present"] is True and body["matched"] == 2
    assert {i["id"] for i in body["ideas"]} == {"ml:m-live-v1", "ml:m-shadow-v1"}
    assert body["summary"]["ideas"] == len(doc["ideas"])          # summary is never filtered
    assert c.get("/api/bot/research/registry", params={"track": "NOPE"}).status_code == 422
