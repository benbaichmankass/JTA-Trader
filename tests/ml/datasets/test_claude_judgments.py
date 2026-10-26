"""CJ-2-DATASET: the claude_judgments family -- point-in-time join, exclusions counted."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ml.datasets.families.claude_judgments import (
    FEATURE_COLUMNS,
    JUDGMENT_COLUMNS,
    OUTCOME_COLUMNS,
    ClaudeJudgmentsBuilder,
    population_report,
)
from ml.datasets.registry import get_builder, list_families


def _review(rid, tid, *, reviewed="2026-10-25T16:30:00Z", cutoff="2026-10-25T16:16:30Z",
            action="hold", applied=False, jc=0.6):
    return {
        "schema_version": 1, "review_id": rid, "reviewed_at": reviewed, "info_cutoff_at": cutoff,
        "order_package_id": f"pkg-{tid}", "trade_id": tid, "leg": "ada_pullback_2h",
        "state": {"bars_held": 11},
        "features_at_review": {"open_r": 0.2, "peak_r": 0.85, "giveback_r": 0.65, "atr_now_over_entry": None,
                               "bars_since_peak": 4, "r_to_stop": 1.2, "r_to_target": 3.8},
        "recommendation": {"action": action, "level": None, "level_atr": None, "ev_delta_r": None,
                           "worst_case_delta_r": None, "basis": "default_hold", "confidence": "suggestive",
                           "judgement_confidence": jc},
        "judge_prior": None, "applied": applied, "model": "opus-tier (x)", "session": "s",
        "prompt_sha": "abcdef0123", "skill_sha": None, "packet_sha": None,
    }


def _journal(path: Path, trades: list[dict]) -> None:
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, entry_price REAL,"
              " exit_price REAL, stop_loss REAL, position_size REAL, pnl REAL, status TEXT, notes TEXT,"
              " account_class TEXT, order_package_id TEXT, closed_at TEXT, exit_reason TEXT,"
              " fee_taker_usd REAL, fee_maker_usd REAL, funding_paid_usd REAL, cost_source TEXT)")
    c.execute("CREATE TABLE order_packages (order_package_id TEXT PRIMARY KEY, entry REAL, sl REAL)")
    for t in trades:
        c.execute("INSERT INTO trades VALUES (:id,:symbol,:direction,:entry_price,:exit_price,:stop_loss,"
                  ":position_size,:pnl,:status,:notes,:account_class,:order_package_id,:closed_at,:exit_reason,"
                  ":fee_taker_usd,:fee_maker_usd,:funding_paid_usd,:cost_source)", t)
        c.execute("INSERT INTO order_packages VALUES (?,?,?)", (t["order_package_id"], t["entry_price"], t["pkg_sl"]))
    c.commit()
    c.close()


def _trade(tid, *, status="closed", closed_at="2026-10-26T02:00:00Z", pnl=20.0, trailed_sl=1.05):
    # long, entry 1.00, INITIAL stop 0.90 (risk 0.10 x 100 = $10); trades.stop_loss is the trailed level
    return {"id": tid, "symbol": "ADAUSDT", "direction": "long", "entry_price": 1.0,
            "exit_price": 1.2 if status == "closed" else None, "stop_loss": trailed_sl, "position_size": 100.0,
            "pnl": pnl if status == "closed" else None, "status": status,
            "notes": json.dumps({"exit_price_source": "bybit_closed_pnl"}), "account_class": "real_money",
            "order_package_id": f"pkg-{tid}", "closed_at": closed_at if status == "closed" else None,
            "exit_reason": "tp", "fee_taker_usd": 1.0, "fee_maker_usd": 0.0, "funding_paid_usd": 0.0,
            "cost_source": "broker", "pkg_sl": 0.90}


@pytest.fixture
def env(tmp_path):
    comms = tmp_path / "comms"
    (comms / "live_review").mkdir(parents=True)
    (comms / "desk").mkdir(parents=True)
    return comms, tmp_path / "trade_journal.db"


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _run(comms, db, **kw):
    b = ClaudeJudgmentsBuilder()
    rows = list(b.iter_rows(comms_root=comms, db_path=db, **kw))
    return rows, population_report(b.last_report)


def test_registered():
    assert "claude_judgments" in list_families()
    assert get_builder("claude_judgments").family == "claude_judgments"


def test_column_groups_disjoint_and_in_schema():
    groups = [set(FEATURE_COLUMNS), set(JUDGMENT_COLUMNS), set(OUTCOME_COLUMNS)]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    for g in groups:
        assert g <= set(ClaudeJudgmentsBuilder.schema)


def test_join_uses_initial_stop_and_net_of_cost(env):
    comms, db = env
    _write(comms / "live_review" / "reviews.jsonl", [_review("LR-20261025T1616Z-pkg-1", 1)])
    _journal(db, [_trade(1)])
    rows, rep = _run(comms, db)
    assert rep["n_emitted_joined"] == 1 and rep["partition_ok"]
    r = rows[0]
    # risk = |1.00 - 0.90| x 100 = 10 (NOT the trailed 1.05); net = (20 - 1) / 10
    assert r["label_net_r"] == pytest.approx(1.9)
    assert r["label_gross_r"] == pytest.approx(2.0)
    assert r["timing"] == "T0" and r["judgement_confidence"] == 0.6
    # unapplied hold: the realised path IS the hold path
    assert r["cf_hold_r"] == pytest.approx(1.9) and r["delta_r"] == 0.0
    assert r["cf_source"] == "realised_path_was_hold" and r["label_provenance"] == "measured"
    assert r["split_group"] == "pkg-1"


def test_unapplied_tighten_waits_for_replay(env):
    comms, db = env
    _write(comms / "live_review" / "reviews.jsonl",
           [_review("LR-20261025T1616Z-pkg-1", 1, action="tighten_sl")])
    _journal(db, [_trade(1)])
    rows, _ = _run(comms, db)
    assert rows[0]["delta_r"] is None and rows[0]["cf_source"] == "pending_replay"


def test_ltr_outcomes_replay_wins(env):
    comms, db = env
    rid = "LR-20261025T1616Z-pkg-1"
    _write(comms / "live_review" / "reviews.jsonl", [_review(rid, 1, action="tighten_sl", applied=True)])
    _write(comms / "live_review" / "outcomes.jsonl", [{
        "schema_version": 1, "review_id": rid, "order_package_id": "pkg-1", "trade_id": 1,
        "closed_at": "2026-10-26T02:00:00Z", "computed_at": "2026-10-26T03:00:00Z", "net_r": 0.5,
        "pnl_provenance": "measured", "cf_r": 1.5, "cf_r_shadow_0_5": None, "cf_method": "v1",
        "cf_provenance": "computed", "exit_reason": "sl"}])
    rows, _ = _run(comms, None)
    assert rows[0]["outcome_source"] == "ltr_outcomes"
    assert rows[0]["delta_r"] == pytest.approx(-1.0) and rows[0]["cf_source"] == "ltr_replay"


def test_ltr_outcome_delta_r_prices_an_unapplied_tighten(env):
    comms, db = env
    rid = "LR-20261025T1616Z-pkg-1"
    _write(comms / "live_review" / "reviews.jsonl", [_review(rid, 1, action="tighten_sl", applied=False)])
    _write(comms / "live_review" / "outcomes.jsonl", [{
        "schema_version": 1, "review_id": rid, "order_package_id": "pkg-1", "trade_id": 1,
        "closed_at": "2026-10-26T02:00:00Z", "computed_at": "2026-10-26T03:00:00Z", "net_r": 2.0,
        "pnl_provenance": "measured", "cf_r": 2.0, "cf_r_shadow_0_5": None, "cf_method": "replay_v1",
        "cf_provenance": "computed", "exit_reason": "tp", "rec_r": 0.5, "delta_r": -1.5}])
    rows, _ = _run(comms, None)
    # realised == hold (cf_r 2.0), so net_r - cf_r would be 0.0; the priced value of the call is -1.5
    assert rows[0]["delta_r"] == pytest.approx(-1.5) and rows[0]["cf_source"] == "ltr_replay"


def test_exclusions_are_counted_by_reason(env):
    comms, db = env
    _write(comms / "live_review" / "reviews.jsonl", [
        _review("LR-20261025T1616Z-pkg-1", 1),                                  # emitted
        _review("LR-20261025T1616Z-pkg-2", 2),                                  # trade still open
        _review("LR-20261025T1616Z-pkg-3", 3),                                  # not in journal
        _review("LR-20261025T1616Z-pkg-4", 4, cutoff="2026-10-25T16:40:00Z"),   # cutoff 10 min after judged
        _review("LR-20261026T0300Z-pkg-5", 5, reviewed="2026-10-26T03:00:00Z",
                cutoff="2026-10-26T02:59:00Z"),                                 # saw the close: T1
    ])
    _journal(db, [_trade(1), _trade(2, status="open"), _trade(4), _trade(5)])
    rows, rep = _run(comms, db)
    assert [r["judgment_id"] for r in rows] == ["LR-20261025T1616Z-pkg-1"]
    assert rep["excluded_by_reason"] == {
        "outcome_pending": 1, "outcome_unjoined_trade_not_in_journal": 1,
        "cutoff_after_judged": 1, "t1_outcome_visible": 1}
    assert rep["partition_ok"] and rep["n_source_rows"] == 5
    rows_t1, _ = _run(comms, db, include_t1=True)
    assert {r["timing"] for r in rows_t1} == {"T0", "T1"}


def test_minute_rounded_judged_at_is_tolerated_and_flagged(env):
    comms, db = env
    _write(comms / "live_review" / "reviews.jsonl",
           [_review("LR-20261026T1226Z-pkg-1", 1, reviewed="2026-10-26T00:26:00Z", cutoff="2026-10-26T00:26:08Z")])
    _journal(db, [_trade(1)])
    rows, _ = _run(comms, db)
    assert rows[0]["judged_at_rounded"] is True


def test_holdout_window(env):
    comms, db = env
    _write(comms / "live_review" / "reviews.jsonl", [_review("LR-20261025T1616Z-pkg-1", 1)])
    _journal(db, [_trade(1)])
    _, rep = _run(comms, db, holdout_days=100000)
    assert rep["excluded_by_reason"] == {"holdout_window": 1}


def test_no_journal_is_counted_not_zeroed(env):
    comms, _ = env
    _write(comms / "live_review" / "reviews.jsonl", [_review("LR-20261025T1616Z-pkg-1", 1)])
    rows, rep = _run(comms, None)
    assert rows == [] and rep["excluded_by_reason"] == {"outcome_unjoined_no_journal": 1}
    assert rep["journal"] == "absent"


def _decision(did, *, eligible=True, reasons=()):
    return {"schema_version": 2, "decision_id": did, "packet_id": "DP-20261027T1000Z-x", "packet_sha": "0" * 64,
            "packet_kind": "scan", "role": "entry_generation", "order_package_id": None,
            "judged_at": "2026-10-27T10:01:00Z", "info_cutoff_at": "2026-10-27T10:00:00Z",
            "model": "sonnet-tier", "prompt_sha": "p", "skill_sha": "s", "label_version": 1,
            "action": "propose_entry", "params": {"level": None, "level_atr": None, "frac": None, "bars": None},
            "proposal": {"symbol": "BTCUSDT", "side": "long", "expected_r_net": 0.4},
            "judge_prior": 0.55, "confidence": "suggestive", "basis": "ev_positive",
            "disposition": {"route": "none", "per_account": []},
            "external_context": {"used": bool(reasons)},
            "training": {"train_eligible": eligible, "gate_eligible": eligible, "exclusion_reasons": list(reasons)}}


def test_desk_rows_join_and_respect_training_marker(env):
    comms, _ = env
    _write(comms / "desk" / "decisions.jsonl", [
        _decision("DD-20261027T1000Z-a"),
        _decision("DD-20261027T1000Z-b", eligible=False, reasons=("external_context",)),
        _decision("DD-20261027T1000Z-c"),
    ])
    _write(comms / "desk" / "outcomes.jsonl", [
        {"decision_id": "DD-20261027T1000Z-a", "kind": "replayed", "computed_at": "2026-10-28T00:00:00Z",
         "net_r": 1.2, "provenance": "computed", "cost_policy": "bybit_perp", "order_package_id": None},
        {"decision_id": "DD-20261027T1000Z-b", "kind": "replayed", "computed_at": "2026-10-28T00:00:00Z",
         "net_r": 0.3, "provenance": "computed"},
    ])
    rows, rep = _run(comms, None)
    assert [r["judgment_id"] for r in rows] == ["DD-20261027T1000Z-a"]
    assert rows[0]["kind"] == "desk_entry_generation" and rows[0]["label_net_r"] == 1.2
    assert rep["excluded_by_reason"] == {"never_train:external_context": 1, "outcome_pending": 1}
    assert rep["partition_ok"]


def test_build_writes_dataset(env, tmp_path):
    comms, db = env
    _write(comms / "live_review" / "reviews.jsonl", [_review("LR-20261025T1616Z-pkg-1", 1)])
    _journal(db, [_trade(1)])
    paths = ClaudeJudgmentsBuilder().build(tmp_path / "out", "v001", source="test",
                                           comms_root=comms, db_path=db)
    meta = json.loads(paths.metadata.read_text())
    assert meta["row_count"] == 1 and meta["family"] == "claude_judgments"


def _grade(kind, tid, *, cutoff="2026-10-25T10:00:00Z", judged="2026-10-26T18:00:00Z"):
    base = {"schema_version": 1, "kind": kind, "order_package_id": f"pkg-{tid}", "trade_id": tid,
            "leg": "ada_pullback_2h", "judged_at": judged, "info_cutoff_at": cutoff,
            "decision_ts": "2026-10-25T10:00:00Z", "author_kind": "llm", "model_id": "claude-sonnet-5-5",
            "prompt_sha": "e951412992e1", "mask_version": "mask-v1", "packet_sha": "0" * 64,
            "run_id": "cj3-pilot-r1", "session_id": "s", "pre_cutoff": False}
    if kind == "blind_grade":
        return dict(base, judgment_id=f"BG-pkg-{tid}-e9514129", decision_grade="B", grade_score=3,
                    entry_quality="acceptable", risk_management="correct", p_win=0.4, expected_r=0, thesis="t")
    return dict(base, judgment_id=f"RG-pkg-{tid}-aaaaaaaa", blind_judgment_id=f"BG-pkg-{tid}-e9514129",
                revised_decision_grade="C", revised_grade_score=2, exit_quality="sl_appropriate",
                alternative_action="none", hindsight_note="h")


def test_blind_and_revealed_grades_join_the_journal(env):
    comms, db = env
    (comms / "claude_judgments").mkdir()
    _write(comms / "claude_judgments" / "blind_grades.jsonl", [_grade("blind_grade", 1)])
    _write(comms / "claude_judgments" / "revealed_grades.jsonl",
           [_grade("revealed_grade", 1, cutoff="2026-10-26T02:00:00Z")])
    _journal(db, [_trade(1)])
    rows, rep = _run(comms, db)
    # the blind row is T0 by construction; the revealed row saw the close (T1) and is label-only
    assert [r["kind"] for r in rows] == ["blind_grade"]
    assert rep["excluded_by_reason"] == {"t1_outcome_visible": 1} and rep["partition_ok"]
    r = rows[0]
    assert r["timing"] == "T0" and r["label_provenance"] == "judgment"
    assert r["grade_score"] == 3 and r["expected_r"] == 0.0 and isinstance(r["expected_r"], float)
    assert r["label_net_r"] == pytest.approx(1.9) and r["split_group"] == "pkg-1"
    rows_t1, _ = _run(comms, db, include_t1=True)
    rv = [x for x in rows_t1 if x["kind"] == "revealed_grade"][0]
    assert rv["timing"] == "T1" and rv["grade_score"] == 2 and rv["exit_quality"] == "sl_appropriate"
    # the builder's schema accepts the rows (the real build path validates every row)
    b = ClaudeJudgmentsBuilder()
    for x in rows_t1:
        b._validate_row(x, b.schema.keys())


def test_a_blind_row_that_saw_the_outcome_is_refused(env):
    comms, db = env
    (comms / "claude_judgments").mkdir()
    # cutoff after the trade closed (2026-10-26T02:00Z): this "blind" grade was not blind
    _write(comms / "claude_judgments" / "blind_grades.jsonl",
           [_grade("blind_grade", 1, cutoff="2026-10-26T03:00:00Z")])
    _journal(db, [_trade(1)])
    rows, rep = _run(comms, db, include_t1=True)
    assert rows == [] and rep["excluded_by_reason"] == {"blind_grade_not_t0": 1}


def test_revealed_grade_is_t1_by_kind_even_when_cutoff_truncation_reads_t0(env):
    comms, db = env
    (comms / "claude_judgments").mkdir()
    _write(comms / "claude_judgments" / "blind_grades.jsonl", [_grade("blind_grade", 1)])
    # cutoff = the close truncated to the second; journal closed_at has microseconds after it
    _write(comms / "claude_judgments" / "revealed_grades.jsonl",
           [_grade("revealed_grade", 1, cutoff="2026-10-26T02:00:00Z")])
    t = _trade(1, closed_at="2026-10-26T02:00:00.734000+00:00")
    _journal(db, [t])
    rows, rep = _run(comms, db)
    assert [r["kind"] for r in rows] == ["blind_grade"]
    assert rep["excluded_by_reason"] == {"t1_outcome_visible": 1}
