#!/usr/bin/env python3
"""Held-out, cost-charged E1/E1.5 exit-head test for ONE leg against its CURRENT declared exit.

WHY THIS EXISTS (RQ-20261104-e4a1-01, lane EXIT-HEAD-ETH-REGISTER, operator "Register + gate now")
-------------------------------------------------------------------------------------------------
Every earlier exit-head verdict on trend_donchian_eth_4h (coverage matrix `exit_head_ml`,
2026-07-12 / 07-13 / 08-14) was measured against the bracket the leg had THEN (stop 2.0-2.5 ATR,
trail 5.0, no trail-decay, no measured-move TP revision). The bracket has changed since (#18868 et
seq.), so "does a learned exit beat the exit we run NOW" has no record. The stock E1 trainer
(`scripts/ml/train_exit_head.py`) cannot answer it honestly as-is, for two reasons this driver fixes
WITHOUT re-implementing any primitive:

1. COST BASIS. The trainer's head arm is the GROSS candle mark `open_r` while its baseline is the
   harness NET R, a bias toward PASS (RQ-20260929-401). Every truncated trade here is charged the
   round trip through `src.runtime.execution_costs.roundtrip_cost_r` with the BASELINE ARM'S OWN
   recorded cost stack, plus one side of slippage for the discretionary exit -- the
   `exit_head_final_fold_replay.head_exit_net_r` convention, imported.
2. SELECTION. The trainer's gate reads `max over tau arms` on the fold it grades (hindsight).
   Here an arm is SELECTED on the discovery walk-forward only and read ONCE on a held-out span
   selection never saw (the PROMOTION-BAR-HOLDOUT-1016 / c6f1 design), against a matched
   random-truncation control (practice principle T1).

IMPORTED, UNMODIFIED: `train_exit_head` (FEATURES, EMBARGO_S, TAUS, _SHAPES, load_rows,
group_trades, train_model, matrix, auc_score, policy_model, policy_model_cond, policy_stale,
policy_giveback, fold_blocks) and `exit_head_final_fold_replay.head_exit_net_r`.

INPUTS: the baseline arm's emitted trades + its `__bt.json` (cost stack) from
`exit_lever_ablation.py` (config-exact: the argv builder forwards the leg's declared trail-decay and
tp_revision), and the E0 rows `build_exit_head_dataset.py` built from those trades.

Usage::

    python3 scripts/research/exit_head_holdout.py --rows <e0>/donchian/rows.jsonl \
        --trades <ab>/arms/B__trades.jsonl --bt <ab>/arms/B__bt.json \
        --boundary '2025-04-03 15:00:00+00:00' --tf 4h --json <out>/verdict.json
"""
# wiring: manual-only - the one-off held-out exit-head read for research/queue/RQ-20261104-e4a1-01.yaml
# (run.note); dispatched by a lane, not called from CI.
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ml"))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import numpy as np  # noqa: E402
import train_exit_head as te  # noqa: E402

from src.runtime import execution_costs as ec  # noqa: E402

TF_S = te.TF_S
BLOCK_N = 50            # the trainer's own --min-fold-trades default (derived, never tuned)
AUC_FLOOR = 0.55        # program doc E1 gate
DD_TOL = 1.35           # maxDD(head) <= 1.35 x maxDD(B), the c6f1 / a7c3 tolerance
CONTROL_DRAWS = 2000
CONTROL_PCTL = 95.0
CONTROL_SEED = 20261104
COST_TOL = 1e-3


def _epoch(s: Any) -> float:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def arm_names() -> list[str]:
    out = [f"tau_{t}" for t in te.TAUS]
    out += [f"{s}_tau_{t}" for s in te._SHAPES for t in (0.10, 0.15, 0.20)]
    return out


def exit_index(arm: str, bars: list[dict], probs: np.ndarray) -> int | None:
    """Bar index the arm exits at (None = rides to the declared exit). Uses the trainer's predicates."""
    if arm == "stale_8_0":
        def cond(i):
            return (bars[i]["age_bars"] >= 8 and float(bars[i]["open_r"]) < 0.0)
    elif arm == "giveback_1_1":
        def cond(i):
            return (float(bars[i]["mfe_r"]) >= 1.0 and float(bars[i]["giveback_r"]) >= 1.0)
    elif arm.startswith("tau_"):
        tau = float(arm.split("_")[1])
        def cond(i):
            return (probs[i] < tau)
    else:
        shape, tau = arm.rsplit("_tau_", 1)
        sh, tau = te._SHAPES[shape], float(tau)
        def cond(i):
            return (probs[i] < tau and sh(bars, i))
    for i in range(len(bars)):
        if cond(i):
            return None if i >= len(bars) - 1 else i
    return None


