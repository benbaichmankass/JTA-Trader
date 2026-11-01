"""Reverse-reconciler orphan RE-ATTACH (return an adopted orphan to its
originating strategy for monitoring, instead of a bare orphan_adopt row).

Covers _adopt_orphan_position's two paths:
  * confident recovery of the originating order package → trade attributed to
    that strategy, carries the package's SL/TP, package reopened + re-linked
    (so run_monitor_tick's monitor() governs it);
  * no confident match → fallback bare orphan_adopt (NULL SL/TP).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.runtime.order_monitor import (
    _adopt_orphan_position,
    _reattach_adopted_orphans,
    _resolve_account_class,
)
from src.units.db.database import Database
from tests.fixtures.real_schema_db import (
    insert_order_package as _insert_package,
    insert_trade as _insert_trade,
    make_canonical_db,
)

# Fresh, not a fixed date: the orphan matcher refuses packages older than
# ORPHAN_PACKAGE_MAX_AGE_DAYS (PROV-IB).
_FRESH = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _orphan_adopt_trade(db: Database, **over) -> int:
    fields = {
        "timestamp": "2026-06-14T06:30:00Z", "symbol": "MHG",
        "direction": "long", "entry_price": 6.40, "position_size": 3.0,
        "status": "open", "is_backtest": 0, "is_demo": 0,
        "strategy_name": "orphan_adopt", "setup_type": "adopted_orphan",
        "account_id": "ib_paper",
    }
    fields.update(over)
    return int(_insert_trade(db.db_path, **fields))


def _db(tmp_path: Path) -> Database:
    path = tmp_path / "trade_journal.db"
    make_canonical_db(path)
    return Database(str(path))


def _trade_row(db: Database, trade_id: int) -> dict:
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT * FROM trades WHERE id = ?", [trade_id]).fetchone()
        return dict(r)
    finally:
        conn.close()


def _origin_fill(db: Database, opid: str, account_id: str, symbol: str, direction: str, entry: float,
                 size: float, strategy: str) -> None:
    """The orphan account's ORIGINAL fill in the package (since closed, e.g. falsely flat-reconciled).
    GLD-ORPHAN-5209: the matcher now requires the orphan's account to have FILLED in the candidate."""
    _insert_trade(db.db_path, timestamp="2026-06-13T00:00:00Z", symbol=symbol, direction=direction,
                  entry_price=entry, position_size=size, status="closed", is_backtest=0, is_demo=0,
                  strategy_name=strategy, setup_type=strategy, account_id=account_id, order_package_id=opid)


def _pkg_row(db: Database, opid: str) -> dict:
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute(
            "SELECT * FROM order_packages WHERE order_package_id = ?", [opid]
        ).fetchone()
        return dict(r)
    finally:
        conn.close()


def test_reattaches_orphan_to_originating_strategy(tmp_path: Path):
    db = _db(tmp_path)
    # The closed package that originally opened the (now-orphan) MHG position.
    _insert_package(
        db.db_path, order_package_id="op-mhg", strategy_name="mhg_pullback_1d",
        symbol="MHG", direction="long", entry=6.40, sl=6.05, tp=7.03,
        status="closed", close_reason="reconciler",
        created_at=_FRESH,
    )
    _origin_fill(db, 'op-mhg', 'ib_paper', 'MHG', 'long', 6.4, 3.0, 'mhg_pullback_1d')

    tid = _adopt_orphan_position(
        db=db, account_id="ib_paper", symbol="MHG", direction="long",
        size=3.0, entry_price=6.40,
    )

    trade = _trade_row(db, tid)
    # Attributed to the originating strategy (NOT orphan_adopt), with its SL/TP.
    assert trade["strategy_name"] == "mhg_pullback_1d"
    assert trade["setup_type"] == "adopted_orphan"
    assert trade["stop_loss"] == 6.05
    assert trade["take_profit_1"] == 7.03
    assert trade["status"] == "open"
    # The original package is reopened + re-linked so the monitor loop finds it.
    pkg = _pkg_row(db, "op-mhg")
    assert pkg["status"] == "open"
    assert str(pkg["linked_trade_id"]) == str(tid)


