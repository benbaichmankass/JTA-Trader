#!/usr/bin/env python3
# wiring: research/queue/RQ-20261118-f7c1-01.yaml (ml_entry same-bar basket cap, walkthrough 2026-11-18 D1, PI-20261118-PREP1118-0001)
# wiring: research/queue/RQ-20261118-f7c1-08.yaml (`forward`: the selected k=2 on post-record decisions 2026-10-01..2026-11-16)
"""ml_entry SAME-BAR BASKET CAP on the committed Stage-0 record (Tier-1 research; no order, no config).

Question (RQ-20261118-f7c1-01, rule RULE-RQ20261118-f7c1-01-SAMEBAR-CAP, registered before this ran): at each decision bar keep at
most k decisions per side, survivors = the highest frozen-v1 predicted net R for that side (causal: the score exists at the bar
close), k in {1, 2, 3}. Does a cap keep net R, cut max drawdown by >= 20%, and beat a matched random drop?

Inputs:
* the committed per-trade record ``comms/strategy_evidence/runs/2026-11-12/ml_entry__trades.jsonl`` (907 trades, arm F = the live
  exit, net of the full cost stack). It carries no score, so
* every (symbol, decision_ts) is re-scored with the frozen v1 booster that produced it (the same artifact and table recipe as
  ``ml_entry_maker_replay.v1_decisions``) and the side's prediction is joined.

Drawdown: per-bar net R summed, booked at the decision bar, in decision order; max peak-to-trough of the cumulative sum, in R.
NOT MODELLED (stated beside the result): a dropped decision would free its symbol earlier, so the live policy could take a later
decision on that symbol that the record does not contain.

    python3 scripts/research/ml_entry_samebar_cap.py --unit RQ-20261118-f7c1-01 --out O [--cache C] [--scores S.csv]
    python3 scripts/research/ml_entry_samebar_cap.py forward --unit RQ-20261118-f7c1-08 --out O [--cache C]
    python3 scripts/research/ml_entry_samebar_cap.py --self-test

FORWARD (RQ-20261118-f7c1-08): the frozen v1 booster scores post-record decision bars FWD_START..FWD_END on the bybit_2 symbols
(ml_decision_entry.policy, tau 0.10, outcome = the c692-01 label's fixed bracket, a DECLARED fidelity gap vs arm F), the read is claimed
in the holdout ledger first, then the selected k=2 is graded by the same three conditions (k=1, 3 reported).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

UNIT = "RQ-20261118-f7c1-01"
RULE_ID = "RULE-RQ20261118-f7c1-01-SAMEBAR-CAP"
RECORD = REPO / "comms/strategy_evidence/runs/2026-11-12/ml_entry__trades.jsonl"
ART = REPO / "comms/research/RQ-20261101-c692-06/41324826751/model"   # the frozen v1 booster (ml_entry_maker_replay.v1_decisions)
K_GRID = (1, 2, 3)
DD_RATIO = 0.8
SCORE_COVERAGE_MIN = 0.95
BIND_BARS_MIN = 30
REPS = 2000
SEED = 20261118
FWD_UNIT = "RQ-20261118-f7c1-08"
FWD_RULE_ID = "RULE-RQ20261118-f7c1-08-SAMEBAR-CAP-FWD"
FWD_START, FWD_END = "2026-10-01", "2026-11-16"
FWD_K = 2
FWD_MIN_N = 60
TAU = 0.10


# ------------------------------------------------------------------------------------------------ inputs
def load_record(path: Path = RECORD) -> pd.DataFrame:
    d = pd.read_json(path, lines=True)
    d["decision_ts"] = pd.to_datetime(d["decision_ts"], utc=True)
    return d.reset_index(drop=True)


def score_record(rec: pd.DataFrame, cache: Path) -> pd.Series:
    """The frozen v1 predicted net R of each row's side at its decision bar (NaN where the table has no row)."""
    import lightgbm as lgb
    import ml_decision_entry as E
    syms = E.universe()
    E.fetch(cache, syms, end=E.END)
    tab = E.build_table(cache, syms)
    tab["ts"] = pd.to_datetime(tab["ts"], utc=True)
    test = tab[tab.ts >= pd.Timestamp(E.HOLDOUT_START, tz="UTC")].reset_index(drop=True)
    # provenance: Booster — regression booster file: predicts net R per decision, not a class probability
    pl, ps = (lgb.Booster(model_file=str(ART / f"entry_{s}.txt")).predict(test[E.FEATURES]) for s in ("long", "short"))
    key = pd.DataFrame({"symbol": test.symbol, "decision_ts": test.ts, "p_long": pl, "p_short": ps})
    m = rec[["symbol", "decision_ts", "side"]].merge(key, on=["symbol", "decision_ts"], how="left", validate="many_to_one")
    return pd.Series(np.where(m.side == "long", m.p_long, m.p_short), index=rec.index, name="score")


