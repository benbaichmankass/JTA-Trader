"""WORK-GAP-ALERTS: gap numbers carry population + read-state, and a non-zero one reaches the alert ledger and the wake pass.

Gates this adds: none (no CI check; operator m12 2026-11-12)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from scripts.ops import attention_watch, gap_counts
from src.runtime import alerts_ledger as al

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _tree(tmp: Path, milestones, topics, insights=()):
    (tmp / "docs/roadmap").mkdir(parents=True)
    (tmp / "docs/roadmap/milestones.yaml").write_text(yaml.safe_dump({"milestones": [{"id": m} for m in milestones]}))
    (tmp / "docs/roadmap/topics.yaml").write_text(yaml.safe_dump({"topics": {t: {"topic": "T", "subtopic": "s"} for t in topics}}))
    from scripts.ops import pipeline
    store = tmp / pipeline.STORE
    store.mkdir(parents=True, exist_ok=True)
    for i, it in enumerate(insights):
        (store / f"20261112T00000{i}Z-INS.json").write_text(json.dumps(it))


def test_milestone_gap_counted_with_population(tmp_path):
    _tree(tmp_path, ["A", "B", "C"], ["A"])
    g = gap_counts.milestones_no_topic(tmp_path)
    assert (g["n"], g["ids"], g["read_state"], g["population"]["n_milestones"]) == (2, ["B", "C"], "measured", 3)


def test_unreadable_sources_are_could_not_look_never_zero(tmp_path):
    g = gap_counts.milestones_no_topic(tmp_path)          # no files at all
    assert g["n"] is None and g["read_state"] == "could_not_look" and gap_counts.needs_attention(g)
    (tmp_path / "docs/roadmap").mkdir(parents=True)
    (tmp_path / "docs/roadmap/milestones.yaml").write_text("milestones: []")
    (tmp_path / "docs/roadmap/topics.yaml").write_text("topics: {}")
    assert gap_counts.milestones_no_topic(tmp_path)["n"] is None   # empty population is not "no gaps"


def test_zero_gap_emits_nothing(tmp_path):
    _tree(tmp_path, ["A"], ["A"])
    led = tmp_path / "l.jsonl"
    r = gap_counts.emit(gap_counts.compute(tmp_path), now=NOW, state_path=tmp_path / "s.json", ledger_path=led)
    assert r["state"] == "nothing_to_alert" and not led.exists()


def test_injected_gap_reaches_ledger_and_wakes_manager_then_dedups(tmp_path):
    _tree(tmp_path, ["A", "B"], ["A"])
    led, st = tmp_path / "l.jsonl", tmp_path / "s.json"
    res = gap_counts.compute(tmp_path)
    assert gap_counts.emit(res, now=NOW, state_path=st, ledger_path=led)["state"] == "emitted"
    rows = al.read(path=led)["rows"]
    assert len(rows) == 1 and rows[0]["kind"] == "work_gap" and rows[0]["priority"] == "high"
    assert "milestones_no_topic: 1 of 2" in rows[0]["body"] and "B" in rows[0]["body"]
    assert al.wakes_manager(rows[0])
    # the real wake pass turns it into a comment for the manager
    body, _, summary = attention_watch.plan_alert_comment(rows, {}, datetime.now(timezone.utc) + timedelta(seconds=1))
    assert summary["posted_kinds"] == ["work_gap"] and body and "work_gap" in body
    # unchanged within REALERT_HOURS => held; changed => re-emitted; after REALERT_HOURS => re-emitted
    assert gap_counts.emit(res, now=NOW + timedelta(hours=1), state_path=st, ledger_path=led)["state"] == "held_unchanged"
    assert gap_counts.emit(res, now=NOW + timedelta(hours=7), state_path=st, ledger_path=led)["state"] == "emitted"
    _tree_more = tmp_path / "docs/roadmap/milestones.yaml"
    _tree_more.write_text(yaml.safe_dump({"milestones": [{"id": m} for m in "ABC"]}))
    assert gap_counts.emit(gap_counts.compute(tmp_path), now=NOW + timedelta(hours=8), state_path=st, ledger_path=led)["state"] == "emitted"


def test_insight_with_no_link_is_counted(tmp_path):
    base = {"kind": "insight", "claim": "c", "population": "p", "provenance": "MEASURED", "evidence": "e", "outcome": "noted"}
    _tree(tmp_path, ["A"], ["A"], insights=[])
    from scripts.ops import pipeline
    items = {"I1": {**base, "id": "I1", "links": []}, "I2": {**base, "id": "I2", "links": [{"type": "row", "id": "X"}]}}
    orig = pipeline.read_log
    class R:  # stand-in for the store read: two insights, one linkless
        unreadable = []
        def __init__(s): s.items = items
    pipeline.read_log = lambda *_a, **_k: R()
    try:
        g = gap_counts.insights_no_link(tmp_path)
    finally:
        pipeline.read_log = orig
    assert (g["n"], g["ids"], g["population"]["n_insights_total"], g["read_state"]) == (1, ["I1"], 2, "measured")
