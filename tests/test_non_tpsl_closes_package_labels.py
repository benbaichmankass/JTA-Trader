"""NON-TPSL-CLOSES-20261029: a package's close_reason must not keep a bookkeeping label
when its trade is a venue stop/target fill, and shadow/netting packages must not be
mislabelled by the sweeps.

Rows are the live ones measured 2026-10-29 (diag journal): pkg-d752b509 / trade 6765
(`stuck_strategy_watchdog`), pkg-29c8e90b / trade 6764 (`stuck_cascade_recovered`),
pkg-11c1100f / trade 6763 (`reconciler_filled`), pkg-1f69590887ac44e9 (shadow refusal
row, package left `rejected`). Each trade already read exit_reason='sl'.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.runtime import order_monitor as om


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    from src.units.db.database import Database
    from src.utils.paths import trade_journal_db_path
    return Database(db_path=trade_journal_db_path())


def _now(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _pkg(db, pid, strategy, symbol, direction, entry, sl, tp, **extra):
    db.insert_order_package({
        "order_package_id": pid, "strategy_name": strategy, "symbol": symbol,
        "direction": direction, "entry": entry, "sl": sl, "tp": tp,
        "status": "open", **extra,
    })


def _trade(db, pkg, *, status, exit_reason, notes="{}", tid=None, **kw):
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO trades (timestamp, symbol, direction, entry_price, "
            "position_size, status, exit_reason, notes, account_id, "
            "order_package_id, created_at, is_backtest) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
            (_now(300), kw.get("symbol", "ETHUSDT"), kw.get("direction", "short"),
             2326.44, 27.57, status, exit_reason, notes, "bybit_1", pkg, _now(300)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _pkg_row(db, pid):
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT status, close_reason, meta FROM order_packages "
            "WHERE order_package_id=?", (pid,)).fetchone()
    finally:
        conn.close()


@pytest.mark.parametrize("pid,label", [
    ("pkg-d752b5099eab4317", "stuck_strategy_watchdog"),
    ("pkg-29c8e90b80c24835", "stuck_cascade_recovered"),
    ("pkg-11c1100f6cbb4667", "reconciler_filled"),
    ("pkg-netting", "netting_attributed"),
])
def test_closed_package_takes_the_trades_sl_label(db, pid, label):
    _pkg(db, pid, "trend_donchian_eth", "ETHUSDT", "short", 2326.44, 2348.68, 2096.12)
    tid = _trade(db, pid, status="closed", exit_reason="sl")
    db.update_order_package(pid, {
        "status": "closed", "close_reason": label, "linked_trade_id": tid})
    assert om._sweep_package_close_reason_from_trade(db)["relabelled"] == 1
    status, reason, meta = _pkg_row(db, pid)
    assert (status, reason) == ("closed", "sl")
    assert json.loads(meta)["pre_label_close_reason"] == label
    # idempotent: a second pass finds nothing left to change
    assert om._sweep_package_close_reason_from_trade(db)["relabelled"] == 0


def test_package_keeps_its_label_when_the_trade_is_not_a_bracket_fill(db):
    _pkg(db, "pkg-a", "trend_donchian", "BTCUSDT", "long", 81518, 80961, 89588)
    tid = _trade(db, "pkg-a", status="closed", exit_reason="reconciler_filled")
    db.update_order_package("pkg-a", {
        "status": "closed", "close_reason": "stuck_cascade_recovered",
        "linked_trade_id": tid})
    assert om._sweep_package_close_reason_from_trade(db)["relabelled"] == 0
    assert _pkg_row(db, "pkg-a")[1] == "stuck_cascade_recovered"


def test_a_real_strategy_close_reason_is_never_overwritten(db):
    _pkg(db, "pkg-b", "trend_donchian", "BTCUSDT", "long", 81518, 80961, 89588)
    tid = _trade(db, "pkg-b", status="closed", exit_reason="sl")
    db.update_order_package("pkg-b", {
        "status": "closed", "close_reason": "trail_exit", "linked_trade_id": tid})
    assert om._sweep_package_close_reason_from_trade(db)["relabelled"] == 0
    assert _pkg_row(db, "pkg-b")[1] == "trail_exit"


def test_shadow_refusal_package_is_shadow_expired_not_rejected(db, monkeypatch):
    """pkg-1f69590887ac44e9: execution:shadow refusal row, package was left 'rejected'."""
    import src.strategy_registry as sr
    monkeypatch.setattr(sr, "execution_mode", lambda name, *a, **k: "shadow")
    pid = "pkg-1f69590887ac44e9"
    _pkg(db, pid, "trend_donchian_1h", "BTCUSDT", "short", 79835.2, 81043.7, 71931.5)
    _trade(db, pid, status="rejected", exit_reason=None, symbol="BTCUSDT",
           notes=json.dumps({"reason": "dry_run_no_order_placed",
                             "dry_cause": "execution:shadow"}))
    conn = db.connect()
    conn.execute("UPDATE order_packages SET created_at=?", (_now(10),))
    conn.commit()
    conn.close()
    om._sweep_unlinked_packages(db)
    status, reason, _ = _pkg_row(db, pid)
    assert (status, reason) == ("shadow_expired", "shadow_no_execute")


def test_real_risk_refusal_is_still_rejected(db, monkeypatch):
    import src.strategy_registry as sr
    monkeypatch.setattr(sr, "execution_mode", lambda name, *a, **k: "live")
    _pkg(db, "pkg-r", "live_strat", "ETHUSDT", "long", 1800, 1770, 1980)
    _trade(db, "pkg-r", status="rejected", exit_reason=None,
           notes=json.dumps({"reason": "risk_refused"}))
    conn = db.connect()
    conn.execute("UPDATE order_packages SET created_at=?", (_now(10),))
    conn.commit()
    conn.close()
    om._sweep_unlinked_packages(db)
    assert _pkg_row(db, "pkg-r")[0] == "rejected"


@pytest.mark.parametrize("anchor_status,price,outcome", [
    ("anchored", 80999.9, "closed"), ("no_anchor", None, "unmeasured")])
def test_netting_full_close_cascades_its_package(db, anchor_status, price, outcome):
    """pkg-29c8e90b / trade 6764: the netting close left the package open, so
    `_sweep_stuck_linked_packages` stamped stuck_cascade_recovered."""
    pid = "pkg-29c8e90b80c24835"
    _pkg(db, pid, "trend_donchian", "BTCUSDT", "long", 81518, 80961, 89588)
    tid = _trade(db, pid, status="open", exit_reason=None, symbol="BTCUSDT",
                 direction="long")
    db.update_order_package(pid, {"linked_trade_id": tid})
    conn = db.connect()
    row = conn.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    conn.close()
    got = om._netting_apply_close(
        db, row=row, take=27.57, basis="fifo", anchor_price=price,
        anchor_status=anchor_status, anchored_at=_now(),
        anchor_source="candle_at_close", unmeasured_marker="__unmeasured__")
    assert got == outcome
    assert _pkg_row(db, pid)[:2] == ("closed", "netting_attributed")
