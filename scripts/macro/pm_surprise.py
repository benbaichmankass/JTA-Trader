#!/usr/bin/env python3
# wiring: library for scripts/research/pm_surprise_eval.py (queue unit RQ-20261009-903) and scripts/macro/econ_event_study.py --pm-surprise; no timer, no service.
"""PM-SURPRISE-JOIN — prediction-market-implied expectation → PM-surprise, per macro release.

Turns the off-repo, trainer-resident Kalshi backfill (``<data_dir>/pm_backfill/kalshi/{KXCPI,KXPAYROLLS,
KXFEDDECISION}.jsonl``, written by ``scripts/research/pm_backfill_kalshi.py``) into ONE derived number per
release:

    pm_expected  = the expectation implied by the LAST usable two-sided yes bid/ask mid with
                   ``candle_end_utc <= close_time`` (no lookahead possible: later candles are never read)
    pm_surprise  = realized - pm_expected     (same sign convention as the calendar's ``surprise``)

* CPI / NFP: strike ladder of ``greater`` markets, S_k = P(X > k). Probability-weighted expectation over the
  bins the ladder cuts the line into (``ladder_expectation``). NFP strikes are in JOBS, the calendar is in
  THOUSANDS, so ``KIND_SPEC['nfp'].scale`` converts.
* FOMC: the hike / cut ladder (``H0``, ``H25``, ``C25`` ...) → implied rate change in bps (``fomc_expected_bps``).

Third-party data (terms unread, operator 2026-10-08) stays off-repo: this module only returns derived numbers;
callers commit derived scorecards, never quotes.

Definitions that the registered rule leaves open, fixed HERE and echoed into every scorecard:
  * "two-sided" = bid and ask both reported, 0 <= bid <= ask <= 1, spread <= ``MAX_SPREAD`` (a settled/empty
    book reads bid 0 / ask 1.0 — that is NOT a quote and is skipped, so the last USABLE quote is used).
  * ladder coherence: a market whose own last usable quote is older than ``LADDER_STALE_HOURS`` before the
    event's freshest quote is dropped from that event's ladder.
  * the exact release-date join key is the UTC DATE of the market's ``close_time`` against the calendar's
    ``scheduled_for``.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

MAX_SPREAD = 0.30
LADDER_STALE_HOURS = 6.0
MIN_STRIKES = 3
#: sum of FOMC outcome mids must be near 1 for the ladder to be read as a distribution
FOMC_MASS_BAND = (0.85, 1.15)
#: ">25bps" markets (suffix 26): representative size, an ASSUMPTION (cap of one further step)
FOMC_BEYOND_25_BPS = 50.0

#: backfill series → (calendar kind, ladder unit scale to calendar units, tick of the printed value)
KIND_SPEC: Dict[str, Dict[str, Any]] = {
    "KXCPI": {"kind": "cpi_mom", "scale": 1.0, "tick": 0.1},
    "KXPAYROLLS": {"kind": "nfp", "scale": 1e-3, "tick": 0.0},
    "KXFEDDECISION": {"kind": "fomc", "scale": 1.0, "tick": 0.0},
}


def _ts(iso: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln:
                out.append(json.loads(ln))
    return out


def usable_mid(row: Dict[str, Any], max_spread: float = MAX_SPREAD) -> Optional[float]:
    """Yes mid at the candle close, or None when the book is not a two-sided, sane quote."""
    bid, ask = row.get("yes_bid_close"), row.get("yes_ask_close")
    if bid is None or ask is None:
        return None
    bid, ask = float(bid), float(ask)
    if not (0.0 <= bid <= ask <= 1.0) or (ask - bid) > max_spread:
        return None
    return (bid + ask) / 2.0


def last_quotes(rows: Iterable[Dict[str, Any]], close_time: str) -> Dict[str, Tuple[str, float, Dict[str, Any]]]:
    """market_id → (candle_end_utc, mid, row): each market's LAST usable quote with candle_end_utc <= close_time."""
    cutoff = _ts(close_time)
    best: Dict[str, Tuple[str, float, Dict[str, Any]]] = {}
    for r in rows:
        ce = r.get("candle_end_utc")
        if not ce or _ts(ce) > cutoff:
            continue  # the lookahead guard: a later candle is never read
        mid = usable_mid(r)
        if mid is None:
            continue
        cur = best.get(r["market_id"])
        if cur is None or ce > cur[0]:
            best[r["market_id"]] = (ce, mid, r)
    return best


def _coherent(quotes: Dict[str, Tuple[str, float, Dict[str, Any]]]) -> Tuple[Dict[str, Tuple[str, float, Dict[str, Any]]], Optional[str]]:
    if not quotes:
        return {}, None
    latest = max(q[0] for q in quotes.values())
    floor = _ts(latest) - _dt.timedelta(hours=LADDER_STALE_HOURS)
    return {m: q for m, q in quotes.items() if _ts(q[0]) >= floor}, latest


