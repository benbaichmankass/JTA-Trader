"""account_reachable_set: the reachable set is DERIVED through the live sizer, never a recorded constant (row SMALL-ACCOUNT-RISK)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "account_reachable_set.py"
_spec = importlib.util.spec_from_file_location("account_reachable_set", _P)
ars = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ars)


def test_self_test_passes():
    assert ars._self_test() == 0


def test_no_data_is_not_zero_and_unreadable_when_nothing_reads():
    accounts = {"a": {"exchange": "alpaca", "strategies": ["L"], "risk": {"risk_pct": 0.02}}}
    strategies = {"L": {"symbols": ["X"], "timeframe": "1h"}}
    res = ars.run("a", balance={"equity": 100.0, "buying_power": 100.0}, candles=lambda s, tf: [],
                  accounts=accounts, strategies=strategies)
    assert res["read_state"] == "unreadable"
    assert res["rows"][0]["notional_usd"] is None
    assert res["reachable"] == []


def test_what_if_cap_floors_to_whole_shares():
    rows = [{"leg": "L", "symbol": "A", "qty": 3.0, "entry": 30.0}, {"leg": "L", "symbol": "B", "qty": 1.0, "entry": 80.0}]
    wi = {w["cap_pct_equity"]: w for w in ars.what_if(rows, 100.0, caps=(0.5,))}
    assert wi[0.5]["still_sized"] == 1 and wi[0.5]["trimmed"] == 1 and wi[0.5]["lost"] == 1
