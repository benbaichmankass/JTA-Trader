"""Tests for the trade-lifecycle notification dispatcher (trade_events).

Covers:
- The typed FCM publish fires inline (so the journal observer hooks keep
  their synchronous-capture contract).
- Paper / live tagging in the formatted Telegram line.
- The per-trade Telegram line fires **unconditionally** (off-thread) — the
  ``TRADE_EVENT_TELEGRAM_DISABLED`` kill-switch was scrubbed 2026-07-26.
- ``notify_trade_event`` never raises even if the FCM publish blows up.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from src.runtime.mobile_push import trade_events


@pytest.fixture(autouse=True)
def _drain_telegram_threads(monkeypatch: pytest.MonkeyPatch):
    """Join every off-thread Telegram send a test started, BEFORE the test's monkeypatches are undone.

    ``notify_trade_event`` starts a daemon thread (``trade-event-telegram``) and returns. A test that does not
    wait for it leaks the thread into the NEXT test, whose stub then counts the leaked send as its own:
    ``test_telegram_send_fires_unconditionally`` saw ``['called', 'called']`` whenever it ran after
    ``test_notify_publishes_inline`` (deterministic here, timing-dependent in CI). TELEGRAM-TRIM (#23051) put an
    accounts.yaml policy read on that thread, which widened the window from ~0 to tens of milliseconds.
    Requesting ``monkeypatch`` makes this fixture's teardown run first (reverse setup order).
    """
    yield
    for t in threading.enumerate():
        if t.name == "trade-event-telegram":
            t.join(timeout=5.0)


def test_format_tags_paper_and_live() -> None:
    paper = trade_events.format_trade_event_message(
        "trade_opened",
        {"symbol": "MES", "direction": "buy", "account_class": "paper"},
    )
    live = trade_events.format_trade_event_message(
        "trade_closed",
        {"symbol": "BTCUSDT", "direction": "sell", "pnl": 3.0, "account_class": "real_money"},
    )
    assert "[paper]" in paper
    assert "[live]" in live


def test_notify_publishes_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "src.runtime.mobile_push.publish_event",
        lambda kind, payload: captured.append((kind, payload)),
    )
    # Stub the Telegram send so the unconditional off-thread line never
    # touches the network during the test.
    monkeypatch.setattr(
        "src.runtime.notify.send_telegram_direct", lambda *a, **k: None
    )

    trade_events.notify_trade_event("trade_closed", {"symbol": "BTCUSDT"})

    assert captured == [("trade_closed", {"symbol": "BTCUSDT"})]


def test_telegram_send_fires_unconditionally(monkeypatch: pytest.MonkeyPatch) -> None:
    # Post-scrub: the per-trade Telegram line always fires (best-effort,
    # off-thread). There is no longer a kill-switch to suppress it.
    monkeypatch.setattr("src.runtime.mobile_push.publish_event", lambda *a, **k: None)
    sent: list[str] = []
    monkeypatch.setattr(
        "src.runtime.notify.send_telegram_direct",
        lambda *a, **k: sent.append("called"),
    )

    trade_events.notify_trade_event("trade_opened", {"symbol": "MES"})
    # off-thread send window — the TELEGRAM-TRIM policy read (accounts.yaml) runs on
    # that thread first, so poll rather than a fixed 50 ms.
    deadline = time.time() + 5.0
    while not sent and time.time() < deadline:
        time.sleep(0.02)

    assert sent == ["called"]


def test_notify_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr("src.runtime.mobile_push.publish_event", _boom)
    monkeypatch.setattr(
        "src.runtime.notify.send_telegram_direct", lambda *a, **k: None
    )

    # Must not raise.
    trade_events.notify_trade_event("trade_closed", {"symbol": "BTCUSDT"})


def _close_payload(monkeypatch, tmp_path, pnl):
    from src.units.db import database as db_module
    db = db_module.Database(db_path=str(tmp_path / "j.db"))
    seen = []
    monkeypatch.setattr(trade_events, "notify_trade_event", lambda kind, p: seen.append((kind, p)))
    monkeypatch.setattr(db, "_fire_trade_opened_event", lambda tid: None)
    tid = db.insert_trade({"timestamp": "2026-11-14T10:00:00+00:00", "symbol": "ADAUSDT", "direction": "short", "entry_price": 0.1784, "position_size": 153220.0,
                           "status": "open", "strategy_name": "ada", "account_id": "bybit_portfolio",
                           "account_class": "paper", "is_backtest": 0})
    upd = {"status": "closed", "exit_price": 0.1607, "exit_reason": "tp"}
    if pnl is not None:
        upd["pnl"] = pnl
    db.update_trade(tid, upd)
    closes = [p for k, p in seen if k == trade_events.TRADE_CLOSED]
    assert len(closes) == 1
    return closes[0]


def test_close_alert_estimates_pnl_when_the_close_path_left_it_to_the_sweep(monkeypatch, tmp_path):
    """Trade 7003 (2026-11-14): the netting own-leg close wrote no pnl, so the alert read 'PnL —'."""
    p = _close_payload(monkeypatch, tmp_path, None)
    assert p["pnl_estimated"] is True and abs(p["pnl"] - 2711.994) < 1e-6 and p["pnl_percent"] is not None
    assert "PnL 2,711.994" in trade_events.format_trade_event_message(trade_events.TRADE_CLOSED, p)
    assert " est" in trade_events.format_trade_event_message(trade_events.TRADE_CLOSED, p)


def test_close_alert_keeps_a_journal_pnl_and_never_labels_it_est(monkeypatch, tmp_path):
    p = _close_payload(monkeypatch, tmp_path, 2700.0)
    assert p["pnl"] == 2700.0 and p["pnl_estimated"] is False
    assert " est" not in trade_events.format_trade_event_message(trade_events.TRADE_CLOSED, p)
