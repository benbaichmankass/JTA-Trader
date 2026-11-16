#!/usr/bin/env python3
# wiring: manual-only — LTR-STALL-TIMESTOP-S0 (and LTR-WEAK-LEG-CLOSE-S0): mechanical time-stop / stall / weak-leg close vs hold vs random over a committed per-package path corpus. Research; no timer.
"""Does a MECHANICAL close (time stop, stall stop, weak-leg close) beat, or at least not lose to, holding? (no reviewer)

    # build the committed corpus from saved journal pages + binance.vision klines (VM-side data; run once, commit the output)
    python3 scripts/research/ltr_timestop_s0.py build --trades DIR --packages FILE --cache DIR --out comms/research/ltr_timestop_s0/paths.jsonl
    # grade arms against the committed corpus (runs anywhere, no network)
    python3 scripts/research/ltr_timestop_s0.py grade --paths comms/research/ltr_timestop_s0/paths.jsonl \
        --arm ts:4 --arm ts:12 --arm stall:8:0.5 --arm weak:12:0.0 --out DIR

Arm grammar (hours are since ENTRY; the exit is at the OPEN of the first bar after the first closed bar at/after
entry + h, and only if that is strictly before the realised close, the same "fired in time" rule as
``ltr_trigger_close_s0``):
  ``ts:H``         close unconditionally at H hours (a per-leg max-hold);
  ``stall:H:X``    close at H hours only if the peak CLOSE-R so far is < X (the leg never got going);
  ``weak:H:X``     close at H hours only if the CURRENT close-R is < X (the leg is behind where it should be).
HOLD = the realised net R (journal fills, initial-stop R basis). CLOSE = open of the exit bar, net of the harness
cost stack (recorded fee/funding legs pro-rata to the held fraction, plus policy slippage, i.e. the S0 convention).
RANDOM = the mean over 50 draws of the same exit at a uniformly drawn bar from the bars the arm could have fired on,
restricted to the packages the arm fired on (the matched random-time control). Delta = CLOSE - HOLD, paired per package.
STATED BIASES: spot candles (binance.vision) against perp fills; entry/exit bars are bar opens; the HOLD side includes
every exit the leg really took (stops, TPs, max-hold, reviewer closes); crypto USDT legs only.
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

SEED, DRAWS, N_RANDOM = 20261116, 10_000, 50


def build(a: argparse.Namespace) -> int:
    import ltr_trigger_close_s0 as s0
    import live_review_counterfactual as cf
    trades = s0.load_rows(sorted(glob.glob(str(Path(a.trades) / "tr_*.json"))))
    pk = {p["order_package_id"]: p for p in s0.load_rows([a.packages])}
    legs = s0.roster_legs()
    pool = [t for t in trades if str(t.get("status") or "").lower() == "closed" and not t.get("is_backtest")
            and t.get("strategy_name") in legs and str(t.get("symbol") or "").endswith("USDT")
            and t.get("order_package_id") in pk]
    by_pkg: Dict[str, dict] = {}
    for t in sorted(pool, key=lambda t: int(t["id"])):
        by_pkg.setdefault(t["order_package_id"], t)
    excluded: Counter = Counter()
    groups: Dict[tuple, list] = defaultdict(list)
    for pid, t in by_pkg.items():
        tf = cf._meta(pk[pid]).get("timeframe")
        if tf not in s0.TF_S:
            excluded["timeframe_unknown"] += 1
            continue
        groups[(t["symbol"], tf)].append((pid, t, pk[pid]))
    rows: List[dict] = []
    for (sym, tf), items in sorted(groups.items()):
        t0 = min(s0._ts(t.get("timestamp")) for _, t, _ in items) - 40 * s0.TF_S[tf]
        t1 = max(s0._ts(t.get("closed_at")) or 0 for _, t, _ in items) + 2 * s0.TF_S[tf]
        bars = s0.fetch_klines(sym, tf, t0, t1, Path(a.cache))
        times = [b["time"] for b in bars]
        for pid, t, p in items:
            side = 1.0 if str(t.get("direction") or p.get("direction")).lower() in ("long", "buy") else -1.0
            sl0, entry = cf.initial_stop(p), cf._num(t.get("entry_price"))
            te, tc = s0._ts(t.get("timestamp")), s0._ts(t.get("closed_at"))
            if sl0 is None or entry is None or not te or not tc or tc <= te or abs(entry - sl0) <= 0:
                excluded["geometry_or_times_missing"] += 1
                continue
            lab = cf.net_r_for_trade(dict(t, stop_loss=sl0))
            if lab is None:
                excluded["realised_net_r_uncomputable"] += 1
                continue
            r_dist = abs(entry - sl0)
            idx = [i for i, ts in enumerate(times) if ts >= te and ts + s0.TF_S[tf] <= tc]
            idx = [i for i in idx if i + 1 < len(bars) and bars[i + 1]["time"] < tc]
            if not idx:
                excluded["no_closed_bar_before_close"] += 1
                continue
            fee_r, fund_r, slip_r, stack = cf.cost_legs(t, sym, entry, r_dist, lab["risk_usd"])
            meta = cf._meta(p)
            rows.append({"package": pid, "leg": t.get("strategy_name"), "symbol": sym, "tf": tf, "account": t.get("account_id"),
                         "side": int(side), "month": datetime.fromtimestamp(te, timezone.utc).strftime("%Y-%m"),
                         "te": te, "tc": tc, "hold": round(lab["net_R"], 6), "fee_r": round(fee_r, 6), "fund_r": round(fund_r, 6),
                         "slip_r": round(slip_r, 6), "cost_stack": stack, "decision_bar": meta.get("decision_bar"),
                         "tn": [bars[i + 1]["time"] for i in idx],
                         "close_r": [round(side * (bars[i]["close"] - entry) / r_dist, 4) for i in idx],
                         "next_open_r": [round(side * (bars[i + 1]["open"] - entry) / r_dist, 4) for i in idx]})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(json.dumps({"packages_pool": len(by_pkg), "rows": len(rows), "excluded": dict(excluded),
                      "first_entry": min((r["month"] for r in rows), default=None)}))
    return 0


def _close_net(r: dict, k: int) -> float:
    span = r["tc"] - r["te"]
    frac = min(1.0, max(0.0, (r["tn"][k] - r["te"]) / span))
    return r["next_open_r"][k] - r["fee_r"] - r["slip_r"] - r["fund_r"] * frac


def fire_index(r: dict, spec: str) -> Optional[int]:
    kind, *args = spec.split(":")
    h = float(args[0]) * 3600.0
    k = next((i for i, tn in enumerate(r["tn"]) if tn >= r["te"] + h), None)
    if k is None:
        return None
    if kind == "ts":
        return k
    x = float(args[1])
    if kind == "stall":
        return k if max(r["close_r"][:k + 1]) < x else None
    if kind == "weak":
        return k if r["close_r"][k] < x else None
    raise ValueError(f"unknown arm kind {kind!r}")


def boot(xs: List[float], rng: random.Random, alpha: float, one_sided: bool = False) -> Optional[List[float]]:
    if len(xs) < 2:
        return None
    n = len(xs)
    ms = sorted(statistics.fmean(rng.choice(xs) for _ in range(n)) for _ in range(DRAWS))
    if one_sided:
        return [round(ms[int(alpha * DRAWS)], 4), None]
    return [round(ms[int(alpha / 2 * DRAWS)], 4), round(ms[min(DRAWS - 1, int((1 - alpha / 2) * DRAWS))], 4)]


def grade(a: argparse.Namespace) -> int:
    rows = [json.loads(ln) for ln in Path(a.paths).read_text().splitlines() if ln.strip()]
    if a.legs:
        keep = set(a.legs.split(","))
        rows = [r for r in rows if r["leg"] in keep]
    rng = random.Random(SEED)
    k_arms = len(a.arm)
    out_arms: Dict[str, Any] = {}
    for spec in a.arm:
        fired = [(r, fire_index(r, spec)) for r in rows]
        fired = [(r, k) for r, k in fired if k is not None and r["tn"][k] < r["tc"]]
        d, dr = [], []
        by_m: Dict[str, List[float]] = defaultdict(list)
        by_leg: Dict[str, List[float]] = defaultdict(list)
        for r, k in fired:
            delta = _close_net(r, k) - r["hold"]
            rr = random.Random(f"{SEED}:{r['package']}:{spec}")
            elig = [i for i, tn in enumerate(r["tn"]) if tn < r["tc"]]
            rand = statistics.fmean(_close_net(r, rr.choice(elig)) for _ in range(N_RANDOM))
            d.append(delta)
            dr.append(rand - r["hold"])
            by_m[r["month"]].append(delta)
            by_leg[r["leg"]].append(delta)
        n_all = len(rows)
        mean_d = statistics.fmean(d) if d else None
        ci_b = boot(d, rng, 0.05 / k_arms)
        lo1 = boot(d, rng, 0.05, one_sided=True)
        months = {m: {"n": len(v), "mean": round(statistics.fmean(v), 4)} for m, v in sorted(by_m.items())}
        big = [m for m, v in by_m.items() if len(v) >= a.month_min_n]
        pos = [m for m in big if statistics.fmean(by_m[m]) >= 0]
        gain = sum(d)
        top_m = max((sum(v) for v in by_m.values()), default=0.0)
        edge = [x - y for x, y in zip(d, dr)]
        c = {"n_floor": len(d) >= a.n_floor,
             "mean_ge_0": mean_d is not None and mean_d >= 0,
             "noninferior_lb": bool(lo1) and lo1[0] is not None and lo1[0] >= -a.margin,
             "month_stability": bool(big) and len(pos) >= a.month_pos_min and len(big) >= a.month_pos_min,
             "no_single_month_gt_half": gain <= 0 or top_m <= 0.5 * gain}
        beat = mean_d is not None and bool(ci_b) and ci_b[0] > 0
        verdict = ("PASS_BEATS_HOLD" if all(c.values()) and beat else "PASS_NONINFERIOR" if all(c.values())
                   else "FAIL" if (len(d) >= a.n_floor and mean_d is not None and mean_d < 0) else "INDETERMINATE")
        out_arms[spec] = {"n_fired": len(d), "n_population": n_all, "share_fired": round(len(d) / n_all, 3) if n_all else None,
                          "mean_delta_vs_hold": round(mean_d, 4) if d else None, "sum_delta_vs_hold": round(gain, 3) if d else None,
                          "book_mean_delta_all_packages": round(gain / n_all, 4) if n_all else None,
                          "ci_bonferroni_delta": ci_b, "ci_onesided_lb95": lo1, "mean_random_delta_vs_hold": round(statistics.fmean(dr), 4) if dr else None,
                          "mean_edge_vs_random": round(statistics.fmean(edge), 4) if edge else None, "hit_rate": round(sum(1 for x in d if x > 0) / len(d), 3) if d else None,
                          "by_month": months, "by_leg": {k: {"n": len(v), "mean": round(statistics.fmean(v), 4)} for k, v in sorted(by_leg.items())},
                          "clauses": c, "beats_hold_bonferroni": beat, "verdict": verdict}
    ml = [r for r in rows if r["leg"] == "ml_entry"]
    doc = {"schema": "ltr_timestop_s0/v1", "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "population": {"packages": len(rows), "ml_entry_packages": len(ml), "by_leg": dict(Counter(r["leg"] for r in rows)),
                          "first_entry": min((r["month"] for r in rows), default=None),
                          "mean_hold_all": round(statistics.fmean(r["hold"] for r in rows), 4) if rows else None},
           "rule": {"n_floor": a.n_floor, "noninferiority_margin_r": a.margin, "arms_in_family": k_arms,
                    "month_min_n": a.month_min_n, "month_pos_min": a.month_pos_min},
           "arms": out_arms, "read_state": "ok" if rows else "no_rows"}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "verdict.json").write_text(json.dumps(doc, indent=1) + "\n")
    for spec, v in out_arms.items():
        print(f"{spec:14s} n={v['n_fired']:4d} dMean={v['mean_delta_vs_hold']} dRand={v['mean_random_delta_vs_hold']} "
              f"ciB={v['ci_bonferroni_delta']} lb95={v['ci_onesided_lb95']} -> {v['verdict']}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--trades", required=True)
    b.add_argument("--packages", required=True)
    b.add_argument("--cache", required=True)
    b.add_argument("--out", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--paths", required=True)
    g.add_argument("--arm", action="append", required=True)
    g.add_argument("--legs", default="", help="comma list restricting the population (default: every leg in the corpus)")
    g.add_argument("--n-floor", type=int, default=100)
    g.add_argument("--margin", type=float, default=0.05, help="non-inferiority margin in R on the one-sided 95%% lower bound")
    g.add_argument("--month-min-n", type=int, default=8)
    g.add_argument("--month-pos-min", type=int, default=3)
    g.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    return build(a) if a.cmd == "build" else grade(a)


if __name__ == "__main__":
    sys.exit(main())
