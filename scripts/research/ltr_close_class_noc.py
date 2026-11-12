#!/usr/bin/env python3
# wiring: manual-only — the run command of research unit RQ-20261112-c1a5-01 (net-of-cost test of the live-review CLOSE class); re-run by a lane when the unit is due. No timer.
"""Net-of-cost test of the live-review CLOSE recommendation class, on a window disjoint from the one it was found on.

    python3 scripts/research/ltr_close_class_noc.py --since 2026-11-01T11:47:00Z --out comms/research/ltr_close_class_noc/verdict.json

Unit RQ-20261112-c1a5-01 (rule registered before any run; see its decision_rule).  Fixes the three defects that made
LTR-CLOSE-CLASS-TEST's number untrustworthy (record: comms/research/ltr_class_grade/VERDICT.md):

* ONE ROW PER ORDER PACKAGE: the FIRST close call on a package.  The audit's 18-21 "calls" were 4 packages
  (the reviewer re-issued ``close`` every cycle), so calls are never the unit.
* DISJOINT WINDOW: only reviews with ``reviewed_at`` strictly after ``--since`` (the last row of the graded W44 record,
  2026-11-01T11:46:42Z, plus a margin), so nothing the class was found on is re-graded.
* A RANDOM-CLOSE CONTROL: the same package closed at the OPEN of a uniformly random bar between the review bar and the
  realised exit, ``--draws`` seeded draws, priced by the same cost stack.  Edge = close delta minus the mean random delta.
* Unpriced packages stay in the denominator with their reason (replay_mismatch was the audit's blocker,
  AUD-20261028-LTR-CLOSE-REPLAY-MISMATCH): a not-applied close is priced ANCHORED ON THE REALISED EXIT
  (close-at-review-open net minus realised net R), which needs no hold replay; an applied close (exit_reason
  live_review_close) is priced by the harness's own paired replay.  ``null`` means could-not-look, never 0.

Pricing is ``live_review_counterfactual.price_all`` unchanged (net of the recorded fee/funding legs + policy slippage;
cost_legs / net_of_costs), the same harness LTR-CLASS-GRADE used, audited there.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import live_review_counterfactual as cf  # noqa: E402
import ltr_class_grade as g  # noqa: E402

SEED, BOOT = 20261112, 10_000
#: rule thresholds, registered in the unit's decision_rule before any run
N_FLOOR, CTL_FLOOR, WEEK_MIN_PKGS, WEEKS_MIN, LEG_SHARE_MAX = 30, 20, 3, 3, 0.5

candles = lru_cache(maxsize=None)(cf.fetch_candles_live)


def first_close_per_package(reviews: List[dict], since: str, until: Optional[str]) -> List[dict]:
    seen: Dict[str, dict] = {}
    for r in sorted(reviews, key=lambda x: x["reviewed_at"]):
        if (r.get("recommendation") or {}).get("action") != "close" or r["reviewed_at"] <= since:
            continue
        if until and r["reviewed_at"] > until:
            continue
        seen.setdefault(r["order_package_id"], r)
    return list(seen.values())


def _price(rv: dict, packages: dict, trades: dict) -> Dict[str, Any]:
    """Close delta vs the realised exit for one package's first close call (net of cost) and its state."""
    captured: List[Optional[float]] = []
    orig_tad, orig_fid = cf.trade_action_delta, cf._fidelity

    def tad(action, rec, **kw):
        captured.append(kw.get("close_net"))
        return orig_tad(action, rec, **kw)

    cf.trade_action_delta = tad
    cf._fidelity = lambda h, r: "replay_matches_realised" if h is not None else "unvalidated"   # anchor on the realised exit
    try:
        r = cf.price_all([rv], packages, trades, candles)[0]
    finally:
        cf.trade_action_delta, cf._fidelity = orig_tad, orig_fid
    if r["state"] != "priced":
        return {"state": "unpriced", "reason": r.get("reason")}
    out = r["outcome"]
    if out.get("applied"):
        return {"state": "priced", "delta_r": out["delta_r"], "anchor": "applied_paired_replay", "net_r": out["net_r"]}
    if not captured or captured[-1] is None:
        return {"state": "unpriced", "reason": "close_at_open_unresolved"}
    return {"state": "priced", "delta_r": captured[-1] - out["net_r"], "anchor": "realised_exit", "net_r": out["net_r"]}


def _random_close_delta(rv: dict, packages: dict, trades: dict, draws: int, rng: random.Random) -> Optional[float]:
    """Mean delta of closing at the open of a uniformly random bar in [review bar, realised exit)."""
    pkg = packages.get(rv["order_package_id"]) or {}
    tid = rv.get("trade_id") if rv.get("trade_id") is not None else pkg.get("linked_trade_id")
    tr = trades.get(int(tid)) if tid is not None else None
    t_close = cf._ts((tr or {}).get("closed_at"))
    if not t_close:
        return None
    orig = cf.exit_at_open
    ds: List[float] = []

    def rand_exit(bars, *, side, entry, r_dist, start_ts):
        pool = [b for b in bars if start_ts <= b["time"] < t_close]
        if not pool:
            return None
        b = rng.choice(pool)
        sign = 1.0 if side == "long" else -1.0
        return {"gross_r": sign * (b["open"] - entry) / r_dist, "ts": b["time"], "reason": "close"}

    cf.exit_at_open = rand_exit
    try:
        for _ in range(draws):
            p = _price(rv, packages, trades)
            if p["state"] == "priced" and p["anchor"] == "realised_exit":
                ds.append(p["delta_r"])
    finally:
        cf.exit_at_open = orig
    return statistics.fmean(ds) if ds else None


