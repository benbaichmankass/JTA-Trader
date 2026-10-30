#!/usr/bin/env python3
# wiring: manual-only - CF-B0 fidelity check, run by hand or by the bulk-run lane: python3 scripts/research/cf_fidelity.py --corpus v1 --n 1000 --out <dir>
"""Engine fidelity on backtest jobs (CF-B0-ENGINE-LIFT, design § 4.3 "Fidelity first").

For each sampled backtest trade, replay the leg's OWN management through the ONE engine (``cf_core.simulate`` fed the
emitted per-bar stop_r / target_r by ``tm_bench.engine_bars`` + ``leg_actions``) and compare the replayed GROSS R to the
harness ``exit_r``. PASS = |gap| <= ``--tol`` (0.01 R). The pass rate always carries its population (corpus id, legs,
sample size, seed); mismatches are broken down by harness exit_reason and by leg, and each is classified by what the
engine did on the bar the harness exited on, so an engine bias and an adapter bias are not confused.

Gross R is compared (not net) because the harness exit_r is gross; costs are applied identically downstream.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import tm_bench  # noqa: E402

TOL_R = 0.01


def classify(t: dict, sim: dict) -> str:
    """What the engine did relative to the harness's exit bar. Heuristic labels, each backed by a measured field."""
    last = sim["fills"][-1] if sim["fills"] else None
    if last is None:
        return "no_fill"
    sec = tm_bench._sec(t)
    eng_bar = int(round(last["ts"] / sec)) if last["reason"] != "open_at_data_end" else t["bars"]
    exit_bar = t["bars"] - 1
    if last["reason"] == "open_at_data_end":
        return "engine_unresolved_at_data_end"
    if eng_bar < exit_bar:
        return "engine_exits_earlier_than_harness"
    if eng_bar > exit_bar:
        return "engine_exits_later_than_harness"
    return f"same_bar_different_price[{last['reason']}]"


def check(trades: List[dict], cost, tol: float = TOL_R) -> Dict[str, Any]:
    rows = []
    for t in trades:
        net0, info = tm_bench.replay(t, tm_bench.engine_bars(t), tm_bench._cm(t, cost))
        gap = info["gross_r"] - t["exit_r"]
        rows.append({"leg": t["leg"], "exit_reason": t["exit_reason"], "gap": float(gap), "ok": bool(abs(gap) <= tol), "gap_f": float(gap),
                     "why": None if abs(gap) <= tol else classify(t, info["sim"])})
    return {"rows": rows}


def summarize(rows: List[dict], tol: float) -> Dict[str, Any]:
    def agg(sel):
        n = len(sel)
        ok = int(sum(bool(r["ok"]) for r in sel))
        bad = [r["gap"] for r in sel if not r["ok"]]
        return {"n": n, "pass": ok, "pass_rate": None if not n else round(ok / n, 4),
                "mismatch_mean_gap_r": None if not bad else round(sum(bad) / len(bad), 4),
                "mismatch_mean_abs_gap_r": None if not bad else round(sum(abs(x) for x in bad) / len(bad), 4)}
    by_reason, by_leg = defaultdict(list), defaultdict(list)
    for r in rows:
        by_reason[r["exit_reason"]].append(r)
        by_leg[r["leg"]].append(r)
    return {"overall": agg(rows), "tol_r": tol,
            "by_exit_reason": {k: agg(v) for k, v in sorted(by_reason.items())},
            "by_leg": {k: agg(v) for k, v in sorted(by_leg.items())},
            "mismatch_cause": dict(Counter(r["why"] for r in rows if not r["ok"])),
            "mismatch_cause_by_exit_reason": {k: dict(Counter(r["why"] for r in v if not r["ok"])) for k, v in sorted(by_reason.items())}}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="v1", help="tm_bench corpus spec (v1 | synthetic | frozen dir | shard dir)")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--tol", type=float, default=TOL_R)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as td:
        corp, meta = tm_bench.resolve_corpus(a.corpus, work=Path(td))
        cost = lambda sym: tm_bench._cost_policy(sym)  # noqa: E731
        bc = tm_bench.build_corpus(corp, meta, cost_fn=None)
    trades = bc["trades"]
    rng = random.Random(a.seed)
    sample = trades if len(trades) <= a.n else rng.sample(trades, a.n)
    res = check(sample, cost, a.tol)
    out = {"schema": "cf_fidelity/1", "population": {"corpus_id": bc["corpus_id"], "source": bc["source"], "n_corpus": len(trades),
                                                      "n_sampled": len(sample), "seed": a.seed,
                                                      "legs": sorted({t["leg"] for t in trades}), "tol_r": a.tol,
                                                      "compared": "replayed GROSS R vs harness exit_r"},
           "engine": tm_bench.ENGINE_SOURCE, **summarize(res["rows"], a.tol)}
    txt = json.dumps(out, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "fidelity.json").write_text(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
