"""One direction per (account, symbol) across legs, at prop ticket emission (manager 2026-11-09 04:07Z).

The incident: 2026-11-09 04:02Z ``ml_entry`` fired a SOL LONG (pkg-6aac531720874a00) and ticketed breakout_2 / tradeify_1 / velotrade_1, each holding an OPEN
trend_donchian SOL SHORT (6.82 @ 87.64). breakout_2's phone filled the buy form and was stopped only by the ``cushion_unknown`` read-back gate; the reticket guard
looked at the SAME direction only. Every case runs against an isolated ``trade_journal.db`` through the real journal read.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

NOW = datetime(2026, 11, 9, 4, 2, 29, tzinfo=timezone.utc)
ACCOUNTS = ("breakout_2", "tradeify_1", "velotrade_1")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    return tmp_path


def _short_sol_position(acct: str, *, strategy: str = "trend_donchian_sol_4h", ticket: str = "prop-manual-aaaaaaaaaaaa") -> None:
    """The live state: an OPEN trend SOL SHORT (ticket placed + an open fill row)."""
    from src.prop import prop_journal

    prop_journal.record_ticket({
        "ticket_id": ticket, "account_id": acct, "strategy": strategy, "symbol": "SOLUSDT", "direction": "short",
        "entry": 87.64, "sl": 91.0, "tp": 80.0, "qty": 6.82, "risk_usd": 17.5,
        "signal_time": (NOW - timedelta(hours=3)).isoformat(), "valid_until": (NOW - timedelta(hours=2)).isoformat(), "status": "placed",
    })
    prop_journal.insert_fill({
        "account_id": acct, "ticket_id": ticket, "symbol": "SOLUSDT", "direction": "short", "qty": 6.82, "entry_price": 87.64,
        "status": "open", "external_order_id": f"inferred-{ticket}",
    })


def _reason(acct: str, direction: str = "long", strategy: str = "ml_entry", symbol: str = "SOLUSDT"):
    from src.prop.breakout_executor import _opposite_direction_block_reason

    return _opposite_direction_block_reason(acct, symbol, direction, strategy, now=NOW)


@pytest.mark.parametrize("acct", ACCOUNTS)
def test_the_incident_ml_entry_long_against_an_open_trend_short_is_blocked(env, acct):
    _short_sol_position(acct)
    r = _reason(acct)
    assert r and r.startswith("opposite_"), r
    assert "trend_donchian_sol_4h" in r and "short" in r


@pytest.mark.parametrize("acct", ACCOUNTS)
def test_emission_journals_a_suppressed_row_and_never_pushes(env, acct):
    from src.prop import breakout_executor as BE
    from src.prop import prop_journal

    _short_sol_position(acct)
    pushed = []
    order = {"symbol": "SOLUSDT", "direction": "long", "entry": 87.43, "sl": 85.08, "tp": 90.95, "strategy": "ml_entry",
             "order_package_id": "pkg-6aac531720874a00"}
    tid = BE.emit_prop_ticket(order, {"account_id": acct}, timeframe="1h", _emitter=lambda *a, **k: pushed.append(a))
    assert tid.startswith(BE.MANUAL_FILL_PREFIX) and pushed == []
    rows = [t for t in prop_journal.list_tickets(account_id=acct, limit=50) if t["ticket_id"] == tid]
    assert len(rows) == 1 and rows[0]["status"] == "suppressed"
    assert rows[0]["message"].startswith("opposite_direction_blocked")


def test_negative_control_no_opposite_position_does_not_block(env):
    assert _reason("breakout_2") is None                          # empty journal
    _short_sol_position("breakout_2")
    assert _reason("breakout_2", direction="short", strategy="ml_entry") is None   # same direction is the reticket guard's job
    assert _reason("breakout_2", symbol="ETHUSDT") is None                          # another symbol
    assert _reason("tradeify_1") is None                                            # another account


def test_a_same_leg_reversal_is_not_blocked(env):
    _short_sol_position("breakout_2", strategy="trend_donchian_sol_4h")
    assert _reason("breakout_2", direction="long", strategy="trend_donchian_sol_4h") is None


def test_a_live_outstanding_opposite_ticket_blocks_even_without_a_fill(env):
    from src.prop import prop_journal

    prop_journal.record_ticket({
        "ticket_id": "prop-manual-bbbbbbbbbbbb", "account_id": "tradeify_1", "strategy": "trend_donchian_sol_4h", "symbol": "SOLUSDT",
        "direction": "short", "entry": 87.6, "sl": 91.0, "tp": 80.0, "signal_time": NOW.isoformat(),
        "valid_until": (NOW + timedelta(hours=1)).isoformat(), "status": "emitted",
    })
    assert (_reason("tradeify_1") or "").startswith("opposite_outstanding_ticket:emitted")


def test_an_expired_unplaced_opposite_ticket_does_not_block(env):
    from src.prop import prop_journal

    prop_journal.record_ticket({
        "ticket_id": "prop-manual-cccccccccccc", "account_id": "tradeify_1", "strategy": "trend_donchian_sol_4h", "symbol": "SOLUSDT",
        "direction": "short", "entry": 87.6, "sl": 91.0, "tp": 80.0, "signal_time": (NOW - timedelta(hours=3)).isoformat(),
        "valid_until": (NOW - timedelta(hours=2)).isoformat(), "status": "emitted",
    })
    assert _reason("tradeify_1") is None


def test_an_unreadable_journal_blocks_this_entry_with_a_named_reason(env, monkeypatch):
    from src.prop import prop_journal

    def boom(**k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(prop_journal, "list_tickets", boom)
    assert _reason("breakout_2") == "opposite_check_unreadable: RuntimeError"
