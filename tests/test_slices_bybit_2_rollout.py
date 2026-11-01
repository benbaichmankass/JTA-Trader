"""NETTED-SLICES rollout to bybit_2 + bybit_portfolio (Tier-3; operator 2026-11-01 ~09:40Z, popup, verbatim
"Slices on bybit_2 (Rec.)").

Pins three things the rollout depends on:

1. Both books declare ``position_model: slices`` (the mirror carries the live book's value).
2. ``same-symbol-allocation-guard`` treats exactly the YAML-declared accounts as slice-supported.
3. ADOPTION WITHOUT A CLOSE: the slice ledger IS the trade journal, so a position opened on bybit_2 under the old
   pick-one model (one open ``trades`` row per strategy, its own SL/TP legs) is read as that strategy's slice the
   moment the account switches. Nothing is closed, rewritten or migrated; the next package on the symbol is admitted
   or refused per trade against that slice.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from src.runtime.positions import account_uses_slices, admit_slice, open_slices

REPO = Path(__file__).resolve().parents[1]


def _accounts():
    return (yaml.safe_load((REPO / "config/accounts.yaml").read_text(encoding="utf-8")) or {})["accounts"]


def test_bybit_2_and_its_mirror_declare_slices():
    accts = _accounts()
    assert account_uses_slices(accts["bybit_2"])
    assert account_uses_slices(accts["bybit_portfolio"])
    assert accts["bybit_portfolio"].get("position_model") == accts["bybit_2"].get("position_model")


def test_guard_slice_accounts_equal_the_yaml_declarations():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ssa", REPO / "scripts/ci/check_same_symbol_allocation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    declared = {n for n, a in _accounts().items() if account_uses_slices(a)}
    assert set(mod.SLICE_SUPPORT_ACCOUNTS) == declared


def _journal(tmp_path: Path, rows):
    db = tmp_path / "trade_journal.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE trades (id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT, direction TEXT,"
            " entry_price REAL, stop_loss REAL, take_profit_1 REAL, position_size REAL, status TEXT,"
            " is_backtest INTEGER, account_id TEXT, strategy_name TEXT, sl_order_id TEXT, tp_order_id TEXT)")
        for r in rows:
            conn.execute(
                "INSERT INTO trades (timestamp, symbol, direction, entry_price, stop_loss, take_profit_1,"
                " position_size, status, is_backtest, account_id, strategy_name, sl_order_id, tp_order_id)"
                " VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?)", r)
    return str(db)


# A pre-switch bybit_2 position: ada_pullback_2h long 1000 ADA, entry 0.50, SL 0.45, its own legs.
_PRE_SWITCH = ("2026-11-01T00:00:00Z", "ADAUSDT", "long", 0.50, 0.45, 0.60, 1000.0, "open",
               "bybit_2", "ada_pullback_2h", "sl-leg-1", "tp-leg-1")
_CFG = {"account_id": "bybit_2", "exchange": "bybit", "position_model": "slices"}


def _admit(db, *, strategy, direction, venue_net, hedge=False, sized=1000.0):
    side = "Buy" if venue_net > 0 else "Sell"
    return admit_slice(
        account_id="bybit_2", account_cfg=_CFG, strategy=strategy, symbol="ADAUSDT",
        direction=direction, entry=0.50, sl=0.45 if direction == "long" else 0.55,
        meta=None, sized_qty=sized, dry=False,
        slices_reader=lambda a, s: open_slices(a, s, db_path=db),
        positions_reader=lambda cfg: [{"symbol": "ADAUSDT", "side": side, "size": abs(venue_net)}],
        tpsl_mode_fn=lambda: "partial", hedge_fn=lambda a, s: hedge, budget_trades=1.0)


def test_pre_switch_position_is_read_as_its_strategys_slice(tmp_path):
    db = _journal(tmp_path, [_PRE_SWITCH])
    slices = open_slices("bybit_2", "ADAUSDT", db_path=db)
    assert len(slices) == 1
    s = slices[0]
    assert (s["strategy_name"], s["direction"], s["position_size"]) == ("ada_pullback_2h", "long", 1000.0)
    assert (s["sl_order_id"], s["tp_order_id"]) == ("sl-leg-1", "tp-leg-1")


def test_owner_of_the_adopted_slice_keeps_the_same_strategy_guard(tmp_path):
    db = _journal(tmp_path, [_PRE_SWITCH])
    out = _admit(db, strategy="ada_pullback_2h", direction="long", venue_net=1000.0)
    assert out["ok"] and out["own_signed"] == pytest.approx(1000.0)
    assert out["detail"]["admission"] == "own_slice_open"


def test_new_leg_beside_an_adopted_full_risk_slice_is_refused_not_netted(tmp_path):
    # The adopted slice holds the whole 1.0-trade symbol budget at its stop, so ml_entry's same-side slice is
    # refused per trade (re-asked next tick) instead of reading `noop at_target` against the account net.
    db = _journal(tmp_path, [_PRE_SWITCH])
    out = _admit(db, strategy="ml_entry", direction="long", venue_net=1000.0)
    assert not out["ok"] and out["reason"] == "slice_budget_exhausted"


def test_opposite_leg_cannot_shrink_an_adopted_slice_on_a_one_way_book(tmp_path):
    # Under the old model an opposite intent from another leg reduced/flipped the shared net position.
    db = _journal(tmp_path, [_PRE_SWITCH])
    out = _admit(db, strategy="ml_entry", direction="short", venue_net=1000.0)
    assert not out["ok"] and out["reason"] == "opposite_slice_one_way_book"


def test_divergent_ledger_refuses_the_new_slice(tmp_path):
    # venue holds less than the journal says: the adopted book does not reconcile -> refuse, never resize it.
    db = _journal(tmp_path, [_PRE_SWITCH])
    out = _admit(db, strategy="ml_entry", direction="long", venue_net=400.0)
    assert not out["ok"] and out["reason"] == "slice_ledger_divergent"
