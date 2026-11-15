"""PI-20261009-BKKVRSVQ-0002: the daily-DD switch gets Alpaca's live equity.

Before: only Bybit linear ``totalEquity`` reached ``RiskManager.note_live_equity``,
so armed real-money Alpaca accounts (alpaca_live, alpaca_portfolio) were judged
on the hourly balance snapshot, accepted up to 2 h old.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from src.core.coordinator import _dd_switch_live_equity

REPO = Path(__file__).resolve().parents[1]


def _acc(name="alpaca_live", exchange="alpaca"):
    return SimpleNamespace(name=name, exchange=exchange)


def test_bybit_total_equity_still_wins():
    assert _dd_switch_live_equity(_acc("bybit_2", "bybit"), 1234.5, {"bybit_2": 999.0},
                                  effective_dry=False) == 1234.5


def test_alpaca_feeds_this_rounds_live_equity():
    assert _dd_switch_live_equity(_acc(), None, {"alpaca_live": 5000.0},
                                  effective_dry=False) == 5000.0


def test_oanda_nav_is_fed_too():
    assert _dd_switch_live_equity(_acc("oanda_practice", "oanda"), None,
                                  {"oanda_practice": 100.0}, effective_dry=False) == 100.0


def test_a_failed_live_read_is_could_not_look_not_zero():
    # None in live_balances = the API was asked and failed -> snapshot fallback.
    assert _dd_switch_live_equity(_acc(), None, {"alpaca_live": None},
                                  effective_dry=False) is None
    # Not asked at all (balance_fetcher override / whole-fetch exception).
    assert _dd_switch_live_equity(_acc(), None, {}, effective_dry=False) is None


def test_ib_and_unknown_venues_are_not_fed_a_balance_as_equity():
    for ex in ("interactive_brokers", "ib", "breakout", "", None):
        assert _dd_switch_live_equity(_acc("x", ex), None, {"x": 777.0},
                                      effective_dry=False) is None


def test_effective_dry_accounts_are_not_fed():
    assert _dd_switch_live_equity(_acc(), None, {"alpaca_live": 5000.0},
                                  effective_dry=True) is None


def test_the_dispatch_feeds_the_switch_through_this_helper():
    """The call site, not just the helper: ``note_live_equity`` must receive
    ``_dd_switch_live_equity(...)``. Reverting to ``note_live_equity(total_account_usd)``
    fails here."""
    tree = ast.parse((REPO / "src/core/coordinator.py").read_text(encoding="utf-8"))
    args = [node.args for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "note_live_equity"]
    assert args, "no note_live_equity call found in coordinator.py"
    for a in args:
        assert (len(a) == 1 and isinstance(a[0], ast.Call)
                and getattr(a[0].func, "id", None) == "_dd_switch_live_equity"), ast.dump(a[0])


def test_a_fed_alpaca_equity_is_what_the_switch_reads(monkeypatch):
    """End of the chain: the RiskManager folds the fed live equity, not the
    snapshot (which would be up to 2 h old)."""
    from src.units.accounts import risk as risk_mod

    rm = risk_mod.RiskManager.__new__(risk_mod.RiskManager)
    rm.account_id = "alpaca_live"
    rm._live_equity = None
    monkeypatch.setattr(risk_mod._dd, "snapshot_equity_reading",
                        lambda account_id, **_: (4000.0, "2026-11-12T21:00:00+00:00"))
    assert rm.dd_switch_reading()[0] == 4000.0          # snapshot fallback (old)
    rm.note_live_equity(_dd_switch_live_equity(_acc(), None, {"alpaca_live": 3850.0},
                                               effective_dry=False))
    assert rm.dd_switch_reading() == (3850.0, None)      # this dispatch's live read
    rm.note_live_equity(_dd_switch_live_equity(_acc(), None, {"alpaca_live": None},
                                               effective_dry=False))
    assert rm.dd_switch_reading()[0] == 4000.0          # failed read -> back to snapshot
