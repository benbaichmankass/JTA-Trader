"""PI-20261118-JFWRQYOV-0004: the one-off reopen of 7 SLV rows closed before their entries filled."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import reopen_filled_closed_rows as r  # noqa: E402


def _db(tmp_path):
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, direction TEXT, "
              "position_size REAL, status TEXT, exit_reason TEXT, broker_order_id TEXT, entry_price REAL, "
              "closed_at TEXT, notes TEXT, order_package_id TEXT, reconcile_status TEXT, pnl REAL)")
    c.execute("CREATE TABLE order_packages (order_package_id TEXT PRIMARY KEY, status TEXT, close_reason TEXT, "
              "meta TEXT, updated_at TEXT)")
    for rid, (size, boid) in r.REOPEN.items():
        c.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (rid, r.ACCOUNT, r.SYMBOL, r.DIRECTION, size, "closed", r.REOPEN_FROM_EXIT, boid, 41.0,
                   "2026-11-18T13:10:21", None, f"pkg-{rid}", None, None))
        c.execute("INSERT INTO order_packages VALUES (?,?,?,?,?)", (f"pkg-{rid}", "closed", "reconciler_flat", None, "t"))
    c.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (7784, r.ACCOUNT, r.SYMBOL, r.DIRECTION, 6.0, "open", None, None, 41.21, None, None, "pkg-7774",
               "reconciled", None))
    c.commit()
    c.close()
    return p


def _history(**over):
    orders = [{"order_id": boid, "status": "filled", "side": "sell", "filled_qty": size, "filled_avg_price": 41.1}
              for _, (size, boid) in r.REOPEN.items()]
    for o in orders:
        o.update(over)
    return {"read_state": "orders_read", "result": {"orders": orders}}


def _positions(size=877.0, read_state="ok"):
    return {"accounts": [{"account_id": r.ACCOUNT, "read_state": read_state,
                          "positions": [{"symbol": "SLV", "side": "short", "size": size}]}]}


def _run(tmp_path, db, history, positions, *extra):
    h, p = tmp_path / "h.json", tmp_path / "p.json"
    h.write_text(json.dumps(history))
    p.write_text(json.dumps(positions))
    return r.main(["--db", str(db), "--order-history", str(h), "--positions", str(p), *extra])


def _status(db):
    c = sqlite3.connect(db)
    out = {i: s for i, s in c.execute("SELECT id, status FROM trades")}
    pk = {i: s for i, s in c.execute("SELECT order_package_id, status FROM order_packages")}
    c.close()
    return out, pk


def test_dry_run_plans_and_writes_nothing(tmp_path, capsys):
    db = _db(tmp_path)
    assert _run(tmp_path, db, _history(), _positions()) == 0
    assert "DRY RUN" in capsys.readouterr().out
    rows, _ = _status(db)
    assert all(rows[i] == "closed" for i in r.REOPEN) and rows[7784] == "open"


def test_apply_reopens_seven_closes_the_phantom_and_keeps_priors(tmp_path):
    db = _db(tmp_path)
    assert _run(tmp_path, db, _history(), _positions(), "--apply") == 0
    rows, pk = _status(db)
    assert all(rows[i] == "open" for i in r.REOPEN) and rows[7784] == "closed"
    assert all(pk[f"pkg-{i}"] == "open" for i in r.REOPEN)
    c = sqlite3.connect(db)
    notes, ep, rs = c.execute("SELECT notes, entry_price, reconcile_status FROM trades WHERE id=7750").fetchone()
    assert json.loads(notes)["reopen_repair"]["prior"]["exit_reason"] == r.REOPEN_FROM_EXIT and ep == 41.1
    er, rs, pnl = c.execute("SELECT exit_reason, reconcile_status, pnl FROM trades WHERE id=7784").fetchone()
    assert (er, rs, pnl) == ("never_filled_phantom", "superseded", None)
    assert list(tmp_path.glob("j.db.bak-reopen-*"))
    # a second run refuses: the signatures no longer match (idempotent by refusal)
    assert _run(tmp_path, db, _history(), _positions(), "--apply") == 3


def test_refuses_when_the_venue_moved(tmp_path):
    db = _db(tmp_path)
    assert _run(tmp_path, db, _history(), _positions(size=871.0), "--apply") == 3
    assert _run(tmp_path, db, _history(), _positions(read_state="error"), "--apply") == 3
    assert _status(db)[0][7750] == "closed"


def test_refuses_an_order_that_did_not_fill_or_is_not_a_sell(tmp_path):
    db = _db(tmp_path)
    assert _run(tmp_path, db, _history(status="canceled"), _positions(), "--apply") == 3
    assert _run(tmp_path, db, _history(side="buy"), _positions(), "--apply") == 3
    assert _run(tmp_path, db, {"read_state": "error"}, _positions(), "--apply") == 3
    assert _status(db)[0][7750] == "closed"


def test_refuses_a_row_whose_signature_moved(tmp_path):
    db = _db(tmp_path)
    c = sqlite3.connect(db)
    c.execute("UPDATE trades SET position_size=790 WHERE id=7750")
    c.commit()
    c.close()
    assert _run(tmp_path, db, _history(), _positions(), "--apply") == 3
    assert _status(db)[0][7754] == "closed"
