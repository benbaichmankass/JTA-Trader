#!/usr/bin/env python3
# wiring: manual-only - AM-V2 unit 1 (bar-expanded label build): pure per-bar label function for the target / invalidation heads; docs/research/ml-am-heads-design-2026-11-23.md section 2
"""cf_bar_labels: per-(trade, bar) forward labels and point-in-time features for the AM v2 target and invalidation heads (Tier 1, no training).

Design: ``docs/research/ml-am-heads-design-2026-11-23.md`` sections 2-4. CF-D1 (``cf_labels.py``) emits one row per TRADE; the heads act at
every bar, so this expands a trade into one row per bar it is open. It is a PURE function of one trade and its bars, so the cf_bulk shard
runner (owner: the CF lane) can call it where it already holds the bar window, and a census can run on it without re-deriving anything.

ENTRY CONVENTION (the run-w correction): the harness enters at the SIGNAL BAR'S CLOSE (``entry_at_bar_close``). ``entry_time`` is the signal
bar's open, so the fill is at ``entry_time + bar_seconds`` and the first bar this module reads is the bar that OPENS at that instant. A bar
that opens before the fill is never read, so the signal bar's own range can never leak into a label or a feature.

For each bar index k (k = 1 is the first bar after the fill; the row is built at bar k's CLOSE):
  features  (bars 1..k only): open_r, peak_r, mae_r, bars_since_peak, bars_open, range_atr_k (bar k range / mean range of bars 1..k).
  labels    (bars k+1.. only, hindsight by construction, never features):
    fwd_mfe_r   max favourable excursion after bar k from bar k's CLOSE, in R0 (the TARGET head's quantile target)
    reach_j     1 if the path reaches close_k +/- j*R0 (favourable) before the stop is touched, j in REACH_J (the P(reach) target)
    stop_first  1 if the stop (the original stop) is touched before the path reaches close_k + TARGET_J*R0  (the INVALIDATION target)
    dip_recovers 1 if, within DIP_BARS, the adverse excursion from close_k reaches DIP_FRAC of the distance to the stop AND the path then reaches
                the target before the stop (the trade a tighter stop kills and hold wins)
    censored    True if the forward window ends (data end) before the stop is touched AND fewer than ``max_fwd_bars`` bars remain: label
                is "at least"; callers EXCLUDE censored rows from a fit and report the count (never fill).
Rows stop at the bar of the replayed actual exit (``exit_idx``) or when the stop is touched, whichever is first.
"""
from __future__ import annotations

import sys
from typing import Dict, List, Optional, Sequence

REACH_J = (0.5, 1.0, 2.0, 3.0)
TARGET_J = 2.0           # the target the invalidation labels are measured against (PROPOSED in the design memo; fixed before any fit)
DIP_FRAC = 0.5           # adverse excursion that counts as a dip: this fraction of the distance to the stop
DIP_BARS = 6
SCHEMA = "cf_bar_labels/1"


