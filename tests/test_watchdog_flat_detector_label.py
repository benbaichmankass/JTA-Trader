"""ML-ENTRY-WATCHDOG-EXIT (2026-11-05): a watchdog-detected close is refined to
the bracket leg the venue filled, off a MEASURED exit price only.

THE DEFECT (MEASURED 2026-11-05, diag alpaca_order_history + journal): alpaca_paper
ml_entry SLV short 10, trade 6920. Its bracket stop leg filled at the broker
16:48:25.795Z @47.643 (package SL 47.6443). Alpaca rows carry no
sl_order_id/tp_order_id, and the forward reconciler cannot read Alpaca orders,
so the stuck-strategy watchdog's unmatched branch finalised the row 63 s later
with ``exit_reason='stuck_strategy_watchdog'``. ``_sweep_local_pnl_for_unpriced``
then priced it off that fill (``exit_price_source='exchange_fill'``, MEASURED) and
left the label frozen, because it relabelled only ``''`` / ``reconciler_filled``.
The Stage-1 soak graded the trade ``exit_journaled: fault``.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import order_monitor as om

_FILLS = """
CREATE TABLE exchange_fills (
    exec_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, price REAL NOT NULL, qty REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0, fee_currency TEXT, exec_time TEXT NOT NULL,
    order_id TEXT, is_maker INTEGER NOT NULL DEFAULT 0, raw TEXT,
    inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
_JOURNAL = """
CREATE TABLE trades (
    id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, direction TEXT,
    position_size REAL, entry_price REAL, exit_price REAL, pnl REAL,
    pnl_percent REAL, status TEXT, is_backtest INTEGER DEFAULT 0, setup_type TEXT,
    order_package_id TEXT, closed_at TEXT, created_at TEXT, exit_reason TEXT,
    timestamp TEXT, notes TEXT, sl_order_id TEXT, tp_order_id TEXT
);
CREATE TABLE order_packages (
    order_package_id TEXT, symbol TEXT, direction TEXT, sl REAL, tp REAL,
    linked_trade_id INTEGER, status TEXT, close_reason TEXT, meta TEXT,
    updated_at TEXT, created_at TEXT
);
"""


def _iso(d: datetime) -> str:
    return d.isoformat().replace("+00:00", "Z")


class _DB:
    def __init__(self, path):
        self.path = str(path)

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def update_trade(self, tid, updates):
        sets = ", ".join(f"{k} = ?" for k in updates)
        c = sqlite3.connect(self.path)
        c.execute(f"UPDATE trades SET {sets} WHERE id = ?", (*updates.values(), int(tid)))
        c.commit()
        c.close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    fpath = tmp_path / "fills.sqlite"
    c = sqlite3.connect(str(fpath))
    c.executescript(_FILLS)
    c.commit()
    c.close()
    jpath = tmp_path / "j.db"
    c = sqlite3.connect(str(jpath))
    c.executescript(_JOURNAL)
    c.commit()
    c.close()
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile", lambda: {
        "alpaca_paper": {"account_id": "alpaca_paper", "exchange": "alpaca"}})
    import src.runtime.exit_anchor as EA
    monkeypatch.setattr(EA, "bar_close_at", lambda *a, **k: None)
    import src.runtime.fills_pnl as FP
    factory = lambda: sqlite3.connect(f"file:{fpath}?mode=ro", uri=True)  # noqa: E731
    monkeypatch.setattr(FP, "_open_ro", lambda cf: factory())

    def add_fill(order_id, qty, price, at, side="buy"):
        c = sqlite3.connect(str(fpath))
        c.execute("INSERT INTO exchange_fills (exec_id, account_id, symbol, side, price, qty,"
                  " exec_time, order_id) VALUES (?,?,?,?,?,?,?,?)",
                  (f"e-{order_id}-{price}", "alpaca_paper", "SLV", side, price, qty,
                   _iso(at), order_id))
        c.commit()
        c.close()

    def add_trade(reason, *, notes=None, exit_price=None):
        # Closed > the 6 h broker-defer grace, so the local sweep owns the row
        # (inside the grace an Alpaca row waits for the broker sweep).
        now = datetime.now(timezone.utc)
        opened, closed = now - timedelta(hours=7, minutes=46), now - timedelta(hours=7)
        c = sqlite3.connect(str(jpath))
        c.execute("INSERT INTO order_packages (order_package_id, symbol, direction, sl, tp,"
                  " linked_trade_id, status, close_reason) VALUES"
                  " ('pkg-b51697fe35294b95','SLV','short',47.644285714285715,"
                  "  45.07107142857143, 6920, 'closed', ?)", (reason,))
        c.execute("INSERT INTO trades (id, account_id, symbol, direction, position_size,"
                  " entry_price, exit_price, status, exit_reason, setup_type,"
                  " order_package_id, created_at, closed_at, notes) VALUES"
                  " (6920,'alpaca_paper','SLV','short', 10.0, 46.615, ?, 'closed', ?,"
                  " 'ml_entry', 'pkg-b51697fe35294b95', ?, ?, ?)",
                  (exit_price, reason, _iso(opened), _iso(closed), json.dumps(notes or {
                      "closed_by": "stuck_strategy_watchdog"})))
        c.commit()
        c.close()
        return closed

    ns = type("W", (), {})()
    ns.db, ns.add_fill, ns.add_trade = _DB(jpath), add_fill, add_trade
    return ns


