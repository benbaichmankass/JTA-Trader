"""Pure builders for the trade chart snapshot + decision markers (UI-REDESIGN-2026-11, addenda 2, 3 and 5).

Routes (``src.web.api.routers.trade_snapshot``):
  * ``GET /api/bot/trades/{id}/snapshot`` -- the STORED snapshot of a closed trade (built once by
    ``src.runtime.trade_snapshot_builder``, kept in ``trade_chart_snapshots``; see ``src.runtime.trade_snapshot_store``).
  * ``GET /api/bot/trades/{id}/markers``  -- the same marker blocks for an OPEN trade, computed per request.

Contract + fixtures: docs/reference/bot-api-reference.md § "Trade chart snapshot + decision markers",
tests/fixtures/trade_chart_snapshot_v1.json, tests/fixtures/trade_markers_v1.json.

Everything here is pure (no I/O): the callers pass the trade row, its order package, candles, review rows and
directed-action receipts. Honesty rules: null stays null (never 0 / []); every part that could not be read says
so in ``read_state`` / ``partial_reasons``; per-bar strategy indicators are NOT recorded anywhere, so the chart's
series are computed from the stored candles and labelled ``computed_from_candles``, and the strategy's own values
at entry come from ``signal_logic.features``.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.web.api import brackets_history as bh

SCHEMA = "trade_chart_snapshot/v1"
TIME_PAD_FRAC = 0.15
PRICE_PAD_FRAC = 0.10
MAX_BARS = 300
MIN_BARS = 20
#: Bar sizes the snapshot may pick, smallest first (all in ``bh._INTERVAL_S`` and the candles route's set).
INTERVALS = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
#: Review actions that recommend nothing (a marker still shows, disposition ``no_action``).
NO_ACTION = (None, "", "hold", "no_recommendation")
_SUMMARY_MAX = 200


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return float(v)
    return None


def _json(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str) and v:
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return None
    return None


def _dict(v: Any) -> Dict[str, Any]:
    d = _json(v)
    return d if isinstance(d, dict) else {}


# ───────────────────────────────────────────── frame

def choose_interval(window_s: float) -> str:
    """Smallest bar size whose window holds at most ``MAX_BARS`` bars."""
    for iv in INTERVALS:
        if window_s / bh._INTERVAL_S[iv] <= MAX_BARS:
            return iv
    return INTERVALS[-1]


def time_frame(opened: datetime, closed: datetime) -> Dict[str, Any]:
    """open..close widened by ``TIME_PAD_FRAC`` of the span on each side, and the bar size for it.

    A very short trade still gets ``MIN_BARS`` bars of the smallest interval (``min_window_applied``), else
    the chart would be one or two bars wide."""
    span = max((closed - opened).total_seconds(), 0.0)
    pad = span * TIME_PAD_FRAC
    t0, t1 = opened - timedelta(seconds=pad), closed + timedelta(seconds=pad)
    interval = choose_interval((t1 - t0).total_seconds())
    min_s = MIN_BARS * bh._INTERVAL_S[interval]
    applied = (t1 - t0).total_seconds() < min_s
    if applied:
        extra = (min_s - (t1 - t0).total_seconds()) / 2.0
        t0, t1 = t0 - timedelta(seconds=extra), t1 + timedelta(seconds=extra)
    return {"interval": interval, "time_from": t0, "time_to": t1, "open_close_span_s": int(span),
            "min_window_applied": applied}


def price_frame(candles: List[Dict[str, Any]], opened: datetime, closed: datetime,
                fallback: Iterable[Optional[float]] = ()) -> Dict[str, Any]:
    """The low/high of the candles between open and close, widened by ``PRICE_PAD_FRAC`` of that range.

    With no candle in the span it falls back to the entry/exit prices (``high_low_over`` says which)."""
    lo_t, hi_t = opened.timestamp(), closed.timestamp()
    step = 0
    if len(candles) >= 2:
        step = candles[1]["time"] - candles[0]["time"]
    inside = [c for c in candles if lo_t - step < c["time"] <= hi_t]
    if inside:
        high, low, over = max(c["high"] for c in inside), min(c["low"] for c in inside), \
            "candles between opened_at and closed_at"
    else:
        xs = [x for x in (_num(v) for v in fallback) if x is not None]
        if not xs:
            return {"price_low": None, "price_high": None, "high": None, "low": None, "high_low_over": None}
        high, low, over = max(xs), min(xs), "entry and exit prices (no candles in the span)"
    rng = high - low
    pad = rng * PRICE_PAD_FRAC if rng > 0 else abs(high) * 0.001
    return {"price_low": low - pad, "price_high": high + pad, "high": high, "low": low, "high_low_over": over}


# ───────────────────────────────────────────── indicators (computed from the stored candles)

def _ema(closes: List[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(closes[:n]) / n
    out[n - 1] = e
    for i in range(n, len(closes)):
        e = closes[i] * k + e * (1 - k)
        out[i] = e
    return out


def _rsi(closes: List[float], n: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n

    def val(gain: float, loss: float) -> float:
        return 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)

    out[n] = val(ag, al)
    for i in range(n + 1, len(closes)):
        ag = (ag * (n - 1) + gains[i - 1]) / n
        al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = val(ag, al)
    return out


def _atr(candles: List[Dict[str, Any]], n: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(candles)
    if len(candles) <= n:
        return out
    trs = [candles[0]["high"] - candles[0]["low"]]
    for i in range(1, len(candles)):
        hi, lo, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    a = sum(trs[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(candles)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def indicators(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candles:
        return {"state": "unavailable", "source": "computed_from_candles", "series": None}
    closes = [c["close"] for c in candles]
    times = [c["time"] for c in candles]

    def series(name: str, pane: str, vals: List[Optional[float]]) -> Dict[str, Any]:
        return {"name": name, "pane": pane, "points": [{"time": t, "value": v} for t, v in zip(times, vals)]}

    return {"state": "measured", "source": "computed_from_candles", "series": [
        series("ema_20", "price", _ema(closes, 20)), series("ema_50", "price", _ema(closes, 50)),
        series("rsi_14", "rsi", _rsi(closes, 14)), series("atr_14", "atr", _atr(candles, 14))]}


# ───────────────────────────────────────────── trade / entry / exit / signal

def trade_block(trade: Dict[str, Any], pnl_provenance: Optional[str] = None) -> Dict[str, Any]:
    opened = bh.parse_ts(trade.get("timestamp"))
    closed = bh.parse_ts(trade.get("closed_at"))
    return {"trade_id": trade.get("id"), "prop_fill_id": trade.get("prop_fill_id"),
            "ticket_id": trade.get("ticket_id"), "order_package_id": trade.get("order_package_id"),
            "account_id": trade.get("account_id"), "account_class": trade.get("account_class"),
            "strategy_name": trade.get("strategy_name"), "symbol": trade.get("symbol"),
            "direction": trade.get("direction"), "qty": _num(trade.get("position_size")),
            "opened_at": _iso(opened), "closed_at": _iso(closed),
            "entry_price": _num(trade.get("entry_price")), "exit_price": _num(trade.get("exit_price")),
            "exit_reason": trade.get("exit_reason") or None, "pnl": _num(trade.get("pnl")),
            "pnl_provenance": pnl_provenance}


def point(ts: Optional[datetime], price: Any, interval: str, **extra: Any) -> Optional[Dict[str, Any]]:
    if ts is None and _num(price) is None:
        return None
    p = _num(price)
    return {"ts": _iso(ts), "bar_ts": bh.bar_ts(ts, interval), "price": p,
            "provenance": "MEASURED" if (ts is not None and p is not None) else "UNVERIFIED", **extra}


def entry_signal(pkg: Optional[Dict[str, Any]], interval: str) -> Dict[str, Any]:
    if pkg is None:
        return {"state": "no_record"}
    sl = _dict(pkg.get("signal_logic"))
    meta = _dict(pkg.get("meta"))
    src = sl or meta
    if not src:
        return {"state": "no_record"}
    db = bh.parse_ts(src.get("decision_bar") or src.get("entry_time"))
    feats = src.get("features")
    scores = _json(pkg.get("model_scores"))
    return {"state": "measured", "decision_bar": _iso(db), "bar_ts": bh.bar_ts(db, interval),
            "timeframe": src.get("timeframe"), "model_id": src.get("model_id"),
            "confidence": _num(pkg.get("confidence")) if pkg.get("confidence") is not None else _num(src.get("confidence")),
            "p_long": _num(src.get("p_long")), "p_short": _num(src.get("p_short")),
            "tp_intent": src.get("tp_intent"), "tp_basis": src.get("tp_basis"),
            "contributing_strategies": src.get("contributing_strategies"),
            "features": feats if isinstance(feats, dict) else None,
            "model_scores": scores if isinstance(scores, (dict, list)) else None}


def prop_trade(opener: Dict[str, Any], closer: Optional[Dict[str, Any]],
               ticket: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A prop trade (``prop_fills`` opening row + closing row, ``prop_tickets`` row) in the ``trades``-row shape the
    builders read. ``id`` is None (prop has no ``trades.id``); ``prop_fill_id`` = the opening row's id. The ticket's
    ``meta.sl_floor`` (written by the live-review / phone-trail applies) becomes ``notes.sl_floor`` so a review it
    names reads ``applied``. Bracket history comes from the opener's ``amendments`` (``_prop_opener``)."""
    tk = ticket or {}
    meta = _dict(tk.get("meta"))
    notes: Dict[str, Any] = {}
    if isinstance(meta.get("sl_floor"), dict):
        notes["sl_floor"] = meta["sl_floor"]
    c = closer or {}
    d = str(opener.get("direction") or "").lower()
    direction = "long" if d in ("long", "buy") else ("short" if d in ("short", "sell") else (opener.get("direction") or None))
    return {"id": None, "prop_fill_id": opener.get("id"), "ticket_id": opener.get("ticket_id"),
            "timestamp": opener.get("opened_at") or opener.get("reported_at"),
            "closed_at": c.get("closed_at") or (c.get("reported_at") if closer else None),
            "status": "closed" if closer else "open", "symbol": opener.get("symbol"), "direction": direction,
            "position_size": opener.get("qty"), "entry_price": opener.get("entry_price"),
            "exit_price": c.get("exit_price"), "exit_reason": c.get("reason"), "pnl": c.get("pnl"),
            "stop_loss": opener.get("sl"), "take_profit_1": opener.get("tp"),
            "account_id": opener.get("account_id"), "account_class": "prop",
            "order_package_id": tk.get("order_package_id"), "strategy_name": tk.get("strategy"),
            "notes": json.dumps(notes), "_prop_opener": opener}


