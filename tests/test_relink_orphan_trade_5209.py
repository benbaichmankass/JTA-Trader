"""GLD-ORPHAN-5209: the relink action is conditional, venue-gated, all-or-nothing and idempotent."""
from __future__ import annotations

import json
import sqlite3

import pytest

from scripts.ops import relink_orphan_trade_5209 as R


def _db(tmp_path, **over):
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT, account_id TEXT, symbol TEXT, position_size REAL,"
              " order_package_id TEXT, stop_loss REAL, take_profit_1 REAL, notes TEXT)")
    c.execute("CREATE TABLE order_packages (order_package_id TEXT PRIMARY KEY, status TEXT, close_reason TEXT,"
              " linked_trade_id INTEGER, sl REAL, tp REAL, meta TEXT, updated_at TEXT)")
    t = dict(id=5209, status="open", account_id="alpaca_paper", symbol="GLD", position_size=39.0,
             order_package_id=R.FALSE_PKG, stop_loss=414.53875, take_profit_1=461.32723, notes='{"adopted_by": "x"}')
    t.update(over.get("trade", {}))
    c.execute("INSERT INTO trades VALUES (:id,:status,:account_id,:symbol,:position_size,:order_package_id,"
              ":stop_loss,:take_profit_1,:notes)", t)
    c.execute("INSERT INTO order_packages VALUES (?,?,?,?,?,?,?,?)",
              (R.TRUE_PKG, *over.get("true", ("closed", "exchange_flat_reconciled")), 5126, 416.08857143, 461.27228, "{}", "x"))
    c.execute("INSERT INTO order_packages VALUES (?,?,?,?,?,?,?,?)",
              (R.FALSE_PKG, *over.get("false", ("open", None)), 5209, 414.53875, 461.32723, "{}", "x"))
    c.commit()
    c.close()
    return str(p)


def _venue(tmp_path, qty=39.0, sl=416.09, tp=461.27, read_state="orders_read"):
    doc = {"accounts": [{"account_id": "alpaca_paper", "read_state": read_state, "result": {
        "positions": [{"symbol": "GLD", "side": "buy", "qty": qty}],
        "orders": [{"symbol": "GLD", "side": "sell", "order_type": "limit", "limit_price": tp},
                   {"symbol": "GLD", "side": "sell", "order_type": "stop", "stop_price": sl}]}}]}
    p = tmp_path / "v.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _rows(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    t = dict(c.execute("SELECT * FROM trades WHERE id=5209").fetchone())
    pk = {r["order_package_id"]: dict(r) for r in c.execute("SELECT * FROM order_packages")}
    c.close()
    return t, pk


def test_dry_run_writes_nothing(tmp_path):
    db = _db(tmp_path)
    assert R.main(["--db", db, "--venue", _venue(tmp_path)]) == 0
    t, pk = _rows(db)
    assert t["order_package_id"] == R.FALSE_PKG and pk[R.TRUE_PKG]["status"] == "closed"


def test_apply_relinks_reopens_and_closes_then_is_a_noop(tmp_path):
    db = _db(tmp_path)
    assert R.main(["--db", db, "--venue", _venue(tmp_path), "--reason", "r", "--apply"]) == 0
    t, pk = _rows(db)
    assert (t["order_package_id"], t["stop_loss"], t["take_profit_1"]) == (R.TRUE_PKG, 416.08857143, 461.27228)
    assert json.loads(t["notes"])["relink_repair"]["from_package"] == R.FALSE_PKG
    assert json.loads(t["notes"])["adopted_by"] == "x"
    assert (pk[R.TRUE_PKG]["status"], pk[R.TRUE_PKG]["close_reason"], pk[R.TRUE_PKG]["linked_trade_id"]) == ("open", None, 5209)
    assert (pk[R.FALSE_PKG]["status"], pk[R.FALSE_PKG]["close_reason"]) == ("closed", "sl")
    assert json.loads(pk[R.TRUE_PKG]["meta"])["relink_repair"]["prior_close_reason"] == "exchange_flat_reconciled"
    assert R.main(["--db", db, "--venue", _venue(tmp_path), "--apply"]) == 0  # idempotent no-op


@pytest.mark.parametrize("kw", [dict(qty=38.0), dict(sl=414.54), dict(tp=461.33), dict(read_state="could_not_look")])
def test_venue_that_does_not_match_refuses_and_writes_nothing(tmp_path, kw):
    db = _db(tmp_path)
    assert R.main(["--db", db, "--venue", _venue(tmp_path, **kw), "--apply"]) == 2
    assert _rows(db)[0]["order_package_id"] == R.FALSE_PKG


@pytest.mark.parametrize("over", [{"trade": {"status": "closed"}}, {"trade": {"order_package_id": "pkg-other"}},
                                  {"true": ("open", None)}, {"false": ("closed", "sl")}, {"trade": {"position_size": 40.0}}])
def test_a_row_that_moved_is_refused(tmp_path, over):
    db = _db(tmp_path, **over)
    assert R.main(["--db", db, "--venue", _venue(tmp_path), "--apply"]) == 2


def test_unreadable_venue_payload_refuses(tmp_path):
    db = _db(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert R.main(["--db", db, "--venue", str(bad), "--apply"]) == 2
