"""DESK-9-GRADING: the no_trade counterfactual, the per-role n ledger (never folds 'could not grade' into a grade), the
earliest-ETA arithmetic, the snapshot churn rule, and that the schedule carriers actually run the graders."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "scripts" / "research", REPO / "scripts" / "ops", REPO / "scripts" / "ci"):
    sys.path.insert(0, str(_p))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load("claude_role_grade", "scripts/ops/claude_role_grade.py")
dg = rg.dg
T0 = datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
FREE = lambda s, e, x, r, h: 0.0  # noqa: E731


def _bars(drift: float, start=T0) -> list:
    out, px = [], 100.0
    for i in range(400):
        px += drift + (0.5 if i % 2 else -0.5)
        out.append({"time": int(start.timestamp()) + (i - 60) * 3600, "open": px, "high": px + 0.4, "low": px - 0.4, "close": px})
    return out


def _dec(i: int, cutoff: datetime) -> dict:
    return {"decision_id": f"DD-{cutoff:%Y%m%dT%H%M}Z-scan-1h-{i}", "packet_id": "P", "role": "entry_generation", "action": "no_trade",
            "judged_at": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"), "info_cutoff_at": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "alternatives": [{"action": "propose_entry", "symbol": "AAA", "side": "long", "mean_r": 0.3}]}


PK = {"universe": [{"symbol": "AAA", "timeframe": "1h"}, {"symbol": "BBB", "timeframe": "1h"}],
      "system_book": {"items": [{"status": "near_signal", "symbol": "BBB", "side": "short", "bars_to_signal": 2},
                                {"status": "near_signal", "symbol": "AAA", "side": "long", "bars_to_signal": 1}]}}


def test_no_trade_is_awaiting_until_its_horizon_elapses():
    r = rg.price_no_trade(_dec(1, T0), PK, lambda s, tf: _bars(0), T0 + timedelta(hours=11), cost=FREE)
    assert r["state"] == "awaiting"


def test_declining_a_rising_candidate_is_priced_as_lost_value_and_uses_the_strongest_near_signal():
    r = rg.price_no_trade(_dec(1, T0), PK, lambda s, tf: _bars(0.2), T0 + timedelta(hours=13), cost=FREE)
    assert r["state"] == "priced" and r["abstain_value"] < 0 and r["top_alternative"]["symbol"] == "AAA"
    assert r["near_signal_strongest"] == r["top_alternative"]["r"]      # AAA long has bars_to_signal 1 < BBB short 2
    assert r["hindsight_best_cell"] >= r["top_alternative"]["r"]


def test_random_entry_baseline_is_context_not_the_verdict_basis():
    r = rg.price_no_trade(_dec(1, T0), PK, lambda s, tf: _bars(0.2), T0 + timedelta(hours=13),
                          cost=lambda s, e, x, r_, h: 0.1)
    assert r["abstain_value_vs_random"] == 0.1 and r["abstain_value"] != r["abstain_value_vs_random"]


def test_missing_candles_are_never_a_zero_grade():
    now = T0 + timedelta(days=4)
    assert rg.price_no_trade(_dec(1, T0), PK, lambda s, tf: None, now, cost=FREE)["state"] == "could_not_look"
    assert rg.price_no_trade(_dec(1, T0), None, lambda s, tf: _bars(0), now, cost=FREE)["state"] == "could_not_look"
    part = lambda s, tf: _bars(0) if s == "AAA" else None  # noqa: E731
    assert rg.price_no_trade(_dec(1, T0), PK, part, T0 + timedelta(hours=14), cost=FREE)["state"] == "awaiting"   # inside grace
    after = rg.price_no_trade(_dec(1, T0), PK, part, now, cost=FREE)
    assert after["state"] == "priced" and after["n_symbols_unavailable"] == 1                                       # excluded, counted


def test_independent_windows_are_spaced_by_the_horizon():
    ps = [{"cutoff": T0 + timedelta(hours=i), "abstain_value": 0.1} for i in range(30)]
    assert [p["cutoff"] for p in rg.independent(ps)] == [T0, T0 + timedelta(hours=12), T0 + timedelta(hours=24)]


def _grade(n_hours: int, drift: float):
    # decisions every hour; the candles carry enough history for ATR before each cutoff and 12+ bars after
    ds = [_dec(i, T0 + timedelta(hours=i)) for i in range(n_hours)]
    return rg.grade_no_trade(ds, lambda pid: PK, lambda s, tf: _bars(drift), T0 + timedelta(days=30))


def test_below_twenty_independent_windows_is_insufficient_n_with_the_numbers_still_shown():
    g = _grade(60, 0.2)                      # 60 hourly decisions -> 5 independent 12h windows
    assert g["state"] == "insufficient_n" and g["verdict"].startswith("INSUFFICIENT_N")
    assert g["n_priced"] == 60 and g["n_independent"] == 5 and g["abstain_value_independent"]["n"] == 5


def test_twenty_independent_windows_grade_and_the_sign_decides_the_verdict():
    lost = _grade(240, 0.2)                  # declining a rising long, 20 independent windows
    assert lost["n_independent"] == 20 and lost["state"] == "graded"
    assert lost["verdict"] in ("NO_TRADE_COSTS_VALUE", "INDETERMINATE (interval includes 0)")
    saved = rg.grade_no_trade([_dec(i, T0 + timedelta(hours=i)) for i in range(240)], lambda pid: PK,
                              lambda s, tf: _bars(-0.2), T0 + timedelta(days=30))
    assert saved["state"] == "graded" and saved["abstain_value_independent"]["mean"] > 0


def test_without_candles_nothing_is_graded_and_the_reason_is_named():
    g = rg.grade_no_trade([_dec(1, T0)], lambda pid: PK, None, T0 + timedelta(days=30))
    assert g["n_priced"] == 0 and g["n_could_not_look"] == 1 and "candles not read" in next(iter(g["could_not_look_reasons"]))


def test_eta_arithmetic():
    now = T0
    assert rg.eta(0, 0, 20, 2.0, 0.5, now)["eta_earliest"] == (now + timedelta(days=10.5)).date().isoformat()
    assert rg.eta(5, 5, 20, 5.0, 1.0, now)["eta_earliest"] == (now + timedelta(days=2 + 1)).date().isoformat()   # 10 more at 5/day + 1d
    assert rg.eta(0, 0, 20, None, 1.0, now)["eta_earliest"] is None and "no accrual" in rg.eta(0, 0, 20, None, 1.0, now)["eta_note"]
    assert rg.eta(20, 0, 20, 1.0, 1.0, now)["eta_note"] == "already at n_needed"
    ready = ["2026-10-30T00:00:00Z", "2026-10-28T00:00:00Z", "2026-10-29T00:00:00Z"]
    assert rg.eta(0, 3, 3, 1.0, 1.0, now, ready)["eta_earliest"] == "2026-10-30"   # all three already recorded: the last one to become gradeable
    assert rg.eta(0, 3, 4, 1.0, 1.0, now, ready)["eta_earliest"] == "2026-10-28"   # one short: 1 more call at 1/day + 1d lag
    assert rg._rate_per_day([None, T0 - timedelta(days=30)], T0) is None                      # nothing in the 7d window is no rate


def _desk_g():
    return dg.grade([], [], system_trades=None)


def test_role_table_states_never_fold_could_not_grade_into_a_grade():
    nt = rg.grade_no_trade([_dec(1, T0)], lambda pid: PK, None, T0 + timedelta(days=1))
    ds = [_dec(1, T0), {"decision_id": "DD-20261026T0100Z-scan-1h-2", "role": "entry_generation", "action": "watch_note",
                        "judged_at": "2026-10-26T01:00:00Z"}]
    rows = rg.role_table(_desk_g(), None, nt, ds, [{"review_id": "x"}], T0 + timedelta(days=1))
    by = {(r["role"], r["class"]): r for r in rows}
    assert by[("entry_generation", "propose_entry vs random entry")]["state"] == "no_data"
    assert by[("entry_generation", "no_trade vs entering (counterfactual)")]["state"] == "insufficient_n"
    assert by[("entry_generation", "watch_note")]["state"] == "not_gradeable_by_design"
    ltr = by[("in_trade (live review)", "all")]
    assert ltr["state"] == "could_not_look" and ltr["n_graded"] == 0 and ltr["n_not_yet_graded"] == 1


def test_no_trade_eta_counts_independent_windows_not_raw_decisions():
    ds = [_dec(i, T0 + timedelta(hours=i)) for i in range(24)]            # 24 hourly decisions = 2 independent 12h windows
    nt = rg.grade_no_trade(ds, lambda pid: PK, None, T0 + timedelta(hours=30))
    assert nt["n_recorded"] == 24 and nt["n_independent_recorded"] == 2
    row = next(r for r in rg.role_table(_desk_g(), None, nt, ds, [], T0 + timedelta(hours=30)) if r["class"].startswith("no_trade"))
    assert row["recorded_per_day_7d"] <= 2 and "18 more" in row["eta_note"]                                  # 20 - 2 pending, not 20 - 24


def test_role_table_carries_every_altering_class_with_its_n_needed():
    ltr_g = {"use_rules": {"tighten_sl": {"n": 3, "n_applied": 1, "mean_dr": 0.1, "ci95": None, "verdict": "HOLD_SCOPE (INDETERMINATE: n=3 < 20)"}},
             "population": {"could_not_price_reasons": {"open": 2}}, "hold_vs_close": {"n": 4, "mean_dr": 0.0},
             "calibration": {}}
    rvs = [{"review_id": f"r{i}", "reviewed_at": (T0 - timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "recommendation": {"action": "tighten_sl"}} for i in range(5)]
    rows = rg.role_table(_desk_g(), ltr_g, rg.grade_no_trade([], lambda p: None, None, T0), [], rvs, T0)
    by = {r["class"]: r for r in rows if r["role"].startswith("in_trade")}
    assert set(rg.ALTERING) <= set(by) and all(by[a]["n_needed"] == 20 for a in rg.ALTERING)
    t = by["tighten_sl"]
    assert (t["n_recorded"], t["n_graded"], t["n_not_yet_graded"], t["state"]) == (5, 3, 2, "insufficient_n")
    assert by["close"]["state"] == "no_data" and by["close"]["eta_earliest"] is None


def test_snapshot_is_not_rewritten_for_a_timestamp_alone(tmp_path):
    g = {"generated_at": "2026-10-26T00:00:00Z", "rows": [{"role": "r", "class": "c", "n_recorded": 1, "n_graded": 0,
                                                            "n_not_yet_graded": 1, "state": "insufficient_n", "verdict": None}]}
    p = tmp_path / "s.json"
    assert rg.write_snapshot(g, p, T0) and not rg.write_snapshot(dict(g, generated_at="2026-10-26T05:00:00Z"), p, T0 + timedelta(hours=5))
    moved = json.loads(json.dumps(g))
    moved["rows"][0]["n_graded"] = 1
    assert rg.write_snapshot(moved, p, T0 + timedelta(hours=5))
    assert rg.write_snapshot(moved, p, T0 + timedelta(hours=40))                                    # age rolls it daily


def test_the_schedule_carriers_run_the_graders():
    desk = (REPO / ".github/workflows/desk-decisions-mirror.yml").read_text()
    ltr = (REPO / ".github/workflows/live-review-rows-mirror.yml").read_text()
    assert "claude_role_grade.py --live --write comms/desk/role_grade.json" in desk and "steps.grade.outputs.changed" in desk
    assert "live_review_grade.py --live --write-outcomes" in ltr and "steps.price.outputs.changed" in ltr
    assert "DIAG_READ_TOKEN" in desk and "DIAG_READ_TOKEN" in ltr
    assert desk.count("continue-on-error: true") >= 1 and ltr.count("continue-on-error: true") >= 1   # grading never stops the mirror


def test_c13_flags_a_missing_or_stale_snapshot():
    import check_claude_grade_loop as c13
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    assert c13.role_grade_check(None, now)["state"] == "fail"
    assert c13.role_grade_check({"generated_at": "2026-10-20T00:00:00Z", "rows": []}, now)["state"] == "fail"
    assert c13.role_grade_check({"generated_at": "2026-11-01T12:00:00Z", "rows": []}, now)["state"] == "pass"
