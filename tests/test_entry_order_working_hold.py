"""A journal row is never closed while its ENTRY ORDER is still working at the venue.

PI-20261118-JFWRQYOV-0004, root cause. Measured 2026-11-18/19 from /api/diag/journal,
/api/diag/alpaca_order_history and /api/diag/exchange_positions:

* alpaca_paper QQQ short: venue 1981 vs journal 2. 1981 = 1182 (row 7712, order
  d20245bd sent 2026-11-17 21:01:54Z AFTER the close, filled 2026-11-18 14:34:31Z)
  + 735 (7780) + 55 (7781) + 7 (7782) + 2 (7783, the only row still open). Each of
  7712/7780/7781/7782 was closed ``exchange_flat_reconciled`` ~6.5 min after it
  opened, while its order was still queued.
* alpaca_portfolio SLV short: venue 877 vs journal 6 (seven rows 7750..7774, same
  shape; repaired 2026-11-19 04:04Z by reopen-filled-closed-rows).

#26862 (merged 2026-11-18 19:04Z) held the snapshot reconciler on a POSITIVE
"still pending" only. Two holes stayed, and this file pins both shut:

1. an UNREADABLE order read (Alpaca 5xx / network) still closed the row;
2. the stuck-strategy watchdog (package idle >= 30 min, flat on two reads) has no
   entry-order check at all, so an overnight-queued entry like 7712 (13.5 h in the
   queue) is closed there once the snapshot path holds it.

The venue is simulated at the HTTP layer (``requests.request`` inside
``alpaca_client``) with Alpaca's real ``GET /v2/orders/{id}`` bodies, so the real
``AlpacaClient.order_pending`` -> ``account_entry_order_pending`` chain runs.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple
from unittest.mock import patch

import pytest

from src.runtime import order_monitor as om
from src.units.accounts.alpaca_client import AlpacaClient
from src.units.db.database import Database

ACCOUNT = "alpaca_paper"
_CFG = {"account_id": ACCOUNT, "exchange": "alpaca", "mode": "live"}
#: The real 2026-11-17 after-close QQQ entry (row 7712).
QQQ_7712 = "d20245bd-de47-4711-b38f-d551d105866a"
#: The real 2026-11-18 pre-open QQQ entry (row 7780).
QQQ_7780 = "a599695c-4fd8-4f3d-ae1f-d907e7ba7c6a"


def _alpaca_order(order_id: str, *, status: str, qty: int, filled_qty: int = 0,
                  filled_avg_price: Optional[str] = None,
                  submitted_at: str = "2026-11-17T21:01:54.373311Z",
                  filled_at: Optional[str] = None) -> Dict[str, Any]:
    """A ``GET /v2/orders/{id}`` body in Alpaca's shape (bracket SELL to open)."""
    leg_status = "held" if status in ("accepted", "new", "pending_new") else "new"
    return {
        "id": order_id,
        "client_order_id": "jta-" + order_id[:8],
        "created_at": submitted_at,
        "updated_at": filled_at or submitted_at,
        "submitted_at": submitted_at,
        "filled_at": filled_at,
        "expired_at": None,
        "canceled_at": None,
        "failed_at": None,
        "replaced_at": None,
        "replaced_by": None,
        "replaces": None,
        "asset_id": "b28f4066-5c6d-479b-a2af-85dc1a8f16fb",
        "symbol": "QQQ",
        "asset_class": "us_equity",
        "notional": None,
        "qty": str(qty),
        "filled_qty": str(filled_qty),
        "filled_avg_price": filled_avg_price,
        "order_class": "bracket",
        "order_type": "market",
        "type": "market",
        "side": "sell",
        "position_intent": "sell_to_open",
        "time_in_force": "gtc",
        "limit_price": None,
        "stop_price": None,
        "status": status,
        "extended_hours": False,
        "legs": [
            {"id": order_id[:-4] + "aaaa", "order_type": "limit", "type": "limit",
             "side": "buy", "position_intent": "buy_to_close", "qty": str(qty),
             "limit_price": "641.20", "status": leg_status, "order_class": "bracket"},
            {"id": order_id[:-4] + "bbbb", "order_type": "stop", "type": "stop",
             "side": "buy", "position_intent": "buy_to_close", "qty": str(qty),
             "stop_price": "668.90", "status": leg_status, "order_class": "bracket"},
        ],
    }


class _Resp:
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self._body = body
        self.content = json.dumps(body).encode()

    def json(self):
        return self._body


