"""VENUE-FLAT-PENDING-ENTRY-LABELS (2026-11-19).

A symbol that reads FLAT because the row's ENTRY ORDER has not filled yet is
not a ghost, not a filled stop and not a refused-flat re-arm. Measured case:
alpaca_options_paper SLV trade 8034. Its DAY mleg limit entry was still `new`
when the 16:14Z boot audit printed it as a ghost, the 15:58Z re-arm preflight
paged CRITICAL alpaca_rearm_refused, and the naked sweep graded it target_flat
("stop already filled").

The three readers now use the same ``_entry_order_hold`` check as the
flat-close paths. Only a POSITIVE "still working" changes the label. An
unreadable or terminal read keeps the old grading; the controls below pin that.
"""
from __future__ import annotations

import sqlite3

import pytest

from src.runtime import boot_audit as ba
from src.runtime import order_monitor as om
from src.runtime.outcomes import Level
import tests.test_alpaca_rearm_preflight as _pf
from tests.test_alpaca_rearm_preflight import _Venue, _use

world = _pf.world  # the re-arm preflight suite's journal + venue fixture, reused as-is

ENTRY_OID = "10fd4469-aa72-4c9a-a893-ff5cafcc491d"


def _pending(mp, answer):
    """Stub the venue's entry-order state: True working, False terminal, None unreadable."""
    seen = []

    def _read(cfg, oid):
        seen.append(oid)
        return answer
    mp.setattr("src.units.accounts.clients.account_entry_order_pending", _read)
    return seen


def _flat_row_with_entry_oid(db):
    c = sqlite3.connect(db.path)
    c.execute("ALTER TABLE trades ADD COLUMN broker_order_id TEXT")
    c.execute("UPDATE trades SET status='closed' WHERE id=6024")
    c.execute("UPDATE trades SET broker_order_id=? WHERE id=5928", (ENTRY_OID,))
    c.commit()
    c.close()


def _refusals(pages):
    return [k for a, k in pages if a and a[0] == "alpaca_rearm_refused"]


# ---------------------------------------------------------------------------
# naked sweep + re-arm preflight (readers 2 and 3)
# ---------------------------------------------------------------------------

def test_pending_entry_on_a_flat_symbol_grades_entry_pending_and_pages_nothing(world):
    db, pages, mp = world
    _flat_row_with_entry_oid(db)
    v = _Venue(qty=0.0, price=735.0)
    v.resting = []
    _use(mp, v)
    seen = _pending(mp, True)
    s = om._check_broker_naked_equity_positions(db)
    assert seen == [ENTRY_OID]
    assert s["entry_pending"] == 1
    assert s["target_flat"] == 0 and s["target_naked"] == 0
    assert s["rearm_refused_flat"] == 0 and s["broker_naked"] == 0
    assert _refusals(pages) == []
    assert v.posts() == []
    assert s["unaccounted"] == 0


def test_unreadable_entry_state_keeps_the_flat_refusal(world):
    """Control: "could not look" never hides a refusal. The CRITICAL page stays."""
    db, pages, mp = world
    _flat_row_with_entry_oid(db)
    v = _Venue(qty=0.0, price=735.0)
    _use(mp, v)
    _pending(mp, None)
    s = om._check_broker_naked_equity_positions(db)
    assert s["entry_pending"] == 0 and s["rearm_refused_flat"] == 1
    flat = [k for k in _refusals(pages) if k.get("kind") == "flat"]
    assert flat and all(k.get("level") == Level.CRITICAL for k in flat)
    assert v.posts() == []


def test_terminal_entry_order_keeps_the_existing_flat_grading(world):
    """Control: a terminal or unknown entry order is not pending. The old labels stand."""
    db, pages, mp = world
    _flat_row_with_entry_oid(db)
    v = _Venue(qty=0.0, price=735.0)
    v.resting = []
    _use(mp, v)
    _pending(mp, False)
    s = om._check_broker_naked_equity_positions(db)
    assert s["entry_pending"] == 0
    assert s["target_flat"] == 1 and s["rearm_refused_flat"] == 1


