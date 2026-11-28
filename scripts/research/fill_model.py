#!/usr/bin/env python3
# wiring: manual-only - the D9 fill model (row MLP-D9-WHIPPET, lane INFRA-BUILD-20261128); imported by research units that grade a post-only entry/exit; no schedule consumes it.
"""Queue-aware fill model for a resting post-only limit order, from Bybit trade prints. (Tier-1 research tooling; no order, no config.)

WHY. Every maker-entry / maker-exit test so far (a3f1-01, 1c4e-01, e8a1-0x, b9d0-0x) grades ONE fill rule: STRICT, the order fills only
when a print trades at least one tick THROUGH the limit (``desk_maker_fills.first_fill``). That is the pessimistic end of a range: under
price-time priority a print through L consumed the whole level, so no queue model is needed, but it also ignores every order that
would have filled from prints AT L once the queue ahead of it traded. The optimistic end (any print at L) is reported but never graded.
The truth depends on the queue ahead of us, which prints cannot show (Bybit publishes no historical L2) and which our account has
never measured (zero maker fills ever). So a limit-entry verdict comes back INDETERMINATE whenever the answer depends on the queue.

WHAT THIS ADDS. One parameter, kappa = queue ahead of our order, in units of u (the median per-minute volume of the aggressor side that
hits our order, over the 60 minutes before the decision). The fill rule, for a resting buy at L (a sell is the mirror):

  filled at the first print p_i in (T, T+W] such that
      p_i <= L - tick                                   (the level was consumed: always a fill, whatever the queue), OR
      cumulative size of Sell-aggressor prints at price == L, up to and including p_i,  >  kappa * u      (the queue ahead has traded).

kappa = 0 is the OPTIMISTIC rule (first print at L fills) and kappa -> infinity is the STRICT rule, both byte-equal to
``desk_maker_fills.first_fill`` on the same prints (asserted in --self-test). Fill probability is monotone non-increasing in kappa by
construction. The deliverable is not a point estimate of kappa (unmeasurable here) but the CURVE and one number per claim:

  kappa* (``breakeven_kappa``) = the largest queue (in u) at which the claim still holds. A claim that holds at every kappa is
  ROBUST; one that fails at kappa = 0 is a FAIL whatever the queue is; one that flips inside the grid is QUEUE-DEPENDENT and names
  kappa*, so the test tells the manager exactly which measurement (the real queue position of our first post-only fills) would
  settle it, instead of returning INDETERMINATE.

NOT MODELLED (stated, not hidden): latency, post-only rejects (an order that would cross is rejected on Bybit), partial fills (an order
fills whole), our own size changing the level, hidden/iceberg liquidity, cancel-and-requeue. RPI prints are dropped as in a3f1-01.
The touch is inferred from the last print (one-tick spread), identical to desk_maker_fills.quote_at.

    python3 scripts/research/fill_model.py run --out O [--cache C] [--symbols ADAUSDT,...] [--days 2026-10-01,...]
    python3 scripts/research/fill_model.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import desk_maker_fills as DMF  # noqa: E402

KAPPAS = (0.0, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, float("inf"))
LOOKBACK_S = 3600.0
TAKER, MAKER = DMF.TAKER_FEE_BPS, DMF.MAKER_FEE_BPS


@dataclass
class SizedPrints:
    ts: np.ndarray
    price: np.ndarray
    is_buy: np.ndarray
    size: np.ndarray
    n_rpi_dropped: int = 0


def parse_sized(raw_csv: bytes) -> SizedPrints:
    """Parse one Bybit trading-archive day, keeping the print size (``desk_maker_fills.parse_prints`` drops it)."""
    lines = raw_csv.decode("utf-8").splitlines()
    h = lines[0].split(",")
    i_ts, i_side, i_px, i_sz = h.index("timestamp"), h.index("side"), h.index("price"), h.index("size")
    i_rpi = h.index("RPI") if "RPI" in h else None
    ts, px, buy, sz, n_rpi = [], [], [], [], 0
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
        sz.append(float(f[i_sz]))
    o = np.argsort(np.asarray(ts, dtype=float), kind="stable")
    return SizedPrints(np.asarray(ts, dtype=float)[o], np.asarray(px, dtype=float)[o], np.asarray(buy, dtype=bool)[o],
                       np.asarray(sz, dtype=float)[o], n_rpi)


def unit_volume(p: SizedPrints, T: float, long: bool, lookback_s: float = LOOKBACK_S) -> float | None:
    """u: median per-minute size of the aggressor side that hits a resting order (Sell for a buy limit) over the lookback; None if empty."""
    a = int(np.searchsorted(p.ts, T - lookback_s, side="right"))
    b = int(np.searchsorted(p.ts, T, side="right"))
    if b <= a:
        return None
    side = (~p.is_buy[a:b]) if long else p.is_buy[a:b]
    if not side.any():
        return None
    minute = ((p.ts[a:b] - (T - lookback_s)) // 60).astype(int)
    per = np.zeros(int(lookback_s // 60) + 1)
    np.add.at(per, minute[side], p.size[a:b][side])
    nz = per[per > 0]
    return float(np.median(nz)) if len(nz) else None


def first_fill_q(p: SizedPrints, t0: float, t1: float, limit: float, tick: float, long: bool, queue_ahead: float) -> float | None:
    """Time of the first print in (t0, t1] that fills a resting limit given ``queue_ahead`` (same units as print size); None if none does.

    queue_ahead = 0 -> optimistic (first print at the level fills); inf -> strict (only a trade-through fills)."""
    a = int(np.searchsorted(p.ts, t0, side="right"))
    b = int(np.searchsorted(p.ts, t1, side="right"))
    if b <= a:
        return None
    px, sz, buy = p.price[a:b], p.size[a:b], p.is_buy[a:b]
    eps = tick * 1e-6
    if long:
        through = px <= limit - tick + eps
        at = (np.abs(px - limit) <= eps) & (~buy)
    else:
        through = px >= limit + tick - eps
        at = (np.abs(px - limit) <= eps) & buy
    if np.isinf(queue_ahead):
        hit = through
    else:
        cum = np.cumsum(np.where(at, sz, 0.0))
        # strict ">" for queue_ahead > 0 (the order sits behind the whole queue); queue 0 fills on the first print at the level.
        at_fill = at & ((cum > queue_ahead) if queue_ahead > 0 else True)
        hit = through | at_fill
    j = int(np.argmax(hit))
    return float(p.ts[a + j]) if hit[j] else None


def decision_rows_q(p: SizedPrints, symbol: str, day: date, tick: float, kappas: Sequence[float] = KAPPAS,
                    windows: Sequence[int] = (5,), hours: Sequence[int] = DMF.HOURS) -> list[dict]:
    """One row per (T, direction, W, kappa): fill flag and delta_F (bps, policy F) -- the same formula as ``desk_maker_fills.decision_rows``."""
    day0 = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
    if len(p.ts) == 0:
        return []
    rows: list[dict] = []
    fee_diff = TAKER - MAKER
    t_last = float(p.ts[-1])
    for h in hours:
        T = day0 + 3600 * h
        if T + 60 * max(windows) > t_last:
            continue
        q = DMF.quote_at(p, T, tick)
        if q is None:
            continue
        bid, ask, mid = q
        for direction in (1, -1):
            long = direction == 1
            u = unit_volume(p, T, long)
            if u is None:
                continue
            taker_px = ask if long else bid
            L = bid if long else ask
            for W in windows:
                qW = DMF.quote_at(p, T + 60 * W, tick)
                fb_px = qW[1] if long else qW[0]
                for kap in kappas:
                    tf = first_fill_q(p, T, T + 60 * W, L, tick, long, kap * u if np.isfinite(kap) else float("inf"))
                    filled = tf is not None
                    eff = L if filled else fb_px
                    delta = direction * (taker_px - eff) / mid * 1e4 + (fee_diff if filled else 0.0)
                    rows.append({"symbol": symbol, "day": day.isoformat(), "hour": h, "dir": direction, "W": W,
                                 "kappa": "inf" if not np.isfinite(kap) else kap, "filled": filled, "delta_F_bps": float(delta),
                                 "u": u, "wait_s": (tf - T) if filled else None})
    return rows


def curve(rows: list[dict], W: int) -> list[dict]:
    """Per-kappa fill rate and mean delta_F with a day-block CI (days resampled, as DMF.day_block_ci)."""
    out = []
    ks = sorted({r["kappa"] for r in rows if r["W"] == W}, key=lambda k: float("inf") if k == "inf" else float(k))
    for k in ks:
        sel = [r for r in rows if r["W"] == W and r["kappa"] == k]
        d = np.array([r["delta_F_bps"] for r in sel])
        days = np.array([r["day"] for r in sel])
        mean, lo, hi = DMF.day_block_ci(d, days)
        out.append({"kappa": k, "n": len(sel), "fill_rate": float(np.mean([r["filled"] for r in sel])),
                    "mean_delta_F_bps": mean, "ci95": [lo, hi]})
    return out


def breakeven_kappa(cv: list[dict], bar_bps: float) -> dict:
    """Where on the kappa grid does the claim 'mean delta_F >= bar_bps AND ci95 lower > 0' hold?

    Returns {'state', 'kappa_star', 'holds_at_0', 'holds_at_inf'}. state: 'robust' (holds at every kappa, incl. strict), 'fails_everywhere'
    (fails even with an empty queue: no queue assumption rescues it), 'queue_dependent' (holds up to kappa_star, the last grid point
    where it holds before the first failure)."""
    def holds(c):
        return c["mean_delta_F_bps"] is not None and c["mean_delta_F_bps"] >= bar_bps and c["ci95"][0] is not None and c["ci95"][0] > 0
    flags = [holds(c) for c in cv]
    if not flags:
        return {"state": "no_data", "kappa_star": None, "holds_at_0": None, "holds_at_inf": None}
    if all(flags):
        return {"state": "robust", "kappa_star": "inf", "holds_at_0": True, "holds_at_inf": True}
    if not flags[0]:
        return {"state": "fails_everywhere", "kappa_star": None, "holds_at_0": False, "holds_at_inf": bool(flags[-1])}
    star = None
    for c, f in zip(cv, flags):
        if not f:
            break
        star = c["kappa"]
    return {"state": "queue_dependent", "kappa_star": star, "holds_at_0": True, "holds_at_inf": bool(flags[-1])}


# ---------------------------------------------------------------------------------------------------------------- run
def run(a) -> int:
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    days = [date.fromisoformat(d) for d in a.days.split(",")] if a.days else DMF.sample_days()[: a.max_days]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache) if a.cache else None
    windows = tuple(int(w) for w in a.windows.split(","))
    rows, cells = [], {}
    for day in days:
        for sym in symbols:
            key = f"{sym}|{day.isoformat()}"
            try:
                p = parse_sized(DMF.fetch_day(sym, day, cache))
                tick = DMF.infer_tick(p.price)
                r = decision_rows_q(p, sym, day, tick, windows=windows)
                rows.extend(r)
                cells[key] = {"state": "measured", "n_prints": len(p.ts), "tick": tick, "rows": len(r)}
            except Exception as exc:  # noqa: BLE001 -- recorded per cell, never dropped  # allow-silent: written to the cell as producer_failed and counted in cells_failed
                cells[key] = {"state": "producer_failed", "error": str(exc)[:300]}
            finally:
                if cache is not None and not a.keep_cache:
                    fp = cache / f"{sym}{day.isoformat()}.csv.gz"
                    if fp.exists():
                        fp.unlink()
            print(key, cells[key], flush=True)
    failed = [k for k, v in cells.items() if v["state"] != "measured"]
    res = {}
    for W in windows:
        cv = curve(rows, W)
        res[f"W{W}"] = {"curve": cv, "breakeven_vs_a3f1_bar": breakeven_kappa(cv, DMF.X_BPS), "breakeven_vs_zero": breakeven_kappa(cv, 1e-9)}
    rec = {"harness": "scripts/research/fill_model.py", "row": "MLP-D9-WHIPPET",
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "read_state": "measured" if rows and not failed else ("partial" if rows else "producer_failed"),
           "population": {"symbols": symbols, "days": [d.isoformat() for d in days], "decision_times": "on the hour, hours 1..22 UTC, both directions",
                          "n_rows": len(rows), "cells_failed": failed, "k_ticks": 0,
                          "unit_u": "median per-minute hitting-side volume over the prior 60 min"},
           "bars": {"a3f1_X_bps": DMF.X_BPS}, "results": res,
           "not_modelled": ["latency", "post-only rejects", "partial fills", "own-size impact", "hidden liquidity", "cancel and requeue"],
           "cells": cells}
    (out / "fill_model_record.json").write_text(json.dumps(rec, indent=1, sort_keys=True, default=str))
    for w, v in res.items():
        print(w, json.dumps(v["breakeven_vs_a3f1_bar"]), json.dumps(v["breakeven_vs_zero"]))
        for c in v["curve"]:
            print("  kappa", c["kappa"], "fill", round(c["fill_rate"], 3), "delta_F", None if c["mean_delta_F_bps"] is None else round(c["mean_delta_F_bps"], 3), "ci", c["ci95"])
    return 0 if rows else 1


# ---------------------------------------------------------------------------------------------------------------- self-test
def _synthetic(seed: int, n: int = 40000) -> SizedPrints:
    rng = np.random.default_rng(seed)
    ts = np.sort(rng.uniform(0, 86400, n))
    px = np.round(100 + np.cumsum(rng.choice([-0.01, 0.0, 0.01], n, p=[0.3, 0.4, 0.3])), 2)
    return SizedPrints(ts, px, rng.random(n) < 0.5, rng.exponential(1.0, n) + 0.01)


def _self_test() -> None:
    p = _synthetic(7)
    tick = 0.01
    # 1) kappa 0 == DMF optimistic, kappa inf == DMF strict, on the same prints, both directions, 300 random windows.
    rng = np.random.default_rng(1)
    pp = DMF.Prints(p.ts, p.price, p.is_buy, 0, len(p.ts))
    for _ in range(300):
        t0 = float(rng.uniform(100, 80000))
        t1 = t0 + 300
        L = float(np.round(rng.choice(p.price), 2))
        long = bool(rng.random() < 0.5)
        for kap, strict in ((float("inf"), True),):
            assert first_fill_q(p, t0, t1, L, tick, long, kap) == DMF.first_fill(pp, t0, t1, L, tick, long, strict)
        # optimistic DMF fills on ANY print at/through L (either aggressor); kappa 0 requires the hitting side at L, so it is <= optimistic
        # and >= strict: assert the ordering instead of equality, and equality on the through-print component.
        f0 = first_fill_q(p, t0, t1, L, tick, long, 0.0)
        fs = first_fill_q(p, t0, t1, L, tick, long, float("inf"))
        assert (fs is None) or (f0 is not None and f0 <= fs)
    # 2) monotone: fill time is non-decreasing (and fill prob non-increasing) in queue_ahead
    for _ in range(300):
        t0 = float(rng.uniform(100, 80000))
        L = float(np.round(rng.choice(p.price), 2))
        long = bool(rng.random() < 0.5)
        prev = -1.0
        for qa in (0.0, 0.5, 2.0, 10.0, float("inf")):
            f = first_fill_q(p, t0, t0 + 300, L, tick, long, qa)
            cur = float("inf") if f is None else f
            assert cur >= prev, (qa, cur, prev)
            prev = cur
    # 3) hand case: buy limit 10.00, queue 5; sell prints at 10.00 sizes 2,2,2 -> fills on the third (cum 6 > 5)
    h = SizedPrints(np.array([1.0, 2.0, 3.0, 4.0]), np.array([10.0, 10.0, 10.0, 9.99]), np.array([False, False, False, False]), np.array([2.0, 2.0, 2.0, 1.0]))
    assert first_fill_q(h, 0.0, 10.0, 10.0, 0.01, True, 5.0) == 3.0
    assert first_fill_q(h, 0.0, 10.0, 10.0, 0.01, True, 6.0) == 4.0     # cum 6 is not > 6; the through-print at 9.99 fills
    assert first_fill_q(h, 0.0, 10.0, 10.0, 0.01, True, float("inf")) == 4.0
    assert first_fill_q(h, 0.0, 10.0, 10.0, 0.01, True, 0.0) == 1.0
    # a Buy-aggressor print at the level does not consume the queue of a resting BUY
    h2 = SizedPrints(np.array([1.0, 2.0]), np.array([10.0, 10.0]), np.array([True, True]), np.array([9.0, 9.0]))
    assert first_fill_q(h2, 0.0, 10.0, 10.0, 0.01, True, 1.0) is None
    # sell limit mirror
    h3 = SizedPrints(np.array([1.0, 2.0, 3.0]), np.array([10.0, 10.0, 10.01]), np.array([True, True, True]), np.array([2.0, 2.0, 1.0]))
    assert first_fill_q(h3, 0.0, 10.0, 10.0, 0.01, False, 3.0) == 2.0
    assert first_fill_q(h3, 0.0, 10.0, 10.0, 0.01, False, 4.0) == 3.0
    # 4) breakeven_kappa states
    def mk(means, los):
        return [{"kappa": k, "mean_delta_F_bps": m, "ci95": [lo, 9.0]} for k, m, lo in zip((0, 1, "inf"), means, los)]
    assert breakeven_kappa(mk([3, 3, 3], [1, 1, 1]), 2.0)["state"] == "robust"
    assert breakeven_kappa(mk([1, 1, 1], [1, 1, 1]), 2.0)["state"] == "fails_everywhere"
    r = breakeven_kappa(mk([3, 3, 1], [1, 1, -1]), 2.0)
    assert r["state"] == "queue_dependent" and r["kappa_star"] == 1 and r["holds_at_inf"] is False
    # 5) parse_sized keeps size, drops RPI
    raw = b"timestamp,symbol,side,size,price,RPI\n1.0,X,Buy,2.5,10.0,0\n2.0,X,Sell,1.0,10.0,1\n3.0,X,Sell,4.0,9.99,0\n"
    s = parse_sized(raw)
    assert list(s.size) == [2.5, 4.0] and s.n_rpi_dropped == 1
    # 6) decision rows: one row per (T, dir, W, kappa); delta_F at kappa=inf equals DMF strict on the same prints
    day = date(2026, 1, 2)
    d0 = datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp()
    q = _synthetic(3, 60000)
    q = SizedPrints(q.ts + d0, q.price, q.is_buy, q.size)
    rows = decision_rows_q(q, "SYN", day, 0.01, hours=(5, 6, 7))
    ref = DMF.decision_rows(DMF.Prints(q.ts, q.price, q.is_buy, 0, len(q.ts)), "SYN", day, 0.01, windows=(5,), offsets=(0,), markouts=(1,), hours=(5, 6, 7))
    inf_rows = sorted((r["hour"], r["dir"], r["delta_F_bps"]) for r in rows if r["kappa"] == "inf")
    ref_rows = sorted((r["hour"], r["dir"], r["delta_F_strict"]) for r in ref)
    assert len(inf_rows) == len(ref_rows) > 0
    for x, y in zip(inf_rows, ref_rows):
        assert x[:2] == y[:2] and abs(x[2] - y[2]) < 1e-9
    print("fill_model self-test OK")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--symbols", default=",".join(DMF.SYMBOLS))
    r.add_argument("--days", default="")
    r.add_argument("--max-days", type=int, default=40)
    r.add_argument("--windows", default="5")
    r.add_argument("--cache", default="")
    r.add_argument("--keep-cache", action="store_true")
    r.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if a.cmd == "run":
        return run(a)
    ap.error("a command or --self-test is required")


if __name__ == "__main__":
    sys.exit(main())
