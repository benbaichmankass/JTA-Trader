"""Server-side fill / close INFERENCE for the prop book (PHONE-POSITIONS-READ-CONTEXT scope add).

WHY (operator, 2026-10-13, verbatim): *"the system opened that position, it should be aware of it"*. A resting limit
the system itself issued (journal status ``placed``) must not wait for the phone's Positions read to become a known
open position: when the venue-symbol candles (the SAME feed ``/api/bot/candles`` serves) trade THROUGH the limit after
it was placed, the order has filled. This module journals that, as an ESTIMATE, and the existing mark-based uPnL
(``prop_overview._mark_estimate``) then applies because the row is ``open`` with an entry and a size.

Rules (each is a way an inference can lie, refused):

* **ESTIMATED, never MEASURED.** Entry = the limit price (a resting limit fills at or better than its price; the
  true fill is unknown). The row carries ``provenance: estimated``, ``inferred: true``, an ``external_order_id`` of
  ``inferred-<ticket>`` and a reason that starts ``INFERRED`` so every surface labels it.
* **Strictly through.** A short limit needs a bar HIGH above the price, a long a bar LOW below it. A bar that only
  touches the price does not fill; a bar that opened before the order was placed is not considered.
* **A close needs a LATER bar.** SL/TP are looked for only in bars after the fill bar. If one bar spans BOTH the
  stop and the target the order of events is unknowable: nothing is written and ONE flag is raised. If the fill bar
  itself spans a level, the fill is still journaled but ONE flag says the ordering is unknown.
* **The phone is the arbiter.** ``positions`` is the latest CLEAN venue Positions read (``None`` = none / stale).
  With a clean read: a placed order whose symbol+side is NOT on the venue list is not inferred filled (the venue
  disagrees with the Bybit feed); an inferred-open row that IS on the list is overwritten in place with the venue's
  entry and size, provenance MEASURED; an inferred-open row that is on the list is never inferred closed.
  An inferred value is never written over a MEASURED row (only ``placed`` and inferred rows are touched).
* Writes go through :func:`src.prop.prop_report.ingest_report` (the one fill chokepoint), whose fill / close
  notification is the ONE alert per inference. No order is placed, cancelled or amended; the phone-driven reconcile
  keeps its own ``report_only`` mode for open/close decisions made from the phone.
* Fail soft: an unreadable feed changes nothing ("we could not look" is not "it did not fill").
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.runtime.provenance import ESTIMATED, MEASURED

logger = logging.getLogger(__name__)

SOURCE = "fill_inference"
MAX_AGE = timedelta(days=7)      # a placed order older than this is stale, not inferred
INTERVAL_S = 300.0               # the tick hook runs the pass at most this often
BAR_S = 300                      # candle interval used (5m, the feed local_pnl.last_mark_price uses)
_LOCK = threading.Lock()
_LAST_RUN = 0.0

Bar = Tuple[datetime, float, float]            # (bar open time, high, low)
BarsFn = Callable[[str, datetime, datetime], List[Bar]]


def _parse(ts: Any) -> Optional[datetime]:
    from src.prop.phone_reconcile import _parse as p
    return p(ts)


def _side(v: Any) -> Optional[str]:
    s = str(v or "").lower()
    return "long" if s in ("long", "buy") else "short" if s in ("short", "sell") else None


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x > 0 else None


def _raw(f: Dict[str, Any]) -> Dict[str, Any]:
    r = f.get("raw")
    if isinstance(r, str):
        try:
            r = json.loads(r)
        except ValueError:
            return {}
    return r if isinstance(r, dict) else {}


def _placed_at(f: Dict[str, Any]) -> Optional[datetime]:
    """When the working order reached the venue. BREAKOUT-UNTRACKED-1014: an unconfirmed live submit is journaled by the
    stale-claim watchdog, which ran 5 h after the click (2026-10-14: submit ~13:22Z, row 18:36Z); keying the bars off
    that write time missed the fill bar, so the open short was never inferred. Order: the report's own ``placed_at``,
    ``opened_at``, the ticket's go-token redemption time (taken right before the submit click), then ``reported_at``."""
    raw = _raw(f)
    at = _parse(raw.get("placed_at")) or _parse(f.get("opened_at"))
    if at is None and raw.get("source") == "phone_executor_unconfirmed" and f.get("ticket_id"):
        try:
            from src.prop import prop_journal
            t = prop_journal.get_ticket(str(f["ticket_id"])) or {}
            m = t.get("meta") if isinstance(t.get("meta"), dict) else {}
            at = _parse((((m.get("phone") or {}).get("go")) or {}).get("used_at"))
        except Exception:  # noqa: BLE001  # allow-silent: falls back to reported_at below
            logger.warning("fill_inference: go-token time lookup failed for %s", f.get("ticket_id"), exc_info=True)
    return at or _parse(f.get("reported_at"))


