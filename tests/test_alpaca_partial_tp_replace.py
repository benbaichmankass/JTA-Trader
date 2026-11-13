"""ALPACA-PARTIAL-TP-STOP-GAP (2026-11-13, manager "build (a)").

On a take-profit PARTIAL fill Alpaca cancels the bracket's stop leg; the still-resting target holds
the remaining shares, so the existing additive OCO is refused and retried only every 900 s. The
fix replaces OUR OWN target: cancel -> confirm -> OCO (else a plain stop, else CRITICAL every tick).

The fake venue is alpaca_paper QLD 7142 at 2026-11-13 15:20:31Z (from /api/diag/alpaca_order_history):
short 77 @81.08 (bracket parent 63e28d2a...), TP buy-limit 77 @77.76 partially filled 39, stop
buy-stop 77 @83.27 CANCELED by the venue, venue holding 38. Driven end to end through the real
sweep (_check_broker_naked_equity_positions), one test per hard requirement.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from src.runtime import order_monitor as om
from src.units.accounts.alpaca_client import AlpacaClient

PARENT = "63e28d2a-f5c1-42d4-8654-14b9e902eacb"
TP_ID = "c03de97f-dfa1-4803-a66b-7d10c8ca9a81"
STOP_ID = "bae72f61-aa51-40aa-8f24-8f43a6a71b8d"


class _Venue(AlpacaClient):
    """QLD after a partial TP. Knobs: cancel_result (canceled|filled|stuck), oco_ok, stop_ok,
    stop_status (the bracket's stop leg), held (venue holding)."""

    def __init__(self, *, held=38.0, cancel_result="canceled", oco_ok=True, stop_ok=True,
                 stop_status="canceled", tp_status="partially_filled", order_class="bracket"):
        self.api_key, self.api_secret = "k", "s"
        self.held = held
        self.cancel_result, self.oco_ok, self.stop_ok = cancel_result, oco_ok, stop_ok
        self.stop_status, self.tp_status, self.order_class = stop_status, tp_status, order_class
        self.tp_cancelled = False
        self.calls: list = []

    # the target / stop legs as the venue reports them right now
    def _tp_leg(self):
        status = self.tp_status
        if self.tp_cancelled:
            status = {"canceled": "canceled", "filled": "filled", "stuck": "pending_cancel"}[
                self.cancel_result]
        return {"id": TP_ID, "symbol": "QLD", "order_class": "bracket", "type": "limit",
                "side": "buy", "qty": "77", "filled_qty": "77" if status == "filled" else "39",
                "limit_price": "77.76", "status": status, "legs": None}

    def _stop_leg(self):
        return {"id": STOP_ID, "symbol": "QLD", "order_class": "bracket", "type": "stop",
                "side": "buy", "qty": "77", "stop_price": "83.27", "status": self.stop_status,
                "legs": None}

    def _parent(self):
        return {"id": PARENT, "symbol": "QLD", "order_class": self.order_class, "type": "market",
                "side": "sell", "qty": "77", "filled_qty": "77", "status": "filled",
                "submitted_at": "2026-11-12T20:02:27.680831Z",
                "legs": [self._tp_leg(), self._stop_leg()]}

    def _request(self, method, path, json_body=None):  # type: ignore[override]
        self.calls.append((method, path, json_body))
        if method == "GET" and path.startswith("/v2/positions/"):
            if self.held <= 0:
                return {"retCode": 404, "retMsg": "position does not exist"}
            return {"retCode": 0, "result": {"symbol": "QLD", "qty": str(self.held),
                                             "side": "short", "current_price": "77.80"}}
        if method == "GET" and "status=open" in path:
            tp = self._tp_leg()
            return {"retCode": 0, "result": [tp] if tp["status"] in (
                "new", "partially_filled", "pending_cancel") else []}
        if method == "GET" and "status=closed" in path:
            return {"retCode": 0, "result": [self._parent()]}
        if method == "GET" and path.startswith(f"/v2/orders/{PARENT}"):
            return {"retCode": 0, "result": self._parent()}
        if method == "GET" and path == f"/v2/orders/{TP_ID}":
            return {"retCode": 0, "result": self._tp_leg()}
        if method == "DELETE" and path == f"/v2/orders/{TP_ID}":
            self.tp_cancelled = True
            if self.cancel_result == "filled":
                self.held = 0.0
            return {"retCode": 0, "result": {}}
        if method == "POST":
            b = json_body or {}
            if b.get("order_class") == "oco":
                return ({"retCode": 0, "result": {"id": "oco-new"}} if self.oco_ok
                        else {"retCode": 403, "retMsg": "insufficient qty available"})
            if b.get("type") == "stop":
                return ({"retCode": 0, "result": {"id": "stop-new"}} if self.stop_ok
                        else {"retCode": 403, "retMsg": "stop refused"})
        return {"retCode": 500, "retMsg": f"unrouted {method} {path}"}

    def latest_trade(self, symbol):
        return {"price": 77.80, "age_s": 5.0}

    def latest_quote(self, symbol):
        return {"bid": 77.79, "ask": 77.81}

    def positions(self):
        return [] if self.held <= 0 else [{"symbol": "QLD", "qty": str(self.held), "side": "short"}]

    def posts(self):
        return [b for m, _p, b in self.calls if m == "POST"]

    def deletes(self):
        return [p for m, p, _b in self.calls if m == "DELETE"]


class _Db:
    def __init__(self, path):
        self.path = str(path)
        self.stamps: list = []

    def connect(self):
        return sqlite3.connect(self.path)

    def update_trade(self, tid, upd):
        c = sqlite3.connect(self.path)
        c.execute("UPDATE trades SET status=?, notes=? WHERE id=?",
                  (upd.get("status"), upd.get("exit_reason"), tid))
        c.commit()
        c.close()

    def stamp_protection_repair(self, tid, kind, verified="unverified"):
        self.stamps.append((tid, kind, verified))


def _make(tmp_path, monkeypatch, account="alpaca_paper", rows=None, broker_order_id=PARENT):
    path = tmp_path / "j.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT,"
        " direction TEXT, position_size REAL, stop_loss REAL, take_profit_1 REAL,"
        " created_at TEXT, notes TEXT, status TEXT, is_backtest INTEGER DEFAULT 0,"
        " broker_order_id TEXT);"
        "CREATE TABLE order_packages (order_package_id TEXT, symbol TEXT,"
        " direction TEXT, sl REAL, tp REAL, created_at TEXT);")
    rows = rows or [(7142, account, "QLD", "short", 77.0, 83.27883929, 77.76392857,
                     "2026-11-12T20:02:30+00:00", broker_order_id)]
    conn.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,NULL,'open',0,?)", rows)
    conn.commit()
    conn.close()
    monkeypatch.setattr(om, "_alert_state_path", lambda kind: tmp_path / f"{kind}.json")
    monkeypatch.setattr("src.bot.data_loaders.list_accounts",
                        lambda: [{"account_id": a, "exchange": "alpaca"}
                                 for a in ("alpaca_paper", "alpaca_live", "alpaca_portfolio")])
    pages: list = []
    monkeypatch.setattr("src.runtime.outcomes.report", lambda *a, **k: pages.append((a, k)))
    for name in ("_emit_partial_stop_coverage_alert", "_emit_target_naked_alert"):
        monkeypatch.setattr(om, name, lambda **kw: None)
    monkeypatch.setattr(om, "is_active_close", lambda *a: False)
    monkeypatch.setattr(om, "_capture_fill_details", lambda *a, **k: None)
    monkeypatch.setattr(om, "_cascade_close_linked_package", lambda *a, **k: True)
    monkeypatch.setattr("src.runtime.market_hours.us_equity_session", lambda *a, **k: "rth")
    log = tmp_path / "alpaca_partial_tp_replace.jsonl"
    monkeypatch.setattr(om, "_alpaca_partial_tp_log_path", lambda: str(log))
    # no real waiting in tests: one confirm read, then the verdict
    monkeypatch.setattr(AlpacaClient, "cancel_order_confirmed",
                        lambda self, oid, **kw: _ORIG_CANCEL(self, oid, timeout_s=0.0,
                                                             poll_s=0.0, sleep=lambda s: None))
    om._PROTECTION_UNREADABLE_STREAK.clear()
    om._ALPACA_TOPUP_ATTEMPTS.clear()
    om._ALPACA_BREACH_DEFERRALS.clear()
    om._ALPACA_PARTIAL_TP_PENDING.clear()
    return _Db(path), pages, log


