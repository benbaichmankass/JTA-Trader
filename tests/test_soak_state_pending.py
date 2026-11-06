"""A close whose costs the hourly broker-truth sweep has not written yet is PENDING (could not
look), never mechanical_fail; a real fault is never masked by an older clean trade; a pass cites
the LATEST clean trades. Trades 6936/6944/6950/6956/6938, 2026-11-06."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))
import soak_state as ss  # noqa: E402
sys.path.insert(0, str(REPO))

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def _t(tid, age_h, **over):
    row = {"id": tid, "account_id": "bybit_1", "order_package_id": f"p{tid}", "direction": "long",
           "position_size": 1.0, "entry_price": 100.0, "stop_loss": 99.0, "take_profit_1": 103.0,
           "exit_reason": "sl", "exit_price": 99.0, "pnl": -1.0, "fee_taker_usd": 0.1,
           "closed_at": (NOW - timedelta(hours=age_h)).isoformat(), "sl_order_id": "s", "tp_order_id": "t"}
    row.update(over)
    return row


def test_fresh_close_without_costs_is_pending_not_fault():
    g = ss.grade_trade(_t(1, 0.5, pnl=None, fee_taker_usd=None), now=NOW)
    assert g["pending"] and g["fault"] is None and g["clean"] is False


def test_price_less_strategy_close_is_pending():  # 6938 shape
    g = ss.grade_trade(_t(2, 0.2, exit_reason="strategy_close", exit_price=None, pnl=None,
                          fee_taker_usd=None), now=NOW)
    assert g["pending"] and g["fault"] is None


def test_costs_missing_past_grace_is_a_real_fault():
    g = ss.grade_trade(_t(3, ss.COST_WRITE_GRACE_HOURS + 1, pnl=None, fee_taker_usd=None), now=NOW)
    assert not g["pending"] and "fill_and_fees" in g["fault"]


def test_no_now_keeps_old_behaviour():
    assert ss.grade_trade(_t(4, 0.1, pnl=None, fee_taker_usd=None))["fault"]


def test_pending_never_hides_a_non_cost_fault():
    g = ss.grade_trade(_t(5, 0.1, pnl=None, fee_taker_usd=None, order_package_id=None), now=NOW)
    assert not g["pending"] and "signal_fired" in g["fault"]


def test_reconciler_close_is_never_pending():  # 6926: a reconciler close is a bug by contract
    g = ss.grade_trade(_t(6, 0.1, exit_reason="exchange_flat_reconciled", pnl=None, fee_taker_usd=None), now=NOW)
    assert not g["pending"] and g["fault"]


def test_newest_pending_does_not_borrow_an_older_clean_trade():
    clean = ss.grade_trade(_t(7, 30), now=NOW)
    pend = ss.grade_trade(_t(8, 0.5, pnl=None, fee_taker_usd=None), now=NOW)
    ev = ss.evaluate([clean, pend], 1)
    assert ev["state"] == "pending" and ev["clean"] == []


def test_pending_then_healed_passes_citing_the_latest_trade():
    old, new = ss.grade_trade(_t(9, 30), now=NOW), ss.grade_trade(_t(10, 0.5), now=NOW)
    ev = ss.evaluate([old, new], 1)
    assert ev["state"] == "passed" and ev["clean"] == [10]  # not the oldest (9)


def test_real_fault_is_not_masked_by_an_older_clean_trade():
    clean = ss.grade_trade(_t(11, 30), now=NOW)
    bad = ss.grade_trade(_t(12, 10, exit_reason="exchange_flat_reconciled"), now=NOW)
    assert ss.evaluate([clean, bad], 1)["state"] == "mechanical_fail"


def test_mechanics_fault_intake_files_each_faulted_trade_once():
    import mechanics_fault_intake as fi
    import pipeline
    bad = _t(20, 10, exit_reason="exchange_flat_reconciled")           # reconciler close: a fault
    ok = _t(21, 10)
    fresh = _t(22, 0.5, pnl=None, fee_taker_usd=None)                    # inside the cost window: not filed
    stale = _t(23, 10, pnl=None, fee_taker_usd=None)                     # costs missing past the window: filed
    got = fi.candidates([bad, ok, fresh, stale], [], NOW)
    assert [c["trade"]["id"] for c in got] == [20, 23]
    filed = [{"origin": {"ref": fi.fault_key(20) + " (mechanics monitoring)"}}]
    assert [c["trade"]["id"] for c in fi.candidates([bad], filed, NOW)] == []
    pipeline.validate(fi.build_item(got[0], "PI-X"))


def test_max_hold_and_strategy_close_are_clean_reasons():
    for r in ("max_hold", "strategy_close"):
        assert ss.grade_trade(_t(30, 10, exit_reason=r), now=NOW)["clean"] is True
    g = ss.grade_trade(_t(31, 0.2, exit_reason="max_hold", exit_price=None, pnl=None, fee_taker_usd=None), now=NOW)
    assert g["pending"]  # the 2026-11-06 15:00Z Alpaca max_hold shape, inside the cost window
