"""Venue adapter for the isolated pairs executor (M22) — the SESSION venue (Alpaca).

The pairs executor (``pairs_executor.run_pairs_tick``) was built for Bybit:
24/7 perps, fractional qty, a 1h bar that is always "the last closed bar".
An equity pair on Alpaca differs in exactly the places this module owns, and
NOTHING else in the engine changes (same spread/z math, same ``decide_pair``):

* **When to decide.** ``scripts/backtest_pairs.py`` enters and exits AT THE
  CLOSE of the decision bar. A daily equity bar's close is the 16:00 ET print,
  so the live sleeve decides inside the last ``decision_window_minutes`` of the
  venue's own session (``AlpacaClient.clock``), using the forming daily bar as
  the decision bar. Deciding on the completed bar at the NEXT open instead
  would fill every entry/exit across an overnight gap the backtest never paid,
  and Gate 2's realized-cost comparison would read that gap as cost.
  Outside the window no decision is taken; the bar is not consumed.
* **Bars held / cooldown.** ``max_hold_bars`` and ``cooldown_bars`` count
  TRADING bars. Wall-clock age / 86400 (the Bybit path) counts weekends, so it
  would time a 20-bar hold out after ~14 sessions. Here both are counted off
  the candle timestamps themselves.
* **Shorts.** A short leg needs the account's ``shorting_enabled`` (the
  existing ``broker_shorting_gate``) AND the asset's ``shortable`` /
  ``easy_to_borrow`` (``AlpacaClient.asset_short_status``). Refused BEFORE any
  leg is sent, so a borrow refusal can never leave the long leg naked.
* **Whole shares / buying power.** Alpaca brackets reject fractionals; both
  legs are floored to whole shares, and the pair is scaled down (hedge ratio
  preserved) to fit the broker's Reg-T buying power before anything is sent.
* **Netting.** Alpaca nets per symbol. A pairs leg opposite (or beside) a
  standing DIRECTIONAL position on the same symbol would reduce or merge with
  it, so a pair whose leg symbol carries a directional open row is refused.

Every read here has an explicit "could not look" answer, never folded into a
yes or a no. Nothing here halts anything (Prime Directive rule 7): a refusal
is per pair, per decision, and the next decision re-reads.
"""
from __future__ import annotations

import logging
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Exchanges whose pairs legs trade a SESSION (RTH) venue with whole-share,
#: per-symbol-netted positions. Everything else keeps the 24/7 Bybit path.
SESSION_EXCHANGES = frozenset({"alpaca"})

DEFAULT_DECISION_WINDOW_MINUTES = 10
#: Fraction of the broker's buying power a pair may use (headroom for the
#: market-order fill drifting from the decision price).
BUYING_POWER_BUFFER = 0.95


def exchange_of(acct_cfg: Dict[str, Any]) -> str:
    return str((acct_cfg or {}).get("exchange") or "").strip().lower()


def pairs_account_refusal(acct_cfg: Dict[str, Any]) -> Optional[str]:
    """Why the pairs sleeve may NOT trade this account, or None when it may.

    ``not_paper`` — ``config/accounts.yaml`` does not declare
    ``account_class: paper`` (real money, absent, unknown: fail closed).
    ``stage2_mirror`` — a paper account with ``paper_role: portfolio`` is the
    Stage-2 mirror of a real-money book (roster/trade equality with it is
    enforced by tests/test_paper_portfolio_accounts.py); a soak leg there
    would break that equality. The sleeve is a Stage-1 soak by operator
    decision, so only plain paper accounts qualify. This is the CODE check;
    the yaml test is the second line."""
    cfg = acct_cfg or {}
    if str(cfg.get("account_class") or "").strip().lower() != "paper":
        return "not_paper"
    if str(cfg.get("paper_role") or "").strip().lower() == "portfolio":
        return "stage2_mirror"
    return None


def is_session_venue(acct_cfg: Dict[str, Any]) -> bool:
    return exchange_of(acct_cfg) in SESSION_EXCHANGES


