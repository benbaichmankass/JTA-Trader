"""ENTRY-UNFILLED-LABEL (2026-11-19, manager decision; row VENUE-FLAT-PENDING-ENTRY-LABELS).

alpaca_options_paper SLV trade 8034 had a DAY mleg limit entry that expired
unfilled. The position-snapshot reconciler then closed the row as
``exchange_flat_reconciled``, and mechanics_fault_intake graded that a close
fault ("no exit price; pnl or fee not recorded"). The row never held a position.

Contract under test (the manager's conditions):
1. The venue is asked about fills ONLY after ``_entry_order_hold`` found the
   entry order neither working nor unreadable, never for a pending entry or a
   placeholder id.
2. The read fails closed: anything other than "terminal, filled_qty exactly 0"
   keeps ``exchange_flat_reconciled``.
3. A filled-then-flat row is NEVER relabelled.
4. ``entry_unfilled`` is neutral to the mechanics grader, a not-strategy exit to
   close attribution, ungraded in the paper classifier, outside KPI denominators,
   and never priced by the local-PnL sweep.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import tests.test_position_snapshot_reconcile as _snap
from src.runtime import order_monitor as om
from tests.test_position_snapshot_reconcile import (
    _alpaca_row_status,
    _insert_alpaca_open_trade,
    _reconcile_orphan_exchange_positions,
)

tmp_db = _snap.tmp_db  # the snapshot-reconcile suite's journal fixture, reused as-is

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "scripts" / "ops", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _two_passes(db, *, pending, unfilled):
    with patch(
        "src.units.accounts.clients.account_open_positions", return_value=[],
    ), patch(
        "src.units.accounts.clients.account_position_present", return_value=False,
    ), patch(
        "src.units.accounts.clients.account_entry_order_pending", return_value=pending,
    ), patch(
        "src.units.accounts.clients.account_entry_order_unfilled", return_value=unfilled,
    ) as m_unfilled:
        _reconcile_orphan_exchange_positions(db)            # arms
        summary = _reconcile_orphan_exchange_positions(db)  # closes (or holds)
    return summary, m_unfilled


def _row(db):
    conn = db.connect()
    try:
        r = conn.execute(
            "SELECT status, exit_reason, pnl, notes FROM trades WHERE account_id='alpaca_live'"
        ).fetchone()
        return {"status": r[0], "exit_reason": r[1], "pnl": r[2], "notes": r[3]}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# the close path
# ---------------------------------------------------------------------------

def test_terminal_unfilled_entry_closes_as_entry_unfilled_and_is_never_priced(tmp_db):
    _insert_alpaca_open_trade(tmp_db, "10fd4469-aa72-4c9a-a893-ff5cafcc491d")
    summary, m = _two_passes(tmp_db, pending=False, unfilled=True)
    assert m.call_args.args[1] == "10fd4469-aa72-4c9a-a893-ff5cafcc491d"
    assert summary["snapshot_closed"] == 1
    assert summary["snapshot_closed_entry_unfilled"] == 1
    r = _row(tmp_db)
    assert r["status"] == "closed" and r["exit_reason"] == om.ENTRY_UNFILLED_EXIT_REASON
    assert "filled_qty 0" in r["notes"]
    swept = om._sweep_local_pnl_for_unpriced(tmp_db)
    assert swept["scanned"] == 0
    assert _row(tmp_db)["pnl"] is None


def test_filled_then_flat_row_is_never_relabelled(tmp_db):
    """The venue says the entry filled (then the position closed): keep the flat label."""
    _insert_alpaca_open_trade(tmp_db, "ord-filled-then-stopped")
    summary, m = _two_passes(tmp_db, pending=False, unfilled=False)
    assert m.called
    assert summary["snapshot_closed"] == 1 and summary["snapshot_closed_entry_unfilled"] == 0
    assert _row(tmp_db)["exit_reason"] == "exchange_flat_reconciled"


def test_unreadable_fill_state_fails_closed_to_the_flat_label(tmp_db):
    _insert_alpaca_open_trade(tmp_db, "ord-terminal-unknown-fills")
    summary, _ = _two_passes(tmp_db, pending=False, unfilled=None)
    assert summary["snapshot_closed"] == 1 and summary["snapshot_closed_entry_unfilled"] == 0
    assert _row(tmp_db)["exit_reason"] == "exchange_flat_reconciled"


def test_pending_entry_is_held_and_fills_are_never_asked(tmp_db):
    _insert_alpaca_open_trade(tmp_db, "ord-queued-1")
    summary, m = _two_passes(tmp_db, pending=True, unfilled=True)
    m.assert_not_called()
    assert summary["snapshot_closed"] == 0 and _alpaca_row_status(tmp_db) == "open"


def test_placeholder_order_id_is_never_asked(tmp_db):
    _insert_alpaca_open_trade(tmp_db, "rejected-abc123")
    summary, m = _two_passes(tmp_db, pending=False, unfilled=True)
    m.assert_not_called()
    assert _row(tmp_db)["exit_reason"] == "exchange_flat_reconciled"


def test_entry_never_filled_is_true_only_on_true():
    cfg = {"account_id": "alpaca_live", "exchange": "alpaca", "mode": "live"}
    for answer, want in ((True, True), (False, False), (None, False)):
        with patch("src.units.accounts.clients.account_entry_order_unfilled",
                   return_value=answer):
            assert om._entry_never_filled(cfg, "10fd4469-aa72") is want
    with patch("src.units.accounts.clients.account_entry_order_unfilled",
               side_effect=RuntimeError("boom")):
        assert om._entry_never_filled(cfg, "10fd4469-aa72") is False


# ---------------------------------------------------------------------------
# the venue reader
# ---------------------------------------------------------------------------

def test_alpaca_order_entry_unfilled_fails_closed():
    from src.units.accounts.alpaca_client import AlpacaClient
    cli = AlpacaClient(api_key="k", api_secret="s")

    def _env(rc, status=None, filled="__absent__"):
        res = {"status": status}
        if filled != "__absent__":
            res["filled_qty"] = filled
        return lambda method, path, json_body=None: (
            {"retCode": rc, "result": res} if rc == 0 else {"retCode": rc, "retMsg": "x"})

    cases = [
        ((0, "expired", "0"), True),
        ((0, "canceled", "0"), True),
        ((0, "cancelled", "0"), True),
        ((0, "rejected", "0"), True),
        ((0, "filled", "1"), False),
        ((0, "canceled", "0.5"), False),      # partial fill: a position existed
        ((0, "expired", "3"), False),
        ((0, "expired", None), None),         # unparseable -> ambiguous
        ((0, "expired", "__absent__"), None),
        ((0, "done_for_day", "0"), None),
        ((0, "replaced", "0"), None),
        ((0, "new", "0"), None),              # not terminal
        ((404,), None),                       # unknown order: never guess
        ((500,), None),
    ]
    for args, want in cases:
        cli._request = _env(*args)  # type: ignore[method-assign]
        assert cli.order_entry_unfilled("oid-1") is want, (args, want)
    assert cli.order_entry_unfilled("") is None


def test_clients_wrapper_needs_a_supported_account():
    from src.units.accounts import clients
    assert clients.account_entry_order_unfilled(
        {"exchange": "bybit", "mode": "live"}, "x") is None
    assert clients.account_entry_order_unfilled(
        {"exchange": "alpaca", "mode": "dry_run"}, "x") is None
    assert clients.account_entry_order_unfilled(
        {"exchange": "alpaca", "mode": "live"}, "") is None


# ---------------------------------------------------------------------------
# the readers treat it as neutral
# ---------------------------------------------------------------------------

def _unfilled_row():
    return {"id": 8034, "status": "closed", "exit_reason": "entry_unfilled",
            "account_id": "alpaca_options_paper", "strategy_name": "slv_trend_1h",
            "symbol": "SLV", "direction": "short", "entry_price": 40.22,
            "stop_loss": 40.88, "take_profit_1": 36.25, "position_size": 1.0,
            "order_package_id": "pkg-145e79054b884464",
            "closed_at": "2026-11-19T21:02:11+00:00", "pnl": None,
            "fee_taker_usd": 0.0, "is_backtest": 0, "account_class": "paper"}


def test_mechanics_grader_is_neutral_and_the_intake_files_nothing():
    import mechanics_fault_intake as mfi
    import soak_state
    from datetime import datetime, timezone
    g = soak_state.grade_trade(_unfilled_row())
    assert g["clean"] is None and g["fault"] is None
    assert mfi.candidates([_unfilled_row()], [], datetime.now(timezone.utc)) == []


def test_close_attribution_and_ml_monitor_call_it_not_a_strategy_exit():
    import real_money_close_attribution as rmca
    from src.runtime.ml_entry_live_monitor import OPERATIONAL_EXIT_REASONS
    assert rmca.bucket_for("entry_unfilled")[0] == "b_not_strategy_exit"
    assert "entry_unfilled" in OPERATIONAL_EXIT_REASONS


def test_paper_classifier_never_grades_or_reconstructs_it():
    from src.analysis.paper_record_classifier import classify_record
    c = classify_record(_unfilled_row())
    assert c.bucket == "B" and c.category == "entry_unfilled"
    assert c.gradeable is False and c.reconstructable is False


def test_kpi_predicate_drops_it_and_still_drops_reset_flat():
    import sqlite3
    from src.web.api._clean_trades import exclude_reset_flat_predicate
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE trades (id INTEGER, exit_reason TEXT)")
    con.executemany("INSERT INTO trades VALUES (?,?)", [
        (1, "entry_unfilled"), (2, "exchange_reset_flat"), (3, "sl"), (4, None)])
    kept = [r[0] for r in con.execute(
        "SELECT id FROM trades WHERE 1=1" + exclude_reset_flat_predicate("") + " ORDER BY id")]
    assert kept == [3, 4]
