"""DESK-MAKER-FILLS probe (b): post-only entry at the touch, 5-min Market fallback, real-money fence."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.units.accounts import maker_entry as me
from src.units.accounts.execute import _submit_order

_DESK = {"name": "claude_desk", "entry_order": "post_only_touch"}
_PLAIN = {"name": "ict_scalp"}


def _loader(name):
    return {"claude_desk": _DESK, "ict_scalp": _PLAIN}[name]


DEMO = {"account_id": "bybit_1", "exchange": "bybit", "market_type": "linear", "demo": True,
        "account_class": "paper"}
REAL = {"account_id": "bybit_2", "exchange": "bybit", "market_type": "linear", "demo": False,
        "account_class": "real_money"}


class _Client:
    def __init__(self, bid="64000.0", ask="64000.1", ticker_raises=False):
        self.placed = []
        self.cancelled = []
        self.bid, self.ask, self.ticker_raises = bid, ask, ticker_raises

    def get_instruments_info(self, *, category, symbol):
        return {"result": {"list": [{"priceFilter": {"tickSize": "0.1"},
                                     "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"}}]}}

    def get_tickers(self, *, category, symbol):
        if self.ticker_raises:
            raise ConnectionError("ticker down")
        return {"result": {"list": [{"lastPrice": "64000", "bid1Price": self.bid, "ask1Price": self.ask}]}}

    def place_order(self, **kwargs):
        self.placed.append(kwargs)
        return {"retCode": 0, "result": {"orderId": f"oid-{len(self.placed)}"}}

    def cancel_order(self, **kwargs):
        self.cancelled.append(kwargs)
        return {"retCode": 0}

    def get_executions(self, **kwargs):
        return {"result": {"list": [{"execFee": "0.0256", "feeRate": "0.0002", "isMaker": True}]}}


def _order(side="Buy", strategy="claude_desk", **kw):
    o = {"account_id": "bybit_1", "symbol": "BTCUSDT", "side": side, "qty": 0.002,
         "sl": 63000.0 if side == "Buy" else 65000.0, "tp": 65000.0 if side == "Buy" else 63000.0,
         "strategy": strategy}
    o.update(kw)
    return o


@pytest.fixture(autouse=True)
def _desk_loader(monkeypatch):
    monkeypatch.setattr("src.strategy_registry._strategy_cfg", _loader)
    monkeypatch.delenv("BYBIT_TPSL_MODE", raising=False)


# --- the fence ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("cfg,order,cat,want", [
    (DEMO, _order(), "linear", "post_only_touch"),
    (REAL, _order(), "linear", "market"),                                     # real money: never
    (dict(DEMO, account_class="real_money"), _order(), "linear", "market"),
    ({k: v for k, v in DEMO.items() if k != "account_class"}, _order(), "linear", "market"),  # missing => refuse
    (dict(DEMO, demo=False), _order(), "linear", "market"),
    (DEMO, _order(strategy="ict_scalp"), "linear", "market"),                # leg does not declare it
    (DEMO, _order(reduce_only=True), "linear", "market"),
    (DEMO, _order(), "spot", "market"),
    (dict(DEMO, exchange="alpaca"), _order(), "linear", "market"),
])
def test_resolve_entry_order_fence(cfg, order, cat, want):
    assert me.resolve_entry_order(order, cfg, cat)[0] == want


def test_unknown_entry_order_value_is_market(monkeypatch):
    monkeypatch.setattr("src.strategy_registry._strategy_cfg", lambda n: {"entry_order": "iceberg"})
    assert me.leg_entry_order("claude_desk") == "market"


def test_unreadable_leg_is_market(monkeypatch):
    def boom(n):
        raise KeyError(n)
    monkeypatch.setattr("src.strategy_registry._strategy_cfg", boom)
    assert me.leg_entry_order("claude_desk") == "market"


def test_live_claude_desk_leg_declares_post_only_and_nothing_else_does():
    from pathlib import Path

    import yaml
    doc = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "strategies.yaml").read_text())
    legs = doc.get("strategies", doc)
    declared = {k for k, v in legs.items() if isinstance(v, dict) and v.get("entry_order")}
    assert declared == {"claude_desk"}
    assert legs["claude_desk"]["entry_order"] == "post_only_touch"


# --- order construction -------------------------------------------------------------------------------

@pytest.mark.parametrize("side,price", [("Buy", "64000.0"), ("Sell", "64000.1")])
def test_demo_desk_entry_is_post_only_at_the_touch_with_bracket(side, price):
    c = _Client()
    order = _order(side=side)
    _submit_order(c, order, DEMO)
    kw = c.placed[-1]
    assert kw["orderType"] == "Limit" and kw["timeInForce"] == "PostOnly" and kw["price"] == price
    assert kw["stopLoss"] and kw["takeProfit"]
    fb = order["maker_probe_notes"]["maker_probe"]["fallback_kwargs"]
    assert fb["orderType"] == "Market" and "price" not in fb and "timeInForce" not in fb
    assert fb["stopLoss"] == kw["stopLoss"] and fb["takeProfit"] == kw["takeProfit"] and fb["qty"] == kw["qty"]
    assert order["maker_probe_notes"]["maker_probe"]["state"] == "resting"


def test_real_money_account_never_receives_post_only_even_for_the_desk_leg():
    c = _Client()
    order = _order()
    _submit_order(c, order, REAL)
    kw = c.placed[-1]
    assert kw["orderType"] == "Market" and "timeInForce" not in kw and "price" not in kw
    assert "maker_probe_notes" not in order


def test_other_legs_are_byte_identical_market():
    c = _Client()
    order = _order(strategy="ict_scalp")
    _submit_order(c, order, DEMO)
    assert c.placed[-1]["orderType"] == "Market" and "maker_probe_notes" not in order


def test_unreadable_touch_sends_market():
    c = _Client(ticker_raises=True)
    order = _order()
    _submit_order(c, order, DEMO)
    assert c.placed[-1]["orderType"] == "Market" and "maker_probe_notes" not in order


# --- the fallback sweep -------------------------------------------------------------------------------

T0 = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)


def _row(placed=T0, size=0.002):
    notes = {"trade_id": "lim-1", **me.probe_notes(limit_price=64000.0, touch=64000.0, reason="x",
                                                   fallback_kwargs={"category": "linear", "symbol": "BTCUSDT",
                                                                    "side": "Buy", "orderType": "Market",
                                                                    "qty": "0.002", "stopLoss": "63000.0",
                                                                    "takeProfit": "65000.0"})}
    notes["maker_probe"]["placed_at"] = placed.isoformat()
    return {"id": 7, "account_id": "bybit_1", "symbol": "BTCUSDT", "created_at": placed.isoformat(),
            "position_size": size}, notes


def _status(seq):
    it = iter(seq)
    last = {}

    def f(cfg, tid):
        nonlocal last
        try:
            last = next(it)
        except StopIteration:
            pass
        return last
    return f


def _resolve(seq, age_s, client=None):
    row, notes = _row()
    c = client or _Client()
    upd = me.resolve_row(row, notes, client=c, cfg=DEMO, order_status=_status(seq), category="linear",
                         now=T0 + timedelta(seconds=age_s))
    return upd, c


def test_resting_inside_window_is_left_alone():
    upd, c = _resolve([{"status": "New", "filled_qty": 0}], 120)
    assert upd is None and not c.placed and not c.cancelled


def test_expired_zero_fill_cancels_then_sends_market_and_repoints():
    upd, c = _resolve([{"status": "New", "filled_qty": 0}, {"status": "Cancelled", "filled_qty": 0}], 301)
    assert c.cancelled and c.cancelled[0]["orderId"] == "lim-1"
    assert c.placed[-1]["orderType"] == "Market" and c.placed[-1]["stopLoss"] == "63000.0"
    notes = json.loads(upd["notes"])
    assert notes["trade_id"] == "oid-1" and notes["maker_probe"]["state"] == "fallback_market"
    assert notes["maker_probe"]["limit_order_id"] == "lim-1"


def test_post_only_reject_falls_back_at_once():
    upd, c = _resolve([{"status": "Cancelled", "filled_qty": 0}], 5)
    assert not c.cancelled and c.placed[-1]["orderType"] == "Market"
    assert json.loads(upd["notes"])["maker_probe"]["fallback_reason"] == "post_only_reject_or_cancelled"


def test_filled_records_maker_fee():
    upd, c = _resolve([{"status": "Filled", "filled_qty": 0.002}], 40)
    p = json.loads(upd["notes"])["maker_probe"]
    assert p["state"] == "filled_maker" and p["is_maker"] is True and p["fee_rates"] == ["0.0002"]
    assert not c.placed and "position_size" not in upd


def test_partial_fill_at_expiry_cancels_remainder_and_shrinks_size():
    upd, c = _resolve([{"status": "PartiallyFilled", "filled_qty": 0.001},
                       {"status": "PartiallyFilledCanceled", "filled_qty": 0.001}], 400)
    assert c.cancelled and not c.placed
    assert upd["position_size"] == 0.001
    assert json.loads(upd["notes"])["maker_probe"]["state"] == "partial_maker_remainder_cancelled"


def test_unreadable_status_retries():
    row, notes = _row()
    assert me.resolve_row(row, notes, client=_Client(), cfg=DEMO, order_status=lambda c, t: None,
                          category="linear", now=T0 + timedelta(seconds=900)) is None


def test_failed_fallback_is_recorded_and_not_repointed():
    class Bad(_Client):
        def place_order(self, **kw):
            return {"retCode": 10001, "retMsg": "nope"}
    upd, _ = _resolve([{"status": "Cancelled", "filled_qty": 0}], 5, client=Bad())
    notes = json.loads(upd["notes"])
    assert notes["trade_id"] == "lim-1" and notes["maker_probe"]["state"] == "fallback_failed"


class _DB:
    def __init__(self, rows):
        self.path = ":memory:"
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, notes TEXT,"
                          " created_at TEXT, position_size REAL, status TEXT, is_backtest INTEGER)")
        for r in rows:
            self.conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,0)", r)
        self.updates = []

    def connect(self):
        class _NoClose:
            def __init__(s, c):
                s._c = c

            def __getattr__(s, n):
                return getattr(s._c, n)

            def close(s):
                pass

            @property
            def row_factory(s):
                return s._c.row_factory

            @row_factory.setter
            def row_factory(s, v):
                s._c.row_factory = v
        return _NoClose(self.conn)

    def update_trade(self, tid, upd):
        self.updates.append((tid, upd))


def test_sweep_only_touches_resting_probe_rows():
    row, notes = _row()
    plain = json.dumps({"trade_id": "mkt-9"})
    done = dict(notes, maker_probe=dict(notes["maker_probe"], state="fallback_market"))
    db = _DB([(7, "bybit_1", "BTCUSDT", json.dumps(notes), row["created_at"], 0.002, "open"),
              (8, "bybit_1", "BTCUSDT", plain, row["created_at"], 0.002, "open"),
              (9, "bybit_1", "BTCUSDT", json.dumps(done), row["created_at"], 0.002, "open")])
    c = _Client()
    s = me.sweep_maker_entries(db, build_client=lambda a: (c, DEMO),
                               order_status=_status([{"status": "Cancelled", "filled_qty": 0}]),
                               now=T0 + timedelta(seconds=10))
    assert s == {"resting": 1, "resolved": 1, "errors": 0}
    assert [u[0] for u in db.updates] == [7]


def test_closed_row_with_resting_limit_is_cancelled_not_filled_into_an_untracked_position():
    row, notes = _row()
    row["status"] = "closed"
    c = _Client()
    upd = me.resolve_row(row, notes, client=c, cfg=DEMO, order_status=_status([{"status": "New", "filled_qty": 0}]),
                         category="linear", now=T0 + timedelta(seconds=30))
    assert c.cancelled and c.cancelled[0]["orderId"] == "lim-1" and not c.placed
    assert json.loads(upd["notes"])["maker_probe"]["state"] == "cancelled_row_not_open"


def test_fallback_targets_the_same_position_book(monkeypatch):
    from src.runtime import bybit_position_mode

    def fake_idx(kwargs, account_id, symbol, side):
        kwargs["positionIdx"] = 1

        class R:
            idx, state, reason = 1, "hedge", None
        return R()
    monkeypatch.setattr(bybit_position_mode, "apply_position_idx", fake_idx)
    c = _Client()
    order = _order()
    _submit_order(c, order, DEMO)
    assert c.placed[-1]["positionIdx"] == 1
    assert order["maker_probe_notes"]["maker_probe"]["fallback_kwargs"]["positionIdx"] == 1
