"""Size-up below a venue minimum (operator 2026-11-09, Tier 3; reverses
"never round up / refuse below min"). Rule lives in the ONE seam."""
from __future__ import annotations

import pytest

from src.core.instrument_profile import InstrumentProfile
from src.units.accounts import precision, qty_legalize
from src.units.accounts.qty_legalize import legalize_qty

_BYBIT = {"account_id": "bybit_1", "exchange": "bybit", "market_type": "linear"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    qty_legalize._reset_profile_cache()
    precision._MIN_NOTIONAL_CACHE.clear()
    monkeypatch.setattr(qty_legalize, "venue_min_notional",
                        lambda **kw: 5.0)
    yield
    qty_legalize._reset_profile_cache()


def _prof(step, mn, mx=None):
    return {"AVAXUSDT": InstrumentProfile(
        symbol="AVAXUSDT", exchange="bybit", category="linear",
        base_asset="AVAX", quote_currency="USDT", settlement_currency="USDT",
        tick_size=0.001, min_qty=mn, qty_step=step, max_qty=mx)}


def _lz(qty, price=8.8, **kw):
    prof = kw.pop("profiles", _prof(0.1, 0.1))
    return legalize_qty(qty, account_cfg=_BYBIT, symbol="AVAXUSDT",
                        profiles=prof, price=price, size_up=True, **kw)


def test_avax_notional_binding_bumps_to_0_6():
    r = _lz(0.5779)
    assert r.ok and r.qty == pytest.approx(0.6)
    assert r.resized_from == pytest.approx(0.5)
    assert r.resize_binding == "min_notional"
    assert r.qty * 8.8 >= 5.0


def test_min_qty_binding():
    r = _lz(0.03, price=8.8, profiles=_prof(0.1, 1.0))
    # notional 5/8.8 = 0.57 -> 0.6 < minOrderQty 1.0 -> min_qty binds
    assert r.ok and r.qty == pytest.approx(1.0)
    assert r.resize_binding == "min_qty"


def test_notional_binding_when_high_min_notional(monkeypatch):
    monkeypatch.setattr(qty_legalize, "venue_min_notional", lambda **kw: 100.0)
    r = _lz(1.0)
    assert r.ok and r.qty == pytest.approx(11.4)  # 100/8.8=11.36 -> 11.4
    assert r.resize_binding == "min_notional"


def test_max_below_bumped_min_refuses():
    r = _lz(0.5779, profiles=_prof(0.1, 0.1, mx=0.4))
    assert not r.ok and r.reason == "venue_max_below_min_qty"


def test_normal_qty_unchanged():
    r = _lz(10.07)
    assert r.ok and r.qty == pytest.approx(10.0)
    assert r.resized_from is None and r.resize_binding == ""


def test_default_off_still_refuses_below_min():
    r = legalize_qty(0.03, account_cfg=_BYBIT, symbol="AVAXUSDT",
                     profiles=_prof(0.1, 0.1), price=8.8)
    assert not r.ok and r.reason == "below_venue_min_qty"


def test_no_price_only_min_qty():
    r = legalize_qty(0.03, account_cfg=_BYBIT, symbol="AVAXUSDT",
                     profiles=_prof(0.1, 0.1), size_up=True)
    assert r.ok and r.qty == pytest.approx(0.1) and r.resize_binding == "min_qty"