class Pricer:
    """Net R of each trade under an exit index, on the baseline arm's own cost stack."""

    def __init__(self, emit: dict[str, dict], stack: dict[str, float], tf_s: int):
        self.emit, self.stack, self.tf_s = emit, stack, tf_s

    def risk(self, e: dict) -> float:
        return abs(float(e["entry"]) - float(e["sl"]))

    def cost(self, e: dict, exit_price: float, exit_time: Any) -> float:
        return ec.roundtrip_cost_r(
            entry=float(e["entry"]), exit_price=exit_price, risk=self.risk(e),
            entry_time=e["entry_time"], exit_time=exit_time,
            fee_bps_roundtrip=self.stack["fee_bps_roundtrip"],
            slippage_bps_roundtrip=self.stack["slippage_bps_roundtrip"],
            funding_bps_per_window=self.stack["funding_bps_per_window"])["total_cost_r"]

    def baseline_gap(self, e: dict) -> float:
        is_long = str(e["direction"]).lower() in ("long", "buy")
        xp = float(e["entry"]) + (1 if is_long else -1) * float(e["gross_r"]) * self.risk(e)
        emitted = float(e["cost_fee_r"]) + float(e["cost_slippage_r"]) + float(e["cost_funding_r"])
        return abs(emitted - self.cost(e, xp, e["exit_time"]))

    def net(self, tk: str, bars: list[dict] | None, idx: int | None) -> dict[str, float]:
        e = self.emit[tk]
        if bars is None or idx is None:
            return {"r": float(e["net_r"]), "mfe": float(e["mfe_r"]), "bars": len(bars or [None]),
                    "cut": 0}
        open_r = float(bars[idx]["open_r"])
        is_long = str(e["direction"]).lower() in ("long", "buy")
        risk = self.risk(e)
        xp = float(e["entry"]) + (1 if is_long else -1) * open_r * risk
        exit_t = _iso(int(bars[idx]["bar_t"]) + self.tf_s)   # exit at that bar's CLOSE
        per_r = (abs(float(e["entry"])) + abs(xp)) / 2.0 / risk
        exit_fee_r = self.stack["slippage_bps_roundtrip"] / 2.0 / 1.0e4 * per_r
        r = open_r - self.cost(e, xp, exit_t) - exit_fee_r
        return {"r": r, "mfe": float(bars[idx]["mfe_r"]), "bars": idx + 1, "cut": 1}


def summarize(res: list[dict[str, float]], tf_s: int) -> dict[str, Any]:
    if not res:
        return {"n": 0}
    rs = np.array([x["r"] for x in res])
    eq = np.cumsum(rs)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq])) - np.concatenate([[0.0], eq])))
    gb = np.array([x["mfe"] - x["r"] for x in res])
    days = sum(x["bars"] for x in res) * tf_s / 86400.0
    return {"n": len(res), "net_r": round(float(rs.sum()), 4), "max_dd_r": round(dd, 4),
            "n_truncated": int(sum(x["cut"] for x in res)),
            "r_giveback_mean": round(float(gb.mean()), 4),
            "r_giveback_p95": round(float(np.percentile(gb, 95)), 4),
            "net_r_per_pos_day": round(float(rs.sum()) / days, 4) if days > 0 else None}


def score(model, trades: dict[str, list[dict]]) -> dict[str, np.ndarray]:
    rows = [b for bars in trades.values() for b in bars]
    if not rows:
        return {}
    X, _ = te.matrix(rows)
    p = model.predict_proba(X)[:, 1]
    out, i = {}, 0
    for tk, bars in trades.items():
        out[tk] = p[i:i + len(bars)]
        i += len(bars)
    return out


def run_arm(arm: str, keys: list[str], resolv: dict[str, list[dict]], probs: dict[str, np.ndarray],
            pricer: Pricer) -> list[dict[str, float]]:
    out = []
    for tk in keys:
        bars = resolv.get(tk)
        idx = None if (arm == "B" or bars is None) else exit_index(arm, bars, probs.get(tk))
        out.append(pricer.net(tk, bars, idx))
    return out


