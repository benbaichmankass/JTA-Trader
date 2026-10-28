"""STRATEGY-STATUS-MODEL (operator 2026-10-28): testing / production / inactive, derived from the rosters.

Rule: docs/plans/OPERATING-PLAN-2026-09-21.md § 2 "Three strategy statuses". Guard: scripts/ci/check_strategy_status.py.
These tests pin the status module's account sets to the ones the mandate resolver and the mirror tests use, so the
guard and the promotion machinery cannot disagree about which book is which.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts" / "ops"))
sys.path.insert(0, str(_REPO / "scripts" / "ci"))

import check_strategy_status as guard  # noqa: E402
import mandate_resolver as mr  # noqa: E402
import strategy_status as st  # noqa: E402
from tests import test_paper_portfolio_accounts as mirror_tests  # noqa: E402


def test_account_sets_agree_with_the_resolver_and_the_mirror_tests():
    assert set(st.GENERAL_PAPER) == set(mr.DEMO_FLOOR_ACCOUNTS)
    assert set(st.GENERAL_PAPER) == set(mr.SOAK_ACCOUNT.values())
    assert {a for a, s in mr.STAGE_OF_ACCOUNT.items() if s == "S2"} == set(st.REAL_MONEY_MIRROR)
    assert {k: v for k, v in st.REAL_MONEY_MIRROR.items() if v} == mr.MIRROR_OF
    assert st.MIRROR_CARVE_OUT["alpaca_portfolio"] == mirror_tests._ALPACA_PROXY_STRATEGIES


def test_the_real_tree_holds_the_invariant():
    accounts, strategies = st.load(_REPO)
    assert accounts and strategies
    assert guard.findings(accounts, strategies) == []


def test_no_production_leg_is_on_general_paper():
    t = st.table(_REPO)
    prod = {leg: row["books"] for leg, row in t.items() if row["status"] == st.PRODUCTION}
    assert prod, "no production leg found — the probe must find a positive before a clean read means anything"
    for leg, books in prod.items():
        allowed = {guard.DUAL_BOOK_EXCEPTIONS[leg]} if leg in guard.DUAL_BOOK_EXCEPTIONS else set()
        assert not (set(books) & set(st.GENERAL_PAPER)) - allowed, f"{leg} is production and on general paper: {books}"


def test_status_derivation():
    ros = {"bybit_1": ["t"], "bybit_2": ["p"], "breakout_2": ["q"]}
    strat = {"t": {}, "p": {}, "q": {}, "r": {"enabled": False}}
    assert st.status_of("t", ros, strat) == st.TESTING
    assert st.status_of("p", ros, strat) == st.PRODUCTION
    assert st.status_of("r", ros, strat) == st.INACTIVE
    # prop membership alone does not make a leg production
    assert st.status_of("q", ros, strat) == st.TESTING


def test_guard_self_test_passes():
    assert guard.self_test() == 0


def test_autoland_admits_only_the_move_back_to_general_paper():
    import check_mandate_autoland as al
    removals = {"bybit_2": ["x"], "bybit_portfolio": ["x"]}
    assert al.moved_back(removals, {"bybit_1": ["x"]}) == {"bybit_1": ["x"]}
    assert al.moved_back(removals, {"bybit_1": ["x", "y"]}) == {}      # an unrelated leg rides along: refused
    assert al.moved_back(removals, {"bybit_2": ["x"]}) == {}           # real money is never an admitted add
    assert al.moved_back({"bybit_portfolio": ["x"]}, {"bybit_1": ["x"]}) == {}  # mirror-only cut is not a demotion
