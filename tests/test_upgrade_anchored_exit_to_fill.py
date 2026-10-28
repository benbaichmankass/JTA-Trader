"""CLOSE-LABELS-1214: a candle-priced exit is replaced by the row's own bracket fill.

Shape taken from bybit_1 trade 6764 (BTCUSDT long, demo, 2026-10-28): closed by
`_netting_apply_close` at the first divergence observation, booked at the 1-minute
candle close 80999.9 (`candle_at_close`) with pnl -851.24, package stop 80961.13.
The fill price below is the package stop level, an ILLUSTRATIVE value: the real
fill row was not readable when this was written (no diag route to the fills store).
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

from src.runtime import order_monitor as om

_SL = 80961.12857143
_ENTRY = 81518.0
_QTY = 1.643
_CANDLE = 80999.9


def _journal(tmp_path, *, notes=None, setup_type="trend_donchian", closed_ago_h=1.0):
    now = _dt.datetime.now(_dt.timezone.utc)
    created = (now - _dt.timedelta(hours=5)).isoformat()
    closed = (now - _dt.timedelta(hours=closed_ago_h)).isoformat()
    notes = notes if notes is not None else json.dumps({
        "exit_price_source": "candle_at_close", "pnl_source": "local_compute",
        "netting_attribution_basis": "leg_gone", "contract_value_usd": 1.0,
    })
    path = tmp_path / "j.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, "
        "position_size REAL, entry_price REAL, exit_price REAL, pnl REAL, "
        "pnl_percent REAL, account_id TEXT, created_at TEXT, closed_at TEXT, "
        "notes TEXT, setup_type TEXT, exit_reason TEXT, status TEXT, "
        "is_backtest INTEGER, sl_order_id TEXT, tp_order_id TEXT)")
    c.execute(
        "INSERT INTO trades VALUES (6764,'BTCUSDT','long',?,?,?,?,NULL,'bybit_1',?,?,?,?,"
        "'netting_attributed','closed',0,'sl-1','tp-1')",
        (_QTY, _ENTRY, _CANDLE, round((_CANDLE - _ENTRY) * _QTY, 4), created, closed,
         notes, setup_type))
    c.commit()
    c.close()
    return path, now - _dt.timedelta(hours=closed_ago_h)


def _fills(tmp_path, closed_at, fills):
    path = tmp_path / "f.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE exchange_fills (exec_id TEXT PRIMARY KEY, account_id TEXT, "
        "symbol TEXT, side TEXT, price REAL, qty REAL, fee REAL, fee_currency TEXT, "
        "exec_time TEXT, order_id TEXT, is_maker INTEGER, raw TEXT, inserted_at TEXT)")
    for i, (oid, price, qty, fee) in enumerate(fills):
        c.execute(
            "INSERT INTO exchange_fills VALUES (?,?,?,?,?,?,?,?,?,?,0,NULL,NULL)",
            (f"e{i}", "bybit_1", "BTCUSDT", "sell", price, qty, fee, "USDT",
             (closed_at - _dt.timedelta(seconds=2)).isoformat(), oid))
    c.commit()
    c.close()
    return lambda: sqlite3.connect(path)


class _DB:
    def __init__(self, path):
        self.path = path

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c


def _row(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    r = dict(c.execute("SELECT * FROM trades WHERE id=6764").fetchone())
    c.close()
    r["notes"] = json.loads(r["notes"])
    return r


def test_candle_exit_is_replaced_by_own_stop_fill(tmp_path):
    jpath, closed = _journal(tmp_path)
    fac = _fills(tmp_path, closed, [("sl-1", _SL, _QTY, 5.0)])
    s = om._sweep_upgrade_anchored_exit_to_fill(_DB(jpath), fills_conn_factory=fac)
    r = _row(jpath)
    assert s["upgraded"] == 1 and s["scanned"] == 1
    assert r["exit_price"] == round(_SL, 10)
    assert r["pnl"] == round((_SL - _ENTRY) * _QTY - 5.0, 4)
    assert r["pnl"] < round((_CANDLE - _ENTRY) * _QTY, 4)   # the estimate flattered the loss
    n = r["notes"]
    assert n["exit_price_source"] == "exchange_fill"
    assert n["pre_fill_exit_price"] == _CANDLE
    assert n["pre_fill_pnl"] == round((_CANDLE - _ENTRY) * _QTY, 4)
    assert n["exit_fill"] == {"order_id": "sl-1", "match": "own_bracket_order"}
    assert r["exit_reason"] == "netting_attributed"           # label is the other sweep's job
    assert r["pnl_percent"] is not None


def test_no_fill_in_store_yet_leaves_the_estimate(tmp_path):
    jpath, closed = _journal(tmp_path)
    fac = _fills(tmp_path, closed, [])
    s = om._sweep_upgrade_anchored_exit_to_fill(_DB(jpath), fills_conn_factory=fac)
    r = _row(jpath)
    assert s["upgraded"] == 0 and s["no_own_fill"] == 1
    assert r["exit_price"] == _CANDLE
    assert r["notes"]["exit_price_source"] == "candle_at_close"


def test_qty_only_match_is_not_identity_and_is_left_alone(tmp_path):
    """A full-qty fill on SOME OTHER order is not this row's stop."""
    jpath, closed = _journal(tmp_path)
    fac = _fills(tmp_path, closed, [("someone-elses", _SL, _QTY, 0.0)])
    s = om._sweep_upgrade_anchored_exit_to_fill(_DB(jpath), fills_conn_factory=fac)
    assert s["upgraded"] == 0
    assert _row(jpath)["exit_price"] == _CANDLE


def test_measured_exit_and_intent_reduce_rows_are_not_selected(tmp_path):
    jpath, closed = _journal(tmp_path, notes=json.dumps(
        {"exit_price_source": "exchange_fill"}))
    fac = _fills(tmp_path, closed, [("sl-1", _SL, _QTY, 0.0)])
    assert om._sweep_upgrade_anchored_exit_to_fill(
        _DB(jpath), fills_conn_factory=fac)["scanned"] == 0
    other = tmp_path / "reduce"
    other.mkdir()
    jpath2, _ = _journal(other, setup_type="intent_reduce")
    assert om._sweep_upgrade_anchored_exit_to_fill(
        _DB(jpath2), fills_conn_factory=fac)["scanned"] == 0


def test_second_pass_is_a_noop(tmp_path):
    jpath, closed = _journal(tmp_path)
    fac = _fills(tmp_path, closed, [("sl-1", _SL, _QTY, 0.0)])
    om._sweep_upgrade_anchored_exit_to_fill(_DB(jpath), fills_conn_factory=fac)
    again = om._sweep_upgrade_anchored_exit_to_fill(_DB(jpath), fills_conn_factory=fac)
    assert again["scanned"] == 0 and again["upgraded"] == 0
