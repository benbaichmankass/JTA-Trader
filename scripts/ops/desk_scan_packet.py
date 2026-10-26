#!/usr/bin/env python3
# wiring: manual-only - a session-side builder run by the desk session (DESK-6) and the D-S0 replay
# (DESK-18), neither built yet; the VM read route that would schedule it is DESK-1.
"""DESK-16-SCAN-PACKETS -- build a desk SCAN packet (the entry-generation input).

Design: docs/plans/claude-trading-desk-DESIGN.md § 2.3 (the scan block table), § 3.9 (onboarding),
§ 4A (point-in-time, priced alternatives), § 4C (historical masked packets). Schema:
comms/schema/desk_packet.schema.json (kind `scan`, DESK-0B-SCHEMA-V2); every packet this builds is
validated by scripts/ci/check_desk_records.py's packet_problems() BEFORE it is returned or written,
and its `features_at_review` IS that guard's projection (one implementation, so the student trains on
exactly what the teacher saw).

READ-ONLY. No order path, no config write, no runtime change: it reads config/accounts.yaml and
config/strategies.yaml (the pull lists), candles, and the open-package book, and writes one JSON file
when asked (--out / --write). Tier 1.

WHAT EACH BLOCK IS, AND WHERE IT COMES FROM
* universe   -- the UNION pull list (src.config.symbol_sets.resolve_symbols mode UNION) over every
               account that trades; one full-tier row per symbol (venue = the first account in
               accounts.yaml order that pulls it; tradable_by = every account class that pulls it).
               Light-tier rows (venue-listed, not pulled) come from an injected listing; there is no
               reachable venue-listing source from a session today (Bybit's public API is geo-blocked
               here), so live packets name `universe.light_tier` in missing_inputs instead of
               pretending the venue lists nothing.
* system_book-- the strategies' open packages (scripts/ops/live_review_packet.collect, the same
               union of sources the live trade review uses) plus NEAR-SIGNALS from
               scripts/ops/desk_near_signals.py (DESK-16B; each rostered leg's own strategy unit run on
               its latest closed candles). `near_signals_read_state` is `read` only when EVERY rostered
               leg x symbol was looked at; otherwise it is could_not_look and the unlooked legs are
               named with the N-of-M denominator -- never an empty "none found".
* desk_book  -- the desk's own unresolved propose_entry rows (comms/desk/decisions.jsonl without an
               outcomes.jsonl row) inside their good_till window.
* history    -- per symbol x side x horizon: forward R = side * (close[t+h] - close[t]) / ATR14[t]
               minus the round-trip cost in R from execution_costs.roundtrip_cost_r with the
               venue-aware slippage/funding of execution_costs.resolve_cost_policy(symbol) and the
               venue fee of profile_loader.roundtrip_fee_bps_for (None -> DEFAULT_FEE_BPS_ROUNDTRIP).
               POINT IN TIME: only pairs whose forward close is itself before info_cutoff_at count,
               so the base rate never sees an outcome the desk could not have seen.
* ml         -- not read by this builder (no served-head read route for a scan yet): [] and
               `ml` named in missing_inputs.

HISTORICAL MODE (--as-of, always masked; design § 4C.2, distillation § 3.5.5). Every bar at or after
the cutoff is dropped before anything is computed. The packet is MASKED: symbols become aliases
(ASSET_01...), prices are rebased so each symbol's last close is 100, timestamps are anchored at
2000-01-01T00:00Z (the real cutoff is not in the packet), volume and calendar are withheld. The unmask
key (alias -> symbol, anchor -> real cutoff) is returned separately and written ONLY to
--mask-key-out: it must never sit beside the packet a desk session reads.

Usage:
  desk_scan_packet.py [--timeframe 1h] [--horizons 4,12,48] [--candles-dir DIR] [--out FILE | --write]
  desk_scan_packet.py --as-of 2026-03-02T12:00:00Z --candles-dir DIR --out FILE --mask-key-out KEY
  desk_scan_packet.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ci", REPO / "scripts" / "ops", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import check_desk_records as cdr  # noqa: E402  (the schema, the guard, the feature projection)
from src.runtime import execution_costs as xc  # noqa: E402

GENERATOR = "scripts/ops/desk_scan_packet.py"
PACKETS_DIR = REPO / "comms" / "desk" / "packets"
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
ATR_PERIOD = 14
SWING_BARS = 20
DEFAULT_HORIZONS = (4, 12, 48)
DEFAULT_LOOKBACK = 3000       # bars of history behind the base rates
N_FLOOR = 100                 # stated on the packet; below it a row is thin, not hidden
MASK_ANCHOR = datetime(2000, 1, 1, tzinfo=timezone.utc)
SIDES = (("long", 1.0), ("short", -1.0))

Bar = Dict[str, float]  # {"time": bar-open epoch seconds, "open", "high", "low", "close"}


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r6(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), 6)


# ----------------------------------------------------------------------------- universe (the pull lists)

def pulled_universe(accounts_cfg: Dict[str, dict], strategies_cfg: Dict[str, Any]) -> List[dict]:
    """[{symbol, venue, classes}] in accounts.yaml order: the UNION fetch set the tick uses."""
    from src.config.symbol_sets import UNION, resolve_symbols

    rows: Dict[str, dict] = {}
    for acct, a in accounts_cfg.items():
        if not isinstance(a, dict) or a.get("configured") is False:
            continue
        roster = a.get("strategies")
        if roster is not None and len(roster) == 0:
            continue  # explicit opt-out: the account trades nothing (src/main.py::_resolve_tick_symbols)
        for sym in resolve_symbols(declared=a.get("symbols"), roster=roster, mode=UNION,
                                   strategies_cfg=strategies_cfg, exchange=a.get("exchange")):
            r = rows.setdefault(sym, {"symbol": sym, "venue": a.get("exchange") or "unknown", "classes": []})
            cls = a.get("account_class")
            if cls in ("real_money", "prop", "paper", "soak") and cls not in r["classes"]:
                r["classes"].append(cls)
    return list(rows.values())


def venue_class(symbol: str, venue: str) -> str:
    return f"{venue}:{'perp' if xc.is_perp(symbol) else 'non_perp'}"


# ----------------------------------------------------------------------------- candles -> features

def closed_before(bars: Sequence[Bar], tf: str, cutoff: datetime) -> List[Bar]:
    """Bars fully closed at or before the cutoff, sorted, de-duplicated. The forming bar is dropped."""
    sec, cut = TF_SECONDS[tf], cutoff.timestamp()
    seen, out = set(), []
    for b in sorted(bars, key=lambda b: b["time"]):
        if b["time"] + sec <= cut and b["time"] not in seen:
            seen.add(b["time"])
            out.append(b)
    return out


def atr_series(bars: Sequence[Bar], period: int = ATR_PERIOD) -> List[Optional[float]]:
    """ATR[t] = SMA of the true range over the `period` bars ending at t (the strategies' ATR, and
    live_review_packet.atr_sma's definition). None until `period` true ranges exist."""
    out: List[Optional[float]] = [None] * len(bars)
    trs: List[float] = []
    run = 0.0
    for i in range(1, len(bars)):
        c, p = bars[i], bars[i - 1]
        tr = max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
        trs.append(tr)
        run += tr
        if len(trs) > period:
            run -= trs[-period - 1]
        if len(trs) >= period:
            out[i] = run / period
    return out


def htf_trend(bars: Sequence[Bar]) -> Optional[str]:
    """The live regime detector's trend label (src.runtime.regime.detector via live_review_packet)."""
    try:
        from live_review_packet import trend_now
    except Exception:  # allow-silent: the caller names the missing input
        return None
    return trend_now(list(bars))[0]


def session_of(t: datetime) -> str:
    h = t.astimezone(timezone.utc).hour
    return "asia" if h < 7 else "europe" if h < 13 else "us" if h < 21 else "late_us"


def _quantile(xs: List[float], q: float) -> float:
    """Nearest-rank quantile of a sorted list."""
    return xs[min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))]


