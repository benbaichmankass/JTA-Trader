"""IB-MGC-INACTIVE-1125: physically delivered futures roll opening orders out
of the delivery window; management orders follow the HELD contract.

MEASURED 2026-11-25: every ib_paper ``mgc_trend_1h`` SELL on MGCZ6 (Dec 2026)
came back parent status=Inactive with IBKR Error 201 "You are placing an order
during the contracts delivery window" -- ContFuture still resolved the Dec
contract while IBKR refused opening orders in it.
"""
from __future__ import annotations

import sys
import types
from datetime import date

import pytest

from src.units.accounts import ib_client as ib_client_mod
from src.units.accounts.ib_client import IBClient
from src.units.accounts.ib_instruments import (
    IBInstrumentSpec,
    contract_month_of,
    ib_instrument_spec,
    in_roll_window,
    select_open_month,
)

MGC = IBInstrumentSpec(symbol="MGC", sec_type="FUT", exchange="COMEX",
                       roll_days_before_month=10, active_months=(2, 4, 6, 8, 10, 12))


# ---------------------------------------------------------------------------
# Pure selection rules
# ---------------------------------------------------------------------------

def test_config_declares_roll_for_physical_metals_only():
    assert ib_instrument_spec("MGC").roll_days_before_month == 10
    assert ib_instrument_spec("MGC").active_months == (2, 4, 6, 8, 10, 12)
    assert ib_instrument_spec("MHG").roll_days_before_month == 10
    assert ib_instrument_spec("MHG").active_months == (3, 5, 7, 9, 12)
    # MES is cash-settled: no roll, behaviour unchanged.
    assert ib_instrument_spec("MES").roll_days_before_month is None


def test_dec_contract_is_in_window_on_the_incident_day():
    assert in_roll_window("202612", MGC, date(2026, 11, 25))
    assert not in_roll_window("202612", MGC, date(2026, 11, 20))
    assert not in_roll_window("202702", MGC, date(2026, 11, 25))


def test_select_skips_window_and_inactive_months():
    listed = ["202611", "202612", "202701", "202702", "202704"]
    assert select_open_month(listed, MGC, date(2026, 11, 25)) == "202702"
    assert select_open_month(listed, MGC, date(2026, 11, 1)) == "202612"
    assert select_open_month(["202612"], MGC, date(2026, 11, 25)) is None


def test_no_roll_spec_never_in_window():
    mes = IBInstrumentSpec(symbol="MES", sec_type="FUT", exchange="CME")
    assert not in_roll_window("202612", mes, date(2026, 12, 15))


def test_contract_month_reads_last_trade_date():
    assert contract_month_of("20261229") == "202612"
    assert contract_month_of(types.SimpleNamespace(lastTradeDateOrContractMonth="20270224")) == "202702"
    assert contract_month_of(types.SimpleNamespace()) is None


# ---------------------------------------------------------------------------
# IBClient contract choice
# ---------------------------------------------------------------------------

_CONIDS = {"202612": 751, "202701": 760, "202702": 770, "202704": 780}
_LAST = {"202612": "20261229", "202701": "20270127", "202702": "20270224", "202704": "20270428"}


class _C:
    def __init__(self, **kw):
        self.secType = "FUT"
        self.conId = 0
        self.lastTradeDateOrContractMonth = ""
        self.exchange = ""
        self.symbol = ""
        self.localSymbol = ""
        self.__dict__.update(kw)


class _Detail:
    def __init__(self, month):
        self.contractMonth = month
        self.contract = _C(symbol="MGC", conId=_CONIDS[month], exchange="COMEX",
                           lastTradeDateOrContractMonth=_LAST[month], localSymbol=f"MGC{month}")


class _Pos:
    def __init__(self, contract, position):
        self.contract = contract
        self.position = position
        self.account = "ACCT"


class _IB:
    def __init__(self):
        self.held = []
        self.details_calls = 0
        self.placed = []

    def isConnected(self):
        return True

    def qualifyContracts(self, *cs):
        by_id = {v: k for k, v in _CONIDS.items()}
        for c in cs:
            if not c.conId:  # ContFuture -> the IB front month (still Dec)
                c.conId = _CONIDS["202612"]
            m = by_id.get(c.conId)
            if m:
                c.symbol = "MGC"
                c.lastTradeDateOrContractMonth = _LAST[m]
        return list(cs)

    def reqContractDetails(self, _c):
        self.details_calls += 1
        return [_Detail(m) for m in _CONIDS]

    def positions(self, *_a):
        return list(self.held)


@pytest.fixture
def client(monkeypatch):
    mod = types.ModuleType("ib_insync")
    mod.ContFuture = lambda symbol, exchange, currency=None: _C(symbol=symbol, exchange=exchange)
    mod.Future = lambda **kw: _C(**kw)
    mod.Stock = lambda *a, **k: _C(secType="STK")
    monkeypatch.setitem(sys.modules, "ib_insync", mod)
    ib = _IB()
    c = IBClient(host="127.0.0.1", port=4002, client_id=1, account="ACCT")
    monkeypatch.setattr(c, "connect", lambda: ib)
    return c, ib


def _today(monkeypatch, d):
    monkeypatch.setattr(ib_client_mod, "_utc_today", lambda: d)


def test_open_rolls_to_next_active_month_inside_window(client, monkeypatch):
    c, ib = client
    _today(monkeypatch, date(2026, 11, 25))
    assert contract_month_of(c._build_open_contract("MGC")) == "202702"


def test_open_keeps_front_month_outside_window(client, monkeypatch):
    c, ib = client
    _today(monkeypatch, date(2026, 11, 10))
    assert contract_month_of(c._build_open_contract("MGC")) == "202612"
    assert ib.details_calls == 0


def test_management_follows_held_contract_even_in_window(client, monkeypatch):
    c, ib = client
    _today(monkeypatch, date(2026, 11, 25))
    held = _C(symbol="MGC", conId=751, exchange="COMEX", lastTradeDateOrContractMonth="20261229")
    ib.held = [_Pos(held, -3)]
    # A close / protective re-arm must target the Dec position it holds...
    assert c._build_contract("MGC") is held
    # ...while a NEW opening order still goes to Feb.
    assert contract_month_of(c._build_open_contract("MGC")) == "202702"


def test_management_after_roll_targets_held_feb_not_front(client, monkeypatch):
    c, ib = client
    _today(monkeypatch, date(2026, 11, 25))
    held = _C(symbol="MGC", conId=770, exchange="COMEX", lastTradeDateOrContractMonth="20270224")
    ib.held = [_Pos(held, 2)]
    assert c._build_contract("MGC") is held
    assert c._build_open_contract("MGC") is held


def test_flat_management_uses_the_opening_contract(client, monkeypatch):
    c, ib = client
    _today(monkeypatch, date(2026, 11, 25))
    assert contract_month_of(c._build_contract("MGC")) == "202702"


def test_lookup_failure_falls_back_to_front(client, monkeypatch):
    c, ib = client
    _today(monkeypatch, date(2026, 11, 25))

    def _boom(_c):
        raise RuntimeError("gateway down")

    ib.reqContractDetails = _boom
    assert contract_month_of(c._build_open_contract("MGC")) == "202612"
