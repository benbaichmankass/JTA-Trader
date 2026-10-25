#!/usr/bin/env python3
# wiring: research/queue units RQ-20261025-d7e6-01 and -05 (pooled paired read of exit_lever_ablation arms) via research-script-run.yml
"""POOLED PAIRED READ of per-leg exit_lever_ablation arms (Tier-1 research tooling).

WHY (lane EXITS-ROUND2-1026; RESULTS-GRADE-1025 finding + docs/research/exit-failed-levers-diag-2026-10-24): a lever's
registered bar of 0.02 R/trade sits BELOW what one leg's n can resolve. MEASURED 2026-10-25 from the committed arm emits of
RQ-20261022-eba2-07 / -08 (ada / xrp pullback 2h, n 402 / 394): the sd of the PAIRED per-entry difference (arm minus
incumbent A) is 0.41 / 0.31 R for a 50% bank and 0.69 R for a tight trail, so the minimum detectable per-trade effect at
alpha 0.05 one-sided, power 0.80 is 2.487 * sd / sqrt(n) = 0.051 / 0.039 / 0.086 R/trade on ONE leg. A per-leg FAIL on a
0.02 R bar is therefore "nothing detectable", not "the lever lost". Pooling the legs that carry the same lever is the
design that reaches the floor: this module reads each leg's kept arm emits (comms/research/<unit>/<run>/arms/
<ARM>__trades.jsonl), pairs the arms on (leg, entry_time, direction) and grades the POOLED difference.

THE CONSTRUCTION
  * cluster key = (leg, entry_time, direction). diff_k = net_r(arm) - net_r(baseline), a side missing from one arm counts
    as 0 R there (a lever that changes re-entry changes the entry set; that is net R the lever really earned or lost).
  * pooled mean diff per baseline trade = sum(diff) / n(baseline).
  * CI: moving-block bootstrap over calendar months of the pooled clusters (the unit is the month, not the trade: trades
    of the five alts overlap in time), 4000 resamples, seed fixed by --seed.
  * folds: ``--folds`` equal spans of the pooled entry range; a fold is a win when the arm's pooled net R in it is >=
    the baseline's.
  * maxDD: pooled equity (all legs, trades ordered by exit time); arm maxDD must be <= --dd-mult x baseline's.
  * MDE (reported, and a verdict input): 2.487 * paired_sd / sqrt(n(baseline)).

THE REGISTERED RULE (every threshold is a flag the unit passes; none is defaulted here)
  INDETERMINATE if a unit's arm files are missing, if pooled n(baseline) < --min-n, or if the MDE exceeds --bar (the bar
        is below what the pool can resolve: said so, never graded);
  PASS  if the candidate's pooled diff per baseline trade >= --bar AND the bootstrap CI lower bound > 0 AND fold wins >=
        --fold-majority of --folds AND maxDD <= --dd-mult x baseline's AND, for each --control, candidate minus control
        > 0 with fold wins >= --fold-majority;
  FAIL  if the CI upper bound of (candidate - baseline) < --bar;
  otherwise INDETERMINATE ('unresolved': neither a pass nor a fail; the rule has no third outcome, so none is invented).

Changes no config, places no order; writes only under --out.

    python3 scripts/research/pool_arm_diff.py --self-test
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

Z_SUM = 1.644854 + 0.841621  # one-sided alpha 0.05 + power 0.80


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def find_arm_file(unit: str, arm: str, root: Path) -> Optional[Path]:
    """The newest kept emit of ``arm`` for ``unit`` (comms/research/<unit>/<run>/arms/<arm>__trades.jsonl)."""
    hits = sorted(
        glob.glob(
            str(
                root
                / "comms"
                / "research"
                / unit
                / "*"
                / "arms"
                / f"{arm}__trades.jsonl"
            )
        )
    )
    return Path(hits[-1]) if hits else None


def load_arm(path: Path, leg: str) -> List[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows.append(
            {
                "key": (leg, str(r["entry_time"]), r.get("direction") or r.get("side")),
                "entry": _ts(r["entry_time"]),
                "exit": _ts(r.get("exit_time") or r["entry_time"]),
                "net_r": float(r["net_r"]),
            }
        )
    return rows


def max_drawdown(rows: Sequence[dict]) -> float:
    eq = peak = dd = 0.0
    for r in sorted(rows, key=lambda x: x["exit"]):
        eq += r["net_r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def paired(
    base: Sequence[dict], arm: Sequence[dict]
) -> Dict[tuple, Tuple[datetime, float]]:
    """cluster key -> (entry ts, net_r(arm) - net_r(base)); a missing side is 0 R."""
    b = {r["key"]: r for r in base}
    a = {r["key"]: r for r in arm}
    out = {}
    for k in set(a) | set(b):
        ts = (b.get(k) or a[k])["entry"]
        out[k] = (
            ts,
            (a[k]["net_r"] if k in a else 0.0) - (b[k]["net_r"] if k in b else 0.0),
        )
    return out


def fold_edges(entries: Sequence[datetime], n_folds: int) -> List[datetime]:
    lo, hi = min(entries), max(entries)
    step = (hi - lo) / n_folds
    return [lo + step * i for i in range(n_folds)] + [hi]


def fold_of(ts: datetime, edges: Sequence[datetime]) -> int:
    for i in range(len(edges) - 1):
        if ts < edges[i + 1]:
            return i
    return len(edges) - 2


def fold_wins(
    base: Sequence[dict], arm: Sequence[dict], edges: Sequence[datetime]
) -> Tuple[int, List[float]]:
    n = len(edges) - 1
    tot_b, tot_a = [0.0] * n, [0.0] * n
    for r in base:
        tot_b[fold_of(r["entry"], edges)] += r["net_r"]
    for r in arm:
        tot_a[fold_of(r["entry"], edges)] += r["net_r"]
    return sum(1 for x, y in zip(tot_a, tot_b) if x >= y), [
        round(x - y, 4) for x, y in zip(tot_a, tot_b)
    ]


def month_bootstrap(
    diffs: Dict[tuple, Tuple[datetime, float]], n_base: int, reps: int, seed: int
) -> Tuple[float, float]:
    by_month: Dict[Tuple[int, int], float] = defaultdict(float)
    for ts, d in diffs.values():
        by_month[(ts.year, ts.month)] += d
    months = list(by_month.values())
    rng = random.Random(seed)
    means = sorted(
        sum(rng.choice(months) for _ in months) / n_base for _ in range(reps)
    )
    return means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def grade(
    per_leg: Dict[str, Dict[str, List[dict]]],
    *,
    baseline: str,
    candidate: str,
    controls: Sequence[str],
    bar: float,
    min_n: int,
    n_folds: int,
    fold_majority: int,
    dd_mult: float,
    reps: int = 4000,
    seed: int = 20261025,
) -> dict:
    """``per_leg[leg][arm]`` = rows. Returns the verdict record."""
    pool = lambda arm: [r for leg in per_leg for r in per_leg[leg][arm]]  # noqa: E731
    base, cand = pool(baseline), pool(candidate)
    n_base = len(base)
    out: dict = {"n_baseline": n_base, "legs": sorted(per_leg), "bar_r_per_trade": bar}
    if n_base < min_n:
        return {
            **out,
            "verdict": "indeterminate",
            "note": f"pooled n(baseline) {n_base} < {min_n}",
        }
    pair: Dict[tuple, Tuple[datetime, float]] = {}
    for leg in per_leg:
        pair.update(paired(per_leg[leg][baseline], per_leg[leg][candidate]))
    diffs = [d for _, d in pair.values()]
    mean_pt = sum(diffs) / n_base
    mu = sum(diffs) / len(diffs)
    sd = math.sqrt(sum((d - mu) ** 2 for d in diffs) / max(1, len(diffs) - 1))
    mde = Z_SUM * sd / math.sqrt(n_base)
    lo, hi = month_bootstrap(pair, n_base, reps, seed)
    edges = fold_edges([r["entry"] for r in base], n_folds)
    wins, per_fold = fold_wins(base, cand, edges)
    dd_b, dd_c = max_drawdown(base), max_drawdown(cand)
    ctrl = {}
    for c in controls:
        cr = pool(c)
        cp: Dict[tuple, Tuple[datetime, float]] = {}
        for leg in per_leg:
            cp.update(paired(per_leg[leg][c], per_leg[leg][candidate]))
        cw, _ = fold_wins(cr, cand, edges)
        cs = sum(d for _, d in cp.values())
        ctrl[c] = {
            "cand_minus_control_r": round(cs, 4),
            "fold_wins": cw,
            "pass": cs > 0 and cw >= fold_majority,
        }
    out.update(
        {
            "paired_sd_r": round(sd, 4),
            "mde_r_per_trade": round(mde, 4),
            "diff_r_per_baseline_trade": round(mean_pt, 5),
            "ci95_r_per_trade": [round(lo, 5), round(hi, 5)],
            "fold_wins": wins,
            "per_fold_diff_r": per_fold,
            "max_drawdown_r": {"baseline": round(dd_b, 3), "candidate": round(dd_c, 3)},
            "controls": ctrl,
            "net_r": {
                "baseline": round(sum(r["net_r"] for r in base), 3),
                "candidate": round(sum(r["net_r"] for r in cand), 3),
            },
        }
    )
    if mde > bar:
        return {
            **out,
            "verdict": "indeterminate",
            "note": f"MDE {mde:.4f} R/trade > bar {bar}: the pool cannot resolve the bar",
        }
    ok = (
        mean_pt >= bar
        and lo > 0
        and wins >= fold_majority
        and dd_c <= dd_mult * dd_b
        and all(v["pass"] for v in ctrl.values())
    )
    if ok:
        return {
            **out,
            "verdict": "pass",
            "note": f"{candidate} beats {baseline} by {mean_pt:.4f} R/trade pooled (CI lower {lo:.4f}), {wins}/{n_folds} folds, beats {list(ctrl)}",
        }
    if hi < bar:
        return {
            **out,
            "verdict": "fail",
            "note": f"CI upper {hi:.4f} < bar {bar}: {candidate} does not reach the bar on the pool",
        }
    return {
        **out,
        "verdict": "indeterminate",
        "note": f"unresolved: diff {mean_pt:.4f}, CI [{lo:.4f}, {hi:.4f}], folds {wins}/{n_folds}",
    }


def run(a: argparse.Namespace) -> int:
    root = Path(a.root)
    units = dict(u.split("=", 1) for u in a.unit)  # leg=UNIT
    arms = [a.baseline, a.candidate, *a.control]
    per_leg: Dict[str, Dict[str, List[dict]]] = {}
    missing = []
    for leg, unit in units.items():
        per_leg[leg] = {}
        for arm in arms:
            p = find_arm_file(unit, arm, root)
            if p is None:
                missing.append(f"{unit}:{arm}")
            else:
                per_leg[leg][arm] = load_arm(p, leg)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if missing:
        rec = {
            "verdict": "indeterminate",
            "read_state": "unmeasured",
            "n": 0,
            "population": f"arm emits missing: {missing}",
            "measurement": {"missing": missing},
            "note": "arm emits not landed for every leg; nothing pooled",
        }
    else:
        m = grade(
            per_leg,
            baseline=a.baseline,
            candidate=a.candidate,
            controls=a.control,
            bar=a.bar,
            min_n=a.min_n,
            n_folds=a.folds,
            fold_majority=a.fold_majority,
            dd_mult=a.dd_mult,
            seed=a.seed,
        )
        rec = {
            "verdict": m["verdict"],
            "read_state": "measured",
            "n": m["n_baseline"],
            "population": f"{m['n_baseline']} baseline trades pooled over {m['legs']}; arms {arms}; net of the harness's own cost stack (read from the kept emits)",
            "measurement": m,
            "note": m["note"],
        }
    (out / "verdict.json").write_text(
        json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verdict": rec["verdict"], "note": rec["note"]}, indent=1))
    return 0


def _self_test() -> int:
    import subprocess

    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_pool_arm_diff.py"]
    )
    return r.returncode


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    p.add_argument(
        "--unit",
        action="append",
        default=[],
        metavar="LEG=UNIT",
        help="repeatable: the leg's ablation unit id",
    )
    p.add_argument("--baseline", default="A")
    p.add_argument("--candidate")
    p.add_argument("--control", action="append", default=[])
    p.add_argument("--bar", type=float)
    p.add_argument("--min-n", type=int)
    p.add_argument("--folds", type=int)
    p.add_argument("--fold-majority", type=int)
    p.add_argument("--dd-mult", type=float)
    p.add_argument("--seed", type=int, default=20261025)
    p.add_argument("--root", default=".")
    p.add_argument("--out")
    a = p.parse_args(argv)
    if a.self_test:
        return _self_test()
    for need in (
        "candidate",
        "bar",
        "min_n",
        "folds",
        "fold_majority",
        "dd_mult",
        "out",
    ):
        if getattr(a, need) is None:
            p.error(
                f"--{need.replace('_', '-')} is required (thresholds are registered by the unit, never defaulted)"
            )
    if not a.unit:
        p.error("at least one --unit LEG=UNIT")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
