"""LIVE-TICK-NEAR-BUDGET (2026-11-20): the equity naked sweep reads the venue WITHOUT journal_sync.

MEASURED /api/diag/tick_cost, 76 ticks after the 04:41:12Z restart: main journal_sync.wait mean 6.51 s;
off-loop journal_sync.hold max 15.9 s = the equity naked sweep's max. Design (manager-approved, with the
hardening that EVERY venue-mutating call moves the generation):

1. the sweep's venue reads are prefetched unlocked;
2. the locked body is served from them only while the venue generation is unchanged;
3. any non-GET through the Alpaca clients' `_request`, and every entry-dispatch / pairs release, moves the
   generation, so a trail amend / re-arm / cancel / dispatch that lands mid-prefetch forces live reads
   under the lock (today's behaviour);
4. on the happy path, NO venue read runs while the lock is held.
"""
from __future__ import annotations

import sqlite3

import tests.test_alpaca_rearm_preflight as _pf
from src.runtime import journal_sync as js
from src.runtime import order_monitor as om
from src.runtime import venue_read_cache as vrc
from tests.test_alpaca_rearm_preflight import _use, _Venue

world = _pf.world  # the re-arm preflight suite's journal + venue fixture, reused as-is


class _SpyVenue(_Venue):
    """The preflight suite's venue, plus: every GET records whether journal_sync is held, and every
    non-GET moves the venue generation the way the real `AlpacaClient._request` now does."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.gets_locked = 0
        self.gets_unlocked = 0

    def _request(self, method, path, json_body=None):  # type: ignore[override]
        if method == "GET":
            if js.is_held_by_current_thread():
                self.gets_locked += 1
            else:
                self.gets_unlocked += 1
        else:
            js.bump_venue_generation()
        try:
            return super()._request(method, path, json_body)
        finally:
            if method != "GET":
                js.bump_venue_generation()

    def positions(self):
        if js.is_held_by_current_thread():
            self.gets_locked += 1
        else:
            self.gets_unlocked += 1
        return super().positions()


def _covered(db):
    """One open QQQ row (6024, 56 long) fully covered by a resting OCO at its own levels."""
    c = sqlite3.connect(db.path)
    c.execute("DELETE FROM trades WHERE id=5928")
    c.commit()
    c.close()
    v = _SpyVenue(qty=56.0, price=735.0)
    v.resting = [{
        "id": "oco-6024", "symbol": "QQQ", "order_class": "oco", "type": "limit", "side": "sell",
        "qty": "56", "limit_price": "787.86", "status": "new",
        "legs": [{"id": "stop-6024", "symbol": "QQQ", "order_class": "oco", "type": "stop",
                  "side": "sell", "qty": "56", "stop_price": "716.80", "status": "held", "legs": None}]}]
    return v


def _sweep_with_prefetch(db):
    cache = om._prefetch_equity_sweep_reads(db)
    with js.journal_sync("reconciliation:check_broker_naked_equity_positions"), vrc.active(cache):
        summary = om._check_broker_naked_equity_positions(db)
    return cache, summary


def test_happy_path_makes_no_venue_read_under_the_lock(world):
    db, _pages, mp = world
    v = _covered(db)
    _use(mp, v)
    cache, s = _sweep_with_prefetch(db)
    assert cache is not None and cache.hits >= 2, cache and cache.stats()
    assert v.gets_unlocked > 0
    assert v.gets_locked == 0, f"{v.gets_locked} venue read(s) ran while journal_sync was held"
    assert v.posts() == [] and s["errors"] == 0


def test_without_prefetch_the_same_sweep_reads_under_the_lock(world):
    """Negative control: proves the spy can see a locked read (today's behaviour)."""
    db, _pages, mp = world
    v = _covered(db)
    _use(mp, v)
    with js.journal_sync("reconciliation:check_broker_naked_equity_positions"):
        om._check_broker_naked_equity_positions(db)
    assert v.gets_locked > 0


def test_a_trail_amend_mid_prefetch_forces_the_locked_reread(world):
    """Manager hardening: a protection write between prefetch and lock must invalidate every cached read."""
    db, _pages, mp = world
    v = _covered(db)
    _use(mp, v)
    cache = om._prefetch_equity_sweep_reads(db)
    v._request("PATCH", "/v2/orders/stop-6024", {"stop_price": "720.00"})   # the trail amend lands
    with js.journal_sync("reconciliation:check_broker_naked_equity_positions"), vrc.active(cache):
        om._check_broker_naked_equity_positions(db)
    assert cache.hits == 0 and cache.invalidated >= 1
    assert v.gets_locked > 0


def test_an_entry_dispatch_mid_prefetch_forces_the_locked_reread(world):
    db, _pages, mp = world
    v = _covered(db)
    _use(mp, v)
    cache = om._prefetch_equity_sweep_reads(db)
    with js.journal_sync("entry_dispatch"):
        pass
    with js.journal_sync("reconciliation:check_broker_naked_equity_positions"), vrc.active(cache):
        om._check_broker_naked_equity_positions(db)
    assert cache.hits == 0 and v.gets_locked > 0


# ---------------------------------------------------------------------------
# the generation itself
# ---------------------------------------------------------------------------

def test_real_alpaca_request_moves_the_generation_only_on_writes(monkeypatch):
    from src.units.accounts.alpaca_client import AlpacaClient

    class _Resp:
        status_code, content = 200, b"{}"

        def json(self):
            return {}
    monkeypatch.setattr("src.units.accounts.alpaca_client.requests.request", lambda *a, **k: _Resp())
    cli = AlpacaClient(api_key="k", api_secret="s")
    g = js.venue_generation()
    cli._request("GET", "/v2/positions")
    assert js.venue_generation() == g
    for m in ("POST", "PATCH", "DELETE"):
        before = js.venue_generation()
        cli._request(m, "/v2/orders")
        assert js.venue_generation() == before + 2      # before AND after the call


def test_options_client_request_moves_the_generation_on_writes(monkeypatch):
    from src.units.accounts import alpaca_options_exec as ox

    class _Resp:
        status_code, content = 200, b"{}"

        def json(self):
            return {}
    monkeypatch.setattr(ox.requests, "request", lambda *a, **k: _Resp())
    cls = next(c for c in vars(ox).values() if isinstance(c, type) and hasattr(c, "_request_http"))
    inst = cls.__new__(cls)
    inst.api_key, inst.api_secret, inst.base_url, inst.timeout = "k", "s", "https://x", 5
    g = js.venue_generation()
    inst._request("GET", "/v2/orders")
    assert js.venue_generation() == g
    inst._request("POST", "/v2/orders", {})
    assert js.venue_generation() == g + 2


def test_only_dispatch_holders_move_the_generation():
    g = js.venue_generation()
    with js.journal_sync("reconciliation:reconcile_open_trades"):
        pass
    assert js.venue_generation() == g
    for h in js.DISPATCH_HOLDERS:
        before = js.venue_generation()
        with js.journal_sync(h):
            pass
        assert js.venue_generation() == before + 1


def test_cached_client_serves_while_valid_and_goes_live_after_a_bump():
    calls = []

    class _C:
        def protection_state(self, sym, since=None):
            calls.append(sym)
            return {"n": len(calls)}

        def place_protective(self, order):
            return "placed"

    cache = vrc.Cache()
    rec = cache.recorder("a", _C())
    assert rec.protection_state("QQQ", since="t") == {"n": 1}
    cc = vrc.CachedClient(cache, "a", _C())
    assert cc.protection_state("QQQ", since="t") == {"n": 1} and len(calls) == 1
    assert cc.place_protective({}) == "placed"           # writes pass straight through
    js.bump_venue_generation()
    assert cc.protection_state("QQQ", since="t") == {"n": 2} and cache.invalidated == 1
    assert cc.protection_state("SPY") == {"n": 3} and cache.misses == 1


def test_wrap_is_the_identity_without_an_active_cache():
    obj = object()
    assert vrc.wrap("a", obj) is obj
    assert vrc.wrap("a", None) is None