_ORIG_CANCEL = AlpacaClient.cancel_order_confirmed


def _use(monkeypatch, venue):
    monkeypatch.setattr("src.units.accounts.clients.alpaca_client_for", lambda acc: venue)


def _steps(log):
    if not log.exists():
        return []
    return [json.loads(x) for x in log.read_text().splitlines() if x.strip()]


def _kinds(pages):
    return [k.get("kind") for _a, k in pages]


# ── requirement 2: cancel -> confirm -> OCO at the row's levels for the held qty ───────────────
def test_partial_tp_is_replaced_by_an_oco_for_the_held_qty(tmp_path, monkeypatch):
    db, _pages, _log = _make(tmp_path, monkeypatch)
    v = _Venue()
    _use(monkeypatch, v)
    s = om._check_broker_naked_equity_positions(db)
    assert s["partial_tp_oco_placed"] == 1
    assert v.deletes() == [f"/v2/orders/{TP_ID}"]          # OUR target, by id
    oco = [b for b in v.posts() if b.get("order_class") == "oco"]
    assert len(oco) == 1 and oco[0]["qty"] == "38" and oco[0]["side"] == "buy"
    assert oco[0]["stop_loss"]["stop_price"] == "83.28"
    assert oco[0]["take_profit"]["limit_price"] == "77.76"
    # the cancel was CONFIRMED (re-read of the order) BEFORE the OCO was posted
    seq = [(m, p) for m, p, _b in v.calls]
    i_del = seq.index(("DELETE", f"/v2/orders/{TP_ID}"))
    i_get = seq.index(("GET", f"/v2/orders/{TP_ID}"), i_del)
    i_post = next(i for i, (m, _p) in enumerate(seq) if m == "POST")
    assert i_del < i_get < i_post
    assert db.stamps == [(7142, "partial_tp_replace", "unverified")]


