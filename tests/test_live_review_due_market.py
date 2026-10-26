"""LTR-1B-MARKET-TRIGGERS: swing / vol_regime / funding / calendar / mechanics in the due computation."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from src.runtime import live_review_due as lrd

NOW = datetime(2026, 10, 26, 11, 0, tzinfo=timezone.utc)
CFG = lrd.load_config()
TF = 7200


def row(**kw):
    base = {"order_package_id": "pkg-1", "strategy": "ada_pullback_2h", "account_id": "bybit_2",
            "symbol": "ADAUSDT", "direction": "short", "open_r": 0.2, "peak_r": 0.3,
            "giveback_r": 0.1, "r_to_target": 3.0, "bars_held": 3,
            "updated_at": NOW.isoformat(), "lifecycle": "open"}
    base.update(kw)
    return base


def hist(prices, atrs, start=None):
    start = start or (NOW - timedelta(seconds=TF * (len(prices) - 1)))
    return [{"bar_ts": (start + timedelta(seconds=TF * i)).isoformat(), "last_price": p, "atr": a}
            for i, (p, a) in enumerate(zip(prices, atrs))]


FRESH_CAL = {"state": "read", "events": [], "classes": {"BTC": ["fomc"]}}


def ctx(history=None, funding=None, calendar=None, reason=None):
    return {"history": history, "history_reason": reason, "calendar": calendar or FRESH_CAL,
            "funding": funding or {"state": "read", "row": None}}


def mkt(r, c):
    return lrd.market_events(r, c, CFG, NOW, TF)


def names(evs):
    return [e[0] for e in evs]


def cnl_names(c):
    return [x["event"] for x in c]


def test_swing_fires_at_two_atr_and_not_below():
    ev, _ = mkt(row(), ctx(hist([1.0, 1.0, 1.0, 1.25], [0.1, 0.1, 0.1, 0.1])))
    assert "swing" in names(ev)
    ev, _ = mkt(row(), ctx(hist([1.0, 1.0, 1.0, 1.15], [0.1, 0.1, 0.1, 0.1])))
    assert "swing" not in names(ev)


def test_vol_regime_expand_contract_and_late_history():
    ev, _ = mkt(row(), ctx(hist([1, 1, 1, 1], [0.1, 0.1, 0.12, 0.16])))
    assert ("vol_regime", "expand") in [(e[0], e[1]) for e in ev]
    ev, _ = mkt(row(), ctx(hist([1, 1, 1, 1], [0.1, 0.1, 0.08, 0.06])))
    assert ("vol_regime", "contract") in [(e[0], e[1]) for e in ev]
    # history began 3 bars after a 6-bar-old entry: entry ATR unknown -> could not look
    ev, c = mkt(row(bars_held=6), ctx(hist([1, 1, 1, 1], [0.1, 0.1, 0.1, 0.3])))
    assert "vol_regime" not in names(ev) and "vol_regime" in cnl_names(c)


def test_no_history_is_could_not_look_not_quiet():
    ev, c = mkt(row(), ctx(None, reason="history_table_absent"))
    assert not ev and {"swing", "vol_regime"} <= set(cnl_names(c))
    _, c = mkt(row(), None)
    assert set(cnl_names(c)) == set(lrd.MARKET_EVENTS)


def test_funding_paid_beyond_three_x_fires_received_does_not():
    paid = {"state": "read", "row": {"funding_usd": -1.2, "funding_time": "2026-10-26T08:00:00+00:00",
                                     "rate_bps": 3.5}}
    ev, _ = mkt(row(), ctx([], funding=paid))
    assert "funding" in names(ev)
    recv = {"state": "read", "row": dict(paid["row"], funding_usd=1.2)}
    assert "funding" not in names(mkt(row(), ctx([], funding=recv))[0])
    small = {"state": "read", "row": dict(paid["row"], rate_bps=2.0)}
    assert "funding" not in names(mkt(row(), ctx([], funding=small))[0])
    _, c = mkt(row(), ctx([], funding={"state": "could_not_look", "reason": "funding_store_absent"}))
    assert "funding" in cnl_names(c)


def test_funding_not_applicable_to_non_perp():
    _, c = mkt(row(symbol="SPY", strategy="spy_trend_1d"), ctx([]))
    assert "funding" not in cnl_names(c)


def test_calendar_stale_fresh_and_horizon(tmp_path):
    p = tmp_path / "cal.yaml"
    p.write_text("symbol_event_classes: {BTC: [fomc]}\nevents:\n"
                 "  - {class: fomc, time: '2026-07-29T18:30:00Z', impact: 1.0}\n")
    stale = lrd.read_calendar(str(p), NOW)
    assert stale["state"] == "could_not_look" and "stale" in stale["reason"]
    _, c = mkt(row(symbol="BTCUSDT"), ctx([], calendar=stale))
    assert "calendar" in cnl_names(c)
    soon = (NOW + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    later = (NOW + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.write_text("symbol_event_classes: {BTC: [fomc]}\nevents:\n"
                 f"  - {{class: fomc, time: '{soon}', impact: 1.0}}\n"
                 f"  - {{class: fomc, time: '{later}', impact: 1.0}}\n")
    cal = lrd.read_calendar(str(p), NOW)
    ev, _ = mkt(row(symbol="BTCUSDT"), ctx([], calendar=cal))
    assert names(ev).count("calendar") == 1
    _, c = mkt(row(symbol="ADAUSDT"), ctx([], calendar=cal))   # no classes declared for ADA
    assert "calendar" in cnl_names(c)


def test_market_event_dedupes_on_level():
    h = hist([1.0, 1.0, 1.0, 1.25], [0.1, 0.1, 0.1, 0.1])
    pkg_ctx = {"pkg-1": ctx(h)}
    res = lrd.compute_due([row()], [], CFG, NOW, market=pkg_ctx)
    sw = [e for d in res["due"] for e in d["events"] if e["event"] == "swing"]
    assert len(sw) == 1
    rv = {"order_package_id": "pkg-1", "reviewed_at": (NOW - timedelta(hours=3)).isoformat(),
          "trigger": {"event": "swing", "level": sw[0]["level"]}, "state": {}}
    res = lrd.compute_due([row()], [rv], CFG, NOW, market=pkg_ctx)
    assert not [e for d in res["due"] for e in d["events"] if e["event"] == "swing"]


def test_mechanics_journal_trade_absent_only_while_written():
    m = row(lifecycle="unknown_trade_absent", trade_id="999")
    res = lrd.compute_due([], [], CFG, NOW, mechanics_rows=[m])
    assert [d["events"][0]["event"] for d in res["due"]] == ["mechanics"]
    old = dict(m, updated_at=(NOW - timedelta(hours=2)).isoformat())
    assert lrd.compute_due([], [], CFG, NOW, mechanics_rows=[old])["due_count"] == 0


# collapsed-state: measured -- fixture rows only need the measured peak state; the
# production reader (live_review_due) does not branch on peak_state at all.
def test_payload_reads_history_funding_and_calendar(tmp_path):
    db = str(tmp_path / "j.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, status TEXT)")
    c.execute("INSERT INTO trades VALUES (7, 'open')")
    cols = ("order_package_id,trade_id,strategy,symbol,account_id,direction,open_r,peak_r,"
            "peak_state,giveback_r,r_to_target,bars_held,updated_at")
    c.execute(f"CREATE TABLE position_telemetry ({cols}, terminal_state, levers)")
    c.execute(f"INSERT INTO position_telemetry ({cols}) VALUES ({','.join('?' * 13)})",
              ("pkg-1", "7", "ada_pullback_2h", "ADAUSDT", "bybit_2", "short", 0.2, 0.3,
               "measured", 0.1, 3.0, 3, NOW.isoformat()))
    c.execute("INSERT INTO position_telemetry (order_package_id,trade_id,strategy,symbol,account_id,"
              "updated_at) VALUES ('pkg-x','999','ada_pullback_2h','ADAUSDT','bybit_2',?)",
              (NOW.isoformat(),))
    c.execute("CREATE TABLE position_path_history (order_package_id, bar_ts, last_price, atr, written_at)")
    for h in hist([1.0, 1.0, 1.0, 1.3], [0.1, 0.1, 0.1, 0.1]):
        c.execute("INSERT INTO position_path_history VALUES (?,?,?,?,?)",
                  ("pkg-1", h["bar_ts"], h["last_price"], h["atr"], h["bar_ts"]))
    c.commit()
    c.close()
    fdb = str(tmp_path / "f.sqlite")
    f = sqlite3.connect(fdb)
    f.execute("CREATE TABLE exchange_funding (funding_id, account_id, symbol, funding_usd, "
              "funding_time, raw)")
    f.execute("INSERT INTO exchange_funding VALUES ('a','bybit_2','ADA/USDT:USDT',-2.0,?,?)",
              ((NOW - timedelta(hours=3)).isoformat(), json.dumps({"feeRate": "0.0005"})))
    f.commit()
    f.close()
    cal = tmp_path / "cal.yaml"
    cal.write_text("symbol_event_classes: {}\nevents: []\n")
    out = lrd.live_review_due(db_path=db, reviews_path=str(tmp_path / "none.jsonl"), now=NOW,
                              funding_db_path=fdb, calendar_path=str(cal))
    assert out["read_state"] == "looked" and out["calendar_state"] == "could_not_look"
    by = {d["order_package_id"]: d for d in out["due"]}
    evs = {e["event"] for e in by["pkg-1"]["events"]}
    assert {"swing", "funding", "daily_floor"} <= evs
    assert "calendar" in [x["event"] for x in by["pkg-1"]["events_could_not_look"]]
    assert by["pkg-x"]["events"][0]["event"] == "mechanics"
    # funding store absent -> could not look, never "no settlement"
    out = lrd.live_review_due(db_path=db, reviews_path=str(tmp_path / "none.jsonl"), now=NOW,
                              funding_db_path=str(tmp_path / "nope.sqlite"), calendar_path=str(cal))
    cnl = {x["event"]: x["reason"] for x in
           next(d for d in out["due"] if d["order_package_id"] == "pkg-1")["events_could_not_look"]}
    assert cnl["funding"] == "funding_store_absent"
