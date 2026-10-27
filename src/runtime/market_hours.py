"""Market-hours / session gate (M15 Phase 1).

The pipeline was built for 24/7 crypto and has never had a trading
calendar (the ``killzone`` naming in older modules is a shim, not
session logic). The non-24/7 venues M15 adds need one:

- ``fx``        — 24/5: closed from Friday 21:00 UTC to Sunday 21:00 UTC.
- ``us_equity`` — US cash session: Mon–Fri 14:30–21:00 UTC.
- ``crypto``    — always open.

**WIRED** (M15): ``is_market_open`` is a live signal gate in
``strategy_signal_builders.py`` (the ``fx`` / ``us_equity`` session checks set
``side=none`` when the venue is closed) — skip fetch +
signal for a symbol whose market is closed, so closed-market stale
candles can never produce entries.

Research-grade limitations, by design (documented, not hidden):

- No US holiday calendar and no half-days — a holiday reads "open".
  Harmless for signal gating (no fresh bars arrive anyway); revisit
  before any equities strategy goes paper-live (M15 Phase 3).
- US DST is handled by month approximation (EST = UTC-5 in Nov–Feb →
  session 14:30–21:00 UTC standard, 13:30–20:00 UTC in DST months).
  Exact second-Sunday boundaries are NOT modeled; the affected edge
  weeks read conservatively (closed-when-actually-open at the margins).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

ASSET_CLASSES = ("crypto", "fx", "us_equity", "cme_futures")

# Months fully inside US daylight-saving time. March and November are
# transition months — treated as standard time (the conservative edge).
_FULL_DST_MONTHS = {4, 5, 6, 7, 8, 9, 10}


def _utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def is_market_open(asset_class: str, ts: datetime | None = None) -> bool:
    """True when *asset_class*'s market is open at *ts* (default: now).

    Unknown asset classes return ``True`` (fail-permissive, matching the
    Prime Directive posture — a gate bug must never strand a live
    capability; crypto/unknown symbols keep today's 24/7 behaviour).
    """
    ts = _utc(ts or datetime.now(timezone.utc))
    cls = str(asset_class or "").strip().lower()

    if cls == "fx":
        # Closed Fri 21:00 UTC -> Sun 21:00 UTC.
        wd, t = ts.weekday(), ts.time()
        if wd == 4 and t >= time(21, 0):  # Friday evening
            return False
        if wd == 5:  # Saturday
            return False
        if wd == 6 and t < time(21, 0):  # Sunday before reopen
            return False
        return True

    if cls == "us_equity":
        wd, t = ts.weekday(), ts.time()
        if wd >= 5:  # weekend
            return False
        if ts.month in _FULL_DST_MONTHS:
            open_t, close_t = time(13, 30), time(20, 0)
        else:
            open_t, close_t = time(14, 30), time(21, 0)
        return open_t <= t < close_t

    if cls == "cme_futures":
        # CME Globex (the micro equity-index / metals contracts ib_paper trades):
        # Sun 18:00 ET -> Fri 17:00 ET, with a daily 17:00-18:00 ET maintenance
        # break. ET from the same DST-month table as us_equity_session.
        et = ts - timedelta(hours=(4 if ts.month in _FULL_DST_MONTHS else 5))
        wd, t = et.weekday(), et.time()
        if wd == 5:  # Saturday
            return False
        if wd == 6:  # Sunday: opens 18:00 ET
            return t >= time(18, 0)
        if wd == 4:  # Friday: closes 17:00 ET for the weekend
            return t < time(17, 0)
        return not (time(17, 0) <= t < time(18, 0))  # Mon-Thu daily break

    return True  # crypto / unknown: 24/7


def us_equity_session(ts: datetime | None = None) -> str:
    """Session phase for the US equity market at *ts*: ``rth`` | ``extended`` | ``closed``.

    - ``rth``      — regular trading hours (09:30–16:00 ET): plain **market**
      orders fill. ``is_market_open("us_equity")`` is True exactly here.
    - ``extended`` — pre-market 04:00–09:30 ET + after-hours 16:00–20:00 ET:
      only a **limit** order with ``extended_hours=true`` can trade (a market
      order is rejected).
    - ``closed``   — overnight 20:00–04:00 ET + weekends: nothing trades.

    This is the exit-side companion to ``is_market_open`` (BL-20260716-ALPACA-
    MARKET-HOURS-EXIT): the entry gate only needs open/closed, but the exit path
    needs the three-way so it can market-close in RTH, limit-close in extended
    hours, and DEFER (leave the protective bracket armed) when fully closed —
    instead of firing doomed market flattens into a closed market every tick.

    ET is approximated from the same DST-month table ``is_market_open`` uses
    (March/November read as standard time — the conservative edge); exact
    second-Sunday DST boundaries and US holidays are NOT modeled.
    """
    ts = _utc(ts or datetime.now(timezone.utc))
    # Approximate ET wall-clock (hours behind UTC): 4 in DST months, else 5.
    et = ts - timedelta(hours=(4 if ts.month in _FULL_DST_MONTHS else 5))
    if et.weekday() >= 5:  # Sat/Sun in ET → closed
        return "closed"
    t = et.time()
    if time(9, 30) <= t < time(16, 0):
        return "rth"
    if (time(4, 0) <= t < time(9, 30)) or (time(16, 0) <= t < time(20, 0)):
        return "extended"
    return "closed"


def asset_class_for_exchange(exchange: str) -> str:
    """Map an exchange name to the asset class its symbols trade as."""
    e = str(exchange or "").strip().lower()
    if e == "oanda":
        return "fx"
    if e == "alpaca":
        return "us_equity"
    if e in ("interactive_brokers", "ib"):
        return "cme_futures"
    return "crypto"


def asset_class_for_symbol(symbol: str) -> str:
    """The asset class a SYMBOL trades as, from its instrument profile's exchange
    (``config/instruments.yaml``; SPY -> alpaca -> ``us_equity``, MES ->
    interactive_brokers -> ``cme_futures``). An unprofiled symbol or an
    unreadable profile reads ``crypto`` (24/7), the module's fail-permissive
    posture. Used by the claude_desk leg (DESK-PAPER-ACCOUNTS) and the desk
    scan packet."""
    try:
        from src.core.profile_loader import load_instrument_profiles
        prof = (load_instrument_profiles() or {}).get(str(symbol or "").upper())
    except Exception:  # noqa: BLE001 -- fail-permissive, as is_market_open
        prof = None
    return asset_class_for_exchange(getattr(prof, "exchange", "") if prof is not None else "")
