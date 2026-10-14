"""Server-side fill / close inference for the prop book (PHONE-POSITIONS-READ-CONTEXT scope add)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.prop import fill_inference as fi
from src.prop import prop_journal
from src.prop import prop_overview as po
from src.prop.prop_report import ingest_report

ACCT = "breakout_2"
T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)   # a fixed synthetic clock, never compared with now()


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    sent: list = []
    monkeypatch.setattr("src.prop.breakout_notify.emit_prop_fill", lambda f, **k: sent.append(f) or {})
    monkeypatch.setattr("src.prop.phone_executor._ping", lambda m, send=None: sent.append(m))
    monkeypatch.setattr(fi, "_state_path", lambda a: tmp_path / f"fi_{a}.json")
    return sent


def _placed(tid="prop-manual-x1", side="short", limit=2491.47, sl=2535.25, tp=2244.81):
    ingest_report({"kind": "fill", "status": "placed", "account_id": ACCT, "ticket_id": tid, "symbol": "ETHUSDT",
                   "direction": side, "qty": 0.57, "entry_price": limit, "sl": sl, "tp": tp,
                   "opened_at": T0.isoformat()})


def _bars(*rows):
    """rows: (minutes after T0, high, low)"""
    out = [(T0 + timedelta(minutes=m), hi, lo) for m, hi, lo in rows]
    return lambda sym, since, now: out


def _states():
    fills = prop_journal.list_fills(account_id=ACCT, limit=50)
    return sorted((f["status"], f["entry_price"], f["exit_price"]) for f in fills)


def test_crossed_limit_becomes_estimated_open():
    _placed()
    r = fi.infer(ACCT, now=T0 + timedelta(hours=1), bars_fn=_bars((5, 2480, 2470), (10, 2500, 2480)))
    assert r["filled"] == ["prop-manual-x1"]
    o = next(f for f in prop_journal.list_fills(account_id=ACCT) if f["status"] == "open")
    raw = json.loads(o["raw"])
    assert o["entry_price"] == 2491.47 and raw["provenance"] == "estimated" and raw["inferred"] is True
    assert o["reason"].startswith("INFERRED") and o["external_order_id"] == "inferred-prop-manual-x1"
    open_rows, _ = po.split_fills(prop_journal.list_fills(account_id=ACCT))
    assert [f["status"] for f in open_rows] == ["open"]
    # a second pass changes nothing
    assert fi.infer(ACCT, now=T0 + timedelta(hours=2), bars_fn=_bars((10, 2500, 2480)))["filled"] == []


def test_not_crossed_stays_placed_and_touch_or_earlier_bar_does_not_fill():
    _placed()
    # exactly touching the limit, and a bar that opened BEFORE the order was placed, do not fill
    r = fi.infer(ACCT, now=T0 + timedelta(hours=1), bars_fn=_bars((-5, 2600, 2400), (5, 2491.47, 2470)))
    assert r["filled"] == [] and [s[0] for s in _states()] == ["placed"]


def test_stale_unreadable_feed_changes_nothing():
    _placed()
    assert fi.infer(ACCT, now=T0 + timedelta(hours=1), bars_fn=lambda *a: [])["filled"] == []
    assert fi.infer(ACCT, now=T0 + timedelta(days=30), bars_fn=_bars((5, 2500, 2480)))["filled"] == []


def test_tp_crossed_later_closes_estimated_and_sl_for_long():
    _placed()
    fi.infer(ACCT, now=T0 + timedelta(hours=1), bars_fn=_bars((5, 2500, 2480)))
    r = fi.infer(ACCT, now=T0 + timedelta(hours=3), bars_fn=_bars((5, 2500, 2480), (60, 2490, 2200)))
    assert r["closed"] == ["prop-manual-x1"]
    c = next(f for f in prop_journal.list_fills(account_id=ACCT) if f["status"] == "closed")
    assert c["exit_price"] == 2244.81 and c["pnl"] is None and c["reason"].startswith("INFERRED tp")
    assert json.loads(c["raw"])["provenance"] == "estimated"
    assert po.split_fills(prop_journal.list_fills(account_id=ACCT))[0] == []
    _placed("prop-manual-l1", side="long", limit=100.0, sl=95.0, tp=120.0)
    fi.infer(ACCT, now=T0 + timedelta(hours=4), bars_fn=_bars((5, 101, 99)))   # (symbol-agnostic fake feed)
    r2 = fi.infer(ACCT, now=T0 + timedelta(hours=5), bars_fn=_bars((5, 101, 99), (30, 100, 94)))
    assert "prop-manual-l1" in r2["closed"]


def test_both_sl_and_tp_in_one_bar_is_not_guessed(env):
    _placed()
    fi.infer(ACCT, now=T0 + timedelta(hours=1), bars_fn=_bars((5, 2500, 2480)))
    wide = _bars((5, 2500, 2480), (60, 2600, 2100))
    r = fi.infer(ACCT, now=T0 + timedelta(hours=3), bars_fn=wide)
    assert r["closed"] == [] and r["flagged"] == ["prop-manual-x1"]
    assert [s[0] for s in _states()] == ["open", "placed"]
    n = len([m for m in env if isinstance(m, str)])
    fi.infer(ACCT, now=T0 + timedelta(hours=4), bars_fn=wide)
    assert len([m for m in env if isinstance(m, str)]) == n      # the flag is raised once


def test_phone_read_is_the_arbiter():
    _placed()
    other = [{"symbol": "SOLUSDT", "direction": "long", "qty": 1.0, "entry": 100.0}]
    # a clean read that does not show the position: not inferred filled
    assert fi.infer(ACCT, now=T0 + timedelta(hours=1), bars_fn=_bars((5, 2500, 2480)), positions=other)["filled"] == []
    # no clean read: inferred; then a clean read showing it overrides the inferred entry/size with MEASURED values
    fi.infer(ACCT, now=T0 + timedelta(hours=1), bars_fn=_bars((5, 2500, 2480)))
    vp = [{"symbol": "ETHUSDT", "direction": "short", "qty": 0.57, "entry": 2492.1}]
    r = fi.infer(ACCT, now=T0 + timedelta(hours=2), bars_fn=_bars((5, 2500, 2480), (60, 2490, 2200)), positions=vp)
    assert r["measured"] == ["prop-manual-x1"] and r["closed"] == []     # on the venue list: never inferred closed
    opens = [f for f in prop_journal.list_fills(account_id=ACCT) if f["status"] == "open"]
    assert len(opens) == 1 and opens[0]["entry_price"] == 2492.1 and json.loads(opens[0]["raw"])["provenance"] == "measured"
    assert fi.is_inferred(opens[0]) is False


def test_measured_open_row_is_never_touched():
    ingest_report({"kind": "fill", "status": "open", "account_id": ACCT, "ticket_id": "m1", "symbol": "ETHUSDT",
                   "direction": "short", "qty": 0.5, "entry_price": 2500.0, "sl": 2510.0, "tp": 2400.0,
                   "opened_at": T0.isoformat(), "source": "phone_reconcile", "provenance": "measured"})
    r = fi.infer(ACCT, now=T0 + timedelta(hours=3), bars_fn=_bars((5, 2600, 2300)))
    assert r == {"filled": [], "closed": [], "measured": [], "flagged": []}


def test_filled_and_stopped_between_two_looks_is_journaled_in_one_pass():
    _placed()
    r = fi.infer(ACCT, now=T0 + timedelta(hours=3), bars_fn=_bars((5, 2500, 2480), (60, 2540, 2495)))   # fill, then SL 2535.25
    assert r["filled"] == ["prop-manual-x1"] and r["closed"] == ["prop-manual-x1"]
    assert po.split_fills(prop_journal.list_fills(account_id=ACCT))[0] == []


def _unconfirmed(tid, *, placed_at=None, go_used_at=None):
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": ACCT, "strategy": "trend_donchian_eth_prop", "symbol": "ETHUSDT",
        "direction": "short", "entry": 2458.24, "sl": 2504.25, "tp": 2214.87, "qty": 0.54,
        "valid_until": (T0 + timedelta(hours=1)).isoformat(), "status": "placed",
        "meta": {"phone": {"go": {"go": True, "mode": "live", "used_at": go_used_at}}} if go_used_at else None})
    rep = {"kind": "fill", "status": "placed", "account_id": ACCT, "ticket_id": tid, "symbol": "ETHUSDT",
           "direction": "short", "qty": 0.54, "entry_price": 2458.24, "sl": 2504.25, "tp": 2214.87,
           "source": "phone_executor_unconfirmed", "provenance": "UNVERIFIED"}
    if placed_at:
        rep["placed_at"] = placed_at
    ingest_report(rep)   # reported_at = the real write time, hours/months after the synthetic bars


@pytest.mark.parametrize("how", ["go_used_at", "placed_at"])
def test_unconfirmed_submit_journaled_late_is_inferred_from_its_submit_time(how):
    """BREAKOUT-UNTRACKED-1014: the watchdog journaled the 13:22Z submit at 18:36Z; ETH was through the short limit
    only before that, so keying bars off the write time left the open short `placed` for ever."""
    tid = "prop-manual-f6552263ed1d"
    _unconfirmed(tid, **{how: (T0 + timedelta(minutes=1)).isoformat()})
    r = fi.infer(ACCT, now=T0 + timedelta(hours=6), bars_fn=_bars((0, 2472.12, 2457.13), (15, 2487.41, 2471.51),
                                                                 (300, 2431.46, 2424.74)))
    assert r["filled"] == [tid]   # the 15-min bar (after the submit) traded through 2458.24
    o = next(f for f in prop_journal.list_fills(account_id=ACCT) if f["status"] == "open")
    assert o["entry_price"] == 2458.24 and json.loads(o["raw"])["provenance"] == "estimated"
    assert r["closed"] == []      # neither SL 2504.25 nor TP 2214.87 traded


def test_unconfirmed_submit_without_any_submit_time_keeps_the_old_write_time_rule():
    _unconfirmed("t-no-time")
    r = fi.infer(ACCT, now=T0 + timedelta(hours=6), bars_fn=_bars((15, 2487.41, 2471.51)))
    assert r["filled"] == []