def cost_policy(symbol: str) -> Tuple[float, float, float]:
    """(fee_bps_roundtrip, slippage_bps_roundtrip, funding_bps_per_window) -- the canonical policy."""
    try:
        from src.core.profile_loader import roundtrip_fee_bps_for
        fee = roundtrip_fee_bps_for(symbol)
    except Exception:  # allow-silent: an unknown venue keeps the conservative default, never zero
        fee = None
    slip, fund = xc.resolve_cost_policy(symbol)
    return (xc.DEFAULT_FEE_BPS_ROUNDTRIP if fee is None else float(fee)), slip, fund


def base_rates(symbol: str, tf: str, bars: Sequence[Bar], horizons: Iterable[int],
               lookback: int = DEFAULT_LOOKBACK) -> List[dict]:
    """Forward-R distribution per side x horizon, NET of the full cost stack, point in time:
    `bars` are already closed before the cutoff, so close[t+h] is a close the desk could have seen."""
    bars = list(bars)[-(lookback + max(horizons, default=0) + ATR_PERIOD + 1):]
    atr = atr_series(bars)
    fee, slip, fund = cost_policy(symbol)
    hours = TF_SECONDS[tf] / 3600.0
    rows = []
    for h in horizons:
        samples: Dict[str, List[float]] = {"long": [], "short": []}
        costs: List[float] = []
        for t in range(len(bars) - h):
            a = atr[t]
            if not a or a <= 0:
                continue
            c0, c1 = bars[t]["close"], bars[t + h]["close"]
            cost = xc.roundtrip_cost_r(entry=c0, exit_price=c1, risk=a, hold_hours=h * hours,
                                       fee_bps_roundtrip=fee, slippage_bps_roundtrip=slip,
                                       funding_bps_per_window=fund)["total_cost_r"]
            costs.append(cost)
            for side, sgn in SIDES:
                samples[side].append(sgn * (c1 - c0) / a - cost)
        for side, _ in SIDES:
            xs = sorted(samples[side])
            n = len(xs)
            if n == 0:
                stats = dict(mean_r=None, sd_r=None, p10_r=None, p50_r=None, p90_r=None, mean_cost_r=None)
            else:
                mu = sum(xs) / n
                sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
                stats = dict(mean_r=_r6(mu), sd_r=_r6(sd), p10_r=_r6(_quantile(xs, 0.10)),
                             p50_r=_r6(_quantile(xs, 0.50)), p90_r=_r6(_quantile(xs, 0.90)),
                             mean_cost_r=_r6(sum(costs) / len(costs)))
            rows.append({"symbol": symbol, "timeframe": tf, "side": side, "horizon_bars": int(h), "n": n, **stats})
    return rows


