"""SIZED-QTY-META-MISMATCH (row PKG-SIZED-QTY-2X-PLACED-BYBIT1, 2026-11-12).

MEASURED on the live journal: 27 bybit_1 order packages carried
``meta.sized_qty_by_account`` exactly 2x the placed (journal + venue) qty, e.g.
pkg-ea7ad25c89394394 sized 232931.526 while ``slice_admission.qty`` and the
venue fill were 116465.763. Cause: ``sized_qty_by_account`` is stamped with the
RiskManager size BEFORE ``positions.admit_slice`` resizes it; bybit_1 declares
``claude_desk`` / ``e4_oi_shock_1h`` slices of 0.5 (config/slice_allocation.yaml),
so the order is half the stamped figure. Bookkeeping only: the order itself was
right.

The fix keeps ``sized_qty_by_account`` (RiskManager size) and adds
``placed_qty_by_account`` (the qty handed to execute_pkg) plus a per-account
``slice_admission_by_account`` (the single ``slice_admission`` key is
overwritten by the last slice account in the loop).
"""
from __future__ import annotations

import textwrap

import pytest

from tests.test_intent_delta_dispatch import _patch_dispatch_deps
from tests.test_slice_coordinator_dispatch import (  # noqa: F401 (pytest fixtures)
    SLICE_ACCOUNTS,
    _pkg,
    _run,
    _seed,
    coord,
    slice_yaml,
    trade_db,
    venue,
)


def test_weighted_slice_places_less_than_sized_and_meta_says_so(
        coord, slice_yaml, trade_db, venue, monkeypatch):  # noqa: F811 (pytest fixture params)
    captured = []
    _patch_dispatch_deps(monkeypatch, captured)
    pkg = _pkg("trend_donchian_eth_4h", weight=0.5,
               contenders=["trend_donchian_eth_4h", "trend_donchian_eth_prop"])
    res = _run(coord, slice_yaml, pkg)
    assert res[0]["error"] is None, res
    placed = captured[0]["qty_override"]
    # The reproduction: the RiskManager size (0.2) is 2x what went out (0.1).
    assert pkg.meta["sized_qty_by_account"]["bybit_2"] == pytest.approx(0.2, abs=1e-3)
    assert placed == pytest.approx(0.1, abs=1e-3)
    # The fix: the placed figure is on the package, per account.
    assert pkg.meta["placed_qty_by_account"]["bybit_2"] == pytest.approx(placed)
    assert pkg.meta["slice_admission_by_account"]["bybit_2"]["qty"] == pytest.approx(placed)


def test_refused_slice_records_no_placed_qty(coord, slice_yaml, trade_db, venue, monkeypatch):  # noqa: F811 (pytest fixture params)
    captured = []
    _patch_dispatch_deps(monkeypatch, captured)
    _seed(trade_db, "trend_donchian_eth_4h", 0.2, sl=49_500.0)  # budget fully at risk
    venue["net"] = 0.2
    pkg = _pkg("trend_donchian_eth_prop")
    res = _run(coord, slice_yaml, pkg)
    assert captured == [] and res[0]["error"] == "slice_budget_exhausted"
    assert "bybit_2" not in pkg.meta["placed_qty_by_account"]
    assert pkg.meta["slice_admission_by_account"]["bybit_2"]["ok"] is False


def test_dry_account_records_no_placed_qty(coord, tmp_path, trade_db, venue, monkeypatch):  # noqa: F811 (pytest fixture params)
    captured = []
    _patch_dispatch_deps(monkeypatch, captured)
    p = tmp_path / "dry.yaml"
    p.write_text(SLICE_ACCOUNTS.replace("mode: live", "mode: dry_run"))
    pkg = _pkg("trend_donchian_eth_4h")
    coord.multi_account_execute(pkg, accounts_path=str(p),
                                balance_fetcher=lambda a: 10_000.0)
    assert pkg.meta["placed_qty_by_account"] == {}


def test_two_slice_accounts_each_keep_their_admission(coord, tmp_path, trade_db, venue, monkeypatch):  # noqa: F811 (pytest fixture params)
    captured = []
    _patch_dispatch_deps(monkeypatch, captured)
    monkeypatch.setenv("BYBIT_API_KEY_9", "k")
    monkeypatch.setenv("BYBIT_API_SECRET_9", "s")
    second = textwrap.indent(
        SLICE_ACCOUNTS.split("accounts:\n", 1)[1]
        .replace("bybit_2:", "bybit_9:").replace("BYBIT_API_KEY_2", "BYBIT_API_KEY_9")
        .replace("risk_pct: 0.01", "risk_pct: 0.02"),
        "",
    )
    p = tmp_path / "two.yaml"
    p.write_text(SLICE_ACCOUNTS + second)
    pkg = _pkg("trend_donchian_eth_4h")
    coord.multi_account_execute(pkg, accounts_path=str(p),
                                balance_fetcher=lambda a: 10_000.0)
    by_acct = pkg.meta["slice_admission_by_account"]
    assert set(by_acct) == {"bybit_2", "bybit_9"}
    assert by_acct["bybit_2"]["qty"] != by_acct["bybit_9"]["qty"]
    assert set(pkg.meta["placed_qty_by_account"]) == {"bybit_2", "bybit_9"}
