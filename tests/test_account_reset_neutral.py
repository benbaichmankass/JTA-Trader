"""`account_reset` is not a strategy exit (AM-OPS-11, 2026-11-20).

`execute.journal_account_reset` closes every OTHER open alpaca_paper row with
exit_reason='account_reset' after the close ladder's rung-3 paper close-all
(`DELETE /v2/positions?cancel_orders=true`). Measured 2026-11-16 14:32:33Z: one
USO close liquidated QQQ/SLV/GDX/IAUM/SPY/USO (alpaca_order_history). Those rows
are collateral, so the readers must treat the label as neutral, like
`exchange_reset_flat` and `entry_unfilled`:
the mechanics grader (no clean, no fault), close attribution (not a strategy
exit) and the KPI predicate (outside per-strategy denominators).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for sub in ("scripts/ops", "scripts/research"):
    p = str(REPO / sub)
    if p not in sys.path:
        sys.path.insert(0, p)


def _row(reason: str) -> dict:
    return {"id": 7031, "status": "closed", "exit_reason": reason,
            "account_id": "alpaca_paper", "strategy_name": "gdx_pullback_1d",
            "symbol": "GDX", "direction": "short", "entry_price": 87.01,
            "stop_loss": 94.72, "take_profit_1": 78.39601, "position_size": 1869.0,
            "order_package_id": "pkg-d0cbee77dcd74a4d", "exit_price": 80.263,
            "closed_at": "2026-11-16T14:35:52+00:00", "pnl": 12610.11,
            "fee_taker_usd": 0.0, "is_backtest": 0, "account_class": "paper"}


def test_grader_is_neutral_on_account_reset_and_still_faults_the_watchdog_label():
    import soak_state
    g = soak_state.grade_trade(_row("account_reset"))
    assert g["clean"] is None and g["fault"] is None
    # negative control: the same row under the detector label it carries today is a fault
    w = soak_state.grade_trade(_row("stuck_strategy_watchdog"))
    assert w["clean"] is False and "exit_journaled" in (w["fault"] or "")


def test_neutral_row_does_not_reset_a_soak():
    import soak_state
    clean = dict(soak_state.grade_trade(_row("sl")), id=1)
    reset = dict(soak_state.grade_trade(_row("account_reset")), id=2)
    assert clean["clean"] is True
    assert soak_state.evaluate([clean, reset], 1)["state"] == "passed"


def test_close_attribution_calls_it_not_a_strategy_exit():
    import real_money_close_attribution as rmca
    assert rmca.bucket_for("account_reset")[0] == "b_not_strategy_exit"


def test_kpi_predicate_drops_account_reset_and_keeps_strategy_exits():
    from src.web.api._clean_trades import exclude_reset_flat_predicate
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE trades (id INTEGER, exit_reason TEXT)")
    con.executemany("INSERT INTO trades VALUES (?,?)", [
        (1, "account_reset"), (2, "exchange_reset_flat"), (3, "entry_unfilled"),
        (4, "sl"), (5, None), (6, "stuck_strategy_watchdog")])
    kept = [r[0] for r in con.execute(
        "SELECT id FROM trades WHERE 1=1" + exclude_reset_flat_predicate("") + " ORDER BY id")]
    assert kept == [4, 5, 6]