# ----------------------------------------------------------------------------- books

def system_book_from_snapshot(s: Any) -> List[dict]:
    """Open strategy packages from a live_review_packet.Snapshot (its union of open sources)."""
    from live_review_packet import _f, _json, _package_view, open_package_ids

    items = []
    for pkg in open_package_ids(s):
        v = _package_view(s, pkg)
        p, tel = v["package"] or {}, (v["telemetry"] or [{}])[0]
        tr0 = (v["trades"] or [{}])[0]
        side = p.get("direction") or tel.get("direction") or tr0.get("direction")
        items.append({"order_package_id": pkg,
                      "leg": p.get("strategy_name") or tel.get("strategy") or tr0.get("strategy_name") or "unknown",
                      "symbol": p.get("symbol") or tel.get("symbol") or tr0.get("symbol") or "unknown",
                      "side": side if side in ("long", "short") else None,
                      "timeframe": _json(p.get("meta")).get("timeframe") or tel.get("timeframe"),
                      "status": "open", "bars_to_signal": None,
                      "entry": _f(p.get("entry")) or _f(tel.get("entry")), "sl": _f(p.get("sl")), "tp": _f(p.get("tp"))})
    return items


def desk_book_from_records(decisions: Path, outcomes: Path, now: datetime) -> List[dict]:
    """Unresolved propose_entry rows (no outcome yet) still inside good_till_bars."""
    resolved = set()
    for _, r, err in cdr._rows(outcomes) if outcomes.exists() else []:
        if not err and isinstance(r, dict):
            resolved.add(r.get("decision_id"))
    items = []
    for _, r, err in cdr._rows(decisions) if decisions.exists() else []:
        if err or not isinstance(r, dict) or r.get("action") != "propose_entry" or r["decision_id"] in resolved:
            continue
        if r.get("label_source") not in ("live", "shadow"):
            continue
        pr = r["proposal"]
        until = cdr._ts(r["info_cutoff_at"]) + timedelta(seconds=TF_SECONDS.get(pr["timeframe"], 0) * pr["entry"]["good_till_bars"])
        if until > now:
            items.append({"decision_id": r["decision_id"], "order_package_id": None, "symbol": pr["symbol"],
                          "side": pr["side"], "status": "pending_proposal"})
    return items


# ----------------------------------------------------------------------------- the packet

def _missing_block(missing: List[str], key: str, why: str) -> None:
    missing.append(f"{key}: {why}")


def universe_row(sym: str, venue: str, classes: List[str], tf: str, bars: Optional[List[Bar]],
                 cutoff: datetime, missing: List[str], *, funding: Optional[float] = None,
                 spread_bps: Optional[float] = None, volume_24h: Optional[float] = None,
                 calendar: Optional[List[str]] = None) -> dict:
    tag = f"universe.{sym}"
    last = atr = None
    trend = None
    swing = {"read_state": "could_not_look", "high": None, "low": None, "dist_high_atr": None, "dist_low_atr": None}
    if not bars:
        _missing_block(missing, f"{tag}.last_close", f"no closed {tf} candles before the cutoff")
        _missing_block(missing, f"{tag}.atr", "no candles")
        _missing_block(missing, f"{tag}.swing", "no candles")
    else:
        last = bars[-1]["close"]
        atr = atr_series(bars)[-1]
        if atr is None:
            _missing_block(missing, f"{tag}.atr", f"fewer than {ATR_PERIOD + 1} closed bars")
        trend = htf_trend(bars)
        if trend is None:
            _missing_block(missing, f"{tag}.htf_trend", "regime detector unavailable or < 30 bars")
        w = bars[-SWING_BARS:]
        hi, lo = max(b["high"] for b in w), min(b["low"] for b in w)
        swing = {"read_state": "read", "high": hi, "low": lo,
                 "dist_high_atr": _r6((hi - last) / atr) if atr else None,
                 "dist_low_atr": _r6((last - lo) / atr) if atr else None}
    _missing_block(missing, f"{tag}.regime_cell", "the trend x vol cell is not computed by the scan builder yet")
    perp = xc.is_perp(sym)
    if not perp:
        fund = {"read_state": "not_applicable", "rate": None}
    elif funding is None:
        fund = {"read_state": "could_not_look", "rate": None}
        _missing_block(missing, f"{tag}.funding", "no point-in-time funding read")
    else:
        fund = {"read_state": "read", "rate": funding}
    if spread_bps is None:
        spread = {"read_state": "could_not_look", "bps": None}
        _missing_block(missing, f"{tag}.spread", "no order-book read")
    else:
        spread = {"read_state": "read", "bps": spread_bps}
    if calendar is None:
        cal = {"read_state": "could_not_look", "events_next_bar": None}
        _missing_block(missing, f"{tag}.calendar", "no point-in-time calendar read")
    else:
        cal = {"read_state": "read", "events_next_bar": calendar}
    return {"symbol": sym, "venue": venue, "venue_class": venue_class(sym, venue), "tier": "full",
            "tradable_by": classes, "timeframe": tf, "last_close": last, "atr": _r6(atr), "htf_trend": trend,
            "regime_cell": None, "funding": fund, "swing": swing, "session": session_of(cutoff),
            "calendar": cal, "spread": spread, "volume_24h": volume_24h}


