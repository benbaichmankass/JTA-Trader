"""PERF-PAGE-CATEGORY-TABLE: category derivation, metric arithmetic (hand-computed), route 400/null rules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.runtime import perf_category as pc
from src.web.api import main as api_main
from src.web.api.routers import performance_categories as router
from tests.fixtures.real_schema_db import make_canonical_db, insert_trade

ACCOUNTS = {
    "a_live": {"account_class": "real_money"},
    "a_mirror": {"account_class": "paper", "paper_role": "portfolio"},
    "a_paper": {"account_class": "paper"},
    "a_prop": {"type": "prop", "account_class": "prop"},
    "a_old": {"type": "prop", "account_class": "prop", "retired": True},
    "a_odd": {"account_class": "weird"},
}


def test_categorize_is_derived_and_excluded_are_named():
    cats, ex = pc.categorize(ACCOUNTS)
    assert cats == {"live": ["a_live"], "prop": ["a_prop"], "paper_portfolio": ["a_mirror"], "paper_testing": ["a_paper"]}
    assert {e["account_id"]: e["reason"] for e in ex} == {"a_old": "retired", "a_odd": "no_category"}


def _row(pnl, entry=100.0, qty=2.0, hold_h=24.0, notes='{"pnl_source":"local_compute","exit_price_source":"bybit_closed_pnl"}',
         stop=99.0, closed="2026-11-10T12:00:00+00:00", **kw):
    c = datetime.fromisoformat(closed)
    r = {"pnl": pnl, "entry_price": entry, "qty": qty, "stop_loss": stop, "take_profit_1": entry + 3, "direction": "long",
         "symbol": "BTCUSDT", "opened_at": (c - timedelta(hours=hold_h)).isoformat(), "closed_at": closed,
         "notes": notes, "package_meta": None}
    r.update(kw)
    return r


def test_metrics_hand_computed_and_split_sums_to_net():
    fab = '{"pnl_source":"local_compute","exit_price_source":"local_markprice"}'
    rows = [_row(10.0, closed="2026-11-08T00:00:00+00:00"), _row(-4.0, closed="2026-11-09T00:00:00+00:00"),
            _row(6.0, notes=fab, closed="2026-11-10T00:00:00+00:00")]
    m = pc.category_metrics(rows, category="live", window_days=30)
    assert m["n_closed"] == 3 and m["net_pnl_usd"] == 12.0
    assert m["measured_usd"] == 6.0 and m["not_measured_usd"] == 6.0 and m["n_measured"] == 2 and m["n_not_measured"] == 1
    assert round(m["measured_usd"] + m["not_measured_usd"], 6) == m["net_pnl_usd"]
    assert m["win_rate"] == 0.5 and m["n_priced"] == 2 and m["profit_factor"] == 2.5
    # notional-days = 3 trades x |2*100| x 1 day = 600; all-rows 12/600*1e4 = 200 bps; measured-only 6/400*1e4 = 150
    assert m["return_on_time_in_trade_all_rows_bps_per_notional_day"] == 200.0
    assert m["return_on_time_in_trade_bps_per_notional_day"] == 150.0
    assert m["avg_hold_days"] == 1.0 and m["max_drawdown_usd"] == 4.0
    assert m["r_insufficient_n"] is True


def test_nulls_are_none_not_zero():
    m = pc.category_metrics([], category="prop", window_days=30)
    assert m["n_closed"] == 0 and m["net_pnl_usd"] is None and m["win_rate"] is None and m["profit_factor"] is None
    assert m["avg_realised_r"] is None and m["capital_utilisation"] is None and m["max_drawdown_usd"] is None
    assert m["capital_utilisation_read_state"] == "no_equity_record"
    one = pc.category_metrics([_row(5.0)], category="live", window_days=30)
    assert one["profit_factor"] is None            # no losses: never inf/0
    nohold = pc.category_metrics([_row(5.0, opened_at=None)], category="live", window_days=30)
    assert nohold["n_no_hold"] == 1 and nohold["return_on_time_in_trade_bps_per_notional_day"] is None


def test_capital_utilisation_needs_enough_snapshots_on_every_account():
    rows = [_row(5.0)]                                             # notional-days = 200
    ok = {"x": {"n": 48, "mean_balance": 1000.0}}
    assert pc.category_metrics(rows, category="live", window_days=10, snapshots=ok)["capital_utilisation"] == 0.02
    thin = {"x": {"n": 3, "mean_balance": 1000.0}}
    m = pc.category_metrics(rows, category="live", window_days=10, snapshots=thin)
    assert m["capital_utilisation"] is None and m["capital_utilisation_read_state"] == "no_equity_record"
    mixed = {"x": ok["x"], "y": {"n": 0, "mean_balance": None}}
    assert pc.category_metrics(rows, category="live", window_days=10, snapshots=mixed)["capital_utilisation"] is None


def test_prop_pnl_is_never_measured():
    m = pc.category_metrics([_row(5.0)], category="prop", window_days=30)
    assert m["measured_usd"] is None and m["not_measured_usd"] == 5.0 and m["net_pnl_usd"] == 5.0


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "trade_journal.db"
    make_canonical_db(db)
    monkeypatch.setattr(router, "_DB_PATH", db)
    monkeypatch.setattr(router, "_accounts", lambda: ACCOUNTS)
    monkeypatch.setattr(router, "_prop_rows", lambda ids, since: {"rows": [], "n_null_pnl": 0})
    return db


def _trade(db, **over):
    now = datetime.now(timezone.utc)
    f = {"timestamp": (now - timedelta(days=2, hours=1)).isoformat(), "closed_at": (now - timedelta(days=2)).isoformat(),
         "symbol": "BTCUSDT", "direction": "long", "entry_price": 100.0, "position_size": 2.0, "stop_loss": 99.0,
         "status": "closed", "is_backtest": 0, "is_demo": 0, "account_id": "a_live", "account_class": "real_money",
         "pnl": 5.0, "notes": '{"pnl_source":"local_compute","exit_price_source":"bybit_closed_pnl"}'}
    f.update(over)
    return insert_trade(db, **f)


def test_route_rows_window_400_and_null_pnl_counted(env, client):
    _trade(env, pnl=10.0)
    _trade(env, pnl=-4.0, account_id="a_paper", account_class="paper")
    _trade(env, pnl=None)                                                      # counted, not hidden
    _trade(env, pnl=99.0, is_backtest=1)                                       # excluded
    d = client.get("/api/bot/performance/categories", params={"window": "30d"}).json()
    by = {c["category"]: c for c in d["categories"]}
    assert [c["category"] for c in d["categories"]] == list(pc.CATEGORIES)
    assert by["live"]["n_closed"] == 1 and by["live"]["net_pnl_usd"] == 10.0 and by["live"]["n_excluded_null_pnl"] == 1
    assert by["paper_testing"]["net_pnl_usd"] == -4.0 and by["paper_portfolio"]["net_pnl_usd"] is None
    assert by["prop"]["n_closed"] == 0 and by["live"]["capital_utilisation"] is None
    assert d["population"]["n_closed"] == 2 and d["population"]["rows_excluded_null_pnl"] == 1
    assert {e["account_id"] for e in d["excluded"]} == {"a_old", "a_odd"}
    assert client.get("/api/bot/performance/categories", params={"window": "zz"}).status_code == 400
    assert client.get("/api/bot/performance/categories", params={"window": "90d"}).status_code == 200
    assert client.get("/api/bot/performance/categories", params={"window": "all"}).json()["categories"][0]["n_closed"] == 1


def test_window_excludes_old_trades(env, client):
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    _trade(env, pnl=7.0, closed_at=old, timestamp=old)
    assert client.get("/api/bot/performance/categories", params={"window": "30d"}).json()["categories"][0]["n_closed"] == 0
    assert client.get("/api/bot/performance/categories", params={"window": "90d"}).json()["categories"][0]["n_closed"] == 1


def test_prop_rows_join_the_opener_and_count_null_pnl(monkeypatch):
    from src.prop import prop_journal
    now = datetime.now(timezone.utc)
    op = {"id": 1, "account_id": "a_prop", "ticket_id": "t1", "status": "open", "symbol": "ETHUSDT", "direction": "long",
          "qty": 2.0, "entry_price": 100.0, "sl": 99.0, "tp": 105.0, "amendments": None,
          "opened_at": (now - timedelta(days=1, hours=1)).isoformat()}
    cl = {"id": 2, "account_id": "a_prop", "ticket_id": "t1", "status": "closed", "symbol": "ETHUSDT", "direction": "long",
          "pnl": 8.0, "sl": None, "tp": None, "closed_at": (now - timedelta(hours=1)).isoformat(), "reported_at": now.isoformat()}
    nopnl = dict(cl, id=4, ticket_id="t2", pnl=None)
    monkeypatch.setattr(prop_journal, "list_fills", lambda **k: [dict(nopnl), dict(cl), dict(op)])
    d = router._prop_rows(["a_prop"], (now - timedelta(days=30)).isoformat())
    assert d["n_null_pnl"] == 1 and len(d["rows"]) == 1
    r = d["rows"][0]
    assert r["pnl"] == 8.0 and r["entry_price"] == 100.0 and r["qty"] == 2.0 and r["stop_loss"] == 99.0
    m = pc.category_metrics(d["rows"], category="prop", window_days=30)
    assert m["avg_hold_days"] == 1.0 and m["n_measured"] == 0 and m["net_pnl_usd"] == 8.0


# ---- PERF-PAGE-PNL-CHART: /performance/pnl-series ----

FAB = '{"pnl_source":"local_compute","exit_price_source":"local_markprice"}'


def _snap(db, account_id, balance, days_ago, n=1):
    import sqlite3 as _s
    c = _s.connect(str(db))
    for i in range(n):
        ts = (datetime.now(timezone.utc) - timedelta(days=days_ago, minutes=i)).isoformat()
        c.execute("INSERT INTO balance_snapshots (account_id, balance, api_ok, ts) VALUES (?,?,1,?)", (account_id, balance, ts))
    c.commit()
    c.close()


def _series(client, **p):
    return client.get("/api/bot/performance/pnl-series", params=p)


def test_series_last_point_equals_category_table_and_split_is_visible(env, client):
    now = datetime.now(timezone.utc)
    d1, d2 = (now - timedelta(days=3)).isoformat(), (now - timedelta(days=1)).isoformat()
    _trade(env, pnl=10.0, closed_at=d1, timestamp=d1)
    _trade(env, pnl=-4.0, closed_at=d2, timestamp=d2)
    _trade(env, pnl=6.0, closed_at=d2, timestamp=d2, notes=FAB)
    _snap(env, "a_live", 1000.0, days_ago=40)
    tab = {c["category"]: c for c in client.get("/api/bot/performance/categories", params={"window": "30d"}).json()["categories"]}
    for mo, key in ((True, "measured_usd"), (False, "net_pnl_usd")):
        s = _series(client, window="30d", category="live", measured_only=str(mo).lower()).json()["series"][0]
        assert s["points"][-1]["cum_pnl_usd"] == tab["live"][key]          # the cross-check
    s = _series(client, window="30d", category="live").json()["series"][0]
    assert [p["pnl_usd"] for p in s["points"]] == [10.0, -4.0]               # measured-only; the fabricated +6 is skipped
    assert s["points"][-1]["cum_pnl_all_rows_usd"] == 12.0 and s["points"][-1]["n"] == 1
    assert s["start_capital_usd"] == 1000.0 and s["capital_read_state"] == "measured"
    assert s["points"][-1]["cum_pct"] == 0.6 and s["points"][-1]["cum_pct_all_rows"] == 1.2


def test_series_no_capital_record_is_null_pct_not_zero(env, client):
    _trade(env, pnl=10.0)
    s = _series(client, window="30d", category="live").json()["series"][0]
    assert s["start_capital_usd"] is None and s["capital_read_state"] == "no_capital_record"
    assert s["points"][-1]["cum_pnl_usd"] == 10.0 and s["points"][-1]["cum_pct"] is None


def test_series_first_snapshot_after_start_is_flagged_and_7d_is_per_trade(env, client):
    _trade(env, pnl=3.0)
    _trade(env, pnl=2.0)
    _snap(env, "a_live", 500.0, days_ago=1)                                   # nothing at/before the 7d start
    d = _series(client, window="7d", category="live").json()
    s = d["series"][0]
    assert s["capital_read_state"] == "first_snapshot_after_start" and d["bucket"] == "trade" and len(s["points"]) == 2


def test_series_filters_and_errors(env, client):
    _trade(env, pnl=1.0, strategy_name="s1", symbol="BTCUSDT")
    _trade(env, pnl=2.0, strategy_name="s2", symbol="ETHUSDT")
    one = _series(client, window="30d", category="live", strategy="s2").json()
    assert one["series"][0]["points"][-1]["cum_pnl_usd"] == 2.0 and one["population"]["filters"]["strategy"] == "s2"
    assert _series(client, window="30d", category="live", symbol="BTCUSDT").json()["series"][0]["n_rows"] == 1
    assert _series(client, window="30d", category="live", account_id="a_paper").json()["series"][0]["n_rows"] == 0
    assert len(_series(client, window="30d").json()["series"]) == 4
    assert _series(client, window="zz").status_code == 400
    assert _series(client, window="30d", category="nope").status_code == 400
    assert _series(client, window="all", category="live").status_code == 200


def test_pnl_series_pure_daily_bucketing_and_nonpositive_capital():
    rows = [_row(5.0, closed="2026-11-08T01:00:00+00:00"), _row(-2.0, closed="2026-11-08T23:00:00+00:00"),
            _row(4.0, closed="2026-11-09T01:00:00+00:00")]
    pts = pc.pnl_series(rows, category="live", per_trade=False, measured_only=True, start_capital=100.0)
    assert [(p["date"], p["pnl_usd"], p["cum_pnl_usd"], p["n"], p["cum_pct"]) for p in pts] == [
        ("2026-11-08", 3.0, 3.0, 2, 3.0), ("2026-11-09", 4.0, 7.0, 1, 7.0)]
    assert pc.pnl_series(rows, category="live", per_trade=False, measured_only=True, start_capital=0.0)[0]["cum_pct"] is None
    assert pc.pnl_series([], category="live", per_trade=True, measured_only=True, start_capital=None) == []
