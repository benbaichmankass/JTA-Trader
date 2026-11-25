"""F8 cross-asset / macro-state ENTRY family (row D3-POINT-IN-TIME-MACRO-BUILDER, lane RESEARCH-UNBLOCK-BUILDS-W48).

Leakage (truncation invariance + the US-close boundary), NaN-not-zero, the ablation arm wiring and the verdict map."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO)]
import ml_entry_families as F  # noqa: E402


def test_f8_self_test():
    F._self_test_f8()


def test_f8_columns_and_market_wide_values():
    daily = F._macro_synthetic()
    ts = pd.Series(pd.date_range("2024-01-15", periods=48, freq="1h", tz="UTC"))
    out = F.f8(ts, daily)
    assert list(out.columns) == ["ts"] + F.FAMILIES["F8"] and len(F.FAMILIES["F8"]) == 21
    assert out["f8_present"].eq(1).all()
    # within one day before the close the value is constant (the last completed session), and it changes after 22:00 UTC
    day = out[out.ts.dt.date == pd.Timestamp("2024-01-15").date()]
    assert day[day.ts.dt.hour < 21]["f8_spy_r1"].nunique() == 1
    assert day[day.ts.dt.hour >= 21]["f8_spy_r1"].nunique() == 1
    assert day[day.ts.dt.hour < 21]["f8_spy_r1"].iloc[0] != day[day.ts.dt.hour >= 21]["f8_spy_r1"].iloc[0]


def test_missing_ticker_is_nan_never_zero():
    daily = F._macro_synthetic()
    daily.pop("UUP")
    out = F.f8(pd.Series(pd.date_range("2024-02-01", periods=5, freq="1h", tz="UTC")), daily)
    assert out[[c for c in F.FAMILIES["F8"] if c.startswith("f8_uup_")]].isna().all().all()
    assert out["f8_spy_r1"].notna().all()


def test_load_macro_daily_roundtrip(tmp_path):
    for t, df in F._macro_synthetic().items():
        df.to_csv(tmp_path / f"{t}.csv", index=False)
    got = F.load_macro_daily(tmp_path)
    assert set(got) == set(F.MACRO_TICKERS)
    ts = pd.Series(pd.date_range("2024-02-01", periods=5, freq="1h", tz="UTC"))
    assert np.allclose(F.f8(ts, got)[F.FAMILIES["F8"]].to_numpy(float), F.f8(ts, F._macro_synthetic())[F.FAMILIES["F8"]].to_numpy(float),
                       equal_nan=True)


def test_ablation_arm_and_verdict_map(tmp_path):
    import ml_entry_v2 as V
    import ml_entry_v2_run as R
    assert V.ARMS["M"] == ["F8"] and V.features_for("M")[-1] == "f8_present"
    assert all(c in V.ALL_FAM_COLS for c in F.FAMILIES["F8"])
    for word, want in (("admit", "pass"), ("reject", "fail"), ("indeterminate", "indeterminate")):
        (tmp_path / "ablation.json").write_text(json.dumps({"rule": "r", "baseline_A": {}, "noise_floor_abs_A_minus_A2": 0.001,
                                                            "arms": {"M": {"verdict": word, "n": 10, "dev_coverage": 0.9}}}))
        assert R.write_ablation_trend_verdict("RQ-X", tmp_path, arm_key="M", family="F8 cross-asset / macro-state")
        v = json.loads((tmp_path / "verdict.json").read_text())
        assert v["verdict"] == want and "F8" in v["population"] and v["measurement"]["M"]["verdict"] == word
    # the F7 path is unchanged
    (tmp_path / "ablation.json").write_text(json.dumps({"arms": {"T": {"verdict": "admit", "n": 1}}}))
    assert R.write_ablation_trend_verdict("RQ-X", tmp_path)
    assert json.loads((tmp_path / "verdict.json").read_text())["verdict"] == "pass"