def light_row(item: dict) -> dict:
    """A venue-listed symbol nobody pulls: ticker, 24h volume, spread only (design 2.3)."""
    na = {"read_state": "not_applicable"}
    bps = item.get("spread_bps")
    return {"symbol": item["symbol"], "venue": item["venue"], "venue_class": venue_class(item["symbol"], item["venue"]),
            "tier": "light", "tradable_by": [], "timeframe": None, "last_close": None, "atr": None,
            "htf_trend": None, "regime_cell": None, "funding": dict(na, rate=None),
            "swing": dict(na, high=None, low=None, dist_high_atr=None, dist_low_atr=None), "session": None,
            "calendar": dict(na, events_next_bar=None),
            "spread": {"read_state": "read" if bps is not None else "could_not_look", "bps": bps},
            "volume_24h": item.get("volume_24h")}


def build_scan_packet(*, cutoff: datetime, tf: str, universe: List[dict], candles: Dict[str, Optional[List[Bar]]],
                      horizons: Sequence[int] = DEFAULT_HORIZONS, lookback: int = DEFAULT_LOOKBACK,
                      system_book: Optional[List[dict]] = None, near_signals: Optional[List[dict]] = None,
                      desk_book: Optional[List[dict]] = None, light: Optional[List[dict]] = None,
                      extras: Optional[Dict[str, dict]] = None, built_at: Optional[datetime] = None,
                      mode: str = "live", unread_why: Optional[Dict[str, str]] = None,
                      near_signals_why: Optional[str] = None) -> dict:
    """Pure: everything is injected. `candles[symbol]` = bars of `tf` (any extent; bars at or after the
    cutoff are dropped here) or None when the read failed. `system_book` / `near_signals` /
    `desk_book` / `light` = None means could-not-look, [] means read-and-empty. `near_signals` comes from
    scripts/ops/desk_near_signals.py and is passed ONLY when every rostered leg x symbol was looked at (else None
    plus `near_signals_why`, which names the unlooked legs and the N-of-M denominator)."""
    if tf not in TF_SECONDS:
        raise ValueError(f"timeframe {tf!r} not in {sorted(TF_SECONDS)}")
    built_at = built_at or datetime.now(timezone.utc)
    missing: List[str] = []
    extras = extras or {}
    why = {"system_book": "open-package read failed", "desk_book": "desk records unreadable", **(unread_why or {})}
    rows, hist = [], []
    for u in universe:
        sym = u["symbol"]
        raw = candles.get(sym)
        bars = closed_before(raw, tf, cutoff) if raw else None
        if raw is None:
            _missing_block(missing, f"universe.{sym}.candles", "candle read failed")
        rows.append(universe_row(sym, u["venue"], u["classes"], tf, bars, cutoff, missing, **extras.get(sym, {})))
        if bars:
            hist += base_rates(sym, tf, bars, horizons, lookback)
    if light is None:
        _missing_block(missing, "universe.light_tier", "no venue-listing read: venue-listed symbols outside the pull lists are not shown")
    else:
        pulled = {r["symbol"] for r in rows}
        rows += [light_row(x) for x in light if x["symbol"] not in pulled]
    if system_book is None:
        sb = {"read_state": "could_not_look", "near_signals_read_state": "could_not_look", "items": None}
        _missing_block(missing, "system_book", why["system_book"])
        _missing_block(missing, "system_book.near_signals", "no open-package read")
    else:
        items = list(system_book)
        if near_signals is None:
            ns = "could_not_look"
            _missing_block(missing, "system_book.near_signals", near_signals_why or "not computed (pass near_signals from scripts/ops/desk_near_signals.py)")
        else:
            ns = "read"
            items += near_signals
        sb = {"read_state": "read", "near_signals_read_state": ns, "items": items}
    if desk_book is None:
        db = {"read_state": "could_not_look", "items": None}
        _missing_block(missing, "desk_book", why["desk_book"])
    else:
        db = {"read_state": "read", "items": desk_book}
    _missing_block(missing, "ml", "served heads are not read by the scan builder yet")
    hist_block = {"source": GENERATOR, "read_state": "read" if hist else "could_not_look",
                  "population": (f"per symbol: up to {lookback} closed {tf} bars before info_cutoff_at; "
                                 f"pairs whose forward close is also before the cutoff") if hist else None,
                  "n_floor": N_FLOOR, "net_of_full_cost_stack": True if hist else None,
                  "cost_policy": ("execution_costs.resolve_cost_policy(symbol) slippage+funding, "
                                  "profile_loader.roundtrip_fee_bps_for fee (None -> DEFAULT_FEE_BPS_ROUNDTRIP)") if hist else None,
                  "r_unit": "atr_stop_1x", "rows": hist}
    if not hist:
        _missing_block(missing, "history", "no symbol had candles for base rates")
    stamp = cutoff.strftime("%Y%m%dT%H%MZ")
    p = {"schema_version": 2,
         "meta": {"packet_id": f"DP-{stamp}-scan-{tf}", "packet_kind": "scan", "packet_version": 3, "mode": mode,
                  "built_at": _iso(max(built_at, cutoff)), "info_cutoff_at": _iso(cutoff),
                  "generator": GENERATOR, "missing_inputs": missing},
         "universe": rows, "system_book": sb, "desk_book": db, "history": hist_block, "ml": []}
    p["features_at_review"] = cdr.project_scan_features(p)
    return p


