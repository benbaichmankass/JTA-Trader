"""Netted-venue gross-exposure exemption (operator 2026-11-12, decisions page
w15: "Yes: exempt net-reducing orders on netted venues"; row
ZERO-QTY-EXPOSURE-EXPLAIN, evidence PI-20261104-KKPOFDJQ-0004).

On a venue that nets one position per contract (IB), an order against a held
opposite position reduces |net| for its first |net_qty| units: those need no
headroom. Only the part that flips past flat opens new exposure and is
clamped. Non-netted venues keep the pre-decision behaviour.

Shape of the 2026-11-04 case: ib_paper at/over its 1.5x ceiling with an MGC
short held; every MGC long signal sized to 0 and the gate refused it.
"""
import sqlite3

import pytest

from src.core.coordinator import OrderPackage
from src.units.accounts.risk import RiskManager

EQUITY = 1_000_000.0          # synthetic, not a live balance
MGC_ENTRY = 4000.0            # x10 contract value -> 40k notional per contract
HELD_SHORT = 11               # contracts


def _rm(tmp_path, *, exchange, held_short=HELD_SHORT, filler_notional=1_520_000.0):
    """An account with an MGC short plus a non-MGC filler, so gross sits at or
    over 1.5 x equity (headroom 0 -> REFUSE verdict) unless the filler is small."""
    db = tmp_path / "j.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE trades (account_id TEXT, symbol TEXT, status TEXT,"
                  " direction TEXT, position_size REAL, entry_price REAL,"
                  " is_backtest INT)")
        if held_short:
            c.execute("INSERT INTO trades VALUES ('a','MGC','open','short',?,?,0)",
                      (held_short, MGC_ENTRY))
        if filler_notional:
            c.execute("INSERT INTO trades VALUES ('a','TLT','open','long',?,1.0,0)",
                      (filler_notional,))
    rm = RiskManager({"risk_pct": 0.05, "max_gross_exposure_pct": 1.5},
                     account_id="a", exchange=exchange)
    rm._risk_db_path = lambda: str(db)
    rm.current_equity = EQUITY
    return rm


def _pkg(direction="long", entry=MGC_ENTRY):
    sl = entry - 20 if direction == "long" else entry + 20
    tp = entry + 60 if direction == "long" else entry - 60
    return OrderPackage(strategy="mgc_trend_1h", symbol="MGC", direction=direction,
                        entry=entry, sl=sl, tp=tp, confidence=1.0)


def _size(rm, pkg):
    return rm.position_size(pkg, EQUITY, market_type="futures")


def test_mgc_long_against_held_short_is_not_refused_on_ib(tmp_path):
    rm = _rm(tmp_path, exchange="interactive_brokers")
    assert rm.exposure_headroom_usd() == 0.0      # at/over the ceiling
    ok, why = rm.evaluate(_pkg("long"))
    assert ok, why
    qty = _size(rm, _pkg("long"))
    # Unclamped risk size is far above 11; the reducing part is exactly the
    # held short, and with zero headroom nothing past flat is allowed.
    assert qty == HELD_SHORT


def test_flip_past_flat_is_clamped_to_headroom(tmp_path):
    # 440k (MGC) + 980k (TLT) = 1,420,000 vs cap 1,500,000 -> headroom 80,000
    # = 2 contracts at 40k each.
    rm = _rm(tmp_path, exchange="interactive_brokers", filler_notional=980_000.0)
    assert rm.exposure_headroom_usd() == pytest.approx(80_000.0)
    qty = _size(rm, _pkg("long"))
    assert qty == HELD_SHORT + 2                  # 11 reduce + 2 past flat


def test_adding_to_the_held_side_gets_no_exemption(tmp_path):
    rm = _rm(tmp_path, exchange="interactive_brokers")
    ok, why = rm.evaluate(_pkg("short"))
    assert not ok and why == "GROSS_EXPOSURE_CAP"
    assert _size(rm, _pkg("short")) == 0.0


def test_non_netted_venue_is_unchanged(tmp_path):
    rm = _rm(tmp_path, exchange="bybit")
    ok, why = rm.evaluate(_pkg("long"))
    assert not ok and why == "GROSS_EXPOSURE_CAP"
    assert _size(rm, _pkg("long")) == 0.0


def test_no_exchange_passed_is_unchanged(tmp_path):
    rm = _rm(tmp_path, exchange=None)
    assert not rm.evaluate(_pkg("long"))[0]
    assert _size(rm, _pkg("long")) == 0.0


def test_unreadable_net_gives_no_exemption(tmp_path):
    rm = _rm(tmp_path, exchange="interactive_brokers")
    rm._open_net_qty_for_symbol = lambda symbol: None
    assert not rm.evaluate(_pkg("long"))[0]
    assert _size(rm, _pkg("long")) == 0.0


def test_flat_symbol_on_netted_venue_is_unchanged(tmp_path):
    rm = _rm(tmp_path, exchange="interactive_brokers", held_short=0,
             filler_notional=1_600_000.0)
    assert not rm.evaluate(_pkg("long"))[0]
    assert _size(rm, _pkg("long")) == 0.0


def test_loader_passes_the_exchange():
    from src.units.accounts import load_accounts
    accts = load_accounts()
    ib = [a for a in accts if getattr(a, "exchange", None) == "interactive_brokers"]
    assert ib, "positive control: config has an IB account"
    assert all(a.risk_manager.exchange == "interactive_brokers" for a in ib)
