"""The account-wide open-order response prunes ib_insync's grow-only Trade cache.

BL-20260826-DIAG-IB-OPEN-ORDERS-SERVES-A-STALE-MONOTONIC-ORDER-VIEW. The first
version (#26996) was tested with hand-rolled Order-shaped stubs and pruned every
live leg in production, because the real response is ``List[Trade]``. These
tests drive the REAL ib_insync wrapper (``openOrder`` / ``openOrderEnd``) so the
response has exactly the shape the trader receives.
"""
import asyncio

import pytest

ib_insync = pytest.importorskip("ib_insync")
from ib_insync import IB, Contract, Order, OrderState  # noqa: E402

from src.units.accounts.ib_client import IBClient  # noqa: E402


def _order(oid, perm, client=1, action="BUY", otype="STP", qty=5):
    return Order(orderId=oid, clientId=client, permId=perm, action=action,
                 orderType=otype, totalQuantity=qty)


def _feed(ib, order, status="Submitted"):
    c = Contract(conId=1000 + order.orderId, symbol="MGC", secType="FUT", exchange="COMEX")
    ib.wrapper.openOrder(order.orderId, c, order, OrderState(status=status))


def _response(ib, live_orders):
    """Run a real reqAllOpenOrders round trip: startReq -> openOrder* -> openOrderEnd."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        fut = ib.wrapper.startReq("openOrders")
        for o in live_orders:
            _feed(ib, o)
        ib.wrapper.openOrderEnd()
        return loop.run_until_complete(fut)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _book():
    """The ib_paper shape of 2026-11-18: three positions, one STP+LMT pair each."""
    return [_order(10 + i, 9000 + i, otype=("STP" if i % 2 == 0 else "LMT")) for i in range(6)]


def test_real_response_is_a_list_of_trades():
    ib = IB()
    resp = _response(ib, _book())
    assert resp and all(type(r).__name__ == "Trade" for r in resp)
    assert not hasattr(resp[0], "permId")  # the #26996 assumption, pinned false


def test_full_resting_book_survives_the_prune_untouched():
    ib = IB()
    book = _book()
    for o in book:
        _feed(ib, o)
    cached = list(ib.openTrades())
    assert len(cached) == 6
    resp = _response(ib, book)
    assert IBClient._prune_to_response(cached, resp) == cached


def test_order_cancelled_by_another_client_is_dropped():
    ib = IB()
    book = _book()
    for o in book:
        _feed(ib, o)
    stale = _order(99, 9999, client=7)  # cancelled elsewhere: still Submitted in the cache
    _feed(ib, stale)
    cached = list(ib.openTrades())
    assert len(cached) == 7
    resp = _response(ib, book)  # the venue no longer reports it
    kept = IBClient._prune_to_response(cached, resp)
    assert len(kept) == 6
    assert all(t.order.permId != 9999 for t in kept)


def test_unacknowledged_trade_is_kept():
    ib = IB()
    book = _book()
    for o in book:
        _feed(ib, o)
    fresh = _order(50, 0)  # just placed, no permId yet
    _feed(ib, fresh, status="PendingSubmit")
    cached = list(ib.openTrades())
    resp = _response(ib, book)
    assert len(IBClient._prune_to_response(cached, resp)) == 7


def test_empty_or_unreadable_response_changes_nothing():
    ib = IB()
    for o in _book():
        _feed(ib, o)
    cached = list(ib.openTrades())
    assert IBClient._prune_to_response(cached, []) == cached
    assert IBClient._prune_to_response(cached, None) == cached
    assert IBClient._prune_to_response(cached, "garbage") == cached
    assert IBClient._prune_to_response(cached, [object(), object()]) == cached
