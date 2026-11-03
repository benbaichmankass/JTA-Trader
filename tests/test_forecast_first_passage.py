"""FORECAST-GRADE-FIRST-PASSAGE: three classes, same-bar ties from 1m, pending, frozen ledger, ML label join."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "scripts" / "research"):
    sys.path.insert(0, str(_p))

import forecast_first_passage as ffp  # noqa: E402
from ml.datasets.families import claude_judgments as cj  # noqa: E402

T0 = 1_800_000_000 - (1_800_000_000 % 3600)          # on an hour boundary
FC = {"target_px": 110.0, "invalidation_px": 95.0, "horizon_bars": 3, "timeframe": "1h", "p_target": 0.4}


def bar(t, lo, hi, c=100.0):
    return {"time": t, "open": 100.0, "high": hi, "low": lo, "close": c}


def hours(*specs):
    return [bar(T0 + i * 3600, lo, hi) for i, (lo, hi) in enumerate(specs)]


def test_target_first_invalidation_first_expired():
    now = T0 + 10 * 3600
    assert ffp.first_passage(FC, T0, hours((99, 111), (99, 100), (99, 100), (99, 100)), None, now)["class"] == "target_first"
    assert ffp.first_passage(FC, T0, hours((99, 101), (94, 101), (99, 111), (99, 100)), None, now)["class"] == "invalidation_first"
    r = ffp.first_passage(FC, T0, hours((99, 101), (99, 101), (99, 101), (99, 101)), None, now)
    assert r["class"] == "expired" and r["resolved_at"].endswith("Z")


def test_touch_after_horizon_is_expired_not_target():
    now = T0 + 10 * 3600
    assert ffp.first_passage(FC, T0, hours((99, 101), (99, 101), (99, 101), (99, 120)), None, now)["class"] == "expired"


def test_pending_before_horizon_carries_time_remaining_and_gradable_once_a_level_trades():
    now = T0 + 3600 + 100
    r = ffp.first_passage(FC, T0, hours((99, 101), (99, 101)), None, now)
    assert r["class"] == "pending" and r["time_remaining_s"] == 3 * 3600 - 3700
    assert ffp.first_passage(FC, T0, hours((99, 101), (99, 112)), None, now)["class"] == "target_first"   # early, still open


def test_same_bar_double_touch_resolved_from_1m_else_unresolved_never_assigned():
    now = T0 + 10 * 3600
    h = hours((94, 111), (99, 101), (99, 101), (99, 101))
    assert ffp.first_passage(FC, T0, h, None, now)["class"] == "tie_unresolved"
    mins = [bar(T0 + 60 * i, 99, 101) for i in range(60)]
    mins[7] = bar(T0 + 60 * 7, 99, 111)              # target minute first
    mins[20] = bar(T0 + 60 * 20, 94, 101)
    assert ffp.first_passage(FC, T0, h, mins, now)["class"] == "target_first"
    mins[7] = bar(T0 + 60 * 7, 94, 111)              # one minute touches both: still unresolved
    assert ffp.first_passage(FC, T0, h, mins, now)["class"] == "tie_unresolved"
    assert ffp.first_passage(FC, T0, h, mins[:30], now)["class"] == "tie_unresolved"     # partial 1m coverage


def test_short_forecast_and_no_candles_are_null_states_not_misses():
    now = T0 + 10 * 3600
    short = dict(FC, target_px=90.0, invalidation_px=105.0)
    assert ffp.first_passage(short, T0, hours((89, 101), (99, 101)), None, now)["class"] == "target_first"
    assert ffp.first_passage(FC, T0, None, None, now)["class"] == "no_data"
    assert ffp.first_passage(FC, T0, hours((99, 101)), None, now)["class"] == "no_data"   # candles end before the horizon
    assert ffp.first_passage(dict(FC, horizon_bars=None), T0, hours((99, 101)), None, now)["class"] == "no_data"


def test_summary_brier_per_class_and_unresolved_reported():
    rows = [{"class": "target_first", "p_target": 0.8, "package": "a", "direction_hit": True},
            {"class": "invalidation_first", "p_target": 0.5, "package": "a", "direction_hit": False},
            {"class": "expired", "p_target": 0.5, "package": "b", "direction_hit": None},
            {"class": "pending", "p_target": 0.9}, {"class": "tie_unresolved", "p_target": 0.1},
            {"class": "no_data", "p_target": None}]
    s = ffp.summarise(rows)
    assert s["classes"]["expired"] == 1 and s["unresolved_ties"] == 1 and s["classes"]["pending"] == 1
    assert s["brier_by_class"]["target_first"]["brier"] == 0.04 and s["brier_by_class"]["expired"]["brier"] == 0.25
    assert s["brier_overall"] == round((0.04 + 0.25 + 0.25) / 3, 4)
    assert s["direction_hit_rate"] == {"n": 2, "rate": 0.5} and s["n_graded"] == 3 and s["n_packages"] == 2


def test_run_freezes_final_rows_and_normalises_both_sources():
    review = {"review_id": "LR-1", "order_package_id": "pkg-1", "reviewed_at": "2027-01-15T08:00:00Z", "forecast": dict(FC)}
    desk = [{"decision_id": "DD-1", "judged_at": "2027-01-15T08:00:00Z", "order_package_id": None,
             "proposal": {"symbol": "XUSDT", "timeframe": "1h", "horizon_bars": 3, "stop": {"level": 95.0},
                          "tp": {"level": 110.0, "p_hit": 0.3}}},
            {"decision_id": "DD-2", "proposal": None}]
    t0 = ffp.cf._ts("2027-01-15T08:00:00Z")
    bars = [bar(t0 + i * 3600, 99, 101) for i in range(5)]
    prior = {"LR-1": {"fid": "LR-1", "source": "live_review", "class": "invalidation_first", "package": "pkg-1"}}
    out = ffp.run([review], desk, {"pkg-1": {"symbol": "XUSDT"}}, lambda s, tf: bars if tf == "1h" else None, prior, t0 + 9 * 3600)
    by = {x["fid"]: x for x in out["_ledger"]}
    assert by["LR-1"]["class"] == "invalidation_first"             # frozen, not re-derived
    assert by["DD-1"]["class"] == "expired" and by["DD-1"]["p_target"] == 0.3
    assert out["inventory"]["desk_entry"] == {"records": 2, "with_forecast": 1, "no_trade_without_forecast": 1}
    assert "DD-2" not in by


def test_claude_judgments_label_columns():
    assert "fc_outcome" in cj.JUDGMENT_COLUMNS and "fc_resolved_at" in cj.JUDGMENT_COLUMNS
    assert cj._fc_outcome_cols({"class": "expired", "resolved_at": "Z"}) == {"fc_outcome": "expired", "fc_resolved_at": "Z"}
    for e in (None, {"class": "pending"}, {"class": "tie_unresolved"}, {"class": "no_data"}):
        assert cj._fc_outcome_cols(e) == {"fc_outcome": None, "fc_resolved_at": None}
