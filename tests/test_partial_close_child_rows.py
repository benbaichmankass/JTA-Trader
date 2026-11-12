"""PARTIAL-CLOSE-PNL-NOT-JOURNALED + DEMO-EXIT-FIRST-FILL-ATTRIBUTION.

Reproduces pkg-633f05fad1ee4c1d (trend_donchian_xrp_4h, short), from the venue order history
read 2026-11-12:
  * bybit_portfolio entry ceb9758e Sell 32478.5 @ 1.1103 (2026-11-09T00:02:40Z)
  * live-review 50% partial close 9178f2b1 Buy 16239.2 @ 1.0836 (2026-11-09T10:52:17Z)
  * the row's own stop bd8d3a72 Buy 16239.3 @ 1.0629 (2026-11-10T18:28:14Z)
The journal booked the closed half nowhere and priced row 6983's remaining half at 1.0836.
Times below are offsets from now (the sweeps keep a recent window); prices and sizes are live.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

import pytest

from src.runtime import order_monitor as om
from src.runtime import partial_close_journal as pcj
from src.runtime import provenance as prov
from src.utils.json_notes import _DEFAULT_PROTECTED

ENTRY = 1.1103
FULL = 32478.5
PARTIAL = 16239.2
REMAIN = 16239.3


def _iso(t):
    return t.isoformat()


class _DB:
    def __init__(self, path):
        self.path = path

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def insert_trade(self, row):
        c = sqlite3.connect(self.path)
        cols = ", ".join(row)
        cur = c.execute(f"INSERT INTO trades ({cols}) VALUES ({', '.join('?' for _ in row)})",
                        list(row.values()))
        c.commit()
        rid = cur.lastrowid
        c.close()
        return rid

    def update_trade(self, tid, upd):
        c = sqlite3.connect(self.path)
        c.execute(f"UPDATE trades SET {', '.join(f'{k} = ?' for k in upd)} WHERE id = ?",
                  [*upd.values(), int(tid)])
        c.commit()
        c.close()
        return 1


@pytest.fixture
def times():
    now = _dt.datetime.now(_dt.timezone.utc)
    return {"open": now - _dt.timedelta(hours=40), "partial": now - _dt.timedelta(hours=30),
            "stop": now - _dt.timedelta(hours=2)}


def _journal(tmp_path, times, *, size=REMAIN, status="closed", exit_price=None,
             exit_reason="sl", notes=None):
    path = tmp_path / "j.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT, direction TEXT, "
        "entry_price REAL, stop_loss REAL, take_profit_1 REAL, exit_price REAL, position_size REAL, "
        "pnl REAL, pnl_percent REAL, setup_type TEXT, entry_reason TEXT, exit_reason TEXT, "
        "status TEXT, created_at TEXT, closed_at TEXT, is_backtest INTEGER, account_class TEXT, "
        "is_demo INTEGER, strategy_name TEXT, account_id TEXT, notes TEXT, order_package_id TEXT, "
        "broker_order_id TEXT, sl_order_id TEXT, tp_order_id TEXT)")
    c.execute(
        "INSERT INTO trades (id, symbol, direction, entry_price, stop_loss, take_profit_1, exit_price, "
        "position_size, setup_type, exit_reason, status, created_at, closed_at, is_backtest, "
        "account_class, is_demo, strategy_name, account_id, notes, order_package_id, broker_order_id, "
        "sl_order_id, tp_order_id) VALUES (6983,'XRPUSDT','short',?,1.0629,1.0271,?,?,"
        "'trend_donchian_xrp_4h',?,?,?,?,0,'paper',1,'trend_donchian_xrp_4h','bybit_portfolio',?,"
        "'pkg-633f05fad1ee4c1d','ceb9758e','bd8d3a72','322121a9')",
        (ENTRY, exit_price, size, exit_reason, status, _iso(times["open"]),
         _iso(times["stop"]) if status == "closed" else None,
         notes or json.dumps({"closed_by": "netting_own_leg_fill",
                              "exit_reason_source": "venue_bracket_order"})))
    c.commit()
    c.close()
    return _DB(path)


def _fills(tmp_path, times):
    path = tmp_path / "f.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE exchange_fills (exec_id TEXT PRIMARY KEY, account_id TEXT, symbol TEXT, "
        "side TEXT, price REAL, qty REAL, fee REAL, fee_currency TEXT, exec_time TEXT, "
        "order_id TEXT, is_maker INTEGER, raw TEXT, inserted_at TEXT)")
    for i, (side, px, qty, t, oid) in enumerate([
            ("sell", ENTRY, FULL, times["open"], "ceb9758e"),
            ("buy", 1.0836, PARTIAL, times["partial"], "9178f2b1"),
            ("buy", 1.0629, REMAIN, times["stop"], "bd8d3a72")]):
        c.execute("INSERT INTO exchange_fills VALUES (?,?,?,?,?,?,0,'USDT',?,?,0,NULL,NULL)",
                  (f"e{i}", "bybit_portfolio", "XRPUSDT", side, px, qty, _iso(t), oid))
    c.commit()
    c.close()
    return path


def _row(db, tid):
    c = db.connect()
    r = dict(c.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone())
    c.close()
    return r, json.loads(r["notes"] or "{}")


# ── the child row ────────────────────────────────────────────────────────────

def test_partial_close_books_a_child_row_with_its_own_fill_and_pnl(tmp_path, times):
    db = _journal(tmp_path, times, size=FULL, status="open", exit_reason=None)
    out = pcj.book_partial_close(
        db, parent_trade_id=6983, qty=PARTIAL, fill_price=1.0836,
        filled_at=_iso(times["partial"]), close_order_id="9178f2b1",
        source="live_review_apply", reason="live_review_partial_close",
        shrink_parent=True, review_id="LR-20261109T0828Z-pkg-633f05fad1ee4c1d")
    assert out["state"] == pcj.STATE_BOOKED
    assert out["parent_size_after"] == pytest.approx(REMAIN)
    child, n = _row(db, out["child_id"])
    assert child["setup_type"] == "partial_close" and child["status"] == "closed"
    assert child["position_size"] == PARTIAL and child["exit_price"] == 1.0836
    assert child["pnl"] == pytest.approx((ENTRY - 1.0836) * PARTIAL)  # +433.59, short
    assert child["order_package_id"] == "pkg-633f05fad1ee4c1d"
    assert child["broker_order_id"] == "9178f2b1"
    assert n["parent_trade_id"] == 6983 and n["partial_close_state"] == "booked"
    assert prov.classify(n["exit_price_source"], "exit_price_source") == prov.MEASURED
    parent, _ = _row(db, 6983)
    assert parent["position_size"] == pytest.approx(REMAIN)


def test_the_same_close_order_is_booked_once(tmp_path, times):
    db = _journal(tmp_path, times, size=FULL, status="open", exit_reason=None)
    kw = dict(parent_trade_id=6983, qty=PARTIAL, fill_price=1.0836, filled_at=None,
              close_order_id="9178f2b1", source="live_review_apply", reason="r", shrink_parent=True)
    first = pcj.book_partial_close(db, **kw)
    again = pcj.book_partial_close(db, **kw)
    assert again["state"] == pcj.STATE_DUPLICATE and again["child_id"] == first["child_id"]
    parent, _ = _row(db, 6983)
    assert parent["position_size"] == pytest.approx(REMAIN), "a repeat must not shrink twice"


def test_unread_fill_is_booked_pending_then_settled_from_the_fills_store(tmp_path, times):
    db = _journal(tmp_path, times, size=FULL, status="open", exit_reason=None)
    fpath = _fills(tmp_path, times)
    out = pcj.book_partial_close(db, parent_trade_id=6983, qty=PARTIAL, fill_price=None,
                                 filled_at=_iso(times["partial"]), close_order_id="9178f2b1",
                                 source="monitor_verdict_partial", reason="partial_close")
    assert out["state"] == pcj.STATE_PENDING
    child, n = _row(db, out["child_id"])
    assert child["pnl"] is None and n["partial_close_state"] == "pending_fill"
    s = pcj.settle_pending_children(db, fills_conn_factory=lambda: sqlite3.connect(fpath))
    assert s["settled"] == 1
    child, n = _row(db, out["child_id"])
    assert child["exit_price"] == pytest.approx(1.0836)
    assert child["pnl"] == pytest.approx((ENTRY - 1.0836) * PARTIAL)
    assert n["exit_price_source"] == "exchange_fill" and n["partial_close_state"] == "booked"


def test_child_link_keys_survive_the_notes_cap():
    for k in ("parent_trade_id", "partial_close_source", "partial_close_state"):
        assert k in _DEFAULT_PROTECTED


def test_child_rows_are_skipped_by_both_pnl_sweeps(tmp_path, times):
    db = _journal(tmp_path, times, size=FULL, status="open", exit_reason=None)
    pcj.book_partial_close(db, parent_trade_id=6983, qty=PARTIAL, fill_price=None, filled_at=None,
                           close_order_id="9178f2b1", source="s", reason="r")
    c = db.connect()
    pending = c.execute("SELECT COUNT(*) FROM trades WHERE setup_type='partial_close' "
                        "AND pnl IS NULL").fetchone()[0]
    c.close()
    assert pending == 1
    for sweep in (om._sweep_pending_pnl_from_bybit, om._sweep_local_pnl_for_unpriced):
        assert sweep(db)["scanned"] == 0, f"{sweep.__name__} must not price a child row"


# ── the parent's remainder is priced from its own leg ─────────────────────────

def test_demo_row_is_priced_from_its_own_stop_not_the_partial_close_fill(tmp_path, times, monkeypatch):
    db = _journal(tmp_path, times)
    fpath = _fills(tmp_path, times)
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(fpath))
    cfg = {"account_id": "bybit_portfolio", "exchange": "bybit", "demo": True}
    opened_ms = om._isoformat_to_ms(_iso(times["open"]))
    rec = om._own_leg_exit_for_demo_row(db, cfg, {"id": 6983, "account_id": "bybit_portfolio",
                                                  "symbol": "XRPUSDT", "direction": "short",
                                                  "position_size": REMAIN}, opened_ms)
    assert rec is not None and rec["match"] == "own_bracket_order"
    assert rec["avg_exit_price"] == pytest.approx(1.0629)
    # The defect, pinned: the cumulative first-fill read (what the demo branch used)
    # takes the partial close's 1.0836.
    from src.runtime.fills_pnl import exit_from_fills
    old = exit_from_fills(account_id="bybit_portfolio", symbol="XRPUSDT", direction="short",
                          opened_at_ms=opened_ms, closed_at_ms=None, qty=REMAIN)
    assert old["avg_exit_price"] == pytest.approx(1.0836)


def test_real_money_rows_never_take_the_demo_own_leg_read(tmp_path, times, monkeypatch):
    db = _journal(tmp_path, times)
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(_fills(tmp_path, times)))
    cfg = {"account_id": "bybit_2", "exchange": "bybit", "demo": False}
    assert om._own_leg_exit_for_demo_row(
        db, cfg, {"id": 6983, "account_id": "bybit_portfolio", "symbol": "XRPUSDT",
                  "direction": "short", "position_size": REMAIN},
        om._isoformat_to_ms(_iso(times["open"]))) is None


def test_pending_sweep_writes_the_own_stop_price_for_6983(tmp_path, times, monkeypatch):
    db = _journal(tmp_path, times)
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(_fills(tmp_path, times)))
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile", lambda: {
        "bybit_portfolio": {"account_id": "bybit_portfolio", "exchange": "bybit", "demo": True}})
    om._sweep_pending_pnl_from_bybit(db)   # demo: writes the measured exit price
    r, n = _row(db, 6983)
    assert r["exit_price"] == pytest.approx(1.0629)
    assert n["exit_price_source"] == "exchange_fill"
    om._sweep_local_pnl_for_unpriced(db)   # then the local sweep books pnl from it (tick order)
    r, n = _row(db, 6983)
    assert r["pnl"] == pytest.approx((ENTRY - 1.0629) * REMAIN, rel=1e-6)


# ── the live-review reduce books the child ───────────────────────────────────

def test_live_review_reduce_books_a_child_from_the_reduce_orders_fill(tmp_path, times, monkeypatch):
    from scripts.ops import live_review_apply as lra

    db = _journal(tmp_path, times, size=REMAIN, status="open", exit_reason=None)
    monkeypatch.setattr(om, "_capture_fill_details",
                        lambda t, oid: {"avg_price": 1.0836, "filled_qty": PARTIAL})

    class _I:
        review_id = "LR-20261109T0828Z-pkg-633f05fad1ee4c1d"

    out = lra._book_reduce_child(db, {"id": 6983}, _I(), qty=PARTIAL,
                                 sent={"ok": True, "exchange_order_id": "9178f2b1"},
                                 reason="live_review_partial_close")
    assert out["state"] == pcj.STATE_BOOKED
    child, n = _row(db, out["child_id"])
    assert child["exit_price"] == 1.0836 and n["review_id"].startswith("LR-20261109T0828Z")
    parent, _ = _row(db, 6983)
    assert parent["position_size"] == REMAIN, "the apply path shrinks the parent itself"


def test_ml_entry_monitor_does_not_count_a_child_as_a_second_decision():
    from src.runtime.ml_entry_live_monitor import _is_entry
    assert _is_entry({"strategy_name": "ml_entry", "setup_type": "ml_entry"})
    assert not _is_entry({"strategy_name": "ml_entry", "setup_type": "partial_close"})