# ── requirement 1: SCOPE ────────────────────────────────────────────────────────────────────────
def test_a_resting_stop_leg_means_not_our_case(tmp_path, monkeypatch):
    db, _pages, log = _make(tmp_path, monkeypatch)
    v = _Venue(stop_status="held")          # the bracket's stop still rests
    _use(monkeypatch, v)
    om._check_broker_naked_equity_positions(db)
    assert f"/v2/orders/{TP_ID}" not in v.deletes()
    assert not any(st.get("step") == "detect" for st in _steps(log))


def test_no_broker_order_id_means_no_cancel(tmp_path, monkeypatch):
    db, _pages, _log = _make(tmp_path, monkeypatch, broker_order_id=None)
    v = _Venue()
    _use(monkeypatch, v)
    om._check_broker_naked_equity_positions(db)
    assert v.deletes() == []                # never "any open limit on the symbol"


def test_two_rows_on_the_symbol_is_ambiguous_and_falls_back(tmp_path, monkeypatch):
    rows = [(7142, "alpaca_paper", "QLD", "short", 77.0, 83.27883929, 77.76392857,
             "2026-11-12T20:02:30+00:00", PARENT),
            (7150, "alpaca_paper", "QLD", "short", 10.0, 83.5, 77.0,
             "2026-11-12T21:00:00+00:00", "other-parent")]
    db, _pages, _log = _make(tmp_path, monkeypatch, rows=rows)
    v = _Venue(held=48.0)
    _use(monkeypatch, v)
    om._check_broker_naked_equity_positions(db)
    assert v.deletes() == []


def test_parent_not_a_bracket_is_not_our_case(tmp_path, monkeypatch):
    db, _pages, _log = _make(tmp_path, monkeypatch)
    v = _Venue(order_class="oco")
    _use(monkeypatch, v)
    om._check_broker_naked_equity_positions(db)
    assert v.deletes() == []


# ── requirement 3: never leave it naked ─────────────────────────────────────────────────────────
def test_refused_oco_falls_back_to_a_plain_stop_at_once(tmp_path, monkeypatch):
    db, pages, log = _make(tmp_path, monkeypatch)
    v = _Venue(oco_ok=False)
    _use(monkeypatch, v)
    s = om._check_broker_naked_equity_positions(db)
    assert s["partial_tp_stop_placed"] == 1
    stops = [b for b in v.posts() if b.get("type") == "stop"]
    assert len(stops) == 1 and stops[0]["qty"] == "38" and stops[0]["side"] == "buy"
    assert stops[0]["stop_price"] == "83.28" and stops[0]["time_in_force"] == "gtc"
    assert "partial_tp_stop_only" in _kinds(pages)
    assert [st["step"] for st in _steps(log)][-1] == "fallback_stop"