def ladder_expectation(strikes: List[Tuple[float, float]], tick: float = 0.0) -> Optional[Dict[str, float]]:
    """E[X] from survival points ``[(k, P(X > k)), ...]``.

    P is made monotone non-increasing in k (running min — quote noise, not information). Bins: (-inf,k1], (k1,k2]
    ... (km,+inf); the two tails are closed with the adjacent bin width. A bin (a, b] is represented by the
    mean of the printed grid values it holds, (a + b + tick) / 2 (tick = 0 for a continuous variable);
    a constant offset like this cannot move a rank IC. Needs >= MIN_STRIKES distinct strikes."""
    pts = sorted({k: p for k, p in strikes}.items())
    if len(pts) < MIN_STRIKES:
        return None
    ks = [k for k, _ in pts]
    s: List[float] = []
    run = 1.0
    for _, p in pts:
        run = min(run, max(0.0, min(1.0, p)))
        s.append(run)
    w_lo, w_hi = ks[1] - ks[0], ks[-1] - ks[-2]
    edges = [ks[0] - w_lo] + ks + [ks[-1] + w_hi]
    mass = [1.0 - s[0]] + [s[i] - s[i + 1] for i in range(len(s) - 1)] + [s[-1]]
    total = sum(mass)  # == 1 by construction
    mean = sum(m * (edges[i] + edges[i + 1] + tick) / 2.0 for i, m in enumerate(mass))
    return {"expected": mean / total, "n_strikes": float(len(ks)), "tail_lo_mass": mass[0], "tail_hi_mass": mass[-1]}


_FOMC_RE = re.compile(r"-(H|C)(\d+)$")


def fomc_delta_bps(market_id: str) -> Optional[float]:
    """Signed rate change (bps) a FEDDECISION market resolves YES on. ``H0`` hold, ``H25``/``H50`` hike, ``C25``
    cut; suffix 26 is the ">25bps" market (FOMC_BEYOND_25_BPS). Unrecognised suffixes (e.g. ``TC25``) → None."""
    m = _FOMC_RE.search(market_id)
    if not m:
        return None
    side, n = m.group(1), int(m.group(2))
    size = FOMC_BEYOND_25_BPS if n == 26 else float(n)
    return 0.0 if size == 0 else (size if side == "H" else -size)


def fomc_expected_bps(quotes: Dict[str, Tuple[str, float, Dict[str, Any]]]) -> Optional[Dict[str, float]]:
    """Probability-weighted implied rate change (bps) from the hold / hike / cut ladder, mids normalised to sum 1.
    Refused (None) when the mids do not look like a distribution (sum outside FOMC_MASS_BAND) or no hold market."""
    pts = [(fomc_delta_bps(m), q[1]) for m, q in quotes.items()]
    pts = [(d, p) for d, p in pts if d is not None]
    if len(pts) < 3 or not any(d == 0.0 for d, _ in pts):
        return None
    tot = sum(p for _, p in pts)
    if not (FOMC_MASS_BAND[0] <= tot <= FOMC_MASS_BAND[1]):
        return None
    return {"expected": sum(d * p for d, p in pts) / tot, "n_strikes": float(len(pts)), "mass": tot}


def parse_expiration_value(series: str, text: Any) -> Optional[float]:
    """Kalshi's own settled value, in CALENDAR units — a cross-check on the calendar's ``actual``, never the
    realized used in the surprise. CPI '0.4' → 0.4; NFP '29,000' → 29.0; FOMC 'Hike 25bps' → +25."""
    if text is None:
        return None
    t = str(text).strip()
    if series == "KXFEDDECISION":
        m = re.search(r"(\d+)\s*bps", t, re.I)
        if t.lower().startswith("hold") or "no change" in t.lower():
            return 0.0
        if not m:
            return None
        v = float(m.group(1))
        return -v if t.lower().startswith("cut") else v
    try:
        return float(t.replace(",", "")) * KIND_SPEC[series]["scale"]
    except (ValueError, KeyError):
        return None


