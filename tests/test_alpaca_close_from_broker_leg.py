"""ALPACA-CLOSE-BROKER-TRUTH: an Alpaca close a flat detector noticed takes the
broker's own filled bracket leg -- reason, price and time -- not an inference.

Shape from alpaca_paper trade 7011 (IWM long, 2275 sh): the stop leg filled
2026-11-10T14:33:31Z at 279.450338 (Alpaca /v2/orders/{id}?nested=true, read
2026-11-12), and the position-snapshot reconciler closed the row at 14:36:00Z
as `exchange_flat_reconciled`. Times below are offsets from now so the 14-day
window holds; prices are the live ones.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

from src.runtime import order_monitor as om
from src.runtime import provenance as prov

_QTY = 2275.0
_OID = "11a8ee08-fa05-4c7d-ae9f-7d14103fe03f"
_CFGS = {"alpaca_paper": {"account_id": "alpaca_paper", "exchange": "alpaca"},
         "bybit_1": {"account_id": "bybit_1", "exchange": "bybit"}}


def _iso(t):
    return t.isoformat()


def _journal(tmp_path, *, exit_reason="exchange_flat_reconciled", notes=None,
             account="alpaca_paper", pnl=None):
    now = _dt.datetime.now(_dt.timezone.utc)
    opened = now - _dt.timedelta(hours=20)
    fill_t = now - _dt.timedelta(minutes=30)
    closed = fill_t + _dt.timedelta(seconds=149)
    notes = notes if notes is not None else json.dumps({
        "closed_at": _iso(closed), "closed_by": "position_snapshot_reconciler",
        "reset_event": False,
        "closed_reason": ("(symbol, side) confirmed absent from the exchange "
                          "open-positions snapshot across two observations AND, "
                          "where the integration supports it, by a direct "
                          "per-symbol broker check (alpaca 404); integration has "
                          "no per-order status reader (non-Bybit). PnL filled by "
                          "the local-PnL sweep (mark-to-market)."),
    })
    path = tmp_path / "j.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, "
        "position_size REAL, entry_price REAL, exit_price REAL, pnl REAL, "
        "pnl_percent REAL, account_id TEXT, created_at TEXT, closed_at TEXT, "
        "notes TEXT, setup_type TEXT, exit_reason TEXT, status TEXT, "
        "is_backtest INTEGER, broker_order_id TEXT)")
    c.execute(
        "INSERT INTO trades VALUES (7011,'IWM','long',?,283.68,NULL,?,NULL,?,?,?,?,"
        "'ml_entry',?,'closed',0,?)",
        (_QTY, pnl, account, _iso(opened), _iso(closed), notes, exit_reason, _OID))
    c.commit()
    c.close()
    return path, opened, fill_t, closed


class _DB:
    def __init__(self, path):
        self.path = path

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c


def _parent(fill_t, *, stop_status="filled", stop_qty=_QTY, legs_extra=()):
    return {
        "order_id": _OID, "order_class": "bracket", "order_type": "market",
        "side": "buy", "status": "filled", "filled_qty": _QTY,
        "legs": [
            {"order_id": "e38cd831", "order_type": "limit", "side": "sell",
             "status": "canceled", "limit_price": 288.68, "filled_qty": None,
             "filled_avg_price": None, "filled_at": None},
            {"order_id": "375986df", "order_type": "stop", "side": "sell",
             "status": stop_status, "stop_price": 279.54, "filled_qty": stop_qty,
             "filled_avg_price": 279.450338,
             "filled_at": fill_t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")},
            *legs_extra,
        ],
    }


def _reader(by_id, calls=None):
    def read(cfg, *, order_ids):
        if calls is not None:
            calls.append(tuple(order_ids))
        return {"by_id": {oid: by_id.get(oid, {"read_state": "not_found", "order": None})
                          for oid in order_ids}}
    return read


def _row(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    r = dict(c.execute("SELECT * FROM trades WHERE id = 7011").fetchone())
    c.close()
    return r, json.loads(r["notes"])


def test_filled_stop_leg_sets_the_broker_reason_price_and_time(tmp_path):
    path, _o, fill_t, closed = _journal(tmp_path)
    s = om._sweep_alpaca_close_from_broker_leg(
        _DB(path), cfgs=_CFGS,
        history_reader=_reader({_OID: {"read_state": "order_read",
                                       "order": _parent(fill_t)}}))
    assert s["closed_from_leg"] == 1
    r, n = _row(path)
    assert r["exit_reason"] == "sl"
    assert r["exit_price"] == 279.450338
    assert r["closed_at"].startswith(fill_t.strftime("%Y-%m-%dT%H:%M:%S"))
    assert abs(r["pnl"] - (279.450338 - 283.68) * _QTY) < 0.01
    assert n["closed_by"] == "broker_leg_fill"
    assert n["exit_reason_source"] == "broker_leg_fill"
    assert n["exit_price_source"] == "broker_leg_fill"
    assert n["pre_label_exit_reason"] == "exchange_flat_reconciled"
    assert n["closed_at_detected"] == _iso(closed)
    assert n["broker_leg_read"] == "filled_leg"
    assert n["exit_leg_id"] == "375986df"
    assert "_truncated" not in n
    assert n["closed_reason"] == "stop leg filled at broker"
    assert prov.classify("broker_leg_fill", "exit_reason_source") == prov.MEASURED
    assert prov.classify("broker_leg_fill", "exit_price_source") == prov.MEASURED


def test_row_is_read_once(tmp_path):
    path, _o, fill_t, _c = _journal(tmp_path)
    calls = []
    rd = _reader({_OID: {"read_state": "order_read", "order": _parent(fill_t)}}, calls)
    om._sweep_alpaca_close_from_broker_leg(_DB(path), cfgs=_CFGS, history_reader=rd)
    s = om._sweep_alpaca_close_from_broker_leg(_DB(path), cfgs=_CFGS, history_reader=rd)
    assert s["scanned"] == 0 and len(calls) == 1


def test_price_inferred_sl_off_a_detector_is_upgraded(tmp_path):
    path, _o, fill_t, _closed = _journal(tmp_path, exit_reason="sl", pnl=-9622.48, notes=json.dumps({
        "closed_at": "x", "closed_by": "position_snapshot_reconciler",
        "exit_reason_source": "price_vs_pkg_bracket", "exit_reason_price_basis": "measured",
        "pre_label_exit_reason": "exchange_flat_reconciled",
        "exit_price_source": "exchange_fill"}))
    om._sweep_alpaca_close_from_broker_leg(
        _DB(path), cfgs=_CFGS,
        history_reader=_reader({_OID: {"read_state": "order_read",
                                       "order": _parent(fill_t)}}))
    r, n = _row(path)
    assert n["exit_reason_source"] == "broker_leg_fill"
    assert n["pre_label_exit_reason"] == "exchange_flat_reconciled"
    assert "exit_reason_price_basis" not in n
    assert r["exit_reason"] == "sl"


def test_no_filled_leg_keeps_the_inference_and_marks_the_read(tmp_path):
    path, _o, fill_t, _c = _journal(tmp_path)
    s = om._sweep_alpaca_close_from_broker_leg(
        _DB(path), cfgs=_CFGS,
        history_reader=_reader({_OID: {"read_state": "order_read",
                                       "order": _parent(fill_t, stop_status="canceled")}}))
    assert s["no_leg"] == 1
    r, n = _row(path)
    assert r["exit_reason"] == "exchange_flat_reconciled" and r["exit_price"] is None
    assert n["broker_leg_read"] == "no_filled_leg"
    assert n["closed_by"] == "position_snapshot_reconciler"


def test_not_found_is_terminal_could_not_look_retries(tmp_path):
    path, *_ = _journal(tmp_path)
    s = om._sweep_alpaca_close_from_broker_leg(
        _DB(path), cfgs=_CFGS, history_reader=lambda cfg, *, order_ids: None)
    assert s["could_not_look"] == 1
    _r, n = _row(path)
    assert "broker_leg_read" not in n, "a failed read writes nothing, so the next tick retries"
    om._sweep_alpaca_close_from_broker_leg(_DB(path), cfgs=_CFGS, history_reader=_reader({}))
    _r, n = _row(path)
    assert n["broker_leg_read"] == "not_found"


def test_partial_leg_fill_is_not_the_close(tmp_path):
    path, _o, fill_t, _c = _journal(tmp_path)
    om._sweep_alpaca_close_from_broker_leg(
        _DB(path), cfgs=_CFGS,
        history_reader=_reader({_OID: {"read_state": "order_read",
                                       "order": _parent(fill_t, stop_qty=1000.0)}}))
    r, n = _row(path)
    assert n["broker_leg_read"] == "qty_mismatch" and r["exit_reason"] == "exchange_flat_reconciled"


def test_replaced_stop_is_followed_to_its_fill(tmp_path):
    path, _o, fill_t, _c = _journal(tmp_path)
    parent = _parent(fill_t)
    filled = dict(parent["legs"][1], order_id="newstop1")
    parent["legs"][1] = dict(parent["legs"][1], status="replaced", replaced_by="newstop1",
                             filled_qty=None, filled_avg_price=None, filled_at=None)
    om._sweep_alpaca_close_from_broker_leg(
        _DB(path), cfgs=_CFGS,
        history_reader=_reader({_OID: {"read_state": "order_read", "order": parent},
                                "newstop1": {"read_state": "order_read", "order": filled}}))
    r, n = _row(path)
    assert r["exit_reason"] == "sl" and n["exit_leg_id"] == "newstop1"


def test_filled_limit_leg_is_tp_and_non_alpaca_rows_are_untouched(tmp_path):
    path, _o, fill_t, _c = _journal(tmp_path)
    parent = _parent(fill_t, stop_status="canceled")
    parent["legs"][0] = dict(parent["legs"][0], status="filled", filled_qty=_QTY,
                             filled_avg_price=288.70,
                             filled_at=fill_t.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    om._sweep_alpaca_close_from_broker_leg(
        _DB(path), cfgs=_CFGS,
        history_reader=_reader({_OID: {"read_state": "order_read", "order": parent}}))
    r, _n = _row(path)
    assert r["exit_reason"] == "tp" and r["exit_price"] == 288.70



def test_bybit_row_is_never_selected(tmp_path):
    path, *_ = _journal(tmp_path, account="bybit_1")
    calls = []
    s = om._sweep_alpaca_close_from_broker_leg(
        _DB(path), cfgs=_CFGS, history_reader=_reader({}, calls))
    assert s["scanned"] == 0 and calls == []


def test_a_real_strategy_reason_is_never_replaced(tmp_path):
    path, *_ = _journal(tmp_path, exit_reason="max_hold")
    calls = []
    s = om._sweep_alpaca_close_from_broker_leg(
        _DB(path), cfgs=_CFGS, history_reader=_reader({}, calls))
    assert s["scanned"] == 0 and calls == []
