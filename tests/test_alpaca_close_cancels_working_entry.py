"""ALPACA-PKG-CLOSE-LEAVES-WORKING-ENTRY-1125: a package close cancels the row's OWN still-working Alpaca entry order.

MEASURED 2026-11-25 (alpaca_options_paper slv_trend_1h row 8569): the close found no position, closed the row, left the
DAY mleg limit entry working, and it filled an hour later as an orphan."""
from __future__ import annotations

import pytest

import src.runtime.order_monitor as om
import src.units.accounts.clients as clients
import src.units.accounts.execute as execute

OID = "f48416cd-0000-4000-8000-000000000001"
CFG = {"account_id": "alpaca_options_paper", "exchange": "alpaca", "mode": "live"}
ROW = {"id": 8569, "account_id": "alpaca_options_paper", "symbol": "SLV", "direction": "long",
       "position_size": 1.0, "broker_order_id": OID}


class _Client:
    def __init__(self, result):
        self.result, self.cancelled = result, []

    def cancel_order_confirmed(self, oid):
        self.cancelled.append(oid)
        return dict(self.result)


@pytest.fixture
def wire(monkeypatch):
    calls = {"close": 0}

    def setup(cancel_result=None, hold="pending", cfg=CFG, close_ok=True):
        client = _Client(cancel_result or {"state": "canceled", "status": "canceled", "filled_qty": 0.0})
        monkeypatch.setattr(om, "_build_account_client", lambda acct: (client, dict(cfg)))
        monkeypatch.setattr(clients, "account_supports_management", lambda c, op: True)
        monkeypatch.setattr(om, "_entry_order_hold", lambda c, oid: hold)
        monkeypatch.setattr(om, "_options_structure_close", lambda m, c: None)

        def _close(*a, **k):
            calls["close"] += 1
            return {"ok": close_ok, "exchange_response": {"result": {"note": "no open position"}},
                    "exchange_order_id": None, "error": None if close_ok else "boom"}
        monkeypatch.setattr(execute, "close_open_position", _close)
        return client
    return setup, calls


def test_working_entry_is_cancelled_and_row_labelled_unfilled(wire):
    setup, calls = wire
    client = setup()
    out = om._send_close_to_exchange(dict(ROW))
    assert client.cancelled == [OID]                       # the row's OWN entry order, nothing else
    assert out["ok"] and out["entry_unfilled"] is True
    assert out["entry_cancel"]["state"] == "canceled" and calls["close"] == 1


def test_partial_fill_cancelled_then_closed_not_labelled_unfilled(wire):
    setup, calls = wire
    setup({"state": "canceled", "status": "canceled", "filled_qty": 3.0})
    out = om._send_close_to_exchange(dict(ROW))
    assert out["ok"] and "entry_unfilled" not in out and calls["close"] == 1   # the close liquidates the partial


def test_entry_filled_first_still_closes(wire):
    setup, calls = wire
    setup({"state": "filled", "status": "filled", "filled_qty": 1.0})
    out = om._send_close_to_exchange(dict(ROW))
    assert out["ok"] and "entry_unfilled" not in out and calls["close"] == 1


def test_unconfirmed_cancel_keeps_the_row_open(wire):
    setup, calls = wire
    setup({"state": "failed", "status": "accepted", "filled_qty": 0.0})
    out = om._send_close_to_exchange(dict(ROW))
    assert out["ok"] is False and "still working" in out["error"] and calls["close"] == 0


@pytest.mark.parametrize("hold", [None, "unreadable"])
def test_not_working_or_unreadable_entry_leaves_the_close_unchanged(wire, hold):
    setup, calls = wire
    client = setup(hold=hold)
    out = om._send_close_to_exchange(dict(ROW))
    assert client.cancelled == [] and "entry_cancel" not in out and out["ok"] and calls["close"] == 1


def test_non_alpaca_account_is_untouched(wire):
    setup, calls = wire
    client = setup(cfg={**CFG, "exchange": "bybit"})
    out = om._send_close_to_exchange(dict(ROW))
    assert client.cancelled == [] and "entry_cancel" not in out and calls["close"] == 1


def test_dry_run_sends_nothing(wire):
    setup, calls = wire
    client = setup(cfg={**CFG, "mode": "dry_run"})
    out = om._send_close_to_exchange(dict(ROW))
    assert out.get("skipped") == "dry_run" and client.cancelled == [] and calls["close"] == 0


def test_journal_writer_maps_entry_unfilled_to_the_label():
    src = open(om.__file__).read()
    assert 'if ex_result.get("entry_unfilled"):' in src
    assert "reason, actual_exit_price = ENTRY_UNFILLED_EXIT_REASON, None" in src
