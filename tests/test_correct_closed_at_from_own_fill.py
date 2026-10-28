"""CLOSE-LABELS-1214: reconciler-detected close times move back to the row's own fill,
and the existing order-identity relabel keeps turning those closes into sl/tp.

Shape from the 2026-10-28 SOLUSDT stop on bybit_1 (trade 6761) and bybit_portfolio
(6763): the stop filled about 12:14:35Z, the reconciler (demo accounts have no
closed-pnl record) stamped closed_at 12:19:07Z / 12:19:13Z with reason
`reconciler_filled`. The hourly fills pull (:20) is why the fix is a sweep, not a
reconciler change. Fill times below are illustrative offsets, not the live rows.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

from src.runtime import order_monitor as om

_QTY = 334.1


def _journal(tmp_path, *, detected_lag_s=270, notes=None, exit_reason="reconciler_filled"):
    now = _dt.datetime.now(_dt.timezone.utc)
    fill_t = now - _dt.timedelta(minutes=30)
    closed = fill_t + _dt.timedelta(seconds=detected_lag_s)
    notes = notes if notes is not None else json.dumps({
        "closed_at": closed.isoformat(), "closed_by": "monitor_reconciler",
        "closed_reason": "reconciler — Bybit reports order filled and position flat",
        "exit_price_source": "exchange_fill", "exit_reason_source": "venue_bracket_order",
    })
    path = tmp_path / "j.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, "
        "position_size REAL, entry_price REAL, exit_price REAL, pnl REAL, "
        "account_id TEXT, created_at TEXT, closed_at TEXT, notes TEXT, "
        "setup_type TEXT, exit_reason TEXT, status TEXT, is_backtest INTEGER, "
        "sl_order_id TEXT, tp_order_id TEXT)")
    c.execute(
        "INSERT INTO trades VALUES (6761,'SOLUSDT','long',?,102.98,NULL,NULL,'bybit_1',"
        "?,?,?,'trend_donchian_sol_prop',?,'closed',0,'sl-1','tp-1')",
        (_QTY, (now - _dt.timedelta(hours=4)).isoformat(), closed.isoformat(), notes,
         exit_reason))
    c.commit()
    c.close()
    return path, fill_t, closed


def _fills(tmp_path, fill_t, fills):
    path = tmp_path / "f.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE exchange_fills (exec_id TEXT PRIMARY KEY, account_id TEXT, "
        "symbol TEXT, side TEXT, price REAL, qty REAL, fee REAL, fee_currency TEXT, "
        "exec_time TEXT, order_id TEXT, is_maker INTEGER, raw TEXT, inserted_at TEXT)")
    for i, (oid, price, qty) in enumerate(fills):
        c.execute(
            "INSERT INTO exchange_fills VALUES (?,?,?,?,?,?,0,'USDT',?,?,0,NULL,NULL)",
            (f"e{i}", "bybit_1", "SOLUSDT", "sell", price, qty,
             fill_t.isoformat(), oid))
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
    r = dict(c.execute("SELECT * FROM trades WHERE id=6761").fetchone())
    c.close()
    r["notes"] = json.loads(r["notes"])
    return r


def test_late_detected_close_time_moves_to_the_fill(tmp_path):
    jpath, fill_t, closed = _journal(tmp_path)
    fac = _fills(tmp_path, fill_t, [("sl-1", 101.85, _QTY)])
    s = om._sweep_correct_closed_at_from_own_fill(_DB(jpath), fills_conn_factory=fac)
    r = _row(jpath)
    assert s["corrected"] == 1
    assert _dt.datetime.fromisoformat(r["closed_at"]) == fill_t
    assert r["notes"]["closed_at"] == r["closed_at"]
    assert r["notes"]["closed_at_detected"] == closed.isoformat()
    assert r["notes"]["closed_at_source"] == "own_bracket_fill"
    assert r["exit_reason"] == "reconciler_filled" and r["status"] == "closed"


def test_second_pass_and_in_sync_rows_are_left_alone(tmp_path):
    jpath, fill_t, _ = _journal(tmp_path)
    fac = _fills(tmp_path, fill_t, [("sl-1", 101.85, _QTY)])
    om._sweep_correct_closed_at_from_own_fill(_DB(jpath), fills_conn_factory=fac)
    assert om._sweep_correct_closed_at_from_own_fill(
        _DB(jpath), fills_conn_factory=fac)["corrected"] == 0
    other = tmp_path / "sync"
    other.mkdir()
    jp2, ft2, _ = _journal(other, detected_lag_s=20)
    s = om._sweep_correct_closed_at_from_own_fill(
        _DB(jp2), fills_conn_factory=_fills(other, ft2, [("sl-1", 101.85, _QTY)]))
    assert s["corrected"] == 0 and s["in_sync"] == 1


def test_no_fill_or_foreign_order_or_venue_record_row_is_untouched(tmp_path):
    jpath, fill_t, closed = _journal(tmp_path)
    for fills in ([], [("someone-elses", 101.85, _QTY)]):
        sub = tmp_path / f"n{len(fills)}"
        sub.mkdir()
        jp, ft, cl = _journal(sub)
        s = om._sweep_correct_closed_at_from_own_fill(
            _DB(jp), fills_conn_factory=_fills(sub, ft, fills))
        assert s["corrected"] == 0 and s["no_own_fill"] == 1
        assert _row(jp)["closed_at"] == cl.isoformat()
    venue = tmp_path / "venue"
    venue.mkdir()
    jp, ft, _ = _journal(venue, notes=json.dumps({
        "closed_by": "monitor_reconciler", "exit_price_source": "bybit_closed_pnl"}))
    assert om._sweep_correct_closed_at_from_own_fill(
        _DB(jp), fills_conn_factory=_fills(venue, ft, [("sl-1", 101.85, _QTY)])
    )["scanned"] == 0


def test_reconciler_filled_close_with_own_stop_fill_is_relabelled_sl(tmp_path):
    """Regression for the 6761/6763 label: reconciler_filled + a full fill on the
    row's own sl_order_id becomes `sl` (MEASURED, venue_bracket_order)."""
    jpath, fill_t, _ = _journal(tmp_path)
    fac = _fills(tmp_path, fill_t, [("sl-1", 101.85, _QTY)])

    def _factory():
        return fac()

    s = om._sweep_exit_label_from_bracket_order(_DB(jpath), fills_conn_factory=_factory)
    r = _row(jpath)
    assert s["relabelled"] == 1
    assert r["exit_reason"] == "sl"
    assert r["notes"]["exit_reason_source"] == "venue_bracket_order"
    assert r["notes"]["pre_label_exit_reason"] == "reconciler_filled"


def test_netting_attributed_close_with_own_target_fill_is_relabelled_tp(tmp_path):
    jpath, fill_t, _ = _journal(tmp_path, exit_reason="netting_attributed")
    fac = _fills(tmp_path, fill_t, [("tp-1", 110.9, _QTY)])
    s = om._sweep_exit_label_from_bracket_order(_DB(jpath), fills_conn_factory=fac)
    assert s["relabelled"] == 1 and _row(jpath)["exit_reason"] == "tp"
