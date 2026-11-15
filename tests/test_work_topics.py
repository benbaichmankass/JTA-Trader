"""WORK-TOPIC-TAXONOMY backend: topic/subtopic COMPUTED from a row's roadmap ref through docs/roadmap/topics.yaml."""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from src.runtime import checklist_store
from src.web.api import main as api_main
from src.web.api.routers import work_topics as wt

TMAP = {"L-PROP": {"topic": "Prop accounts", "subtopic": "automate"}, "M23": {"topic": "ML", "subtopic": "meta-labelling"},
        "M25": {"topic": "ML", "subtopic": "promotion"}}


def test_topic_for_first_mapped_wins_and_unknowns_are_none():
    assert wt.topic_for(["L-PROP"], TMAP) == {"topic": "Prop accounts", "subtopic": "automate", "milestone": "L-PROP"}
    assert wt.topic_for(["unmapped", "M25", "L-PROP"], TMAP)["milestone"] == "M25"       # first ref that maps
    assert wt.topic_for("M23", TMAP)["topic"] == "ML"                                    # a bare string works
    for bad in (None, [], ["unmapped"], ["M999"], 5, [None]):
        assert wt.topic_for(bad, TMAP) is None


def test_build_counts_open_vs_total_lists_unmapped_refs_and_sums_to_rows():
    rows = [{"id": "A", "roadmap": ["L-PROP"], "state": "queued"}, {"id": "B", "roadmap": ["L-PROP"], "state": "done"},
            {"id": "C", "roadmap": ["M23"], "state": "in_progress"}, {"id": "D", "roadmap": ["M25"], "state": "queued"},
            {"id": "E", "roadmap": ["unmapped"], "state": "queued"}, {"id": "F", "state": "queued"},
            {"id": "G", "roadmap": ["M999"], "state": "dropped"}, {"state": "queued"}, "junk"]
    d = wt.build(rows, TMAP, ["L-PROP", "M23", "M25", "M30"])
    assert d["rows"]["A"] == {"topic": "Prop accounts", "subtopic": "automate", "milestone": "L-PROP"}
    assert d["rows"]["E"]["topic"] == wt.UNMAPPED and d["rows"]["F"]["topic"] == wt.UNMAPPED and d["rows"]["G"]["milestone"] is None
    t = {x["topic"]: x for x in d["topics"]}
    assert (t["Prop accounts"]["n_open"], t["Prop accounts"]["n_total"]) == (1, 2)       # the done row is total only
    assert (t["ML"]["n_open"], t["ML"]["n_total"]) == (2, 2) and {s["subtopic"] for s in t["ML"]["subtopics"]} == {"meta-labelling", "promotion"}
    assert (t[wt.UNMAPPED]["n_open"], t[wt.UNMAPPED]["n_total"]) == (2, 3)
    assert d["unmapped"] == {"n_rows": 3, "refs": {"(no roadmap ref)": 1, "M999": 1, "unmapped": 1}}
    assert sum(x["n_total"] for x in d["topics"]) == len(d["rows"]) == 7                 # arithmetic cross-check
    assert d["coverage"]["milestones_without_topic"] == ["M30"] and d["coverage"]["n_mapped"] == 3


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "docs/roadmap").mkdir(parents=True)
    (tmp_path / "docs/roadmap/topics.yaml").write_text(yaml.safe_dump({"topics": TMAP}))
    (tmp_path / "docs/roadmap/milestones.yaml").write_text(yaml.safe_dump({"milestones": [{"id": "L-PROP"}, {"id": "M23"}, {"id": "NEW"}]}))
    monkeypatch.setattr(wt, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(checklist_store, "load", lambda *a, **k: {"items": [
        {"id": "R1", "roadmap": ["M23"], "state": "queued"}, {"id": "R2", "roadmap": ["unmapped"], "state": "queued"}]})
    return tmp_path


def test_route_reports_unmapped_milestones_instead_of_failing(root, client):
    d = client.get("/api/bot/work/topics").json()
    assert d["read_state"] == "measured" and d["n_rows"] == 2
    assert d["rows"]["R1"]["topic"] == "ML" and d["rows"]["R2"]["topic"] == "Unmapped"
    assert d["coverage"]["milestones_without_topic"] == ["NEW"]                          # a gap is shown, never a crash


def test_route_unreadable_states(root, client, monkeypatch):
    def boom(*a, **k):
        raise OSError("store down")
    monkeypatch.setattr(checklist_store, "load", boom)
    d = client.get("/api/bot/work/topics").json()
    assert d["read_state"] == "rows_unreadable" and d["rows"] == {} and d["coverage"]["n_milestones"] == 3
    (root / "docs/roadmap/topics.yaml").unlink()
    assert client.get("/api/bot/work/topics").json()["read_state"] == "map_unreadable"
