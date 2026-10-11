"""PERF-FU-REDUCE-PNL: an intent_reduce leg's realised PnL is settled from fills.

The numbers in the headline test are the live case the checklist row named:
bybit_1 trade 6532 reduced 5117.3 XRP of short parent 6527 (shrunk, not closed).
Fills (diag /api/bot/pnl/exchange/fills, 2026-10-11): parent entry order vwap
1.3481, reduce order vwap 1.3893, reduce fees 3.91020569. Hand arithmetic:
(1.3481 - 1.3893) * 5117.3 = -210.83 gross, -214.74 net.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import reduce_leg_settlement as rls
from src.runtime.exchange_fills_store import init_db
from src.runtime.order_monitor import _sweep_settle_intent_reduce_legs
from src.units.db.database import Database


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(p))
    return Database(db_path=str(p))


@pytest.fixture
def fills(tmp_path, monkeypatch):
    p = tmp_path / "exchange_fills.sqlite"
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(p))
    init_db(p)

    def add(order_id, price, qty, fee=0.0, side="buy"):
        c = sqlite3.connect(str(p))
        c.execute(
            "INSERT INTO exchange_fills (exec_id, account_id, symbol, side, price,"
            " qty, fee, exec_time, order_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{order_id}-{price}-{qty}", "bybit_1", "XRP/USDT:USDT", side,
             price, qty, fee, "2026-10-09T00:00:00Z", order_id))
        c.commit()
        c.close()
    return add


def _iso(hours_ago=0.0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _parent(db, *, direction="short", size=7486.3, order="P-1", status="open"):
    return db.insert_trade({
        "timestamp": _iso(30), "symbol": "XRPUSDT", "direction": direction,
        "entry_price": 1.3464, "position_size": size, "status": status,
        "is_backtest": 0, "account_id": "bybit_1", "account_class": "paper",
        "strategy_name": "xrp_pullback_2h", "broker_order_id": order,
        "notes": json.dumps({"trade_id": order}), "created_at": _iso(30),
    })


def _reduce(db, allocs, *, order="R-1", qty=5117.3, hours_ago=1.0, direction="long",
            extra_notes=None):
    notes = {"trade_id": order, "intent_reduce": True,
             "pnl_source": "deferred_intent_reduce",
             "intent_reduce_allocations": allocs}
    if extra_notes is not None:
        notes = extra_notes
    return db.insert_trade({
        "timestamp": _iso(hours_ago), "symbol": "XRPUSDT", "direction": direction,
        "entry_price": 1.3898, "stop_loss": 1.45, "take_profit_1": 1.25,
        "position_size": qty, "setup_type": "intent_reduce",
        "exit_reason": "intent_reduce_executed", "status": "closed",
        "closed_at": _iso(hours_ago), "is_backtest": 0, "account_id": "bybit_1",
        "account_class": "paper", "strategy_name": "xrp_pullback_2h",
        "notes": json.dumps(notes), "created_at": _iso(hours_ago),
    })


def _row(db, tid):
    return db.get_trades(filters={"id": tid})[0]


def _plan(db, tid):
    conn = sqlite3.connect(db.db_path)
    try:
        cand = rls.select_candidates(conn, ids=[tid])
    finally:
        conn.close()
    f = rls.fills_by_order_from_store(cand["order_ids"])
    rows = cand["rows"]
    assert len(rows) == 1
    return rows[0], rls.plan_settlement(rows[0], cand["parents_by_id"], f)


def test_partial_consumption_books_the_reduced_units_from_two_fills(db, fills):
    pid = _parent(db)
    tid = _reduce(db, [{"parent_id": pid, "consumed": 5117.3, "closed": False,
                        "new_size": 7486.3}])
    fills("P-1", 1.3481, 12603.6, side="sell")
    fills("R-1", 1.3893, 5117.3, fee=3.91020569)
    row, plan = _plan(db, tid)
    assert plan.state == rls.SETTLED_STATE
    assert plan.gross_pnl == pytest.approx(-210.83, abs=0.01)
    assert plan.pnl == pytest.approx(-214.74, abs=0.01)
    rls.apply_settlement(db, row, plan, now_iso=_iso())
    out = _row(db, tid)
    notes = json.loads(out["notes"])
    assert out["pnl"] == pytest.approx(-214.74, abs=0.01)
    assert out["exit_price"] == pytest.approx(1.3893)
    assert notes["exit_price_source"] == "exchange_fill"  # MEASURED
    assert notes["pnl_source"] == "local_compute"
    assert notes["reduce_settlement"] == rls.SETTLED_STATE
    from src.runtime.provenance import MEASURED, classify_row
    assert classify_row(out, "exit_price_source")[0] == MEASURED
    # The parent row is never touched.
    assert _row(db, pid)["position_size"] == pytest.approx(7486.3)


def test_fully_consumed_parent_is_absorbed_not_double_counted(db, fills):
    pid = _parent(db, status="closed")
    tid = _reduce(db, [{"parent_id": pid, "consumed": 5117.3, "closed": True}])
    fills("P-1", 1.3481, 5117.3)
    fills("R-1", 1.3893, 5117.3)
    _, plan = _plan(db, tid)
    assert plan.state == rls.ABSORBED_STATE
    assert plan.pnl is None


def test_mixed_allocations_book_only_the_partial_share(db, fills):
    full = _parent(db, size=1000.0, order="P-F", status="closed")
    part = _parent(db, size=9000.0, order="P-P")
    tid = _reduce(db, [
        {"parent_id": full, "consumed": 1000.0, "closed": True},
        {"parent_id": part, "consumed": 1000.0, "closed": False},
    ], qty=2000.0)
    fills("P-F", 1.30, 1000.0)
    fills("P-P", 1.40, 10000.0)
    fills("R-1", 1.35, 2000.0, fee=2.0)
    _, plan = _plan(db, tid)
    assert plan.state == rls.SETTLED_STATE
    assert plan.reason == "partial_allocations_only"
    # short parent at 1.40, bought back at 1.35 on 1000 units = +50; fee half = 1.
    assert plan.gross_pnl == pytest.approx(50.0)
    assert plan.pnl == pytest.approx(49.0)


@pytest.mark.parametrize("case,reason", [
    ("no_reduce_fill", "no_reduce_fill_in_store"),
    ("no_parent_fill", "no_entry_fill_for_parent_"),
    ("qty_mismatch", "fill_qty_mismatch"),
])
def test_refusals_leave_pnl_null(db, fills, case, reason):
    pid = _parent(db)
    tid = _reduce(db, [{"parent_id": pid, "consumed": 5117.3, "closed": False}])
    if case != "no_parent_fill":
        fills("P-1", 1.3481, 12603.6)
    if case == "qty_mismatch":
        fills("R-1", 1.3893, 4.6)
    elif case != "no_reduce_fill":
        fills("R-1", 1.3893, 5117.3)
    _, plan = _plan(db, tid)
    assert plan.state == rls.UNVERIFIED_STATE
    assert plan.reason.startswith(reason)
    assert plan.pnl is None


def test_missing_allocations_refuse(db, fills):
    tid = _reduce(db, None, extra_notes={"trade_id": "R-1", "intent_reduce": True,
                                         "_truncated": True})
    fills("R-1", 1.3893, 5117.3)
    _, plan = _plan(db, tid)
    assert plan.state == rls.UNVERIFIED_STATE
    assert plan.reason == "no_allocations_in_notes"


def test_sweep_settles_recent_retries_fresh_refusals_and_is_idempotent(db, fills):
    pid = _parent(db)
    ok = _reduce(db, [{"parent_id": pid, "consumed": 100.0, "closed": False}],
                 order="R-OK", qty=100.0)
    fresh = _reduce(db, [{"parent_id": pid, "consumed": 50.0, "closed": False}],
                    order="R-FRESH", qty=50.0, hours_ago=0.5)
    aged = _reduce(db, [{"parent_id": pid, "consumed": 70.0, "closed": False}],
                   order="R-AGED", qty=70.0, hours_ago=30)
    old = _reduce(db, [{"parent_id": pid, "consumed": 10.0, "closed": False}],
                  order="R-OLD", qty=10.0, hours_ago=24 * 10)
    fills("P-1", 1.40, 10000.0)
    fills("R-OK", 1.35, 100.0)
    fills("R-OLD", 1.35, 10.0)
    s = _sweep_settle_intent_reduce_legs(db)
    assert s["settled"] == 1 and s["retry_later"] == 1 and s["unverified"] == 1
    assert _row(db, ok)["pnl"] == pytest.approx(5.0)
    assert _row(db, fresh)["pnl"] is None
    assert "reduce_settlement" not in json.loads(_row(db, fresh)["notes"])
    assert json.loads(_row(db, aged)["notes"])["reduce_settlement"] == "unverified"
    # Outside the 3-day window: the backfill's, not the sweep's.
    assert _row(db, old)["pnl"] is None
    assert "reduce_settlement" not in json.loads(_row(db, old)["notes"])
    s2 = _sweep_settle_intent_reduce_legs(db)
    assert s2["settled"] == 0 and s2["unverified"] == 0


def test_superseded_and_already_priced_rows_are_not_candidates(db, fills):
    pid = _parent(db)
    tid = _reduce(db, [{"parent_id": pid, "consumed": 1.0, "closed": False}], qty=1.0)
    db.update_trade(tid, {"reconcile_status": "superseded"})
    conn = sqlite3.connect(db.db_path)
    try:
        assert rls.select_candidates(conn)["rows"] == []
    finally:
        conn.close()


def test_backfill_dry_run_writes_nothing_and_apply_writes(db, fills, tmp_path, capsys):
    from scripts.ops import backfill_intent_reduce_pnl as bf
    pid = _parent(db)
    tid = _reduce(db, [{"parent_id": pid, "consumed": 100.0, "closed": False}],
                  qty=100.0, hours_ago=24 * 30)
    fills("P-1", 1.40, 10000.0)
    fills("R-1", 1.35, 100.0)
    assert bf.run(db.db_path, apply=False) == 0
    assert "net +5.00 USD" in capsys.readouterr().out
    assert _row(db, tid)["pnl"] is None
    assert bf.run(db.db_path, apply=True) == 0
    assert _row(db, tid)["pnl"] == pytest.approx(5.0)
    assert list(tmp_path.glob("trade_journal.db.bak-reduce-pnl-*"))
    assert bf.run(db.db_path, apply=True) == 0  # idempotent: no candidates left
    assert _row(db, tid)["pnl"] == pytest.approx(5.0)


def test_supersede_script_skips_settled_reduce_legs(db, fills):
    from scripts.ops import supersede_intent_reduce_phantom_pnl as sup
    pid = _parent(db)
    tid = _reduce(db, [{"parent_id": pid, "consumed": 100.0, "closed": False}],
                  qty=100.0)
    fills("P-1", 1.40, 10000.0)
    fills("R-1", 1.35, 100.0)
    row, plan = _plan(db, tid)
    rls.apply_settlement(db, row, plan, now_iso=_iso())
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert sup._candidate_rows(conn, ids=None) == []
    finally:
        conn.close()


def test_absent_fills_store_refuses_instead_of_planning_unverified(db, tmp_path, monkeypatch):
    """First VM dry-run (#17598): the wrapper shell resolved a fills path that did
    not exist, read it as 'no fills', and planned every row unverified. An absent
    store is 'we could not look' — the backfill refuses, the sweep stamps nothing."""
    from scripts.ops import backfill_intent_reduce_pnl as bf
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(tmp_path / "absent.sqlite"))
    pid = _parent(db)
    tid = _reduce(db, [{"parent_id": pid, "consumed": 1.0, "closed": False}],
                  qty=1.0, hours_ago=30)
    assert bf.run(db.db_path, apply=True) == 2
    assert bf.run(db.db_path, apply=True,
                  fills_db=str(tmp_path / "also-absent.sqlite")) == 2
    s = _sweep_settle_intent_reduce_legs(db)
    assert s["errors"] == 1 and s["unverified"] == 0
    assert "reduce_settlement" not in json.loads(_row(db, tid)["notes"])


def test_action_wrapper_passes_the_canonical_fills_path():
    from pathlib import Path
    src = Path("scripts/ops/backfill_intent_reduce_pnl_action.sh").read_text()
    assert 'FILLS_DB="$(fills_store_path)"' in src
    assert '--fills-db "${FILLS_DB}"' in src


def test_legacy_allocation_without_closed_key_is_classified_from_the_parent(db, fills):
    """Pre-`closed`-key allocations (81 of 104 live, 2026-10-11). Reading the
    absence as 'partial' double-counted 29 fully-consumed parents (e.g. 4217 ->
    4162, which already books its full 86,102.5 units): the legacy writer closed
    the parent with exit_reason=intent_reduce, at its full size, in the same call.
    """
    t = _iso(30)
    full_parent = db.insert_trade({
        "timestamp": t, "symbol": "XRPUSDT", "direction": "short",
        "entry_price": 1.40, "position_size": 1000.0, "status": "closed",
        "exit_reason": "intent_reduce", "closed_at": t, "pnl": 50.0,
        "is_backtest": 0, "account_id": "bybit_1", "broker_order_id": "P-F",
        "notes": json.dumps({"trade_id": "P-F"}), "created_at": t,
    })
    part_parent = _parent(db, size=9000.0, order="P-P")
    tid = db.insert_trade({
        "timestamp": t, "symbol": "XRPUSDT", "direction": "long",
        "entry_price": 1.35, "position_size": 2000.0, "setup_type": "intent_reduce",
        "exit_reason": "intent_reduce_executed", "status": "closed", "closed_at": t,
        "is_backtest": 0, "account_id": "bybit_1", "created_at": t,
        "notes": json.dumps({"trade_id": "R-1", "intent_reduce": True,
                             "pnl_source": "deferred_intent_reduce",
                             "intent_reduce_allocations": [
                                 {"parent_id": full_parent, "consumed": 1000.0},
                                 {"parent_id": part_parent, "consumed": 1000.0}]}),
    })
    fills("P-F", 1.40, 1000.0)
    fills("P-P", 1.40, 10000.0)
    fills("R-1", 1.35, 2000.0)
    _, plan = _plan(db, tid)
    assert plan.state == rls.SETTLED_STATE
    assert plan.consumed_full == pytest.approx(1000.0)
    assert plan.consumed_partial == pytest.approx(1000.0)
    assert plan.gross_pnl == pytest.approx(50.0)  # NOT 100: the full parent already books its 50
    assert [p["parent_id"] for p in plan.parents] == [part_parent]


def test_legacy_same_size_but_different_close_time_is_partial(db, fills):
    """Partial first, the same size later closed by ANOTHER reduce: the earlier
    reduce's allocation must stay partial (its units are not on the parent)."""
    early = _iso(40)
    pid = db.insert_trade({
        "timestamp": early, "symbol": "XRPUSDT", "direction": "short",
        "entry_price": 1.40, "position_size": 500.0, "status": "closed",
        "exit_reason": "intent_reduce", "closed_at": _iso(1), "pnl": 5.0,
        "is_backtest": 0, "account_id": "bybit_1", "broker_order_id": "P-1",
        "notes": json.dumps({"trade_id": "P-1"}), "created_at": early,
    })
    tid = _reduce(db, None, qty=500.0, hours_ago=30, extra_notes={
        "trade_id": "R-1", "intent_reduce": True,
        "intent_reduce_allocations": [{"parent_id": pid, "consumed": 500.0}]})
    fills("P-1", 1.40, 1000.0)
    fills("R-1", 1.35, 500.0)
    _, plan = _plan(db, tid)
    assert plan.state == rls.SETTLED_STATE
    assert plan.gross_pnl == pytest.approx(25.0)
