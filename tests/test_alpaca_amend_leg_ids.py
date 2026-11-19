"""ALPACA-AMEND-LEG-IDS — the Alpaca tighten executor scopes legs by ORDER ID.

The incident (MEASURED 2026-11-19 21:09Z): alpaca_portfolio held three SLV
short trades of qty=2 (7758 / 7766 / 7770), each with its own bracket. The
trail on each was refused ``ambiguous_legs: 3 stop / 3 target leg(s) of
qty=2.0`` because legs were matched by share count only, and the monitor
retried (and alerted) every tick.

The venue read the fix relies on (``/api/diag/alpaca_open_orders``,
alpaca_portfolio, 2026-11-19 21:21Z): every resting SLV stop leg is nested
under its trade's entry order (``trades.broker_order_id``), including legs a
PATCH replaced at 21:00Z. The fake below models exactly that: a leg carries
the ``parent`` it is nested under, a PATCH replacement inherits it, and
``GET /v2/orders/{id}?nested=true`` returns the parent's current legs.
"""
from __future__ import annotations

import copy

import pytest

from src.units.accounts import alpaca_amend as aa


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(aa, "_sleep", lambda s: None)


class NestedFakeAlpaca:
    def __init__(self, legs, *, position=None, entry_read_fails=False,
                 replace_after_reads=0):
        self.legs = copy.deepcopy(legs)
        self.position = position or {"state": "open", "qty": 6.0, "side": "short",
                                     "current_price": 38.0}
        self.entry_read_fails = entry_read_fails
        self.replace_after_reads = replace_after_reads
        self._pending = []
        self._countdown = 0
        self.patches = []
        self.entry_reads = []
        self._n = 0

    def position_quote(self, symbol):
        return dict(self.position)

    def _resting(self):
        return [o for o in self.legs if o["status"] not in ("replaced", "canceled")]

    def _open_orders_for_symbol(self, symbol, since=None):
        if self._pending:
            self._countdown -= 1
            if self._countdown < 0:
                for fn in self._pending:
                    fn()
                self._pending = []
        return [{k: v for k, v in o.items() if k != "parent"} for o in self._resting()]

    def _request(self, method, path, body=None):
        if method == "GET" and path.startswith("/v2/orders/"):
            oid = path[len("/v2/orders/"):].split("?", 1)[0]
            self.entry_reads.append(oid)
            if self.entry_read_fails:
                return {"retCode": 500, "retMsg": "boom"}
            legs = [{k: v for k, v in o.items() if k != "parent"}
                    for o in self._resting() if o.get("parent") == oid]
            return {"retCode": 0, "result": {"id": oid, "status": "filled", "legs": legs}}
        if method == "GET":  # the open-parents (partial-fill) read
            return {"retCode": 0, "result": []}
        assert method == "PATCH"
        oid = path.rsplit("/", 1)[-1]
        self.patches.append((oid, body))
        self._n += 1
        new_id = f"{oid}-r{self._n}"

        def _apply(oid=oid, new_id=new_id, body=body):
            for o in self.legs:
                if o["id"] == oid:
                    o["status"] = "replaced"
                    new = {**o, "id": new_id, "status": "held" if o["type"] == "stop" else "new"}
                    new.update(body)
                    self.legs.append(new)
                    break
        if self.replace_after_reads:
            self._pending.append(_apply)
            self._countdown = self.replace_after_reads
        else:
            _apply()
        return {"retCode": 0, "result": {"id": new_id, "replaces": oid}}


def _bracket(entry, *, qty, stop, tp, side="buy"):
    return [
        {"id": f"tp-{entry}", "parent": entry, "type": "limit", "side": side,
         "qty": str(qty), "status": "new", "limit_price": str(tp)},
        {"id": f"sl-{entry}", "parent": entry, "type": "stop", "side": side,
         "qty": str(qty), "status": "held", "stop_price": str(stop)},
    ]