def build_client(acct_cfg: Dict[str, Any]) -> Any:
    """The account's order client (Bybit HTTP / AlpacaClient), or None when
    the venue is not wired or creds are missing. Never raises."""
    ex = exchange_of(acct_cfg)
    try:
        if ex == "bybit":
            from src.units.accounts.clients import bybit_client_for
            return bybit_client_for(acct_cfg)
        if ex == "alpaca":
            from src.units.accounts.clients import alpaca_client_for
            return alpaca_client_for(acct_cfg)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pairs_venue: client build failed for %s: %s",
                       acct_cfg.get("account_id"), exc)
    return None


# ── candles ────────────────────────────────────────────────────────────────

def fetch_leg_frame(symbol: str, timeframe: str, limit: int,
                    settings: Optional[Dict[str, Any]]) -> Optional[Tuple[List[float], List[datetime]]]:
    """``(closes, timestamps)`` for *symbol*, routed to the venue its
    instrument profile names (GLD → Alpaca), or None on any failure.

    The last row is kept even when it is the FORMING session bar: inside the
    decision window it is the decision bar (see module docstring)."""
    try:
        from src.runtime.market_data import connector_for_symbol, fetch_candles
        conn = connector_for_symbol(symbol, settings or {})
        df = fetch_candles(symbol, timeframe, settings=settings, limit=limit,
                           exchange_client=conn)
        if df is None or len(df) == 0 or "close" not in df or "timestamp" not in df:
            return None
        import pandas as pd
        ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        closes = [float(x) for x in df["close"].tolist()]
        stamps = [t.to_pydatetime() if not pd.isna(t) else None for t in ts]
        if any(s is None for s in stamps) or any(not math.isfinite(c) for c in closes):
            return None
        return closes, stamps
    except Exception as exc:  # noqa: BLE001
        logger.warning("pairs_venue: candle fetch failed (%s %s): %s", symbol, timeframe, exc)
        return None


def align_frames(a: Tuple[List[float], List[datetime]],
                 b: Tuple[List[float], List[datetime]]) -> Tuple[List[float], List[float], List[datetime]]:
    """Inner-join two leg frames on timestamp (the harness's ``_align``), so a
    bar missing on one leg can never pair leg A's day N with leg B's day N-1."""
    mb = {t: c for c, t in zip(b[0], b[1])}
    ca: List[float] = []
    cb: List[float] = []
    ts: List[datetime] = []
    for c, t in zip(a[0], a[1]):
        if t in mb:
            ca.append(c)
            cb.append(mb[t])
            ts.append(t)
    return ca, cb, ts


# ── session clock ──────────────────────────────────────────────────────────

def _parse_ts(value: Any) -> Optional[datetime]:
    try:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def decision_window_state(clock: Optional[Dict[str, Any]], *,
                          window_minutes: int = DEFAULT_DECISION_WINDOW_MINUTES,
                          now: Optional[datetime] = None) -> str:
    """Where the session is relative to the decision window. FOUR states:

    ``in_window`` — open, and within ``window_minutes`` of ``next_close``.
    ``open_outside_window`` — open, earlier in the session.
    ``closed`` — the venue says the market is closed (night, weekend, holiday).
    ``unreadable`` — the clock could not be read. NOT "closed": the caller
    takes no decision this tick and re-reads next tick (no latch).
    """
    if not isinstance(clock, dict) or "is_open" not in clock:
        return "unreadable"
    if clock.get("is_open") is not True:
        return "closed" if clock.get("is_open") is False else "unreadable"
    nxt = _parse_ts(clock.get("next_close"))
    cur = _parse_ts(clock.get("timestamp")) or now or datetime.now(timezone.utc)
    if nxt is None:
        return "unreadable"
    remaining = nxt - cur
    if timedelta(0) <= remaining <= timedelta(minutes=int(window_minutes)):
        return "in_window"
    return "open_outside_window"


def session_date(moment: datetime):
    """The US-equity SESSION date of *moment* (America/New_York calendar day)."""
    from zoneinfo import ZoneInfo
    m = moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
    return m.astimezone(ZoneInfo("America/New_York")).date()


def session_bar_stamp(day) -> datetime:
    """The UTC timestamp Alpaca stamps a daily bar for session *day* with
    (local midnight, America/New_York — 04:00Z in EDT, 05:00Z in EST)."""
    from zoneinfo import ZoneInfo
    local = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc)


