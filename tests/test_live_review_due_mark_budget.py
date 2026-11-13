"""DIAG-LIVE-REVIEW-DUE-SLOW / RM-AM-DUE-COULDNOTLOOK: the due route's bot-feed marks run under ONE wall-clock budget.

Before: every prop symbol and (since CONFLICTING-EXPOSURE-ALERT) every open symbol was marked by a serial network
candle fetch inside the request; the route took 19.1 s and then 502'd at ~31 s, so the live-review wake read
could_not_look while packages were due. A slow or hung feed must now cost at most the budget, and a missing mark
is labelled, never 0.
"""
from __future__ import annotations

import sqlite3
import threading
import time

from src.runtime import live_review_due as lrd
from tests.test_live_review_due import _ACC, NOW, _db, _journal, _tk


def test_bounded_marks_returns_inside_budget_and_labels_the_slow_symbol():
    release = threading.Event()

    def mark(sym):
        if sym == "SLOW":
            release.wait(5)
        return {"FAST": 10.0, "SLOW": 20.0}.get(sym)

    t0 = time.monotonic()
    marks, misses = lrd.bounded_marks(["FAST", "SLOW", "NONE"], mark, budget_s=0.3)
    took = time.monotonic() - t0
    release.set()
    assert took < 1.5
    assert marks == {"FAST": 10.0}
    assert misses["SLOW"] == "timeout" and misses["NONE"] == "unavailable"


def test_hung_symbol_is_not_stacked_one_thread_per_request():
    release = threading.Event()
    calls = []

    def mark(sym):
        calls.append(sym)
        release.wait(5)
        return 1.0

    _, m1 = lrd.bounded_marks(["HANG"], mark, budget_s=0.1)
    _, m2 = lrd.bounded_marks(["HANG"], mark, budget_s=0.1)
    release.set()
    assert m1["HANG"] == "timeout" and m2["HANG"] == "in_flight"
    assert calls == ["HANG"]
    for _ in range(50):  # the first read finishes and frees the slot
        if "HANG" not in lrd._MARK_INFLIGHT:
            break
        time.sleep(0.02)
    assert "HANG" not in lrd._MARK_INFLIGHT


def test_errors_are_labelled_and_no_source_is_explicit():
    def boom(sym):
        raise RuntimeError("gateway closed")
    _, misses = lrd.bounded_marks(["X"], boom, budget_s=1)
    assert misses["X"].startswith("error: RuntimeError")
    assert lrd.bounded_marks(["X"], None)[1] == {"X": "no_mark_source_supplied"}


def test_route_payload_answers_inside_budget_when_the_feed_hangs(tmp_path, monkeypatch):
    db = str(tmp_path / "j.db")
    _db(db, [])
    _journal(db, [])
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE prop_tickets (ticket_id, account_id, strategy, symbol, direction, entry, sl, tp, "
              "qty, status, order_package_id, created_at)")
    for t in (_tk(1, "breakout_2"), _tk(2, "tradeify_1")):
        c.execute("INSERT INTO prop_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", t)
    c.commit()
    c.close()
    orig = lrd.read_prop_open
    monkeypatch.setattr(lrd, "read_prop_open", lambda p=None, mark_fn=None: orig(p, _ACC, mark_fn))
    monkeypatch.setattr(lrd, "MARK_BUDGET_S", 0.3)
    release = threading.Event()
    calls = []

    def hang(sym):
        calls.append(sym)
        release.wait(5)
        return 148.0

    t0 = time.monotonic()
    out = lrd.live_review_due(db_path=db, reviews_path=str(tmp_path / "none.jsonl"), now=NOW, mark_fn=hang)
    took = time.monotonic() - t0
    release.set()
    assert took < 3.0
    assert out["read_state"] == "looked" and out["open_count"] == 1
    assert calls == ["SOLUSDT"]  # one read per symbol, not one per ticket
    tel = out["prop_open"][0]["accounts"][0]["telemetry"]
    assert tel["state"] == "could_not_look" and tel["unrealized_pnl"] is None
    assert "MarkTimeout" in tel["reason"]
    assert set(out["timings_ms"]) >= {"reviews", "telemetry", "prop_marks", "market_context",
                                      "conflicting_exposure", "compute_due", "total"}


def test_route_payload_keeps_the_estimate_when_the_feed_answers(tmp_path, monkeypatch):
    db = str(tmp_path / "j.db")
    _db(db, [])
    _journal(db, [])
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE prop_tickets (ticket_id, account_id, strategy, symbol, direction, entry, sl, tp, "
              "qty, status, order_package_id, created_at)")
    c.execute("INSERT INTO prop_tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", _tk(1, "breakout_2"))
    c.commit()
    c.close()
    orig = lrd.read_prop_open
    monkeypatch.setattr(lrd, "read_prop_open", lambda p=None, mark_fn=None: orig(p, _ACC, mark_fn))
    out = lrd.live_review_due(db_path=db, reviews_path=str(tmp_path / "none.jsonl"), now=NOW,
                              mark_fn=lambda s: 148.0)
    tel = out["prop_open"][0]["accounts"][0]["telemetry"]
    assert tel["state"] == "mark_estimate" and tel["unrealized_pnl"] == 4.0
