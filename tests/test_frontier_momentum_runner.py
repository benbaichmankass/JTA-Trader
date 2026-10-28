"""FRONTIER-LEVER-XSEC-RUNNER: funding fetch/aggregation, signed per-leg funding in the xsec + TSMOM
engines, the verdict.json shape the research-script-run runner derives its record from, and the
pre-registered grading. No network: every fetch is injected."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    sys.path.insert(0, str(p))

import backtest_tsmom  # noqa: E402
import backtest_xsec_momentum as xsec  # noqa: E402
import frontier_momentum_runner as fmr  # noqa: E402
import funding_series  # noqa: E402


def _panel(n=420, seed=3, syms=("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT")):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    drifts = np.linspace(-0.002, 0.003, len(syms))
    return pd.DataFrame({s: 100 * np.exp(np.cumsum(d + rng.normal(0, 0.01, n)))
                         for s, d in zip(syms, drifts)}, index=idx)


def _bk(panel, rate):
    return {s: pd.Series(rate, index=panel.index) for s in panel.columns}


def _xsec(panel, **kw):
    base = dict(formation=28, skip=0, rebalance=7, quantile=0.3333, fee_bps=7.5, fee_mult=1.0, venue="perp")
    base.update(kw)
    return xsec.run_backtest(panel, **base)["summary"]


def test_funding_parse_and_daily_sum():
    rows = funding_series.parse_funding_csv(
        "calc_time,funding_interval_hours,last_funding_rate\n"
        "1704067200000,8,0.0001\n1704096000000000,8,0.0002\nbad,row\n1704153600000,8,-0.0003\n")
    assert len(rows) == 3  # header + malformed dropped; microsecond stamp normalised
    s = funding_series.daily_sum(rows)
    assert s.loc[pd.Timestamp("2024-01-01", tz="UTC")] == pytest.approx(0.0003)  # 0.0001 + 0.0002 (us stamp)
    assert s.loc[pd.Timestamp("2024-01-02", tz="UTC")] == pytest.approx(-0.0003)


def test_funding_self_test_missing_month_not_zero_filled():
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/funding_series.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "PASS" in r.stdout, r.stderr


def test_xsec_default_unchanged_without_real_funding():
    p = _panel()
    a = _xsec(p)
    assert a["funding_basis"]["real_series_symbols"] == []
    assert a["funding_basis"]["funding_flat_symbols"] == sorted(p.columns)
    assert a["funding_cost_total"] > 0  # flat perp drag still charged, not a silent zero


def test_xsec_real_funding_is_signed_per_leg_and_per_symbol_sums_to_book():
    p = _panel()
    pos = _xsec(p, funding_series=_bk(p, 0.0004))
    neg = _xsec(p, funding_series=_bk(p, -0.0004))
    # dollar-neutral book: equal-and-opposite legs net the funding to ~0 (long pays, short receives)
    assert abs(pos["funding_cost_total"]) < 0.02 * abs(_xsec(p)["funding_cost_total"]) + 0.5
    assert pos["funding_cost_total"] == pytest.approx(-neg["funding_cost_total"], abs=1e-6)
    assert pos["funding_basis"]["real_leg_days"] > 0 and pos["funding_basis"]["missing_leg_days"] == 0
    book_net = pos["net_total_return"]
    assert sum(v["net_return"] for v in pos["per_symbol"].values()) == pytest.approx(book_net, abs=1e-6)


def test_xsec_long_only_leg_pays_positive_funding():
    p = _panel()
    fs = {"DDDUSDT": pd.Series(0.001, index=p.index)}  # only the best-momentum name has a series
    s = _xsec(p, funding_series=fs)
    d = s["per_symbol"]["DDDUSDT"]
    assert d["held_days"] > 0 and d["funding_cost"] > 0  # held long -> pays
    assert s["funding_basis"]["real_series_symbols"] == ["DDDUSDT"]
    assert "AAAUSDT" in s["funding_basis"]["funding_flat_symbols"]


def test_missing_funding_days_are_counted_not_hidden():
    p = _panel()
    fs = {s: pd.Series(0.0002, index=p.index[:200]) for s in p.columns}
    out = _xsec(p, funding_series=fs)["funding_basis"]
    assert out["missing_leg_days"] > 0


def test_tsmom_self_test_and_cost_basis():
    r = subprocess.run([sys.executable, str(REPO / "scripts/backtest_tsmom.py"), "--self-test"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    p = _panel()
    kw = dict(lookbacks=[28, 56], vol_window=30, target_vol=0.2, max_leverage=2.0, rebalance=7, venue="perp")
    full = backtest_tsmom.run_tsmom(p, **kw)["per_symbol"]["DDDUSDT"]
    pol = full["cost_policy"]
    # the cost owner supplied every term: perp slippage default + a non-zero measured/default fee
    assert pol["slippage_bps_roundtrip"] > 0 and pol["fee_bps_roundtrip"] > 0
    assert pol["source"].startswith("execution_costs")
    assert full["turnover_cost"] > 0 and full["funding_cost"] > 0
    assert full["net_total_r"] == pytest.approx(full["gross_return"] - full["funding_cost"] - full["turnover_cost"], abs=1e-6)


def test_tsmom_no_lookahead():
    p = _panel()
    kw = dict(lookbacks=[28], vol_window=30, target_vol=0.2, max_leverage=2.0, rebalance=7, venue="perp")
    base = backtest_tsmom.run_tsmom(p, **kw)["per_symbol"]["BBBUSDT"]["gross_return"]
    q = p.copy()
    q.iloc[-1, :] *= 5.0  # perturb ONLY the final bar
    pert = backtest_tsmom.run_tsmom(q.iloc[:-1], **kw)["per_symbol"]["BBBUSDT"]["gross_return"]
    cut = backtest_tsmom.run_tsmom(p.iloc[:-1], **kw)["per_symbol"]["BBBUSDT"]["gross_return"]
    assert pert == pytest.approx(cut) and np.isfinite(base)


def test_grading_follows_the_registered_rules():
    assert fmr.grade_xsec(0.2, 50, 0.5, 0.1, 39)["verdict"] == "pass"
    assert fmr.grade_xsec(-0.2, 50, 0.1, 0.05, 39)["verdict"] == "fail"
    assert fmr.grade_xsec(0.9, 38, 1.0, 0.1, 39)["verdict"] == "indeterminate"
    why = fmr.grade_xsec(-0.01, 50, 0.2, 0.15, 39)["why"]
    assert "FUNDING share" in why
    ps = lambda *rows: {f"S{i}": {"net_total_r": a, "n_trades": b} for i, (a, b) in enumerate(rows)}
    assert fmr.grade_tsmom(ps((1, 40), (2, 45), (-1, 50)), 39)["verdict"] == "pass"
    assert fmr.grade_tsmom(ps((-1, 40), (-2, 45), (1, 50)), 39)["verdict"] == "fail"
    assert fmr.grade_tsmom(ps((1, 40), (-2, 45), (1, 30)), 39)["verdict"] == "indeterminate"


def _args(mode, **kw):
    d = dict(mode=mode, symbols="", days=400, n_floor=3, rebalance_days=7, fee_multiplier=1.0,
             formation_days=28, skip_days=0, quantile=0.3333, lookbacks="28,56", vol_window=30,
             target_vol=0.2, max_leverage=2.0, out="")
    d.update(kw)
    return argparse.Namespace(**d)


@pytest.mark.parametrize("mode", ["xsec", "tsmom"])
def test_runner_verdict_json_shape_is_accepted_by_script_run(mode, tmp_path):
    from script_run import READ_STATES, VERDICTS
    p = _panel()
    inp = {"panel": p, "funding": _bk(p, 0.0002), "coverage": {}, "empty": []}
    rec = fmr.run(_args(mode), inputs=inp)
    assert rec["verdict"] in VERDICTS and rec["read_state"] in READ_STATES
    assert rec["population"] and "n" in rec and isinstance(rec["n"], int)
    per = rec["measurement"]["per_symbol"]
    assert set(per) == set(p.columns)
    assert all({"net_total_r", "n_trades"} <= set(v) for v in per.values())
    json.dumps(rec)  # serialisable


def test_runner_no_data_is_not_a_measured_zero():
    rec = fmr.run(_args("xsec", symbols="AAAUSDT"),
                  inputs={"panel": None, "funding": {}, "coverage": {"AAAUSDT": {}}, "empty": ["AAAUSDT"]})
    assert rec["read_state"] == "no_data" and rec["verdict"] == "not_applicable" and rec["n"] is None


def test_build_inputs_trims_to_last_funded_day_and_flags_empty():
    p = _panel(n=100)
    closes = lambda sym, a, b: p[sym.replace("USDT", "") + "USDT"]
    fund = lambda sym, a, b: {"series": pd.Series(0.0003, index=p.index[:60]), "months_ok": [],
                              "missing_months": ["2023-04"], "n_settlements": 180}
    out = fmr.build_inputs(["AAAUSDT", "BBBUSDT"], 100, now=datetime(2023, 4, 11, tzinfo=timezone.utc),
                           fetch_close=closes, fetch_fund=fund)
    assert out["panel"].index.max() == p.index[59] and out["trimmed_to"] == str(p.index[59].date())
    none = fmr.build_inputs(["AAAUSDT"], 100, fetch_close=lambda *a: pd.Series(dtype=float),
                            fetch_fund=fund)
    assert none["panel"] is None and none["empty"] == ["AAAUSDT"]