# ───────────────────────────────────────────── brackets

def _account_updates(notes: Dict[str, Any], interval: str) -> List[Dict[str, Any]]:
    """This account's own stop / trade-action moves from ``trades.notes`` (``sl_amends``, ``live_review_actions``)."""
    out: List[Dict[str, Any]] = []
    for a in notes.get("sl_amends") or []:
        ts = bh.parse_ts(a.get("at")) if isinstance(a, dict) else None
        if ts is None:
            continue
        out.append({"ts": _iso(ts), "kind": "sl", "from": _num(a.get("from")), "to": _num(a.get("to")),
                    "source": a.get("source"), "detail": a.get("review_id") or "", "bar_ts": bh.bar_ts(ts, interval),
                    "scope": "account"})
    for a in notes.get("live_review_actions") or []:
        ts = bh.parse_ts(a.get("at")) if isinstance(a, dict) else None
        if ts is None:
            continue
        act = str(a.get("action") or "")
        kind = "tp" if "tp" in act else ("sl" if "sl" in act else "action")
        out.append({"ts": _iso(ts), "kind": kind, "from": _num(a.get("from")),
                    "to": _num(a.get("to")) if a.get("to") is not None else _num(a.get("level")),
                    "source": a.get("source"), "detail": a.get("review_id") or "", "action": act or None,
                    "bar_ts": bh.bar_ts(ts, interval), "scope": "account"})
    return out


