#!/usr/bin/env python3
# wiring: research tooling for AM-V2 Stage B iteration (row AM-V2-STAGE-B-POLICY-ARM); reads the same corpus/bars/heads as am_policy_arm.py; tests/test_am_action_value.py; docs/research/am-v2-stage-b-diagnosis-2026-11-24.md
"""Diagnose WHY the Stage-B head-timed bracket actions lose to their matched random re-timings (RQ-20261124-b5a1-02/04 FAIL R4).

Tier 1 research tooling, DIAGNOSTIC ONLY: grades nothing, claims no holdout, reads only DEV trades (entry < 2026-01-01). For a seeded sample of
cf_bulk shards it re-runs the exact Stage-B replay (``am_policy_arm.run_arm`` / ``decide`` / ``control_specs``) and records, per trade and per
action: the state the action fired in (open_r, bars_open, head scores), the level it set, whether a bank filled and where, and the trade's HOLD
outcome. It also prices SINGLE actions ex post at sampled decision rows (one bank / one tighten / one breakeven move placed at row k and never
re-placed), so the realised value of acting can be read against the state and the heads' scores (is the head's score correlated with the payoff
of acting, or anti-correlated?).

  python3 scripts/research/am_policy_diag.py --heads DIR --out DIR [--shard-every 12] [--max-trades-per-shard 300] [--n-control 10]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import am_policy_arm as P  # noqa: E402
import cf_bars  # noqa: E402
import cf_bulk  # noqa: E402
import cf_core  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

CLASSES = ("tighten", "bank", "loosen")
SINGLE_ROWS = 6          # sampled decision rows per trade for the single-action ex-post pricing


def _r_of(ctx, px):
    return ctx["sign"] * (px - ctx["entry_ref"]) / ctx["r_dist"]


def single_actions(ctx, rows, pred, base_net, rng) -> List[dict]:
    """Ex-post value of ONE action placed at a sampled row k (never re-placed), net of the full cost stack, minus HOLD."""
    out = []
    if not rows:
        return out
    idx = sorted(rng.sample(range(len(rows)), min(SINGLE_ROWS, len(rows))))
    for i in idx:
        row = rows[i]
        k, f = row["k"], row["features"]
        ts = P._close_ts(ctx, ctx["post"], k)
        q50 = max(0.0, float(pred["q0.5"][i]))
        o = f["open_r"]
        acts = {
            "bank_q50": {"ts": ts, "kind": "bank_at", "level": P._px(ctx, o + max(q50, P.TP_MIN_DIST_R)), "frac": 0.5},
            "bank_p1R": {"ts": ts, "kind": "bank_at", "level": P._px(ctx, max(o + P.TP_MIN_DIST_R, 1.0)), "frac": 0.5},
            "tighten_half": {"ts": ts, "kind": "set_stop", "level": P._px(ctx, -1.0 + 0.5 * (o + 1.0))},
            "close_half": {"ts": ts, "kind": "close", "frac": 0.5, "level": None},
        }
        if o > 0.25:
            acts["breakeven"] = {"ts": ts, "kind": "set_stop", "level": P._px(ctx, 0.0)}
        rec = {"k": k, "open_r": round(o, 4), "peak_r": round(f["peak_r"], 4), "mae_r": round(f["mae_r"], 4), "bars_open": f["bars_open"],
               "q50": round(q50, 4), "q90": round(float(pred["q0.9"][i]), 4), "p_stop": round(float(pred["stop_first"][i]), 4),
               "p_dip": round(float(pred["dip_recovers"][i]), 4), "d": {}}
        for name, a in acts.items():
            rec["d"][name] = round(P.run_arm(ctx, [a])["net_r"] - base_net, 5)
        out.append(rec)
    return out


def diag_trade(ctx, rows, pred, thr, n_control, rng) -> dict:
    base = P.run_arm(ctx)
    rec = {"base": round(base["net_r"], 5), "base_reason": base["fills"][-1]["reason"] if base["fills"] else None,
           "base_mfe": base["mfe_r"], "n_rows": len(rows), "tp0_r": P._tp0_r(ctx), "cls": {}}
    for cls in CLASSES:
        specs = P.decide(ctx, rows, pred, thr, [cls]) if rows else []
        if not specs:
            rec["cls"][cls] = {"n": 0}
            continue
        arm = P.run_arm(ctx, [P._spec_action(s) for s in specs])
        kidx = {r["k"]: i for i, r in enumerate(rows)}
        fire = [{"k": s["k"], "open_r": round(rows[kidx[s["k"]]]["features"]["open_r"], 4), "lvl_r": round(_r_of(ctx, s["level"]), 4)} for s in specs]
        cell = {"n": len(specs), "pol": round(arm["net_r"] - base["net_r"], 5), "fire": fire[:40],
                "bank_fill_r": next((round(_r_of(ctx, f["px"]), 4) for f in arm["fills"] if f["reason"] == "partial"), None),
                "pol_reason": arm["fills"][-1]["reason"] if arm["fills"] else None}
        cds, cfire, cbank = [], [], []
        for d in range(n_control):
            cs = P.control_specs(ctx, rows, specs, P.control_rng(ctx["key"], cls, d))
            c = P.run_arm(ctx, [P._spec_action(s) for s in cs]) if cs else base
            cds.append(round(c["net_r"] - base["net_r"], 5))
            if d < 3:
                cfire += [{"k": s["k"], "open_r": round(rows[kidx[s["k"]]]["features"]["open_r"], 4), "lvl_r": round(_r_of(ctx, s["level"]), 4)} for s in cs][:40]
                cbank.append(next((round(_r_of(ctx, f["px"]), 4) for f in c["fills"] if f["reason"] == "partial"), None))
        cell.update({"ctl": cds, "ctl_fire": cfire, "ctl_bank_fill_r": cbank})
        rec["cls"][cls] = cell
    rec["single"] = single_actions(ctx, rows, pred, base["net_r"], rng) if rows else []
    return rec


def main(argv=None) -> int:
    import numpy as np
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--heads", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", default="am-policy-diag")
    ap.add_argument("--shard-every", type=int, default=12)
    ap.add_argument("--shard-offset", type=int, default=0)
    ap.add_argument("--max-trades-per-shard", type=int, default=300)
    ap.add_argument("--n-control", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261124)
    a = ap.parse_args(argv)
    heads = P.Heads(Path(a.heads))
    plan, jobs, chunks = cf_bulk.build_plan(a.run_id, cf_bulk.DEFAULT_MAX_JOBS)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    fh = open(out / "diag.jsonl", "w")
    n_tr = 0
    for si, shard in enumerate(plan["shards"]):
        if (si - a.shard_offset) % a.shard_every:
            continue
        tf, sym = shard["timeframe"], shard["symbol"]
        if tf is None or not cf_bulk.is_crypto(sym):
            continue
        keys = [k for k in chunks[shard["shard_id"]] if str(jobs[k].get("entry_time"))[:10] < P.DEV_END]
        keys = sorted(rng.sample(keys, min(a.max_trades_per_shard, len(keys)))) if keys else []
        if not keys:
            continue
        sec = cf_bars.TF_SECONDS[tf]
        hz = lambda j: cf_core.resolve_horizon({"timeframe": tf}, {"timeframe": tf, **({"max_hold_bars": mb} if (mb := cf_bulk.timeout_bars_for(j.get("strategy"))) else {})})["seconds"]  # noqa: E731
        try:
            lo = min(lrc._ts(jobs[k]["entry_time"]) for k in keys) - P.PRE_BARS * sec
            hi = max(lrc._ts(jobs[k]["exit_time"]) + hz(jobs[k]) for k in keys)
            store = cf_bulk.BarStore(cf_bars.historical_bars(sym, tf, lo, hi))
        except Exception as e:   # allow-silent: diagnostic sample; a failed fetch skips the shard and is printed
            print(json.dumps({"shard": shard["shard_id"], "fetch_failed": str(e)[:200]}), flush=True)
            continue
        items, mats = [], defaultdict(list)
        for key in keys:
            job = dict(jobs[key], trade_key=key)
            t_row, t_exit = lrc._ts(job["entry_time"]), lrc._ts(job["exit_time"])
            fold = heads.fold_of(t_row) if t_row else None
            if fold is None or t_exit is None:
                continue
            ctx = P.make_ctx(job, store.window(t_row - P.PRE_BARS * sec, t_exit + hz(job)), tf)
            if ctx is None:
                continue
            rows = P.decision_rows(ctx)
            if not rows:
                continue
            it = [key, job, ctx, rows, fold, None]
            items.append(it)
            mats[fold["fold_id"]].append((it, P.feature_matrix(ctx, rows, heads.strat.get(str(job.get("strategy")), -1))))
        for fid, lst in mats.items():
            p = heads.predict(fid, np.vstack([m for _, m in lst]))
            i = 0
            for it, m in lst:
                it[5] = {h: p[h][i:i + len(m)] for h in p}
                i += len(m)
        for key, job, ctx, rows, fold, pred in items:
            rec = diag_trade(ctx, rows, pred, fold["thresholds"], a.n_control, rng)
            rec.update({"key": key, "st": job.get("strategy"), "sy": sym, "tf": tf, "e": job.get("entry_time"), "f": fold["fold_id"]})
            fh.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
            n_tr += 1
        fh.flush()
        print(json.dumps({"shard": shard["shard_id"], "n": len(items), "total": n_tr}), flush=True)
    fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
