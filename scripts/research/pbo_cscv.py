#!/usr/bin/env python3
# wiring: manual-only - design docs/research/measure-read-ledger-pbo-design-2026-11-28.md § 4 (row MEASURE-READ-LEDGER-PBO); first consumer the f1a0 arms' series.json (ml_entry_fix_arms --emit-series), then trial_ledger
"""PROBABILITY OF BACKTEST OVERFITTING (PBO) by Combinatorially Symmetric Cross-Validation (Bailey, Borwein, Lopez de Prado
& Zhu 2014): how often does the configuration chosen IN-SAMPLE land below the median OUT-OF-SAMPLE?

REPORT-ONLY. Gates this adds or changes: none (a PBO ceiling on promotion is operator proposal D-C in the design, deferred).

INPUT: a T x N matrix of per-period net R (rows = periods, e.g. ISO weeks of entry; columns = the N candidate
configurations the selection chose among), net of the full cost stack. Read from one or more ``series.json`` files
(``ml_entry_fix_arms.py --emit-series``: {"weeks": [...], "matrix": {config: [..]}}); several files are merged on the
week key, a column named in more than one file must agree (the shared ``base`` arm), else the run refuses.

METHOD: split the T periods into S contiguous blocks (S even). For every one of the C(S, S/2) ways to pick S/2 blocks as
in-sample (IS; the complement is out-of-sample, OOS): rank configs by IS mean; take the IS-best n*; omega = the OOS
relative rank of n* in (0, 1) (rank / (N + 1)); lambda = logit(omega). PBO = share of splits with lambda <= 0 (the
IS winner at or below the OOS median). Also: the OOS-on-IS slope of the winners' performance (degradation), and the
share of splits where the IS winner LOSES OOS (mean <= 0).

Reported read_state: ``no_series`` (no file), ``too_few_configs`` (N < 2), ``too_few_periods`` (T < 4 * S), else measured.

    python3 scripts/research/pbo_cscv.py --series A/series.json B/series.json [--blocks 16] [--out DIR]
    python3 scripts/research/pbo_cscv.py --self-test
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
from pathlib import Path
from typing import Any


def load_series(paths: list[str]) -> tuple[list[str], dict[str, list[float]]]:
    """Merge series.json files on the week key. A config in several files must carry the same values."""
    weeks: set[str] = set()
    cols: dict[str, dict[str, float]] = {}
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        w = list(d.get("weeks") or [])
        weeks |= set(w)
        for name, vals in (d.get("matrix") or {}).items():
            col = dict(zip(w, (float(v) for v in vals)))
            if name in cols:
                shared = set(col) & set(cols[name])
                if any(abs(col[k] - cols[name][k]) > 1e-9 for k in shared):
                    raise ValueError(f"config {name!r} differs between series files: not one configuration")
                cols[name].update(col)
            else:
                cols[name] = col
    order = sorted(weeks)
    return order, {n: [c.get(w, 0.0) for w in order] for n, c in sorted(cols.items())}


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def cscv(matrix: dict[str, list[float]], blocks: int = 16) -> dict[str, Any]:
    names = list(matrix)
    n, t = len(names), len(next(iter(matrix.values()))) if matrix else 0
    if n < 2:
        return {"read_state": "too_few_configs", "n_configs": n}
    if blocks % 2 or blocks < 2:
        raise ValueError("--blocks must be an even number >= 2")
    if t < 4 * blocks:
        return {"read_state": "too_few_periods", "n_periods": t, "blocks": blocks, "need": 4 * blocks}
    edges = [round(i * t / blocks) for i in range(blocks + 1)]
    idx = [list(range(edges[i], edges[i + 1])) for i in range(blocks)]
    lambdas, is_best, oos_best, oos_loss = [], [], [], 0
    for combo in itertools.combinations(range(blocks), blocks // 2):
        ins = [r for b in combo for r in idx[b]]
        oos = [r for b in range(blocks) if b not in combo for r in idx[b]]
        is_perf = {c: _mean([matrix[c][r] for r in ins]) for c in names}
        oos_perf = {c: _mean([matrix[c][r] for r in oos]) for c in names}
        best = max(names, key=lambda c: (is_perf[c], c))                    # ties broken by name: deterministic
        rank = 1 + sum(oos_perf[c] < oos_perf[best] for c in names) + 0.5 * (sum(oos_perf[c] == oos_perf[best] for c in names) - 1)
        omega = rank / (n + 1)
        lambdas.append(math.log(omega / (1 - omega)))
        is_best.append(is_perf[best])
        oos_best.append(oos_perf[best])
        oos_loss += oos_perf[best] <= 0
    k = len(lambdas)
    mx, my = _mean(is_best), _mean(oos_best)
    vx = sum((x - mx) ** 2 for x in is_best)
    slope = (sum((x - mx) * (y - my) for x, y in zip(is_best, oos_best)) / vx) if vx > 0 else None
    return {"read_state": "measured", "n_configs": n, "n_periods": t, "blocks": blocks, "splits": k,
            "pbo": round(sum(lam <= 0 for lam in lambdas) / k, 4),
            "prob_oos_loss_of_is_winner": round(oos_loss / k, 4),
            "degradation_slope_oos_on_is": round(slope, 4) if slope is not None else None,
            "median_lambda": round(sorted(lambdas)[k // 2], 4), "configs": names}


def self_test() -> None:
    rng = random.Random(20261128)
    t, n = 160, 20
    noise = {f"c{i}": [rng.gauss(0, 1) for _ in range(t)] for i in range(n)}
    r = cscv(noise, blocks=8)
    assert r["read_state"] == "measured" and 0.30 <= r["pbo"] <= 0.70, r          # skill-free: PBO near 1/2
    planted = dict(noise)
    planted["edge"] = [rng.gauss(0.8, 1) for _ in range(t)]                     # one real edge among noise
    r2 = cscv(planted, blocks=8)
    assert r2["pbo"] <= 0.10 and r2["prob_oos_loss_of_is_winner"] <= 0.10, r2
    assert cscv(planted, blocks=8) == r2                                         # deterministic
    assert cscv({"a": [0.0] * 10}, blocks=2)["read_state"] == "too_few_configs"
    assert cscv({"a": [0.0] * 10, "b": [1.0] * 10}, blocks=4)["read_state"] == "too_few_periods"
    print(f"pbo-cscv self-test OK (noise PBO {r['pbo']}, planted-edge PBO {r2['pbo']})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--series", nargs="*", default=[])
    ap.add_argument("--blocks", type=int, default=16)
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not a.series:
        res: dict[str, Any] = {"read_state": "no_series", "why": "no --series file given"}
    else:
        weeks, matrix = load_series(a.series)
        res = cscv(matrix, a.blocks) | {"series": a.series, "period": "iso_week", "first": weeks[0] if weeks else None,
                                         "last": weeks[-1] if weeks else None}
    print(json.dumps(res, default=str))
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "pbo.json").write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