def test_direction_normalised_buy_matches_long(tmp_path: Path):
    db = _db(tmp_path)
    _insert_package(
        db.db_path, order_package_id="op-buy", strategy_name="trend_donchian",
        symbol="BTCUSDT", direction="buy", entry=80000.0, sl=79000.0, tp=82000.0,
        status="closed", created_at=_FRESH,
    )
    _origin_fill(db, 'op-buy', 'bybit_2', 'BTCUSDT', 'long', 80000.0, 0.01, 'trend_donchian')
    tid = _adopt_orphan_position(
        db=db, account_id="bybit_2", symbol="BTCUSDT", direction="long",
        size=0.01, entry_price=80050.0,  # within 2% of 80000
    )
    assert _trade_row(db, tid)["strategy_name"] == "trend_donchian"


def test_no_confident_match_falls_back_to_orphan_adopt(tmp_path: Path):
    db = _db(tmp_path)
    # A package for the same symbol but a far-off entry (>2%) — not confident.
    _insert_package(
        db.db_path, order_package_id="op-far", strategy_name="mhg_pullback_1d",
        symbol="MHG", direction="long", entry=5.00, sl=4.80, tp=5.50,
        status="closed", created_at=_FRESH,
    )
    tid = _adopt_orphan_position(
        db=db, account_id="ib_paper", symbol="MHG", direction="long",
        size=3.0, entry_price=6.40,
    )
    trade = _trade_row(db, tid)
    assert trade["strategy_name"] == "orphan_adopt"
    assert trade["stop_loss"] is None
    assert trade["take_profit_1"] is None
    # The far-off package is untouched (still closed).
    assert _pkg_row(db, "op-far")["status"] == "closed"


def test_self_heal_reattaches_existing_orphan_adopt_row(tmp_path: Path):
    """An already-adopted orphan_adopt row (created before the fix) is driven
    back to its strategy on the next reconcile pass — orphan_adopt is a
    problem state, not a resting status."""
    db = _db(tmp_path)
    tid = _orphan_adopt_trade(db)  # open orphan_adopt MHG row, no SL/TP
    _insert_package(
        db.db_path, order_package_id="op-mhg", strategy_name="mhg_pullback_1d",
        symbol="MHG", direction="long", entry=6.40, sl=6.05, tp=7.03,
        status="closed", created_at=_FRESH,
    )
    _origin_fill(db, 'op-mhg', 'ib_paper', 'MHG', 'long', 6.4, 3.0, 'mhg_pullback_1d')
    summary: dict = {}
    _reattach_adopted_orphans(db, summary)

    trade = _trade_row(db, tid)
    assert trade["strategy_name"] == "mhg_pullback_1d"
    assert trade["stop_loss"] == 6.05
    assert trade["take_profit_1"] == 7.03
    assert summary.get("reattached_existing") == 1
    pkg = _pkg_row(db, "op-mhg")
    assert pkg["status"] == "open"
    assert str(pkg["linked_trade_id"]) == str(tid)


def test_self_heal_skips_unrecoverable_orphan(tmp_path: Path):
    """No recoverable package → ``_reattach_adopted_orphans`` leaves the row
    untouched (reattach-only). The flatten of a still-alive un-attributable
    orphan happens in the per-account pass — see test_reverse_reconciler.py."""
    db = _db(tmp_path)
    tid = _orphan_adopt_trade(db)
    summary: dict = {}
    _reattach_adopted_orphans(db, summary)
    assert _trade_row(db, tid)["strategy_name"] == "orphan_adopt"
    assert _trade_row(db, tid)["status"] == "open"
    assert summary.get("reattached_existing", 0) == 0


# ---------------------------------------------------------------------------
# WC-2: paper/real_money + order_package_id stamping at the adopt insert.
# A PAPER adopted-orphan must not be mis-classified as real_money (the column
# defaults — is_demo=0, account_class=NULL→real_money — leak it into real-money
# PnL/stats); the recovered branch must also link the trade to its package via
# the canonical trades.order_package_id.
# ---------------------------------------------------------------------------


def test_resolve_account_class_canonical_coercion():
    """Mirror execute.py: paper→paper, real_money→real_money, missing/invalid
    →real_money, unknown account→real_money, lookup failure→real_money."""
    cfgs = {
        "p": {"account_class": "Paper"},          # case-insensitive
        "r": {"account_class": "real_money"},
        "blank": {"account_class": ""},            # falsy → real_money
        "weird": {"account_class": "demo"},        # invalid → real_money
        "none": {},                                # absent → real_money
    }
    assert _resolve_account_class("p", cfgs) == "paper"
    assert _resolve_account_class("r", cfgs) == "real_money"
    assert _resolve_account_class("blank", cfgs) == "real_money"
    assert _resolve_account_class("weird", cfgs) == "real_money"
    assert _resolve_account_class("none", cfgs) == "real_money"
    assert _resolve_account_class("missing_account", cfgs) == "real_money"
    # Best-effort: a malformed cfgs map never raises — falls back to real_money.
    assert _resolve_account_class("p", cfgs={"p": "not-a-dict"}) == "real_money"


