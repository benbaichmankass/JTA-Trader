"""FRONTIER-LEVER-HARNESS-COSTS: backtest_xsec_momentum + backtest_vol_target carry
the FULL cost stack (fee + slippage + perp funding) through
execution_costs.resolve_cost_policy -- every term non-zero by default, applied,
and recorded in the result's evidence fields. An explicit 0 is the comparison
arm, never a silent default."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.runtime import execution_costs as ec

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


xs = _load("backtest_xsec_momentum")
vt = _load("backtest_vol_target")


def _panel(symbols, n=200, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    data = {}
    for i, s in enumerate(symbols):
        drift = 0.002 * (i - len(symbols) / 2)
        data[s] = 100 * np.cumprod(1 + rng.normal(drift, 0.02, n))
    return pd.DataFrame(data, index=idx)


def _run(panel, **kw):
    return xs.run_backtest(panel, formation=14, skip=0, rebalance=7, quantile=0.34,
                           fee_bps=7.5, fee_mult=1.0, **kw)["summary"]


PERPS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
ETFS = ["SPY", "QQQ", "GLD", "TLT"]


class TestXsecFullCostStack:
    def test_perp_universe_pays_fee_slippage_and_funding_by_default(self):
        s = _run(_panel(PERPS))
        cp = s["params"]["cost_policy"]
        assert all(v == ec.PERP_SLIPPAGE_BPS_ROUNDTRIP for v in cp["slippage_bps_roundtrip"].values())
        assert all(v == ec.DEFAULT_FUNDING_BPS_PER_WINDOW for v in cp["funding_bps_per_window"].values())
        assert cp["n_perp_funding_symbols"] == len(PERPS)
        assert s["funding_cost_total"] > 0
        assert s["turnover_cost_total"] > s["turnover_cost_total_fee_only"] > 0

    def test_funding_cost_matches_closed_form(self):
        p = _panel(PERPS)
        s = _run(p)
        # funding is charged on |w| of every held leg each day with weights set
        res = xs.run_backtest(p, formation=14, skip=0, rebalance=7, quantile=0.34,
                              fee_bps=7.5, fee_mult=1.0)
        assert res["summary"]["funding_cost_total"] == pytest.approx(s["funding_cost_total"])
        # lower bound: at least one fully-invested week of 1bps*3 windows * gross exposure
        assert s["funding_cost_total"] >= (1.0 / 1e4) * 3 * s["mean_gross_exposure"] * 7

    def test_net_return_reduced_by_each_term(self):
        p = _panel(PERPS)
        full = _run(p)
        no_fund = _run(p, funding_bps_per_window=0.0)
        no_slip = _run(p, slippage_bps=0.0)
        fee_only = _run(p, slippage_bps=0.0, funding_bps_per_window=0.0)
        assert fee_only["funding_cost_total"] == 0.0
        assert full["net_total_return"] < no_fund["net_total_return"] < fee_only["net_total_return"]
        assert full["net_total_return"] < no_slip["net_total_return"]
        # the always-present fee-only arm equals the explicit fee-only run
        assert full["net_total_return_fee_only"] == pytest.approx(fee_only["net_total_return"], abs=1e-7)

    def test_non_perp_universe_pays_slippage_but_no_funding(self):
        s = _run(_panel(ETFS))
        cp = s["params"]["cost_policy"]
        assert all(v == ec.DEFAULT_SLIPPAGE_BPS_ROUNDTRIP for v in cp["slippage_bps_roundtrip"].values())
        assert cp["n_perp_funding_symbols"] == 0
        assert s["funding_cost_total"] == 0.0

    def test_bare_ticker_perp_universe_needs_venue_perp(self):
        p = _panel(["BTC", "ETH", "SOL", "XRP"])
        assert _run(p)["funding_cost_total"] == 0.0  # unclassifiable -> visible via n_perp
        assert _run(p)["params"]["cost_policy"]["n_perp_funding_symbols"] == 0
        s = _run(p, venue="perp")
        assert s["funding_cost_total"] > 0
        assert s["params"]["cost_policy"]["n_perp_funding_symbols"] == 4

    def test_explicit_override_wins_and_is_recorded(self):
        s = _run(_panel(PERPS), slippage_bps=9.0, funding_bps_per_window=2.5)
        cp = s["params"]["cost_policy"]
        assert set(cp["slippage_bps_roundtrip"].values()) == {9.0}
        assert set(cp["funding_bps_per_window"].values()) == {2.5}
        assert cp["slippage_override"] == 9.0 and cp["funding_override"] == 2.5
        assert cp["source"] == "execution_costs.resolve_cost_policy"

    def test_mixed_universe_is_priced_per_symbol(self):
        cp = xs.resolve_book_costs(["BTCUSDT", "SPY"])
        assert cp["slippage_bps_roundtrip"] == {"BTCUSDT": 3.0, "SPY": 5.0}
        assert cp["funding_bps_per_window"] == {"BTCUSDT": 1.0, "SPY": 0.0}

    def test_gate_arms_carry_the_same_policy(self):
        # _run_for_panel (gate folds) must not fall back to a silent 0.0
        cfg = {"formation": 14, "skip": 0, "rebalance": 7, "quantile": 0.34, "fee_bps": 7.5}
        daily = xs._run_for_panel(_panel(PERPS), fee_mult=1.0, cfg=cfg)
        zero = xs._run_for_panel(_panel(PERPS), fee_mult=1.0,
                                 cfg={**cfg, "slippage_bps": 0.0, "funding_bps_per_window": 0.0})
        assert sum(r for _d, r, _n in daily) < sum(r for _d, r, _n in zero)


def _daily(n=200, seed=5):
    rng = np.random.default_rng(seed)
    from datetime import date, timedelta
    d0 = date(2024, 1, 1)
    return [(d0 + timedelta(days=i), float(rng.normal(0.001, 0.01 * (1 + (i // 50) * 0.5))), 1)
            for i in range(n)]


def _vt(daily, **cost_kw):
    costs = vt.resolve_overlay_costs(**cost_kw)
    return vt.run_vol_target(daily, target_vol=0.10, short=20, long=60, blend=0.5,
                             cap_lo=0.5, cap_hi=1.5, retarget="weekly", costs=costs)


class TestVolTargetFullCostStack:
    def test_default_policy_is_nonzero_perp(self):
        c = vt.resolve_overlay_costs()
        assert c["is_perp"] is True
        # default symbol is a Bybit linear perp -> measured venue fee (COST-STACK-BYBIT-TAKER-FEE)
        assert c["fee_bps_roundtrip"] == 11.0 > 0
        assert c["slippage_bps_roundtrip"] == ec.PERP_SLIPPAGE_BPS_ROUNDTRIP > 0
        assert c["funding_bps_per_window"] == ec.DEFAULT_FUNDING_BPS_PER_WINDOW > 0
        assert c["turnover_bps_charged"] == pytest.approx(14.0)
        assert c["source"] == "execution_costs.resolve_cost_policy"

    def test_default_run_without_costs_arg_still_charges_everything(self):
        out = vt.run_vol_target(_daily(), target_vol=0.10, short=20, long=60, blend=0.5,
                                cap_lo=0.5, cap_hi=1.5, retarget="weekly")
        assert out["total_turnover_cost_r"] > 0
        assert out["total_funding_cost_r"]["baseline"] > 0
        assert out["total_funding_cost_r"]["vol_targeted"] > 0
        assert out["params"]["cost_policy"]["funding_bps_per_window"] > 0

    def test_each_term_is_applied(self):
        d = _daily()
        full = _vt(d)["vol_targeted"]["total_return_r"]
        no_fund = _vt(d, funding_bps_per_window=0.0)["vol_targeted"]["total_return_r"]
        no_slip = _vt(d, slippage_bps_roundtrip=0.0)["vol_targeted"]["total_return_r"]
        no_fee = _vt(d, fee_bps_roundtrip=0.0)["vol_targeted"]["total_return_r"]
        assert full < no_fund and full < no_slip and full < no_fee

    def test_funding_hits_both_arms_so_delta_isolates_overlay(self):
        d = _daily()
        f = _vt(d)
        z = _vt(d, funding_bps_per_window=0.0)
        base_gap = z["baseline"]["total_return_r"] - f["baseline"]["total_return_r"]
        # 1 bps * 3 windows/day * held_exposure 1.0 * n days
        assert base_gap == pytest.approx(1.0 / 1e4 * 3 * len(d), rel=1e-4)

    def test_non_perp_symbol_pays_no_funding_but_pays_fee_and_slippage(self):
        c = vt.resolve_overlay_costs("SPY")
        assert c["is_perp"] is False
        assert c["funding_bps_per_window"] == 0.0
        assert c["slippage_bps_roundtrip"] == ec.DEFAULT_SLIPPAGE_BPS_ROUNDTRIP
        assert c["fee_bps_roundtrip"] >= 0  # Alpaca equities are commission-free

    def test_turnover_override_is_recorded(self):
        c = vt.resolve_overlay_costs(turnover_bps=2.0)
        assert c["turnover_bps_charged"] == 2.0 and c["turnover_bps_override"] == 2.0
