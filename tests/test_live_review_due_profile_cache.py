"""RM-AM-DUE-COULDNOTLOOK: compute_due must not re-parse config/instruments.yaml per package_market_state call.

Measured on the VM after #25234: compute_due took 8-20 s of the route's 9-30 s; locally 41 instruments.yaml parses
were 13.7 s of a 13.8 s compute_due over 20 packages.
"""
from __future__ import annotations

from datetime import UTC, datetime

from src.runtime import live_review_due as lrd
from src.runtime.market_hours import asset_class_for_symbol

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


def _reset():
    lrd._PROFILE_LOADED_AT = None
    lrd._PROFILE_EXCHANGE.clear()


def test_profiles_are_parsed_once_across_many_calls(monkeypatch):
    import src.core.profile_loader as pl
    calls = []
    real = pl.load_instrument_profiles

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(pl, "load_instrument_profiles", counting)
    _reset()
    for _ in range(25):
        for sym in ("MGC", "QQQ", "ETHUSDT", "NOT_A_SYMBOL"):
            lrd.package_market_state(sym, NOW)
    assert len(calls) == 1


def test_asset_class_matches_the_market_hours_helper():
    _reset()
    for sym in ("MGC", "MHG", "QQQ", "TLT", "GLD", "ETHUSDT", "XRPUSDT", "NOT_A_SYMBOL", "", None):
        _, cls, _ = lrd.package_market_state(sym, NOW)
        assert cls == asset_class_for_symbol(str(sym or "")), sym


def test_a_failed_profile_read_is_not_cached(monkeypatch):
    import src.core.profile_loader as pl
    real = pl.load_instrument_profiles
    _reset()

    def boom(*a, **k):
        raise OSError("instruments.yaml unreadable")

    monkeypatch.setattr(pl, "load_instrument_profiles", boom)
    is_open, cls, why = lrd.package_market_state("QQQ", NOW)
    assert is_open is True and cls == "unknown" and "market_hours_unreadable" in why
    monkeypatch.setattr(pl, "load_instrument_profiles", real)
    assert lrd.package_market_state("QQQ", NOW)[1] == asset_class_for_symbol("QQQ")
