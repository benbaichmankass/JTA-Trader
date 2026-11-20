"""PI-20261118-JFWRQYOV-0004: reopen rows closed before their entries filled, driven by a committed spec.

Covers the two real specs (alpaca_portfolio SLV: 7 reopen + 1 phantom; alpaca_paper QQQ: 4 reopen + 1
already-open row = 1981) and every refusal.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import reopen_filled_closed_rows as r  # noqa: E402

SPECS = Path(__file__).resolve().parents[1] / "comms" / "ops" / "reopen_specs"


def _spec(name):
    return json.loads((SPECS / name).read_text())


def _db(tmp_path, spec, phantom_order=None):
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, direction TEXT, "
              "position_size REAL, status TEXT, exit_reason TEXT, broker_order_id TEXT, entry_price REAL, "
              "closed_at TEXT, notes TEXT, order_package_id TEXT, reconcile_status TEXT, pnl REAL)")
    c.execute("CREATE TABLE order_packages (order_package_id TEXT PRIMARY KEY, status TEXT, close_reason TEXT, "
              "meta TEXT, updated_at TEXT)")
    a, s, d = spec["account"], spec["symbol"], spec["direction"]
    for e in spec["reopen"]:
        c.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (e["id"], a, s, d, e["size"], "closed", r.REOPEN_FROM_EXIT, e["broker_order_id"], 1.0,
                   "2026-11-18T13:10:21", None, f"pkg-{e['id']}", None, None))
        c.execute("INSERT INTO order_packages VALUES (?,?,?,?,?)",
                  (f"pkg-{e['id']}", "closed", "exchange_flat_reconciled", None, "t"))
    for e in spec["keep_open"]:
        c.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (e["id"], a, s, d, e["size"], "open", None, e["broker_order_id"], 1.0, None, None,
                   f"pkg-{e['id']}", None, None))
    for e in spec["phantom"]:
        c.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (e["id"], a, s, d, e["size"], "open", None, phantom_order, 41.21, None, None, "pkg-x",
                   "reconciled", None))
    c.commit()
    c.close()
    return p


def _orders(spec, **over):
    side = "sell" if spec["direction"] == "short" else "buy"
    out = []
    for k in ("reopen", "keep_open"):
        for e in spec[k]:
            o = {"order_id": e["broker_order_id"], "status": "filled", "side": side,
                 "filled_qty": e["size"], "filled_avg_price": 661.5}
            o.update(over)
            out.append(o)
    return out


def _by_id(spec, extra=None, **over):
    by = {o["order_id"]: {"read_state": "order_read", "order": o} for o in _orders(spec, **over)}
    by.update(extra or {})
    return {"read_state": "orders_read", "result": {"list_state": "not_requested", "orders": None, "by_id": by}}


def _list(spec, **over):
    return {"read_state": "orders_read", "result": {"orders": _orders(spec, **over)}}


def _positions(spec, size=None, read_state="ok"):
    return {"accounts": [{"account_id": spec["account"], "read_state": read_state,
                          "positions": [{"symbol": spec["symbol"], "side": spec["direction"],
                                         "size": spec["venue_qty"] if size is None else size}]}]}


def _run(tmp_path, db, spec, history, positions, *extra):
    h, p, sp = tmp_path / "h.json", tmp_path / "p.json", tmp_path / "spec.json"
    h.write_text(json.dumps(history))
    p.write_text(json.dumps(positions))
    sp.write_text(json.dumps(spec))
    return r.main(["--db", str(db), "--account", spec["account"], "--symbol", spec["symbol"],
                   "--spec", str(sp), "--order-history", str(h), "--positions", str(p), *extra])


def _status(db):
    c = sqlite3.connect(db)
    out = {i: s for i, s in c.execute("SELECT id, status FROM trades")}
    pk = {i: s for i, s in c.execute("SELECT order_package_id, status FROM order_packages")}
    c.close()
    return out, pk


# ── the committed specs ───────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["alpaca_portfolio__SLV.json", "alpaca_paper__QQQ.json"])
def test_committed_specs_validate_and_sum_to_the_venue(name):
    spec = r.load_spec(_spec(name))
    counted = sum(e["size"] for k in ("reopen", "keep_open") for e in spec[k])
    assert counted == spec["venue_qty"]
    assert name == f"{spec['account']}__{spec['symbol']}.json"


def test_qqq_spec_is_the_measured_1981():
    spec = r.load_spec(_spec("alpaca_paper__QQQ.json"))
    assert [e["size"] for e in spec["reopen"]] == [1182, 735, 55, 7]
    assert [e["size"] for e in spec["keep_open"]] == [2]
    assert spec["venue_qty"] == 1981 == 1182 + 735 + 55 + 7 + 2


# ── SLV shape: reopen + phantom ───────────────────────────────────────────────


def test_slv_dry_run_plans_and_writes_nothing(tmp_path, capsys):
    spec = _spec("alpaca_portfolio__SLV.json")
    db = _db(tmp_path, spec)
    assert _run(tmp_path, db, spec, _list(spec), _positions(spec)) == 0
    assert "DRY RUN" in capsys.readouterr().out
    rows, _ = _status(db)
    assert all(rows[e["id"]] == "closed" for e in spec["reopen"]) and rows[7784] == "open"


def test_slv_apply_reopens_closes_the_phantom_and_keeps_priors(tmp_path):
    spec = _spec("alpaca_portfolio__SLV.json")
    db = _db(tmp_path, spec)
    assert _run(tmp_path, db, spec, _list(spec), _positions(spec), "--apply") == 0
    rows, pk = _status(db)
    assert all(rows[e["id"]] == "open" for e in spec["reopen"]) and rows[7784] == "closed"
    assert all(pk[f"pkg-{e['id']}"] == "open" for e in spec["reopen"])
    c = sqlite3.connect(db)
    notes, ep = c.execute("SELECT notes, entry_price FROM trades WHERE id=7750").fetchone()
    assert json.loads(notes)["reopen_repair"]["prior"]["exit_reason"] == r.REOPEN_FROM_EXIT and ep == 661.5
    er, rs, pnl = c.execute("SELECT exit_reason, reconcile_status, pnl FROM trades WHERE id=7784").fetchone()
    assert (er, rs, pnl) == ("never_filled_phantom", "superseded", None)
    assert list(tmp_path.glob("j.db.bak-reopen-*"))
    # a second run refuses: the signatures no longer match (idempotent by refusal)
    assert _run(tmp_path, db, spec, _list(spec), _positions(spec), "--apply") == 3


# ── QQQ shape: reopen + keep_open, by-id payload ─────────────────────────────


def test_qqq_apply_reopens_four_and_leaves_the_open_row_alone(tmp_path):
    spec = _spec("alpaca_paper__QQQ.json")
    db = _db(tmp_path, spec)
    assert _run(tmp_path, db, spec, _by_id(spec), _positions(spec), "--apply") == 0
    rows, pk = _status(db)
    assert {i: rows[i] for i in (7712, 7780, 7781, 7782, 7783)} == {i: "open" for i in (7712, 7780, 7781, 7782, 7783)}
    c = sqlite3.connect(db)
    assert c.execute("SELECT notes FROM trades WHERE id=7783").fetchone()[0] is None  # never written


def test_print_lookup_lists_the_spec_orders_and_a_phantoms_own_order(tmp_path, capsys):
    spec = _spec("alpaca_portfolio__SLV.json")
    db = _db(tmp_path, spec, phantom_order="ph-0001")
    sp = tmp_path / "spec.json"
    sp.write_text(json.dumps(spec))
    assert r.main(["--db", str(db), "--account", spec["account"], "--symbol", "SLV", "--spec", str(sp),
                   "--print-lookup"]) == 0
    ids = capsys.readouterr().out.strip().split(",")
    assert ids[-1] == "ph-0001" and len(ids) == 8


# ── refusals ─────────────────────────────────────────────────────────────────


def test_refuses_when_the_venue_moved_or_could_not_look(tmp_path):
    spec = _spec("alpaca_paper__QQQ.json")
    db = _db(tmp_path, spec)
    assert _run(tmp_path, db, spec, _by_id(spec), _positions(spec, size=1979), "--apply") == 3
    assert _run(tmp_path, db, spec, _by_id(spec), _positions(spec, read_state="error"), "--apply") == 3
    assert _run(tmp_path, db, spec, _by_id(spec), {"accounts": []}, "--apply") == 3
    assert _status(db)[0][7712] == "closed"


def test_refuses_an_order_that_did_not_fill_is_the_wrong_side_or_unreadable(tmp_path):
    spec = _spec("alpaca_paper__QQQ.json")
    db = _db(tmp_path, spec)
    assert _run(tmp_path, db, spec, _by_id(spec, status="canceled"), _positions(spec), "--apply") == 3
    assert _run(tmp_path, db, spec, _by_id(spec, side="buy"), _positions(spec), "--apply") == 3
    assert _run(tmp_path, db, spec, {"read_state": "error"}, _positions(spec), "--apply") == 3
    bad = _by_id(spec)
    bad["result"]["by_id"][spec["reopen"][0]["broker_order_id"]] = {"read_state": "could_not_look"}
    assert _run(tmp_path, db, spec, bad, _positions(spec), "--apply") == 3
    missing = _by_id(spec)
    missing["result"]["by_id"][spec["reopen"][0]["broker_order_id"]] = {"read_state": "not_found"}
    assert _run(tmp_path, db, spec, missing, _positions(spec), "--apply") == 3
    assert _status(db)[0][7712] == "closed"


def test_refuses_a_row_whose_signature_moved(tmp_path):
    spec = _spec("alpaca_paper__QQQ.json")
    db = _db(tmp_path, spec)
    c = sqlite3.connect(db)
    c.execute("UPDATE trades SET position_size=1180 WHERE id=7712")
    c.commit()
    c.close()
    assert _run(tmp_path, db, spec, _by_id(spec), _positions(spec), "--apply") == 3
    assert _status(db)[0][7780] == "closed"


def test_refuses_a_phantom_that_has_a_venue_order_or_was_not_looked_up(tmp_path):
    spec = _spec("alpaca_portfolio__SLV.json")
    db = _db(tmp_path, spec, phantom_order="ph-0001")
    found = _by_id(spec, extra={"ph-0001": {"read_state": "order_read", "order": {"order_id": "ph-0001"}}})
    assert _run(tmp_path, db, spec, found, _positions(spec), "--apply") == 3
    assert _run(tmp_path, db, spec, _by_id(spec), _positions(spec), "--apply") == 3  # never looked up
    gone = _by_id(spec, extra={"ph-0001": {"read_state": "not_found"}})
    assert _run(tmp_path, db, spec, gone, _positions(spec)) == 0  # looked up, absent: a real phantom


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(venue_qty=1980),                       # sizes no longer sum
    lambda s: s.update(direction="sideways"),
    lambda s: s["reopen"].append(dict(s["reopen"][0])),       # a row listed twice
    lambda s: s["reopen"][0].pop("broker_order_id"),
    lambda s: s.update(account="alpaca_live"),                # not the account asked for
])
def test_refuses_a_malformed_or_mismatched_spec(tmp_path, mutate):
    spec = _spec("alpaca_paper__QQQ.json")
    db = _db(tmp_path, spec)
    bad = json.loads(json.dumps(spec))
    mutate(bad)
    h, p, sp = tmp_path / "h.json", tmp_path / "p.json", tmp_path / "spec.json"
    h.write_text(json.dumps(_by_id(spec)))
    p.write_text(json.dumps(_positions(spec)))
    sp.write_text(json.dumps(bad))
    assert r.main(["--db", str(db), "--account", "alpaca_paper", "--symbol", "QQQ", "--spec", str(sp),
                   "--order-history", str(h), "--positions", str(p), "--apply"]) == 3
    assert _status(db)[0][7712] == "closed"


def test_apply_waits_for_the_traders_write_lock(tmp_path):
    """2026-11-19 run 44513698892: the apply lost a 5 s race for the live journal's write lock and rolled back.
    A lock held longer than sqlite's 5 s default, then released, must now be waited out and the apply land."""
    import sqlite3
    import threading
    import time
    spec = _spec("alpaca_paper__QQQ.json")
    db = _db(tmp_path, spec)
    holder = sqlite3.connect(db, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")                       # the trader mid-write
    t = threading.Timer(6.0, holder.rollback)               # past sqlite3's 5 s default, well inside 60 s
    t.start()
    t0 = time.monotonic()
    try:
        assert _run(tmp_path, db, spec, _by_id(spec), _positions(spec), "--apply") == 0
    finally:
        t.join()
        holder.close()
    assert time.monotonic() - t0 >= 5.5, "it really waited on the held lock"
    rows, _pk = _status(db)
    assert {i: rows[i] for i in (7712, 7780, 7781, 7782, 7783)} == {i: "open" for i in (7712, 7780, 7781, 7782, 7783)}


def test_backup_names_are_seen_by_the_shared_retention(tmp_path):
    """PI-20261120-CGNCTD2Z-0005: both whole-journal writers go through journal_backup.take_backup,
    so their copies carry a stamp the total-retention prune recognises (and are capped at 2)."""
    import sqlite3 as _sq
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
    from scripts.ops import backfill_partial_close_children as bp
    from scripts.ops import journal_backup as jb
    db = tmp_path / "j.db"
    _sq.connect(db).execute("CREATE TABLE t (x)").connection.commit()
    for name in ("j.db.bak-reopen-20261119T112300Z", "j.db.bak-other-20261118T000000Z",
                 "j.db.bak-third-20261117T000000Z"):
        (tmp_path / name).write_bytes(b"x")
    fresh = bp._backup(str(db))
    left = sorted(p.name for p in tmp_path.glob("j.db.bak-*"))
    assert _P(fresh).name in left and len(left) == jb.KEEP_TOTAL, left
    assert _P(fresh).name.startswith("j.db.bak-partial-close-")