def brackets(trade: Dict[str, Any], pkg: Optional[Dict[str, Any]], interval: str) -> Dict[str, Any]:
    notes = _dict(trade.get("notes"))
    acct = _account_updates(notes, interval)
    if trade.get("_prop_opener") is not None:
        # prop: the ticket's own SL/TP amendments (before/after, with times) ARE this account's bracket history
        h = bh.build_prop_history(trade["_prop_opener"], interval)
        ups = [dict(u, scope="account") for u in h["updates"]] + acct
        return {"read_state": "partial" if h["read_state"] != "measured" else "measured",
                "partial_reasons": list(h["partial_reasons"]), "tp_history": h["tp_history"],
                "levels": h["levels"], "updates": sorted(ups, key=lambda u: u["ts"])}
    if pkg is None:
        # no package: the trade row's own levels are all there is
        opened = bh.parse_ts(trade.get("timestamp"))
        levels = [bh._level(k, _num(trade.get(col)), opened, None, "open", "",
                            "MEASURED" if _num(trade.get(col)) is not None else "UNVERIFIED")
                  for k, col in (("sl", "stop_loss"), ("tp", "take_profit_1"))]
        return {"read_state": "partial", "partial_reasons": ["no_order_package"], "tp_history": "unrecorded",
                "levels": levels, "updates": sorted(acct, key=lambda u: u["ts"])}
    h = bh.build_package_history(pkg, interval)
    ups = [dict(u, scope="package") for u in h["updates"]] + acct
    return {"read_state": h["read_state"], "partial_reasons": list(h["partial_reasons"]),
            "tp_history": h["tp_history"], "levels": h["levels"], "updates": sorted(ups, key=lambda u: u["ts"])}


