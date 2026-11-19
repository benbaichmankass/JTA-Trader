"""placeOrder raising AFTER the pre-cancel must not leave the position unprotected (BRACKETS-ALWAYS item 2).

The keyed pre-cancel removes the trade's previous legs first. A placeOrder that raised used to return retCode 1 at once,
with nothing resting until the next naked sweep (~5 min). Each leg that did not go out is now retried ONCE with a fresh
orderId in the same OCA group. Built on REAL ib_insync 0.9.86 LimitOrder / StopOrder objects.
"""
from __future__ import annotations

import pytest

ib_insync = pytest.importorskip("ib_insync")

from tests.test_ib_protection_quantity import _IB, _Position  # noqa: E402
from tests.test_ib_rearm_keeps_resting_tp import _client_real, _leg  # noqa: E402


def _raising(ib, placed, fail_calls):
    """placeOrder that raises on the given 1-based call numbers, else records the order."""
    n = {"i": 0}

    def _place(_c, o):
        n["i"] += 1
        if n["i"] in fail_calls:
            raise ConnectionError(f"gateway dropped (call {n['i']})")
        placed.append(o)
        return o
    ib.placeOrder = _place
    return n


def _arm(c):
    return c.place_protective({"symbol": "TLT", "direction": "long", "qty": 100, "sl": 80.0, "tp": 90.0,
                               "oca_key": "6879", "account_id": "ib_paper"})


def test_a_stop_that_raises_once_is_restored_by_the_retry(monkeypatch):
    old = _leg("STP", 100, 79.0, oca="oca-protect-t6879", order_id=12)
    ib = _IB([_Position("TLT", 100)], [old])
    c, placed = _client_real(monkeypatch, ib)
    calls = _raising(ib, placed, fail_calls={1})        # the STOP (placed first) raises once
    resp = _arm(c)
    assert old.order in ib.cancelled                    # the pre-cancel ran
    assert resp["retCode"] == 0, resp
    kinds = sorted(type(o).__name__ for o in placed)
    assert kinds == ["LimitOrder", "StopOrder"], "a leg was not restored"
    assert {o.ocaGroup for o in placed} == {"oca-protect-t6879"}
    assert calls["i"] == 3                              # stop raise, target ok, stop retry ok


def test_only_the_missing_leg_is_retried_never_a_duplicate_of_a_placed_one(monkeypatch):
    ib = _IB([_Position("TLT", 100)], [])
    c, placed = _client_real(monkeypatch, ib)
    _raising(ib, placed, fail_calls={2})                # the stop goes out; the TARGET raises once
    resp = _arm(c)
    assert resp["retCode"] == 0
    assert sorted(type(o).__name__ for o in placed) == ["LimitOrder", "StopOrder"]   # one of each, no twin stop


def test_the_retry_takes_a_fresh_order_id(monkeypatch):
    ib = _IB([_Position("TLT", 100)], [])
    c, placed = _client_real(monkeypatch, ib)
    seen = []
    n = {"i": 0}

    def _place(_c, o):
        n["i"] += 1
        seen.append(o.orderId)
        if n["i"] == 1:
            raise ConnectionError("drop")
        placed.append(o)
    ib.placeOrder = _place
    _arm(c)
    assert seen[0] != seen[-1]                          # the retried stop is re-sent under a new id


def test_a_persistent_failure_is_reported_loudly_with_the_missing_legs(monkeypatch, caplog):
    old = _leg("STP", 100, 79.0, oca="oca-protect-t6879", order_id=12)
    ib = _IB([_Position("TLT", 100)], [old])
    c, placed = _client_real(monkeypatch, ib)
    _raising(ib, placed, fail_calls={1, 2, 3, 4})
    with caplog.at_level("CRITICAL"):
        resp = _arm(c)
    assert resp["retCode"] == 1
    assert resp["result"]["protection_restored"] is False
    assert "StopOrder" in resp["result"]["legs_missing"]
    assert any("UNPROTECTED" in r.getMessage() for r in caplog.records if r.levelname == "CRITICAL")


def test_the_happy_path_is_unchanged(monkeypatch):
    ib = _IB([_Position("TLT", 100)], [])
    c, placed = _client_real(monkeypatch, ib)
    calls = _raising(ib, placed, fail_calls=set())
    resp = _arm(c)
    assert resp["retCode"] == 0 and calls["i"] == 2
    assert [type(o).__name__ for o in placed] == ["StopOrder", "LimitOrder"]