def test_journal_without_broker_order_id_keeps_working(world):
    """An older journal schema (no broker_order_id column) still sweeps, with the old grading."""
    db, _pages, mp = world
    c = sqlite3.connect(db.path)
    c.execute("UPDATE trades SET status='closed' WHERE id=6024")
    c.commit()
    c.close()
    v = _Venue(qty=0.0, price=735.0)
    _use(mp, v)
    seen = _pending(mp, True)
    s = om._check_broker_naked_equity_positions(db)
    assert seen == []                     # no id -> nothing to ask the venue
    assert s["entry_pending"] == 0 and s["rearm_refused_flat"] == 1
    assert s["errors"] == 0


def test_preflight_returns_entry_pending_only_with_cfg_and_a_positive_read(world):
    db, pages, mp = world
    v = _Venue(qty=0.0, price=735.0)
    row = {"id": 8034, "direction": "long", "position_size": 1.0,
           "stop_loss": 700.0, "broker_order_id": ENTRY_OID}
    cfg = {"account_id": "alpaca_options_paper", "exchange": "alpaca", "mode": "live"}
    _pending(mp, True)
    assert om._alpaca_rearm_preflight(v, "alpaca_options_paper", "QQQ", row, [row], 700.0,
                                      cfg=cfg)[0] == "entry_pending"
    assert _refusals(pages) == []
    # Without cfg (the old call shape) the verdict is unchanged: flat, paged.
    assert om._alpaca_rearm_preflight(v, "alpaca_options_paper", "QQQ", row, [row],
                                      700.0)[0] == "flat"
    assert [k.get("kind") for k in _refusals(pages)] == ["flat"]


def test_entry_pending_is_declared_at_zero(world):
    db, _pages, mp = world
    c = sqlite3.connect(db.path)
    c.execute("DELETE FROM trades")
    c.commit()
    c.close()
    _use(mp, _Venue(qty=0.0, price=735.0))
    s = om._check_broker_naked_equity_positions(db)
    assert s["entry_pending"] == 0 and s["rearm_refused_entry_pending"] == 0


# ---------------------------------------------------------------------------
# boot audit (reader 1)
# ---------------------------------------------------------------------------

@pytest.fixture
def boot(tmp_path, monkeypatch):
    db = tmp_path / "trade_journal.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, "
                  "status TEXT, is_backtest INTEGER, strategy_name TEXT, account_id TEXT, "
                  "position_size REAL, broker_order_id TEXT)")
        c.execute("CREATE TABLE order_packages (order_package_id TEXT, strategy_name TEXT, "
                  "status TEXT, linked_trade_id INTEGER)")
        c.execute("INSERT INTO trades VALUES (8034,'SLV','short','open',0,'slv_trend_1h',"
                  "'alpaca_options_paper',1.0,?)", (ENTRY_OID,))
    monkeypatch.setattr("src.utils.paths.trade_journal_db_path", lambda: str(db))
    monkeypatch.setattr(ba, "_load_live_accounts", lambda: {"alpaca_options_paper": {
        "account_id": "alpaca_options_paper", "exchange": "alpaca", "mode": "live",
        "account_class": "paper"}})
    import src.units.accounts.clients as cl
    monkeypatch.setattr(cl, "account_open_positions", lambda cfg: [])
    monkeypatch.setattr(cl, "account_alpaca_open_orders", lambda cfg: {"orders": []})
    from src.runtime import restart_cause as rc
    return monkeypatch, rc.RestartCause("deploy", "deploy a1b2c3d (test)")


def _report(cause):
    return ba.build_restart_report(cause=cause)


def test_boot_audit_pending_entry_is_not_a_ghost(boot):
    mp, cause = boot
    _pending(mp, True)
    rep = _report(cause)
    a = rep["accounts"][0]
    assert a.ghosts == [] and a.entry_pending == ["trade #8034 SLV short"]
    assert a.problems == 0
    text, _, _ = ba.render_restart_message(rep)
    assert "ghost" not in text


@pytest.mark.parametrize("answer", [None, False])
def test_boot_audit_unreadable_or_terminal_entry_is_still_a_ghost(boot, answer):
    mp, cause = boot
    _pending(mp, answer)
    rep = _report(cause)
    a = rep["accounts"][0]
    assert a.ghosts == ["trade #8034 SLV short"] and a.entry_pending == []
    assert a.problems == 1
