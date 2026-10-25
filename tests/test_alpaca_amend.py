"""AMEND-PARITY-ALL-ACCOUNTS — the Alpaca tighten executor with venue read-back.

A fake venue models the Alpaca semantics the executor relies on: a bracket's
stop rests ``held`` nested under its parent, and ``PATCH /v2/orders/{id}``
REPLACES the order (new id, old id goes ``replaced``). Nothing here touches a
network.
"""
from __future__ import annotations

import copy
import json

from src.units.accounts import alpaca_amend as aa


class FakeAlpaca:
    def __init__(self, *, legs, position=None, partial_parent_legs=(),
                 patch_effective=True, patch_rc=0, patch_returns_id=True):
        self.legs = copy.deepcopy(legs)
        self.position = position or {"state": "open", "qty": 10.0, "side": "long",
                                     "current_price": 105.0}
        self.partial_parent_legs = list(partial_parent_legs)
        self.patch_effective = patch_effective
        self.patch_rc = patch_rc
        self.patch_returns_id = patch_returns_id
        self.patches = []
        self._n = 0

    def position_quote(self, symbol):
        return dict(self.position)

    def _open_orders_for_symbol(self, symbol, since=None):
        return [dict(o) for o in self.legs if o["status"] not in ("replaced", "canceled")]

    def _request(self, method, path, body=None):
        if method == "GET":
            parents = []
            if self.partial_parent_legs:
                parents.append({"id": "parent-p", "status": "partially_filled",
                                "legs": [{"id": i} for i in self.partial_parent_legs]})
            return {"retCode": 0, "result": parents}
        assert method == "PATCH"
        oid = path.rsplit("/", 1)[-1]
        self.patches.append((oid, body))
        if self.patch_rc:
            return {"retCode": self.patch_rc, "retMsg": "rejected"}
        self._n += 1
        new_id = f"{oid}-r{self._n}"
        if self.patch_effective:
            for o in self.legs:
                if o["id"] == oid:
                    o["status"] = "replaced"
                    new = {**o, "id": new_id, "status": "held" if "stop" in o["type"] else "new"}
                    new.update({k: v for k, v in body.items()})
                    self.legs.append(new)
                    break
        return {"retCode": 0, "result": ({"id": new_id, "replaces": oid}
                                         if self.patch_returns_id else {})}


def _oco(qty=10, stop=100.0, tp=120.0, side="sell"):
    return [
        {"id": "tp-1", "type": "limit", "side": side, "qty": str(qty), "status": "new",
         "limit_price": str(tp)},
        {"id": "sl-1", "type": "stop", "side": side, "qty": str(qty), "status": "held",
         "stop_price": str(stop)},
    ]


def test_tighten_long_applied_with_readback_and_oco_ids():
    c = FakeAlpaca(legs=_oco())
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=101.234, apply=True)
    assert r["result"] == aa.X_APPLIED, r
    assert c.patches == [("sl-1", {"stop_price": "101.24"})]  # rounded TIGHTER (up)
    assert r["oco_leg_ids"] == {"stop": "sl-1", "target": "tp-1"}
    assert r["oco_leg_ids_after"] == {"stop": "sl-1-r1", "target": "tp-1"}
    assert r["venue_after"] == 101.24


def test_tighten_only_refuses_looser_and_equal():
    c = FakeAlpaca(legs=_oco(stop=100.0))
    for lvl in (99.0, 100.0):
        r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=lvl, apply=True)
        assert r["result"] == aa.X_REFUSED and "already_at_or_tighter" in r["detail"]
    assert c.patches == []


def test_short_tightens_down():
    c = FakeAlpaca(legs=_oco(stop=110.0, tp=90.0, side="buy"),
                   position={"state": "open", "qty": 10.0, "side": "short", "current_price": 105.0})
    r = aa.tighten(c, symbol="SPY", direction="short", qty=10, new_sl=108.006, apply=True)
    assert r["result"] == aa.X_APPLIED
    assert c.patches == [("sl-1", {"stop_price": "108.00"})]  # rounded DOWN for a short
    r = aa.tighten(c, symbol="SPY", direction="short", qty=10, new_sl=109.0, apply=True)
    assert r["result"] == aa.X_REFUSED


def test_readback_mismatch_is_apply_failed():
    # Alpaca 2xx-accepts the PATCH but nothing moves (the GLD wedge's lesson).
    c = FakeAlpaca(legs=_oco(), patch_effective=False)
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0, apply=True)
    assert r["result"] == aa.X_APPLY_FAILED
    assert "old stop leg sl-1 still rests" in r["detail"]


def test_readback_mismatch_without_returned_id_is_apply_failed():
    c = FakeAlpaca(legs=_oco(), patch_effective=False, patch_returns_id=False)
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0, apply=True)
    assert r["result"] == aa.X_APPLY_FAILED
    assert "venue reads stop 100.0" in r["detail"]


def test_patch_rejected_is_apply_failed():
    c = FakeAlpaca(legs=_oco(), patch_rc=422)
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0, apply=True)
    assert r["result"] == aa.X_APPLY_FAILED and "refused" in r["detail"]


def test_partially_filled_bracket_is_refused():
    c = FakeAlpaca(legs=_oco(), partial_parent_legs=["sl-1", "tp-1"])
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0, apply=True)
    assert r["result"] == aa.X_REFUSED and "parent_partially_filled" in r["detail"]
    assert c.patches == []


