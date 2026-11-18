"""The account-wide open-order response prunes ib_insync's grow-only Trade cache.

BL-20260826-DIAG-IB-OPEN-ORDERS-SERVES-A-STALE-MONOTONIC-ORDER-VIEW, re-measured 2026-11-18:
the cache kept serving orders another client had cancelled (70 resting MGC stop lots vs one real pair).
"""
from types import SimpleNamespace as NS

from src.units.accounts.ib_client import IBClient


def _trade(perm, client=1, oid=10):
    return NS(order=NS(permId=perm, clientId=client, orderId=oid))


def test_cancelled_elsewhere_is_dropped_live_and_unacked_are_kept():
    live = _trade(111, oid=1)
    dead = _trade(222, oid=2)          # cancelled by another client: absent from the response
    unacked = _trade(0, oid=3)         # just placed, no permId yet: must survive (else a fresh bracket reads naked)
    by_key = _trade(333, client=7, oid=4)  # response carries no permId for it but matches on (clientId, orderId)
    resp = [NS(permId=111, clientId=1, orderId=1), NS(permId=0, clientId=7, orderId=4)]
    kept = IBClient._prune_to_response([live, dead, unacked, by_key], resp)
    assert kept == [live, unacked, by_key]


def test_empty_response_means_nothing_open_but_unacked_survive():
    assert IBClient._prune_to_response([_trade(5), _trade(0)], []) == [_trade(0)] or \
        [t.order.permId for t in IBClient._prune_to_response([_trade(5), _trade(0)], [])] == [0]


def test_unreadable_response_changes_nothing():
    trades = [_trade(5), _trade(6)]
    assert IBClient._prune_to_response(trades, None) == trades
    assert IBClient._prune_to_response(trades, "garbage") == trades
