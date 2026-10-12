"""CLOSE-PNL-NULL (2026-10-12): the pending-pnl sweep must match the venue's
closed-pnl record against the venue's ENTRY FILL when the journal's intended
entry misses.

Live case: bybit_2 (real money) trade 6565 ADAUSDT long closed `sl_cross` with
journal entry 0.2492. The venue's own SL order filled at 0.2432 and booked a
closed-pnl record (closedPnl -3.28194216) with avgEntryPrice 0.2489 — the fill,
12 bps from the journal value, past the matcher's 10 bps. The sweep asked with
the journal value every tick, the record was refused every tick, and the SPA
showed "—". WATCHDOG-PAST-STOP (2026-10-10) had fixed the same defect in the
reconciler and the watchdog but not in this, the third caller.

These tests run the REAL sweep against a real sqlite trades table and fake only
the venue: the matcher stub honours the 10 bps entry tolerance exactly as
`_bybit_closed_pnl_lookup` does.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3

from src.runtime import order_monitor as om

_VENUE_ENTRY = 0.2489
_REC = {"avg_exit_price": 0.2432, "avg_entry_price": _VENUE_ENTRY,
        "closed_pnl": -3.28194216, "closed_at": "1791815913411",
        "source": "bybit_closed_pnl"}


def _run(tmp_path, monkeypatch, *, entry_status, journal_entry=0.2492):
    created_at = (_dt.datetime.now(_dt.timezone.utc)
                  - _dt.timedelta(days=1)).isoformat()
    closed_at = (_dt.datetime.now(_dt.timezone.utc)
                 - _dt.timedelta(minutes=5)).isoformat()
    db_path = tmp_path / "j.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, "
        "position_size REAL, entry_price REAL, account_id TEXT, created_at TEXT, "
        "notes TEXT, setup_type TEXT, exit_reason TEXT, status TEXT, "
        "is_backtest INTEGER, pnl REAL, exit_price REAL, pnl_percent REAL, "
        "closed_at TEXT)"
    )
    conn.execute(
        "INSERT INTO trades VALUES (6565,'ADAUSDT','long',548,?,'bybit_2',?,?,"
        "'ada_pullback_2h','sl_cross','closed',0,NULL,0.2431,NULL,?)",
        (journal_entry, created_at,
         '{"trade_id": "09037913-4c5a-47e6-a397-1a1a94f004f9", '
         '"exit_price_source": "verdict"}', closed_at),
    )
    conn.commit()
    conn.close()

    captured: dict = {}
    calls: list = []

    class _DB:
        def connect(self):
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            return c

        def update_trade(self, tid, updates):
            captured[tid] = dict(updates)

    def _lookup(cfg, *, entry_price=None, **_k):
        calls.append(entry_price)
        if entry_price and abs(entry_price - _VENUE_ENTRY) / entry_price <= 0.001:
            return dict(_REC)
        return None

    status_calls: list = []

    def _status(cfg, row):
        status_calls.append(row.get("id"))
        return entry_status

    om._SWEEP_VENUE_ENTRY_CACHE.clear()
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile",
                        lambda: {"bybit_2": {"account_id": "bybit_2"}})
    import src.units.accounts.clients as _clients
    monkeypatch.setattr(_clients, "account_closed_pnl_for_trade", _lookup,
                        raising=False)
    monkeypatch.setattr(om, "_entry_order_status_for", _status)
    monkeypatch.setattr(om, "_classify_broker_exit", lambda *a, **k: None)
    summary = om._sweep_pending_pnl_from_bybit(_DB())
    return summary, captured, calls, status_calls, _DB()


def test_a_slipped_entry_is_retried_against_the_venue_fill(tmp_path, monkeypatch):
    summary, captured, calls, _s, _db = _run(
        tmp_path, monkeypatch, entry_status={"avg_price": _VENUE_ENTRY})
    assert calls == [0.2492, _VENUE_ENTRY]
    assert summary["filled"] == 1
    upd = captured[6565]
    assert upd["pnl"] == -3.28194216
    assert upd["exit_price"] == 0.2432
    assert '"exit_price_source": "bybit_closed_pnl"' in upd["notes"]


def test_a_matching_journal_entry_costs_no_extra_call(tmp_path, monkeypatch):
    summary, captured, calls, status_calls, _db = _run(
        tmp_path, monkeypatch, entry_status={"avg_price": _VENUE_ENTRY},
        journal_entry=_VENUE_ENTRY)
    assert calls == [_VENUE_ENTRY]
    assert status_calls == []
    assert summary["filled"] == 1


def test_no_venue_fill_leaves_the_row_pending_not_fabricated(tmp_path, monkeypatch):
    summary, captured, calls, _s, _db = _run(
        tmp_path, monkeypatch, entry_status={"avg_price": None})
    assert calls == [0.2492]
    assert captured == {}
    assert summary["still_pending"] == 1


def test_a_failed_status_read_is_not_cached(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, entry_status=None)
    assert 6565 not in om._SWEEP_VENUE_ENTRY_CACHE


def test_an_answered_status_is_cached(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, entry_status={"avg_price": None})
    assert om._SWEEP_VENUE_ENTRY_CACHE.get(6565, "missing") is None