def _three_slv_shorts():
    """The 2026-11-19 shape: three short brackets of qty=2 on one symbol."""
    return (_bracket("e7758", qty=2, stop=41.93, tp=37.61)
            + _bracket("e7766", qty=2, stop=41.85, tp=37.64)
            + _bracket("e7770", qty=2, stop=41.90, tp=37.56))


def test_same_size_siblings_resolve_by_entry_order_id_and_only_that_stop_moves():
    c = NestedFakeAlpaca(_three_slv_shorts())
    r = aa.tighten(c, symbol="SLV", direction="short", qty=2, new_sl=41.50,
                   apply=True, entry_order_id="e7766")
    assert r["result"] == aa.X_APPLIED, r
    assert c.patches == [("sl-e7766", {"stop_price": "41.50"})]
    assert r["before"]["leg_scope"] == {"stop": "entry_order", "target": "entry_order"}
    assert r["oco_leg_ids"] == {"stop": "sl-e7766", "target": "tp-e7766"}
    assert r["oco_leg_ids_after"]["stop"] == "sl-e7766-r1"
    # the siblings' stops are untouched
    resting = {o["id"]: o["stop_price"] for o in c._resting() if o["type"] == "stop"}
    assert resting["sl-e7758"] == "41.93" and resting["sl-e7770"] == "41.9"


def test_without_an_entry_order_id_the_prior_rule_still_refuses_ambiguity():
    c = NestedFakeAlpaca(_three_slv_shorts())
    r = aa.tighten(c, symbol="SLV", direction="short", qty=2, new_sl=41.50, apply=True)
    assert r["result"] == aa.X_REFUSED
    # a stop tighten needs only the stop resolved; three same-size stops still refuse
    assert r["detail"].startswith("ambiguous_legs: 3 stop / 0 target leg(s) of qty=2.0")
    assert r["before"]["ambiguous_unneeded"] == {"target": 3}
    assert c.patches == [] and c.entry_reads == []


def test_a_failed_entry_read_falls_back_to_qty_and_still_refuses_rather_than_guesses():
    c = NestedFakeAlpaca(_three_slv_shorts(), entry_read_fails=True)
    r = aa.tighten(c, symbol="SLV", direction="short", qty=2, new_sl=41.50,
                   apply=True, entry_order_id="e7766")
    assert r["result"] == aa.X_REFUSED and "ambiguous_legs" in r["detail"]
    assert c.patches == []


def test_a_rearmed_oco_the_journal_never_saw_falls_back_to_a_unique_qty_match():
    # The entry's own legs are gone (a naked re-arm replaced them with an OCO
    # whose parent id the journal does not hold); the stop is unique by size.
    legs = [
        {"id": "oco-tp", "parent": None, "type": "limit", "side": "buy", "qty": "2",
         "status": "new", "limit_price": "37.6"},
        {"id": "oco-sl", "parent": "oco-tp", "type": "stop", "side": "buy", "qty": "2",
         "status": "held", "stop_price": "41.9"},
    ] + _bracket("e9999", qty=5, stop=41.22, tp=37.3)
    c = NestedFakeAlpaca(legs, position={"state": "open", "qty": 7.0, "side": "short",
                                         "current_price": 38.0})
    r = aa.tighten(c, symbol="SLV", direction="short", qty=2, new_sl=41.50,
                   apply=True, entry_order_id="e7766")
    assert r["result"] == aa.X_APPLIED, r
    assert r["before"]["leg_scope"]["stop"] == "qty"
    assert c.patches == [("oco-sl", {"stop_price": "41.50"})]


def test_an_own_leg_sized_unlike_the_journal_row_is_refused_not_patched():
    legs = _bracket("e7766", qty=3, stop=41.85, tp=37.64)
    c = NestedFakeAlpaca(legs)
    r = aa.tighten(c, symbol="SLV", direction="short", qty=2, new_sl=41.50,
                   apply=True, entry_order_id="e7766")
    assert r["result"] == aa.X_REFUSED
    assert r["detail"].startswith("own_stop_leg_qty_3.0_not_trade_qty_2.0")
    assert c.patches == []