def test_both_refused_pages_critical_every_tick_and_retries_every_tick(tmp_path, monkeypatch):
    db, pages, _log = _make(tmp_path, monkeypatch)
    v = _Venue(oco_ok=False, stop_ok=False)
    _use(monkeypatch, v)
    s1 = om._check_broker_naked_equity_positions(db)
    assert s1["partial_tp_unprotected"] == 1
    n1 = _kinds(pages).count("partial_tp_unprotected")
    posts1 = len(v.posts())
    # next tick: the target is GONE now, yet the chain retries (no 900 s cooldown) and pages again
    s2 = om._check_broker_naked_equity_positions(db)
    assert s2["partial_tp_unprotected"] == 1
    assert _kinds(pages).count("partial_tp_unprotected") == n1 + 1
    assert len(v.posts()) > posts1
    # and once the venue accepts, it is protected and the case clears
    v.oco_ok = True
    s3 = om._check_broker_naked_equity_positions(db)
    assert s3["partial_tp_oco_placed"] == 1
    assert om._ALPACA_PARTIAL_TP_PENDING == {}


def test_a_cancel_that_is_not_confirmed_does_nothing_further_and_retries_next_tick(tmp_path,
                                                                                  monkeypatch):
    db, _pages, _log = _make(tmp_path, monkeypatch)
    v = _Venue(cancel_result="stuck")       # still pending_cancel after the timeout
    _use(monkeypatch, v)
    s = om._check_broker_naked_equity_positions(db)
    assert s["partial_tp_cancel_failed"] == 1
    assert v.posts() == []                  # nothing posted while the target may still rest
    # not throttled by the 900 s top-up cooldown: the next tick tries again
    v.cancel_result, v.tp_cancelled = "canceled", False
    s2 = om._check_broker_naked_equity_positions(db)
    assert s2["partial_tp_oco_placed"] == 1


# ── requirement 4: the cancel races a fill ──────────────────────────────────────────────────────
def test_cancel_racing_a_fill_to_flat_posts_nothing(tmp_path, monkeypatch):
    db, _pages, log = _make(tmp_path, monkeypatch)
    v = _Venue(cancel_result="filled")
    _use(monkeypatch, v)
    s = om._check_broker_naked_equity_positions(db)
    assert s["partial_tp_flat_after_cancel"] == 1
    assert v.posts() == []
    assert any(st.get("outcome") == "flat" for st in _steps(log))


# ── requirement 5: the same path on every Alpaca account, real money included ──────────────────
@pytest.mark.parametrize("account", ["alpaca_paper", "alpaca_live", "alpaca_portfolio"])
def test_same_path_on_every_alpaca_account(tmp_path, monkeypatch, account):
    db, _pages, _log = _make(tmp_path, monkeypatch, account=account)
    v = _Venue()
    _use(monkeypatch, v)
    s = om._check_broker_naked_equity_positions(db)
    assert s["partial_tp_oco_placed"] == 1


# ── requirement 6: every step journaled with its ids ────────────────────────────────────────────
def test_every_step_is_journaled_with_its_order_ids(tmp_path, monkeypatch):
    db, _pages, log = _make(tmp_path, monkeypatch)
    v = _Venue()
    _use(monkeypatch, v)
    om._check_broker_naked_equity_positions(db)
    steps = _steps(log)
    assert [st["step"] for st in steps] == ["detect", "cancel", "post_cancel_read", "oco"]
    assert steps[0]["parent_order_id"] == PARENT and steps[0]["tp_order_id"] == TP_ID
    assert steps[1]["tp_order_id"] == TP_ID and steps[1]["outcome"] == "canceled"
    assert steps[3]["oco_order_id"] == "oco-new"
    assert all(st["trade_id"] == 7142 and st["account_id"] == "alpaca_paper" for st in steps)


# ── the client primitives on their own ──────────────────────────────────────────────────────────
def test_partial_target_holding_grades_by_order_id():
    v = _Venue()
    h = v.partial_target_holding(PARENT, "short")
    assert h["state"] == "tp_only" and h["tp_order_id"] == TP_ID and h["tp_remaining"] == 38.0
    assert _Venue(stop_status="held").partial_target_holding(PARENT, "short")["state"] == "not_tp_only"
    assert v.partial_target_holding(None, "short")["state"] == "could_not_look"


def test_cancel_order_confirmed_reports_filled_and_failed():
    v = _Venue(cancel_result="filled")
    assert _ORIG_CANCEL(v, TP_ID, timeout_s=0, poll_s=0, sleep=lambda s: None)["state"] == "filled"
    v = _Venue(cancel_result="stuck")
    assert _ORIG_CANCEL(v, TP_ID, timeout_s=0, poll_s=0, sleep=lambda s: None)["state"] == "failed"
    v = _Venue()
    assert _ORIG_CANCEL(v, TP_ID, timeout_s=0, poll_s=0, sleep=lambda s: None)["state"] == "canceled"
