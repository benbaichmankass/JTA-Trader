"""A trade's first IB re-arm must also cancel its OWN entry-bracket children.

PAPER-MECHANICS-20261104 item 1. MEASURED ib_paper TLT 2026-11-04
(`/api/diag/ib_open_orders?account_id=ib_paper` 18:24Z + trader journal
14:49Z): trade 6879 entered via bracket parent 1231 (MKT BUY 7443) with
children 1232 LMT 87.57 and 1233 STP 79.41, both `parentId=1231`, grouped by
IBKR under the bare-numeric OCA `1712634399`. Twenty seconds later the
structure exit moved the TP to 83.59; `modify_open_order` re-armed through
`place_protective(oca_key="6879")`, whose pre-cancel is scoped BY NAME to
`oca-protect-t6879` -- empty -- and the stray sweep (armed on ib_paper) saw the
children with an empty local `ocaGroup` and classified them `ungrouped`
(report-only). Result: two disjoint stop groups, 12,743 shares of resting
sell stop against a 7,443-share long -- one fill flattens it and the other
sells into a naked short.

The fix passes the trade's entry order id (`trades.broker_order_id`) so the
keyed pre-cancel also takes legs whose `parentId` is that entry.
"""
from __future__ import annotations

import pathlib

from tests.test_ib_protection_quantity import (
    _IB,
    _place_client,
    _Position,
    _Trade,
)

_REPO = pathlib.Path(__file__).resolve().parents[1]


def _child(order_type, qty, parent, order_id, oca=""):
    t = _Trade("TLT", order_type, qty, oca, order_id=order_id)
    t.order.parentId = parent
    return t


def _rearm(c, **extra):
    return c.place_protective({
        "symbol": "TLT", "direction": "long", "qty": 7443,
        "sl": 79.41, "tp": 83.59, "oca_key": "6879", **extra,
    })


def test_first_rearm_cancels_the_entry_bracket_children(monkeypatch):
    tp = _child("LMT", 7443, 1231, 1232)
    sl = _child("STP", 7443, 1231, 1233)
    ib = _IB([_Position("TLT", 7443)], [tp, sl])
    c, placed = _place_client(monkeypatch, ib)
    resp = _rearm(c, entry_order_id="1231")
    assert resp["retCode"] == 0
    assert tp.order in ib.cancelled and sl.order in ib.cancelled, (
        "the entry bracket survived the re-arm -> two disjoint stop groups")
    assert {o.ocaGroup for o in placed} == {"oca-protect-t6879"}


def test_children_of_ANOTHER_entry_are_never_touched(monkeypatch):
    """Scope stays this trade: a sibling's bracket (other parentId) survives."""
    sib_tp = _child("LMT", 100, 900, 901)
    sib_sl = _child("STP", 100, 900, 902)
    ib = _IB([_Position("TLT", 7543)], [sib_tp, sib_sl])
    c, _ = _place_client(monkeypatch, ib)
    _rearm(c, entry_order_id="1231")
    assert sib_tp.order not in ib.cancelled and sib_sl.order not in ib.cancelled


def test_the_resting_entry_parent_itself_is_not_cancelled(monkeypatch):
    """Only protective (STP/LMT-side) children; never a non-protective order."""
    parent = _Trade("TLT", "MKT", 7443, "", order_id=1231)
    parent.order.parentId = 0
    other = _child("MKT", 5, 1231, 1240)  # a non-protective child, hypothetical
    ib = _IB([_Position("TLT", 7443)], [parent, other])
    c, _ = _place_client(monkeypatch, ib)
    _rearm(c, entry_order_id="1231")
    assert parent.order not in ib.cancelled and other.order not in ib.cancelled


def test_without_an_entry_id_behaviour_is_unchanged(monkeypatch):
    tp = _child("LMT", 7443, 1231, 1232)
    ib = _IB([_Position("TLT", 7443)], [tp])
    c, _ = _place_client(monkeypatch, ib)
    _rearm(c)
    assert tp.order not in ib.cancelled


def test_a_non_numeric_entry_id_is_ignored(monkeypatch):
    tp = _child("LMT", 7443, 1231, 1232)
    ib = _IB([_Position("TLT", 7443)], [tp])
    c, _ = _place_client(monkeypatch, ib)
    assert _rearm(c, entry_order_id="rejected-abc")["retCode"] == 0
    assert tp.order not in ib.cancelled


def test_modify_open_order_forwards_entry_order_id():
    import src.units.accounts.execute as ex
    from src.units.accounts.ib_client import IBClient

    seen = []
    cls = type("_F", (IBClient,), {
        "__init__": lambda self: None,
        "modify_protective": lambda self, o: seen.append(o) or {"retCode": 0},
    })
    ex.modify_open_order(
        cls(), {"account_id": "ib_paper", "exchange": "interactive_brokers"},
        symbol="TLT", side="long", qty=7443.0, sl=None, tp=83.59,
        cur_sl=79.4125, trade_id=6879, entry_order_id="1231")
    assert seen[0]["entry_order_id"] == "1231"
    assert seen[0]["oca_key"] == "6879"


def test_the_monitor_modify_call_site_passes_the_entry_id():
    src = (_REPO / "src/runtime/order_monitor.py").read_text()
    call = src[src.index("return modify_open_order("):]
    call = call[:call.index("\n        )")]
    assert 'entry_order_id=matched_trade.get("broker_order_id")' in call