def _row(db):
    r = dict(db.connect().execute("SELECT * FROM trades WHERE id=6920").fetchone())
    return r, json.loads(r["notes"])


def test_6920_watchdog_close_on_its_own_stop_fill_relabels_sl(world):
    closed = world.add_trade("stuck_strategy_watchdog")
    world.add_fill("8a1fe2b9", 10.0, 47.643, closed - timedelta(seconds=63))
    s = om._sweep_local_pnl_for_unpriced(world.db)
    assert s["filled"] == 1, s
    r, n = _row(world.db)
    assert r["exit_price"] == pytest.approx(47.643)
    assert r["exit_reason"] == "sl"
    assert n["pre_label_exit_reason"] == "stuck_strategy_watchdog"
    assert n["exit_reason_source"] == "price_vs_pkg_bracket"
    assert n["exit_reason_price_basis"] == "measured"


def test_watchdog_close_mid_bracket_stays_watchdog_and_says_it_looked(world):
    """CONTROL: a fill strictly inside the bracket is not a stop or a target."""
    closed = world.add_trade("stuck_strategy_watchdog")
    world.add_fill("mid", 10.0, 46.20, closed - timedelta(seconds=60))
    om._sweep_local_pnl_for_unpriced(world.db)
    r, n = _row(world.db)
    assert r["exit_reason"] == "stuck_strategy_watchdog"
    assert n["exit_reason_source"] == "unresolved"
    assert "pre_label_exit_reason" not in n


def test_watchdog_close_on_an_estimated_price_is_refused_not_labelled(world, monkeypatch):
    """CONTROL: no venue fill -> the candle at DETECTION time. It may sit after
    the real exit, so it must never mint an sl/tp label for a flat detector."""
    import src.runtime.exit_anchor as EA
    world.add_trade("stuck_strategy_watchdog")
    monkeypatch.setattr(EA, "bar_close_at", lambda *a, **k: 47.70)   # through the SL
    om._sweep_local_pnl_for_unpriced(world.db)
    r, n = _row(world.db)
    assert r["exit_reason"] == "stuck_strategy_watchdog"
    if r["exit_price"] is not None:          # priced by the anchor -> declared refusal
        from src.runtime import provenance as prov
        assert n["exit_reason_source"] == prov.EXIT_LABEL_REFUSED_UNMEASURED


def test_a_price_an_earlier_sweep_took_from_the_fill_still_grades_measured(world):
    """The production shape: the broker sweep wrote exit_price off the fills
    store (``exchange_fill``) and left pnl NULL; this sweep prices pnl off the
    RECORDED price and must still read the row's MEASURED stamp."""
    world.add_trade("stuck_strategy_watchdog", exit_price=47.643, notes={
        "closed_by": "stuck_strategy_watchdog", "exit_price_source": "exchange_fill"})
    om._sweep_local_pnl_for_unpriced(world.db)
    r, n = _row(world.db)
    assert r["pnl"] == pytest.approx((46.615 - 47.643) * 10.0)
    assert r["exit_reason"] == "sl"
    assert n["exit_price_source"] == "exchange_fill"


def test_a_real_reason_is_never_overwritten(world):
    """CONTROL: guard 2 still holds for a reason that is not a detector's."""
    closed = world.add_trade("ml_time_exit")
    world.add_fill("8a1fe2b9", 10.0, 47.643, closed - timedelta(seconds=63))
    om._sweep_local_pnl_for_unpriced(world.db)
    r, _n = _row(world.db)
    assert r["exit_reason"] == "ml_time_exit"


def test_both_price_sweeps_share_the_one_detector_set():
    import inspect
    assert "stuck_strategy_watchdog" in om._FLAT_DETECTOR_REASONS
    assert om._SNAPSHOT_FLAT_REASON in om._FLAT_DETECTOR_REASONS
    for fn in (om._sweep_local_pnl_for_unpriced, om._sweep_pending_pnl_from_bybit):
        assert "_FLAT_DETECTOR_REASONS" in inspect.getsource(fn), fn.__name__


def test_backfill_mirrors_the_live_detector_set():
    from scripts.ops import backfill_exit_labels as bel
    assert set(bel.FLAT_DETECTOR_REASONS) == set(om._FLAT_DETECTOR_REASONS)
    assert set(bel.ORDER_ID_RELABEL_REASONS) == set(om._BRACKET_ORDER_RELABEL_REASONS)
