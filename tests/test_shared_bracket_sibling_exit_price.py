"""SHARED-BRACKET-FIX (2026-11-25): a netted demo row's exit is priced from its OWN order, never a sibling's fill.

MEASURED on the live journal 2026-11-25 (trade ids 6614-8613, every closed Bybit row carrying the venue's own
``venue_avg_exit``: 314 rows): 8 have ``exit_price`` more than 10 bps from their own venue exit, 7 of them on
bybit_1 with a same-symbol, same-side sibling open. Two writers took the sibling's fill:

* ``_sweep_pending_pnl_from_bybit`` rewrote an exit the netting reconciler had already priced from the row's own
  take-profit order: trade 7555 (sol_pullback_2h, SOLUSDT short 210.1, own TP cc054397 filled @ 65.51) reads
  ``exit_price`` 71.47. The demo branch of ``account_closed_pnl_for_trade`` tries the cumulative symbol + qty read
  first, and the row's own order only when that refuses.
* ``_close_trade_from_order_status`` priced a close from that same fills-store record: trade 8123 (ml_entry_v2,
  ETHUSDT short 12.97, SL 1694.62, own SL filled @ 1695.79) reads 1659.15.

PnL is not affected on those rows (``pnl_basis = venue_net``: the venue's own closed-pnl record), only the price.
Times are offsets from now because the sweeps keep a recent window; prices and sizes are the live ones.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from unittest.mock import patch

import pytest

from src.runtime import order_monitor as om

QTY = 210.1
ENTRY = 72.71
OWN_TP = "cc054397-041e-479d-b90a-16ac2cee2cef"
OWN_SL = "7054f571-a97b-4aa0-8c9e-da16db470bc6"
SIB_TP = "sibling-tp-0001"


def _iso(t):
    return t.isoformat()


class _DB:
    def __init__(self, path):
        self.path = path

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def update_trade(self, tid, upd):
        c = sqlite3.connect(self.path)
        c.execute(f"UPDATE trades SET {', '.join(f'{k} = ?' for k in upd)} WHERE id = ?",
                  [*upd.values(), int(tid)])
        c.commit()
        c.close()
        return 1


@pytest.fixture
def times():
    now = _dt.datetime.now(_dt.timezone.utc)
    return {"open": now - _dt.timedelta(hours=10), "sib": now - _dt.timedelta(hours=6),
            "own": now - _dt.timedelta(hours=2)}


def _journal(tmp_path, times, *, exit_price=65.51, notes=None):
    path = tmp_path / "j.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, entry_price REAL, "
        "stop_loss REAL, take_profit_1 REAL, exit_price REAL, position_size REAL, pnl REAL, "
        "pnl_percent REAL, setup_type TEXT, exit_reason TEXT, status TEXT, created_at TEXT, "
        "closed_at TEXT, is_backtest INTEGER, strategy_name TEXT, account_id TEXT, notes TEXT, "
        "order_package_id TEXT, sl_order_id TEXT, tp_order_id TEXT)")
    c.execute(
        "INSERT INTO trades VALUES (7555,'SOLUSDT','short',?,74.0407,65.5027,?,?,NULL,NULL,"
        "'sol_pullback_2h','tp','closed',?,?,0,'sol_pullback_2h','bybit_1',?,'pkg-x',?,?)",
        (ENTRY, exit_price, QTY, _iso(times["open"]), _iso(times["own"]),
         notes if notes is not None else json.dumps({
             "closed_by": "netting_own_leg_fill", "exit_reason_source": "venue_bracket_order",
             "exit_price_source": "exchange_fill",
             "own_leg_fill": {"leg": "tp", "order_id": OWN_TP}}),
         OWN_SL, OWN_TP))
    c.commit()
    c.close()
    return _DB(path)


def _fills(tmp_path, times, *, with_own=True):
    """bybit_1 SOLUSDT close-side (buy) fills: a sibling's TP of a similar size first, then the row's own TP."""
    path = tmp_path / "f.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE exchange_fills (exec_id TEXT PRIMARY KEY, account_id TEXT, symbol TEXT, "
        "side TEXT, price REAL, qty REAL, fee REAL, fee_currency TEXT, exec_time TEXT, "
        "order_id TEXT, is_maker INTEGER, raw TEXT, inserted_at TEXT)")
    fills = [("buy", 71.47, 212.0, times["sib"], SIB_TP)]
    if with_own:
        fills.append(("buy", 65.51, QTY, times["own"], OWN_TP))
    for i, (side, px, qty, t, oid) in enumerate(fills):
        c.execute("INSERT INTO exchange_fills VALUES (?,?,?,?,?,?,0,'USDT',?,?,0,NULL,NULL)",
                  (f"e{i}", "bybit_1", "SOL/USDT:USDT", side, px, qty, _iso(t), oid))
    c.commit()
    c.close()
    return path


CFG = {"account_id": "bybit_1", "exchange": "bybit", "demo": True}


# ── the shared reader: own order first ───────────────────────────────────────

def test_demo_reader_takes_the_rows_own_order_not_the_siblings_fill(tmp_path, times, monkeypatch):
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(_fills(tmp_path, times)))
    from src.runtime.fills_pnl import exit_from_fills
    from src.units.accounts.clients import account_closed_pnl_for_trade
    opened_ms = om._isoformat_to_ms(_iso(times["open"]))
    # The defect, pinned: the cumulative read takes the sibling's 71.47 (qty within 5 %).
    old = exit_from_fills(account_id="bybit_1", symbol="SOLUSDT", direction="short",
                          opened_at_ms=opened_ms, closed_at_ms=None, qty=QTY)
    assert old["avg_exit_price"] == pytest.approx(71.47)
    rec = account_closed_pnl_for_trade(CFG, symbol="SOLUSDT", direction="short",
                                       opened_at_ms=opened_ms, qty=QTY,
                                       own_order_ids=(OWN_SL, OWN_TP))
    assert rec["match"] == "own_bracket_order" and rec["order_id"] == OWN_TP
    assert rec["avg_exit_price"] == pytest.approx(65.51)


def test_demo_reader_without_own_ids_is_unchanged(tmp_path, times, monkeypatch):
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(_fills(tmp_path, times)))
    from src.units.accounts.clients import account_closed_pnl_for_trade
    rec = account_closed_pnl_for_trade(CFG, symbol="SOLUSDT", direction="short",
                                       opened_at_ms=om._isoformat_to_ms(_iso(times["open"])), qty=QTY)
    assert rec["avg_exit_price"] == pytest.approx(71.47)   # no identity to prefer: the old read stands


# ── the pending sweep: never rewrites an own-order exit ──────────────────────

def test_pending_sweep_keeps_the_own_tp_price_while_the_own_fill_is_not_pulled_yet(tmp_path, times, monkeypatch):
    """Trade 7555: closed at its own TP's venue price; the hourly fills pull holds only the sibling's fill."""
    db = _journal(tmp_path, times)
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(_fills(tmp_path, times, with_own=False)))
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile", lambda: {"bybit_1": CFG})
    summary = om._sweep_pending_pnl_from_bybit(db)
    c = db.connect()
    r = dict(c.execute("SELECT exit_price, notes FROM trades WHERE id = 7555").fetchone())
    c.close()
    assert r["exit_price"] == pytest.approx(65.51), "the sibling's 71.47 must not replace the own TP fill"
    assert summary["own_order_exit_kept"] == 1 and summary["filled"] == 0


def test_pending_sweep_still_writes_a_row_with_no_own_order_price(tmp_path, times, monkeypatch):
    """A row the close path could NOT price from its own order keeps the old behaviour (best available read)."""
    db = _journal(tmp_path, times, exit_price=None,
                  notes=json.dumps({"closed_by": "monitor_reconciler"}))
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(_fills(tmp_path, times, with_own=False)))
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile", lambda: {"bybit_1": CFG})
    summary = om._sweep_pending_pnl_from_bybit(db)
    assert summary["own_order_exit_kept"] == 0 and summary["filled"] == 1


def test_pending_sweep_writes_the_own_fill_once_it_is_pulled(tmp_path, times, monkeypatch):
    db = _journal(tmp_path, times, exit_price=None)
    monkeypatch.setenv("EXCHANGE_FILLS_DB", str(_fills(tmp_path, times)))
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile", lambda: {"bybit_1": CFG})
    om._sweep_pending_pnl_from_bybit(db)
    c = db.connect()
    px = c.execute("SELECT exit_price FROM trades WHERE id = 7555").fetchone()[0]
    c.close()
    assert px == pytest.approx(65.51)


def test_marker_reads_the_new_key_and_the_netting_close_key():
    assert om._exit_priced_by_own_order(json.dumps({"exit_price_order_id": OWN_SL}), (OWN_SL, OWN_TP))
    assert om._exit_priced_by_own_order(json.dumps({"own_leg_fill": {"order_id": OWN_TP}}), (OWN_SL, OWN_TP))
    assert not om._exit_priced_by_own_order(json.dumps({"exit_price_order_id": SIB_TP}), (OWN_SL, OWN_TP))
    assert not om._exit_priced_by_own_order(json.dumps({}), (OWN_SL, OWN_TP))
    assert not om._exit_priced_by_own_order(json.dumps({"exit_price_order_id": OWN_SL}), ())


# ── the reconciler close: the own leg's order beats a fills-store record ─────

class _FakeDB:
    def __init__(self):
        self.updates = {}

    def update_trade(self, trade_id, updates):
        self.updates[int(trade_id)] = dict(updates)
        return 1


ETH_SL = "6d2904ea-9c80-4966-94a5-53ca166958d9"
ETH_TP = "c5e1d7f0-c30c-4d78-820d-c16c8ebd8010"


def _eth_row():
    return {"id": 8123, "symbol": "ETHUSDT", "direction": "short", "position_size": 12.97,
            "entry_price": 1626.81, "created_at": "2026-11-21T08:01:00+00:00",
            "setup_type": "ml_entry_v2", "sl_order_id": ETH_SL, "tp_order_id": ETH_TP,
            "notes": json.dumps({"trade_id": "x"})}


def _reconcile(record, statuses, cfg):
    db = _FakeDB()
    with patch("src.units.accounts.clients.account_closed_pnl_for_trade", return_value=record), \
         patch("src.units.accounts.clients.account_order_status",
               side_effect=lambda c, oid: statuses.get(oid)), \
         patch.object(om, "_cascade_close_linked_package"), \
         patch.object(om, "_cancel_closed_row_protection"), \
         patch.object(om, "_classify_broker_exit", return_value=None), \
         patch("src.units.accounts.clients.account_exec_type_for_close", return_value=None):
        reason, _ = om._close_trade_from_order_status(
            db, _eth_row(), {"avg_price": 1626.81, "exec_time": "1795000000000"}, cfg=cfg)
    return reason, db.updates[8123]


SIBLING_RECORD = {"avg_exit_price": 1659.15, "avg_entry_price": None, "closed_pnl": None, "qty": 12.9,
                  "side": "buy", "closed_at": "2026-11-21T11:00:00Z", "source": "exchange_fill",
                  "fees": 4.2}
OWN_SL_FILLED = {"order_id": ETH_SL, "status": "Filled", "filled_qty": 12.97, "avg_price": 1695.79,
                 "exec_time": "1795001555109"}


def test_reconciler_prices_from_the_own_sl_not_the_fills_store_siblings_fill():
    reason, upd = _reconcile(SIBLING_RECORD, {ETH_SL: OWN_SL_FILLED}, CFG)
    assert reason == "sl" and upd["exit_reason"] == "sl"
    assert upd["exit_price"] == pytest.approx(1695.79)
    notes = json.loads(upd["notes"])
    assert notes["exit_price_order_id"] == ETH_SL
    assert notes["exit_reason_source"] == "venue_bracket_order"
    assert "close_fees_usd" not in notes, "the sibling's fees are not this row's"


def test_reconciler_keeps_the_record_when_no_own_leg_filled():
    _reason, upd = _reconcile(SIBLING_RECORD, {}, CFG)
    assert upd["exit_price"] == pytest.approx(1659.15)
    assert "exit_price_order_id" not in json.loads(upd["notes"])


def test_reconciler_never_overrides_a_venue_closed_pnl_record():
    """Real money: the venue's own closed-pnl record (source bybit_closed_pnl) stands; no extra order read."""
    venue = dict(SIBLING_RECORD, source="bybit_closed_pnl", avg_exit_price=1695.80, closed_pnl=-442.0)
    _reason, upd = _reconcile(venue, {ETH_SL: OWN_SL_FILLED},
                              {"account_id": "bybit_2", "exchange": "bybit", "demo": False})
    assert upd["exit_price"] == pytest.approx(1695.80)
    assert "exit_price_order_id" not in json.loads(upd["notes"])


def test_reconciler_own_leg_branch_and_netting_close_stamp_the_marker():
    _reason, upd = _reconcile(None, {ETH_SL: OWN_SL_FILLED}, CFG)
    assert json.loads(upd["notes"])["exit_price_order_id"] == ETH_SL
