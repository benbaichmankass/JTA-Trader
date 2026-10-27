"""DESK-PAPER-ACCOUNTS: the claude_desk leg on alpaca_paper and ib_paper as well as bybit_1.

Operator, verbatim (chat 2026-10-27 ~15:58Z): "I do want to have the desk live on the other paper accounts as well,
so Alpaca and IB."

Pins, against the REAL config where it matters:
  1. one leg, three venues: ``account_symbols`` scopes each rostering account (``symbol_sets.leg_symbols``), and the
     tick / data readers resolve each account to its own slice only;
  2. routing: ``Coordinator.multi_account_execute`` drops a desk package on every account whose slice does not hold
     the symbol (``leg_account_scope``) -- a SPY desk order can never reach bybit_1, a BTCUSDT one never alpaca_paper;
  3. coexistence on a non-slice account: ``claude_desk.exclusive_hold_refusal`` (refused, journalled, both directions);
  4. market hours: an ETF / CME micro proposal waits while its market is closed (builder), is refused by desk_write
     when closed at the cutoff, and the scan packet says so per row;
  5. paper only: every account rostering the leg is a paper account and the intake demo floor stays closed the
     moment a real-money account rosters it.
"""
from __future__ import annotations

import logging
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))

from src.config.symbol_sets import UNION, leg_symbols, resolve_symbols  # noqa: E402
from src.core.coordinator import Coordinator, OrderPackage  # noqa: E402
from src.runtime.market_hours import asset_class_for_symbol, is_market_open  # noqa: E402
from src.units.strategies import claude_desk as cd  # noqa: E402

STRATS = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]
ACCTS = yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]
DESK = STRATS["claude_desk"]
CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT"]
ETFS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
MICROS = ["MES", "MGC", "MHG"]


# ----------------------------------------------------------------------------- 1. the scope (real config)

def test_each_rostering_account_resolves_to_its_own_venue_slice():
    assert leg_symbols(DESK, "bybit_1") == CRYPTO
    assert leg_symbols(DESK, "alpaca_paper") == ETFS
    assert leg_symbols(DESK, "ib_paper") == MICROS
    assert leg_symbols(DESK) == CRYPTO + ETFS + MICROS  # no account: the union the builder evaluates
    for acct, syms in (("bybit_1", CRYPTO), ("alpaca_paper", ETFS), ("ib_paper", MICROS)):
        got = resolve_symbols(declared=ACCTS[acct]["symbols"], roster=ACCTS[acct]["strategies"], mode=UNION,
                              strategies_cfg=STRATS, account_id=acct)
        assert set(syms) <= set(got)
        others = set(CRYPTO + ETFS + MICROS) - set(syms) - set(ACCTS[acct]["symbols"])
        assert not others & set(got), f"{acct} would pull another venue's desk symbols: {others & set(got)}"


def test_each_venue_slice_is_on_that_venue_and_pulled_there():
    from src.core.coordinator import _instrument_exchange_for
    for acct, syms in (("bybit_1", CRYPTO), ("alpaca_paper", ETFS), ("ib_paper", MICROS)):
        assert all(_instrument_exchange_for(s) == ACCTS[acct]["exchange"] for s in syms), acct
        assert set(syms) <= set(ACCTS[acct]["symbols"]), f"{acct} pull list"


# ----------------------------------------------------------------------------- 5. paper only

def test_rostered_on_paper_accounts_only_and_never_on_a_real_money_or_mirror_book():
    on = sorted(a for a, v in ACCTS.items() if "claude_desk" in (v.get("strategies") or []))
    assert on == ["alpaca_paper", "bybit_1", "ib_paper"]
    for a in on:
        assert ACCTS[a]["account_class"] == "paper" and ACCTS[a].get("paper_role") != "portfolio"
    assert "claude_desk" not in (ACCTS["alpaca_live"].get("strategies") or [])
    assert "claude_desk" not in (ACCTS["alpaca_portfolio"].get("strategies") or [])


