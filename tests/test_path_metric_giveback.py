"""P1-Q11 rung-1 label study (scripts/research/path_metric_giveback.py).

Planted/clean pair via the script's own self-test (a planted chop->giveback signal PASSES, a label drawn
independently of the path FAILS, a thin table is INDETERMINATE), the no-lookahead population rule, and an
end-to-end run on synthetic candles that writes a script_run-shaped verdict.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops"), str(REPO)]
import path_metric_giveback as pm  # noqa: E402


def test_self_test_planted_and_null():
    assert pm._self_test() == 0


def _row(b, c, exit_=False, peak=None):
    return {"trade_key": "l|S|2021-01-01 00:00:00+00:00|long", "bar_offset": b, "c_r": c, "fav_r": c + 0.05,
            "adv_r": c - 0.05, "open_r": c, "peak_r": peak if peak is not None else c + 0.05, "mae_r": 0.0,
            "bars_since_peak": 0, "is_exit": exit_}


def test_features_never_read_past_bar_k():
    rows = [_row(b, 0.1 * b) for b in range(1, 11)] + [_row(11, -5.0, exit_=True, peak=1.2)]
    f6 = pm.path_features(rows, 6)
    mutated = rows[:6] + [_row(b, 9.0) for b in range(7, 11)] + [_row(11, -5.0, exit_=True, peak=1.2)]
    assert pm.path_features(mutated, 6) == f6
    assert pm.giveback_label(rows) == 1.2 - (-5.0)


def test_end_to_end_writes_a_measured_verdict(tmp_path):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(7)
    ts = pd.date_range("2022-01-01", "2025-01-01", freq="4h", tz="UTC")
    c = 2000 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, len(ts))))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, len(ts))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, len(ts))))
    csv = tmp_path / "c.csv"
    pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S%z"), "open": o, "high": h, "low": lo,
                  "close": c, "volume": 1000.0}).to_csv(csv, index=False)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/path_metric_giveback.py"),
                        "--leg", "trend_donchian_eth_4h", "--k", "6", "--data-csv", str(csv), "--folds", "3",
                        "--fold-majority", "2", "--n-floor", "20", "--min-r2-gain", "0.02",
                        "--min-ll-gain", "0.01", "--big-quantile", "0.5", "--out", str(out)],
                       cwd=REPO, capture_output=True, text=True, check=False, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "measured" and v["verdict"] in pm.VERDICTS and v["population"]
    leg = v["measurement"]["per_leg"]["trend_donchian_eth_4h"]
    assert leg["n"] + leg["n_exited_by_k"] == leg["n_trades"]
    assert 0.0 < leg.get("big_share", 0.5) < 1.0


def test_shuffle_triggers_matches_rate_and_never_flags_unscored():
    rows = [{"trade_key": f"t{i}", "k": 6, "trigger": i % 3 == 0, "p": (None if i < 4 else 0.5)} for i in range(40)]
    rows = [{**r, "trigger": (r["trigger"] and r["p"] is not None)} for r in rows]
    out = pm.shuffle_triggers(rows, 7)
    assert sum(r["trigger"] for r in out) == sum(r["trigger"] for r in rows)
    assert not any(r["trigger"] for r in out if r["p"] is None)
    assert [r["trade_key"] for r in out] == [r["trade_key"] for r in rows]
    assert out != rows and out == pm.shuffle_triggers(rows, 7)  # random, but reproducible by seed


def test_p_threshold_makes_the_gate_more_selective():
    t, _, _ = pm.build_table(pm._synthetic(240, planted=True), k=6)
    lo = pm.oof_triggers(t, 6, folds=6, big_quantile=0.5, p_threshold=0.5)
    hi = pm.oof_triggers(t, 6, folds=6, big_quantile=0.5, p_threshold=0.7)
    assert sum(r["trigger"] for r in hi) <= sum(r["trigger"] for r in lo)
