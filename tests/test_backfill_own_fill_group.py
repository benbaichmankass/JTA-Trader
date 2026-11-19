"""backfill-own-fill-exits GROUP mode: several journal rows closed by ONE venue order get that order's price.

The case (ALPACA-CLOSE-BROKER-TRUTH, 2026-11-19): alpaca_paper QQQ rows 7780/7781/7782 (735/55/7 sh) + 7783 (2 sh)
closed together when the US-open gap took out their stops. No row's own qty equals an order, so per-row mode
refuses each; one stop order of 799 sh filled them all, and every share of it fills at that order's price.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.ops import backfill_own_fill_exits as b  # noqa: E402

OPEN = "2026-11-18T15:00:00+00:00"
CLOSE = "2026-11-19T14:37:37+00:00"


def _journal(path: Path, rows):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, direction TEXT, "
              "entry_price REAL, exit_price REAL, position_size REAL, status TEXT, is_backtest INTEGER, "
              "setup_type TEXT, exit_reason TEXT, pnl REAL, pnl_percent REAL, created_at TEXT, closed_at TEXT, "
              "notes TEXT, sl_order_id TEXT, tp_order_id TEXT)")
    for rid, qty, closed in rows:
        c.execute("INSERT INTO trades (id, account_id, symbol, direction, entry_price, exit_price, position_size, "
                  "status, is_backtest, setup_type, exit_reason, pnl, created_at, closed_at, notes) "
                  "VALUES (?, 'alpaca_paper', 'QQQ', 'short', 660.0, NULL, ?, 'closed', 0, NULL, "
                  "'exchange_reset_flat', NULL, ?, ?, '{}')", (rid, qty, OPEN, closed))
    c.commit()
    c.close()


def _fills(path: Path, orders):
    f = sqlite3.connect(path)
    f.execute("CREATE TABLE exchange_fills (exec_id TEXT PRIMARY KEY, account_id TEXT, symbol TEXT, "
              "side TEXT, price REAL, qty REAL, fee REAL, fee_currency TEXT, exec_time TEXT, "
              "order_id TEXT, is_maker INTEGER, raw TEXT, inserted_at TEXT)")
    n = 0
    for oid, legs in orders:
        for px, qty in legs:
            n += 1
            f.execute("INSERT INTO exchange_fills VALUES (?, 'alpaca_paper', 'QQQ', 'buy', ?, ?, 0.0, 'USD', "
                      "'2026-11-19T14:37:30+00:00', ?, 0, NULL, NULL)", (f"e{n}", px, qty, oid))
    f.commit()
    f.close()


ROWS = [(7780, 735.0, CLOSE), (7781, 55.0, CLOSE), (7782, 7.0, CLOSE), (7783, 2.0, CLOSE)]


def _plan(tmp_path, rows=ROWS, orders=(("ord-799", [(671.0, 500.0), (671.6, 299.0)]),)):
    j, fl = tmp_path / "j.db", tmp_path / "f.db"
    _journal(j, rows)
    _fills(fl, orders)
    c = sqlite3.connect(j)
    try:
        cand = b._candidates(c, [r[0] for r in rows])
    finally:
        c.close()
    return b.plan_group(cand, lambda: sqlite3.connect(fl)), j, fl


def test_one_order_prices_every_row_measured(tmp_path):
    plan, _j, _f = _plan(tmp_path)
    plan, why = plan
    assert why is None and set(plan) == {7780, 7781, 7782, 7783}
    vwap = (671.0 * 500 + 671.6 * 299) / 799
    for rid, qty, _c in ROWS:
        u = plan[rid]
        n = json.loads(u["notes"])
        assert abs(u["exit_price"] - vwap) < 1e-6
        assert abs(u["pnl"] - round((660.0 - vwap) * qty, 4)) < 1e-3     # short: entry - exit
        assert n["exit_price_source"] == b.FILL_EXIT_SOURCE
        assert n["exit_price_allocation"] == "group_allocated"
        assert n["backfill_own_fill"]["match"] == "group_single_order"
        assert n["backfill_own_fill"]["group_qty"] == 799.0
        assert n["backfill_own_fill"]["prior_exit_price"] is None


def test_refuses_when_no_single_order_sums_to_the_group(tmp_path):
    (plan, why), _j, _f = _plan(tmp_path, orders=(("o1", [(671.0, 797.0)]), ("o2", [(672.0, 2.0)])))
    assert plan is None and "no single venue order" in why


def test_refuses_two_qualifying_orders(tmp_path):
    (plan, why), _j, _f = _plan(tmp_path, orders=(("a", [(671.0, 799.0)]), ("b", [(672.0, 799.0)])))
    assert plan is None and "no single venue order" in why


def test_refuses_mixed_keys_and_spread_closes(tmp_path):
    rows = [(1, 10.0, CLOSE), (2, 5.0, "2026-11-19T15:30:00+00:00")]
    (plan, why), _j, _f = _plan(tmp_path, rows=rows, orders=(("o", [(671.0, 15.0)]),))
    assert plan is None and "not one close event" in why


def test_refuses_a_single_row_and_a_measured_row(tmp_path):
    (plan, why), _j, _f = _plan(tmp_path, rows=[(1, 10.0, CLOSE)], orders=(("o", [(671.0, 10.0)]),))
    assert plan is None and ">= 2 rows" in why


def test_cli_group_is_opt_in_and_needs_two_ids(tmp_path, capsys, monkeypatch):
    j, fl = tmp_path / "j.db", tmp_path / "f.db"
    _journal(j, ROWS)
    _fills(fl, (("ord-799", [(671.0, 799.0)]),))
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(j), "--fills-db", str(fl), "--group", "--ids", "7780"])
    assert b.main() == 2
    # without --group the same ids are refused row by row (per-row mode is unchanged)
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(j), "--fills-db", str(fl), "--ids", "7780,7781,7782,7783"])
    assert b.main() == 0
    out = capsys.readouterr().out
    assert out.count("SKIP id=") == 4 and "planned: 0" in out
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(j), "--fills-db", str(fl), "--group",
                                      "--ids", "7780,7781,7782,7783"])
    assert b.main() == 0
    assert "planned: 4" in capsys.readouterr().out
