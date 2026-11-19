"""D9-MAKER-EXIT-BUILD: ml_entry's 24h time stop worked post-only at the passive mid, 1-minute Market fallback.

The close-path tests drive the REAL ``order_monitor._apply_update`` -> ``_send_close_to_exchange`` ->
``execute.close_open_position`` -> ``_capture_fill_details`` chain against a fake pybit client whose responses
use the real V5 shapes (``get_tickers`` bid1Price/ask1Price, ``place_order`` retCode/result.orderId, order status
via ``account_order_status``'s contract). Only the account resolution, the venue order book and the journal are
doubles.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from src.runtime import order_monitor as om
from src.units.accounts import maker_exit as mx

REPO = Path(__file__).resolve().parents[1]

DEMO = {"account_id": "bybit_1", "exchange": "bybit", "market_type": "linear", "demo": True,
        "account_class": "paper", "paper_role": None, "mode": "live"}
REAL = {"account_id": "bybit_2", "exchange": "bybit", "market_type": "linear", "demo": False,
        "account_class": "real_money", "paper_role": None, "mode": "live"}
MIRROR = dict(DEMO, account_id="bybit_portfolio", paper_role="portfolio")


def _legs(name):
    return {"ml_entry": {"time_stop_exit_order": "post_only_mid"}, "ict_scalp": {}}.get(name, {})


# --- the fence ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("strategy,reason,cfg,want", [
    ("ml_entry", "max_hold", DEMO, ("post_only_mid", "leg_post_only_mid")),
    ("ml_entry", "max_hold", REAL, ("market", "not_paper_account")),            # real money: not in PR 1
    ("ml_entry", "max_hold", MIRROR, ("market", "portfolio_mirror")),           # the Stage-2 mirror moves with PR 2
    ("ml_entry", "max_hold", dict(DEMO, demo=False), ("market", "not_demo_account")),
    ("ml_entry", "max_hold", dict(DEMO, mode="dry_run"), ("market", "dry_run")),
    ("ml_entry", "max_hold", dict(DEMO, market_type="spot"), ("market", "not_derivatives")),
    ("ml_entry", "max_hold", dict(DEMO, exchange="alpaca"), ("market", "not_bybit")),
    ("ml_entry", "sl_cross", DEMO, ("market", "not_time_stop")),               # protective closes: never passive
    ("ml_entry", "tp", DEMO, ("market", "not_time_stop")),
    ("ict_scalp", "max_hold", DEMO, ("market", "leg_market")),                 # a leg that does not declare it
])
def test_fence(strategy, reason, cfg, want):
    assert mx.resolve_exit_order(strategy, reason, cfg, cfg_loader=_legs) == want


def test_a_missing_account_class_refuses(tmp_path):
    """The runtime cfg omits account_class/paper_role: they come from accounts.yaml, and an unreadable one refuses."""
    cfg = {k: v for k, v in DEMO.items() if k not in ("account_class", "paper_role")}
    p = tmp_path / "accounts.yaml"
    p.write_text(yaml.safe_dump({"accounts": {"bybit_1": {"account_class": "paper", "demo": True}}}))
    assert mx.resolve_exit_order("ml_entry", "max_hold", cfg, cfg_loader=_legs, accounts_path=str(p))[0] == "post_only_mid"
    p.write_text(yaml.safe_dump({"accounts": {"bybit_1": {"demo": True}}}))           # class absent -> real money
    assert mx.resolve_exit_order("ml_entry", "max_hold", cfg, cfg_loader=_legs, accounts_path=str(p))[0] == "market"
    missing = str(tmp_path / "nope.yaml")
    assert mx.resolve_exit_order("ml_entry", "max_hold", cfg, cfg_loader=_legs, accounts_path=missing) == \
        ("market", "account_unreadable")


def test_the_live_config_admits_the_demo_floor_only():
    """Read the real config/accounts.yaml + config/strategies.yaml (never quote roster counts). PR 1: every
    (account, leg) pair admitted is a demo-floor Bybit account; no real-money account and no mirror is."""
    accs = yaml.safe_load((REPO / "config" / "accounts.yaml").read_text())
    accs = accs.get("accounts", accs)
    admitted, refused_real = [], []
    for name, a in accs.items():
        if not isinstance(a, dict):
            continue
        for leg in a.get("strategies") or []:
            if mx.leg_exit_order(str(leg)) != mx.POST_ONLY_MID:
                continue
            cfg = {"account_id": name, "exchange": a.get("exchange"), "market_type": a.get("market_type"),
                   "demo": a.get("demo", False), "mode": "live"}
            got = mx.resolve_exit_order(str(leg), "max_hold", cfg)[0]
            (admitted if got == mx.POST_ONLY_MID else refused_real).append((name, str(leg)))
    assert ("bybit_1", "ml_entry_v2") in admitted
    for name, _leg in admitted:
        a = accs[name]
        assert a.get("account_class") == "paper" and a.get("demo") is True and a.get("paper_role") != "portfolio"
    # ml_entry (real money + its mirror) is not declared in PR 1: its line would make its committed evidence record
    # STALE, so it lands with the widening. Even if it were declared, the fence would refuse both books.
    assert mx.leg_exit_order("ml_entry") == mx.MARKET
    for acct in ("bybit_2", "bybit_portfolio"):
        a = accs[acct]
        cfg = {"account_id": acct, "exchange": a.get("exchange"), "market_type": a.get("market_type"),
               "demo": a.get("demo", False), "mode": "live"}
        assert mx.resolve_exit_order("ml_entry", "max_hold", cfg, cfg_loader=_legs)[0] == mx.MARKET


def test_the_leg_field_is_read_from_the_whole_yaml_block():
    """``strategy_registry._strategy_cfg`` drops every leg key but five; the leg read must not go through it."""
    assert mx.full_leg_cfg("ml_entry_v2").get("time_stop_exit_order") == "post_only_mid"
    assert mx.leg_exit_order("ml_entry_v2") == mx.POST_ONLY_MID


# --- price parity with the harness ----------------------------------------------------------------------------

T = Decimal("0.1")


@pytest.mark.parametrize("bid,ask,side,want", [
    (64000.0, 64000.1, "Sell", "64000.1"),   # one-tick spread: the passive mid IS the near touch (ask)
    (64000.0, 64000.1, "Buy", "64000.0"),    # ... and the bid for a Buy
    (64000.0, 64000.4, "Sell", "64000.2"),   # wider: inside the spread
    (64000.0, 64000.3, "Sell", "64000.2"),   # an off-grid mid rounds AWAY from the bid
    (64000.0, 64000.3, "Buy", "64000.1"),    # ... and away from the ask
    (64000.0, 64000.0, "Sell", None),        # locked book: no passive price
    (64000.1, 64000.0, "Buy", None),         # crossed
])
def test_passive_mid(bid, ask, side, want):
    got = mx.passive_mid(bid, ask, T, side)
    assert (str(got) if got is not None else None) == want


def test_harness_parity_window_peg_and_reason():
    """The constants this module rests on are the ones both passing units registered."""
    for unit in ("RQ-20261118-04a5-05", "RQ-20261118-e8a1-01"):
        doc = yaml.safe_load((REPO / "research" / "queue" / f"{unit}.yaml").read_text())
        cmd = doc["run"]["command"]
        assert cmd[cmd.index("--exit-w-min") + 1] == "1" and mx.FALLBACK_SECONDS == 60
        assert cmd[cmd.index("--exit-peg") + 1] == "mid"
        assert "24h time-stop" in doc["question"] or "time-stop" in doc["question"]
    assert mx.TIME_STOP_REASONS == frozenset({"max_hold"})
    from src.units.strategies.claude_desk import R_MAX_HOLD
    assert R_MAX_HOLD in mx.TIME_STOP_REASONS


def test_harness_mid_maps_to_the_passive_touch_on_a_one_tick_book():
    """The harness's mid arm rests AT p (the last close, on the grid; its modelled touch sits half a tick away).
    On a real one-tick book where p printed on the passive side (p == ask for a closing Sell), the passive mid is p."""
    import pandas as pd
    import importlib.util
    spec = importlib.util.spec_from_file_location("replay", REPO / "scripts" / "research" / "ml_entry_maker_replay.py")
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    t0 = 1_700_000_000 - (1_700_000_000 % 60)
    p, tick = 100.00, 0.01
    t = [t0 - 120, t0 - 60, t0, t0 + 60]
    d = pd.DataFrame({"t": t, "open": [p] * 4, "high": [p] * 4, "low": [p] * 4, "close": [p] * 4})
    r = replay.delta_f(d, t0, -1, tick, 1, "mid")
    assert r is not None and r["mid"] == p
    assert float(mx.passive_mid(p - tick, p, Decimal("0.01"), "Sell")) == p


# --- the venue double ----------------------------------------------------------------------------------------

class Venue:
    """A Bybit V5 double: one linear position, a book, an order table."""

    def __init__(self, bid="64000.0", ask="64000.1", size=0.01, side="Buy"):
        self.bid, self.ask = bid, ask
        self.pos = {"BTCUSDT": [size, side]}
        self.orders = {}
        self.placed, self.cancelled = [], []
        self.reject_post_only = False
        self.mkt_fill = 64001.0

    # pybit surface
    def get_tickers(self, *, category, symbol):
        return {"retCode": 0, "result": {"list": [{"symbol": symbol, "bid1Price": self.bid, "ask1Price": self.ask,
                                                    "lastPrice": self.bid}]}}

    def get_instruments_info(self, *, category, symbol):
        return {"retCode": 0, "result": {"list": [{"priceFilter": {"tickSize": "0.1"},
                                                    "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"}}]}}

    def place_order(self, **kw):
        self.placed.append(kw)
        oid = f"oid-{len(self.placed)}"
        if kw.get("timeInForce") == "PostOnly" and self.reject_post_only:
            return {"retCode": 170213, "retMsg": "Order would take liquidity (post-only)", "result": {}}
        if kw["orderType"] == "Market":
            q = float(kw["qty"])
            self.pos["BTCUSDT"][0] = max(self.pos["BTCUSDT"][0] - q, 0.0)
            self.orders[oid] = {"status": "Filled", "filled_qty": q, "avg_price": self.mkt_fill}
        else:
            self.orders[oid] = {"status": "New", "filled_qty": 0.0, "avg_price": 0.0, "price": float(kw["price"]),
                                "qty": float(kw["qty"])}
        return {"retCode": 0, "retMsg": "OK", "result": {"orderId": oid}}

    def cancel_order(self, *, category, symbol, orderId):
        self.cancelled.append(orderId)
        o = self.orders.get(orderId)
        if o and o["status"] in ("New", "PartiallyFilled"):
            o["status"] = "Cancelled" if o["filled_qty"] == 0 else "PartiallyFilledCanceled"
            return {"retCode": 0, "result": {"orderId": orderId}}
        return {"retCode": 110001, "retMsg": "order not exists or too late to cancel"}

    def get_executions(self, **kw):
        return {"retCode": 0, "result": {"list": [{"execFee": "0.128", "feeRate": "0.0002", "isMaker": True}]}}

    def get_positions(self, *, category, symbol):
        size, side = self.pos[symbol]
        return {"retCode": 0, "result": {"list": [{"symbol": symbol, "size": str(size), "side": side}]}}

    # test controls
    def fill_limit(self, oid, qty):
        o = self.orders[oid]
        o["filled_qty"] += qty
        o["avg_price"] = o["price"]
        o["status"] = "Filled" if o["filled_qty"] >= o["qty"] - 1e-12 else "PartiallyFilled"
        self.pos["BTCUSDT"][0] = max(self.pos["BTCUSDT"][0] - qty, 0.0)

    def stop_fills(self):
        self.pos["BTCUSDT"][0] = 0.0
        for o in self.orders.values():               # Bybit cancels reduce-only orders on a flat position
            if o["status"] == "New":
                o["status"] = "Cancelled"

    def status(self, _cfg, oid):
        o = self.orders.get(str(oid))
        if o is None:
            return {"order_id": oid, "status": "not_found", "filled_qty": 0.0, "avg_price": 0.0}
        return {"order_id": oid, **{k: o[k] for k in ("status", "filled_qty", "avg_price")}}

    def positions(self, _cfg):
        out = [{"symbol": s, "side": v[1], "size": v[0]} for s, v in self.pos.items() if v[0] > 0]
        return out


class FakeDB:
    def __init__(self, rows):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.pkg_writes = []

    def get_trades(self, filters=None, limit=None):
        out = []
        for r in self.rows.values():
            if all(str(r.get(k)) == str(v) for k, v in (filters or {}).items()):
                out.append(dict(r))
        return out

    def update_trade(self, tid, upd):
        self.rows[int(tid)].update(upd)

    def update_order_package(self, pkg, upd):
        self.pkg_writes.append((pkg, upd))


def _row(tid=7001, account="bybit_1", **kw):
    r = {"id": tid, "account_id": account, "symbol": "BTCUSDT", "direction": "long", "position_size": 0.01,
         "status": "open", "order_package_id": "pkg-d9", "is_backtest": 0, "strategy_name": "ml_entry",
         "sl_order_id": f"sl-{tid}", "tp_order_id": f"tp-{tid}", "notes": json.dumps({"trade_id": f"entry-{tid}"})}
    r.update(kw)
    return r


PKG = {"order_package_id": "pkg-d9", "linked_trade_id": 7001, "strategy_name": "ml_entry", "symbol": "BTCUSDT",
       "sl": 63000.0, "tp": 66000.0}
MAX_HOLD = {"action": "close", "reason": "max_hold"}


@pytest.fixture
def venue(monkeypatch):
    v = Venue()
    cfgs = {"bybit_1": DEMO, "bybit_2": REAL}
    monkeypatch.setattr(om, "_build_account_client", lambda aid: (v, dict(cfgs[aid])))
    monkeypatch.setattr("src.units.accounts.clients.account_order_status", v.status)

    class _Pos(list):
        unreadable_symbols = ()
    monkeypatch.setattr("src.units.accounts.clients.account_open_positions", lambda cfg: _Pos(v.positions(cfg)))
    monkeypatch.setattr("src.units.accounts.execute._bybit_close_headroom",
                        lambda *a, **k: (None, "not_applicable"))
    monkeypatch.setattr(om, "_finish_package_after_leg_close", lambda *a, **k: None)
    monkeypatch.setattr(mx, "full_leg_cfg", lambda name, path=None: _legs(name))
    monkeypatch.setattr(mx, "_now", lambda: v.now)
    v.now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    return v


def _pass(db, verdict=MAX_HOLD, pkg=PKG):
    s = om._StrategyTickSummary()
    om._apply_update(db, dict(pkg), dict(verdict), s)
    return s


def _blk(db, tid=7001):
    return mx.block_of(db.rows[tid]["notes"])


def _markets(v):
    return [p for p in v.placed if p["orderType"] == "Market"]


def test_first_pass_rests_a_post_only_reduce_only_limit_at_the_passive_mid(venue):
    db = FakeDB([_row()])
    _pass(db)
    assert len(venue.placed) == 1
    o = venue.placed[0]
    assert (o["orderType"], o["timeInForce"], o["reduceOnly"], o["side"]) == ("Limit", "PostOnly", True, "Sell")
    assert o["price"] == "64000.1" and o["qty"] == "0.01"       # one-tick book: the near touch
    assert db.rows[7001]["status"] == "open"                       # the row is NOT closed on "resting"
    b = _blk(db)
    assert b["state"] == "resting" and b["limit_order_id"] == "oid-1" and b["fallback_after_s"] == 60
    assert venue.cancelled == []                                   # the venue SL/TP are untouched
    assert json.loads(db.rows[7001]["notes"])["trade_id"] == "entry-7001"   # the reconciler's pointer kept


def test_inside_the_window_nothing_is_sent_again(venue):
    db = FakeDB([_row()])
    _pass(db)
    venue.now += timedelta(seconds=30)
    _pass(db)
    assert len(venue.placed) == 1 and venue.cancelled == []
    assert db.rows[7001]["status"] == "open"


def test_a_full_maker_fill_closes_the_row_at_the_limit_price_with_no_market_order(venue):
    db = FakeDB([_row()])
    _pass(db)
    venue.fill_limit("oid-1", 0.01)
    venue.now += timedelta(seconds=20)
    _pass(db)
    r = db.rows[7001]
    assert _markets(venue) == []
    assert r["status"] == "closed" and r["exit_reason"] == "max_hold"
    assert r["exit_price"] == 64000.1
    notes = json.loads(r["notes"])
    assert notes["exit_price_source"] == "exchange"
    assert notes["maker_exit"]["state"] == "filled_maker" and notes["maker_exit"]["is_maker"] is True
    assert set(venue.cancelled) == {"sl-7001", "tp-7001"}          # the row's own tracked legs, after the fill


def test_window_expired_with_zero_fill_cancels_then_market_closes_the_whole_row(venue):
    db = FakeDB([_row()])
    _pass(db)
    venue.now += timedelta(seconds=61)
    _pass(db)
    assert venue.cancelled[0] == "oid-1"
    m = _markets(venue)
    assert len(m) == 1 and m[0]["qty"] == "0.01" and m[0]["reduceOnly"] is True and m[0]["side"] == "Sell"
    r = db.rows[7001]
    assert r["status"] == "closed" and r["exit_reason"] == "max_hold" and r["exit_price"] == 64001.0
    assert json.loads(r["notes"])["maker_exit"]["state"] == "fallback_market"


def test_partial_fill_then_expiry_market_closes_only_the_remainder_at_a_blended_price(venue):
    db = FakeDB([_row()])
    _pass(db)
    venue.fill_limit("oid-1", 0.004)
    venue.now += timedelta(seconds=61)
    _pass(db)
    m = _markets(venue)
    assert len(m) == 1 and m[0]["qty"] == "0.006"                 # position - filled, never the full size
    r = db.rows[7001]
    want = (0.004 * 64000.1 + 0.006 * 64001.0) / 0.01
    assert r["status"] == "closed" and r["exit_price"] == pytest.approx(want)
    b = json.loads(r["notes"])["maker_exit"]
    assert b["filled_qty"] == pytest.approx(0.004) and b["state"] == "fallback_market"


def test_post_only_refused_at_the_door_market_closes_in_the_same_pass(venue):
    venue.reject_post_only = True
    db = FakeDB([_row()])
    _pass(db)
    assert [p["orderType"] for p in venue.placed] == ["Limit", "Market"]
    r = db.rows[7001]
    assert r["status"] == "closed" and r["exit_reason"] == "max_hold"
    assert json.loads(r["notes"])["maker_exit"]["state"] == "place_failed"


def test_post_only_cancelled_after_placement_market_closes_at_once(venue):
    db = FakeDB([_row()])
    _pass(db)
    venue.orders["oid-1"]["status"] = "Cancelled"                  # EC_PostOnlyWillTakeLiquidity after ack
    venue.now += timedelta(seconds=5)
    _pass(db)
    assert len(_markets(venue)) == 1 and db.rows[7001]["status"] == "closed"


def test_a_stop_during_the_window_releases_to_the_reconciler_and_sends_no_market(venue):
    db = FakeDB([_row()])
    _pass(db)
    venue.stop_fills()
    venue.now += timedelta(seconds=10)
    _pass(db)
    assert _markets(venue) == []                                   # no 'position is zero' close labelled max_hold
    r = db.rows[7001]
    assert r["status"] == "open"                                   # the forward reconciler closes it on the stop
    assert _blk(db)["state"] == "released_venue_flat"
    assert mx.reconciler_defers(r["notes"], venue.now) is False


def test_a_stop_after_the_window_with_a_still_live_limit_also_releases(venue):
    """If the venue left the limit live on a flat position, the expiry path still checks before a Market close."""
    db = FakeDB([_row()])
    _pass(db)
    venue.pos["BTCUSDT"][0] = 0.0                                  # stop filled, limit NOT auto-cancelled
    venue.now += timedelta(seconds=61)
    _pass(db)
    assert venue.cancelled == ["oid-1"] and _markets(venue) == []
    assert _blk(db)["state"] == "released_venue_flat"


def test_a_real_money_leg_keeps_todays_market_exit_byte_for_byte(venue):
    db = FakeDB([_row(account="bybit_2")])
    _pass(db)
    assert [p["orderType"] for p in venue.placed] == ["Market"]
    assert "timeInForce" not in venue.placed[0]
    assert db.rows[7001]["status"] == "closed"
    assert "maker_exit" not in json.loads(db.rows[7001]["notes"])


def test_a_protective_close_on_the_demo_floor_is_never_worked_passively(venue):
    db = FakeDB([_row()])
    _pass(db, {"action": "close", "reason": "sl_cross"})
    assert [p["orderType"] for p in venue.placed] == ["Market"]


def test_a_resting_demo_leg_does_not_hold_up_the_real_money_leg(venue):
    """One package across bybit_1 (resting) and bybit_2: the real-money leg closes at Market meanwhile."""
    db = FakeDB([_row(7001, "bybit_1"), _row(7002, "bybit_2")])
    _pass(db)                                                      # places bybit_1's limit; one venue act per tick
    assert db.rows[7002]["status"] == "open"
    venue.now += timedelta(seconds=20)
    _pass(db)                                                      # bybit_1 waits -> bybit_2 is the leg acted on
    assert db.rows[7002]["status"] == "closed" and db.rows[7001]["status"] == "open"
    assert [p["orderType"] for p in venue.placed] == ["Limit", "Market"]


def test_a_protective_close_while_resting_cancels_the_limit_and_goes_to_market_now(venue):
    db = FakeDB([_row()])
    _pass(db)
    venue.now += timedelta(seconds=5)                              # well inside the window
    _pass(db, {"action": "close", "reason": "sl_cross"})
    assert venue.cancelled[0] == "oid-1"
    assert len(_markets(venue)) == 1 and db.rows[7001]["status"] == "closed"
    assert db.rows[7001]["exit_reason"] == "sl_cross"
    assert json.loads(db.rows[7001]["notes"])["maker_exit"]["fallback_reason"] == "protective_close"


def test_unreadable_status_waits_then_gives_up_to_market(venue, monkeypatch):
    db = FakeDB([_row()])
    _pass(db)
    monkeypatch.setattr("src.units.accounts.clients.account_order_status", lambda cfg, oid: None)
    venue.now += timedelta(seconds=120)
    _pass(db)
    assert _markets(venue) == []
    venue.now += timedelta(seconds=mx.UNREAD_GIVE_UP_S)
    monkeypatch.setattr(om, "_capture_fill_details", lambda *a, **k: None)
    _pass(db)
    assert len(_markets(venue)) == 1 and "oid-1" in venue.cancelled


# --- the reconciliation side ----------------------------------------------------------------------------------

def test_reconciler_defers_only_while_resting_and_only_for_a_bounded_time():
    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    resting = json.dumps({"maker_exit": {"state": "resting", "placed_at": now.isoformat()}})
    assert mx.reconciler_defers(resting, now + timedelta(seconds=30)) is True
    assert mx.reconciler_defers(resting, now + timedelta(seconds=mx.ABANDON_S)) is False
    assert mx.reconciler_defers(json.dumps({"maker_exit": {"state": "filled_maker"}}), now) is False
    assert mx.reconciler_defers(json.dumps({"trade_id": "x"}), now) is False


class _SqlDB:
    def __init__(self, tmp_path, rows):
        import sqlite3
        self.path = str(tmp_path / "j.db")
        c = sqlite3.connect(self.path)
        c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, notes TEXT, "
                  "status TEXT, is_backtest INTEGER)")
        for r in rows:
            c.execute("INSERT INTO trades VALUES (?,?,?,?,?,0)",
                      (r["id"], r["account_id"], r["symbol"], r["notes"], r["status"]))
        c.commit()
        c.close()
        self.updates = []

    def connect(self):
        import sqlite3
        return sqlite3.connect(self.path)

    def update_trade(self, tid, upd):
        self.updates.append((tid, upd))


def test_sweep_cancels_a_limit_left_resting_on_a_closed_row_and_abandons_a_stale_one(tmp_path):
    v = Venue()
    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    v.orders = {"L1": {"status": "New", "filled_qty": 0.0, "avg_price": 0.0},
                "L2": {"status": "New", "filled_qty": 0.0, "avg_price": 0.0},
                "L3": {"status": "New", "filled_qty": 0.0, "avg_price": 0.0}}

    def n(oid, age):
        return json.dumps({"maker_exit": {"state": "resting", "limit_order_id": oid,
                                          "placed_at": (now - timedelta(seconds=age)).isoformat()}})
    db = _SqlDB(tmp_path, [
        {"id": 1, "account_id": "bybit_1", "symbol": "BTCUSDT", "notes": n("L1", 20), "status": "closed"},
        {"id": 2, "account_id": "bybit_1", "symbol": "BTCUSDT", "notes": n("L2", mx.ABANDON_S + 1), "status": "open"},
        {"id": 3, "account_id": "bybit_1", "symbol": "BTCUSDT", "notes": n("L3", 20), "status": "open"},
    ])
    out = mx.sweep_maker_exits(db, build_client=lambda aid: (v, DEMO), order_status=v.status, now=now)
    assert out["resolved"] == 2 and sorted(v.cancelled) == ["L1", "L2"]       # L3: the exit pass owns it
    states = {tid: json.loads(u["notes"])["maker_exit"]["state"] for tid, u in db.updates}
    assert states == {1: "cancelled_row_not_open", 2: "abandoned"}


def test_the_forward_reconciler_skips_a_resting_row(monkeypatch):
    """Wiring: _reconcile_open_trades consults maker_exit.reconciler_defers before reading the entry order."""
    import inspect
    src = inspect.getsource(om._reconcile_open_trades)
    assert "reconciler_defers" in src and src.index("reconciler_defers") < src.index("account_order_status(cfg, trade_id_str)")
    src_tick = inspect.getsource(om.run_reconciliation_tick)
    assert src_tick.index("sweep_maker_exits") < src_tick.index('_recon_phase("reconcile_open_trades")')