def test_stop_through_market_wedge_is_refused():
    # GLD shape: long, stop 416.09 "held" while the mark is ~382.
    c = FakeAlpaca(legs=_oco(stop=416.09, tp=461.27),
                   position={"state": "open", "qty": 10.0, "side": "long", "current_price": 382.0})
    r = aa.tighten(c, symbol="GLD", direction="long", qty=10, new_sl=417.0, apply=True)
    assert r["result"] == aa.X_REFUSED and "venue_stop_through_market" in r["detail"]
    assert c.patches == []


def test_would_trigger_is_refused():
    c = FakeAlpaca(legs=_oco())
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=105.5, apply=True)
    assert r["result"] == aa.X_REFUSED and "would_trigger" in r["detail"]


def test_sibling_legs_of_another_size_are_never_touched():
    legs = _oco(qty=10) + [
        {"id": "sl-sib", "type": "stop", "side": "sell", "qty": "4", "status": "held", "stop_price": "95"},
        {"id": "tp-sib", "type": "limit", "side": "sell", "qty": "4", "status": "new", "limit_price": "130"},
    ]
    c = FakeAlpaca(legs=legs, position={"state": "open", "qty": 14.0, "side": "long", "current_price": 105.0})
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0, apply=True)
    assert r["result"] == aa.X_APPLIED
    assert [p[0] for p in c.patches] == ["sl-1"]


def test_two_same_size_legs_refuse_as_ambiguous():
    c = FakeAlpaca(legs=_oco() + [{"id": "sl-2", "type": "stop", "side": "sell", "qty": "10",
                                   "status": "held", "stop_price": "99"}],
                   position={"state": "open", "qty": 20.0, "side": "long", "current_price": 105.0})
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0, apply=True)
    assert r["result"] == aa.X_REFUSED and "ambiguous" in r["detail"]


def test_read_failures_are_could_not_look_and_send_nothing():
    c = FakeAlpaca(legs=_oco(), position={"state": "could_not_look"})
    assert aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0,
                      apply=True)["result"] == aa.X_COULD_NOT_LOOK
    c = FakeAlpaca(legs=_oco())
    c._open_orders_for_symbol = lambda s, since=None: None
    assert aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0,
                      apply=True)["result"] == aa.X_COULD_NOT_LOOK
    c = FakeAlpaca(legs=_oco())
    c.legs[1]["status"] = "pending_replace"
    assert aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0,
                      apply=True)["result"] == aa.X_COULD_NOT_LOOK
    assert c.patches == []


def test_flat_and_naked_are_refused():
    c = FakeAlpaca(legs=_oco(), position={"state": "flat", "qty": 0.0})
    assert aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0)["result"] == aa.X_REFUSED
    c = FakeAlpaca(legs=_oco()[:1])  # target only, no stop rests
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0, apply=True)
    assert r["result"] == aa.X_REFUSED and "naked" in r["detail"]


def test_tp_amend_moves_only_the_target_leg():
    c = FakeAlpaca(legs=_oco())
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_tp=118.0, apply=True)
    assert r["result"] == aa.X_APPLIED
    assert c.patches == [("tp-1", {"limit_price": "118.00"})]


def test_dry_run_sends_nothing():
    c = FakeAlpaca(legs=_oco())
    r = aa.tighten(c, symbol="SPY", direction="long", qty=10, new_sl=102.0)
    assert r["result"] == aa.X_PLANNED and c.patches == []
    assert r["plan"] == [{"kind": "stop", "leg_id": "sl-1", "field": "stop_price",
                          "from": 100.0, "to": 102.0}]


class FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def get_trades(self, filters=None):
        return [r for r in self.rows if r["account_id"] == filters.get("account_id")]

    def update_trade(self, tid, fields):
        self.updates.append((tid, fields))


def test_exec_trade_leg_writes_journal_only_after_readback():
    trade = {"id": 7, "account_id": "alpaca_live", "symbol": "SPY", "direction": "long",
             "position_size": 10, "stop_loss": 100.0, "notes": "{}"}
    db = FakeDB([trade])
    r = aa.exec_trade_leg(db, trade, 102.0, source="live_review_mandate", review_id="rv-1",
                          client=FakeAlpaca(legs=_oco()))
    assert r["result"] == aa.X_APPLIED
    (tid, fields), = db.updates
    assert tid == 7 and fields["stop_loss"] == 102.0
    notes = json.loads(fields["notes"])
    assert notes["sl_floor"]["level"] == 102.0
    assert notes["sl_amends"][-1]["oco_leg_ids"] == {"stop": "sl-1-r1", "target": "tp-1"}

    db = FakeDB([trade])
    r = aa.exec_trade_leg(db, trade, 102.0, source="x", client=FakeAlpaca(legs=_oco(), patch_effective=False))
    assert r["result"] == aa.X_APPLY_FAILED and db.updates == []


def test_dry_run_cli_lists_open_trades_read_only():
    trade = {"id": 7, "account_id": "alpaca_live", "symbol": "SPY", "direction": "long",
             "position_size": 10, "stop_loss": 100.0, "take_profit": 120.0}
    c = FakeAlpaca(legs=_oco())
    rows = aa.dry_run("alpaca_live", db=FakeDB([trade]), client=c)
    assert rows[0]["result"] == "read_only" and rows[0]["oco_leg_ids"]["stop"] == "sl-1"
    rows = aa.dry_run("alpaca_live", db=FakeDB([trade]), client=c, new_sl=103.0)
    assert rows[0]["result"] == aa.X_PLANNED and c.patches == []
