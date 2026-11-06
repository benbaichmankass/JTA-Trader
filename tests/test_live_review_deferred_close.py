"""ALPACA-LIVE-MECHANICS (2026-11-06): a venue-DEFERRED close is retried, never dropped.

Incident: pkg-58b6ef451e684836 (ml_entry SPY, alpaca_paper). The rows watcher dispatched an LTR close at 03:27Z
under MD-LTR-PAPER-AUTO; AlpacaClient.close() returned retCode 2 ("us_equity market closed - exit deferred to next
session"), the apply mapped it to `refused` (exit 2), and the watcher marked the row seen: the close was never
retried and the row stayed `recommended` with no applier.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.ops import live_review_apply as lra
from src.runtime import live_review_intent as lri
from src.runtime import live_review_rows as rows_lib
from src.runtime import live_review_rows_watch as w

T0 = datetime(2026, 11, 6, 3, 27, tzinfo=timezone.utc)
TIP = "b" * 40


# ── the pure rule ─────────────────────────────────────────────────────────────────────────────────────────
def test_deferred_step_waits_then_retries_then_expires():
    p = lri.deferred_pending(T0, T0, 1)
    assert p["deferred"] is True and p["attempts"] == 1
    assert lri.deferred_step(p, T0, T0 + timedelta(seconds=lri.DEFERRED_RETRY_S - 1)) == "wait"
    assert lri.deferred_step(p, T0, T0 + timedelta(seconds=lri.DEFERRED_RETRY_S)) == "retry"
    assert lri.deferred_step(p, T0, T0 + timedelta(seconds=lri.DEFERRED_MAX_S)) == "expired"
    assert lri.deferred_step(None, T0, T0) == "retry"


# ── the apply: retCode 2 is deferred, not refused ─────────────────────────────────────────────────────────
class _DB:
    def __init__(self):
        self.updates = []

    def get_trades(self, filters=None):
        return []

    def update_trade(self, *a, **k):
        self.updates.append((a, k))

    def update_order_package(self, *a, **k):
        self.updates.append((a, k))


def _leg():
    return {"row": {"id": 7, "account_id": "alpaca_paper", "symbol": "SPY", "status": "open"}}


def _send(monkeypatch, resp):
    from src.runtime import order_monitor as om
    monkeypatch.setattr(om, "_send_close_to_exchange", lambda t: resp)
    monkeypatch.setattr(lra, "_accounts", lambda: {"alpaca_paper": {"exchange": "alpaca"}})


def test_market_closed_close_is_deferred_and_journals_nothing(monkeypatch):
    _send(monkeypatch, {"ok": False, "error": "us_equity market closed — exit deferred to next session",
                        "exchange_response": {"retCode": 2, "retMsg": "x"}})
    db = _DB()
    res = lra._exec_alpaca_close(db, _leg(), {"order_package_id": "pkg-58b6ef451e684836"}, None)
    assert res["result"] == lri.X_DEFERRED and "deferred" in res["detail"]
    assert db.updates == []


def test_a_real_venue_refusal_stays_refused(monkeypatch):
    _send(monkeypatch, {"ok": False, "error": "insufficient qty", "exchange_response": {"retCode": 1}})
    res = lra._exec_alpaca_close(_DB(), _leg(), {"order_package_id": "pkg-x"}, None)
    assert res["result"] == lra.X_REFUSED


# ── the rows watcher: a deferral stays pending and is re-dispatched ───────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_advice_only(monkeypatch):
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", ())


def _row(rid):
    return {"review_id": rid, "order_package_id": "pkg-58b6ef451e684836", "reviewed_at": "2026-11-06T03:20:00Z",
            "recommendation": {"action": "close", "level": None}, "disposition": {"route": "recommended"}}


class _Git:
    def __init__(self, rows):
        self.text = "\n".join(json.dumps(r) for r in rows)

    def __call__(self, *args, timeout=30):
        if args[0] == "fetch":
            return 0, ""
        if args[0] == "rev-parse":
            return 0, TIP
        if args[0] == "ls-tree":
            return 0, ""
        if args[0] == "show":
            return 0, self.text
        return 1, "unexpected"


class _Dispatch:
    def __init__(self, exits):
        self.exits, self.calls = list(exits), []

    def __call__(self, rid, ref):
        self.calls.append(rid)
        code = self.exits.pop(0) if len(self.exits) > 1 else self.exits[0]
        return {"exit": code, "verdict": "dispatched", "detail": "venue deferred" if code == 4 else None, "lines": []}


def test_watcher_keeps_a_deferred_close_and_retries_it_next_session(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "dispatchable", lambda row: None)
    d = _Dispatch([lri.EXIT_DEFERRED, lri.EXIT_DEFERRED, 0])
    w.run_pass(git=_Git([]), dispatch=d, now_fn=lambda: T0, logs=tmp_path)            # seed
    g = _Git([_row("LR-close")])
    w.run_pass(git=g, dispatch=d, now_fn=lambda: T0, logs=tmp_path)                    # deferred
    w.run_pass(git=g, dispatch=d, now_fn=lambda: T0 + timedelta(minutes=5), logs=tmp_path)   # not due yet
    assert d.calls == ["LR-close"]
    state = json.loads((tmp_path / "rows_watch_state.json").read_text())
    assert "LR-close" not in state["seen"] and state["pending"]["LR-close"]["deferred"] is True
    w.run_pass(git=g, dispatch=d, now_fn=lambda: T0 + timedelta(minutes=16), logs=tmp_path)  # due: deferred again
    w.run_pass(git=g, dispatch=d, now_fn=lambda: T0 + timedelta(hours=6, minutes=5), logs=tmp_path)  # session: done
    assert d.calls == ["LR-close"] * 3
    state = json.loads((tmp_path / "rows_watch_state.json").read_text())
    assert "LR-close" in state["seen"] and "LR-close" not in state["pending"]


def test_watcher_expires_a_deferral_after_the_bound_with_one_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "dispatchable", lambda row: None)
    alerts = []
    d = _Dispatch([lri.EXIT_DEFERRED])
    kw = dict(dispatch=d, logs=tmp_path, alert=lambda t: alerts.append(t) or True)
    w.run_pass(git=_Git([]), now_fn=lambda: T0, **kw)
    g = _Git([_row("LR-close")])
    w.run_pass(git=g, now_fn=lambda: T0, **kw)
    w.run_pass(git=g, now_fn=lambda: T0 + timedelta(seconds=lri.DEFERRED_MAX_S + 1), **kw)
    recs = [json.loads(x) for x in (tmp_path / "rows_watch.jsonl").read_text().splitlines()]
    assert recs[-1]["verdict"] == "expired" and len(alerts) == 1
    w.run_pass(git=g, now_fn=lambda: T0 + timedelta(seconds=lri.DEFERRED_MAX_S + 999), **kw)
    assert len(d.calls) == 2