# ----------------------------------------------------------------------------- masking (historical mode)

def mask_packet(p: dict) -> Tuple[dict, dict]:
    """(masked packet, unmask key). Symbols -> ASSET_nn, prices rebased so each last close is 100,
    time anchored at MASK_ANCHOR, volume/calendar withheld. R-unit fields (ATR distances, base rates)
    are scale-free and kept. The key never travels with the packet."""
    m = json.loads(json.dumps(p))
    real_cut = m["meta"]["info_cutoff_at"]
    alias = {u["symbol"]: f"ASSET_{i + 1:02d}" for i, u in enumerate(m["universe"])}
    m["meta"]["mode"] = "historical_masked"
    m["meta"]["info_cutoff_at"] = m["meta"]["built_at"] = _iso(MASK_ANCHOR)
    digest = hashlib.sha256(f"{real_cut}|{m['universe'] and m['universe'][0]['symbol']}".encode()).hexdigest()[:10]
    m["meta"]["packet_id"] = f"DP-{MASK_ANCHOR.strftime('%Y%m%dT%H%MZ')}-scan-{digest}"
    miss = []
    for x in m["meta"]["missing_inputs"]:
        for s, a in alias.items():
            x = x.replace(f"universe.{s}.", f"universe.{a}.")
        miss.append(x)
    scale = {}
    for u in m["universe"]:
        s, a = u["symbol"], alias[u["symbol"]]
        f = 100.0 / u["last_close"] if u["last_close"] else None
        scale[s] = f
        u["symbol"] = a
        u["venue"] = "masked"
        u["venue_class"] = "masked:" + u["venue_class"].split(":")[-1]
        if f is not None:
            u["last_close"] = 100.0
            u["atr"] = _r6(u["atr"] * f) if u["atr"] is not None else None
            for k in ("high", "low"):
                if u["swing"][k] is not None:
                    u["swing"][k] = _r6(u["swing"][k] * f)
        if u["volume_24h"] is not None:
            u["volume_24h"] = None
            miss.append(f"universe.{a}.volume_24h: masked")
        if u["calendar"]["read_state"] == "read":
            u["calendar"] = {"read_state": "could_not_look", "events_next_bar": None}
            miss.append(f"universe.{a}.calendar: masked (event names date the packet)")
    for r in m["history"]["rows"]:
        r["symbol"] = alias.get(r["symbol"], r["symbol"])
    for book in ("system_book", "desk_book"):
        for it in m[book]["items"] or []:
            sym = it["symbol"]
            it["symbol"] = alias.get(sym, "ASSET_XX")
            if book == "system_book":
                it["order_package_id"] = None if it["status"] == "near_signal" else "masked"
                for k in ("entry", "sl", "tp"):
                    if it[k] is not None and scale.get(sym):
                        it[k] = _r6(it[k] * scale[sym])
    m["meta"]["missing_inputs"] = miss
    m["history"]["population"] = "masked: up to the lookback of closed bars before the cutoff"
    m["features_at_review"] = cdr.project_scan_features(m)
    key = {"packet_id": m["meta"]["packet_id"], "real_info_cutoff_at": real_cut,
           "alias": {a: s for s, a in alias.items()}, "price_scale": {alias[s]: f for s, f in scale.items()}}
    return m, key


# ----------------------------------------------------------------------------- IO (CLI only)

def _bars_from_df(df) -> List[Bar]:
    out = []
    for _, r in df.iterrows():
        out.append({"time": int(r["timestamp"].timestamp()), "open": float(r["open"]), "high": float(r["high"]),
                    "low": float(r["low"]), "close": float(r["close"])})
    return out


def candles_from_dir(d: Path, symbols: Iterable[str], tf: str) -> Dict[str, Optional[List[Bar]]]:
    """<SYMBOL>_<tf>.{csv,jsonl,parquet} via the repo's ONE candle reader (scripts/candle_io.py)."""
    import candle_io

    out: Dict[str, Optional[List[Bar]]] = {}
    for s in symbols:
        f = next((d / f"{s}_{tf}.{ext}" for ext in ("csv", "jsonl", "parquet") if (d / f"{s}_{tf}.{ext}").exists()), None)
        try:
            out[s] = _bars_from_df(candle_io.load_candles(str(f))) if f else None
        except Exception:  # allow-silent: a failed read is None -> named in missing_inputs
            out[s] = None
    return out


def candles_from_api(symbols: Iterable[str], tf: str, limit: int = 1000) -> Dict[str, Optional[List[Bar]]]:
    """The bot's public candle route (the one live_review_packet reads)."""
    from live_review_packet import _public

    out: Dict[str, Optional[List[Bar]]] = {}
    for s in symbols:
        try:
            d = _public(f"api/bot/candles?symbol={s}&interval={tf}&limit={limit}")
            out[s] = d.get("candles") or None if not d.get("error") else None
        except Exception:  # allow-silent: named in missing_inputs
            out[s] = None
    return out