class FakeAlpaca:
    """Order book keyed by id. ``set(oid, None)`` = 404; ``fail()`` = HTTP 500 once."""

    def __init__(self):
        self.orders: Dict[str, Optional[Dict[str, Any]]] = {}
        self.fail_next = 0
        self.calls = 0

    def set(self, oid: str, body: Optional[Dict[str, Any]]) -> None:
        self.orders[oid] = body

    def request(self, method, url, headers=None, json=None, timeout=None):  # noqa: A002
        self.calls += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            return _Resp(500, {"code": 50010000, "message": "internal server error"})
        assert method == "GET" and "/v2/orders/" in url, (method, url)
        oid = url.rsplit("/v2/orders/", 1)[1]
        body = self.orders.get(oid)
        if body is None:
            return _Resp(404, {"code": 40410000, "message": "order not found"})
        return _Resp(200, body)


@pytest.fixture
def venue(monkeypatch):
    fake = FakeAlpaca()
    monkeypatch.setattr("src.units.accounts.alpaca_client.requests.request", fake.request)
    monkeypatch.setattr(
        "src.units.accounts.clients.alpaca_client_for",
        lambda account: AlpacaClient(api_key="k", api_secret="s"),
    )
    return fake


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "trade_journal.db"
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(db_path))
    monkeypatch.setenv("RECONCILER_CLOSE_CONFIRM_SECONDS", "0")
    monkeypatch.setattr("src.runtime.execution_diagnostics.PENDING_PINGS_DIR", tmp_path / "pings")
    monkeypatch.setattr(om, "_load_account_cfgs_for_reconcile", lambda: {ACCOUNT: _CFG})
    monkeypatch.setattr(om, "_cancel_closed_row_protection", lambda *a, **k: None)
    monkeypatch.setattr(om, "_send_reset_alert", lambda msg, caller: None)
    monkeypatch.setattr(
        "src.runtime.execution_diagnostics.enqueue_exchange_orphan_adoption", lambda **kw: None)
    for cache in (om._PENDING_SNAPSHOT_DISAPPEAR_CONFIRM, om._PENDING_ORPHAN_DISAPPEAR_CONFIRM,
                  om._PENDING_WATCHDOG_FLAT_CONFIRM, om._PENDING_CLOSE_CONFIRM,
                  om._RESET_ALERT_LATCHED, om._RESET_SUSPECT_ROWS, om._RESET_SUSPECT_FLAGGED):
        cache.clear()
    yield Database(db_path=str(db_path))
    for cache in (om._PENDING_SNAPSHOT_DISAPPEAR_CONFIRM, om._PENDING_WATCHDOG_FLAT_CONFIRM,
                  om._RESET_SUSPECT_ROWS):
        cache.clear()


def _open_row(db, *, broker_order_id: str, size: float, pkg: str) -> int:
    tid = db.insert_trade({
        "timestamp": "2026-11-17T21:01:57+00:00",
        "created_at": "2026-11-17T21:01:57+00:00",
        "symbol": "QQQ",
        "direction": "short",
        "entry_price": 656.65,
        "stop_loss": 668.90,
        "take_profit_1": 641.20,
        "position_size": size,
        "setup_type": "qqq_pullback_1h",
        "strategy_name": "qqq_pullback_1h",
        "status": "open",
        "is_backtest": 0,
        "account_id": ACCOUNT,
        "notes": "{}",
        "broker_order_id": broker_order_id,
        "order_package_id": pkg,
    })
    conn = db.connect()
    try:
        # Package idle 45 min: past the 30-min stuck-strategy floor.
        conn.execute(
            "INSERT INTO order_packages "
            "(order_package_id, strategy_name, symbol, direction, entry, sl, tp, "
            " confidence, status, linked_trade_id, meta, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?, datetime('now','-45 minutes'), "
            " datetime('now','-45 minutes'))",
            (pkg, "qqq_pullback_1h", "QQQ", "short", 656.65, 668.90, 641.20, 0.5,
             "open", tid, "{}"),
        )
        conn.commit()
    finally:
        conn.close()
    return tid


def _status(db, tid: int) -> Tuple[str, Optional[str]]:
    conn = db.connect()
    try:
        return tuple(conn.execute(
            "SELECT status, exit_reason FROM trades WHERE id=?", (tid,)).fetchone())
    finally:
        conn.close()


def _flat():
    """The venue holds no QQQ: the batch list is empty and the per-symbol read 404s."""
    return (
        patch("src.units.accounts.clients.account_open_positions", return_value=[]),
        patch("src.units.accounts.clients.account_position_present", return_value=False),
        patch.object(om, "_recover_close_from_broker_pnl", return_value=None),
    )


def _one_tick(db) -> Dict[str, Dict[str, int]]:
    """The two flat-close passes a monitor tick runs for an Alpaca row."""
    a, b, c = _flat()
    with a, b, c:
        return {"snapshot": om._reconcile_orphan_exchange_positions(db),
                "watchdog": om._watchdog_stuck_strategies(db)}


# ── the replay ────────────────────────────────────────────────────────────────


