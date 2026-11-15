"""INSIGHTS-LEDGER: pipeline `kind: insight` validation + GET /api/bot/work/ledger (links resolved live)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from scripts.ops import pipeline
from src.runtime import checklist_store
from src.web.api import main as api_main
from src.web.api.routers import work_ledger as router


def _item(**over):
    it = {"id": "PI-20261111-TEST-0001", "what": "one line",
          "origin": {"kind": "review", "ref": "#1", "rerun": "python3 scripts/ci/run_guards.py --all"},
          "due_when": {"kind": "observation", "clears_when": "x", "check_every_days": 7},
          "next_action": "check_observation", "state": "queued"}
    it.update(over)
    return it


def _insight(**over):
    return _item(**{"kind": "insight", "claim": "sizing, not entry, drove the 30d loss",
                    "population": "bybit_2, 30d, n=39 closed trades", "provenance": "MEASURED",
                    "evidence": "docs/reviews/x.md", "outcome": "filed", "links": [], **over})


def test_insight_validation_refusals_and_old_items_unaffected():
    assert pipeline.validate(_item()) is not None                      # a non-insight item: untouched
    assert pipeline.validate(_insight()) is not None                   # positive control
    for bad, needle in (({"population": ""}, "insight.population"), ({"claim": None}, "insight.claim"),
                        ({"evidence": " "}, "insight.evidence"), ({"provenance": "FABRICATED"}, "insight.provenance"),
                        ({"outcome": "maybe"}, "insight.outcome"), ({"links": "x"}, "insight.links"),
                        ({"links": [{"type": "memo", "id": "a"}]}, "insight.links"),
                        ({"outcome": "acted", "links": []}, "needs at least one link"),
                        ({"topic": ""}, "insight.topic")):
        with pytest.raises(pipeline.PipelineError, match=needle):
            pipeline.validate(_insight(**bad))
    assert pipeline.validate(_insight(outcome="acted", links=[{"type": "pr", "id": "#24893"}])) is not None
    missing = _insight()
    del missing["population"]
    with pytest.raises(pipeline.PipelineError, match="insight.population"):
        pipeline.validate(missing)


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = tmp_path / pipeline.STORE
    store.mkdir(parents=True)
    (tmp_path / "research" / "queue").mkdir(parents=True)
    (tmp_path / "research" / "queue" / "RQ-1.yaml").write_text("id: RQ-1\n")
    monkeypatch.setattr(router, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(checklist_store, "load", lambda root=None, *a, **k: {"items": [
        {"id": "ROW-A", "state": "queued", "title": "a row"}]})
    return store


def _file(store, **over):
    return pipeline.append(_insight(**over), store, intent="new")


def test_ledger_resolves_links_flags_dangling_and_groups_unmapped(env, client):
    _file(env, id="PI-20261111-TEST-0001", topic="Prop accounts", roadmap="L-PROP", outcome="acted",
          links=[{"type": "row", "id": "ROW-A"}, {"type": "unit", "id": "RQ-1"}, {"type": "pr", "id": "#1"}])
    _file(env, id="PI-20261111-TEST-0002", links=[{"type": "row", "id": "ROW-GONE"}, {"type": "unit", "id": "RQ-NOPE"}])
    pipeline.append(_item(id="PI-20261111-TEST-0003"), env, intent="new")        # not an insight
    d = client.get("/api/bot/work/ledger").json()
    assert d["read_state"] == "measured" and d["population"]["n_insights_total"] == 2
    by = {i["id"]: i for i in d["insights"]}
    assert "PI-20261111-TEST-0003" not in by
    a = {(lk["type"], lk["id"]): lk for lk in by["PI-20261111-TEST-0001"]["links"]}
    assert a[("row", "ROW-A")]["state"] == "queued" and a[("row", "ROW-A")]["title"] == "a row"
    assert a[("unit", "RQ-1")]["read_state"] == "resolved" and a[("pr", "#1")]["read_state"] == "not_checked"
    assert by["PI-20261111-TEST-0001"]["n_dangling"] == 0
    b = by["PI-20261111-TEST-0002"]
    assert b["topic"] == "Unmapped" and b["n_dangling"] == 2
    assert {t["topic"]: t["n"] for t in d["by_topic"]} == {"Prop accounts": 1, "Unmapped": 1}


def test_ledger_filters(env, client):
    _file(env, id="PI-20261111-TEST-0001", topic="ML", roadmap="M23", outcome="open")
    _file(env, id="PI-20261111-TEST-0002", topic="Research", outcome="killed", state="killed",
          terminal_reason="superseded")
    ids = lambda **p: [i["id"] for i in client.get("/api/bot/work/ledger", params=p).json()["insights"]]  # noqa: E731
    assert ids(topic="ML") == ["PI-20261111-TEST-0001"] and ids(outcome="killed") == ["PI-20261111-TEST-0002"]
    assert ids(roadmap="M23") == ["PI-20261111-TEST-0001"] and ids(topic="Nope") == []
    d = client.get("/api/bot/work/ledger", params={"topic": "ML"}).json()
    assert d["population"]["n_shown"] == 1 and d["population"]["n_insights_total"] == 2
    assert d["population"]["filters"] == {"topic": "ML"}


def test_ledger_rows_unreadable_is_not_dangling(env, client, monkeypatch):
    _file(env, id="PI-20261111-TEST-0001", links=[{"type": "row", "id": "ROW-A"}])

    def boom(*a, **k):
        raise OSError("store down")
    monkeypatch.setattr(checklist_store, "load", boom)
    lk = client.get("/api/bot/work/ledger").json()["insights"][0]["links"][0]
    assert lk["read_state"] == "rows_unreadable"


def test_ledger_empty_store_is_measured_with_zero_not_an_error(env, client):
    d = client.get("/api/bot/work/ledger").json()
    assert d["read_state"] == "measured" and d["insights"] == [] and d["population"]["n_insights_total"] == 0
