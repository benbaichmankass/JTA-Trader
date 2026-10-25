"""ML-LEG-CORPUS: the live-leg corpus runner and the R-basis four-baseline grader.

Pins the distinctions (not today's numbers):
  * the two new features are DECISION-TIME columns, never outcomes, and a null
    ADX drops the row rather than being imputed;
  * B1..B4 are four DIFFERENT forecasts and an unformable one fails the gate
    closed instead of shrinking the eval set;
  * the all-four gate fires on a planted signal and not on noise (as a RATE);
  * the runner's completeness grade reports a thin stratum and refuses a
    corpus whose rows are all unusable.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ml2_bracket_train_eval as te  # noqa: E402
import ml2_live_leg_corpus as llc  # noqa: E402
from ml2_bracket_corpus import (  # noqa: E402
    FEATURE_NAMES, LEGACY_FEATURE_NAMES, OUTCOME_NAMES, build_row, complete_rows,
)

_EMIT = {"strategy": "x", "symbol": "ETHUSDT", "entry_time": "2026-01-02 13:00:00",
         "exit_time": "2026-01-02 18:00:00", "entry": 100.0, "sl": 98.0, "direction": "long",
         "gross_r": 2.0, "net_r": 1.9, "mfe_r": 3.0, "confidence": 0.4,
         "adx_at_entry": 31.0, "regime_weight": 1.0}


def test_new_features_are_decision_time_and_closed():
    assert FEATURE_NAMES[-2:] == ("adx_at_entry", "regime_weight")
    assert not set(FEATURE_NAMES) & set(OUTCOME_NAMES)
    assert LEGACY_FEATURE_NAMES == FEATURE_NAMES[:6]
    # one index serves every feature set
    assert FEATURE_NAMES.index("risk_frac") == LEGACY_FEATURE_NAMES.index("risk_frac") == 0


def test_adx_and_weight_are_carried_and_null_adx_drops_the_row():
    r = build_row(dict(_EMIT))
    assert r["adx_at_entry"] == 31.0 and r["regime_weight"] == 1.0
    nulled = build_row(dict(_EMIT, adx_at_entry=None))
    assert nulled["adx_at_entry"] is None          # not 0.0
    kept, dropped = complete_rows([r, nulled], "mfe_r")
    assert len(kept) == 1 and dropped["missing_feature"] == 1
    # the legacy list does not need ADX, so the old corpus stays gradable
    kept2, _ = complete_rows([nulled], "mfe_r", LEGACY_FEATURE_NAMES)
    assert len(kept2) == 1


def _rows(n, *, signal, seed, declared=3.0, class_default=2.0):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        rf = rng.uniform(0.005, 0.05)
        adx = rng.uniform(10, 50)
        base = (0.5 + adx / 20.0) if signal else 1.5     # signal: R-MFE depends on ADX
        mfe = max(0.0, base + rng.expovariate(1 / 0.6))
        rows.append({"leg": "L", "stratum": "S", "entry_time": f"2026-01-{1 + i % 28:02d} {i % 24:02d}:{i % 60:02d}:00",
                     "risk_frac": rf, "is_long": float(i % 2), "confidence": rng.random(),
                     "hour_sin": math.sin(i), "hour_cos": math.cos(i), "dow": float(i % 7),
                     "adx_at_entry": adx, "regime_weight": 1.0, "mfe_r": mfe,
                     "declared_tp_r": declared, "class_default_tp_r": class_default})
    return rows


def test_four_baselines_are_four_different_forecasts():
    rows = _rows(200, signal=False, seed=1)
    X = [[r[k] for k in FEATURE_NAMES] for r in rows]
    y = [r["mfe_r"] for r in rows]
    bl = te.r_baselines(rows[100:], y[:100], X[:100], X[100:], 0.8)
    assert set(bl) == {"B1", "B2", "B3", "B4"}
    assert set(bl["B1"]) == {3.0} and set(bl["B2"]) == {2.0}
    assert len(set(bl["B3"])) == 1                      # constant multiple of risk
    assert len(set(bl["B4"])) > 1                       # %-of-entry: varies with risk_frac
    # B4 is the %-of-entry quantile re-expressed in R, so it is inversely tied to risk
    pairs = sorted(zip((x[0] for x in X[100:]), bl["B4"]))
    assert pairs[0][1] > pairs[-1][1]


def test_unformable_baseline_fails_the_gate_closed():
    rows = _rows(400, signal=True, seed=2)
    for r in rows:
        r["declared_tp_r"] = None                       # a leg with no declared target
    res = te.evaluate(rows, outcome="mfe_r", control_trials=4, quantiles=(0.5, 0.8))
    assert all(s["vs_B1_state"] == te.BASELINE_UNAVAILABLE for s in res["sharpness"])
    assert res["sharp_vs_all_baselines_count"] == 0     # never a pass by omission


def test_r_basis_reports_basis_and_all_four_columns():
    res = te.evaluate(_rows(400, signal=True, seed=3), outcome="mfe_r",
                      control_trials=4, quantiles=(0.5, 0.8))
    assert res["basis"] == "r"
    for s in res["sharpness"]:
        for b in te.BASELINES:
            assert f"vs_{b}_state" in s and f"vs_{b}_improvement" in s


def test_all_four_gate_fires_on_signal_not_noise_as_a_rate():
    def fires(signal):
        hits = 0
        for sd in range(3):
            res = te.evaluate(_rows(450, signal=signal, seed=10 + sd), outcome="mfe_r",
                              control_trials=6, seed=sd)
            if res["sharp_vs_all_baselines_count"] >= 3:
                hits += 1
        return hits
    assert fires(True) >= 2          # finds the ADX dependence that IS there
    assert fires(False) <= 1         # and does not invent one


def test_percent_of_entry_path_is_unchanged_by_the_r_basis():
    rows = _rows(300, signal=False, seed=4)
    for r in rows:
        r["mfe_frac"] = r["mfe_r"] * r["risk_frac"]
    res = te.evaluate(rows, outcome="mfe_frac", control_trials=4, quantiles=(0.5, 0.8))
    assert res["basis"] == "percent_of_entry"
    assert "vs_B1_state" not in res["sharpness"][0]


def test_runner_roster_is_the_six_registered_legs_in_three_strata():
    legs = llc.load_legs()
    assert len(legs) == 6
    assert sorted(set(llc.STRATA.values())) == [
        "S1_bybit2_donchian_4h", "S2_bybit2_pullback_2h", "S3_prop_donchian_1h"]
    with pytest.raises(SystemExit):
        llc.load_legs(["not_a_registered_leg"])


def test_runner_adds_the_noop_band_only_where_no_adx_lever_is_declared():
    legs = llc.load_legs()
    assert not llc.has_adx_lever(legs["trend_donchian_eth_4h"])
    assert llc.has_adx_lever(legs["xrp_pullback_2h"])
    assert llc.ADX_NOOP_BAND == ["--adx-max", "100"]    # ADX <= 100 always: excludes nothing


def test_grade_reports_thin_stratum_and_refuses_unusable_rows():
    row = {"leg": "trend_donchian_eth_4h", "mfe_r": 1.0, **{k: 1.0 for k in FEATURE_NAMES}}
    recs = [{"leg": "trend_donchian_eth_4h", "state": "ok"}]
    thin = llc.grade(recs, [row] * 10)
    assert thin["verdict"] == "pass"
    assert thin["measurement"]["strata_below_eval_floor"] == {"S1_bybit2_donchian_4h": 10}
    assert llc.grade(recs, [dict(row, adx_at_entry=None)] * 300)["verdict"] == "indeterminate"
    assert llc.grade(recs, [])["read_state"] == "no_data"
    assert llc.grade([{"leg": "trend_donchian_eth_4h", "state": "adx_band_not_noop"}],
                     [row] * 300)["verdict"] == "indeterminate"
