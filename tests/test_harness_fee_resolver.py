"""COST-STACK-HARNESS-RESOLVER: the Stage-0 harnesses charge the venue fee, not the bare default.

Unset ``--fee-bps-roundtrip`` resolves through ``execution_costs.resolve_fee_bps_roundtrip``
(``profile_loader.roundtrip_fee_bps_for``: bybit:linear 11.0, commission-free 0.0), falls back to
``DEFAULT_FEE_BPS_ROUNDTRIP`` for a venue with no measured fee, and an explicit value (incl. 0.0,
the fee-only arm) always wins. The harness wiring is checked on the AST of each ``main()``: it must
call the resolver with the harness symbol, and its ``--fee-bps-roundtrip`` argparse default must be
``None`` (a non-None default makes every run look explicit and bypasses the resolver)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.runtime import execution_costs as ec

_ROOT = Path(__file__).resolve().parents[1]
HARNESSES = [
    "scripts/backtest_trend.py",
    "scripts/backtest_pullback.py",
    "scripts/backtest_ict_scalp.py",
    "scripts/backtest_squeeze.py",
    "scripts/backtest_fade.py",
    "scripts/backtest_chop_scalp.py",
    "scripts/backtest_fvg_range.py",
    "src/backtest/run_backtest_vwap.py",
]
DEFAULT = ec.DEFAULT_FEE_BPS_ROUNDTRIP


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
def test_bybit_linear_resolves_measured_11(symbol):
    assert ec.resolve_fee_bps_roundtrip(symbol) == 11.0


@pytest.mark.parametrize("symbol", ["MES", "EURUSD", "NOT_A_SYMBOL", "", None])
def test_other_venues_keep_the_default(symbol):
    assert ec.resolve_fee_bps_roundtrip(symbol) == DEFAULT


def test_commission_free_venue_is_zero():
    assert ec.resolve_fee_bps_roundtrip("SPY") == 0.0


@pytest.mark.parametrize("explicit", [0.0, 3.0, DEFAULT])
def test_explicit_wins_including_zero(explicit):
    assert ec.resolve_fee_bps_roundtrip("BTCUSDT", explicit) == explicit


def test_resolver_failure_falls_back_to_default(monkeypatch):
    import src.core.profile_loader as pl

    def boom(_s):
        raise RuntimeError("x")

    monkeypatch.setattr(pl, "roundtrip_fee_bps_for", boom)
    assert ec.resolve_fee_bps_roundtrip("BTCUSDT") == DEFAULT


def _main_fn(tree):
    return next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"
    )


@pytest.mark.parametrize("rel", HARNESSES)
def test_harness_main_routes_fee_through_resolver(rel):
    tree = ast.parse((_ROOT / rel).read_text())
    main = _main_fn(tree)
    calls = [
        n
        for n in ast.walk(main)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", "") == "resolve_fee_bps_roundtrip"
    ]
    assert len(calls) == 1, (
        f"{rel}: main() must call resolve_fee_bps_roundtrip exactly once"
    )
    assert len(calls[0].args) == 2 and "fee_bps_roundtrip" in ast.unparse(
        calls[0].args[1]
    )
    # the argparse default for --fee-bps-roundtrip is None
    defaults = []
    for n in ast.walk(tree):  # the parser may live in a helper beside main()
        if (
            isinstance(n, ast.Call)
            and getattr(n.func, "attr", "") == "add_argument"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "--fee-bps-roundtrip"
        ):
            defaults += [k.value for k in n.keywords if k.arg == "default"]
    assert (
        len(defaults) == 1
        and isinstance(defaults[0], ast.Constant)
        and defaults[0].value is None
    ), rel
