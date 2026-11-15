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
    starved = rs.evaluate(rs._fixture(survivors_per_month=rs._fact(0.0)), cfg)
    tr = rs.transition(starved, {}, NOW, cfg, [])
    assert tr["alert"]["kind"] == "change" and tr["alert"]["new"] == ["survivors_per_month"]
    assert "survivors_per_month (NEW): 0 vs >= 1" in tr["alert"]["text"]


def test_measure_only_run_does_not_consume_the_alert(tmp_path, monkeypatch):
    """A --write run without --live must not record the breach as announced."""
    cfg = rs.load_config()
    table = rs.evaluate(rs._fixture(survivors_per_month=rs._fact(0.0)), cfg)
    monkeypatch.setattr(rs, "gather_facts", lambda *a, **k: rs._fixture(survivors_per_month=rs._fact(0.0)))
    res = rs.run(tmp_path, NOW, live=False, write=True, use_gh=False)
    doc = json.loads(Path(res["status_file"]).read_text())
    assert doc["alert_state"] == {} and doc["runs"][-1]["alert"] is None
    assert [r["slo"] for r in doc["latest"] if r["state"] != "ok"] == ["survivors_per_month"]
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


def test_heldout_census_counts_only_classified_heldout_registered_passes():
    """RESEARCH-SLO-HELDOUT-SURVIVORS: unknown held-out class is shown, never counted; a pass without a
    pre-registered rule is not a survivor; edge vs model_quality comes from structured fields only."""
    from datetime import datetime, timezone

    from scripts.research.research_slo import heldout_pass_census

    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    rbr = {"registered_before_run": True}
    g = {"verdict": "pass", "graded_at": "2026-11-05"}
    units = {
        "a": {"grading": g, "decision_rule": rbr, "evidence_class": {"holdout": "final_fold", "claim": "edge"}},
        "b": {"grading": g, "decision_rule": rbr, "ml_bakeoff": {"cv": "purged"}},
        "c": {"grading": g, "decision_rule": rbr},  # no structured class -> unknown
        "d": {"grading": g, "decision_rule": {"registered_before_run": False},
              "evidence_class": {"holdout": "final_fold", "claim": "edge"}},  # not pre-registered
        "e": {"grading": {"verdict": "fail", "graded_at": "2026-11-05"}, "decision_rule": rbr},
        "f": {"grading": {"verdict": "pass", "graded_at": "2026-09-01"}, "decision_rule": rbr,
              "evidence_class": {"holdout": "walk_forward", "claim": "edge"}},  # outside the window
        "h": {"grading": g, "decision_rule": rbr, "evidence_class": {"holdout": "in_sample", "claim": "edge"}},
    }
    c = heldout_pass_census(units, now, days=30)
    assert c["held_out"] == 2
    assert c["held_out_edge"] == 1 and c["held_out_model_quality"] == 1
    assert c["registered_passes"] == 4
    assert c["unknown_holdout"] == 1
    assert c["by_holdout"]["in_sample"] == 1


def test_heldout_census_keys_on_result_date_and_counts_a_confirmation_once():
    """AUD-20261019-RESEARCH-SLO-RED: a re-stamped graded_at must not pull an old verdict into the window, and a
    holdout re-run of a counted discovery is one survivor, not two."""
    from datetime import datetime, timezone

    from scripts.research.research_slo import heldout_pass_census

    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    rbr = {"registered_before_run": True}
    ec = {"holdout": "holdout_window", "claim": "edge"}
    g = {"verdict": "pass", "graded_at": "2026-11-12"}           # every stamp re-written today
    units = {
        "OLD": {"id": "OLD", "grading": g, "decision_rule": rbr, "evidence_class": ec},
        "NEW": {"id": "NEW", "grading": g, "decision_rule": rbr, "evidence_class": ec},
        "NEW-CONF": {"id": "NEW-CONF", "grading": g, "decision_rule": rbr, "evidence_class": ec,
                     "confirmation": {"of": "NEW", "mode": "holdout_rerun"}},
    }
    landed = {"OLD": datetime(2026, 9, 30, tzinfo=timezone.utc), "NEW": datetime(2026, 11, 1, tzinfo=timezone.utc),
              "NEW-CONF": datetime(2026, 11, 2, tzinfo=timezone.utc)}
    c = heldout_pass_census(units, now, days=30, verdict_at=lambda uid, ga: landed[uid])
    assert c["held_out_edge"] == 2 and c["held_out_edge_distinct"] == 1 and c["held_out_edge_ids"] == ["NEW"]
    assert c["window_keyed_on"] == {"result_date": 2, "graded_at_fallback": 0}
    # without dated results the graded_at fallback applies (and says so)
    c2 = heldout_pass_census(units, now, days=30)
    assert c2["held_out_edge"] == 3 and c2["window_keyed_on"]["graded_at_fallback"] == 3


def test_census_excludes_unconfirmed_splits_subjects_and_counts_conversion():
    """RESEARCH-SLO-SURVIVOR-CONVERSION: a pass whose own held-out read failed is not a survivor; survivors split by
    subject from structured fields; conversion = cited by the config tree (report-only)."""
    from datetime import datetime, timezone

    from scripts.research.research_slo import classify_subject, heldout_pass_census

    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    rbr = {"registered_before_run": True}
    ec = {"holdout": "holdout_window", "claim": "edge"}

    def g(conf=None):
        return {"verdict": "pass", "graded_at": "2026-11-10", **({"confirmation": conf} if conf else {})}

    units = {
        "LEV": {"id": "LEV", "grading": g("confirmed"), "decision_rule": rbr, "evidence_class": ec,
                "generated": {"family": "m20-exit-lever"}},
        "LEV-FAIL": {"id": "LEV-FAIL", "grading": g("not_replicated"), "decision_rule": rbr, "evidence_class": ec,
                     "generated": {"family": "m20-exit-lever"}},
        "LEV-THIN": {"id": "LEV-THIN", "grading": g("underpowered"), "decision_rule": rbr, "evidence_class": ec},
        "ML": {"id": "ML", "grading": g(), "decision_rule": rbr, "evidence_class": {**ec, "subject": "new"}},
        "REVAL": {"id": "REVAL", "grading": g(), "decision_rule": rbr, "evidence_class": {**ec, "subject": "revalidation"}},
        "BARE": {"id": "BARE", "grading": g(), "decision_rule": rbr, "evidence_class": ec},
    }
    c = heldout_pass_census(units, now, days=30, cited=lambda uid: uid == "ML")
    assert c["excluded_unconfirmed"] == {"not_replicated": 1, "underpowered": 1}
    assert c["held_out_edge_distinct"] == 4
    assert c["by_subject"] == {"lever": 1, "new": 1, "revalidation": 1, "unknown": 1}
    assert c["converted"] == "1/4" and c["converted_ids"] == ["ML"]
    # a holdout re-run inherits its parent's lever family
    assert classify_subject({"confirmation": {"of": "LEV"}}, units) == "lever"
    # no tree -> conversion is not measured, never 0
    assert heldout_pass_census(units, now, days=30)["converted"] is None