# ------------------------------------------------------------------------------------------------ mechanics
def cap_mask(rec: pd.DataFrame, k: int) -> np.ndarray:
    """True for kept rows: per (decision_ts, side), the k highest scores (ties: symbol name)."""
    r = rec.assign(_i=np.arange(len(rec))).sort_values(["decision_ts", "side", "score", "symbol"],
                                                       ascending=[True, True, False, True], kind="mergesort")
    rank = r.groupby(["decision_ts", "side"], sort=False).cumcount().to_numpy()
    keep = np.zeros(len(rec), bool)
    keep[r["_i"].to_numpy()[rank < k]] = True
    return keep


def random_mask(groups: np.ndarray, kept_per_group: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Matched random drop: within each group keep the same number as the ranked arm, chosen at random."""
    u = rng.random(len(groups))
    order = np.lexsort((u, groups))
    g_sorted = groups[order]
    starts = np.r_[0, np.flatnonzero(np.diff(g_sorted)) + 1]
    pos = np.arange(len(groups)) - np.repeat(starts, np.diff(np.r_[starts, len(groups)]))
    keep = np.zeros(len(groups), bool)
    keep[order[pos < kept_per_group[g_sorted]]] = True
    return keep


def max_drawdown(bar_idx: np.ndarray, net: np.ndarray, n_bars: int) -> float:
    per_bar = np.bincount(bar_idx, weights=net, minlength=n_bars)
    cum = np.cumsum(per_bar)
    peak = np.maximum.accumulate(np.r_[0.0, cum])[1:]
    return float(np.max(peak - cum)) if len(cum) else 0.0


def longest_losing_run(bar_idx: np.ndarray, net: np.ndarray, n_bars: int) -> int:
    per_bar = np.bincount(bar_idx, weights=net, minlength=n_bars)
    present = np.bincount(bar_idx, minlength=n_bars) > 0
    best = cur = 0
    for v, p in zip(per_bar, present):
        if not p:
            continue
        cur = cur + 1 if v < 0 else 0
        best = max(best, cur)
    return best


def bar_bootstrap(bar_idx: np.ndarray, values: np.ndarray, n_bars: int, reps: int, rng: np.random.Generator,
                  counts: np.ndarray | None = None) -> tuple[float, float]:
    """Decision-bar-clustered bootstrap of sum(values) (counts None) or of sum(values)/sum(counts) (a mean)."""
    s = np.bincount(bar_idx, weights=values, minlength=n_bars)
    c = None if counts is None else np.bincount(bar_idx, weights=counts, minlength=n_bars)
    present = np.flatnonzero(np.bincount(bar_idx, minlength=n_bars) > 0)
    out = np.empty(reps)
    for j in range(reps):
        b = rng.choice(present, size=len(present), replace=True)
        out[j] = s[b].sum() if c is None else s[b].sum() / max(c[b].sum(), 1e-12)
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def evaluate(rec: pd.DataFrame, reps: int = REPS, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    bars = rec.decision_ts.rank(method="dense").astype(int).to_numpy() - 1
    n_bars = int(bars.max()) + 1
    net = rec.net_r.to_numpy(float)
    groups = pd.factorize(pd.Series(bars.astype(str)) + "|" + rec.side.astype(str).to_numpy())[0]
    base_sum, base_dd = float(net.sum()), max_drawdown(bars, net, n_bars)
    base = {"n": len(rec), "sum_net_r": base_sum, "mean_net_r": float(net.mean()), "max_dd_r": base_dd,
            "mean_net_r_ci95_bar_clustered": bar_bootstrap(bars, net, n_bars, reps, rng, np.ones(len(net))),
            "longest_losing_bar_run": longest_losing_run(bars, net, n_bars), "decision_bars": n_bars,
            "decisions_per_bar_hist": {str(k): int(v) for k, v in pd.Series(bars).value_counts().value_counts().sort_index().items()}}
    arms = {}
    for k in K_GRID:
        keep = cap_mask(rec, k)
        kept_per_group = np.bincount(groups, weights=keep.astype(float)).astype(int)
        s, dd = float(net[keep].sum()), max_drawdown(bars[keep], net[keep], n_bars)
        diff_lo, diff_hi = bar_bootstrap(bars, net * keep - net, n_bars, reps, rng)
        ctrl_sum, ctrl_dd = np.empty(reps), np.empty(reps)
        for j in range(reps):
            km = random_mask(groups, kept_per_group, rng)
            ctrl_sum[j], ctrl_dd[j] = net[km].sum(), max_drawdown(bars[km], net[km], n_bars)
        bind_bars = int(pd.Series(~keep).groupby(bars).any().sum())
        a, b = s >= base_sum, dd <= DD_RATIO * base_dd
        c = s >= float(np.median(ctrl_sum))
        kept = rec[keep]
        arms[f"k{k}"] = {
            "n_kept": int(keep.sum()), "n_dropped": int((~keep).sum()), "bars_where_cap_binds": bind_bars,
            "sum_net_r": s, "mean_net_r": float(net[keep].mean()), "max_dd_r": dd, "dd_ratio_vs_uncapped": dd / base_dd if base_dd else None,
            "sum_net_r_diff_vs_uncapped": s - base_sum, "sum_net_r_diff_ci95_bar_clustered": [diff_lo, diff_hi],
            "mean_net_r_ci95_bar_clustered": bar_bootstrap(bars[keep], net[keep], n_bars, reps, rng, np.ones(int(keep.sum()))),
            "control_median_sum_net_r": float(np.median(ctrl_sum)), "control_median_max_dd_r": float(np.median(ctrl_dd)),
            "ranked_sum_percentile_in_control": float((ctrl_sum <= s).mean()),
            "ranked_dd_percentile_in_control": float((ctrl_dd <= dd).mean()),
            "dropped_mean_net_r": float(net[~keep].mean()) if (~keep).any() else None,
            "longest_losing_bar_run": longest_losing_run(bars[keep], net[keep], n_bars),
            "kept_by_side": kept.side.value_counts().to_dict(), "kept_by_symbol": kept.symbol.value_counts().to_dict(),
            "cond_a_net_r_holds": bool(a), "cond_b_dd_cut_20pct": bool(b), "cond_c_beats_random_drop_median": bool(c),
            "pass_k": bool(a and b and c)}
    return {"uncapped": base, "arms": arms}


def verdict(ev: dict, coverage: float) -> tuple[str, str, int | None]:
    if coverage < SCORE_COVERAGE_MIN:
        return "indeterminate", f"score coverage {coverage:.3f} < {SCORE_COVERAGE_MIN}", None
    if ev["arms"]["k1"]["bars_where_cap_binds"] < BIND_BARS_MIN:
        return "indeterminate", f"k=1 cap binds on {ev['arms']['k1']['bars_where_cap_binds']} bars < {BIND_BARS_MIN}", None
    passing = [k for k in K_GRID if ev["arms"][f"k{k}"]["pass_k"]]
    if passing:
        k = max(passing)
        a = ev["arms"][f"k{k}"]
        return "pass", (f"k={k} (largest passing of {passing}): sum net R {a['sum_net_r']:+.2f} vs {ev['uncapped']['sum_net_r']:+.2f}, "
                        f"max DD {a['max_dd_r']:.2f} vs {ev['uncapped']['max_dd_r']:.2f} R, control median {a['control_median_sum_net_r']:+.2f}"), k
    why = "; ".join(f"k={k}: a={ev['arms'][f'k{k}']['cond_a_net_r_holds']} b={ev['arms'][f'k{k}']['cond_b_dd_cut_20pct']} "
                    f"c={ev['arms'][f'k{k}']['cond_c_beats_random_drop_median']}" for k in K_GRID)
    return "fail", f"no k passes (a net R holds, b DD <= 0.8x, c beats random-drop median): {why}", None


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001  # allow-silent: provenance only; the result records "unknown"
        return "unknown"


def run(a) -> int:
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rec = load_record()
    if a.scores:
        sc = pd.read_csv(a.scores)
        sc["decision_ts"] = pd.to_datetime(sc["decision_ts"], utc=True)
        rec = rec.merge(sc[["symbol", "decision_ts", "side", "score"]], on=["symbol", "decision_ts", "side"], how="left")
    else:
        # provenance: score_record — the frozen v1 regression booster's predicted net R for the row's side (not a probability)
        rec["score"] = score_record(rec, Path(a.cache))
    rec[["symbol", "side", "decision_ts", "score", "net_r"]].to_csv(out / "scored_record.csv.gz", index=False)
    coverage = float(rec.score.notna().mean())
    scored = rec[rec.score.notna()].reset_index(drop=True)
    ev = evaluate(scored)
    v, why, k_sel = verdict(ev, coverage)
    meas = {"unit": UNIT, "rule_id": RULE_ID, "record": str(RECORD.relative_to(REPO)), "artifact": str(ART.relative_to(REPO)),
            "score_coverage": coverage, "n_scored": len(scored), "selected_k": k_sel, **ev,
            "not_modelled": "a dropped decision would free its symbol earlier; the capped arm cannot add the later decision the live "
                            "policy might take (bias direction unknown)",
            "drawdown_definition": "per-bar net R summed, booked at the decision bar, in decision order; max peak-to-trough in R",
            "git_sha": _git_sha(), "elapsed_s": round(time.time() - t0)}
    (out / "measurement.json").write_text(json.dumps(meas, indent=1, default=str) + "\n")
    vj = {"research_unit": UNIT, "rule_id": RULE_ID, "verdict": v, "read_state": "measured", "n": len(scored), "note": why,
          "population": f"committed ml_entry Stage-0 arm-F record ({len(rec)} trades, {rec.decision_ts.nunique()} decision bars, "
                        "2025-10-01..2026-09-30 held-out, 5 bybit_2 symbols), scored by the frozen v1 booster",
          "measurement": meas}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why, "coverage": coverage}), flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ forward (f7c1-08)
def forward_decisions(cache: Path, out: Path) -> tuple[pd.DataFrame, dict]:
    """Post-record decisions of the frozen v1 booster on the bybit_2 symbols, with score and fixed-bracket net R."""
    import lightgbm as lgb
    import ml_decision_entry as E
    import ml_entry_tp_revision as TPR
    syms = E.universe()
    E.fetch(cache, syms, end=E.END)
    TPR.FWD_START, TPR.FWD_END = FWD_START, FWD_END
    fwd = out / "fwd_cache"
    rep = TPR.forward_cache(cache, fwd, syms)
    have = [x for x in syms if (fwd / f"{x}.pkl").exists()]
    tab = E.build_table(fwd, have)
    lo, hi = pd.Timestamp(FWD_START, tz="UTC"), pd.Timestamp(FWD_END, tz="UTC") + pd.Timedelta(days=1)
    test = tab[(tab.ts >= lo) & (tab.ts < hi)].reset_index(drop=True)
    # provenance: Booster — regression booster file: predicts net R per decision, not a class probability
    pl, ps = (lgb.Booster(model_file=str(ART / f"entry_{side}.txt")).predict(test[E.FEATURES]) for side in ("long", "short"))
    taken = E.policy(test, pl, ps, TAU)
    traded = E.traded_symbols()
    taken = taken[taken.symbol.isin(traded)].reset_index(drop=True)
    rec = pd.DataFrame({"symbol": taken.symbol, "side": taken.side, "decision_ts": pd.to_datetime(taken.ts, utc=True),
                        "net_r": taken.net_r.astype(float), "score": taken.pred.astype(float)})
    meta = {"universe": len(syms), "symbols_with_window_data": len(have), "traded_symbols": traded,
            "window_rows": len(test), "window_last_ts": str(test.ts.max()) if len(test) else None,
            "fetch_report_days": {k: v.get("oct_days") for k, v in rep.items() if k in traded}}
    return rec, meta


def claim_forward_read(out: Path) -> dict:
    import shutil

    import holdout_lock as HL
    led = out / "holdout_reads.jsonl"
    if not led.exists() and HL.LEDGER.exists():
        shutil.copy(HL.LEDGER, led)
    return HL.claim_read(model_id="ENTRY-v1-samebar-cap", start=FWD_START, end=FWD_END, unit=FWD_UNIT,
                         reader="ml_entry_samebar_cap.forward", ledger=led, train_end="2025-09-30", family="ENTRY-SAMEBAR")


def forward_verdict(ev: dict) -> tuple[str, str]:
    n, a = ev["uncapped"]["n"], ev["arms"].get(f"k{FWD_K}")
    if n < FWD_MIN_N:
        return "indeterminate", f"{n} decisions taken in the window < {FWD_MIN_N}"
    if a["bars_where_cap_binds"] < BIND_BARS_MIN:
        return "indeterminate", f"k={FWD_K} cap binds on {a['bars_where_cap_binds']} bars < {BIND_BARS_MIN}"
    why = (f"k={FWD_K}: sum net R {a['sum_net_r']:+.2f} vs {ev['uncapped']['sum_net_r']:+.2f}, max DD {a['max_dd_r']:.2f} vs "
           f"{ev['uncapped']['max_dd_r']:.2f} R, random-drop median {a['control_median_sum_net_r']:+.2f}")
    return ("pass", why) if a["pass_k"] else ("fail", why + f" (a={a['cond_a_net_r_holds']} b={a['cond_b_dd_cut_20pct']} "
                                                         f"c={a['cond_c_beats_random_drop_median']})")


def run_forward(a) -> int:
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    claim = claim_forward_read(out)          # BEFORE any forward outcome is computed
    rec, meta = forward_decisions(Path(a.cache), out)
    rec.to_csv(out / "forward_decisions.csv.gz", index=False)
    ev = evaluate(rec) if len(rec) else {"uncapped": {"n": 0}, "arms": {f"k{FWD_K}": {"bars_where_cap_binds": 0}}}
    v, why = forward_verdict(ev)
    meas = {"unit": FWD_UNIT, "rule_id": FWD_RULE_ID, "window": [FWD_START, FWD_END], "selected_k": FWD_K, "artifact": str(ART.relative_to(REPO)),
            "outcome": "c692-01 label fixed bracket (SL 2xATR14, TP 3xATR14, 24h), net of fee 11 + slip 3 bps + funding 1 bps/8h; "
                       "DECLARED fidelity gap vs the record's arm F", "holdout_claim": claim, **meta, **ev,
            "not_modelled": "freed-slot trades after a dropped decision", "git_sha": _git_sha(), "elapsed_s": round(time.time() - t0)}
    (out / "measurement.json").write_text(json.dumps(meas, indent=1, default=str) + "\n")
    vj = {"research_unit": FWD_UNIT, "rule_id": FWD_RULE_ID, "verdict": v, "read_state": "measured", "n": int(ev["uncapped"]["n"]),
          "note": why, "population": (f"frozen v1 booster decisions {FWD_START}..{FWD_END} on the bybit_2 symbols (tau {TAU}, sequential "
                                      "one-position-per-symbol policy), fixed-bracket outcome"), "measurement": meas}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    shutil_rmtree = __import__("shutil").rmtree
    shutil_rmtree(out / "fwd_cache", ignore_errors=True)
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


def _self_test() -> None:
    ts = pd.to_datetime(["2025-10-01 03:00", "2025-10-01 03:00", "2025-10-01 03:00", "2025-10-01 07:00", "2025-10-01 11:00"], utc=True)
    rec = pd.DataFrame({"symbol": ["A", "B", "C", "A", "B"], "side": ["long", "long", "short", "long", "long"], "decision_ts": ts,
                        "net_r": [-1.0, 2.0, -1.0, 1.0, -1.0], "score": [0.3, 0.2, 0.5, 0.4, 0.4]})
    k1 = cap_mask(rec, 1)
    assert k1.tolist() == [True, False, True, True, True], k1     # per (bar, side): B long dropped (lower score); C short alone
    assert cap_mask(rec, 2).all()
    bars = np.array([0, 0, 0, 1, 2])
    assert max_drawdown(bars, rec.net_r.to_numpy(), 3) == 1.0     # per bar 0, +1, -1 -> cum 0, 1, 0 -> dd 1
    assert max_drawdown(np.array([0, 1]), np.array([-2.0, 1.0]), 2) == 2.0  # from the 0 start
    g = np.array([0, 0, 0, 1, 2])
    km = random_mask(g, np.array([2, 1, 0]), np.random.default_rng(1))
    assert km[:3].sum() == 2 and km[3] and not km[4], km
    assert longest_losing_run(np.array([0, 1, 2]), np.array([-1.0, -1.0, 1.0]), 3) == 2
    ev = evaluate(rec, reps=50)
    assert ev["arms"]["k1"]["n_dropped"] == 1 and ev["arms"]["k1"]["sum_net_r"] == -2.0
    # forward verdict branches (f7c1-08)
    arm = {"bars_where_cap_binds": 40, "sum_net_r": 5.0, "max_dd_r": 1.0, "control_median_sum_net_r": 1.0, "pass_k": True,
           "cond_a_net_r_holds": True, "cond_b_dd_cut_20pct": True, "cond_c_beats_random_drop_median": True}
    base = {"n": 120, "sum_net_r": 4.0, "max_dd_r": 2.0}
    assert forward_verdict({"uncapped": base, "arms": {"k2": arm}})[0] == "pass"
    assert forward_verdict({"uncapped": base, "arms": {"k2": {**arm, "pass_k": False}}})[0] == "fail"
    assert forward_verdict({"uncapped": {**base, "n": 59}, "arms": {"k2": arm}})[0] == "indeterminate"
    assert forward_verdict({"uncapped": base, "arms": {"k2": {**arm, "bars_where_cap_binds": 29}}})[0] == "indeterminate"
    print("self-test ok")


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    forward = bool(argv) and argv[0] == "forward"
    if forward:
        argv = argv[1:]
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--unit", default=UNIT)
    p.add_argument("--out", default="out/samebar_cap")
    p.add_argument("--cache", default="/tmp/klines")
    p.add_argument("--scores", help="a scored_record.csv(.gz) from a previous run (skip re-scoring)")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if forward:
        if a.unit != FWD_UNIT:
            raise SystemExit(f"`forward` answers {FWD_UNIT} only, got {a.unit}")
        return run_forward(a)
    if a.unit != UNIT:
        raise SystemExit(f"this harness answers {UNIT} only, got {a.unit}")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
