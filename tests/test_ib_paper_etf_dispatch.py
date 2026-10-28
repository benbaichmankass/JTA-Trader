"""IB-PAPER-SILENT-DROP: the symbol->exchange gate must not exclude an IB account
from an equity/ETF that ib_instruments resolves to an IBKR STK contract.

config/instruments.yaml homes SPY/QQQ/IWM/TLT/GLD on alpaca, so before the fix
``_dispatch_exclusion_reason`` dropped ib_paper (exchange interactive_brokers)
for every ETF leg rostered on it, leaving no journal row and no recorded cause.
"""
from __future__ import annotations

import logging
import textwrap
from unittest.mock import patch

import pytest

from src.core.coordinator import Coordinator, OrderPackage

_RISK = "risk: {max_dd_pct: 0.05, daily_usd: 100, pos_size: 500, risk_pct: 0.01, min_balance_usd: 50}"
_YAML = textwrap.dedent(f"""\
    accounts:
      alpaca_paper:
        type: regular
        exchange: alpaca
        api_key_env: IBETF_KEY
        strategies: [spy_trend_long_1d, mes_trend_long_1d]
        {_RISK}
      ib_paper:
        type: regular
        exchange: interactive_brokers
        api_key_env: IBETF_KEY
        strategies: [spy_trend_long_1d, mes_trend_long_1d]
        {_RISK}
""")


@pytest.fixture()
def run(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("IBETF_KEY", "x")
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    p = tmp_path / "accounts.yaml"
    p.write_text(_YAML)

    def _run(strategy: str, symbol: str, price: float):
        caplog.clear()
        pkg = OrderPackage(strategy=strategy, symbol=symbol, direction="long", entry=price, sl=price * 0.99,
                           tp=price * 1.02, confidence=0.5,
                           meta={"strategy_name": strategy, "is_test": True, "test_qty": 1})
        with patch("src.units.accounts.execute.execute_pkg", side_effect=lambda pkg, account_cfg, **kw: "dry"), \
                caplog.at_level(logging.DEBUG, logger="src.core.coordinator"):
            Coordinator().multi_account_execute(pkg, accounts_path=str(p), dry_run=True,
                                                balance_fetcher=lambda _a: 10_000.0)
        drops = {}
        for r in caplog.records:
            m = r.getMessage()
            if m.startswith("dispatch_drop:"):
                drops[m.split("account=", 1)[1].split()[0]] = m
        return drops, pkg
    return _run


def test_etf_leg_reaches_ib_paper_as_well_as_alpaca(run):
    drops, pkg = run("spy_trend_long_1d", "SPY", 700.0)
    assert drops == {}, drops
    assert set(pkg.meta["sized_qty_by_account"]) >= {"ib_paper", "alpaca_paper"}


def test_futures_still_never_reach_a_non_ib_account(run):
    drops, _ = run("mes_trend_long_1d", "MES", 7000.0)
    assert set(drops) == {"alpaca_paper"} and "symbol_exchange_routing" in drops["alpaca_paper"], drops


def test_non_routine_drop_is_stamped_on_the_package(run):
    _, pkg = run("mes_trend_long_1d", "MES", 7000.0)
    assert pkg.meta["dispatch_exclusions_by_account"]["alpaca_paper"].startswith("symbol_exchange_routing")