def test_intake_floor_open_for_the_three_and_closed_by_one_real_money_roster():
    import desk_intake as di
    mandates = yaml.safe_load((REPO / "config/mandates.yaml").read_text())
    accounts = yaml.safe_load((REPO / "config/accounts.yaml").read_text())
    assert di.entry_gate(mandates, accounts) is None
    accounts["accounts"]["alpaca_live"]["strategies"] = list(accounts["accounts"]["alpaca_live"]["strategies"]) + [
        "claude_desk"]
    assert "not_a_demo_account:alpaca_live" in di.entry_gate(mandates, accounts)
    leg = di._leg_symbols()
    assert set(ETFS + MICROS) <= set(leg)  # an accepted SPY / MES proposal is queued, not symbol_not_in_desk_leg


# ----------------------------------------------------------------------------- 2. routing (coordinator)

_ACCOUNTS_YAML = textwrap.dedent("""\
    accounts:
      bybit_1:
        type: regular
        exchange: bybit
        api_key_env: DESK_TEST_KEY
        strategies: [claude_desk]
        risk: {max_dd_pct: 0.05, daily_usd: 100, pos_size: 500, risk_pct: 0.01, min_balance_usd: 50}
      alpaca_paper:
        type: regular
        exchange: alpaca
        api_key_env: DESK_TEST_KEY
        strategies: [claude_desk]
        risk: {max_dd_pct: 0.05, daily_usd: 100, pos_size: 500, risk_pct: 0.01, min_balance_usd: 50}
      ib_paper:
        type: regular
        exchange: interactive_brokers
        api_key_env: DESK_TEST_KEY
        strategies: [claude_desk]
        risk: {max_dd_pct: 0.05, daily_usd: 100, pos_size: 500, risk_pct: 0.01, min_balance_usd: 50}
""")


@pytest.fixture()
def routed(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DESK_TEST_KEY", "x")
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    p = tmp_path / "accounts.yaml"
    p.write_text(_ACCOUNTS_YAML)

    def run(symbol: str, price: float) -> dict:
        caplog.clear()
        pkg = OrderPackage(strategy="claude_desk", symbol=symbol, direction="long", entry=price, sl=price * 0.99,
                           tp=price * 1.02, confidence=0.5,
                           meta={"strategy_name": "claude_desk", "is_test": True, "test_qty": 1})
        with patch("src.units.accounts.execute.execute_pkg", side_effect=lambda pkg, account_cfg, **kw: "dry"), \
                caplog.at_level(logging.DEBUG, logger="src.core.coordinator"):
            Coordinator().multi_account_execute(pkg, accounts_path=str(p), dry_run=True,
                                                balance_fetcher=lambda _a: 10_000.0)
        drops = {}
        for r in caplog.records:
            m = r.getMessage()
            if m.startswith("dispatch_drop:"):  # leg_account_scope, or symbol_exchange_routing where IB is involved
                drops[m.split("account=", 1)[1].split()[0]] = m
        return drops
    return run


@pytest.mark.parametrize("symbol,price,home", [("SPY", 700.0, "alpaca_paper"), ("BTCUSDT", 80000.0, "bybit_1"),
                                               ("MES", 7000.0, "ib_paper"), ("GLD", 370.0, "alpaca_paper")])
def test_a_desk_package_reaches_only_its_own_venues_account(routed, symbol, price, home):
    drops = routed(symbol, price)
    assert sorted(drops) == sorted({"bybit_1", "alpaca_paper", "ib_paper"} - {home}), drops
    # the new scope is what separates bybit <-> alpaca (the older routing rule only separates IB)
    for a in {"bybit_1", "alpaca_paper"} - {home}:
        if home != "ib_paper":
            assert "reason=leg_account_scope" in drops[a], drops[a]


# ----------------------------------------------------------------------------- 3. coexistence (pure + wired)

def test_exclusive_hold_refusal_both_directions_and_unreadable_fails_closed():
    assert cd.exclusive_hold_refusal("claude_desk", 0.0, None) is None
    assert cd.exclusive_hold_refusal("claude_desk", 3.0, None).startswith(cd.R_DESK_HELD)
    assert cd.exclusive_hold_refusal("claude_desk", -1, None).startswith(cd.R_DESK_HELD)
    assert cd.exclusive_hold_refusal("spy_trend_long_1d", 5.0, False) is None
    assert cd.exclusive_hold_refusal("spy_trend_long_1d", 0.0, True) == cd.R_HELD_BY_DESK
    assert cd.exclusive_hold_refusal("spy_trend_long_1d", 0.0, None) == f"{cd.R_HELD_BY_DESK}:unreadable"


def test_the_coordinator_journals_the_refusal_only_on_non_slice_desk_books():
    src = (REPO / "src/core/coordinator.py").read_text()
    i = src.index("_cd.exclusive_hold_refusal(")
    block = src[src.rindex("if not _slice_mode and _cd.NAME in", 0, i):i + 1500]
    assert "log_rejection_to_journal(" in block and "continue" in block


# ----------------------------------------------------------------------------- 4. market hours

def test_asset_class_and_sessions():
    assert [asset_class_for_symbol(s) for s in ("SPY", "MES", "BTCUSDT")] == ["us_equity", "cme_futures", "crypto"]
    tue_open = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)      # 11:00 ET
    tue_break = datetime(2026, 10, 27, 21, 30, tzinfo=timezone.utc)    # 17:30 ET: CME daily break
    sat = datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)
    assert is_market_open("us_equity", tue_open) and is_market_open("cme_futures", tue_open)
    assert not is_market_open("us_equity", tue_break) and not is_market_open("cme_futures", tue_break)
    assert not is_market_open("cme_futures", sat) and is_market_open("crypto", sat)