#: A latest trade older than this does not stand in for today's close.
MAX_LATEST_TRADE_AGE_S = 900.0


def ensure_session_bar(symbol_a: str, symbol_b: str,
                       closes_a: List[float], closes_b: List[float],
                       stamps: List[datetime], clock: Optional[Dict[str, Any]],
                       client: Any) -> Tuple[str, List[float], List[float], List[datetime]]:
    """Make the LAST bar the CURRENT session's (forming) daily bar.

    ``(source, closes_a, closes_b, stamps)`` where ``source`` is:

    * ``forming_bar`` — the fetch already carried today's session bar; used
      as is.
    * ``latest_trade`` — the fetch ended at an EARLIER session (a completed-
      bars-only response): today's bar is appended from each leg's latest
      trade (``AlpacaClient.latest_trade``, at most
      ``MAX_LATEST_TRADE_AGE_S`` old), stamped like an Alpaca daily bar.
      Without this the in-window decision would run on the previous close —
      a day stale, i.e. a different strategy from the harness.
    * ``stale`` — today's bar is missing and a fresh latest trade could not
      be read for both legs. The caller takes NO decision this tick and does
      not consume the bar.

    Which of the first two the venue actually serves is not assumed: both are
    handled, and the soak row records which one decided. Never raises.
    """
    try:
        now = _parse_ts(clock.get("timestamp")) if isinstance(clock, dict) else None
        today = session_date(now or datetime.now(timezone.utc))
        if stamps and session_date(stamps[-1]) == today:
            return ("forming_bar", closes_a, closes_b, stamps)
        if stamps and session_date(stamps[-1]) > today:
            return ("stale", closes_a, closes_b, stamps)
        reader = getattr(client, "latest_trade", None)
        if not callable(reader):
            return ("stale", closes_a, closes_b, stamps)
        px: List[float] = []
        for sym in (symbol_a, symbol_b):
            t = reader(sym)
            if not isinstance(t, dict):
                return ("stale", closes_a, closes_b, stamps)
            price, age = t.get("price"), t.get("age_s")
            if (price is None or not math.isfinite(float(price)) or float(price) <= 0
                    or age is None or float(age) > MAX_LATEST_TRADE_AGE_S):
                return ("stale", closes_a, closes_b, stamps)
            px.append(float(price))
        return ("latest_trade", list(closes_a) + [px[0]], list(closes_b) + [px[1]],
                list(stamps) + [session_bar_stamp(today)])
    except Exception as exc:  # noqa: BLE001
        logger.warning("pairs_venue: session-bar check failed: %s", exc)
        return ("stale", closes_a, closes_b, stamps)


# ── trading-bar counts (bars held, cooldown) ───────────────────────────────

def bars_after(moment: Optional[datetime], timestamps: Sequence[datetime]) -> Optional[int]:
    """Number of bars whose OPEN timestamp is strictly after *moment*.

    With the decision taken inside bar D's session (D's bar opened before the
    order), the bar D+k decision sees exactly k bars after the open — the
    harness's ``j - i``. None when *moment* is unknown (we could not count)."""
    if moment is None:
        return None
    m = moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
    return sum(1 for t in timestamps if t > m)


def last_close_time(strategy: str, account_id: str, db_path: str) -> Tuple[str, Optional[datetime]]:
    """Newest ``closed_at`` of a closed leg row: ``("found", dt)`` ·
    ``("none", None)`` (we looked; this leg never closed) · ``("error", None)``
    (we could not look). Read-only, never raises."""
    try:
        if not db_path or not os.path.exists(db_path):
            return ("error", None)
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT MAX(closed_at) FROM trades WHERE account_id = ? "
                "AND strategy_name = ? AND status = 'closed' "
                "AND COALESCE(is_backtest, 0) = 0",
                (str(account_id), str(strategy)),
            ).fetchone()
        if not row or not row[0]:
            return ("none", None)
        dt = _parse_ts(row[0])
        return ("found", dt) if dt is not None else ("error", None)
    except Exception as exc:  # noqa: BLE001
        logger.error("pairs_venue: last-close read FAILED for %s: %s", strategy, exc)
        return ("error", None)


