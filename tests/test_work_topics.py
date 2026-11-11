"""WORK-TOPIC-TAXONOMY: a row's topic is computed from its roadmap ref through docs/roadmap/topics.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml

from scripts.ci import check_topic_map as guard
from src.runtime import work_topics as wt

REPO = Path(__file__).resolve().parents[1]


def test_the_committed_map_covers_every_milestone_exactly():
    ms = yaml.safe_load((REPO / "docs/roadmap/milestones.yaml").read_text())
    tp = yaml.safe_load((REPO / "docs/roadmap/topics.yaml").read_text())
    assert guard.problems(ms, tp) == []


def test_a_row_takes_its_first_mapped_refs_topic_and_lists_all():
    r = wt.topic_for(["L-PROP", "L-ATM"])
    assert (r["topic"], r["basis"]) == ("Prop accounts", wt.BASIS_ROADMAP)
    assert r["topics"] == ["Prop accounts", "Trade management"] and r["subtopic"]
    assert wt.topic_for("M20")["topic"] == "Trade management"            # a closed milestone keeps its topic


def test_unmapped_and_unknown_refs_are_visible_not_hidden():
    for refs in (None, [], ["unmapped"], ["NOT-A-MILESTONE"]):
        r = wt.topic_for(refs)
        assert (r["topic"], r["basis"]) == ("Unmapped", wt.BASIS_UNMAPPED), refs


def test_an_unreadable_map_is_could_not_look_never_a_guess(tmp_path):
    bad = tmp_path / "topics.yaml"
    bad.write_text("milestones: [not, a, mapping]\n")
    r = wt.topic_for(["L-PROP"], path=bad)
    assert r == {"topic": None, "subtopic": None, "topics": [], "basis": wt.BASIS_COULD_NOT_LOOK}
    assert wt.topic_for(["L-PROP"], path=tmp_path / "missing.yaml")["basis"] == wt.BASIS_COULD_NOT_LOOK


def test_the_guard_self_test_passes():
    assert guard._self_test() == 0


def test_the_checklist_route_carries_the_topic_and_by_topic_sums_to_the_total():
    from src.web.api.routers import work
    rows = [work._checklist_item({"id": i, "state": "queued", "roadmap": rm}, ("queued",), None)
            for i, rm in (("A", ["L-PROP"]), ("B", ["unmapped"]), ("C", ["L-ATM", "M20"]))]
    assert [r["topic"]["topic"] for r in rows] == ["Prop accounts", "Unmapped", "Trade management"]
    s = work._checklist_summary(rows, 0)
    assert sum(s["byTopic"].values()) == s["total"] == 3
