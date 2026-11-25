"""ALPACA-PAPER-BRACKETS-GONE-1116 — an Alpaca stop amend whose nested open-orders listing is STALE.

MEASURED 2026-11-25, alpaca_paper QQQ short 519, trade 8454: the PATCH of stop leg 9ceb80e9 (673.03 -> 660.44)
was accepted and Alpaca's order history reads it ``replaced`` by 44e7d717 (held at 660.44) from 15:00:24Z. The
nested ``/v2/orders?status=open`` listing kept returning 9ceb80e9 ``held`` at 673.03 for 30 s+, so the read-back
said ``apply_failed: PATCH accepted, not replaced`` and the next tick's re-PATCH got 422 "order already replaced".

The fake below keeps the LISTING stale for a configurable number of reads while ``GET /v2/orders/{id}`` returns
the authoritative per-order state, exactly the venue shape above. Nothing here touches a network.
"""
from __future__ import annotations

import pytest

from src.units.accounts import alpaca_amend as aa


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(aa, "_sleep", lambda s: None)


class StaleListingAlpaca:
    """A short 519 QQQ with an OCO (target limit + held stop). A PATCH replaces the stop at once in the ORDER
    store, but the listing shows the old leg for ``stale_reads`` more listing reads."""

    def __init__(self, *, stale_reads=10**6, new_status="held", by_id_fails=False, patch_effective=True):
        self.orders = {
            "tp-1": {"id": "tp-1", "type": "limit", "side": "buy", "qty": "519", "status": "new",
                     "limit_price": "583.06"},
            "sl-1": {"id": "sl-1", "type": "stop", "side": "buy", "qty": "519", "status": "held",
                     "stop_price": "673.03"},
        }
        self.listed = ["tp-1", "sl-1"]
        self.snapshot = {k: dict(v) for k, v in self.orders.items()}   # what the stale listing shows
        self.stale_reads = stale_reads
        self.new_status = new_status
        self.by_id_fails = by_id_fails
        self.patch_effective = patch_effective
        self.patches = []
        self.by_id_reads = []

    def position_quote(self, symbol):
        return {"state": "open", "qty": 519.0, "side": "short", "current_price": 618.08}

    def _open_orders_for_symbol(self, symbol, since=None):
        if self.stale_reads > 0:
            self.stale_reads -= 1
            return [dict(self.snapshot[i]) for i in ("tp-1", "sl-1")]
        return [dict(o) for o in self.orders.values() if o["status"] not in ("replaced", "canceled")]

    def _request(self, method, path, body=None):
        if method == "GET" and path.startswith("/v2/orders?"):
            return {"retCode": 0, "result": []}          # no partially_filled parents
        oid = path.split("?")[0].rsplit("/", 1)[-1]
        if method == "GET":
            self.by_id_reads.append(oid)
            if self.by_id_fails or oid not in self.orders:
                return {"retCode": 404, "retMsg": "not found"}
            return {"retCode": 0, "result": dict(self.orders[oid])}
        assert method == "PATCH"
        self.patches.append((oid, body))
        cur = self.orders.get(oid)
        if cur and cur["status"] == "replaced":
            return {"retCode": 422, "retMsg": "order already replaced"}
        new_id = f"{oid}-r{len(self.patches)}"
        if self.patch_effective:
            cur["status"] = "replaced"
            cur["replaced_by"] = new_id
            self.orders[new_id] = {**cur, "id": new_id, "status": self.new_status, "replaces": oid,
                                   "replaced_by": None, **body}
        return {"retCode": 0, "result": {"id": new_id, "replaces": oid}}


def _tighten(c):
    return aa.tighten(c, symbol="QQQ", direction="short", qty=519, new_sl=660.44392857, apply=True)


def test_qqq_8454_shape_stale_listing_is_applied_by_the_order_by_id_read():
    c = StaleListingAlpaca()
    r = _tighten(c)
    assert r["result"] == aa.X_APPLIED, r
    assert r["venue_after"] == 660.44 and r["oco_leg_ids_after"]["stop"] == "sl-1-r1"
    assert r["stale_listing"]["stop"] == {"listed": "sl-1", "resting": "sl-1-r1"}
    assert r["after"]["readback_source"] == "order_by_id"
    assert c.by_id_reads == ["sl-1-r1"] and len(c.patches) == 1


def test_the_next_tick_re_patch_of_the_stale_leg_follows_replaced_by_and_is_applied():
    """15:00:56Z: the listing still showed sl-1, the re-PATCH got 422 'order already replaced'."""
    c = StaleListingAlpaca()
    _tighten(c)
    r = _tighten(c)                                   # listing still stale: plans a PATCH on sl-1 again
    assert c.patches[-1][0] == "sl-1"
    assert r["result"] == aa.X_APPLIED, r
    assert r["venue_after"] == 660.44 and r["oco_leg_ids_after"]["stop"] == "sl-1-r1"
    assert r["stale_listing"]["stop"]["resting"] == "sl-1-r1"


def test_a_replace_that_truly_did_not_take_is_still_apply_failed():
    """The by-id read must not paper over a real failure: the returned id does not exist at the venue."""
    c = StaleListingAlpaca(patch_effective=False)
    r = _tighten(c)
    assert r["result"] == aa.X_APPLY_FAILED and "PATCH accepted, not replaced" in r["detail"]


def test_a_failed_by_id_read_stays_apply_failed_never_assumed_applied():
    c = StaleListingAlpaca(by_id_fails=True)
    r = _tighten(c)
    assert r["result"] == aa.X_APPLY_FAILED


def test_a_successor_that_is_not_resting_is_not_applied():
    """A successor that already filled/cancelled is not protection resting at the level."""
    c = StaleListingAlpaca(new_status="canceled")
    r = _tighten(c)
    assert r["result"] == aa.X_APPLY_FAILED


def test_a_successor_at_another_level_after_422_is_apply_failed():
    c = StaleListingAlpaca()
    _tighten(c)                                       # sl-1 -> sl-1-r1 @ 660.44
    r = aa.tighten(c, symbol="QQQ", direction="short", qty=519, new_sl=655.0, apply=True)
    assert r["result"] == aa.X_APPLY_FAILED and "already replaced" in r["detail"]


def test_a_listing_that_catches_up_never_needs_the_by_id_read():
    c = StaleListingAlpaca(stale_reads=1)             # only the `before` read is stale
    r = _tighten(c)
    assert r["result"] == aa.X_APPLIED and "stale_listing" not in r and c.by_id_reads == []
