"""IB-TRAIL-AMEND-MISSED (2026-11-20): the IB price re-assert must never revert a
trail amend that landed while the sweep was running.

Measured on ib_paper MGC trade 7737 (paper):
- 00:00:23.47Z: the monitor's trail amend moved the stop 3683.4 -> 3654.1, IB ack OK.
- 00:00:24.68Z: ``_check_broker_naked_ib_positions`` had read the open rows ONCE
  before its loop. It graded the venue's new 3654.1 against its stale 3683.39,
  called that a divergence and re-placed 3683.4.
- The 1 h re-assert cooldown then held the looser stop in place.

Contract:
1. An amend that lands mid-sweep (the row's stop changed after the snapshot) is
   never reverted.
2. A row whose package LEVELS changed after the snapshot stands down too: this
   covers the trade-row write lagging the package write. A package that was only
   touched (``updated_at`` bumped, levels unchanged) still re-asserts. The check is
   keyed on level columns, never on ``updated_at``.
3. A genuinely diverged, unchanged row still re-asserts.
4. A closed row, or a fresh read that fails, stands down. It fails closed.

Paths 1-3 run the REAL sweep end to end; the rest run the real decision function.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import order_monitor as om

OLD_SL = 3683.38571429     # the sweep's stale snapshot (previous trail step)
NEW_SL = 3654.08571429     # the amend that landed mid-sweep
TP = 3398.6621


class _Db:
    def __init__(self, path):
        self.path = str(path)
        c = sqlite3.connect(self.path)
        c.executescript(
            "CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT,"
            " direction TEXT, position_size REAL, stop_loss REAL, take_profit_1 REAL,"
            " created_at TEXT, notes TEXT, status TEXT, is_backtest INTEGER DEFAULT 0,"
            " order_package_id TEXT);"
            "CREATE TABLE order_packages (order_package_id TEXT, sl REAL, tp REAL,"
            " updated_at TEXT);")
        c.execute("INSERT INTO trades VALUES (7737,'ib_paper','MGC','short',27,?,?,"
                  "'2026-11-18T00:00:00+00:00',NULL,'open',0,'pkg-8958fc7d4ee74c60')",
                  (OLD_SL, TP))
        c.execute("INSERT INTO order_packages VALUES ('pkg-8958fc7d4ee74c60',?,?,"
                  "'2026-11-19T23:00:23+00:00')", (OLD_SL, TP))
        c.commit()
        c.close()

    def connect(self):
        return sqlite3.connect(self.path)

    def set(self, sql, *args):
        c = sqlite3.connect(self.path)
        c.execute(sql, args)
        c.commit()
        c.close()

    def stop(self):
        c = sqlite3.connect(self.path)
        v = c.execute("SELECT stop_loss FROM trades WHERE id=7737").fetchone()[0]
        c.close()
        return v


class _Ib:
    """ib_paper with 27 MGC short covered by one OCA pair resting at ``resting``.

    ``on_read`` runs inside the coverage read, i.e. AFTER the sweep has taken its
    row snapshot: this is where the monitor thread's amend lands in the replay.
    """

    def __init__(self, resting, on_read=None):
        self.resting = resting
        self.on_read = on_read
        self.modified = []

    def protection_coverage(self, symbol, *a, **k):
        if self.on_read:
            self.on_read()
            self.on_read = None
        return {"size": 27.0, "covered_qty": 27.0, "stop_qty": 27.0, "target_qty": 27.0,
                "legs": 2, "unknown_qty_legs": 0, "source": "resting_legs",
                "stop_prices": [self.resting], "oca_groups": {"oca-protect-t7737": 2}}

    def has_protective_orders(self, symbol):
        return True

    def modify_protective(self, order):
        self.modified.append(order)
        self.resting = order["sl"]
        return {"retCode": 0, "result": {"orderId": "1470"}}

    def place_protective(self, order):
        raise AssertionError("nothing is naked here; the sweep must not place")


@pytest.fixture
def world(tmp_path, monkeypatch):
    db = _Db(tmp_path / "j.db")
    soak = tmp_path / "soak.jsonl"
    monkeypatch.setattr(om, "_reassert_soak_path", lambda: str(soak))
    monkeypatch.setenv("PROTECTION_REASSERT_MODE", "apply")
    monkeypatch.setenv("PROTECTION_REASSERT_ACCOUNTS", "ib_paper")
    monkeypatch.setattr("src.bot.data_loaders.list_accounts",
                        lambda: [{"account_id": "ib_paper", "exchange": "interactive_brokers"}])
    om._REASSERT_STATE.clear()
    om._LAST_IB_BROKER_NAKED_CHECK_MONO = -1e9
    om._TICK_ACTIVE_CLOSE_AT.clear()
    yield db, soak, monkeypatch
    om._REASSERT_STATE.clear()


def _use(mp, ib):
    mp.setattr("src.units.accounts.clients.ib_client_for", lambda acc, readonly=False, **k: ib)


def _soak(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


# ---------------------------------------------------------------------------
# end to end through the real sweep
# ---------------------------------------------------------------------------

def test_replay_amend_landing_mid_sweep_is_never_reverted(world):
    db, soak, mp = world

    def amend_lands():          # the monitor thread, between snapshot and decision
        db.set("UPDATE order_packages SET sl=?, updated_at=?", NEW_SL,
               datetime.now(timezone.utc).isoformat())
        db.set("UPDATE trades SET stop_loss=? WHERE id=7737", NEW_SL)

    ib = _Ib(resting=3654.1, on_read=amend_lands)
    _use(mp, ib)
    s = om._check_broker_naked_ib_positions(db)
    assert ib.modified == [], "the sweep re-placed the stale stop over a fresh amend"
    assert ib.resting == 3654.1
    assert s["stop_price_reassert_skipped_row_changed"] == 1
    assert s["stop_price_reasserted"] == 0
    rows = _soak(soak)
    assert rows and rows[-1]["decision"] == "skipped_row_changed_mid_sweep"
    assert "stop_loss changed" in rows[-1]["reason"]
    assert om._REASSERT_STATE == {}, "a stand-down must not spend the cooldown"


def test_package_level_moved_after_snapshot_stands_down_even_if_trade_row_lags(world):
    db, soak, mp = world

    def only_package_moved():   # the trail wrote the package; the trade row lags
        db.set("UPDATE order_packages SET sl=?, updated_at=?", NEW_SL,
               datetime.now(timezone.utc).isoformat())

    ib = _Ib(resting=3654.1, on_read=only_package_moved)
    _use(mp, ib)
    s = om._check_broker_naked_ib_positions(db)
    assert ib.modified == []
    assert s["stop_price_reassert_skipped_row_changed"] == 1
    assert "order package sl changed" in _soak(soak)[-1]["reason"]


def test_package_touched_without_a_level_change_still_reasserts(world):
    """Manager review of #27545: a non-level write that bumps updated_at mid-sweep
    (metadata, telemetry) must NOT make a genuinely diverged row stand down,
    or the re-assert would silently stop working."""
    db, soak, mp = world
    db.set("UPDATE trades SET stop_loss=? WHERE id=7737", NEW_SL)
    db.set("UPDATE order_packages SET sl=?", NEW_SL)

    def touch_only():
        db.set("UPDATE order_packages SET updated_at=?",
               datetime.now(timezone.utc).isoformat())

    ib = _Ib(resting=3683.4, on_read=touch_only)
    _use(mp, ib)
    s = om._check_broker_naked_ib_positions(db)
    assert len(ib.modified) == 1 and ib.modified[0]["sl"] == pytest.approx(NEW_SL)
    assert s["stop_price_reassert_skipped_row_changed"] == 0


def test_genuine_divergence_on_an_unchanged_row_still_reasserts(world):
    """Positive control: the venue drifted and nothing changed the row -> act."""
    db, soak, mp = world
    db.set("UPDATE trades SET stop_loss=? WHERE id=7737", NEW_SL)
    db.set("UPDATE order_packages SET sl=?", NEW_SL)
    ib = _Ib(resting=3683.4)    # looser than declared, the 00:05Z-01:00Z state
    _use(mp, ib)
    s = om._check_broker_naked_ib_positions(db)
    assert len(ib.modified) == 1
    assert ib.modified[0]["sl"] == pytest.approx(NEW_SL)
    assert ib.modified[0]["tp"] == pytest.approx(TP)
    assert s["stop_price_reassert_skipped_row_changed"] == 0
    assert db.stop() == pytest.approx(NEW_SL)


def test_the_new_counter_is_declared_at_zero(world):
    db, _soak_path, mp = world
    db.set("DELETE FROM trades")
    _use(mp, _Ib(resting=3683.4))
    s = om._check_broker_naked_ib_positions(db)
    assert s["stop_price_reassert_skipped_row_changed"] == 0


# ---------------------------------------------------------------------------
# the guard itself
# ---------------------------------------------------------------------------

def _row(db):
    c = db.connect()
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT t.*, p.sl AS pkg_sl, p.tp AS pkg_tp FROM trades t LEFT JOIN "
                  "order_packages p ON p.order_package_id=t.order_package_id "
                  "WHERE t.id=7737").fetchone()
    c.close()
    return r


def test_guard_passes_an_unchanged_row(world):
    db, _s, _mp = world
    snap = _row(db)
    assert om._reassert_row_changed_mid_sweep(db, snap) is None


def test_guard_stands_down_on_a_closed_row(world):
    db, _s, _mp = world
    snap = _row(db)
    db.set("UPDATE trades SET status='closed' WHERE id=7737")
    assert "status" in om._reassert_row_changed_mid_sweep(db, snap)


def test_guard_fails_closed_when_the_fresh_read_fails(world):
    db, _s, _mp = world
    snap = _row(db)

    class _Broken:
        def connect(self):
            raise sqlite3.OperationalError("database is locked")
    assert "failed" in om._reassert_row_changed_mid_sweep(_Broken(), snap)


def test_guard_ignores_an_updated_at_touch_without_a_level_change(world):
    db, _s, _mp = world
    snap = _row(db)
    db.set("UPDATE order_packages SET updated_at=?",
           (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat())
    assert om._reassert_row_changed_mid_sweep(db, snap) is None


def test_guard_works_on_a_journal_without_order_package_id(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT, stop_loss REAL,"
              " take_profit_1 REAL, position_size REAL)")
    c.execute("INSERT INTO trades VALUES (1,'open',10.0,20.0,1.0)")
    c.commit()
    c.close()

    class _Old:
        def connect(self):
            return sqlite3.connect(p)
    snap = {"id": 1, "stop_loss": 10.0, "take_profit_1": 20.0, "position_size": 1.0}
    assert om._reassert_row_changed_mid_sweep(_Old(), snap) is None
    snap2 = dict(snap, stop_loss=11.0)
    assert "stop_loss changed" in om._reassert_row_changed_mid_sweep(_Old(), snap2)