def levels_outside(levels: List[Dict[str, Any]], lo: Optional[float], hi: Optional[float]) -> List[Dict[str, Any]]:
    if lo is None or hi is None:
        return []
    return [{"kind": lv["kind"], "price": lv["price"], "from_ts": lv["from_ts"]} for lv in levels
            if lv.get("price") is not None and not (lo <= lv["price"] <= hi)]


# ───────────────────────────────────────────── decisions (LTR reviews + directed-action receipts)

def applied_ids(notes: Dict[str, Any]) -> set:
    """Every review / directed record id that acted on this leg (mirrors live_review_apply.applied_review_ids,
    without its provenance filter: a directed record stamps its id the same way)."""
    ids = {str(a["review_id"]) for key in ("sl_amends", "live_review_actions")
           for a in (notes.get(key) or []) if isinstance(a, dict) and a.get("review_id")}
    fl = notes.get("sl_floor")
    if isinstance(fl, dict) and fl.get("review_id"):
        ids.add(str(fl["review_id"]))
    return ids


def _advice_only() -> Tuple[str, ...]:
    from src.runtime.live_review_rows import ADVICE_ONLY_ACTIONS
    return ADVICE_ONLY_ACTIONS


def review_disposition(row: Dict[str, Any], account_id: Any, applied: set) -> Tuple[str, Optional[str]]:
    rec = row.get("recommendation") if isinstance(row.get("recommendation"), dict) else {}
    action = rec.get("action")
    route = (row.get("disposition") or {}).get("route") if isinstance(row.get("disposition"), dict) else None
    read = next((a.get("read") for a in (row.get("account_reads") or [])
                 if isinstance(a, dict) and a.get("account_id") == account_id), None)
    if str(row.get("review_id")) in applied:
        return "applied", read
    if read and "refus" in str(read):
        return "refused", read
    if action in NO_ACTION:
        return "no_action", read
    if action in _advice_only():
        return "advice_only", read
    if route == "operator_ask":
        return "operator_ask", read
    if action == "flag_mechanics":
        return "no_action", read
    return "unknown", read


def _summary(row: Dict[str, Any]) -> Optional[str]:
    rec = row.get("recommendation") if isinstance(row.get("recommendation"), dict) else {}
    fc = row.get("forecast") if isinstance(row.get("forecast"), dict) else {}
    s = rec.get("basis") or fc.get("thesis")
    if isinstance(s, list):
        s = "; ".join(str(x) for x in s)
    return str(s)[:_SUMMARY_MAX] if s else None


def _in_window(ts: Optional[datetime], lo: Optional[datetime], hi: Optional[datetime]) -> bool:
    if ts is None:
        return False
    if lo is not None and ts < lo:
        return False
    return hi is None or ts <= hi