def boot_mean_ci(xs: List[float], rng: random.Random) -> Optional[List[float]]:
    if len(xs) < 2:
        return None
    ms = sorted(statistics.fmean(rng.choice(xs) for _ in xs) for _ in range(BOOT))
    return [round(ms[int(0.025 * BOOT)], 4), round(ms[int(0.975 * BOOT) - 1], 4)]


def grade(rows: List[dict], rng: random.Random) -> Dict[str, Any]:
    pr = [x for x in rows if x["state"] == "priced"]
    n = len(pr)
    d = [x["delta_r"] for x in pr]
    with_ctl = [x for x in pr if x.get("random_delta_r") is not None]
    edge = [x["delta_r"] - x["random_delta_r"] for x in with_ctl]
    by_week: Dict[str, List[float]] = defaultdict(list)
    for x in pr:
        by_week[g._week(x["reviewed_at"])].append(x["delta_r"])
    legs = Counter(x["leg"] for x in pr)
    mean = statistics.fmean(d) if d else None
    ci, eci = boot_mean_ci(d, rng), boot_mean_ci(edge, rng)
    best = max(by_week, key=lambda w: sum(by_week[w])) if by_week else None
    rest = [v for w, vs in by_week.items() if w != best for v in vs]
    dbw = statistics.fmean(rest) if rest else None
    big_weeks = [w for w, vs in by_week.items() if len(vs) >= WEEK_MIN_PKGS]
    c = {
        "C1_n": n >= N_FLOOR,
        "C2_mean_pos": bool(mean is not None and mean > 0),
        "C3_ci_lo_pos": bool(ci and ci[0] > 0),
        "C4_beats_random": bool(len(with_ctl) >= CTL_FLOOR and eci and statistics.fmean(edge) > 0 and eci[0] > 0),
        "C5_regime": bool(len(big_weeks) >= WEEKS_MIN and dbw is not None and dbw > 0
                          and sum(1 for w in big_weeks if statistics.fmean(by_week[w]) > 0) * 2 > len(big_weeks)),
        "C6_leg_spread": bool(n and max(legs.values()) / n <= LEG_SHARE_MAX),
    }
    if n < N_FLOOR:
        v, why = "INDETERMINATE", f"C1: {n} priced packages < {N_FLOOR} (accruing)"
    elif mean is not None and (mean <= 0 or (ci and ci[1] < 0)):
        v, why = "FAIL", f"mean {mean:.4f} / CI95 {ci}"
    elif all(c.values()):
        v, why = "PASS", "C1-C6 hold"
    else:
        v, why = "INDETERMINATE", "failed: " + ",".join(k for k, ok in c.items() if not ok)
    return {"verdict": v, "why": why, "clauses": c, "n_priced_packages": n, "mean_delta_r": None if mean is None else round(mean, 4),
            "ci95_mean": ci, "n_with_random_control": len(with_ctl),
            "mean_edge_vs_random": round(statistics.fmean(edge), 4) if edge else None, "ci95_edge": eci,
            "mean_random_delta_r": round(statistics.fmean(x["random_delta_r"] for x in with_ctl), 4) if with_ctl else None,
            "drop_best_week_mean": None if dbw is None else round(dbw, 4), "best_week": best,
            "by_week": {w: {"n": len(v), "mean": round(statistics.fmean(v), 4)} for w, v in sorted(by_week.items())},
            "by_leg": dict(legs), "anchors": dict(Counter(x["anchor"] for x in pr))}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2026-11-01T11:47:00Z", help="exclusive lower bound on reviewed_at (disjoint from W44)")
    ap.add_argument("--until", default=None, help="inclusive upper bound; default = every row at run time")
    ap.add_argument("--refs", default="origin/main,origin/live-review/rows")
    ap.add_argument("--draws", type=int, default=200)
    ap.add_argument("--out", default=str(REPO / "comms/research/ltr_close_class_noc/verdict.json"))
    a = ap.parse_args(argv)
    rng = random.Random(SEED)

    src = g.load_reviews(a.refs.split(","))
    firsts = first_close_per_package(src["rows"], a.since, a.until)
    j = g.load_journal()
    packages, trades = j["packages"], j["trades"]
    rows = []
    for rv in firsts:
        p = _price(rv, packages, trades)
        row = {"package": rv["order_package_id"], "review_id": rv["review_id"], "reviewed_at": rv["reviewed_at"],
               "leg": rv.get("leg"), "accounts": rv.get("accounts") or [], **p}
        row["random_delta_r"] = (_random_close_delta(rv, packages, trades, a.draws, rng)
                                 if p["state"] == "priced" and p["anchor"] == "realised_exit" else None)
        rows.append(row)
    res = grade(rows, rng)
    out = {"schema": "ltr_close_class_noc/v1", "unit": "RQ-20261112-c1a5-01",
           "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "window": {"since_exclusive": a.since, "until": a.until}, "seed": SEED, "draws": a.draws,
           "population": {"refs": src["per_ref"], "n_close_calls_in_window": sum(
               1 for r in src["rows"] if (r.get("recommendation") or {}).get("action") == "close" and r["reviewed_at"] > a.since),
               "n_packages": len(firsts), "unpriced_reasons": dict(Counter(x.get("reason") for x in rows if x["state"] != "priced"))},
           **res, "rows": rows}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
    print(f"packages={len(firsts)} priced={res['n_priced_packages']} mean={res['mean_delta_r']} ci={res['ci95_mean']} "
          f"edge={res['mean_edge_vs_random']} {res['ci95_edge']} -> {res['verdict']}: {res['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