def test_replay_qqq_7712_overnight_queued_entry_is_never_closed(db, venue):
    """7712: sent 21:01:54Z after the close, queued 13.5 h, filled 14:34:31Z.

    Old code closed it on the snapshot path at 21:08Z. #26862 code holds the snapshot
    path but (a) closes on one unreadable read and (b) lets the watchdog close it.
    """
    tid = _open_row(db, broker_order_id=QQQ_7712, size=1182, pkg="pkg-bcc6fb66b53e48f4")
    venue.set(QQQ_7712, _alpaca_order(QQQ_7712, status="accepted", qty=1182))

    for _ in range(4):  # the overnight queue: many ticks, every one flat
        _one_tick(db)
        assert _status(db, tid) == ("open", None)

    venue.fail_next = 4  # an Alpaca 5xx burst while still queued
    for _ in range(2):
        s = _one_tick(db)
        assert _status(db, tid) == ("open", None), "an unreadable order read closed the row"
    assert s["snapshot"].get("snapshot_order_unreadable", 0) >= 1
    venue.fail_next = 0

    venue.set(QQQ_7712, _alpaca_order(QQQ_7712, status="new", qty=1182))  # the open
    s = _one_tick(db)
    assert _status(db, tid) == ("open", None)
    assert s["watchdog"].get("deferred_entry_order_pending", 0) >= 1, {k: v for k, v in s["watchdog"].items() if v}


def test_replay_qqq_7780_preopen_reentry_keeps_the_monocle_gate_closed(db, venue):
    """7780: sent 14:01:46Z pre-open, closed 14:08:22Z on the old code -> re-fire x3."""
    tid = _open_row(db, broker_order_id=QQQ_7780, size=735, pkg="pkg-c0871a50c6d94f26")
    venue.set(QQQ_7780, _alpaca_order(QQQ_7780, status="accepted", qty=735,
                                      submitted_at="2026-11-18T14:01:46.569085Z"))
    for _ in range(3):
        _one_tick(db)
    assert _status(db, tid) == ("open", None)
    conn = db.connect()
    try:
        pkg_status = conn.execute(
            "SELECT status FROM order_packages WHERE order_package_id='pkg-c0871a50c6d94f26'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert pkg_status == "open", "package freed -> the same 1h signal re-fires"


# ── the closes that must still happen ────────────────────────────────────────


def test_filled_entry_then_flat_still_closes(db, venue):
    """Filled at the open, then its stop fired: genuinely flat -> closed."""
    tid = _open_row(db, broker_order_id=QQQ_7780, size=735, pkg="pkg-c0871a50c6d94f26")
    venue.set(QQQ_7780, _alpaca_order(
        QQQ_7780, status="filled", qty=735, filled_qty=735, filled_avg_price="661.584735",
        filled_at="2026-11-18T14:33:38.706208Z"))
    _one_tick(db)
    _one_tick(db)
    assert _status(db, tid)[0] == "closed"


def test_canceled_unfilled_entry_still_closes(db, venue):
    tid = _open_row(db, broker_order_id=QQQ_7780, size=735, pkg="pkg-c0871a50c6d94f26")
    body = _alpaca_order(QQQ_7780, status="canceled", qty=735)
    body["canceled_at"] = "2026-11-18T14:20:00Z"
    venue.set(QQQ_7780, body)
    _one_tick(db)
    _one_tick(db)
    assert _status(db, tid)[0] == "closed"


def test_order_unknown_to_venue_404_still_closes(db, venue):
    tid = _open_row(db, broker_order_id=QQQ_7780, size=735, pkg="pkg-c0871a50c6d94f26")
    venue.set(QQQ_7780, None)
    _one_tick(db)
    _one_tick(db)
    assert _status(db, tid)[0] == "closed"


# ── the helper's contract ────────────────────────────────────────────────────


def test_hold_helper_contract(venue):
    venue.set("o-pend", _alpaca_order("o-pend", status="pending_new", qty=1))
    venue.set("o-fill", _alpaca_order("o-fill", status="filled", qty=1, filled_qty=1))
    assert om._entry_order_hold(_CFG, "o-pend") == "pending"
    assert om._entry_order_hold(_CFG, "o-fill") is None
    assert om._entry_order_hold(_CFG, "o-missing") is None  # 404
    venue.fail_next = 1
    assert om._entry_order_hold(_CFG, "o-pend") == "unreadable"
    before = venue.calls
    # No real entry order: never looked up, never held.
    for oid in (None, "", "rejected-765dcc6d1cb3", "dry-abc"):
        assert om._entry_order_hold(_CFG, oid) is None
    # Integrations that cannot answer: never looked up, never held.
    for cfg in ({"account_id": "ib_paper", "exchange": "interactive_brokers", "mode": "live"},
                {"account_id": "bybit_2", "exchange": "bybit", "mode": "live"},
                {"account_id": "alpaca_x", "exchange": "alpaca", "mode": "dry_run"}):
        assert om._entry_order_hold(cfg, "o-pend") is None
    assert venue.calls == before