def test_recovered_branch_paper_account_stamps_paper_and_links_package(tmp_path: Path):
    """(a) recovered branch on a PAPER account (ib_paper, account_class:paper in
    config/accounts.yaml) → account_class='paper', is_demo=1, and
    order_package_id == the recovered package id."""
    db = _db(tmp_path)
    _insert_package(
        db.db_path, order_package_id="op-mhg", strategy_name="mhg_pullback_1d",
        symbol="MHG", direction="long", entry=6.40, sl=6.05, tp=7.03,
        status="closed", created_at=_FRESH,
    )
    _origin_fill(db, 'op-mhg', 'ib_paper', 'MHG', 'long', 6.4, 3.0, 'mhg_pullback_1d')
    tid = _adopt_orphan_position(
        db=db, account_id="ib_paper", symbol="MHG", direction="long",
        size=3.0, entry_price=6.40,
    )
    trade = _trade_row(db, tid)
    assert trade["strategy_name"] == "mhg_pullback_1d"   # recovered branch
    assert trade["account_class"] == "paper"
    assert int(trade["is_demo"]) == 1
    assert trade["order_package_id"] == "op-mhg"
    # The existing re-link write-back is unchanged.
    assert str(_pkg_row(db, "op-mhg")["linked_trade_id"]) == str(tid)


def test_recovered_branch_real_money_account_stamps_real_and_links_package(tmp_path: Path):
    """(b) recovered branch on a REAL_MONEY account (bybit_2, account_class:
    real_money in config/accounts.yaml) → account_class='real_money',
    is_demo=0, order_package_id set."""
    db = _db(tmp_path)
    _insert_package(
        db.db_path, order_package_id="op-btc", strategy_name="trend_donchian",
        symbol="BTCUSDT", direction="long", entry=80000.0, sl=79000.0, tp=82000.0,
        status="closed", created_at=_FRESH,
    )
    _origin_fill(db, 'op-btc', 'bybit_2', 'BTCUSDT', 'long', 80000.0, 0.01, 'trend_donchian')
    tid = _adopt_orphan_position(
        db=db, account_id="bybit_2", symbol="BTCUSDT", direction="long",
        size=0.01, entry_price=80050.0,
    )
    trade = _trade_row(db, tid)
    assert trade["strategy_name"] == "trend_donchian"    # recovered branch
    assert trade["account_class"] == "real_money"
    assert int(trade["is_demo"]) == 0
    assert trade["order_package_id"] == "op-btc"


def test_bare_branch_stamps_account_class_with_null_order_package(tmp_path: Path):
    """(c) bare branch (no recoverable package) → account_class stamped from the
    account, is_demo consistent, order_package_id NULL (no package)."""
    # PAPER account, no package recovered → bare orphan_adopt, paper-stamped.
    db = _db(tmp_path)
    tid = _adopt_orphan_position(
        db=db, account_id="ib_paper", symbol="MHG", direction="long",
        size=3.0, entry_price=6.40,
    )
    trade = _trade_row(db, tid)
    assert trade["strategy_name"] == "orphan_adopt"      # bare branch
    assert trade["account_class"] == "paper"
    assert int(trade["is_demo"]) == 1
    assert trade["order_package_id"] is None             # no package → NULL

    # REAL_MONEY account, no package recovered → bare, real_money-stamped.
    rm_dir = tmp_path / "rm"
    rm_dir.mkdir()
    db2 = _db(rm_dir)
    tid2 = _adopt_orphan_position(
        db=db2, account_id="bybit_2", symbol="BTCUSDT", direction="long",
        size=0.01, entry_price=80050.0,
    )
    trade2 = _trade_row(db2, tid2)
    assert trade2["strategy_name"] == "orphan_adopt"
    assert trade2["account_class"] == "real_money"
    assert int(trade2["is_demo"]) == 0
    assert trade2["order_package_id"] is None


