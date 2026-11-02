"""LTR-PACKET-FIXES (2026-11-01): ``_venue_tp`` reads THIS leg's tracked take-profit, never a sibling's.

On a Bybit ``position_model: slices`` account two packages hold one Partial TP leg each on one symbol. When this
leg's tracked ``tp_order_id`` is no longer resting, the old fallback read the position-level / sole TP leg -- a
sibling package's -- as this leg's, so the both-brackets check passed for a leg whose own TP was gone.
"""
from __future__ import annotations

from scripts.ops import live_review_apply as lra


class _Client:
    def __init__(self, orders, pos_tp="0"):
        self._orders, self._pos_tp = orders, pos_tp

    def get_positions(self, **_):
        return {"result": {"list": [{"side": "Sell", "size": "3", "takeProfit": self._pos_tp}]}}

    def get_open_orders(self, **_):
        return {"result": {"list": self._orders}}


SIB = {"orderId": "sib-tp", "stopOrderType": "PartialTakeProfit", "triggerPrice": "1.2185"}
MINE = {"orderId": "mine-tp", "stopOrderType": "PartialTakeProfit", "triggerPrice": "1.2421"}


def _tp(client, tp_order_id):
    return lra._venue_tp(client, {"exchange": "bybit"}, "XRPUSDT", "short", tp_order_id)


def test_own_tracked_tp_is_read():
    out = _tp(_Client([SIB, MINE]), "mine-tp")
    assert out == {"read_state": "resolved", "venue_tp": 1.2421}


def test_missing_own_tp_is_none_never_the_siblings_sole_leg():
    out = _tp(_Client([SIB]), "mine-tp")
    assert out["read_state"] == "resolved" and out["venue_tp"] is None


def test_missing_own_tp_is_none_never_the_position_level_tp():
    out = _tp(_Client([SIB], pos_tp="1.3"), "mine-tp")
    assert out["venue_tp"] is None


def test_untracked_leg_keeps_the_position_and_sole_leg_fallbacks():
    assert _tp(_Client([SIB], pos_tp="1.3"), None)["venue_tp"] == 1.3
    assert _tp(_Client([SIB]), None)["venue_tp"] == 1.2185