def prepare(a) -> str:
    """Full chain into a.out: fetch candles, run the config-exact baseline arm, build E0. Returns the
    harness's own held-out boundary (fixed from the baseline's ENTRY TIMES before any outcome)."""
    import subprocess
    import tempfile
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ab = out / "baseline"
    work = Path(tempfile.mkdtemp(prefix="exit_head_holdout_"))
    # The SAME invocation as RQ-20261104-c6f1-04's B arm (plus its T4 arm, so the reproduction is
    # checkable against that record); the harness fetches the candles itself.
    cmd = [sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", a.leg,
           "--arm", "B=", "--arm", "T4=tp_r=4", "--days", str(a.days), "--start", a.start, "--end", a.end,
           "--grade", "holdout", "--baseline", "B", "--delta-r", "0", "--folds", "4", "--fold-majority", "3",
           "--n-floor", "39", "--holdout-frac", "0.25", "--holdout-min-trades", "25",
           "--holdout-max-frac", "0.40", "--out", str(ab)]
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, check=False)
    (out / "baseline.log").write_text(r.stdout[-20000:] + "\n--- stderr ---\n" + r.stderr[-20000:])
    if r.returncode != 0:
        raise SystemExit(f"baseline arm failed rc={r.returncode}")
    csvs = sorted(Path(tempfile.gettempdir()).glob(f"exit_lever_ablation_*/{a.leg}__data.csv"),
                  key=lambda p: p.stat().st_mtime)
    if not csvs:
        raise SystemExit("baseline arm left no candle CSV")
    sym = (json.loads((ab / "arms" / "B__bt.json").read_text()).get("symbol"))
    e0 = work / "e0"
    r = subprocess.run([sys.executable, str(REPO / "scripts/ml/build_exit_head_dataset.py"),
                        "--trades", str(ab / "arms" / "B__trades.jsonl"), "--candles", f"{sym}={csvs[-1]}",
                        "--tf", a.tf, "--out", str(e0)], cwd=str(REPO), capture_output=True, text=True,
                       check=False)
    (out / "e0.log").write_text(r.stdout[-20000:] + "\n--- stderr ---\n" + r.stderr[-20000:])
    if r.returncode != 0:
        raise SystemExit(f"E0 build failed rc={r.returncode}")
    (out / "e0_build_report.json").write_text((e0 / "build_report.json").read_text())
    fams = [d for d in e0.iterdir() if d.is_dir() and (d / "rows.jsonl").exists()]
    if len(fams) != 1:
        raise SystemExit(f"expected one E0 family, got {[d.name for d in fams]}")
    a.rows, a.trades, a.bt = str(fams[0] / "rows.jsonl"), str(ab / "arms" / "B__trades.jsonl"), \
        str(ab / "arms" / "B__bt.json")
    a.json = a.json or str(out / "verdict.json")
    v = json.loads((ab / "verdict.json").read_text())
    return v["measurement"]["grade"]["plan"]["boundary"]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--leg", default=None, help="full chain: fetch + baseline arm + E0 build, then grade")
    ap.add_argument("--days", type=int, default=2350)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=None, help="full chain: output dir (verdict.json lands here)")
    ap.add_argument("--rows", default=None)
    ap.add_argument("--trades", default=None)
    ap.add_argument("--bt", default=None)
    ap.add_argument("--boundary", required=True, help="the REGISTERED held-out boundary")
    ap.add_argument("--tf", required=True, choices=sorted(TF_S))
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv[1:])
    tf_s = TF_S[a.tf]
    harness_boundary = None
    if a.leg:
        harness_boundary = prepare(a)
    bt = json.loads(Path(a.bt).read_text())
    keys = ("fee_bps_roundtrip", "slippage_bps_roundtrip", "funding_bps_per_window")
    stack = ({k: float(bt[k]) for k in keys} if all(bt.get(k) is not None for k in keys) else {})
    emit = {}
    for line in Path(a.trades).read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            emit[f"{e['strategy']}:{e['symbol']}:{int(_epoch(e['entry_time']))}"] = e
    resolv = {tk: b for tk, b in te.group_trades(te.load_rows(Path(a.rows))).items() if tk in emit}
    pricer = Pricer(emit, stack, tf_s)
    boundary = _epoch(a.boundary)
    out: dict[str, Any] = {"unit": "RQ-20261104-e4a1-01", "boundary": a.boundary,
                           "harness_boundary": harness_boundary, "cost_stack": stack,
                           "n_emitted": len(emit), "n_resolvable": len(resolv)}

    def done(verdict: str, why: str) -> int:
        out["rule_verdict"], out["rule_why"] = verdict, why
        rec = {"verdict": verdict if verdict in ("pass", "fail") else "indeterminate",
               "read_state": "measured" if verdict in ("pass", "fail") else "insufficient",
               "population": (f"{a.leg or 'leg'}: {len(emit)} baseline-arm trades (config-exact declared exit), "
                              f"{len(resolv)} with >= 1 in-trade bar; discovery {out.get('n_discovery')} / "
                              f"held-out {out.get('n_held_out')} at boundary {a.boundary}; net of fee "
                              f"{stack.get('fee_bps_roundtrip')} + slippage {stack.get('slippage_bps_roundtrip')} "
                              f"bps rt + funding {stack.get('funding_bps_per_window')} bps/window; every "
                              "head-truncated trade charged its own round trip + one slippage side"),
               "n": out.get("n_held_out") or len(emit), "measurement": out, "note": why}
        Path(a.json).write_text(json.dumps(rec, indent=1, default=str))
        print(json.dumps({"verdict": verdict, "why": why}, indent=1))
        return 0

    if harness_boundary is not None and _epoch(harness_boundary) != _epoch(a.boundary):
        return done("indeterminate", f"boundary_mismatch: harness fixed {harness_boundary}, registered {a.boundary}")

    # ---- self-check: the cost model reproduces every emitted baseline cost
    gaps = [pricer.baseline_gap(e) for e in emit.values()]
    out["cost_selfcheck"] = {"n_checked": len(gaps), "max_gap_r": round(max(gaps), 6)}
    if not stack or max(gaps) > COST_TOL:
        return done("indeterminate", "cost_policy_mismatch: recomputed cost differs from the emitted cost")

    ent = {tk: _epoch(e["entry_time"]) for tk, e in emit.items()}
    ext = {tk: _epoch(e["exit_time"]) for tk, e in emit.items()}
    disc = sorted([tk for tk in emit if ent[tk] < boundary and ext[tk] < boundary], key=ent.get)
    held = sorted([tk for tk in emit if ent[tk] >= boundary], key=ent.get)
    out["n_discovery"], out["n_held_out"] = len(disc), len(held)
    out["n_straddle_excluded"] = len(emit) - len(disc) - len(held)

    # ---- discovery walk-forward (models trained strictly on earlier, purged + embargoed)
    d_res = {tk: resolv[tk] for tk in disc if tk in resolv}
    blocks = te.fold_blocks(d_res, "trades", BLOCK_N, lambda b: b[0]["bar_t"])
    arms = arm_names()
    folds = []
    for label, _y, test, y0 in blocks:
        train_rows = [r for b in d_res.values() if b[-1]["bar_t"] < y0 - te.EMBARGO_S for r in b]
        if len(test) < BLOCK_N or len(train_rows) < te._MIN_FOLD_TRAIN_ROWS:
            folds.append({"fold": label, "skipped": True, "n_test": len(test), "train_rows": len(train_rows)})
            continue
        model = te.train_model(train_rows)
        probs = score(model, test)
        test_rows = [r for b in test.values() for r in b]
        _, y = te.matrix(test_rows)
        p = np.concatenate([probs[tk] for tk in test])
        keys = sorted(test, key=lambda k: ent[k])
        f = {"fold": label, "n_test": len(test), "train_rows": len(train_rows), "auc": te.auc_score(y, p),
             "arms": {}}
        for arm in ["B", "stale_8_0", "giveback_1_1"] + arms:
            f["arms"][arm] = summarize(run_arm(arm, keys, resolv, probs, pricer), tf_s)
        folds.append(f)
    out["discovery_folds"] = folds
    usable = [f for f in folds if not f.get("skipped")]
    out["n_usable_folds"] = len(usable)
    if len(usable) < 2:
        return done("indeterminate", f"underpowered: {len(usable)} usable discovery fold(s) < 2")
    aucs = [f["auc"] for f in usable if f["auc"] is not None]
    out["discovery_mean_auc"] = round(float(np.mean(aucs)), 4) if aucs else None
    need = math.ceil(2 * len(usable) / 3)
    table = {}
    for arm in ["stale_8_0", "giveback_1_1"] + arms:
        tot = sum(f["arms"][arm]["net_r"] for f in usable)
        btot = sum(f["arms"]["B"]["net_r"] for f in usable)
        wins = sum(1 for f in usable if f["arms"][arm]["net_r"] >= f["arms"]["B"]["net_r"])
        fires = sum(f["arms"][arm]["n_truncated"] for f in usable)
        elig = (arm in arms and tot > btot and wins >= need and fires > 0
                and out["discovery_mean_auc"] is not None and out["discovery_mean_auc"] > AUC_FLOOR)
        table[arm] = {"wf_net_r": round(tot, 4), "B_wf_net_r": round(btot, 4), "folds_ge_B": wins,
                      "folds_needed": need, "n_truncated": fires, "eligible": elig}
    out["discovery_table"] = table
    elig = [k for k, v in table.items() if v["eligible"]]
    selected = max(elig, key=lambda k: table[k]["wf_net_r"]) if elig else "B"
    out["selected"] = selected

    # ---- held-out read, ONCE: model trained on all discovery rows (purged at the boundary)
    fin_rows = [r for b in d_res.values() if b[-1]["bar_t"] < boundary - te.EMBARGO_S for r in b]
    model = te.train_model(fin_rows)
    h_res = {tk: resolv[tk] for tk in held if tk in resolv}
    hprobs = score(model, h_res)
    hrows = [r for b in h_res.values() for r in b]
    _, hy = te.matrix(hrows)
    hp = np.concatenate([hprobs[tk] for tk in h_res]) if h_res else np.array([])
    out["held_out_auc"] = te.auc_score(hy, hp) if len(hp) else None
    ho = {arm: summarize(run_arm(arm, held, resolv, hprobs, pricer), tf_s)
          for arm in ["B", "stale_8_0", "giveback_1_1"] + arms}
    out["held_out"] = ho          # every arm REPORTED; only `selected` is graded
    if selected == "B":
        return done("fail", "B selected on discovery: no head arm eligible (beats B on the walk-forward "
                    f"in >= {need} of {len(usable)} folds with mean OOS AUC > {AUC_FLOOR})")

    # ---- matched random-truncation control on the held-out span
    sel = ho[selected]
    k = sel["n_truncated"]
    if k == 0:
        return done("indeterminate", f"{selected} never fires on the held-out span (byte-identical to B)")
    rng = random.Random(CONTROL_SEED)
    pool = [tk for tk in held if tk in resolv and len(resolv[tk]) >= 2]
    draws = []
    for _ in range(CONTROL_DRAWS):
        cut = set(rng.sample(pool, min(k, len(pool))))
        tot = 0.0
        for tk in held:
            idx = rng.randrange(0, len(resolv[tk]) - 1) if tk in cut else None
            tot += pricer.net(tk, resolv.get(tk), idx)["r"]
        draws.append(tot)
    ctl = float(np.percentile(draws, CONTROL_PCTL))
    out["control"] = {"draws": CONTROL_DRAWS, "k": k, "seed": CONTROL_SEED,
                      "median_net_r": round(float(np.median(draws)), 4), f"p{CONTROL_PCTL:g}_net_r": round(ctl, 4)}
    hard = max(ho["stale_8_0"]["net_r"], ho["giveback_1_1"]["net_r"])
    clauses = {
        "c1_selected_is_head": True,
        "c2_held_out_n_ge_25": sel["n"] >= 25,
        "c3_net_ge_B": sel["net_r"] >= ho["B"]["net_r"],
        "c4_net_ge_best_hard": sel["net_r"] >= hard,
        "c5_dd_within_tol": sel["max_dd_r"] <= ho["B"]["max_dd_r"] * DD_TOL,
        "c6_beats_control_p95": sel["net_r"] > ctl,
    }
    out["clauses"] = clauses
    if all(clauses.values()):
        return done("pass", f"{selected} held-out net {sel['net_r']} vs B {ho['B']['net_r']} (n {sel['n']}), "
                    f"control p95 {round(ctl, 4)}")
    failed = [c for c, ok in clauses.items() if not ok]
    return done("fail", f"{selected} selected on discovery but fails held-out clause(s) {failed}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
