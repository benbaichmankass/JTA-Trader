#!/usr/bin/env python3
"""Maker-entry fill rate and adverse selection on Bybit linear perps, from Bybit's own trade prints.

Lane DESK-MAKER-FILLS (checklist row), unit RQ-20261027-a3f1-01. Question: if an entry were sent as a
post-only limit at the touch instead of a Market order, how often would it fill, how much adverse
selection would it carry, and does it beat the taker entry NET of fees and of that selection?

DATA: ``https://public.bybit.com/trading/<SYM>/<SYM><YYYY-MM-DD>.csv.gz`` -- every Bybit linear trade
of the day (timestamp, aggressor side, size, price, RPI flag). Free and keyless. Bybit publishes NO
historical L1/L2 quotes there, so the touch is INFERRED from prints (see ``quote_at``). RPI prints
(retail-price-improvement liquidity an API order cannot rest in) are dropped before anything is read.

MODEL, per (symbol, decision time T, direction):

* Touch at T, 1-tick spread: last non-RPI print p at or before T; a Sell-aggressor print hit the bid
  (bid = p, ask = p + tick), a Buy print lifted the ask (ask = p, bid = p - tick). Assuming one tick
  UNDERSTATES what a taker pays on a wider book, so it is the conservative side for the maker.
* Taker entry at T: long pays ask_T, short receives bid_T, plus the taker fee.
* Maker entry: post-only limit L at the near touch, k ticks behind it (long L = bid_T - k*tick).
  STRICT fill (graded): some print in (T, T+W] trades at least one tick THROUGH L (long: price <=
  L - tick). Under price-time priority a print through our level means the whole level, our order
  included, was consumed, so no queue model is needed. OPTIMISTIC fill (reported): a print AT L.
* Policy F (fallback; the graded one): unfilled at T+W -> cross as taker at the T+W touch. Both
  arms then hold the same position to the same exit, so the exit cancels and the per-entry edge is
  delta_F = (taker price - maker effective price) in bps of mid_T, + (taker fee - maker fee) when the
  maker filled. Adverse selection is inside delta_F: the unfilled entries are the ones price ran away
  from, and they pay the drift.
* Policy S (skip; reported only): markouts of the filled maker entries at 1/5/15/60 min after the
  fill vs the taker entries' markouts from T. With a random direction the gross markout is ~0, so a
  filled-maker markout below the taker's is the selection cost of skipping.

Decision times: on the hour, hours 1..22 UTC of each sampled day (hour 0 has no prior print in the
file; hour 23's 60-min markout would leave the file). Both directions at each T; a trend-aligned /
counter-trend split by the sign of the 60-min return before T is reported (not graded) because the
strategies' entries are mostly breakout-like.

Fees (bps per side) are the Bybit non-VIP derivatives schedule: taker 5.5 (MEASURED on our bybit
fills: 11.0 bps per round trip, row COST-STACK-BYBIT-TAKER-FEE), maker 2.0 (PUBLISHED schedule,
UNVERIFIED on our account: zero maker fills ever).

Usage:
    python3 scripts/research/desk_maker_fills.py run --out <dir> [--cache <dir>] [--keep-cache]
    python3 scripts/research/desk_maker_fills.py run --days 2026-10-26 --symbols ADAUSDT --out /tmp/x
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

RULE_ID = "RULE-RQ20261027-A3F1-01-MAKER-FILLS"
UNIT_ID = "RQ-20261027-a3f1-01"
SYMBOLS = ("ADAUSDT", "AVAXUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
BASE_URL = "https://public.bybit.com/trading"
TAKER_FEE_BPS = 5.5
MAKER_FEE_BPS = 2.0
WINDOWS_MIN = (1, 5, 15)
OFFSETS = (0, 1)
MARKOUTS_MIN = (1, 5, 15, 60)
HOURS = tuple(range(1, 23))
TREND_LOOKBACK_S = 3600

# Registered sample (RULE above): 40 days, every 9th day back from 2026-10-25 (2025-11-08 .. 2026-10-25).
# 2026-10-26 was the development day for this script and is NOT in the sample.
SAMPLE_END = date(2026, 10, 25)
SAMPLE_STEP_DAYS = 9
SAMPLE_N_DAYS = 40

# Registered grading (RULE above).
PRIMARY_W = 5
PRIMARY_K = 0
X_BPS = 2.0
N_FLOOR_ROWS = 1000
DAYS_FLOOR = 30
BREADTH_MIN = 4
BOOT_REPS = 2000
BOOT_SEED = 20261027


def sample_days() -> List[date]:
    return [SAMPLE_END - timedelta(days=SAMPLE_STEP_DAYS * i) for i in range(SAMPLE_N_DAYS)]


@dataclass
class Prints:
    ts: np.ndarray      # float seconds, ascending
    price: np.ndarray   # float
    is_buy: np.ndarray  # bool, aggressor side
    n_rpi_dropped: int
    n_raw: int


def parse_prints(raw_csv: bytes) -> Prints:
    """Parse one Bybit trading-archive day (csv bytes, already gunzipped)."""
    lines = raw_csv.decode("utf-8").splitlines()
    header = lines[0].split(",")
    i_ts, i_side, i_px = header.index("timestamp"), header.index("side"), header.index("price")
    i_rpi = header.index("RPI") if "RPI" in header else None
    ts, px, buy = [], [], []
    n_rpi = 0
    for ln in lines[1:]:
        if not ln:
            continue
        f = ln.split(",")
        if i_rpi is not None and f[i_rpi].strip() not in ("", "0"):
            n_rpi += 1
            continue
        ts.append(float(f[i_ts]))
        px.append(float(f[i_px]))
        buy.append(f[i_side] == "Buy")
    ts_a = np.asarray(ts, dtype=float)
    order = np.argsort(ts_a, kind="stable")
    return Prints(ts=ts_a[order], price=np.asarray(px, dtype=float)[order],
                  is_buy=np.asarray(buy, dtype=bool)[order], n_rpi_dropped=n_rpi,
                  n_raw=len(lines) - 1)


def infer_tick(price: np.ndarray) -> float:
    """Smallest positive gap between distinct traded prices (rounded to kill float dust)."""
    u = np.unique(np.round(price, 10))
    if len(u) < 2:
        raise ValueError("cannot infer tick from fewer than two distinct prices")
    d = np.diff(u)
    d = d[d > 1e-12]
    return float(np.round(d.min(), 10))


def _last_idx(p: Prints, t: float) -> int:
    return int(np.searchsorted(p.ts, t, side="right")) - 1


def quote_at(p: Prints, t: float, tick: float):
    """(bid, ask, mid) at t from the last print at or before t; None when there is none."""
    i = _last_idx(p, t)
    if i < 0:
        return None
    px = p.price[i]
    if p.is_buy[i]:
        return px - tick, px, px - tick / 2.0
    return px, px + tick, px + tick / 2.0


def first_fill(p: Prints, t0: float, t1: float, limit: float, tick: float, long: bool, strict: bool):
    """Time of the first print in (t0, t1] that fills a resting limit; None if it never does."""
    a = int(np.searchsorted(p.ts, t0, side="right"))
    b = int(np.searchsorted(p.ts, t1, side="right"))
    if b <= a:
        return None
    seg = p.price[a:b]
    eps = tick * 1e-6
    if long:
        hit = seg <= (limit - tick + eps) if strict else seg <= limit + eps
    else:
        hit = seg >= (limit + tick - eps) if strict else seg >= limit - eps
    j = int(np.argmax(hit))
    if not hit[j]:
        return None
    return float(p.ts[a + j])


def decision_rows(p: Prints, symbol: str, day: date, tick: float,
                  windows: Sequence[int] = WINDOWS_MIN, offsets: Sequence[int] = OFFSETS,
                  markouts: Sequence[int] = MARKOUTS_MIN, hours: Sequence[int] = HOURS,
                  taker_fee: float = TAKER_FEE_BPS, maker_fee: float = MAKER_FEE_BPS) -> List[dict]:
    """One row per (T, direction, W, k): delta_F (strict + optimistic), fill flags, markouts."""
    day0 = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
    rows: List[dict] = []
    if len(p.ts) == 0:
        return rows
    t_last = float(p.ts[-1])
    fee_diff = taker_fee - maker_fee
    for h in hours:
        T = day0 + 3600 * h
        if T + 60 * (max(windows) + max(markouts)) > t_last:
            continue
        q = quote_at(p, T, tick)
        if q is None:
            continue
        bid, ask, mid = q
        last_age = T - float(p.ts[_last_idx(p, T)])
        q_prev = quote_at(p, T - TREND_LOOKBACK_S, tick)
        trend = None if q_prev is None else float(np.sign(mid - q_prev[2]))
        for direction in (1, -1):
            long = direction == 1
            taker_px = ask if long else bid
            aligned = None if trend in (None, 0.0) else (trend == direction)
            taker_mk = {}
            for m in markouts:
                qm = quote_at(p, T + 60 * m, tick)
                taker_mk[m] = direction * (qm[2] - taker_px) / mid * 1e4 - taker_fee
            for W in windows:
                qW = quote_at(p, T + 60 * W, tick)
                fb_px = qW[1] if long else qW[0]
                for k in offsets:
                    L = (bid - k * tick) if long else (ask + k * tick)
                    row = {"symbol": symbol, "day": day.isoformat(), "hour": h, "dir": direction,
                           "W": W, "k": k, "tick_bps": tick / mid * 1e4, "last_print_age_s": last_age,
                           "trend_aligned": aligned}
                    for mode, strict in (("strict", True), ("optimistic", False)):
                        tf = first_fill(p, T, T + 60 * W, L, tick, long, strict)
                        filled = tf is not None
                        eff = L if filled else fb_px
                        delta = (direction * (taker_px - eff)) / mid * 1e4 + (fee_diff if filled else 0.0)
                        row[f"filled_{mode}"] = filled
                        row[f"delta_F_{mode}"] = delta
                        if mode == "strict":
                            row["fill_wait_s"] = (tf - T) if filled else None
                            mk = {}
                            for m in markouts:
                                if filled:
                                    qm = quote_at(p, tf + 60 * m, tick)
                                    mk[m] = direction * (qm[2] - L) / mid * 1e4 - maker_fee
                                else:
                                    mk[m] = None
                            row["maker_markout_bps"] = mk
                    row["taker_markout_bps"] = taker_mk
                    rows.append(row)
    return rows


def fetch_day(symbol: str, day: date, cache: Optional[Path], retries: int = 4) -> bytes:
    name = f"{symbol}{day.isoformat()}.csv.gz"
    if cache is not None:
        fp = cache / name
        if fp.exists() and fp.stat().st_size > 0:
            return gzip.decompress(fp.read_bytes())
    url = f"{BASE_URL}/{symbol}/{name}"
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                gz = r.read()
            if cache is not None:
                cache.mkdir(parents=True, exist_ok=True)
                (cache / name).write_bytes(gz)
            return gzip.decompress(gz)
        except Exception as exc:  # noqa: BLE001 -- retried, then recorded per cell
            last_exc = exc
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"fetch failed for {url}: {last_exc}")


def day_block_ci(values: np.ndarray, days: np.ndarray, reps: int = BOOT_REPS, seed: int = BOOT_SEED):
    """Mean and 95% percentile CI resampling whole DAYS (prints within a day are correlated)."""
    if len(values) == 0:
        return None, None, None
    uniq = np.unique(days)
    idx_by_day = [np.flatnonzero(days == d) for d in uniq]
    sums = np.array([values[i].sum() for i in idx_by_day])
    cnts = np.array([len(i) for i in idx_by_day])
    rng = np.random.default_rng(seed)
    boots = np.empty(reps)
    for r in range(reps):
        pick = rng.integers(0, len(uniq), len(uniq))
        boots[r] = sums[pick].sum() / cnts[pick].sum()
    return float(values.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def _sel(rows: List[dict], W: int, k: int, pred=None) -> List[dict]:
    return [r for r in rows if r["W"] == W and r["k"] == k and (pred is None or pred(r))]


def summarize(rows: List[dict], W: int, k: int, pred=None, mode: str = "strict") -> dict:
    sel = _sel(rows, W, k, pred)
    if not sel:
        return {"n": 0}
    d = np.array([r[f"delta_F_{mode}"] for r in sel])
    # Cluster by calendar day across symbols: the six perps co-move within a day.
    days = np.array([r["day"] for r in sel])
    mean, lo, hi = day_block_ci(d, days)
    filled = np.array([r[f"filled_{mode}"] for r in sel])
    out = {"n": len(sel), "days": int(len(np.unique(days))), "mean_delta_F_bps": mean,
           "ci95_lo": lo, "ci95_hi": hi, "sd_delta_F_bps": float(d.std(ddof=1)) if len(d) > 1 else None,
           "fill_rate": float(filled.mean()),
           "mean_delta_F_if_filled_bps": float(d[filled].mean()) if filled.any() else None,
           "mean_delta_F_if_unfilled_bps": float(d[~filled].mean()) if (~filled).any() else None,
           "median_tick_bps": float(np.median([r["tick_bps"] for r in sel]))}
    if mode == "strict":
        mk = {}
        for m in MARKOUTS_MIN:
            mm = [r["maker_markout_bps"][m] for r in sel if r["filled_strict"]]
            tk = [r["taker_markout_bps"][m] for r in sel]
            mk[str(m)] = {"maker_filled_net_bps": float(np.mean(mm)) if mm else None,
                          "taker_all_net_bps": float(np.mean(tk)) if tk else None}
        out["policy_S_markouts"] = mk
        waits = [r["fill_wait_s"] for r in sel if r["filled_strict"]]
        out["median_fill_wait_s"] = float(np.median(waits)) if waits else None
    return out


def grade(rows: List[dict], symbols: Sequence[str], days_measured: int) -> dict:
    prim = summarize(rows, PRIMARY_W, PRIMARY_K)
    per_sym = {s: summarize(rows, PRIMARY_W, PRIMARY_K, pred=lambda r, s=s: r["symbol"] == s) for s in symbols}
    positive = sum(1 for s in symbols if (per_sym[s].get("mean_delta_F_bps") or -1) > 0)
    powered = prim.get("n", 0) >= N_FLOOR_ROWS and days_measured >= DAYS_FLOOR
    if not powered:
        verdict = "indeterminate"
    elif (prim["mean_delta_F_bps"] >= X_BPS and prim["ci95_lo"] > 0 and positive >= BREADTH_MIN):
        verdict = "pass"
    else:
        verdict = "fail"
    return {"verdict": verdict, "powered": powered, "primary": prim, "symbols_positive": positive,
            "per_symbol": per_sym,
            "thresholds": {"X_bps": X_BPS, "N_floor_rows": N_FLOOR_ROWS, "days_floor": DAYS_FLOOR,
                           "breadth_min": BREADTH_MIN, "W_min": PRIMARY_W, "k_ticks": PRIMARY_K,
                           "fill": "strict (trade-through by >= 1 tick)", "policy": "F (fallback taker at T+W)"}}


def secondary(rows: List[dict], symbols: Sequence[str]) -> dict:
    out = {}
    for W in WINDOWS_MIN:
        for k in OFFSETS:
            key = f"W{W}_k{k}"
            out[key] = {"strict": summarize(rows, W, k), "optimistic": summarize(rows, W, k, mode="optimistic"),
                        "trend_aligned": summarize(rows, W, k, pred=lambda r: r["trend_aligned"] is True),
                        "counter_trend": summarize(rows, W, k, pred=lambda r: r["trend_aligned"] is False),
                        "per_symbol": {s: summarize(rows, W, k, pred=lambda r, s=s: r["symbol"] == s)
                                       for s in symbols}}
    return out


def run(args) -> int:
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    days = [date.fromisoformat(d) for d in args.days.split(",")] if args.days else sample_days()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache) if args.cache else None
    rows: List[dict] = []
    cells: Dict[str, dict] = {}
    for day in days:
        for sym in symbols:
            key = f"{sym}|{day.isoformat()}"
            t0 = time.time()
            try:
                p = parse_prints(fetch_day(sym, day, cache))
                tick = infer_tick(p.price)
                r = decision_rows(p, sym, day, tick)
                rows.extend(r)
                cells[key] = {"state": "measured", "n_prints": int(len(p.ts)), "n_rpi_dropped": p.n_rpi_dropped,
                              "tick": tick, "rows": len(r), "secs": round(time.time() - t0, 1)}
            except Exception as exc:  # noqa: BLE001 -- recorded per cell, never dropped
                cells[key] = {"state": "producer_failed", "error": str(exc)[:300]}
            finally:
                if cache is not None and not args.keep_cache:
                    fp = cache / f"{sym}{day.isoformat()}.csv.gz"
                    if fp.exists():
                        fp.unlink()
            print(f"{key} {cells[key]}", flush=True)
    measured_days = len({k.split("|")[1] for k, v in cells.items() if v["state"] == "measured"})
    failed = [k for k, v in cells.items() if v["state"] != "measured"]
    g = grade(rows, symbols, measured_days)
    record = {
        "unit": UNIT_ID, "decision_rule": {"id": RULE_ID, "registered_at": "2026-10-27"},
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "read_state": "measured" if not failed or measured_days >= DAYS_FLOOR else "producer_failed",
        "verdict": g["verdict"], "harness": "scripts/research/desk_maker_fills.py",
        "population": {"symbols": symbols, "days_requested": [d.isoformat() for d in days],
                       "days_measured": measured_days, "cells_failed": failed,
                       "decision_times": "on the hour, hours 1..22 UTC, both directions",
                       "data": f"{BASE_URL}/<SYM>/<SYM><day>.csv.gz (Bybit linear trade prints, RPI dropped)"},
        "cost_stack": {"taker_fee_bps_per_side": TAKER_FEE_BPS, "maker_fee_bps_per_side": MAKER_FEE_BPS,
                       "taker_fee_provenance": "MEASURED (11.0 bps RT on our bybit fills)",
                       "maker_fee_provenance": "PUBLISHED schedule, UNVERIFIED on our account",
                       "spread": "1 tick assumed (conservative for the maker)",
                       "funding": "not applicable: both arms hold the same position after entry"},
        "grade": g, "secondary": secondary(rows, symbols), "cells": cells,
    }
    (out / "maker_fills_record.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=str))
    if args.rows:
        with open(out / "maker_fills_rows.jsonl", "w") as fh:
            for r in rows:
                fh.write(json.dumps(r, default=str) + "\n")
    p = g["primary"]
    print(json.dumps({"verdict": g["verdict"], "n": p.get("n"), "days": measured_days,
                      "mean_delta_F_bps": p.get("mean_delta_F_bps"), "ci95": [p.get("ci95_lo"), p.get("ci95_hi")],
                      "fill_rate": p.get("fill_rate"), "symbols_positive": g["symbols_positive"]}, indent=1))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--symbols", default=",".join(SYMBOLS))
    r.add_argument("--days", default="", help="comma list of YYYY-MM-DD; default = the registered sample")
    r.add_argument("--cache", default="")
    r.add_argument("--keep-cache", action="store_true")
    r.add_argument("--rows", action="store_true", help="also write every decision row as jsonl")
    r.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