def is_inferred(f: Dict[str, Any]) -> bool:
    return _raw(f).get("source") == SOURCE and _raw(f).get("provenance") == ESTIMATED


def _ext(ticket_id: str) -> str:
    return f"inferred-{ticket_id}"


def default_bars(symbol: str, since: datetime, now: datetime) -> List[Bar]:
    """5m bars from the bot's own exchange feed (same source as /api/bot/candles). [] when unreadable."""
    try:
        from src.runtime.market_data import connector_for_symbol, fetch_candles

        limit = int(min(1000, max(3, (now - since).total_seconds() // BAR_S + 3)))
        client = connector_for_symbol(symbol, {})
        df = fetch_candles(symbol, "5m", settings={}, limit=limit, exchange_client=client,
                           since=int(since.timestamp() * 1000), bypass_cache=True)
        if df is None or len(df) == 0:
            return []
        out: List[Bar] = []
        for _, r in df.iterrows():
            t = r.get("timestamp")
            ts = (t.to_pydatetime() if hasattr(t, "to_pydatetime") else
                  datetime.fromtimestamp(float(t) / (1000.0 if float(t) > 1e11 else 1.0), tz=timezone.utc)
                  if isinstance(t, (int, float)) else _parse(t))
            if ts is None:
                continue
            ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            hi, lo = _f(r.get("high")), _f(r.get("low"))
            if hi is not None and lo is not None:
                out.append((ts, hi, lo))
        return sorted(out, key=lambda b: b[0])
    except Exception:  # noqa: BLE001  # allow-silent: logged; "could not look" changes nothing
        logger.warning("fill_inference: candle read failed for %s", symbol, exc_info=True)
        return []


def _through(side: str, price: float, hi: float, lo: float) -> bool:
    """Entry limit: a short sells at >= price (needs a high above it), a long buys at <= price (a low below it)."""
    return hi > price if side == "short" else lo < price


def _hits(side: str, sl: Optional[float], tp: Optional[float], hi: float, lo: float) -> Tuple[bool, bool]:
    """(sl_hit, tp_hit) for one bar. A bar that touches the level counts: stops and targets are marketable."""
    if side == "short":
        return (sl is not None and hi >= sl, tp is not None and lo <= tp)
    return (sl is not None and lo <= sl, tp is not None and hi >= tp)


def _state_path(account_id: str):
    from src.prop import phone_executor
    return phone_executor._diag_path(account_id).with_name(
        f"prop_fill_inference_{re.sub(r'[^a-z0-9_]', '', account_id)}.json")


def _flag_once(account_id: str, key: str, msg: str, send=None) -> None:
    p = _state_path(account_id)
    try:
        st = json.loads(p.read_text())
    except (OSError, ValueError):
        st = {}
    flagged = st.setdefault("flagged", [])
    if key in flagged:
        return
    flagged.append(key)
    try:
        p.write_text(json.dumps({"flagged": flagged[-200:]}))
    except OSError:  # allow-silent: logged; worst case the flag repeats once
        logger.warning("fill_inference: state write failed for %s", account_id, exc_info=True)
    from src.prop import phone_executor
    phone_executor._ping(f"📱 {account_id} [inferred, ESTIMATED]: {msg}", send)


def infer(account_id: str, *, now: Optional[datetime] = None, bars_fn: Optional[BarsFn] = None,
          positions: Optional[List[Dict[str, Any]]] = None, send=None) -> Dict[str, Any]:
    """One inference pass for the account. Returns what it did: ``filled`` / ``closed`` / ``measured`` /
    ``flagged`` ticket lists. Never raises past a logged warning for one row."""
    from src.prop import prop_journal
    from src.prop.prop_overview import split_fills
    from src.prop.prop_report import ingest_report

    now = now or datetime.now(timezone.utc)
    bars_fn = bars_fn or default_bars
    out: Dict[str, Any] = {"filled": [], "closed": [], "measured": [], "flagged": []}
    with _LOCK:
        fills = prop_journal.list_fills(account_id=account_id, limit=500)
        open_rows, closed_rows = split_fills(fills)
        open_rows = [f for f in open_rows if f.get("account_id") == account_id]
        have = {str(f["ticket_id"]) for f in open_rows + closed_rows if f.get("ticket_id")}
        venue = positions if isinstance(positions, list) else None

        def on_venue(sym: str, side: str) -> Optional[Dict[str, Any]]:
            return next((p for p in (venue or []) if str(p.get("symbol") or "").upper() == sym
                         and p.get("direction") == side), None)

        # 1. placed working order -> filled-open (ESTIMATED)
        seen_t: set = set()
        for f in fills:
            tid = str(f.get("ticket_id") or "")
            if str(f.get("status") or "").lower() != "placed" or not tid or tid in have or tid in seen_t:
                continue
            seen_t.add(tid)
            try:
                sym, side = str(f.get("symbol") or "").upper(), _side(f.get("direction"))
                limit, qty = _f(f.get("entry_price")), _f(f.get("qty"))
                placed_at = _placed_at(f)
                if not (sym and side and limit and qty and placed_at) or now - placed_at > MAX_AGE:
                    continue
                if venue is not None and on_venue(sym, side) is None:
                    continue      # the venue's clean read says it is not a position: the phone is the arbiter
                bars = [b for b in bars_fn(sym, placed_at, now) if b[0] >= placed_at]
                hit = next((b for b in bars if _through(side, limit, b[1], b[2])), None)
                if hit is None:
                    continue
                sl, tp = _f(f.get("sl")), _f(f.get("tp"))
                rep = {"kind": "fill", "status": "open", "account_id": account_id, "ticket_id": tid,
                       "external_order_id": _ext(tid), "symbol": sym, "direction": side, "qty": qty,
                       "entry_price": limit, "sl": sl, "tp": tp, "opened_at": hit[0].isoformat(),
                       "source": SOURCE, "provenance": ESTIMATED, "inferred": True,
                       "reason": f"INFERRED fill (ESTIMATED, not a venue read): {sym} candles traded through the "
                                 f"{side} limit {limit:g} in the bar opening {hit[0].isoformat()}; entry is the limit price",
                       "inference": {"bar_open": hit[0].isoformat(), "bar_high": hit[1], "bar_low": hit[2]}}
                ingest_report(rep)
                out["filled"].append(tid)
                if any(_hits(side, sl, tp, hit[1], hit[2])):
                    out["flagged"].append(tid)
                    _flag_once(account_id, f"fillbar:{tid}",
                               f"{sym} {side} {tid} filled in a bar that also traded through its SL/TP; the order of "
                               f"events is unknown. The terminal's read decides.", send)
            except Exception:  # noqa: BLE001  # allow-silent: logged; one bad row never blocks the rest
                logger.warning("fill_inference: fill inference failed for %s %s", account_id, tid, exc_info=True)

        if out["filled"]:   # placed -> filled -> closed between two looks: judge the new open rows in the SAME pass
            fills = prop_journal.list_fills(account_id=account_id, limit=500)
            open_rows, _ = split_fills(fills)
            open_rows = [f for f in open_rows if f.get("account_id") == account_id]

        # 2. inferred-open rows: the venue overrides; else SL/TP crossed by a LATER bar closes (ESTIMATED)
        for f in open_rows:
            if not is_inferred(f):
                continue
            tid = str(f.get("ticket_id") or "")
            try:
                sym, side = str(f.get("symbol") or "").upper(), _side(f.get("direction"))
                vp = on_venue(sym, side) if side else None
                if vp is not None:
                    ve, vq = _f(vp.get("entry")), _f(vp.get("qty"))
                    if ve and vq and (ve != f.get("entry_price") or vq != f.get("qty")):
                        ingest_report({"kind": "fill", "status": "open", "account_id": account_id, "ticket_id": tid,
                                       "external_order_id": f.get("external_order_id"), "symbol": sym,
                                       "direction": side, "qty": vq, "entry_price": ve, "sl": f.get("sl"),
                                       "tp": f.get("tp"), "opened_at": f.get("opened_at"), "source": "phone_reconcile",
                                       "provenance": MEASURED,
                                       "reason": "venue Positions read overrides the inferred fill (entry and size)"})
                        out["measured"].append(tid)
                    continue
                opened = _parse(f.get("opened_at"))
                side_ok, sl, tp = side, _f(f.get("sl")), _f(f.get("tp"))
                if not (opened and side_ok and (sl or tp)):
                    continue
                bars = [b for b in bars_fn(sym, opened, now) if b[0] > opened]
                for b in bars:
                    s_hit, t_hit = _hits(side_ok, sl, tp, b[1], b[2])
                    if not (s_hit or t_hit):
                        continue
                    if s_hit and t_hit:
                        out["flagged"].append(tid)
                        _flag_once(account_id, f"both:{tid}",
                                   f"{sym} {side_ok} {tid}: one bar ({b[0].isoformat()}) traded through BOTH the stop "
                                   f"and the target; not guessing which came first. The terminal's read decides.", send)
                        break
                    px, why = (sl, "sl") if s_hit else (tp, "tp")
                    ingest_report({"kind": "fill", "status": "closed", "account_id": account_id, "ticket_id": tid,
                                   "external_order_id": f.get("external_order_id"), "symbol": sym,
                                   "direction": side_ok, "qty": f.get("qty"), "entry_price": f.get("entry_price"),
                                   "sl": sl, "tp": tp, "exit_price": px, "pnl": None,
                                   "closed_at": b[0].isoformat(), "source": SOURCE, "provenance": ESTIMATED,
                                   "inferred": True,
                                   "reason": f"INFERRED {why} close (ESTIMATED, not a venue read): candles traded "
                                             f"through {px:g} in the bar opening {b[0].isoformat()}; exit is the level"})
                    out["closed"].append(tid)
                    break
            except Exception:  # noqa: BLE001  # allow-silent: logged; one bad row never blocks the rest
                logger.warning("fill_inference: close inference failed for %s %s", account_id, tid, exc_info=True)
    return out


def run_inference_tick() -> Dict[str, Any]:
    """Tick hook (src/main.py): at most every :data:`INTERVAL_S`, one pass per phone-executed prop account, using
    the latest FRESH clean Positions read as the arbiter. Best-effort; never raises."""
    global _LAST_RUN
    mono = time.monotonic()
    if _LAST_RUN and mono - _LAST_RUN < INTERVAL_S:
        return {}
    _LAST_RUN = mono
    res: Dict[str, Any] = {}
    try:
        from src.config.accounts_loader import load_accounts_dict
        from src.prop import phone_executor, prop_journal, prop_reconcile
        from src.prop.prop_overview import _venue_positions, prop_account_ids

        for aid in prop_account_ids(load_accounts_dict()):
            if not phone_executor.is_phone_account(aid):
                continue
            snap = prop_journal.latest_account_status(aid)
            fresh = prop_reconcile.compute_rule_distance(aid, snap).get("status_freshness")
            res[aid] = infer(aid, positions=_venue_positions(snap, fresh))
    except Exception:  # noqa: BLE001  # allow-silent: logged; the tick never fails on this
        logger.warning("fill_inference: tick failed", exc_info=True)
    return res
