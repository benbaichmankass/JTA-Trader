"""PROP-EVAL-COSTS: every portfolio/prop evaluator carries the FULL cost stack
(fee + slippage + funding via execution_costs.resolve_cost_policy), records it, and a
fee-only call FAILS instead of defaulting to zero."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

import scripts.backtest_system as bt
from src.prop.ruleset import load_ruleset
from src.research import run_costs as rc
from src.runtime import execution_costs as ec

_ROOT = Path(__file__).resolve().parents[1]


class _Stop(Exception):
    pass


def _capture(monkeypatch, module):
    """Replace the module's engine entrypoint; record kwargs, then stop the script."""
    seen = {}

    def fake(*a, **kw):
        seen.update(kw)
        raise _Stop

    monkeypatch.setattr(module.bt if hasattr(module, "bt") else module.BS, "run_system_backtest", fake)
    return seen


def _assert_full(seen):
    c = seen["costs"]
    assert seen["require_full_costs"] is True
    assert c["fee_bps_roundtrip"] > 0
    assert c["slippage_bps_roundtrip"] == ec.PERP_SLIPPAGE_BPS_ROUNDTRIP > 0
    assert c["funding_bps_per_window"] == ec.DEFAULT_FUNDING_BPS_PER_WINDOW > 0
    assert c["source"] == "execution_costs.resolve_cost_policy"


# ---- the resolver -------------------------------------------------------------------
class TestResolver:
    def test_default_is_full_stack(self):
        c = rc.resolve_run_costs("BTCUSDT")
        assert (c["fee_bps_roundtrip"], c["slippage_bps_roundtrip"], c["funding_bps_per_window"]) == (
            ec.DEFAULT_FEE_BPS_ROUNDTRIP, 3.0, 1.0)

    def test_zero_stack_is_refused_unless_declared(self):
        with pytest.raises(rc.CostPolicyError):
            rc.resolve_run_costs("BTCUSDT", slippage_bps_roundtrip=0.0, funding_bps_per_window=0.0)
        arm = rc.resolve_run_costs("BTCUSDT", slippage_bps_roundtrip=0.0,
                                   funding_bps_per_window=0.0, allow_fee_only=True)
        assert arm["fee_only_arm_declared"] is True

    def test_prop_declared_costs_win_for_fee_and_funding(self):
        r = load_ruleset(str(_ROOT / "config/prop_rulesets/velotrade_classic_1step.yaml"))
        c = rc.resolve_run_costs("BTCUSDT", ruleset=r)
        assert c["fee_bps_roundtrip"] == 6.0  # 3 bps/side x2
        assert c["funding_bps_per_window"] == pytest.approx(5.0 / 3)  # 5 bps/night over 3 windows
        assert c["slippage_bps_roundtrip"] == 3.0  # firms do not declare slippage
        assert c["term_sources"]["fee"] == "prop_ruleset.costs"

    def test_undeclared_ruleset_falls_back_to_venue_default(self):
        r = load_ruleset(str(_ROOT / "config/prop_rulesets/breakout.yaml"))
        assert rc.resolve_run_costs("BTCUSDT", ruleset=r)["term_sources"]["fee"].startswith("execution_costs")


# ---- the engine wrapper -------------------------------------------------------------
class TestEngineWrapper:
    def test_fee_only_call_fails(self):
        with pytest.raises(rc.CostPolicyError):
            bt.run_system_backtest(None, require_full_costs=True)

    def test_declared_fee_only_arm_refused_when_full_required(self):
        arm = rc.resolve_run_costs("BTCUSDT", slippage_bps_roundtrip=0.0,
                                   funding_bps_per_window=0.0, allow_fee_only=True)
        with pytest.raises(rc.CostPolicyError):
            bt.run_system_backtest(None, costs=arm, require_full_costs=True)

    def test_costs_applied_during_run_recorded_and_globals_restored(self, monkeypatch):
        seen = {}

        def core(base5m, **kw):
            seen.update(slip=bt.SLIPPAGE_BPS_ROUNDTRIP, fund=bt.FUNDING_BPS_PER_WINDOW,
                        fee=bt.FEE_BPS_ROUNDTRIP)
            return {}

        monkeypatch.setattr(bt, "_run_system_backtest_core", core)
        before = (bt.SLIPPAGE_BPS_ROUNDTRIP, bt.FUNDING_BPS_PER_WINDOW, bt.FEE_BPS_ROUNDTRIP)
        out = bt.run_system_backtest(None, costs=rc.resolve_run_costs("BTCUSDT"), require_full_costs=True)
        assert seen == {"slip": 3.0, "fund": 1.0, "fee": ec.DEFAULT_FEE_BPS_ROUNDTRIP}
        assert (bt.SLIPPAGE_BPS_ROUNDTRIP, bt.FUNDING_BPS_PER_WINDOW, bt.FEE_BPS_ROUNDTRIP) == before
        assert out["cost_policy"]["status"] == "resolved" and not out["cost_policy"]["cost_incomplete"]

    def test_legacy_call_is_stamped_cost_incomplete(self, monkeypatch):
        monkeypatch.setattr(bt, "_run_system_backtest_core", lambda b, **kw: {})
        monkeypatch.setattr(bt, "SLIPPAGE_BPS_ROUNDTRIP", 0.0)
        monkeypatch.setattr(bt, "FUNDING_BPS_PER_WINDOW", 0.0)
        out = bt.run_system_backtest(None)
        assert out["cost_policy"]["cost_incomplete"] is True


