"""RESEARCH-PIPELINE-SLO: the SLO monitor alerts on a planted breach, stays silent on a healthy pipeline, and every
surface shows could-not-look as a hole, never a 0."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.research import research_slo as rs

NOW = datetime(2030, 1, 10, 12, tzinfo=timezone.utc)


def test_self_test_passes():
    assert rs._self_test() == 0


def test_every_slo_has_op_and_threshold():
    cfg = rs.load_config()
    for name, spec in cfg["slos"].items():
        assert spec.get("op") in ("min", "max"), name
        assert spec.get("threshold") is not None, name
    assert cfg["alerting"]["realert_hours"] > 0


def test_planted_starved_queue_alerts_and_healthy_control_does_not():
    cfg = rs.load_config()
    healthy = rs.evaluate(rs._fixture(), cfg)
    assert rs.transition(healthy, {}, NOW, cfg, [])["alert"] is None
    starved = rs.evaluate(rs._fixture(runnable_floor=rs._fact(2, threshold=50)), cfg)
    tr = rs.transition(starved, {}, NOW, cfg, [])
    assert tr["alert"]["kind"] == "change" and tr["alert"]["new"] == ["runnable_floor"]
    assert "runnable_floor (NEW): 2 vs >= 50" in tr["alert"]["text"]


def test_measure_only_run_does_not_consume_the_alert(tmp_path, monkeypatch):
    """A --write run without --live must not record the breach as announced."""
    cfg = rs.load_config()
    table = rs.evaluate(rs._fixture(runnable_floor=rs._fact(2, threshold=50)), cfg)
    monkeypatch.setattr(rs, "gather_facts", lambda *a, **k: rs._fixture(runnable_floor=rs._fact(2, threshold=50)))
    res = rs.run(tmp_path, NOW, live=False, write=True, use_gh=False)
    doc = json.loads(Path(res["status_file"]).read_text())
    assert doc["alert_state"] == {} and doc["runs"][-1]["alert"] is None
    assert [r["slo"] for r in doc["latest"] if r["state"] != "ok"] == ["runnable_floor"]
    # the next live run still sees the breach as NEW
    prev = rs.prior_state(tmp_path, None, cfg["alerting"]["comment_marker"])
    assert rs.transition(table, prev, NOW + timedelta(hours=2), cfg, [])["alert"]["kind"] == "change"


def test_brief_lines_declare_holes():
    assert "COULD NOT BE READ" in rs.table_lines(None, "absent", NOW)[0]
    cfg = rs.load_config()
    t = rs.evaluate(rs._fixture(hold_pr_wait_h=rs._cnl("no token")), cfg)
    lines = rs.table_lines({"as_of": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "latest": t}, "read", NOW)
    row = next(ln for ln in lines if ln.startswith("| hold_pr_wait_h"))
    assert "| — |" in row and "could not look" in row


def test_brief_section0_carries_the_slo_block():
    from scripts.ops import render_daily_brief as rdb
    b = {"pipeline": {"section0Lines": ["## §0 — WHAT CAME DUE", ""]},
         "researchSlo": {"lines": ["### ✅ Research pipeline SLOs — 0 not ok of 16", ""]}}
    assert any("Research pipeline SLOs" in ln for ln in rdb._section0(b))