def build_series(series: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One record per event in a backfill series: ``{series, kind, event_ticker, date, close_time, as_of,
    stale_hours, pm_expected, n_strikes, kalshi_settled}`` or ``skipped`` with a ``reason``.

    ``date`` is the UTC date of ``close_time`` — the exact-join key. ``stale_hours`` is close_time minus the
    freshest usable quote in the ladder."""
    spec = KIND_SPEC[series]
    by_event: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_event.setdefault(r["event_ticker"], []).append(r)
    out: List[Dict[str, Any]] = []
    for ev in sorted(by_event, key=lambda e: min(r["close_time"] for r in by_event[e])):
        rs = by_event[ev]
        close = min(r["close_time"] for r in rs)
        rec: Dict[str, Any] = {"series": series, "kind": spec["kind"], "event_ticker": ev, "date": close[:10],
                               "close_time": close, "pm_expected": None}
        quotes, latest = _coherent(last_quotes(rs, close))
        sv = next((parse_expiration_value(series, r.get("expiration_value")) for r in rs
                   if r.get("expiration_value") not in (None, "")), None)
        rec["kalshi_settled"] = sv
        if not quotes:
            rec.update(skipped=True, reason="no_usable_two_sided_quote")
            out.append(rec)
            continue
        if series == "KXFEDDECISION":
            res = fomc_expected_bps(quotes)
        else:
            strikes = [(float(q[2]["floor_strike"]) * spec["scale"], q[1]) for q in quotes.values()
                       if q[2].get("strike_type") == "greater" and q[2].get("floor_strike") is not None]
            res = ladder_expectation(strikes, tick=spec["tick"])
        if res is None:
            rec.update(skipped=True, reason="ladder_too_thin_or_incoherent")
        else:
            rec.update(skipped=False, pm_expected=res["expected"], n_strikes=int(res["n_strikes"]),
                       as_of=latest,
                       stale_hours=(_ts(close) - _ts(latest)).total_seconds() / 3600.0)
        out.append(rec)
    return out


def realized_for(kind: str, ev: Dict[str, Any]) -> Optional[float]:
    """Realized outcome in the units of ``pm_expected`` from a calendar row (``load_resolved_events`` shape).
    FOMC is a level in the calendar (percent) → the realized CHANGE in bps; everything else is ``actual``."""
    if kind == "fomc":
        ch = ev.get("change")
        return None if ch is None else float(ch) * 100.0
    a = ev.get("actual")
    return None if a is None else float(a)


def consensus_for(kind: str, ev: Dict[str, Any]) -> Optional[float]:
    """Consensus in the same units as ``realized_for``. FOMC consensus is a LEVEL; the matching expected change
    is consensus - (actual - change) = consensus - prior, in bps."""
    c = ev.get("consensus")
    if c is None:
        return None
    if kind == "fomc":
        a, ch = ev.get("actual"), ev.get("change")
        if a is None or ch is None:
            return None
        return (float(c) - (float(a) - float(ch))) * 100.0
    return float(c)


def join_pm_to_calendar(pm: List[Dict[str, Any]], cal_by_kind: Dict[str, List[Dict[str, Any]]],
                        max_stale_hours: Optional[float] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Exact-date join of PM-expected records to resolved calendar rows → paired release records.

    A paired record carries ``pm_surprise = realized - pm_expected`` and ``consensus_surprise = realized -
    consensus`` against the SAME realized value (so the pair differs only in the expectation). Returns
    ``(paired, diagnostics)``; diagnostics count every drop reason so a thin n is explained, not hidden."""
    diag: Dict[str, Any] = {"pm_events": len(pm), "skipped_no_pm": 0, "stale_dropped": 0, "no_exact_date": 0,
                            "off_by_one_day_only": 0, "no_realized_or_consensus": 0, "paired": 0,
                            "settled_mismatch": 0, "settled_checked": 0}
    paired: List[Dict[str, Any]] = []
    for r in pm:
        if r.get("skipped"):
            diag["skipped_no_pm"] += 1
            continue
        if max_stale_hours is not None and r["stale_hours"] > max_stale_hours:
            diag["stale_dropped"] += 1
            continue
        cal = {e["date"]: e for e in cal_by_kind.get(r["kind"], [])}
        ev = cal.get(r["date"])
        if ev is None:
            d = _dt.date.fromisoformat(r["date"])
            near = {(d + _dt.timedelta(days=o)).isoformat() for o in (-1, 1)}
            diag["off_by_one_day_only" if near & set(cal) else "no_exact_date"] += 1
            continue
        realized, cons = realized_for(r["kind"], ev), consensus_for(r["kind"], ev)
        if realized is None or cons is None:
            diag["no_realized_or_consensus"] += 1
            continue
        if r.get("kalshi_settled") is not None:
            diag["settled_checked"] += 1
            tol = 0.051 if r["kind"] == "cpi_mom" else (1.0 if r["kind"] == "nfp" else 0.5)
            if abs(r["kalshi_settled"] - realized) > tol:
                diag["settled_mismatch"] += 1
        paired.append({"kind": r["kind"], "date": r["date"], "event_ticker": r["event_ticker"],
                       "realized": realized, "pm_expected": r["pm_expected"], "consensus": cons,
                       "pm_surprise": realized - r["pm_expected"], "surprise": realized - cons,
                       "stale_hours": r["stale_hours"], "n_strikes": r["n_strikes"]})
    diag["paired"] = len(paired)
    return paired, diag