def test_wrong_direction_does_not_match(tmp_path: Path):
    db = _db(tmp_path)
    _insert_package(
        db.db_path, order_package_id="op-short", strategy_name="mhg_pullback_1d",
        symbol="MHG", direction="short", entry=6.40, sl=6.75, tp=5.80,
        status="closed", created_at=_FRESH,
    )
    tid = _adopt_orphan_position(
        db=db, account_id="ib_paper", symbol="MHG", direction="long",
        size=3.0, entry_price=6.40,
    )
    assert _trade_row(db, tid)["strategy_name"] == "orphan_adopt"


def test_a_package_where_this_account_did_not_fill_is_never_the_owner(tmp_path: Path):
    """GLD-ORPHAN-5209: the newest price-matching package is SKIPPED when the orphan's account has no fill in it
    (its row was rejected); the older package this account actually filled in is the owner."""
    db = _db(tmp_path)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    _insert_package(db.db_path, order_package_id="pkg-true", strategy_name="gld_pullback_1h", symbol="GLD",
                    direction="long", entry=419.72, sl=416.09, tp=461.27, status="closed", created_at=old_ts)
    _origin_fill(db, "pkg-true", "alpaca_paper", "GLD", "long", 419.72, 39.0, "gld_pullback_1h")
    _insert_package(db.db_path, order_package_id="pkg-false", strategy_name="gld_pullback_1h", symbol="GLD",
                    direction="long", entry=419.77, sl=414.54, tp=461.33, status="open", created_at=_FRESH)
    _insert_trade(db.db_path, timestamp="2026-06-14T00:00:00Z", symbol="GLD", direction="long", entry_price=419.77,
                  position_size=159.0, status="rejected", is_backtest=0, is_demo=1, strategy_name="gld_pullback_1h",
                  setup_type="gld_pullback_1h", account_id="alpaca_paper", order_package_id="pkg-false")
    tid = _adopt_orphan_position(db=db, account_id="alpaca_paper", symbol="GLD", direction="long",
                                 size=39.0, entry_price=419.51)
    t = _trade_row(db, tid)
    assert t["order_package_id"] == "pkg-true" and t["stop_loss"] == 416.09


def test_no_filled_candidate_for_this_account_is_a_named_refusal_not_no_candidate(tmp_path: Path):
    from src.runtime.order_monitor import _recover_orphan_attribution
    db = _db(tmp_path)
    _insert_package(db.db_path, order_package_id="op-x", strategy_name="mhg_pullback_1d", symbol="MHG",
                    direction="long", entry=6.40, sl=6.05, tp=7.03, status="closed", created_at=_FRESH)
    _origin_fill(db, "op-x", "ib_live", "MHG", "long", 6.40, 3.0, "mhg_pullback_1d")   # ANOTHER account filled
    a = _recover_orphan_attribution(db=db, symbol="MHG", direction="long", entry_price=6.40, account_id="ib_paper")
    assert a.package is None and a.refused and a.detail.startswith("no_account_fill")
    tid = _adopt_orphan_position(db=db, account_id="ib_paper", symbol="MHG", direction="long",
                                 size=3.0, entry_price=6.40)
    assert _trade_row(db, tid)["strategy_name"] == "orphan_adopt"                       # bare, never flattened


def test_a_venue_bracket_that_disagrees_refuses_and_one_that_agrees_attributes(tmp_path: Path):
    from src.runtime.order_monitor import _recover_orphan_attribution
    db = _db(tmp_path)
    _insert_package(db.db_path, order_package_id="op-mhg", strategy_name="mhg_pullback_1d", symbol="MHG",
                    direction="long", entry=6.40, sl=6.05, tp=7.03, status="closed", created_at=_FRESH)
    _origin_fill(db, "op-mhg", "ib_paper", "MHG", "long", 6.40, 3.0, "mhg_pullback_1d")
    kw = dict(db=db, symbol="MHG", direction="long", entry_price=6.40, account_id="ib_paper")
    bad = _recover_orphan_attribution(**kw, venue_sl=5.90, venue_tp=7.03)
    assert bad.refused and bad.detail.startswith("bracket_mismatch")
    ok = _recover_orphan_attribution(**kw, venue_sl=6.05, venue_tp=7.03)
    assert ok.package is not None and ok.package["order_package_id"] == "op-mhg"
    assert _recover_orphan_attribution(**kw).package is not None                          # bracket unread: account check only
