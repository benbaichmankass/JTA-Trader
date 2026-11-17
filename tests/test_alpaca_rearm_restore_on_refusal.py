"""PI-20261027-KYYBSZXS-0001: a REFUSED re-arm OCO must not leave the position with less protection.

`AlpacaClient.place_protective` is cancel-before-place. MEASURED 2026-11-16 14:32:55-14:35:03Z on alpaca_paper:
seven refusals, "insufficient qty available for order (requested: 9375, available: 0)". "Place first" cannot work on
Alpaca (the resting legs reserve the shares, hence available 0), so after a refusal the legs it cancelled are put
back, at their OLD prices, always GTC, and read as restored or failed in the returned envelope.

Fixtures reuse the captured alpaca_paper/SPY shape of tests/test_alpaca_rearm_scoped_cancel.py.
"""
from __future__ import annotations

from src.units.accounts.alpaca_client import AlpacaClient

from tests.test_alpaca_rearm_scoped_cancel import (
    _LIVE_SPY, _OCO8, _OCO8_STOP, _OCO11, _Venue, _rearm,
)

_REFUSED = {"retCode": 403,
            "retMsg": "insufficient qty available for order (requested: 8, available: 0)"}
_OK = {"retCode": 0, "result": {"id": "restored-1"}}


def _posts(v):
    return [b for m, p, b in v.calls if m == "POST"]


def test_refused_oco_restores_the_cancelled_own_oco_at_its_old_prices():
    v = _Venue(_LIVE_SPY, post_results=[_REFUSED, _OK])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 403                           # the re-arm still reads as refused
    assert r["restored"]["ok"] == 1 and r["restored"]["attempted"] == 1 and not r["restored"]["failed"]
    assert "restored 1/1" in r["retMsg"] and "insufficient qty" in r["retMsg"]
    new_oco, restore = _posts(v)
    assert new_oco["stop_loss"] == {"stop_price": "760.00"}              # the NEW levels were tried first
    assert restore["order_class"] == "oco" and restore["qty"] == "8" and restore["side"] == "sell"
    assert restore["time_in_force"] == "gtc"
    assert restore["take_profit"] == {"limit_price": "840.65"}           # the OLD target
    assert restore["stop_loss"] == {"stop_price": "763.69"}              # the OLD stop
    assert v.deletes() == sorted([_OCO8["id"], _OCO8_STOP["id"]])        # the 11-share sibling untouched


def test_successful_oco_places_nothing_to_restore():
    v = _Venue(_LIVE_SPY, post_results=[{"retCode": 0, "result": {"id": "oco-new"}}])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 0 and r["result"]["orderId"] == "oco-new"
    assert "restored" not in r
    assert len(_posts(v)) == 1


def test_refusal_with_nothing_cancelled_is_returned_unchanged():
    """No own leg rests (a genuinely naked position): there is nothing to put back."""
    v = _Venue([], post_results=[_REFUSED])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r == _REFUSED
    assert len(_posts(v)) == 1


def test_could_not_look_cancels_nothing_so_restores_nothing():
    v = _Venue(_LIVE_SPY, post_results=[_REFUSED])
    r = _rearm(v, 8, sibling_qtys=None)                  # sibling sizes unreadable: nothing cancelled
    assert v.deletes() == [] and r == _REFUSED


def test_own_stop_only_is_restored_as_a_plain_gtc_stop():
    own_stop = {**_OCO8_STOP, "order_class": "simple"}
    v = _Venue([own_stop], post_results=[_REFUSED, _OK])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["restored"]["ok"] == 1
    _, restore = _posts(v)
    assert restore == {"symbol": "SPY", "qty": "8", "side": "sell", "type": "stop",
                       "time_in_force": "gtc", "stop_price": "763.69"}


def test_own_target_only_is_restored_as_a_plain_gtc_limit():
    own_tp = {**_OCO8, "order_class": "simple", "legs": None}
    v = _Venue([own_tp], post_results=[_REFUSED, _OK])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["restored"]["ok"] == 1
    _, restore = _posts(v)
    assert restore == {"symbol": "SPY", "qty": "8", "side": "sell", "type": "limit",
                       "time_in_force": "gtc", "limit_price": "840.65"}


def test_a_refused_restore_is_reported_never_raised_and_the_retcode_still_reads_refused():
    v = _Venue(_LIVE_SPY, post_results=[_REFUSED, {"retCode": 403, "retMsg": "still no shares"}])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 403
    assert r["restored"]["ok"] == 0 and r["restored"]["failed"]
    assert "FAILED" in r["retMsg"] and "still no shares" in r["retMsg"]


def test_a_raising_restore_post_is_contained():
    class _Raises(_Venue):
        def _request(self, method, path, json_body=None):  # type: ignore[override]
            if method == "POST" and len([c for c in self.calls if c[0] == "POST"]) >= 1:
                self.calls.append((method, path, json_body))
                raise RuntimeError("socket closed")
            return super()._request(method, path, json_body)
    v = _Raises(_LIVE_SPY, post_results=[_REFUSED])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 403 and r["restored"]["failed"] and "socket closed" in r["retMsg"]


def test_released_sibling_target_is_restored_when_the_retry_is_also_refused():
    sibling_tp = {"id": "22222222-aaaa-4bbb-8ccc-000000000002", "symbol": "SPY",
                  "order_class": "simple", "type": "limit", "side": "sell",
                  "qty": "11", "limit_price": "830.43", "status": "new", "legs": None}
    v = _Venue([sibling_tp], post_results=[_REFUSED, _REFUSED, _OK])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 403
    assert v.deletes() == [sibling_tp["id"]]
    posts = _posts(v)
    assert len(posts) == 3                                # OCO, retry OCO, restore of the sibling target
    assert posts[2] == {"symbol": "SPY", "qty": "11", "side": "sell", "type": "limit",
                        "time_in_force": "gtc", "limit_price": "830.43"}
    assert r["restored"]["ok"] == 1


def test_a_successful_retry_does_not_restore_the_released_sibling_target():
    """Unchanged documented behaviour: arming the STOP outranks a sibling's target geometry."""
    sibling_tp = {"id": "22222222-aaaa-4bbb-8ccc-000000000002", "symbol": "SPY",
                  "order_class": "simple", "type": "limit", "side": "sell",
                  "qty": "11", "limit_price": "830.43", "status": "new", "legs": None}
    v = _Venue([sibling_tp], post_results=[_REFUSED, {"retCode": 0, "result": {"id": "oco-new"}}])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 0 and "restored" not in r
    assert len(_posts(v)) == 2


def test_cancel_row_protection_is_an_intended_cancel_and_restores_nothing():
    v = _Venue(_LIVE_SPY)
    r = AlpacaClient.cancel_row_protection(v, "SPY", qty=8, direction="long", sibling_qtys=[11])
    assert r["retCode"] == 0
    assert _posts(v) == []
