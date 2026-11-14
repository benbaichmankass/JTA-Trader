"""ORDER-PATH-RESIDUE-2: a strategy-verdict partial close amends the row's OWN
tracked legs down to the remainder (never cancels them, never touches a sibling).

BL-20260825-CLOSE-SIDE-LEG-CANCEL-IS-WIRED-AT-1-OF-10-CALL-SITES dispositioned
``order_monitor._send_partial_close_to_exchange`` as "needs an AMEND, not a
cancel": the position stays open, so cancelling strips its protection and
leaving the legs over-covers it. The desk reduce and the intent-reduce
allocator already call ``execute.resize_tracked_protective_legs``; this pins
the third partial path (``_apply_partial_close``, e.g. turtle_soup's TP1).
"""
from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("pandas", MagicMock())
sys.modules.setdefault("src.runtime.signal_notifications", MagicMock())
sys.modules.setdefault("src.runtime.signal_writer", MagicMock())

from src.runtime import order_monitor as _om  # noqa: E402
from src.units.accounts import execute as _ex  # noqa: E402

_SENTINEL = object()


class _DB:
    def __init__(self, row: dict[str, Any]):
        self.row = row
        self.events: list[str] = []
        self.trade_updates: list[tuple] = []

    def get_trades(self, filters=None, limit=None):
        f = filters or {}
        if "id" in f and int(f["id"]) != self.row["id"]:
            return []
        if "status" in f and f["status"] != self.row.get("status", "open"):
            return []
        return [dict(self.row)]

    def update_trade(self, trade_id, updates):
        self.events.append("trade_write")
        self.trade_updates.append((trade_id, updates))
        for k, v in updates.items():
            self.row[k] = v

    def update_order_package(self, pkg_id, updates):
        self.events.append("pkg_write")

    def get_order_packages_by_strategy(self, *a, **k):
        return []


def _row(**over):
    row = {
        "id": 77, "account_id": "bybit_1", "symbol": "ETHUSDT",
        "direction": "long", "position_size": 2.0, "status": "open",
        "strategy_name": "turtle_soup", "order_package_id": "pkg-77",
        "is_backtest": 0, "notes": json.dumps({}),
        "sl_order_id": "SL-OWN", "tp_order_id": "TP-OWN",
    }
    row.update(over)
    return row


def _pkg():
    return {"order_package_id": "pkg-77", "strategy_name": "turtle_soup",
            "symbol": "ETHUSDT", "linked_trade_id": 77}


@pytest.fixture
def wire(monkeypatch):
    calls: list[dict[str, Any]] = []
    state = {"send": {"ok": True, "exchange_order_id": "X1", "error": None},
             "raise": False, "db": None}

    monkeypatch.setattr(_om, "_send_partial_close_to_exchange",
                        lambda t, q: dict(state["send"]))
    monkeypatch.setattr(_om, "_send_close_to_exchange",
                        lambda t: {"ok": True, "exchange_order_id": "XF", "error": None})
    monkeypatch.setattr(_om, "_capture_fill_details", lambda t, oid: None)
    monkeypatch.setattr(_om, "_build_account_client",
                        lambda aid: ("CLIENT", {"exchange": "bybit", "account_id": aid}))

    def _resize(client, cfg, *, symbol, new_qty, sl_order_id=_SENTINEL,
                tp_order_id=_SENTINEL, trade_id=_SENTINEL):
        if state["db"] is not None:
            state["db"].events.append("resize")
        if state["raise"]:
            raise RuntimeError("venue down")
        calls.append({"client": client, "symbol": symbol, "new_qty": new_qty,
                      "sl": sl_order_id, "tp": tp_order_id, "trade_id": trade_id})
        return {"sl": {"state": "resized"}, "tp": {"state": "resized"}}

    monkeypatch.setattr(_ex, "resize_tracked_protective_legs", _resize)
    return calls, state


def _run(db, pct):
    s = _om._StrategyTickSummary()
    _om._apply_update(db, _pkg(), {"action": "close", "close_qty_pct": pct,
                                   "reason": "tp1_partial"}, s)
    return s


def test_partial_close_amends_own_legs_to_remainder(wire):
    calls, state = wire
    db = _DB(_row())
    state["db"] = db
    s = _run(db, 0.5)
    assert s.error_count == 0 and s.updated_count == 1
    assert len(calls) == 1
    c = calls[0]
    assert c["client"] == "CLIENT"
    assert c["symbol"] == "ETHUSDT"
    assert abs(c["new_qty"] - 1.0) < 1e-9
    assert (c["sl"], c["tp"], c["trade_id"]) == ("SL-OWN", "TP-OWN", 77)
    # The journal write lands first; the venue amend runs after it.
    assert db.events.index("trade_write") < db.events.index("resize")


def test_dry_run_short_circuit_amends_nothing(wire):
    calls, state = wire
    state["send"] = {"ok": True, "skipped": "dry_run", "exchange_order_id": None,
                     "error": None}
    db = _DB(_row())
    _run(db, 0.5)
    assert calls == []
    assert abs(db.row["position_size"] - 1.0) < 1e-9  # journal partial still booked


def test_row_without_tracked_legs_amends_nothing(wire):
    calls, _ = wire
    db = _DB(_row(sl_order_id=None, tp_order_id=None))
    _run(db, 0.5)
    assert calls == []


def test_cumulative_full_close_does_not_resize(wire):
    calls, _ = wire
    db = _DB(_row(notes=json.dumps({"partial_closes": [{"qty": 0.5}],
                                    "original_position_size": 2.0}),
                  position_size=1.0))
    _run(db, 0.5)
    assert calls == []


def test_failed_venue_reduce_amends_nothing(wire):
    calls, state = wire
    state["send"] = {"ok": False, "error": "venue refused", "exchange_order_id": None}
    db = _DB(_row())
    s = _run(db, 0.5)
    assert calls == [] and db.trade_updates == [] and s.error_count == 1


def test_resize_exception_never_unbooks_the_partial(wire):
    _calls, state = wire
    state["raise"] = True
    db = _DB(_row())
    s = _run(db, 0.5)
    assert s.error_count == 0 and s.updated_count == 1
    assert abs(db.row["position_size"] - 1.0) < 1e-9
