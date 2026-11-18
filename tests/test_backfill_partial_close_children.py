"""The partial-close backfill: dry-run by default, re-verified against the fills store, idempotent.

Uses the committed plan (docs/research/evidence/partial-close-backfill-plan-2026-11-12.json):
rows 6982 (bybit_2) and 6983 (bybit_portfolio) of pkg-633f05fad1ee4c1d, the only TRUE
partials among 29 suspected packages, plus 6983's exit correction 1.0836 -> 1.0629.
"""
from __future__ import annotations

import json
import sqlite3

from scripts.ops import backfill_partial_close_children as bf
from src.units.db.database import Database

PLAN = json.loads(bf.DEFAULT_PLAN.read_text())


def _setup(tmp_path):
    db_path = tmp_path / "j.db"
    Database(str(db_path))  # canonical schema
    c = sqlite3.connect(db_path)
    for tid, acct, size, exit_px, pnl in ((6982, "bybit_2", 53.8, 1.063, 2.4542),
                                          (6983, "bybit_portfolio", 16239.3, 1.0836, 470.9397)):
        c.execute(
            "INSERT INTO trades (id, timestamp, symbol, direction, entry_price, position_size, "
            "status, exit_price, pnl, account_id, order_package_id, strategy_name, is_backtest, "
            "created_at, closed_at, notes) VALUES (?, '2026-11-09T00:02:40Z', 'XRPUSDT', 'short', "
            "1.1126, ?, 'closed', ?, ?, ?, 'pkg-633f05fad1ee4c1d', 'trend_donchian_xrp_4h', 0, "
            "'2026-11-09T00:02:40Z', '2026-11-10T18:28:14Z', '{}')",
            (tid, size, exit_px, pnl, acct))
    c.commit()
    c.close()
    f_path = tmp_path / "f.db"
    f = sqlite3.connect(f_path)
    f.execute("CREATE TABLE exchange_fills (exec_id TEXT PRIMARY KEY, account_id TEXT, symbol TEXT, "
              "side TEXT, price REAL, qty REAL, fee REAL, fee_currency TEXT, exec_time TEXT, "
              "order_id TEXT, is_maker INTEGER, raw TEXT, inserted_at TEXT)")
    child = {c["trade_id"]: c for c in PLAN["partial_children"]}
    rows = [("a", "bybit_2", 1.0893, 53.8, 0.03, child[6982]["close_order_id"]),
            ("b", "bybit_portfolio", 1.0836, 16239.2, 9.68, child[6983]["close_order_id"]),
            ("c", "bybit_portfolio", 1.0629, 16239.3, 9.49341359,
             PLAN["exit_corrections"][0]["own_order_id"])]
    for eid, acct, px, qty, fee, oid in rows:
        f.execute("INSERT INTO exchange_fills VALUES (?,?,'XRPUSDT','buy',?,?,?,'USDT','t',?,0,NULL,NULL)",
                  (eid, acct, px, qty, fee, oid))
    f.commit()
    f.close()
    return str(db_path), str(f_path)


def _count_children(db_path):
    c = sqlite3.connect(db_path)
    n = c.execute("SELECT COUNT(*) FROM trades WHERE setup_type='partial_close'").fetchone()[0]
    c.close()
    return n


def test_plan_holds_only_the_two_true_partials():
    assert sorted(c["trade_id"] for c in PLAN["partial_children"]) == [6982, 6983]
    assert len(PLAN["excluded"]["entry_filled_half_not_a_partial"]) == 27


def test_dry_run_writes_nothing(tmp_path, capsys):
    db_path, f_path = _setup(tmp_path)
    assert bf.main(["--db", db_path, "--fills-db", f_path]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and out.count('"verdict": "write"') == 3
    assert _count_children(db_path) == 0


def test_apply_books_children_and_corrects_6983_once(tmp_path):
    db_path, f_path = _setup(tmp_path)
    bf.main(["--db", db_path, "--fills-db", f_path, "--apply"])
    assert _count_children(db_path) == 2
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT * FROM trades WHERE id=6983").fetchone()
    kid = c.execute("SELECT * FROM trades WHERE setup_type='partial_close' AND account_id='bybit_portfolio'").fetchone()
    parent2 = c.execute("SELECT position_size FROM trades WHERE id=6982").fetchone()[0]
    c.close()
    assert abs(r["exit_price"] - 1.0629) < 1e-9
    assert abs(r["pnl"] - ((1.1126 - 1.0629) * 16239.3 - 9.49341359)) < 1e-3
    assert json.loads(r["notes"])["backfill_partial_close"]["from_exit_price"] == 1.0836
    assert abs(kid["pnl"] - ((1.1126 - 1.0836) * 16239.2 - 9.68)) < 1e-3
    assert parent2 == 53.8, "the parent already holds the remainder; never shrunk again"
    bf.main(["--db", db_path, "--fills-db", f_path, "--apply"])
    assert _count_children(db_path) == 2, "idempotent"


def test_an_item_the_store_cannot_confirm_is_not_written(tmp_path):
    db_path, f_path = _setup(tmp_path)
    f = sqlite3.connect(f_path)
    f.execute("DELETE FROM exchange_fills WHERE account_id='bybit_2'")
    f.commit()
    f.close()
    bf.main(["--db", db_path, "--fills-db", f_path, "--apply"])
    c = sqlite3.connect(db_path)
    n2 = c.execute("SELECT COUNT(*) FROM trades WHERE setup_type='partial_close' AND account_id='bybit_2'").fetchone()[0]
    c.close()
    assert n2 == 0