def build_rows(*, side: str, entry: float, sl: float, bars: Sequence[dict], entry_time: float, bar_seconds: float,
               max_fwd_bars: int = 48, exit_idx: Optional[int] = None) -> List[Dict]:
    """``bars``: dicts with time/open/high/low/close (epoch seconds), ascending. Bars with ``time < entry_time + bar_seconds`` (the signal
    bar and anything earlier) are DROPPED. ``side`` is 'long' or 'short'. R0 = |entry - sl|."""
    if side not in ("long", "short"):
        raise ValueError(side)
    sgn = 1.0 if side == "long" else -1.0
    r0 = abs(entry - sl)
    if r0 <= 0:
        return []
    t_fill = entry_time + bar_seconds
    b = [x for x in bars if x["time"] >= t_fill]
    n = len(b)
    rows: List[Dict] = []
    peak, mae, peak_k, rng_sum = 0.0, 0.0, 0, 0.0
    for k in range(1, n + 1):
        bar = b[k - 1]
        fav = sgn * (bar["high" if sgn > 0 else "low"] - entry) / r0
        adv = sgn * (bar["low" if sgn > 0 else "high"] - entry) / r0
        stopped_here = adv <= -1.0
        if fav > peak:
            peak, peak_k = fav, k
        mae = min(mae, adv)
        rng_sum += (bar["high"] - bar["low"]) / r0
        if stopped_here or (exit_idx is not None and k >= exit_idx):
            break                                           # the trade is closed at bar k: no decision row at or after it
        close_r = sgn * (bar["close"] - entry) / r0
        feat = {"open_r": close_r, "peak_r": peak, "mae_r": mae, "bars_since_peak": k - peak_k, "bars_open": k,
                "range_atr_k": ((bar["high"] - bar["low"]) / r0) / (rng_sum / k) if rng_sum > 0 else None}
        rows.append({"k": k, "features": feat, "labels": _forward(b, k, sgn, entry, r0, close_r, max_fwd_bars)})
    return rows


def _forward(b: Sequence[dict], k: int, sgn: float, entry: float, r0: float, close_r: float, max_fwd: int) -> Dict:
    """Labels from bars k+1.. only. All excursions are in R0 relative to bar k's close; the stop sits at -1R from the ENTRY."""
    fwd = b[k:k + max_fwd]
    mfe, reached = 0.0, {j: 0 for j in REACH_J}
    stop_first, hit_stop, hit_target = None, False, False
    dip_seen, dip_recovers = False, 0
    for i, x in enumerate(fwd, start=1):
        fav = sgn * (x["high" if sgn > 0 else "low"] - entry) / r0 - close_r        # favourable, from the bar-k close
        adv = sgn * (x["low" if sgn > 0 else "high"] - entry) / r0                  # in R from entry, for the stop test
        stopped = adv <= -1.0
        if not hit_stop:
            mfe = max(mfe, fav)
            for j in REACH_J:
                if fav >= j and not reached[j]:
                    reached[j] = 1                                                   # counted only while the stop is still intact
        if not hit_target and fav >= TARGET_J and not stopped:
            hit_target = True
        if i <= DIP_BARS and (adv - close_r) <= -DIP_FRAC * (close_r + 1.0):
            dip_seen = True
        if hit_target and dip_seen and not hit_stop:
            dip_recovers = 1
        if stopped and not hit_target:
            hit_stop = True
            break
        if hit_target and not stopped:
            continue
    stop_first = 1 if hit_stop else 0
    censored = (not hit_stop) and (not hit_target) and len(fwd) < max_fwd
    return {"fwd_mfe_r": mfe, **{f"reach_{j:g}": reached[j] for j in REACH_J}, "stop_first": stop_first,
            "dip_recovers": dip_recovers, "censored": censored, "n_fwd_bars": len(fwd)}


def census(rows_by_trade: Dict[str, List[Dict]]) -> Dict:
    """Counts for the unit-1 census: trades, rows, censored share, stop-first share, dip-recovers share (each with its population)."""
    rows = [r for v in rows_by_trade.values() for r in v]
    nr = len(rows)
    if not nr:
        return {"schema": SCHEMA, "n_trades": len(rows_by_trade), "n_rows": 0}
    ok = [r for r in rows if not r["labels"]["censored"]]
    return {"schema": SCHEMA, "n_trades": len(rows_by_trade), "n_rows": nr, "n_censored": nr - len(ok),
            "share_censored": round((nr - len(ok)) / nr, 4),
            "share_stop_first_uncensored": round(sum(r["labels"]["stop_first"] for r in ok) / len(ok), 4) if ok else None,
            "share_dip_recovers_uncensored": round(sum(r["labels"]["dip_recovers"] for r in ok) / len(ok), 4) if ok else None,
            "population": "uncensored rows only for the shares; one trade contributes one row per bar it is open", "provenance": "ESTIMATED"}


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