def cooldown_state(cooldown_bars: int, last_close: Tuple[str, Optional[datetime]],
                   timestamps: Sequence[datetime]) -> str:
    """``clear`` / ``cooling`` / ``unreadable``. Mirrors the harness's
    ``next_idx = exit_idx + 1 + cooldown_bars``: an entry is allowed once
    ``bars_after(close) >= cooldown_bars + 1``."""
    if int(cooldown_bars) <= 0:
        return "clear"
    status, dt = last_close
    if status == "none":
        return "clear"
    if status != "found":
        return "unreadable"
    n = bars_after(dt, timestamps)
    if n is None:
        return "unreadable"
    return "clear" if n >= int(cooldown_bars) + 1 else "cooling"


# ── shorts ─────────────────────────────────────────────────────────────────

def short_leg_block(client: Any, acct_cfg: Dict[str, Any], symbol: str) -> Tuple[Optional[str], str]:
    """``(block_reason | None, state)`` for selling *symbol* short.

    Refuses on what the broker SAID: account ``shorting_enabled: false``
    (``broker_shorting_disabled``), or the asset not ``tradable`` /
    ``shortable`` / ``easy_to_borrow``. A read that fails is ``unknown`` and
    does NOT refuse (fail-permissive, the same discipline as
    ``broker_shorting_gate``): the venue still rejects an unexecutable short,
    and the executor's leg-imbalance unwind owns that case."""
    from src.runtime.broker_shorting_gate import REFUSAL_TOKEN, shorting_state
    account_id = str(acct_cfg.get("account_id") or "unknown")
    acct_state = shorting_state(account_id, exchange_of(acct_cfg), lambda: client)
    if acct_state == "disabled":
        return REFUSAL_TOKEN, acct_state
    status = None
    try:
        reader = getattr(client, "asset_short_status", None)
        status = reader(symbol) if callable(reader) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("pairs_venue: asset short read failed for %s: %s", symbol, exc)
    if not isinstance(status, dict):
        return None, f"account_{acct_state}|asset_unknown"
    for key, reason in (("tradable", "asset_not_tradable"),
                        ("shortable", "asset_not_shortable"),
                        ("easy_to_borrow", "asset_hard_to_borrow")):
        if status.get(key) is False:
            return reason, f"account_{acct_state}|{reason}"
    return None, f"account_{acct_state}|asset_shortable"


# ── whole shares + buying power ────────────────────────────────────────────

def whole_share_legs(qty_a: float, qty_b: float) -> Tuple[int, int]:
    """Floor both legs to whole shares (never up — realised risk must not
    exceed the sized basis)."""
    return int(math.floor(max(0.0, float(qty_a)) + 1e-9)), int(math.floor(max(0.0, float(qty_b)) + 1e-9))


def fit_buying_power(qty_a: int, qty_b: int, price_a: float, price_b: float,
                     buying_power: Optional[float], *,
                     buffer: float = BUYING_POWER_BUFFER) -> Dict[str, Any]:
    """Scale a whole-share pair down (hedge ratio preserved) so its GROSS
    notional fits ``buffer × buying_power``.

    Returns ``{qty_a, qty_b, scale, bp_state}`` where ``bp_state`` is
    ``fits`` · ``scaled`` · ``insufficient`` (a leg floors to 0) ·
    ``unknown`` (buying power unreadable — the pair is NOT scaled, the venue's
    own margin check stays the backstop)."""
    gross = qty_a * float(price_a) + qty_b * float(price_b)
    if buying_power is None:
        return {"qty_a": qty_a, "qty_b": qty_b, "scale": 1.0, "bp_state": "unknown"}
    cap = max(0.0, float(buying_power)) * float(buffer)
    if gross <= cap:
        return {"qty_a": qty_a, "qty_b": qty_b, "scale": 1.0, "bp_state": "fits"}
    k = cap / gross if gross > 0 else 0.0
    na, nb = whole_share_legs(qty_a * k, qty_b * k)
    if na <= 0 or nb <= 0:
        return {"qty_a": 0, "qty_b": 0, "scale": round(k, 6), "bp_state": "insufficient"}
    return {"qty_a": na, "qty_b": nb, "scale": round(k, 6), "bp_state": "scaled"}
