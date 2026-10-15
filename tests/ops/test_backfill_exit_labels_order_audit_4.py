"""ORDER-AUDIT-4 — backfill_exit_labels.py, the two new populations.

PI-20261015-PD85QJEZ-0002: real-money `sl_cross` closes 6565/6566/6593/6594
carried NO `exit_reason_source` while their OWN `sl_order_id` filled the whole
position 45-53 s before the monitor wrote the close (venue fills store). Rule 0
(venue order identity) now relabels such an UNSOURCED verdict row `sl`
(`venue_bracket_order`), and only that: a verdict close the monitor sent ends
on the monitor's own order and is left alone, and a `strategy_verdict` source
is never touched.

PI-20261015-PD85QJEZ-0003: `intent_reduce_executed` audit rows carried no
`exit_reason_source`; they are stamped `intent_reduce_order`, reason unchanged.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

from src.runtime import provenance as P
from tests.fixtures.real_schema_db import insert_trade, make_canonical_db

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ops/backfill_exit_labels.py"
_SL = "71c1cc1e-2289-4f63-90fa-d9f4fea2d598"   # trade 6565's real sl_order_id
_TP = "f68fde6d-0dc3-4f4f-b07c-5732fad29fc4"


def _mod():
    spec = importlib.util.spec_from_file_location("bfx_oa4", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _fills(path: Path, rows):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE exchange_fills (account_id TEXT, side TEXT, "
              "exec_time TEXT, order_id TEXT, qty REAL, symbol TEXT)")
    c.executemany("INSERT INTO exchange_fills VALUES (?,?,?,?,?,?)", rows)
    c.commit()
    return c


def _verdict_row(db, notes, reason="sl_cross", **kw):
    base = dict(timestamp="2026-10-12T10:00:00+00:00",
                status="closed", is_backtest=0, account_id="bybit_2",
                symbol="ADAUSDT", direction="long", position_size=548.0,
                entry_price=0.25,
                exit_reason=reason, exit_price=0.2432, stop_loss=0.2433,
                take_profit_1=0.30, sl_order_id=_SL, tp_order_id=_TP,
                created_at="2026-10-12T10:00:00+00:00",
                closed_at="2026-10-12T14:38:33.411000+00:00",
                notes=json.dumps(notes))
    base.update(kw)
    return insert_trade(db, **base)


def _plan(tmp_path, fill_rows, *rows):
    db = make_canonical_db(tmp_path / "j.db")
    ids = [_verdict_row(db, **r) for r in rows]
    fc = _fills(tmp_path / "f.db", fill_rows)
    m = _mod()
    conn = sqlite3.connect(db)
    planned, stats = m.plan(conn, fc)
    return m, conn, ids, planned, stats


# The venue's own stop filled the whole position 53 s before the monitor wrote.
_OWN_SL_FILL = [("bybit_2", "sell", "2026-10-12T14:37:40+00:00", _SL, 548.0, "ADAUSDT")]
# The monitor's own market close was the closing fill.
_MONITOR_FILL = [("bybit_2", "sell", "2026-10-12T14:38:33+00:00", "mon-1", 548.0, "ADAUSDT")]


def test_unsourced_sl_cross_closed_by_its_own_stop_is_relabelled(tmp_path):
    m, conn, (rid,), planned, stats = _plan(
        tmp_path, _OWN_SL_FILL, {"notes": {"exit_price_source": "bybit_closed_pnl"}})
    rel = [p for p in planned if p["id"] == rid]
    assert rel and rel[0]["action"] == "relabel" and rel[0]["new_reason"] == "sl"
    assert stats["relabel_verdict_sl_cross_to_sl_order_id"] == 1
    assert m.apply(conn, planned) == 1
    reason, notes = conn.execute(
        "SELECT exit_reason, notes FROM trades WHERE id=?", (rid,)).fetchone()
    n = json.loads(notes)
    assert reason == "sl"
    assert n["exit_reason_source"] == "venue_bracket_order"
    assert n["pre_backfill_exit_reason"] == "sl_cross"
    assert n["exit_price_source"] == "bybit_closed_pnl"   # nothing else changed
    # idempotent: a second plan finds nothing to relabel
    planned2, _ = m.plan(conn, _fills(tmp_path / "f2.db", _OWN_SL_FILL))
    assert not [p for p in planned2 if p["id"] == rid]


def test_venue_flat_marker_row_is_relabelled(tmp_path):
    _m, _c, (rid,), planned, _s = _plan(
        tmp_path, _OWN_SL_FILL,
        {"notes": {"exit_reason_source": P.EXIT_LABEL_VERDICT_VENUE_FLAT}})
    assert [p["new_reason"] for p in planned if p["id"] == rid] == ["sl"]


def test_monitor_sent_close_is_never_relabelled(tmp_path):
    """The control: the closing fill is the MONITOR's order, not the stop."""
    _m, _c, (rid,), planned, stats = _plan(tmp_path, _MONITOR_FILL, {"notes": {}})
    assert not [p for p in planned if p["id"] == rid]
    assert stats["verdict_unsourced_no_bracket_fill"] == 1


def test_strategy_verdict_source_is_never_relabelled(tmp_path):
    _m, _c, (rid,), planned, _s = _plan(
        tmp_path, _OWN_SL_FILL, {"notes": {"exit_reason_source": "strategy_verdict"}})
    assert not [p for p in planned if p["id"] == rid]


def test_concurrent_change_wins_over_the_plan(tmp_path):
    m, conn, (rid,), planned, _s = _plan(tmp_path, _OWN_SL_FILL, {"notes": {}})
    conn.execute("UPDATE trades SET notes=? WHERE id=?",
                 (json.dumps({"closed_by_operator": True}), rid))
    conn.commit()
    assert m.apply(conn, planned) == 0
    assert conn.execute("SELECT exit_reason FROM trades WHERE id=?",
                        (rid,)).fetchone()[0] == "sl_cross"


def test_intent_reduce_row_is_stamped_and_nothing_else_changes(tmp_path):
    m, conn, (rid, done), planned, stats = _plan(
        tmp_path, [],
        {"notes": {"intent_reduce": True}, "reason": "intent_reduce_executed",
         "setup_type": "intent_reduce", "pnl": None},
        {"notes": {"intent_reduce": True, "exit_reason_source": "intent_reduce_order"},
         "reason": "intent_reduce_executed", "setup_type": "intent_reduce"})
    assert stats["stamp_intent_reduce_source"] == 1
    assert stats["intent_reduce_already_sourced"] == 1
    assert m.apply(conn, planned) == 1
    reason, notes, pnl = conn.execute(
        "SELECT exit_reason, notes, pnl FROM trades WHERE id=?", (rid,)).fetchone()
    n = json.loads(notes)
    assert reason == "intent_reduce_executed" and pnl is None
    assert n["exit_reason_source"] == "intent_reduce_order"
    assert "pre_backfill_exit_reason" not in n
    assert "exit_reason_price_basis" not in n


def test_intent_reduce_source_is_registered_and_matches_the_writer():
    assert P.classify("intent_reduce_order", "exit_reason_source") == P.ESTIMATED
    src = (Path(__file__).resolve().parents[2]
           / "src/units/accounts/execute.py").read_text()
    assert ('audit_notes.setdefault("exit_reason_source", "intent_reduce_order")'
            in src)
    assert _mod().INTENT_REDUCE_LABEL_SOURCE == "intent_reduce_order"