# ---- one test per script: the non-zero stack reaches the engine ----------------------
def _args(**kw):
    base = dict(fee_bps_roundtrip=None, slippage_bps_roundtrip=None, funding_bps_per_window=None,
                fee_only_arm=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def test_evaluate_prop_applies_full_costs(monkeypatch):
    m = _load("scripts/prop/evaluate_prop.py", "evaluate_prop_t")
    seen = _capture(monkeypatch, m)
    monkeypatch.setattr(m.bt, "_load_candles", lambda p: object())
    args = _args(ruleset=str(_ROOT / "config/prop_rulesets/breakout.yaml"), data="x", start=None,
                 end=None, members="trend_donchian", combos="trend_donchian", initial_balance=5000.0,
                 risk_pct=0.3, daily_loss_pct=3.0, signal_ttl_bars=1, clock_tf="15m",
                 flip_policy="hold", reentry_policy="suppress", refresh_signals=False,
                 out_dir=None, symbol="BTCUSDT")
    m.run(args)
    _assert_full(seen)


def test_evaluate_prop_fee_only_flag_is_refused_by_engine(monkeypatch):
    m = _load("scripts/prop/evaluate_prop.py", "evaluate_prop_t2")
    seen = {}
    real = bt.run_system_backtest

    def spy(b, **kw):
        seen["err"] = None
        try:
            return real(b, **kw)
        except rc.CostPolicyError as e:
            seen["err"] = e
            raise

    monkeypatch.setattr(m.bt, "run_system_backtest", spy)
    monkeypatch.setattr(m.bt, "_load_candles", lambda p: object())
    args = _args(ruleset=str(_ROOT / "config/prop_rulesets/breakout.yaml"), data="x", start=None,
                 end=None, members="trend_donchian", combos="trend_donchian", initial_balance=5000.0,
                 risk_pct=0.3, daily_loss_pct=3.0, signal_ttl_bars=1, clock_tf="15m",
                 flip_policy="hold", reentry_policy="suppress", refresh_signals=False,
                 out_dir=None, symbol="BTCUSDT", fee_only_arm=False,
                 slippage_bps_roundtrip=0.0, funding_bps_per_window=0.0)
    with pytest.raises(rc.CostPolicyError):  # zero stack without the declared arm: refused up front
        m.run(args)


def test_montecarlo_prop_applies_full_costs(monkeypatch):
    m = _load("scripts/prop/montecarlo_prop.py", "montecarlo_prop_t")
    seen = _capture(monkeypatch, m)
    monkeypatch.setattr(m.bt, "_load_candles", lambda p: object())
    args = _args(ruleset=str(_ROOT / "config/prop_rulesets/breakout.yaml"), data="x", start=None,
                 end=None, combos="trend_donchian", initial_balance=5000.0, base_risk_pct=0.5,
                 risk_pct_grid=[0.5], daily_loss_pct=3.0, signal_ttl_bars=1, clock_tf="1h",
                 flip_policy="hold", refresh_signals=False, n_paths=10, block_len=8, horizons=[3.0],
                 seed=1, out_dir=None, symbol="BTCUSDT", cost_aware=False)
    try:
        m.run(args)
    except Exception:  # noqa: BLE001 -- the stubbed engine yields no combos
        pass
    _assert_full(seen)


def test_validate_alt_prop_applies_fee_and_slippage_funding_downstream(monkeypatch):
    m = _load("scripts/prop/validate_alt_prop.py", "validate_alt_prop_t")
    seen = _capture(monkeypatch, m)
    args = argparse.Namespace(symbol="SOLUSDT", strategy="trend_donchian", initial_balance=5000.0,
                              base_risk_pct=0.5, daily_loss_pct=3.0, signal_ttl_bars=1,
                              refresh_signals=False, clock_tf="1h", flip_policy="hold",
                              long_only=False)
    args.costs = rc.resolve_run_costs("SOLUSDT", funding_bps_per_window=0.0)
    with pytest.raises(_Stop):
        m._engine_ledger(object(), "trend_donchian", args, None, None)
    c = seen["costs"]
    assert seen["require_full_costs"] is True and c["fee_bps_roundtrip"] > 0
    assert c["slippage_bps_roundtrip"] > 0  # funding applied downstream by src.prop.funding (no double count)


def test_account_compat_matrix_and_panel_and_walkforwards_pass_costs():
    """Static: the remaining callers pass both keywords (the guard asserts the same repo-wide)."""
    import ast
    for rel in ("scripts/prop/account_compat_matrix.py", "scripts/research/build_backtest_panel.py",
                "scripts/walkforward_flip_policy.py", "scripts/walkforward_netting_guard.py"):
        tree = ast.parse((_ROOT / rel).read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", getattr(n.func, "id", "")) == "run_system_backtest"]
        assert calls, rel
        for n in calls:
            assert {"costs", "require_full_costs"} <= {k.arg for k in n.keywords}, rel


def test_panel_adapter_records_cost_policy():
    src = (_ROOT / "scripts/research/build_backtest_panel.py").read_text()
    assert "resolve_run_costs(symbol)" in src and '"cost_policy": summary.get("cost_policy")' in src


def test_guard_passes_and_self_tests():
    import subprocess
    for a in (["--self-test"], []):
        r = subprocess.run([sys.executable, str(_ROOT / "scripts/ci/check_prop_harness_full_costs.py"), *a],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
