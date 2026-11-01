"""A close the venue attributes to the trade's own SL/TP order is booked as that leg.

CLOSE-REASON-XRP-1220: bybit_1 trade 6817 was stopped out by the venue at 12:16:49Z and
finalised 12:20:15Z as ``reconciler_filled`` with a NULL exit price, because the demo
closed-pnl path reads an hourly-filled local store. The venue's own order history already
named the filled leg; `_own_bracket_fill_from_venue` reads it once, at finalisation.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from src.runtime import order_monitor as om


class _FakeDB:
    def __init__(self):
        self.updates = {}

    def update_trade(self, trade_id, updates):
        self.updates[int(trade_id)] = dict(updates)
        return 1


def _row(**over):
    row = {
        "id": 6817, "symbol": "XRPUSDT", "direction": "long",
        "position_size": 74160.0, "entry_price": 1.2582,
        "created_at": "2026-11-01T10:20:42.268899+00:00",
        "setup_type": "ict_scalp_xrp_15m",
        "sl_order_id": "e043d46b-a20f-4164-a1cd-82dbae91f2c4",
        "tp_order_id": "9826d97e-94f6-4080-833a-0086d84d2106",
        "notes": json.dumps({"trade_id": "x", "is_dry": False}),
    }
    row.update(over)
    return row


SL_FILLED = {"order_id": "e043d46b-a20f-4164-a1cd-82dbae91f2c4", "status": "Filled",
             "filled_qty": 74160.0, "avg_price": 1.2476, "exec_time": "1793535409544"}
TP_DEACTIVATED = {"order_id": "9826d97e-94f6-4080-833a-0086d84d2106",
                  "status": "Deactivated", "filled_qty": 0.0, "avg_price": 0.0,
                  "exec_time": "1793535409544"}


def _by_id(m):
    return lambda cfg, oid: m.get(oid)


def _close(row, statuses, *, cfg=None):
    db = _FakeDB()
    with patch("src.units.accounts.clients.account_closed_pnl_for_trade",
               return_value=None), \
         patch("src.units.accounts.clients.account_order_status",
               side_effect=_by_id(statuses)), \
         patch.object(om, "_cascade_close_linked_package") as casc, \
         patch.object(om, "_cancel_closed_row_protection"), \
         patch("src.units.accounts.clients.account_exec_type_for_close",
               return_value=None):
        reason, _ = om._close_trade_from_order_status(
            db, row, {"avg_price": 1.2582, "exec_time": "1793528442001"},
            cfg=cfg or {"account_id": "bybit_1", "exchange": "bybit"},
        )
    return reason, db.updates[int(row["id"])], casc


def test_filled_sl_leg_is_booked_as_sl_with_the_venue_price_and_time():
    reason, upd, casc = _close(_row(), {
        SL_FILLED["order_id"]: SL_FILLED, TP_DEACTIVATED["order_id"]: TP_DEACTIVATED})
    assert reason == "sl"
    assert upd["exit_reason"] == "sl"
    assert upd["exit_price"] == 1.2476
    assert upd["closed_at"].startswith("2026-11-01T12:16:49")
    assert "pnl" not in upd, "PnL is the local-compute sweep's job, never invented here"
    notes = json.loads(upd["notes"])
    assert notes["exit_price_source"] == "exchange_fill"
    assert notes["exit_reason_source"] == "venue_bracket_order"
    assert casc.call_args.kwargs["close_reason"] == "sl", "the package gets the true reason too"


def test_filled_tp_leg_is_booked_as_tp():
    tp = dict(TP_DEACTIVATED, status="Filled", filled_qty=74160.0, avg_price=1.2754)
    sl = dict(SL_FILLED, status="Deactivated", filled_qty=0.0, avg_price=0.0)
    reason, upd, _ = _close(_row(), {sl["order_id"]: sl, tp["order_id"]: tp})
    assert reason == "tp" and upd["exit_price"] == 1.2754


def test_no_filled_leg_keeps_the_generic_fallback():
    gone = {"order_id": "x", "status": "not_found", "filled_qty": 0.0,
            "avg_price": 0.0, "exec_time": None}
    reason, upd, _ = _close(_row(), {SL_FILLED["order_id"]: gone,
                                     TP_DEACTIVATED["order_id"]: gone})
    assert reason == "reconciler_filled"
    assert "exit_price" not in upd


def test_a_read_failure_is_not_an_sl():
    reason, upd, _ = _close(_row(), {})  # account_order_status -> None for both
    assert reason == "reconciler_filled" and "exit_price" not in upd


def test_qty_mismatch_is_refused():
    part = dict(SL_FILLED, filled_qty=30000.0)
    reason, _, _ = _close(_row(), {SL_FILLED["order_id"]: part,
                                   TP_DEACTIVATED["order_id"]: TP_DEACTIVATED})
    assert reason == "reconciler_filled"


def test_reduce_leg_is_never_classified_from_its_legs():
    reason, _, _ = _close(_row(setup_type="intent_reduce"), {
        SL_FILLED["order_id"]: SL_FILLED})
    assert reason == "reconciler_filled"


def test_no_cfg_means_no_venue_read():
    assert om._own_bracket_fill_from_venue(None, _row()) is None
