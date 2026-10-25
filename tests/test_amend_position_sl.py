"""Tests for scripts/ops/amend_position_sl.py — the operator-directed stop
TIGHTENING action (AMEND-SL-ACTION, 2026-10-24).

All broker and journal I/O is faked: a fake Bybit client holds the position and
the resting stop legs, and the patched monitor modify seam moves the fake leg
the way ``modify_open_order``'s in-place amend would. These pin the decision
logic: refuse looser, refuse wrong-side, refuse missing row/position/non-live,
the happy path, venue + journal consistency, idempotency, and that the
monitor's trail respects the tighter package stop afterwards.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "amend_position_sl",
    Path(__file__).resolve().parents[1] / "scripts" / "ops" / "amend_position_sl.py",
)
amend_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(amend_mod)  # type: ignore


class FakeClient:
    def __init__(self, *, side="Sell", size="100", mark="0.2022", legs=None,
                 pos_sl="0"):
        self.side, self.size, self.mark, self.pos_sl = side, size, mark, pos_sl
        self.legs = legs if legs is not None else {}  # orderId -> trigger

    def get_positions(self, **_kw):
        return {"result": {"list": [{"side": self.side, "size": self.size,
                                     "markPrice": self.mark, "stopLoss": self.pos_sl}]}}

    def get_open_orders(self, **_kw):
        return {"result": {"list": [
            {"orderId": oid, "stopOrderType": "PartialStopLoss", "triggerPrice": str(px)}
            for oid, px in self.legs.items()]}}


class FakeDB:
    def __init__(self, trades, pkg):
        self.trades = {t["id"]: dict(t) for t in trades}
        self.pkg = dict(pkg)
        self.trade_writes, self.pkg_writes = [], []

    def get_trades(self, filters=None, limit=None):
        out = []
        for t in self.trades.values():
            if all(str(t.get(k)) == str(v) for k, v in (filters or {}).items()):
                out.append(dict(t))
        return out

    def update_trade(self, tid, updates):
        self.trade_writes.append((tid, dict(updates)))
        self.trades[tid].update(updates)
        return 1

    def update_order_package(self, pid, updates):
        self.pkg_writes.append((pid, dict(updates)))
        self.pkg.update(updates)
        return 1


def _trade(tid=101, account="bybit_2", sl=0.2154, oid="SL-A", **kw):
    return {"id": tid, "account_id": account, "symbol": "ADAUSDT", "direction": "short",
            "status": "open", "order_package_id": "pkg-1", "stop_loss": sl,
            "sl_order_id": oid, "position_size": 100, "notes": json.dumps({"k": "v"}),
            "strategy_name": "ada_pullback_2h", **kw}


@pytest.fixture
def world(monkeypatch):
    clients = {"bybit_2": FakeClient(legs={"SL-A": 0.2154}),
               "bybit_portfolio": FakeClient(legs={"SL-B": 0.2154})}
    modes = {"bybit_2": "live", "bybit_portfolio": "live", "bybit_1": "dry_run"}
    db = FakeDB([_trade(), _trade(tid=102, account="bybit_portfolio", oid="SL-B")],
                {"order_package_id": "pkg-1", "status": "open", "sl": 0.2154, "tp": 0.18})
    sent = []

    def _build(aid):
        if aid not in modes:
            return None, None
        return clients.get(aid), {"account_id": aid, "exchange": "bybit",
                                  "market_type": "linear", "mode": modes[aid]}

    def _send(leg, **kw):
        sent.append((leg["id"], kw))
        c = clients[leg["account_id"]]
        c.legs[leg["sl_order_id"]] = kw["sl"]
        return {"ok": True, "exchange_response": {}, "error": None}

    monkeypatch.setattr(amend_mod, "_build_client", _build)
    monkeypatch.setattr(amend_mod, "_open_db", lambda: db)
    monkeypatch.setattr(amend_mod, "_get_package", lambda _db, pid: db.pkg if pid == "pkg-1" else None)
    monkeypatch.setattr(amend_mod, "_tick_size", lambda *a: 0.0001)
    monkeypatch.setattr(amend_mod, "_send_modify", _send)
    monkeypatch.setattr(amend_mod, "_ping", lambda *a, **k: None)
    return {"clients": clients, "modes": modes, "db": db, "sent": sent}


def _run(**kw):
    args = {"new_sl": 0.2053, "reason": "operator popup 2026-10-24", "trade_id": 101,
            "apply": True}
    args.update(kw)
    return amend_mod.amend("bybit_2", **args)


# ---- refusals -----------------------------------------------------------

def test_refuses_looser_stop_on_a_short(world):
    r = _run(new_sl=0.2200)
    assert r["exit"] == amend_mod.EXIT_REFUSED and r["action"] == "refuse_looser"
    assert world["sent"] == [] and world["db"].trade_writes == [] and world["db"].pkg_writes == []


def test_refuses_looser_than_the_resting_venue_stop(world):
    # journal says 0.2154 but the venue already rests tighter at 0.2040
    world["clients"]["bybit_2"].legs["SL-A"] = 0.2040
    r = _run()
    assert r["action"] == "refuse_looser" and "venue" in r["detail"]
    assert world["sent"] == []


def test_refuses_looser_stop_on_a_long(world):
    db = world["db"]
    for t in db.trades.values():
        t.update(direction="long", stop_loss=0.19)
    db.pkg["sl"] = 0.19
    for c in world["clients"].values():
        c.side, c.legs = "Buy", {k: 0.19 for k in c.legs}
    r = _run(new_sl=0.185)
    assert r["action"] == "refuse_looser"


def test_refuses_wrong_side_of_mark_unless_allowed(world):
    r = _run(new_sl=0.2010)  # short stop BELOW the 0.2022 mark fires at once
    assert r["action"] == "refuse_wrong_side" and world["sent"] == []
    r2 = _run(new_sl=0.2010, allow_immediate=True)
    assert r2["action"] == "applied"


def test_refuses_missing_trade_row(world):
    r = _run(trade_id=999)
    assert r["action"] == "refuse_no_trade" and r["exit"] == amend_mod.EXIT_REFUSED


def test_refuses_missing_position(world):
    world["clients"]["bybit_2"].size = "0"
    r = _run()
    assert r["action"] == "refuse_no_position" and world["sent"] == []


def test_refuses_non_live_account(world):
    world["modes"]["bybit_2"] = "dry_run"
    r = _run()
    assert r["action"] == "refuse_not_live"


def test_refuses_trade_on_another_account(world):
    r = _run(trade_id=102)
    assert r["action"] == "refuse_wrong_account"


def test_unreadable_venue_is_exit_3_not_a_refusal(world):
    def boom(**_kw):
        raise RuntimeError("timeout")
    world["clients"]["bybit_2"].get_positions = boom
    r = _run()
    assert r["exit"] == amend_mod.EXIT_UNREADABLE and r["action"] == "unreadable_venue"


# ---- happy path + consistency ---------------------------------------------

def test_dry_run_changes_nothing(world):
    r = _run(apply=False)
    assert r["action"] == "dry_run" and r["exit"] == 0
    assert r["plan"]["venue_amend_trade_ids"] == [101, 102]
    assert world["sent"] == [] and world["db"].trade_writes == [] and world["db"].pkg_writes == []


def test_apply_moves_venue_and_journal_together_on_every_leg(world):
    r = _run()
    assert r["action"] == "applied" and r["exit"] == 0, r
    db = world["db"]
    # venue
    assert world["clients"]["bybit_2"].legs["SL-A"] == 0.2053
    assert world["clients"]["bybit_portfolio"].legs["SL-B"] == 0.2053
    # journal: package + both trade rows, with provenance
    assert db.pkg["sl"] == 0.2053
    for tid in (101, 102):
        assert db.trades[tid]["stop_loss"] == 0.2053
        notes = json.loads(db.trades[tid]["notes"])
        assert notes["k"] == "v"
        last = notes["sl_amends"][-1]
        assert last["source"] == "manual_amend_operator"
        assert last["reason"] == "operator popup 2026-10-24"
        assert last["from"] == 0.2154 and last["to"] == 0.2053
    # the monitor seam got the trade's own direction and the package's current levels
    _, kw = world["sent"][0]
    assert kw["side"] == "short" and kw["cur_sl"] == 0.2154 and kw["sl"] == 0.2053
    # before / after are both reported
    assert r["before"]["package"]["sl"] == 0.2154 and r["after"]["package"]["sl"] == 0.2053


def test_apply_is_idempotent(world):
    _run()
    writes = (len(world["db"].trade_writes), len(world["db"].pkg_writes), len(world["sent"]))
    r = _run()
    assert r["action"] == "already_applied" and r["exit"] == 0
    assert (len(world["db"].trade_writes), len(world["db"].pkg_writes), len(world["sent"])) == writes


def test_target_venue_not_verified_leaves_journal_unchanged(world, monkeypatch):
    # The venue says ok but the read-back still shows the old stop.
    monkeypatch.setattr(amend_mod, "_send_modify",
                        lambda leg, **kw: {"ok": True, "exchange_response": {}, "error": None})
    r = _run()
    assert r["action"] == "amend_failed" and r["exit"] == amend_mod.EXIT_FAILED
    assert world["db"].trade_writes == [] and world["db"].pkg_writes == []


def test_sibling_failure_still_moves_target_and_package_then_rerun_finishes(world, monkeypatch):
    real = amend_mod._send_modify

    def _flaky(leg, **kw):
        if leg["id"] == 102:
            return {"ok": False, "error": "retCode=10006"}
        return real(leg, **kw)
    monkeypatch.setattr(amend_mod, "_send_modify", _flaky)
    r = _run()
    assert r["action"] == "partial" and r["exit"] == amend_mod.EXIT_FAILED
    db = world["db"]
    assert db.pkg["sl"] == 0.2053 and db.trades[101]["stop_loss"] == 0.2053
    assert db.trades[102]["stop_loss"] == 0.2154  # unverified leg not written
    monkeypatch.setattr(amend_mod, "_send_modify", real)
    r2 = _run()
    assert r2["action"] == "applied" and r2["plan"]["venue_amend_trade_ids"] == [102]
    assert db.trades[102]["stop_loss"] == 0.2053


def test_symbol_side_resolution(world):
    r = _run(trade_id=None, symbol="ADAUSDT", side="short", apply=False)
    assert r["action"] == "dry_run" and r["trade_id"] == 101


# ---- the monitor keeps the tighter stop ------------------------------------

def test_pullback_trail_never_loosens_a_tighter_package_stop():
    """The reason the journal must move with the venue: the trail compares to
    open_pkg['sl'] and, for a short, only ever proposes a LOWER stop."""
    from src.units.strategies import htf_pullback_trend_2h as mod

    n = 30
    candles = pd.DataFrame({
        "open": [0.205] * n, "high": [0.206] * n, "low": [0.200] * n,
        "close": [0.2022] * n,
        "timestamp": pd.date_range("2026-10-20", periods=n, freq="2h", tz="UTC"),
    })
    base = {"direction": "short", "entry": 0.2300, "tp": 0.15,
            "meta": {"atr": 0.004, "trail_mult": 3.0}}
    # looser package stop -> trail tightens it (candidate 0.200 + 0.012 = 0.212)
    v_loose = mod.monitor({}, candles, {**base, "sl": 0.2154})
    assert v_loose and v_loose.get("sl") is not None and v_loose["sl"] < 0.2154
    # tighter (manually amended) package stop -> no trail verdict that loosens it
    v_tight = mod.monitor({}, candles, {**base, "sl": 0.2053})
    assert not (v_tight and v_tight.get("sl") is not None and v_tight["sl"] > 0.2053)
