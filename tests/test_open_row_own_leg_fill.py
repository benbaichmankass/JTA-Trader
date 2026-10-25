"""ORDER-AUDIT-4 item 19 — an OPEN row whose own bracket order filled closes.

PI-20260930-3QNHBGND-0002. MEASURED 2026-09-30 on alpaca_paper SPY: row 6131
(8 sh) had its own stop leg fill 8 @ 763.70 while sibling row 4347 (11 sh) kept
the symbol long, so the venue held 11 and the journal 19 for two weeks. Every
flat-close path keys on (account, symbol, side) ABSENCE and so cannot see one
of two netted rows go.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

import pytest

from src.runtime import order_monitor as om


def _ago(**kw):
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(**kw)).isoformat()


_SL, _TP = "9fe49151-sl", "e21f6ca9-tp"


def _setup(tmp_path, rows, fills):
    jp, fp = tmp_path / "j.db", tmp_path / "f.db"
    c = sqlite3.connect(jp)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, "
              "symbol TEXT, direction TEXT, position_size REAL, created_at TEXT, "
              "notes TEXT, sl_order_id TEXT, tp_order_id TEXT, "
              "order_package_id TEXT, setup_type TEXT, status TEXT, "
              "is_backtest INTEGER)")
    for r in rows:
        c.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
                  (r["id"], "alpaca_paper", "SPY", r.get("direction", "long"),
                   r["size"], r.get("created_at", _ago(days=3)),
                   json.dumps(r.get("notes", {"trade_id": "x"})),
                   r.get("sl"), r.get("tp"), r.get("pkg"),
                   r.get("setup_type"), r.get("status", "open")))
    c.commit()
    c.close()
    f = sqlite3.connect(fp)
    f.execute("CREATE TABLE exchange_fills (exec_id TEXT, account_id TEXT, "
              "symbol TEXT, side TEXT, price REAL, qty REAL, exec_time TEXT, "
              "order_id TEXT)")
    f.executemany("INSERT INTO exchange_fills VALUES (?,?,?,?,?,?,?,?)", fills)
    f.commit()
    f.close()

    class _DB:
        def __init__(self):
            self.updates = {}

        def connect(self):
            return sqlite3.connect(jp)

        def update_trade(self, tid, updates):
            self.updates[tid] = dict(updates)
            cc = sqlite3.connect(jp)
            cc.execute("UPDATE trades SET status=? WHERE id=?",
                       (updates["status"], tid))
            cc.commit()
            cc.close()

    return _DB(), (lambda: sqlite3.connect(fp))


@pytest.fixture
def _quiet(monkeypatch):
    calls = {"cancel": [], "cascade": []}
    monkeypatch.setattr(om, "_cancel_closed_row_protection",
                        lambda row, db: calls["cancel"].append(row["id"]))
    monkeypatch.setattr(om, "_cascade_close_linked_package",
                        lambda db, tid, **k: calls["cascade"].append((tid, k["close_reason"])))
    return calls


def _fill(oid, qty, price=763.70, side="sell", when=None):
    return ("e-" + oid + str(qty), "alpaca_paper", "SPY", side, price, qty,
            when or _ago(days=1), oid)


def test_netted_row_whose_own_stop_filled_is_closed(tmp_path, _quiet):
    db, ff = _setup(tmp_path, [
        {"id": 6131, "size": 8.0, "sl": _SL, "tp": _TP, "pkg": "pkg-51f1"},
        {"id": 4347, "size": 11.0, "sl": "other-sl", "tp": "other-tp"},
    ], [_fill(_SL, 5.0, 763.8), _fill(_SL, 3.0, 763.5)])
    s = om._sweep_open_row_own_leg_fill(db, fills_conn_factory=ff)
    assert s["closed"] == 1 and s["no_own_leg_fill"] == 1
    u = db.updates[6131]
    assert u["status"] == "closed" and u["exit_reason"] == "sl"
    assert u["exit_price"] == pytest.approx((5 * 763.8 + 3 * 763.5) / 8)
    n = json.loads(u["notes"])
    assert n["exit_reason_source"] == "venue_bracket_order"
    assert n["exit_price_source"] == "exchange_fill"
    assert n["own_leg_fill"]["order_id"] == _SL
    assert 4347 not in db.updates                # the sibling stays open
    assert _quiet["cancel"] == [6131]
    assert _quiet["cascade"] == [(6131, "sl")]


def test_partial_own_fill_does_not_close(tmp_path, _quiet):
    db, ff = _setup(tmp_path, [{"id": 1, "size": 8.0, "sl": _SL, "tp": _TP}],
                    [_fill(_TP, 4.0, 780.0)])
    s = om._sweep_open_row_own_leg_fill(db, fills_conn_factory=ff)
    assert s["closed"] == 0 and not db.updates and not _quiet["cancel"]


def test_sibling_fills_never_close_a_row(tmp_path, _quiet):
    """Only the row's OWN order ids count; a sibling's full fill is not it."""
    db, ff = _setup(tmp_path, [{"id": 1, "size": 8.0, "sl": _SL, "tp": _TP}],
                    [_fill("sibling-order", 8.0)])
    assert om._sweep_open_row_own_leg_fill(db, fills_conn_factory=ff)["closed"] == 0


def test_entry_side_fill_on_the_order_id_is_ignored(tmp_path, _quiet):
    db, ff = _setup(tmp_path, [{"id": 1, "size": 8.0, "sl": _SL, "tp": _TP}],
                    [_fill(_SL, 8.0, side="buy")])
    assert om._sweep_open_row_own_leg_fill(db, fills_conn_factory=ff)["closed"] == 0


def test_both_legs_full_is_ambiguous_and_left_alone(tmp_path, _quiet):
    db, ff = _setup(tmp_path, [{"id": 1, "size": 8.0, "sl": _SL, "tp": _TP}],
                    [_fill(_SL, 8.0), _fill(_TP, 8.0)])
    assert om._sweep_open_row_own_leg_fill(db, fills_conn_factory=ff)["closed"] == 0


def test_short_row_target_fill_closes_tp(tmp_path, _quiet):
    db, ff = _setup(tmp_path, [{"id": 5265, "size": 707.0, "direction": "short",
                                "sl": _SL, "tp": _TP}],
                    [_fill(_TP, 707.0, 79.5, side="buy")])
    om._sweep_open_row_own_leg_fill(db, fills_conn_factory=ff)
    assert db.updates[5265]["exit_reason"] == "tp"


def test_intent_reduce_and_closed_rows_are_not_scanned(tmp_path, _quiet):
    db, ff = _setup(tmp_path, [
        {"id": 1, "size": 8.0, "sl": _SL, "tp": _TP, "setup_type": "intent_reduce"},
        {"id": 2, "size": 8.0, "sl": _SL + "2", "tp": _TP + "2", "status": "closed"},
    ], [_fill(_SL, 8.0), _fill(_SL + "2", 8.0)])
    s = om._sweep_open_row_own_leg_fill(db, fills_conn_factory=ff)
    assert s["scanned"] == 0 and not db.updates


def test_unreadable_fills_store_is_could_not_look(tmp_path, _quiet):
    db, _ff = _setup(tmp_path, [{"id": 1, "size": 8.0, "sl": _SL, "tp": _TP}], [])
    s = om._sweep_open_row_own_leg_fill(db, fills_conn_factory=lambda: None)
    assert s["store_unreadable"] == 1 and s["no_own_leg_fill"] == 0
