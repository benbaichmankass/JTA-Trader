"""EXIT-ARM-CHOICE-CORPUS: scripts/research/exit_arm_chooser.py (AI-ATM rung C1, unit RQ-20261024-09a6-04).

The module's own self-test is the instrument's control (a planted arm x state interaction is recovered; shuffled state
and a no-interaction corpus find nothing). Here: that self-test, the join and its entry-set agreement, the purge, the
registered rule's branches, and an end-to-end harness run (two arms, real backtest_trend) on synthetic candles."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]
import exit_arm_chooser as eac  # noqa: E402


def test_self_test_controls():
    assert eac._self_test() == 0


def _row(t, d="long", net=0.1):
    return {"entry_time": t, "exit_time": t, "direction": d, "net_r": net}


def test_join_reports_entry_set_agreement_and_excludes_never_imputes():
    per_leg = {"L": {"A": [_row("2021-01-01 00:00:00+00:00"), _row("2021-01-02 00:00:00+00:00"), _row("2021-01-03 00:00:00+00:00")],
                     "B": [_row("2021-01-01 00:00:00+00:00"), _row("2021-01-03 00:00:00+00:00"), _row("2021-01-09 00:00:00+00:00")]}}
    joined, rep = eac.join_arms(per_leg, ["A", "B"], "A")
    assert [str(j["entry_time"]) for j in joined] == ["2021-01-01 00:00:00+00:00", "2021-01-03 00:00:00+00:00"]
    assert rep["n_union"] == 4 and rep["n_joined"] == 2 and rep["excluded_share"] == 0.5
    assert rep["legs"]["L"]["share_of_baseline_entries_in_arm"]["B"] == round(2 / 3, 4)


def test_join_key_includes_side_and_counts_duplicates():
    per_leg = {"L": {"A": [_row("2021-01-01", "long"), _row("2021-01-01", "short"), _row("2021-01-01", "short")],
                     "B": [_row("2021-01-01", "long")]}}
    joined, rep = eac.join_arms(per_leg, ["A", "B"], "A")
    assert len(joined) == 1 and joined[0]["side"] == "long"
    assert rep["legs"]["L"]["duplicate_keys_by_arm"] == {"A": 1}


def test_purge_drops_train_trades_overlapping_the_test_span():
    t0 = pd.Timestamp("2021-01-01", tz="UTC")
    joined = [{"entry_time": t0 + pd.Timedelta(days=d), "exit_time": t0 + pd.Timedelta(days=d + (40 if d == 49 else 1))} for d in range(0, 120)]
    folds = eac.calendar_folds(joined, 6)
    for f, (tr, te) in enumerate(folds):
        assert not set(tr) & set(te)
    # the trade entered on day 49 holds 40 days, into a later span: it must be absent from that span's training set
    i49 = 49
    later = [(tr, te) for tr, te in folds if te and joined[te[0]]["entry_time"] > joined[i49]["entry_time"] and
             joined[te[0]]["entry_time"] < joined[i49]["exit_time"]]
    assert later and all(i49 not in tr for tr, _ in later)


def _rep(n=1000, ex=0.0):
    return {"n_joined": n, "excluded_share": ex}


def _g(d, lo, hi, folds, c_cd, f_cd, dd_ok=True):
    return {"n_oos": 900, "vs_best_fixed": {"diff_r_per_trade": d, "ci95": [lo, hi], "folds_positive": folds},
            "capital_efficiency": {"chooser": {"net_r_per_capital_day": c_cd}, "fixed": {"net_r_per_capital_day": f_cd}},
            "maxdd_per_leg": {"L": {"ok": dd_ok}}}


def test_registered_rule_branches():
    kw = dict(min_n=600, max_excluded=0.10, min_gain=0.03, min_folds=4)
    assert eac.verdict(_rep(), _g(0.06, 0.02, 0.10, 5, 0.2, 0.1), **kw)[0] == "pass"
    assert eac.verdict(_rep(), _g(0.0, -0.02, 0.02, 3, 0.1, 0.1), **kw)[0] == "fail"
    # CI upper >= bar but a PASS clause fails -> neither pass nor fail
    for g in (_g(0.06, 0.02, 0.10, 3, 0.2, 0.1), _g(0.06, 0.02, 0.10, 5, 0.05, 0.1), _g(0.06, 0.02, 0.10, 5, 0.2, 0.1, dd_ok=False),
              _g(0.02, 0.01, 0.10, 5, 0.2, 0.1), _g(0.06, -0.01, 0.10, 5, 0.2, 0.1)):
        assert eac.verdict(_rep(), g, **kw)[0] == "indeterminate"
    assert eac.verdict(_rep(n=599), _g(0.06, 0.02, 0.10, 5, 0.2, 0.1), **kw)[0] == "indeterminate"
    assert eac.verdict(_rep(ex=0.11), _g(0.06, 0.02, 0.10, 5, 0.2, 0.1), **kw)[0] == "indeterminate"


def test_registered_thresholds_are_the_defaults_and_unit_rule_untouched():
    ap = __import__("argparse").ArgumentParser()
    eac.add_args(ap)
    a = ap.parse_args(["--out", "x"])
    assert (a.min_n, a.max_excluded, a.min_gain_r, a.min_folds, a.n_folds) == (600, 0.10, 0.03, 4, 6)
    unit = REPO / "research/queue/RQ-20261024-09a6-04.yaml"
    if unit.exists():
        rule = yaml.safe_load(unit.read_text())["decision_rule"]
        assert rule["id"] == "RULE-RQ20261024-09A6-04-ARM-CHOOSER" and rule["registered_before_run"] is True


def test_state_is_entry_bar_only():
    s = eac.entry_state({"f_atr_pctl": 0.7, "f_adx_14": 30.0, "f_atr_pctl_bucket": "high", "net_r": 9.9, "exit_reason": "tp", "mfe_r": 5.0}, 1.5)
    assert set(s) == set(eac.STATE_COLS) and s["vol_high"] == 1.0 and s["vol_mid"] == 0.0 and 9.9 not in s.values()


def test_end_to_end_two_arms_real_harness(tmp_path):
    rng = np.random.default_rng(7)
    ts = pd.date_range("2021-01-01", "2025-01-01", freq="4h", tz="UTC")
    c = 2000 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, len(ts))))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, len(ts))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, len(ts))))
    csv = tmp_path / "c.csv"
    pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S%z"), "open": o, "high": h, "low": lo, "close": c, "volume": 1000.0}).to_csv(csv, index=False)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/exit_arm_chooser.py"), "--leg", "trend_donchian_eth_4h",
                        "--arm", "A=", "--arm", "S=--momentum-stale-bars=8;--momentum-stale-adx-below=20",
                        "--data-csv", str(csv), "--n-boot", "100", "--out", str(out)],
                       cwd=REPO, capture_output=True, text=True, check=False, timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "measured" and v["verdict"] in ("pass", "fail", "indeterminate") and v["population"]
    m = v["measurement"]
    assert m["arms"] == ["A", "S"] and m["entry_set_agreement"]["n_union"] >= m["entry_set_agreement"]["n_joined"] > 0
    assert (out / "arms" / "trend_donchian_eth_4h__A__trades.jsonl").exists() and (out / "arms" / "trend_donchian_eth_4h__S__trades.jsonl").exists()
    assert m["adx_slope_match_share"]["trend_donchian_eth_4h"] > 0.9
    assert m["cost_policy_check"]["trend_donchian_eth_4h"]["state"] in ("match", "unmeasured")