def _my_leg(legs: List[Dict[str, Any]], trade: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """This trade's entry in a receipt's ``accounts[]``: by trade id (exchange) or ticket id (prop), else the account
    when the entry names no other trade/ticket."""
    tid, tk, acct = trade.get("id"), trade.get("ticket_id"), trade.get("account_id")
    for a in legs:
        if (tid is not None and a.get("trade_id") == tid) or (tk and a.get("ticket_id") == tk):
            return a
    for a in legs:
        if a.get("account_id") == acct and a.get("trade_id") in (None, tid) and a.get("ticket_id") in (None, tk):
            return a
    return None


def decisions(trade: Dict[str, Any], interval: str, reviews: Dict[str, Any], receipts: Dict[str, Any],
              lo: Optional[datetime] = None, hi: Optional[datetime] = None) -> Dict[str, Any]:
    """``reviews`` / ``receipts`` = ``{"state": read|could_not_look|absent, "rows": [...]}``. ``lo``/``hi`` bound
    the markers to this leg's life (a package review after THIS account closed is not on its chart)."""
    pkg_id = trade.get("order_package_id")
    acct = trade.get("account_id")
    applied = applied_ids(_dict(trade.get("notes")))
    markers: List[Dict[str, Any]] = []
    for r in (reviews.get("rows") or []) if pkg_id else []:
        if not isinstance(r, dict) or r.get("order_package_id") != pkg_id:
            continue
        if r.get("trade_id") not in (None, trade.get("id")):
            continue
        ts = bh.parse_ts(r.get("reviewed_at"))
        if not _in_window(ts, lo, hi):
            continue
        rec = r.get("recommendation") if isinstance(r.get("recommendation"), dict) else {}
        disp, read = review_disposition(r, acct, applied)
        markers.append({"kind": "ltr_review", "id": r.get("review_id"), "ts": _iso(ts), "bar_ts": bh.bar_ts(ts, interval),
                        "action": rec.get("action"), "level": _num(rec.get("level")),
                        "confidence": _num(rec.get("confidence")), "summary": _summary(r),
                        "route": (r.get("disposition") or {}).get("route") if isinstance(r.get("disposition"), dict) else None,
                        "disposition": disp, "account_read": read})
    for d in (receipts.get("rows") or []) if pkg_id else []:
        if not isinstance(d, dict) or d.get("order_package_id") != pkg_id:
            continue
        ts = bh.parse_ts(d.get("done_at") or d.get("seen_at") or d.get("created_at"))
        if not _in_window(ts, lo, hi):
            continue
        legs = [a for a in (d.get("accounts") or []) if isinstance(a, dict)]
        mine = _my_leg(legs, trade)
        if legs and mine is None:
            continue   # scoped to another account / trade: not a decision on this leg
        mine = mine or {}
        if str(d.get("id")) in applied or mine.get("executed") or mine.get("read") == "applied":
            disp = "applied"
        elif d.get("verdict") == "dry_run" or d.get("dry_run") is True:
            disp = "dry_run"
        elif "refus" in str(mine.get("verdict") or "") or "refus" in str(d.get("verdict") or "") \
                or "refus" in str(mine.get("read") or ""):
            disp = "refused"
        else:
            disp = "unknown"
        markers.append({"kind": "directed_action", "id": d.get("id"), "ts": _iso(ts), "bar_ts": bh.bar_ts(ts, interval),
                        "action": d.get("resolved_action") or d.get("action"), "level": _num(d.get("level")),
                        "confidence": None, "summary": (str(d.get("directed_by"))[:_SUMMARY_MAX]
                                                        if d.get("directed_by") else None),
                        "route": "directed", "disposition": disp, "account_read": mine.get("read")})
    markers.sort(key=lambda m: m["ts"] or "")
    src = {"reviews": "read" if reviews.get("state") in ("read", "absent") else "could_not_look",
           "receipts": "read" if receipts.get("state") in ("read", "absent") else "could_not_look"}
    return {"read_state": "measured" if all(v == "read" for v in src.values()) else "partial",
            "sources": src, "markers": markers}


# ───────────────────────────────────────────── roll-up

def _rollup(parts: Dict[str, Any]) -> Tuple[str, List[str]]:
    reasons: List[str] = []
    b = parts.get("brackets") or {}
    if b.get("tp_history") == "unrecorded":
        reasons.append("tp_history_unrecorded")
    reasons += [r for r in b.get("partial_reasons") or []]
    if (parts.get("candles") or {}).get("state") not in (None, "measured"):
        reasons.append("candles_unavailable")
    if (parts.get("entry_signal") or {}).get("state") != "measured":
        reasons.append("entry_signal_unrecorded")
    for k, v in ((parts.get("decisions") or {}).get("sources") or {}).items():
        if v != "read":
            reasons.append(f"{k}_could_not_look")
    return ("partial" if reasons else "measured"), reasons


def build_markers(trade: Dict[str, Any], pkg: Optional[Dict[str, Any]], reviews: Dict[str, Any],
                  receipts: Dict[str, Any], interval: str, as_of: str) -> Dict[str, Any]:
    opened = bh.parse_ts(trade.get("timestamp"))
    closed = bh.parse_ts(trade.get("closed_at"))
    parts = {"entry": point(opened, trade.get("entry_price"), interval),
             "entry_signal": entry_signal(pkg, interval),
             "brackets": brackets(trade, pkg, interval),
             "decisions": decisions(trade, interval, reviews, receipts,
                                    lo=opened - timedelta(hours=1) if opened else None, hi=closed)}
    rs, reasons = _rollup(parts)
    return {"as_of": as_of, "trade_id": trade.get("id"), "prop_fill_id": trade.get("prop_fill_id"),
            "order_package_id": trade.get("order_package_id"),
            "account_id": trade.get("account_id"), "symbol": trade.get("symbol"), "direction": trade.get("direction"),
            "status": trade.get("status"), "interval": interval, "read_state": rs, "partial_reasons": reasons, **parts}


def build_snapshot(trade: Dict[str, Any], pkg: Optional[Dict[str, Any]], candles: Optional[List[Dict[str, Any]]],
                   candles_source: Optional[str], reviews: Dict[str, Any], receipts: Dict[str, Any],
                   built_at: datetime, pnl_provenance: Optional[str] = None) -> Dict[str, Any]:
    """The stored payload for one CLOSED trade. ``candles`` None = could not fetch (stored as ``unavailable``)."""
    opened = bh.parse_ts(trade.get("timestamp"))
    closed = bh.parse_ts(trade.get("closed_at"))
    if opened is None or closed is None:
        raise ValueError("trade has no open or close time")
    tf = time_frame(opened, closed)
    iv = tf["interval"]
    rows = [c for c in (candles or []) if tf["time_from"].timestamp() - bh._INTERVAL_S[iv] < c["time"]
            <= tf["time_to"].timestamp()]
    pf = price_frame(rows, opened, closed, (trade.get("entry_price"), trade.get("exit_price")))
    br = brackets(trade, pkg, iv)
    parts = {
        "candles": {"state": "measured" if rows else "unavailable", "source": candles_source,
                    "rows": rows if rows else None},
        "entry_signal": entry_signal(pkg, iv),
        "brackets": br,
        "decisions": decisions(trade, iv, reviews, receipts, lo=opened - timedelta(hours=1), hi=closed),
    }
    return {
        "schema": SCHEMA, "built_at": _iso(built_at), "trade": trade_block(trade, pnl_provenance),
        "frame": {"interval": iv, "time_from": _iso(tf["time_from"]), "time_to": _iso(tf["time_to"]),
                  "price_low": pf["price_low"], "price_high": pf["price_high"],
                  "basis": {"open_close_span_s": tf["open_close_span_s"], "time_pad_frac": TIME_PAD_FRAC,
                            "price_pad_frac": PRICE_PAD_FRAC, "high": pf["high"], "low": pf["low"],
                            "high_low_over": pf["high_low_over"], "min_window_applied": tf["min_window_applied"]},
                  "levels_outside_frame": levels_outside(br["levels"], pf["price_low"], pf["price_high"])},
        "candles": parts["candles"],
        "indicators": indicators(rows),
        "entry": point(opened, trade.get("entry_price"), iv),
        "exit": point(closed, trade.get("exit_price"), iv, reason=trade.get("exit_reason") or None),
        "entry_signal": parts["entry_signal"],
        "brackets": br,
        "decisions": parts["decisions"],
    }


def snapshot_read_state(payload: Dict[str, Any]) -> Tuple[str, List[str]]:
    return _rollup(payload)


def window_end(trade: Dict[str, Any]) -> Optional[datetime]:
    """When the framed window ends (close + 15% of the span, or the min-window pad): build no earlier."""
    opened = bh.parse_ts(trade.get("timestamp"))
    closed = bh.parse_ts(trade.get("closed_at"))
    if opened is None or closed is None:
        return None
    return time_frame(opened, closed)["time_to"]
