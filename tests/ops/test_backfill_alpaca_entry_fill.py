"""ALPACA-ENTRY-FILL-PRICE-UNSYNCED (2026-11-26): the one-shot that corrects late-filled Alpaca entries.

Pins: only plan/unlabelled Alpaca rows whose entry order is fully filled at a different price are written; the
written fields are entry_price, the linear pnl shift on closed rows (old kept), pnl_percent and the cleared basis;
SL/TP/size/status are untouched; dry-run writes nothing; a re-run is a no-op; an unreadable order is left alone.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("bafill", ROOT / "scripts/ops/backfill_alpaca_entry_fill.py")
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)

ACCTS = {"alpaca_paper": {"exchange": "alpaca", "account_id": "alpaca_paper"}}
COLS = ("id INTEGER PRIMARY KEY, timestamp TEXT, created_at TEXT, account_id TEXT, symbol TEXT, direction TEXT, "
        "entry_price REAL, stop_loss REAL, take_profit_1 REAL, position_size REAL, status TEXT, pnl REAL, "
        "pnl_percent REAL, pnl_basis TEXT, pnl_computed REAL, pnl_gap_usd REAL, notes TEXT, broker_order_id TEXT, "
        "is_backtest INTEGER")


def _db(tmp_path):
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute(f"CREATE TABLE trades ({COLS})")
    rows = [
        # 8521 shape: closed long, package 132.715, venue 133.165649 x 1147, labelled venue_fills_net
        (8521, "alpaca_paper", "USO", "long", 132.715, 134.74, 137.71, 1147, "closed", 5807.795, "venue_fills_net",
         {"entry_price_source": "plan", "entry_price_source_reason": "no_venue_fill_read",
          "exit_price_source": "exchange_fill"}, "a4905e39-a15d-4ec3-bd7b-5ee4fe021700"),
        # open short, unlabelled (pre-11-15 row), venue fill differs
        (7587, "alpaca_paper", "TLT", "short", 79.60, 81.0, 77.0, 864, "open", None, None, {},
         "11111111-1111-1111-1111-111111111111"),
        # already venue-labelled: never touched
        (8615, "alpaca_paper", "USO", "long", 139.9, 137.0, 145.0, 100, "open", None, None,
         {"entry_price_source": "alpaca_order_status"}, "22222222-2222-2222-2222-222222222222"),
        # fill equals the journal: skipped
        (8454, "alpaca_paper", "QQQ", "short", 647.29, 650.0, 640.0, 10, "open", None, None,
         {"entry_price_source": "plan"}, "33333333-3333-3333-3333-333333333333"),
        # unreadable order: left alone, counted
        (8000, "alpaca_paper", "SPY", "long", 700.0, 690.0, 720.0, 5, "open", None, None,
         {"entry_price_source": "plan"}, "44444444-4444-4444-4444-444444444444"),
        # a Bybit row: not an Alpaca account, never scanned
        (9000, "bybit_2", "BTCUSDT", "long", 50000.0, 49000.0, 52000.0, 0.1, "open", None, None,
         {"entry_price_source": "plan"}, "BYBIT-1"),
    ]
    for (i, a, s, d, e, sl, tp, q, st, pnl, basis, n, oid) in rows:
        c.execute("INSERT INTO trades (id, timestamp, created_at, account_id, symbol, direction, entry_price, stop_loss,"
                  " take_profit_1, position_size, status, pnl, pnl_basis, pnl_computed, pnl_gap_usd, notes,"
                  " broker_order_id, is_backtest) VALUES (?, datetime('now','-2 days'), datetime('now','-2 days'),"
                  " ?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                  (i, a, s, d, e, sl, tp, q, st, pnl, basis, pnl if basis else None, 0.0 if basis else None,
                   json.dumps(n), oid))
    c.commit()
    return c


ORDERS = {
    "a4905e39-a15d-4ec3-bd7b-5ee4fe021700": {"status": "filled", "filled_qty": 1147.0, "filled_avg_price": 133.165649},
    "11111111-1111-1111-1111-111111111111": {"status": "filled", "filled_qty": 864.0, "filled_avg_price": 79.59},
    "22222222-2222-2222-2222-222222222222": {"status": "filled", "filled_qty": 100.0, "filled_avg_price": 140.5},
    "33333333-3333-3333-3333-333333333333": {"status": "filled", "filled_qty": 10.0, "filled_avg_price": 647.29},
}


def _reader(cfg, oid):
    assert cfg["exchange"] == "alpaca"
    return ORDERS.get(oid)          # 4444... -> None (could not look)


def _row(c, i):
    c.row_factory = sqlite3.Row
    r = dict(c.execute("SELECT * FROM trades WHERE id = ?", (i,)).fetchone())
    r["notes"] = json.loads(r["notes"] or "{}")
    return r


def test_plan_lists_exactly_the_late_fills_with_their_pnl_delta(tmp_path):
    c = _db(tmp_path)
    plan = bf.plan_rows(c, ACCTS, _reader, 30)
    w = {p["id"]: p for p in plan["rows"] if p["action"] == "write"}
    assert set(w) == {8521, 7587}
    assert w[8521]["pnl_delta"] == pytest.approx(516.894403, abs=1e-4)      # the measured overstatement
    assert w[7587]["pnl_delta"] == pytest.approx((79.59 - 79.60) * 864 * -1)  # short: a lower fill is a worse entry
    why = {p["id"]: p["why"] for p in plan["rows"]}
    assert why[8454] == "already_equal" and why[8000] == "could_not_look" and plan["could_not_look"] == 1
    assert 8615 not in why and 9000 not in why


def test_apply_writes_entry_and_shifts_closed_pnl_only(tmp_path):
    c = _db(tmp_path)
    before = {i: _row(c, i) for i in (8521, 7587, 8615, 8454, 8000, 9000)}
    plan = bf.plan_rows(c, ACCTS, _reader, 30)
    assert bf.apply_rows(c, plan, "2026-11-26T13:00:00+00:00") == 2
    r = _row(c, 8521)
    assert r["entry_price"] == pytest.approx(133.165649)
    assert r["pnl"] == pytest.approx(5807.795 - 516.894403, abs=1e-4)
    assert r["pnl_basis"] is None and r["pnl_computed"] is None and r["pnl_gap_usd"] is None
    assert r["notes"]["package_entry"] == pytest.approx(132.715) and r["notes"]["pnl_prior"] == pytest.approx(5807.795)
    assert r["notes"]["entry_price_source"] == "alpaca_order_status" and "entry_price_source_reason" not in r["notes"]
    assert r["notes"]["exit_price_source"] == "exchange_fill"                 # existing keys kept
    o = _row(c, 7587)
    assert o["entry_price"] == pytest.approx(79.59) and o["pnl"] is None and "pnl_prior" not in o["notes"]
    for i, b in before.items():
        a = _row(c, i)
        for k in ("stop_loss", "take_profit_1", "position_size", "status", "broker_order_id"):
            assert a[k] == b[k], (i, k)
        if i in (8615, 8454, 8000, 9000):
            assert a == b, i
    # idempotent: a re-run finds nothing to write
    again = bf.plan_rows(c, ACCTS, _reader, 30)
    assert [p for p in again["rows"] if p["action"] == "write"] == []


def test_dry_run_plan_writes_nothing(tmp_path):
    c = _db(tmp_path)
    snap = c.execute("SELECT * FROM trades ORDER BY id").fetchall()
    bf.plan_rows(c, ACCTS, _reader, 30)
    c.row_factory = None
    assert c.execute("SELECT * FROM trades ORDER BY id").fetchall() == [tuple(r) for r in snap]


def test_a_partial_entry_fill_is_not_isolable_and_is_skipped(tmp_path):
    c = _db(tmp_path)
    orders = dict(ORDERS)
    orders["a4905e39-a15d-4ec3-bd7b-5ee4fe021700"] = {"status": "filled", "filled_qty": 500.0,
                                                      "filled_avg_price": 133.0}
    plan = bf.plan_rows(c, ACCTS, lambda cfg, oid: orders.get(oid), 30)
    assert {p["id"]: p["why"] for p in plan["rows"]}[8521] == "entry_order_qty_mismatch"