def test_an_async_replace_under_entry_scope_is_applied_after_the_settle_wait():
    c = NestedFakeAlpaca(_three_slv_shorts(), replace_after_reads=2)
    r = aa.tighten(c, symbol="SLV", direction="short", qty=2, new_sl=41.50,
                   apply=True, entry_order_id="e7770")
    assert r["result"] == aa.X_APPLIED, r
    assert r["replace_settle_s"]["stop"] > 0
    assert c.patches == [("sl-e7770", {"stop_price": "41.50"})]


def test_looser_stop_is_still_refused_under_entry_scope():
    c = NestedFakeAlpaca(_three_slv_shorts())
    r = aa.tighten(c, symbol="SLV", direction="short", qty=2, new_sl=42.10,
                   apply=True, entry_order_id="e7758")
    assert r["result"] == aa.X_REFUSED and r["detail"].startswith("already_at_or_tighter")
    assert c.patches == []


def test_modify_open_order_threads_the_entry_order_id_to_tighten(monkeypatch):
    from src.units.accounts import execute
    from src.units.accounts.alpaca_client import AlpacaClient

    seen = {}

    def fake_tighten(client, **kw):
        seen.update(kw)
        return {"result": aa.X_APPLIED, "before": {"venue_sl": 41.85}, "venue_after": 41.5}

    monkeypatch.setattr(aa, "tighten", fake_tighten)
    client = AlpacaClient.__new__(AlpacaClient)
    out = execute.modify_open_order(
        client, {"account_id": "alpaca_portfolio", "exchange": "alpaca"},
        symbol="SLV", sl=41.5, side="short", qty=2.0, trade_id=7766,
        entry_order_id="e7766",
    )
    assert out["ok"] is True, out
    assert seen["entry_order_id"] == "e7766" and seen["qty"] == 2.0


def test_exec_trade_leg_scopes_by_the_rows_broker_order_id():
    class DB:
        def __init__(self):
            self.updates = []

        def update_trade(self, tid, fields):
            self.updates.append((tid, fields))

    c = NestedFakeAlpaca(_three_slv_shorts())
    db = DB()
    trade = {"id": 7758, "account_id": "alpaca_portfolio", "symbol": "SLV",
             "direction": "short", "position_size": 2.0, "stop_loss": 41.93,
             "broker_order_id": "e7758", "notes": None}
    r = aa.exec_trade_leg(db, trade, 41.6, source="test", client=c)
    assert r["result"] == aa.X_APPLIED, r
    assert c.patches == [("sl-e7758", {"stop_price": "41.60"})]
    assert db.updates and db.updates[0][1]["stop_loss"] == 41.6


def _three_slv_shorts_targets_unnested():
    """Stops nested under their entries; the three same-size targets are NOT
    attributable to an entry (the shape AM-OPS-8 feared from the flat read)."""
    legs = _three_slv_shorts()
    for o in legs:
        if o["type"] == "limit":
            o["parent"] = None
    return legs


def test_a_stop_tighten_is_not_blocked_by_sibling_targets_it_cannot_attribute():
    c = NestedFakeAlpaca(_three_slv_shorts_targets_unnested())
    r = aa.tighten(c, symbol="SLV", direction="short", qty=2, new_sl=41.50,
                   apply=True, entry_order_id="e7758")
    assert r["result"] == aa.X_APPLIED, r
    assert c.patches == [("sl-e7758", {"stop_price": "41.50"})]
    assert r["before"]["ambiguous_unneeded"] == {"target": 3}
    assert r["before"]["target_leg"] is None  # never guessed


def test_a_target_move_still_refuses_when_its_targets_are_ambiguous():
    c = NestedFakeAlpaca(_three_slv_shorts_targets_unnested())
    r = aa.tighten(c, symbol="SLV", direction="short", qty=2, new_tp=37.0,
                   apply=True, entry_order_id="e7758")
    assert r["result"] == aa.X_REFUSED and "ambiguous_legs" in r["detail"]
    assert c.patches == []
