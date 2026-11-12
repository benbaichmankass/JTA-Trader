"""Trade chart snapshot + decision markers (UI-REDESIGN-2026-11, addenda 2, 3, 5): builders, shape pin, routes."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.runtime import trade_snapshot_store as store
from src.web.api import main as api_main
from src.web.api import trade_chart_snapshot as tcs
from src.web.api.routers import trade_snapshot as router
from tests.fixtures.real_schema_db import insert_order_package, insert_trade, make_canonical_db

FIX = Path(__file__).parent / "fixtures"
OPEN, CLOSE = "2026-11-12T01:00:00+00:00", "2026-11-12T07:00:00+00:00"
PKG = "pkg-0000000000000001"


def _candles(start_s: int, n: int, step: int = 300, base: float = 1.04):
    return [{"time": start_s + i * step, "open": base, "high": base + 0.001 * (i % 7), "low": base - 0.001 * (i % 5),
             "close": base + 0.0001 * i, "volume": 100.0} for i in range(n)]


def _trade(**kw):
    t = {"id": 7001, "timestamp": OPEN, "closed_at": CLOSE, "symbol": "XRPUSDT", "direction": "long",
         "entry_price": 1.04, "exit_price": 1.052, "stop_loss": 1.04, "take_profit_1": 1.052, "position_size": 100.0,
         "exit_reason": "tp_hit", "pnl": 1.2, "status": "closed", "strategy_name": "ml_entry", "account_id": "bybit_1",
         "account_class": "paper", "order_package_id": PKG,
         "notes": json.dumps({"sl_amends": [{"source": "live_review_mandate", "review_id": "DA-1", "at":
                                             "2026-11-12T04:09:00+00:00", "from": 1.03, "to": 1.04}]})}
    t.update(kw)
    return t


def _pkg():
    return {"order_package_id": PKG, "symbol": "XRPUSDT", "direction": "long", "entry": 1.04, "sl": 1.03, "tp": 1.052,
            "confidence": 1.0, "created_at": OPEN, "status": "closed", "meta": "{}",
            "signal_logic": json.dumps({"model_id": "m1", "decision_bar": "2026-11-12T00:00:00+00:00",
                                        "timeframe": "1h", "p_long": 0.16, "features": {"rsi14": 0.29}}),
            "model_scores": None}


REVIEWS = {"state": "read", "rows": [
    {"review_id": "LR-hold", "order_package_id": PKG, "trade_id": None, "reviewed_at": "2026-11-12T02:05:00Z",
     "recommendation": {"action": "hold", "confidence": 0.6, "basis": "structure intact"},
     "disposition": {"route": "none"}, "account_reads": [{"account_id": "bybit_1", "read": "no_action"}]},
    {"review_id": "LR-tight", "order_package_id": PKG, "trade_id": None, "reviewed_at": "2026-11-12T04:05:00Z",
     "recommendation": {"action": "tighten_sl", "level": 1.04, "confidence": 0.7, "basis": "breakeven"},
     "disposition": {"route": "recommended"}, "account_reads": [{"account_id": "bybit_1", "read": "would_apply"}]},
    {"review_id": "LR-other-pkg", "order_package_id": "pkg-x", "reviewed_at": "2026-11-12T04:05:00Z",
     "recommendation": {"action": "close"}},
    {"review_id": "LR-after-close", "order_package_id": PKG, "reviewed_at": "2026-11-12T09:00:00Z",
     "recommendation": {"action": "close"}},
]}
RECEIPTS = {"state": "read", "rows": [
    {"id": "DA-1", "order_package_id": PKG, "done_at": "2026-11-12T04:09:00+00:00", "action": "tighten_sl",
     "resolved_action": "tighten_sl", "level": 1.04, "verdict": "applied", "directed_by": "manager",
     "accounts": [{"account_id": "bybit_1", "trade_id": 7001, "read": "would_apply", "executed": True}]},
    {"id": "DA-2", "order_package_id": PKG, "done_at": "2026-11-12T05:00:00+00:00", "action": "close",
     "accounts": [{"account_id": "bybit_2", "trade_id": 9999, "read": "would_apply"}]},
]}


def _build(candles=None):
    c = _candles(int(datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc).timestamp()), 100) if candles is None else candles
    return tcs.build_snapshot(_trade(), _pkg(), c, "bot-exchange", REVIEWS, RECEIPTS,
                              datetime(2026, 11, 12, 9, 40, tzinfo=timezone.utc), "MEASURED")


def _keys(d, prefix=""):
    """Every dict key path (lists collapse to their first element)."""
    out = set()
    if isinstance(d, dict):
        for k, v in d.items():
            if k.startswith("_"):
                continue
            out.add(prefix + k)
            out |= _keys(v, prefix + k + ".")
    elif isinstance(d, list) and d and isinstance(d[0], dict):
        out |= _keys(d[0], prefix + "[].")
    return out


# ── shape pin: the builders produce exactly the published fixture keys (the UI lane builds against them)

def test_snapshot_shape_matches_fixture():
    fx = json.loads((FIX / "trade_chart_snapshot_v1.json").read_text())["snapshot"]
    built = _build()
    # features / model_scores are free-form dicts; compare everything else
    strip = lambda ks: {k for k in ks if ".features." not in k and ".model_scores" not in k}  # noqa: E731
    assert strip(_keys(built)) >= strip(_keys(fx)) - {"brackets.updates.[].action"}
    missing = strip(_keys(fx)) - strip(_keys(built))
    assert not missing, missing


def test_markers_shape_matches_fixture():
    fx = json.loads((FIX / "trade_markers_v1.json").read_text())
    built = tcs.build_markers(_trade(status="open", closed_at=None), _pkg(), REVIEWS, RECEIPTS, "1h", "now")
    strip = lambda ks: {k for k in ks if ".features." not in k and ".model_scores" not in k}  # noqa: E731
    missing = strip(_keys(fx)) - strip(_keys(built))
    assert not missing, missing


# ── frame

def test_time_frame_pads_15pct_each_side_and_picks_interval():
    f = tcs.time_frame(datetime(2026, 11, 12, 1, tzinfo=timezone.utc), datetime(2026, 11, 12, 7, tzinfo=timezone.utc))
    assert f["time_from"].isoformat() == "2026-11-12T00:06:00+00:00"   # 6h * 0.15 = 54 min
    assert f["time_to"].isoformat() == "2026-11-12T07:54:00+00:00"
    assert f["interval"] == "5m"            # 7.8h / 5m = 93.6 bars <= 300; 1m would be 468
    assert not f["min_window_applied"]


def test_short_trade_gets_min_window():
    o = datetime(2026, 11, 12, 1, tzinfo=timezone.utc)
    f = tcs.time_frame(o, o.replace(minute=2))
    assert f["interval"] == "1m" and f["min_window_applied"]
    assert (f["time_to"] - f["time_from"]).total_seconds() == tcs.MIN_BARS * 60


def test_price_frame_pads_10pct_of_span_high_low():
    s = _build()
    b = s["frame"]["basis"]
    rng = b["high"] - b["low"]
    assert s["frame"]["price_high"] == pytest.approx(b["high"] + 0.1 * rng)
    assert s["frame"]["price_low"] == pytest.approx(b["low"] - 0.1 * rng)
    assert b["high_low_over"].startswith("candles")


def test_no_candles_is_unavailable_not_empty():
    s = _build(candles=[])
    assert s["candles"] == {"state": "unavailable", "source": "bot-exchange", "rows": None}
    assert s["indicators"]["series"] is None
    rs, reasons = tcs.snapshot_read_state(s)
    assert rs == "partial" and "candles_unavailable" in reasons


def test_candles_trimmed_to_window():
    s = _build()
    t0 = datetime.fromisoformat(s["frame"]["time_from"]).timestamp()
    t1 = datetime.fromisoformat(s["frame"]["time_to"]).timestamp()
    assert all(t0 - 300 < c["time"] <= t1 for c in s["candles"]["rows"])


# ── indicators

def test_ema_and_rsi_null_until_warm():
    s = _build()
    ema20 = next(x for x in s["indicators"]["series"] if x["name"] == "ema_20")["points"]
    assert ema20[18]["value"] is None and ema20[19]["value"] is not None
    rsi = next(x for x in s["indicators"]["series"] if x["name"] == "rsi_14")["points"]
    assert rsi[13]["value"] is None and 0 <= rsi[14]["value"] <= 100


# ── decisions

def test_decision_dispositions_per_account():
    m = {x["id"]: x for x in _build()["decisions"]["markers"]}
    assert m["LR-hold"]["disposition"] == "no_action"
    assert m["LR-tight"]["disposition"] == "advice_only" and m["LR-tight"]["account_read"] == "would_apply"
    assert m["DA-1"]["disposition"] == "applied" and m["DA-1"]["kind"] == "directed_action"
    assert "LR-other-pkg" not in m          # other package
    assert "LR-after-close" not in m        # after this leg closed
    assert "DA-2" not in m                  # scoped to another account's trade


def test_review_applied_when_id_on_trade_notes():
    row = {"review_id": "LR-x", "recommendation": {"action": "tighten_sl"}}
    assert tcs.review_disposition(row, "a", {"LR-x"})[0] == "applied"
    row2 = dict(row, review_id="LR-y", account_reads=[{"account_id": "a", "read": "refused"}])
    assert tcs.review_disposition(row2, "a", set())[0] == "refused"
    row3 = {"review_id": "LR-z", "recommendation": {"action": "flag_mechanics"}, "disposition": {"route": "operator_ask"}}
    assert tcs.review_disposition(row3, "a", set())[0] == "operator_ask"


def test_could_not_look_is_partial_never_empty_clean():
    d = tcs.decisions(_trade(), "1h", {"state": "could_not_look", "rows": []}, RECEIPTS)
    assert d["read_state"] == "partial" and d["sources"]["reviews"] == "could_not_look"


def test_account_moves_from_notes_are_scoped_account():
    ups = _build()["brackets"]["updates"]
    assert any(u["scope"] == "account" and u["to"] == 1.04 for u in ups)


def test_window_end_waits_for_post_close_pad():
    assert tcs.window_end(_trade()).isoformat() == "2026-11-12T07:54:00+00:00"


# ── routes

@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "trade_journal.db"
    make_canonical_db(path)
    monkeypatch.setattr(router, "_DB_PATH", path)
    monkeypatch.setattr(router.srcs, "load_reviews", lambda: REVIEWS)
    monkeypatch.setattr(router.srcs, "load_receipts", lambda: RECEIPTS)
    return path


def _insert(db, **kw):
    t = _trade(**kw)
    t.pop("id")
    return insert_trade(db, is_backtest=0, **t)


def test_snapshot_route_not_built_then_built(db, client):
    insert_order_package(db, order_package_id=PKG, created_at=OPEN, status="closed", meta="{}")
    tid = _insert(db)
    d = client.get(f"/api/bot/trades/{tid}/snapshot").json()
    assert d["read_state"] == "not_built" and d["snapshot"] is None   # no table yet
    payload = _build()
    conn = sqlite3.connect(str(db))
    conn.execute(store.DDL)
    conn.execute(f"INSERT INTO {store.TABLE} (snapshot_key, trade_id, state, payload) VALUES (?, ?, 'built', ?)",
                 (store.trade_key(tid), tid, json.dumps(payload)))
    conn.commit()
    conn.close()
    d = client.get(f"/api/bot/trades/{tid}/snapshot").json()
    assert d["snapshot"]["schema"] == tcs.SCHEMA
    assert d["read_state"] == "partial" and "tp_history_unrecorded" in d["partial_reasons"]


def test_snapshot_route_404s(db, client):
    assert client.get("/api/bot/trades/424242/snapshot").status_code == 404
    tid = _insert(db, status="open", closed_at=None)
    assert client.get(f"/api/bot/trades/{tid}/snapshot").status_code == 404


def test_markers_route_open_trade(db, client):
    insert_order_package(db, order_package_id=PKG, created_at=OPEN, status="open", meta="{}")
    tid = _insert(db, status="open", closed_at=None)
    d = client.get(f"/api/bot/trades/{tid}/markers", params={"interval": "1h"}).json()
    assert d["trade_id"] == tid and d["interval"] == "1h"
    assert d["entry"]["bar_ts"] == "2026-11-12T01:00:00+00:00"
    ids = [m["id"] for m in d["decisions"]["markers"]]
    assert "LR-tight" in ids and "LR-after-close" in ids   # open trade: no upper bound
    assert client.get(f"/api/bot/trades/{tid}/markers", params={"interval": "7m"}).status_code == 400


def test_stored_form_is_compressed_and_route_recomputes_indicators(db, client):
    insert_order_package(db, order_package_id=PKG, created_at=OPEN, status="closed", meta="{}")
    tid = _insert(db)
    payload = _build()
    blob = store.encode(payload)
    assert len(blob) < len(json.dumps(payload)) / 3
    conn = sqlite3.connect(str(db))
    conn.execute(store.DDL)
    conn.execute(f"INSERT INTO {store.TABLE} (snapshot_key, trade_id, state, payload) VALUES (?, ?, 'built', ?)",
                 (store.trade_key(tid), tid, blob))
    conn.commit()
    conn.close()
    d = client.get(f"/api/bot/trades/{tid}/snapshot").json()
    assert d["snapshot"]["indicators"] == payload["indicators"]
    assert d["snapshot"]["candles"] == payload["candles"]


# ── prop trades (prop_fills + prop_tickets), keyed by the opening fill id

PROP_AMENDS = json.dumps([{"at": "2026-11-12T03:00:00+00:00", "sl_before": 90.0, "sl": 89.0, "tp_before": 80.0,
                           "tp": 80.0, "source": {"reason": "live review tighten"}}])


def insert_prop_trade(db, closed=True):
    from src.prop import prop_journal
    conn = sqlite3.connect(str(db))
    prop_journal.ensure_tables(conn)
    conn.execute("INSERT INTO prop_tickets (ticket_id, account_id, strategy, symbol, direction, order_package_id, meta,"
                 " created_at) VALUES ('tk-1', 'breakout_2', 'ml_entry', 'SOLUSDT', 'short', ?, ?, ?)",
                 (PKG, json.dumps({"sl_floor": {"level": 89.0, "review_id": "LR-tight"}}), OPEN))
    cur = conn.execute("INSERT INTO prop_fills (account_id, ticket_id, external_order_id, symbol, direction, qty,"
                       " entry_price, sl, tp, status, opened_at, reported_at, amendments, created_at) VALUES"
                       " ('breakout_2', 'tk-1', 'ext-1', 'SOLUSDT', 'SELL', 6.82, 87.64, 89.0, 80.0, 'filled', ?, ?, ?, ?)",
                       (OPEN, OPEN, PROP_AMENDS, OPEN))
    opener = cur.lastrowid
    closer = None
    if closed:
        cur = conn.execute("INSERT INTO prop_fills (account_id, ticket_id, external_order_id, symbol, direction, qty,"
                           " entry_price, exit_price, pnl, status, reason, closed_at, reported_at, created_at) VALUES"
                           " ('breakout_2', 'tk-1', 'ext-1', 'SOLUSDT', 'SELL', 6.82, 87.64, 86.0, 11.2, 'closed',"
                           " 'tp', ?, ?, ?)", (CLOSE, CLOSE, CLOSE))
        closer = cur.lastrowid
    conn.commit()
    conn.close()
    return opener, closer


def test_prop_resolves_from_either_row_and_builds(db):
    opener, closer = insert_prop_trade(db)
    conn = sqlite3.connect(str(db))
    for fid in (opener, closer):
        o, c, tk = store.resolve_prop(conn, fid)
        assert o["id"] == opener and c["id"] == closer and tk["ticket_id"] == "tk-1"
    t = tcs.prop_trade(o, c, tk)
    conn.close()
    assert t["direction"] == "short" and t["status"] == "closed" and t["prop_fill_id"] == opener
    s = tcs.build_snapshot(t, _pkg(), _candles(int(datetime(2026, 11, 12, tzinfo=timezone.utc).timestamp()), 100),
                           "x", REVIEWS, RECEIPTS, datetime(2026, 11, 12, 9, tzinfo=timezone.utc))
    assert s["trade"]["prop_fill_id"] == opener and s["trade"]["trade_id"] is None
    assert s["brackets"]["tp_history"] == "recorded"
    assert [(u["from"], u["to"], u["scope"]) for u in s["brackets"]["updates"]] == [(90.0, 89.0, "account")]
    m = {x["id"]: x for x in s["decisions"]["markers"]}
    assert m["LR-tight"]["disposition"] == "applied"      # ticket meta.sl_floor names it
    assert "DA-1" not in m                                 # receipt scoped to an exchange trade id


def test_prop_routes(db, client):
    opener, closer = insert_prop_trade(db)
    d = client.get(f"/api/bot/prop-trades/{closer}/snapshot").json()
    assert d["read_state"] == "not_built" and d["prop_fill_id"] == opener and d["trade_id"] is None
    conn = sqlite3.connect(str(db))
    o, c, tk = store.resolve_prop(conn, opener)
    payload = tcs.build_snapshot(tcs.prop_trade(o, c, tk), None, [], "x", REVIEWS, RECEIPTS,
                                 datetime(2026, 11, 12, 9, tzinfo=timezone.utc))
    conn.execute(store.DDL)
    conn.execute(f"INSERT INTO {store.TABLE} (snapshot_key, prop_fill_id, state, payload) VALUES (?, ?, 'built', ?)",
                 (store.prop_key(closer), opener, store.encode(payload)))
    conn.commit()
    conn.close()
    d = client.get(f"/api/bot/prop-trades/{opener}/snapshot").json()
    assert d["snapshot"]["trade"]["account_class"] == "prop"
    mk = client.get(f"/api/bot/prop-trades/{opener}/markers").json()
    assert mk["prop_fill_id"] == opener and mk["brackets"]["tp_history"] == "recorded"
    assert client.get("/api/bot/prop-trades/999999/snapshot").status_code == 404


def test_open_prop_trade_snapshot_404_markers_ok(db, client):
    opener, _ = insert_prop_trade(db, closed=False)
    assert client.get(f"/api/bot/prop-trades/{opener}/snapshot").status_code == 404
    mk = client.get(f"/api/bot/prop-trades/{opener}/markers").json()
    assert mk["status"] == "open" and mk["entry"]["price"] == 87.64


def test_prop_fixture_shape_matches_builder(db):
    opener, closer = insert_prop_trade(db)
    conn = sqlite3.connect(str(db))
    o, c, tk = store.resolve_prop(conn, opener)
    conn.close()
    built = tcs.build_snapshot(tcs.prop_trade(o, c, tk), _pkg(),
                               _candles(int(datetime(2026, 11, 12, tzinfo=timezone.utc).timestamp()), 100),
                               "x", REVIEWS, RECEIPTS, datetime(2026, 11, 12, 9, tzinfo=timezone.utc))
    fx = json.loads((FIX / "trade_chart_snapshot_prop_v1.json").read_text())["snapshot"]
    strip = lambda ks: {k for k in ks if ".features." not in k and ".model_scores" not in k}  # noqa: E731
    missing = strip(_keys(fx)) - strip(_keys(built))
    assert not missing, missing


def test_prop_placed_row_is_fallback_opener(db):
    from src.prop import prop_journal
    conn = sqlite3.connect(str(db))
    prop_journal.ensure_tables(conn)
    conn.execute("INSERT INTO prop_fills (account_id, external_order_id, symbol, status, opened_at, reported_at,"
                 " entry_price, created_at) VALUES ('a', 'x9', 'SOLUSDT', 'placed', ?, ?, 87.0, ?)", (OPEN, OPEN, OPEN))
    cur = conn.execute("INSERT INTO prop_fills (account_id, external_order_id, symbol, status, reported_at, exit_price,"
                       " created_at) VALUES ('a', 'x9', 'SOLUSDT', 'closed', ?, 86.0, ?)", (CLOSE, CLOSE))
    o, c, _ = store.resolve_prop(conn, cur.lastrowid)
    conn.close()
    assert o["status"] == "placed" and c["id"] == cur.lastrowid
    t = tcs.prop_trade(o, c, None)
    assert t["timestamp"] == OPEN and t["closed_at"] == CLOSE      # no closed_at on the row -> reported_at