def _accepted(symbol: str, price: float, at: datetime) -> dict:
    return {"at": at.isoformat(), "decision_id": f"DD-x-{symbol}", "intent_id": "DI-x", "packet_id": "DP-x",
            "proposal": {"symbol": symbol, "side": "long", "timeframe": "1h", "horizon_bars": 4, "max_hold_min": 45,
                         "entry": {"type": "market", "level": price, "good_till_bars": 2},
                         "stop": {"level": price * 0.99, "basis": "atr_multiple"},
                         "tp": {"level": price * 1.01, "basis": "swing_level", "p_hit": 0.4}}}


@pytest.mark.parametrize("now,want", [(datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc), "buy"),
                                      (datetime(2026, 10, 27, 21, 30, tzinfo=timezone.utc), "none")])
def test_builder_waits_while_the_etf_market_is_closed(tmp_path, now, want):
    from src.runtime import strategy_signal_builders as ssb
    row = _accepted("SPY", 700.0, now)

    class _DB:
        def __init__(self, **kw):
            pass

        def get_order_packages_by_strategy(self, name):
            return []

    class _Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    with patch.object(cd, "read_queue", return_value=[row]), \
            patch("src.units.db.database.Database", _DB), patch("datetime.datetime", _Now), \
            patch.object(cd, "record", return_value=0):
        sig = ssb.claude_desk_signal_builder({"SYMBOL": "SPY"})
    assert sig.get("side") == want, sig.get("meta")
    if want == "none":
        assert sig["meta"]["reason"] == "market_closed:us_equity"


# desk_write's closed-market refusal: tests/test_desk_wake_write.py::test_a_proposal_on_a_closed_market_is_refused...


def test_scan_packet_rows_carry_the_market_state_and_route_venue():
    import desk_scan_packet as dsp
    tue_break = datetime(2026, 10, 27, 21, 30, tzinfo=timezone.utc)
    assert dsp.market_state("SPY", tue_break) == {"asset_class": "us_equity", "open": False}
    assert dsp.market_state("BTCUSDT", tue_break) == {"asset_class": "crypto", "open": True}
    accounts = yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]
    uni = {u["symbol"]: u for u in dsp.pulled_universe(accounts, STRATS)}
    assert uni["SPY"]["venue"] == "alpaca" and uni["MES"]["venue"] == "interactive_brokers"
    assert uni["BTCUSDT"]["venue"] == "bybit"