def _load_cfg() -> Tuple[Dict[str, dict], Dict[str, Any]]:
    from src.config.accounts_loader import load_accounts_dict
    from src.config.symbol_sets import load_strategies_cfg

    return load_accounts_dict(), load_strategies_cfg()


def validate(p: dict) -> List[str]:
    return cdr.packet_problems(p, json.loads(cdr.PACKET_SCHEMA.read_text()))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--horizons", default=",".join(map(str, DEFAULT_HORIZONS)))
    ap.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK)
    ap.add_argument("--candles-dir", type=Path)
    ap.add_argument("--as-of", help="historical mode (always masked): ISO cutoff")
    ap.add_argument("--symbols", help="comma list: restrict the pulled universe (testing / a sampled offline run)")
    ap.add_argument("--no-system-book", action="store_true", help="skip the open-package read (could_not_look)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--write", action="store_true", help="live mode: write comms/desk/packets/<packet_id>.json")
    ap.add_argument("--mask-key-out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    tf, horizons = a.timeframe, [int(x) for x in a.horizons.split(",") if x]
    historical = a.as_of is not None
    if historical and not a.mask_key_out:
        ap.error("--as-of requires --mask-key-out (the unmask key never travels with the packet)")
    if historical and a.write:
        ap.error("--write is for live packets; a historical packet goes to --out")
    cutoff = (datetime.fromisoformat(a.as_of.replace("Z", "+00:00")) if historical
              else datetime.now(timezone.utc).replace(second=0, microsecond=0))
    acc, strat = _load_cfg()
    uni = pulled_universe(acc, strat)
    if a.symbols:
        keep = set(a.symbols.split(","))
        uni = [u for u in uni if u["symbol"] in keep]
    syms = [u["symbol"] for u in uni]
    candles = candles_from_dir(a.candles_dir, syms, tf) if a.candles_dir else candles_from_api(syms, tf)
    sb, ns, ns_why = None, None, None
    if not historical and not a.no_system_book:
        try:
            import desk_near_signals

            res = desk_near_signals.live_near_signals(cutoff, a.candles_dir)
            print(f"desk_scan_packet: near-signals: {res['denominator']}; read_state={res['read_state']}", file=sys.stderr)
            ns, ns_why = (res["items"], None) if res["read_state"] == "read" else (None, res["missing"])
        except Exception as exc:  # allow-silent: could_not_look, named in missing_inputs
            print(f"desk_scan_packet: near-signal read failed: {exc}", file=sys.stderr)
            ns_why = f"near-signal producer failed: {type(exc).__name__}: {str(exc)[:120]}"
        try:
            from live_review_packet import collect
            sb = system_book_from_snapshot(collect(max_pages=1))
        except Exception as exc:  # allow-silent: could_not_look, named in missing_inputs
            print(f"desk_scan_packet: system book read failed: {exc}", file=sys.stderr)
    db = None if historical else desk_book_from_records(cdr.DECISIONS, cdr.OUTCOMES, cutoff)
    unread = ({"system_book": "not reconstructed point in time (historical mode)",
               "desk_book": "not reconstructed point in time (historical mode)"} if historical
              else {"system_book": "skipped (--no-system-book)"} if a.no_system_book else None)
    p = build_scan_packet(cutoff=cutoff, tf=tf, universe=uni, candles=candles, horizons=horizons,
                          lookback=a.lookback, system_book=sb, near_signals=ns, desk_book=db, unread_why=unread,
                          near_signals_why=ns_why)
    key = None
    if historical:
        p, key = mask_packet(p)
    problems = validate(p)
    if problems:
        print("desk_scan_packet: REFUSED -- the packet fails desk-records-guard:", file=sys.stderr)
        for x in problems:
            print(f"  ✗ {x}", file=sys.stderr)
        return 1
    text = json.dumps(p, indent=1, sort_keys=True) + "\n"
    dest = (PACKETS_DIR / f"{p['meta']['packet_id']}.json") if a.write else a.out
    if dest:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
        print(f"desk_scan_packet: wrote {dest} (sha {cdr.packet_sha(p)[:12]}; {len(p['universe'])} symbols, "
              f"{len(p['history']['rows'])} base-rate rows, {len(p['meta']['missing_inputs'])} missing inputs)")
    else:
        sys.stdout.write(text)
    if key is not None:
        a.mask_key_out.parent.mkdir(parents=True, exist_ok=True)
        a.mask_key_out.write_text(json.dumps(key, indent=1, sort_keys=True) + "\n")
    return 0


# ----------------------------------------------------------------------------- self-test

def _walk(n: int, start: float, step: float, t0: int, sec: int, seed: int = 7) -> List[Bar]:
    """Deterministic synthetic bars (a test fixture only; never a packet input outside --self-test)."""
    import random

    rnd = random.Random(seed)
    out, px = [], start
    for i in range(n):
        o = px
        c = max(0.01, o + rnd.uniform(-1.0, 1.0) * step + step * 0.05)
        out.append({"time": t0 + i * sec, "open": o, "high": max(o, c) + step * 0.3,
                    "low": min(o, c) - step * 0.3, "close": c})
        px = c
    return out


def _self_test() -> int:
    ok = True

    def expect(label: str, cond: bool) -> None:
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        ok &= bool(cond)

    sec = TF_SECONDS["1h"]
    t0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    bars = _walk(600, 100.0, 1.0, t0, sec)
    cutoff = datetime.fromtimestamp(t0 + 500 * sec, tz=timezone.utc)
    uni = [{"symbol": "ETHUSDT", "venue": "bybit", "classes": ["paper", "real_money"]},
           {"symbol": "SPY", "venue": "alpaca", "classes": ["paper"]},
           {"symbol": "NODATA", "venue": "bybit", "classes": ["paper"]}]
    sb = [{"order_package_id": "pkg-1", "leg": "example", "symbol": "ETHUSDT", "side": "long", "timeframe": "4h",
           "status": "open", "bars_to_signal": None, "entry": 100.0, "sl": 95.0, "tp": 110.0}]
    p = build_scan_packet(cutoff=cutoff, tf="1h", universe=uni, candles={"ETHUSDT": bars, "SPY": bars, "NODATA": None},
                          horizons=(4, 12), lookback=300, system_book=sb, desk_book=[],
                          light=[{"symbol": "NEWUSDT", "venue": "bybit", "volume_24h": 1e6, "spread_bps": 8.0}],
                          built_at=cutoff + timedelta(seconds=30))
    expect("a live scan packet passes desk-records-guard", validate(p) == [])
    expect("features_at_review is the guard's projection", p["features_at_review"] == cdr.project_scan_features(p))
    eth = next(u for u in p["universe"] if u["symbol"] == "ETHUSDT")
    expect("last_close is the last bar CLOSED before the cutoff (bar 499), not one after",
           eth["last_close"] == bars[499]["close"])
    expect("a non-perp's funding is not_applicable", next(u for u in p["universe"] if u["symbol"] == "SPY")["funding"]["read_state"] == "not_applicable")
    expect("a failed candle read is null AND named, never zero",
           next(u for u in p["universe"] if u["symbol"] == "NODATA")["last_close"] is None
           and any(m.startswith("universe.NODATA.last_close") for m in p["meta"]["missing_inputs"]))
    expect("the light tier carries only ticker, volume and spread",
           next(u for u in p["universe"] if u["symbol"] == "NEWUSDT")["atr"] is None)
    expect("near-signals not passed are could_not_look and named, not an empty read",
           p["system_book"]["near_signals_read_state"] == "could_not_look"
           and any(m.startswith("system_book.near_signals") for m in p["meta"]["missing_inputs"]))
    ns_item = {"order_package_id": None, "leg": "example_trend_1d", "symbol": "ETHUSDT", "side": "long", "timeframe": "1d",
               "status": "near_signal", "bars_to_signal": 1, "entry": None, "sl": None, "tp": None}
    pn = build_scan_packet(cutoff=cutoff, tf="1h", universe=uni[:1], candles={"ETHUSDT": bars}, horizons=(4,), lookback=300,
                           system_book=sb, near_signals=[ns_item], desk_book=[], built_at=cutoff)
    expect("injected near-signals read: items on the system book, guard-valid, counted in the features",
           pn["system_book"]["near_signals_read_state"] == "read" and validate(pn) == []
           and pn["features_at_review"]["n_near_signals"] == 1)
    pw = build_scan_packet(cutoff=cutoff, tf="1h", universe=uni[:1], candles={"ETHUSDT": bars}, horizons=(4,), lookback=300,
                           system_book=sb, near_signals=None, desk_book=[], built_at=cutoff,
                           near_signals_why="25 of 27 rostered leg x symbol looked; not looked: a/B (no candles)")
    expect("a partial near-signal look names the denominator and the unlooked legs",
           validate(pw) == [] and any(m.startswith("system_book.near_signals") and "25 of 27" in m for m in pw["meta"]["missing_inputs"]))
    rows = {(r["symbol"], r["side"], r["horizon_bars"]): r for r in p["history"]["rows"]}
    expect("base rates per symbol x side x horizon", len(rows) == 2 * 2 * 2)
    r = rows[("ETHUSDT", "long", 4)]
    s = rows[("ETHUSDT", "short", 4)]
    expect("long and short pay the SAME cost (mean_long + mean_short = -2 x mean_cost)",
           abs((r["mean_r"] + s["mean_r"]) + 2 * r["mean_cost_r"]) < 1e-5)
    expect("costs are charged (mean_cost_r > 0, net of the full cost stack)", r["mean_cost_r"] > 0)
    expect("SPY's cost is not the perp policy (non-perp slippage, commission-free fee resolves)",
           rows[("SPY", "long", 4)]["mean_cost_r"] != r["mean_cost_r"])
    # point in time: bars after the cutoff must not move any number
    shocked = bars[:500] + [dict(b, close=b["close"] * 3, high=b["high"] * 3) for b in bars[500:]]
    p2 = build_scan_packet(cutoff=cutoff, tf="1h", universe=uni, candles={"ETHUSDT": shocked, "SPY": bars, "NODATA": None},
                           horizons=(4, 12), lookback=300, system_book=sb, desk_book=[],
                           light=[{"symbol": "NEWUSDT", "venue": "bybit", "volume_24h": 1e6, "spread_bps": 8.0}],
                           built_at=cutoff + timedelta(seconds=30))
    expect("POINT IN TIME: rewriting every bar after the cutoff changes nothing", cdr.packet_sha(p) == cdr.packet_sha(p2))
    # a forward close on the cutoff boundary: n counts only pairs fully before the cutoff
    kept = min(500, 300 + 12 + ATR_PERIOD + 1)  # closed bars before the cutoff, trimmed to the lookback window
    expect("n counts only (t, t+h) pairs whose forward close is before the cutoff, with an ATR at t",
           r["n"] == kept - 4 - ATR_PERIOD and rows[("ETHUSDT", "long", 12)]["n"] == kept - 12 - ATR_PERIOD)
    # could-not-look books
    p3 = build_scan_packet(cutoff=cutoff, tf="1h", universe=uni[:1], candles={"ETHUSDT": bars}, horizons=(4,),
                           lookback=300, system_book=None, desk_book=None, built_at=cutoff)
    expect("unread system/desk books are null, named and still guard-valid",
           p3["system_book"]["items"] is None and p3["desk_book"]["items"] is None and validate(p3) == [])
    # masking
    m, key = mask_packet(p)
    blob = json.dumps(m)
    expect("a masked packet passes desk-records-guard", validate(m) == [])
    expect("masked: no real symbol appears anywhere in the packet",
           not any(s in blob for s in ("ETHUSDT", "SPY", "NEWUSDT", "NODATA")))
    expect("masked: no real date appears (the cutoff is anchored)", "2026-" not in blob and m["meta"]["mode"] == "historical_masked")
    meth = next(u for u in m["universe"] if key["alias"][u["symbol"]] == "ETHUSDT")
    expect("masked: prices rebased (every last close 100 or null), R-unit distances unchanged",
           all(u["last_close"] in (100.0, None) for u in m["universe"])
           and meth["swing"]["dist_high_atr"] == eth["swing"]["dist_high_atr"])
    expect("masked: base rates are unchanged (scale-free R)",
           [x["mean_r"] for x in m["history"]["rows"]] == [x["mean_r"] for x in p["history"]["rows"]])
    expect("the unmask key maps every alias back and holds the real cutoff",
           set(key["alias"].values()) == {"ETHUSDT", "SPY", "NODATA", "NEWUSDT"} and key["real_info_cutoff_at"] == p["meta"]["info_cutoff_at"])
    # CLI refuses an unmasked historical packet path without a key file
    try:
        main(["--as-of", "2026-01-02T00:00:00Z", "--out", "/dev/null"])
        expect("--as-of without --mask-key-out is refused", False)
    except SystemExit as e:
        expect("--as-of without --mask-key-out is refused", e.code == 2)
    # the CLI's candle-dir reader goes through scripts/candle_io.py and yields bars
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "ETHUSDT_1h.csv"
        f.write_text("timestamp,open,high,low,close\n" + "".join(
            f"{datetime.fromtimestamp(b['time'], tz=timezone.utc).isoformat()},{b['open']},{b['high']},{b['low']},{b['close']}\n"
            for b in bars[:50]))
        got = candles_from_dir(Path(d), ["ETHUSDT", "MISSING"], "1h")
        expect("candles_from_dir reads a candle_io CSV into bars (and None for an absent file)",
               got["MISSING"] is None and got["ETHUSDT"] is not None and len(got["ETHUSDT"]) == 50
               and got["ETHUSDT"][0]["time"] == bars[0]["time"] and abs(got["ETHUSDT"][-1]["close"] - bars[49]["close"]) < 1e-9)
    # desk book from records
    with tempfile.TemporaryDirectory() as d:
        dec, oc = Path(d) / "decisions.jsonl", Path(d) / "outcomes.jsonl"
        e = cdr.GOOD_ENTRY_DECISION
        dec.write_text(json.dumps(e) + "\n")
        oc.write_text("")
        now = cdr._ts(e["info_cutoff_at"]) + timedelta(hours=1)
        expect("an unresolved shadow proposal inside good_till is on the desk book",
               [i["decision_id"] for i in desk_book_from_records(dec, oc, now)] == [e["decision_id"]])
        expect("...and off it once good_till_bars has passed", desk_book_from_records(dec, oc, now + timedelta(hours=5)) == [])
        oc.write_text(json.dumps(cdr.GOOD_OUTCOME) + "\n")
        expect("...and off it once an outcome row exists", desk_book_from_records(dec, oc, now) == [])
    # the pulled universe follows the UNION rule and skips opted-out accounts
    acc = {"a1": {"exchange": "bybit", "account_class": "paper", "symbols": ["BTCUSDT"], "strategies": ["leg_x"]},
           "a2": {"exchange": "alpaca", "account_class": "real_money", "symbols": ["SPY"], "strategies": []},
           "a3": {"exchange": "bybit", "account_class": "real_money", "symbols": ["BTCUSDT"], "strategies": None}}
    u = pulled_universe(acc, {"leg_x": {"symbols": ["SOLUSDT"]}})
    expect("universe = UNION(declared, roster-implied); an opted-out account contributes nothing",
           [x["symbol"] for x in u] == ["BTCUSDT", "SOLUSDT"] and u[0]["classes"] == ["paper", "real_money"])
    print("desk_scan_packet self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
