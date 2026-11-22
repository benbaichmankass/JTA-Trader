#!/usr/bin/env python3
# wiring: research/queue units authored by RESEARCH-FILL-20261122 (run.command via research-script-run.yml; reads COMMITTED tagged trades, no trainer)
"""PER-CELL MARGINAL GRADE of the authored regime-router OFF-cells (lane RESEARCH-FILL-20261122; PI-20261122-HOPS0847-0001).

RQ-20261120-d7c2-01 graded the BTC router cells POOLED (228 dropped trades over 3 legs: added_r +11.57, 4 of 6 folds, matched-random
p 0.35 -> FAIL). A pooled grade cannot say WHICH cell earns its keep and which only rides along, so no single cell can be kept
or proposed for removal on it. This grades each authored OFF-cell on its own, on the SAME committed per-trade tagged rows the
pooled run measured (comms/research/RQ-20261120-d7c2-01/<run>/legs/<leg>__tagged.jsonl: net of fee + slippage + funding,
tagged with ADX regime and the replayed vol label). Nothing is re-run and no trainer is touched.

Per (leg, cell = trend/vol/direction), over the trades with a label, in the window:
  n          trades the cell would veto;  added_r = -(sum net_r of those trades)   (> 0: vetoing them added R)
  folds      FOLDS equal-width calendar folds of the leg's own span: the cell's added_r per fold; `active` = folds with >= 1 veto
  control_p  MATCHED-DROP control: (#draws with added_r >= actual + 1)/(draws + 1), each draw dropping n trades of the SAME
             leg and SAME direction at random (the null: does this cell beat vetoing the same number of arbitrary trades?)
  years      per calendar year n and added_r (regime-robustness table; the cell is not graded on it)
Verdict per cell (thresholds fixed by the unit, never moved after a result):
  indeterminate_underpowered  n < MIN_N
  fail                        n >= MIN_N AND added_r <= 0           (the veto cost R: a Tier-3 REMOVAL case, the manager's)
  pass                        n >= MIN_N AND added_r > 0 AND control_p <= ALPHA AND active >= 3 AND wins >= ceil(2/3 * active)
  indeterminate               n >= MIN_N AND added_r > 0 but the control or the fold stability is not met
The run verdict: pass iff every authored cell is pass; fail iff any cell is fail; indeterminate otherwise (per-cell rows are the
product). Writes <out>/verdict.json (+ cells.json). Tier-1 research tooling: reads committed files, writes --out only.

    python3 scripts/research/regime_cell_marginal_grade.py --out O [--leg trend_donchian=PATH ...] [--since 2026-07-01]
    python3 scripts/research/regime_cell_marginal_grade.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import regime_gate_family_consumer as G

MIN_N = 25
FOLDS = 6
ALPHA = 0.05
DRAWS = 5000
SEED = 20261112
DEFAULT_RUN = "comms/research/RQ-20261120-d7c2-01"


def default_legs() -> dict[str, str]:
    runs = sorted((REPO / DEFAULT_RUN).glob("*/legs"))
    if not runs:
        return {}
    d = runs[-1]
    return {p.name.split("__")[0]: str(p) for p in sorted(d.glob("*__tagged.jsonl"))}


def grade_cell(rows: list[dict], cell: tuple[str, str, str], t0: float, t1: float, folds: int = FOLDS,
               draws: int = DRAWS, seed: int = SEED, min_n: int = MIN_N) -> dict:
    trend, vol, side = cell
    drop = [r for r in rows if r.get("regime") == trend and r.get("vol_regime") == vol and str(r["direction"]).lower() == side]
    added = -sum(r["net_r"] for r in drop)
    width = (t1 - t0) / folds or 1.0
    fa = [0.0] * folds
    fn = [0] * folds
    for r in drop:
        i = min(folds - 1, int((r["_t"] - t0) / width))
        fa[i] -= r["net_r"]
        fn[i] += 1
    active = sum(1 for k in fn if k)
    wins = sum(1 for x, k in zip(fa, fn) if k and x > 0)
    pool = [r for r in rows if str(r["direction"]).lower() == side]
    ge = None
    if drop and pool:
        rng = random.Random(seed)
        ge = 0
        k = min(len(drop), len(pool))
        for _ in range(draws):
            ge += (-sum(r["net_r"] for r in rng.sample(pool, k))) >= added
    p = round((ge + 1) / (draws + 1), 4) if ge is not None else None
    years: dict[str, dict] = {}
    for r in drop:
        y = datetime.fromtimestamp(r["_t"], timezone.utc).strftime("%Y")
        d = years.setdefault(y, {"n": 0, "added_r": 0.0})
        d["n"] += 1
        d["added_r"] = round(d["added_r"] - r["net_r"], 4)
    if len(drop) < min_n:
        verdict = "indeterminate_underpowered"
    elif added <= 0:
        verdict = "fail"
    elif p is not None and p <= ALPHA and active >= 3 and wins >= math.ceil(2 * active / 3):
        verdict = "pass"
    else:
        verdict = "indeterminate"
    return {"cell": "/".join(cell), "n": len(drop), "added_r": round(added, 4), "control_p": p, "folds_active": active,
            "fold_wins": wins, "fold_added_r": [round(x, 4) for x in fa], "years": years, "verdict": verdict}


def run(legs: dict[str, str], policy: str, since: str | None, folds: int, draws: int, seed: int, min_n: int) -> dict:
    loaded = G.load_legs(legs)
    sinc = G._ts(since) if since else None
    out_legs, flat, missing = {}, [], []
    for leg, rows in loaded.items():
        if sinc is not None:
            rows = [r for r in rows if r["_t"] >= sinc]
        cells = sorted(G.load_cells(policy, leg))
        if not cells:
            missing.append(leg)
        if not rows:
            out_legs[leg] = {"trades": 0, "cells": []}
            continue
        t0, t1 = min(r["_t"] for r in rows), max(r["_t"] for r in rows)
        res = [grade_cell(rows, c, t0, t1, folds, draws, seed, min_n) for c in cells]
        out_legs[leg] = {"trades": len(rows), "span": [t0, t1], "cells": res}
        flat += [{"leg": leg, **c} for c in res]
    if not flat:
        verdict, why = "not_applicable", "no authored cell graded (no legs, no rows, or no cells in the policy)"
    elif any(c["verdict"] == "fail" for c in flat):
        verdict, why = "fail", "at least one authored cell lost R when vetoed: " + ", ".join(
            f"{c['leg']}:{c['cell']}" for c in flat if c["verdict"] == "fail")
    elif all(c["verdict"] == "pass" for c in flat):
        verdict, why = "pass", "every authored cell earns its keep against the matched drop"
    else:
        verdict, why = "indeterminate", "no cell failed; " + str(sum(c["verdict"] != "pass" for c in flat)) + " of " + str(len(flat)) + " are not pass"
    return {"verdict": verdict, "read_state": "measured" if flat else "could_not_look", "note": why, "cells": flat,
            "legs": out_legs, "legs_without_authored_cells": missing, "since": since, "folds": folds, "draws": draws,
            "seed": seed, "min_n": min_n, "alpha": ALPHA,
            "population": f"{len(flat)} authored OFF-cells over {len(out_legs)} BTC legs, committed tagged trades net of the full cost stack",
            "n": sum(c["n"] for c in flat) if flat else None}


def _selftest() -> None:
    rng = random.Random(3)
    t0 = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    rows = []
    for i in range(600):
        side = "long" if i % 2 == 0 else "short"
        bad = i % 5 == 0 and side == "long"           # a cell that genuinely loses: trending/volatile/long
        reg, vol = ("trending", "volatile") if bad else rng.choice([("chop", "calm"), ("trending", "calm"), ("chop", "volatile")])
        nr = (-0.8 + rng.gauss(0, 0.3)) if bad else rng.gauss(0.05, 0.9)
        rows.append({"direction": side, "net_r": nr, "regime": reg, "vol_regime": vol, "_t": t0 + i * 86400})
    t1 = rows[-1]["_t"]
    good = grade_cell(rows, ("trending", "volatile", "long"), t0, t1, draws=500)
    assert good["n"] == 60 and good["added_r"] > 0 and good["verdict"] == "pass", good
    empty = grade_cell(rows, ("trending", "volatile", "short"), t0, t1, draws=50)
    assert empty["n"] == 0 and empty["verdict"] == "indeterminate_underpowered" and empty["control_p"] is None, empty
    for r in rows:                                    # flip: the cell now MAKES money, vetoing it costs R
        if r["regime"] == "trending" and r["vol_regime"] == "volatile" and r["direction"] == "long":
            r["net_r"] = abs(r["net_r"]) + 0.2
    bad = grade_cell(rows, ("trending", "volatile", "long"), t0, t1, draws=50)
    assert bad["verdict"] == "fail" and bad["added_r"] < 0, bad
    assert good["years"] and sum(v["n"] for v in good["years"].values()) == 60
    print("self-test OK")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="out/regime_cell_marginal")
    ap.add_argument("--leg", action="append", default=[], help="leg=path to <leg>__tagged.jsonl (default: the committed d7c2-01 legs)")
    ap.add_argument("--policy", default=str(REPO / "config" / "regime_policy.yaml"))
    ap.add_argument("--since", default=None, help="only trades entered on/after this date (e.g. 2026-07-01)")
    ap.add_argument("--folds", type=int, default=FOLDS)
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--min-n", type=int, default=MIN_N)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _selftest()
        return 0
    legs = dict(x.split("=", 1) for x in a.leg) if a.leg else default_legs()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if not legs:
        v = {"verdict": "not_applicable", "read_state": "producer_failed", "population": "no tagged legs found", "n": None,
             "note": f"no {DEFAULT_RUN}/*/legs/*__tagged.jsonl on this checkout and no --leg given"}
        (out / "verdict.json").write_text(json.dumps(v, indent=1))
        print(json.dumps(v))
        return 2
    v = run(legs, a.policy, a.since, a.folds, a.draws, a.seed, a.min_n)
    (out / "cells.json").write_text(json.dumps(v["cells"], indent=1))
    (out / "verdict.json").write_text(json.dumps(v, indent=1))
    for c in v["cells"]:
        print(f"{c['leg']:22s} {c['cell']:26s} n={c['n']:4d} added_r={c['added_r']:8.3f} p={c['control_p']} "
              f"folds {c['fold_wins']}/{c['folds_active']} -> {c['verdict']}")
    print("VERDICT", v["verdict"], "-", v["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
