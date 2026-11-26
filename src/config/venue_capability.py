"""What a venue can trade, by asset class: the one answer behind "an account configures strategies, never symbols".

ML-UNIVERSE-RULE (operator 2026-11-04, canonical § "An account configures strategies, never symbols"; operator 2026-11-26
chat, verbatim: "Those order paths should, in any case, be designed for all symbols. Even if whatever's trading on them
isn't trading all symbols, they should be able to accept any symbols on the broker that they're working on."):

* a strategy defines its own symbols (``config/strategies.yaml::<leg>.symbols``; an ML's set is its passed population
  record, ``src/config/ml_universe.py``);
* an account trades every symbol of each rostered leg that its VENUE can trade. That is a fact about the broker, not a
  configuration: a crypto perp venue trades crypto, Alpaca trades US equities/ETFs, IB trades futures and the US
  equities/ETFs our IB connector resolves to a STK contract (src/units/accounts/ib_instruments.py);
* a prop account additionally trades only the population its prop superset gate scored (``comms/prop_survival/<leg>.json
  ::symbols``; OPERATING-PLAN § 2, prop legs clear a superset), the existing gate, read as data.

There is no per-account symbol map. Per-trade ``RiskManager`` refusals are unchanged.

``asset_class`` is the same classification the read-only ``/api/bot/tradable`` and candles routes use
(``src/web/api/routers/candles.py::classify`` imports :func:`classify` from here), so the dashboard, the macro brief and
the order path agree on which venue answers for a symbol.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

_CRYPTO_SUFFIXES = ("USDT", "USDC", "PERP")
_EQUITY_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
_FUTURES_MONTH_RE = re.compile(r"^([A-Z]{2,})([FGHJKMNQUVXZ]\d{1,2})$")

#: Asset classes each venue (``accounts.yaml::<acct>.exchange``) can trade. A broker capability, not a per-account choice.
#: ``breakout`` is the crypto prop venue family (tradeify_1 / velotrade_1 route crypto perps).
VENUE_ASSET_CLASSES: Dict[str, frozenset] = {
    "bybit": frozenset({"crypto"}),
    "breakout": frozenset({"crypto"}),
    "alpaca": frozenset({"equity"}),
    "interactive_brokers": frozenset({"equity", "future"}),
    "oanda": frozenset({"fx"}),
}


def _profiles() -> Dict[str, Any]:
    try:
        from src.core.profile_loader import load_instrument_profiles
        return load_instrument_profiles() or {}
    except Exception:  # noqa: BLE001  # allow-silent: no profiles -> every symbol is classified by its shape alone
        return {}


def _profile(symbol: str, profiles: Mapping[str, Any]) -> Any:
    prof = profiles.get(symbol)
    if prof is None:
        m = _FUTURES_MONTH_RE.match(symbol)
        if m and m.group(1) in profiles:
            prof = profiles[m.group(1)]
    return prof


def classify(symbol: str, profiles: Optional[Mapping[str, Any]] = None) -> Dict[str, Optional[str]]:
    """Which venue answers for *symbol*: its instrument profile's exchange, else its shape (read-only routing)."""
    s = str(symbol or "").strip().upper()
    profiles = _profiles() if profiles is None else profiles
    prof = _profile(s, profiles)
    if prof is not None:
        return {"exchange": getattr(prof, "exchange", None), "basis": "instrument_profile"}
    if s.endswith(_CRYPTO_SUFFIXES):
        return {"exchange": "bybit", "basis": "crypto_suffix"}
    if _EQUITY_RE.match(s):
        return {"exchange": "alpaca", "basis": "equity_shape_unprofiled"}
    return {"exchange": None, "basis": "unrecognised"}


def asset_class(symbol: str, profiles: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """``crypto`` / ``equity`` / ``future`` / ``fx``, or None when the symbol is not recognised."""
    s = str(symbol or "").strip().upper()
    profiles = _profiles() if profiles is None else profiles
    prof = _profile(s, profiles)
    if prof is not None:
        if getattr(prof, "is_crypto", False):
            return "crypto"
        if getattr(prof, "is_futures", False):
            return "future"
        if str(getattr(prof, "exchange", "") or "").lower() == "oanda":
            return "fx"
        return "equity"
    if s.endswith(_CRYPTO_SUFFIXES):
        return "crypto"
    if _EQUITY_RE.match(s):
        return "equity"
    return None


def venue_can_trade(symbol: str, venue: Optional[str], profiles: Optional[Mapping[str, Any]] = None) -> bool:
    """True when *venue*'s broker can trade *symbol*'s asset class. An unknown venue or symbol is False (it cannot be
    routed there), never a silent pass."""
    v = str(venue or "").lower()
    caps = VENUE_ASSET_CLASSES.get(v)
    cls = asset_class(symbol, profiles)
    if not caps or cls not in caps:
        return False
    if v == "interactive_brokers" and cls == "equity":
        # IB trades US equities, but OUR IB connector places only what it resolves to an IBKR STK contract
        # (src/units/accounts/ib_instruments.py); anything else the coordinator drops as symbol_exchange_routing.
        try:
            from src.units.accounts.ib_instruments import is_ib_equity_symbol
            return bool(is_ib_equity_symbol(symbol))
        except Exception:  # noqa: BLE001  # allow-silent: unresolvable on IB -> not tradable there (never a silent pass)
            return False
    return True


def venue_symbols(symbols: Iterable[str], venue: Optional[str], profiles: Optional[Mapping[str, Any]] = None) -> List[str]:
    """``symbols`` (order kept) that *venue* can trade."""
    profiles = _profiles() if profiles is None else profiles
    return [s for s in symbols if venue_can_trade(s, venue, profiles)]
