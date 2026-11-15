#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-0be0-01.yaml (MANAGE signal-reversal CLOSE, lane ML-DECISION-MODELS); spec docs/research/ml-decision-models-2026-11-01/DESIGN.md section 4 + 4b
"""MANAGE lever M1, SIGNAL-REVERSAL CLOSE: close an open frozen-ENTRY trade at a 4h check-in when the ENTRY model itself, re-scored
at that check-in bar, no longer backs the trade (Tier-1 research, no order, no sizing).

Why a separate arm: every MANAGE arm read so far (c692-03, -08..-15) decides from price triggers or from heads trained on paired
deltas; none used the decision model's own re-score. This arm adds NO learned parameter: the ENTRY predictions at the check-in bar
are the same walk-forward OOS predictions (dev) / final-fit predictions (held-out) that opened the trades, and tau is c692-01's.

Rules (the grid; one is chosen on DEV only, argmax pooled dev delta, tie -> the earlier rule in this list):
  own_le0     close if the re-scored prediction for the trade's OWN side is <= 0 (the model no longer expects it to pay net of cost)
  opp_gt_tau  close if the OPPOSITE side's prediction is > tau (ENTRY would now open the other way)
  either      own_le0 OR opp_gt_tau
A close decided at the close of check-in bar k (4, 8, 12, 16, 20) exits at bar k+1's open and pays the full cost stack there.

Everything else is ml_decision_manage's: the base trades (frozen ENTRY, tau from c692-01, static 2/4 ATR, 24h, one position per
symbol), the simulator, the cost stack, the stats, the paired bootstrap and the holdout ledger claim (family MANAGE).

    python3 scripts/research/ml_decision_manage_reverse.py run --unit RQ-20261112-0be0-01 --cache /tmp/ml_decision_klines --out O
    python3 scripts/research/ml_decision_manage_reverse.py --self-test
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_decision_entry as E  # noqa: E402
import ml_decision_manage as M  # noqa: E402

SCHEMA = "ml_decision_manage_reverse/1"
RULES = ["own_le0", "opp_gt_tau", "either"]
DEV_FOLDS_POSITIVE_MIN = 5          # of the 8 ENTRY dev folds that carry trades
RANDOM_DRAWS = 200


# ------------------------------------------------------------------------------------------------ world (ENTRY predictions kept)
def build_world(a, tau):
    """ml_decision_manage.build_world, but it also keeps the ENTRY predictions of EVERY decision row (needed at the check-ins)."""
    syms = E.universe()
    if a.smoke:
        syms = sorted(set(syms[:9]) | {"BTCUSDT"})
    cache = Path(a.cache)
    E.fetch(cache, syms, end=E.END)
    tab = E.build_table(cache, syms)
    if a.smoke and tab.ts.max() >= pd.Timestamp("2025-10-01", tz="UTC"):
        raise RuntimeError("smoke run saw the sealed held-out window; refusing")
    df_by = {s: pd.read_pickle(cache / f"{s}.pkl").reset_index(drop=True) for s in syms}
    hs = pd.Timestamp(E.HOLDOUT_START, tz="UTC")
    dev = tab[tab.ts < hs]
    bounds = [pd.Timestamp(x, tz="UTC") for x in E.DEV_FOLDS] + [hs]
    dev_tr, dev_pred = [], []
    for lo, hi in itertools.pairwise(bounds):
        # predictions for every dev row of the fold (check-ins may sit up to 20 bars past the last ENTRY decision of the fold)
        test_all = dev[(dev.ts >= lo) & (dev.ts < hi)].reset_index(drop=True)
        pl_all, ps_all = E.fit_predict(E.purge_train(dev, lo), test_all)
        dev_pred.append(pd.DataFrame({"symbol": test_all.symbol, "i": test_all.i, "pl": pl_all, "ps": ps_all}))
        keep = (test_all.ts < hi - pd.Timedelta(hours=M.H + 1)).to_numpy()
        test = test_all[keep].reset_index(drop=True)
        tr = M.entry_trades(test, pl_all[keep], ps_all[keep], tau, df_by)
        tr["fold"] = str(lo.date())
        dev_tr.append(tr)
        print(f"ENTRY dev fold {lo.date()} trades={len(tr)}", flush=True)
    test = tab[tab.ts >= hs].reset_index(drop=True)
    pl, ps = E.fit_predict(E.purge_train(dev, hs), test)
    ho_tr = M.entry_trades(test, pl, ps, tau, df_by)
    ho_pred = pd.DataFrame({"symbol": test.symbol, "i": test.i, "pl": pl, "ps": ps})
    return tab, df_by, pd.concat(dev_tr, ignore_index=True), ho_tr, pd.concat(dev_pred, ignore_index=True), ho_pred


def checkin_scores(trades: pd.DataFrame, order: np.ndarray, pred: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """own / opposite ENTRY prediction at each check-in k, in Paths order. NaN where no decision row exists (never acts)."""
    key = pred.drop_duplicates(["symbol", "i"]).set_index(["symbol", "i"])
    tr = trades.loc[order]
    own = np.full((len(tr), len(M.CHECKINS)), np.nan)
    opp = np.full_like(own, np.nan)
    side = tr["side"].to_numpy()
    for c, k in enumerate(M.CHECKINS):
        idx = pd.MultiIndex.from_arrays([tr["symbol"].to_numpy(), tr["i"].to_numpy() + k])
        got = key.reindex(idx)
        pl, ps = got["pl"].to_numpy(), got["ps"].to_numpy()
        own[:, c] = np.where(side == 1, pl, ps)
        opp[:, c] = np.where(side == 1, ps, pl)
    return own, opp


def rule_mask(rule: str, own: np.ndarray, opp: np.ndarray, tau: float) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        a = own <= 0
        b = opp > tau
    a &= ~np.isnan(own)
    b &= ~np.isnan(opp)
    return {"own_le0": a, "opp_gt_tau": b, "either": a | b}[rule]


def close_hook(fire: np.ndarray):
    """fire[n, len(CHECKINS)]: close at check-in c (bar CHECKINS[c]) if alive; exit at the next bar's open."""
    col = {k: c for c, k in enumerate(M.CHECKINS)}

    def hook(b, st):
        if b in col:
            st["close"] = st["close"] | (st["alive"] & fire[:, col[b]])
    return hook


def first_fire(fire: np.ndarray) -> np.ndarray:
    """Check-in index of the first fire per trade (-1 if none). The simulator only acts on alive trades, so later fires are moot."""
    any_ = fire.any(axis=1)
    return np.where(any_, fire.argmax(axis=1), -1)


def random_matched(P, fire: np.ndarray, base: dict, seed: int = E.SEED) -> dict:
    """Close the SAME number of trades at the SAME check-in distribution, on randomly chosen trades (200 draws)."""
    rng = np.random.default_rng(seed)
    ff = first_fire(fire)
    n = P.n
    means = []
    for _ in range(RANDOM_DRAWS):
        perm = rng.permutation(n)
        f = np.zeros_like(fire)
        f[perm[ff >= 0], ff[ff >= 0]] = True
        r = M.simulate(P, close_hook(f))
        means.append(float(np.mean(r["net"] - base["net"])))
    return {"draws": RANDOM_DRAWS, "mean": float(np.mean(means)), "p95": float(np.percentile(means, 95))}


def day_clustered_se(d: np.ndarray, ts) -> dict:
    """SE of the mean paired delta clustered by entry day (reported, never gating): s_c = sum over day c of (d - mean)."""
    day = pd.to_datetime(pd.Series(ts)).dt.floor("D").to_numpy()
    s = pd.Series(d - d.mean()).groupby(day).sum().to_numpy()
    n_c, n = len(s), len(d)
    se = float(np.sqrt(n_c / max(n_c - 1, 1) * np.sum(s ** 2)) / n)
    return {"n_day_clusters": n_c, "se": se, "t": float(d.mean() / se) if se > 0 else None}


# ------------------------------------------------------------------------------------------------ run
def run(a) -> int:
    t0 = time.time()
    if a.smoke:      # DEV-ONLY plumbing check; the sealed window is never fetched
        E.START, E.END, E.HOLDOUT_START = "2021-07-01", "2025-03-31", "2024-10-01"
        E.DEV_FOLDS = ["2022-07-01", "2023-01-01", "2023-07-01", "2024-01-01", "2024-04-01"]
        tau = 0.1
    else:
        tau = json.loads(Path(a.entry_summary).read_text())["walk_forward"]["tau_star"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tab, df_by, dev_tr, ho_tr, dev_pred, ho_pred = build_world(a, tau)
    dev_tr = dev_tr.sort_values(["symbol", "i"], kind="stable").reset_index(drop=True)
    ho_tr = ho_tr.sort_values(["symbol", "i"], kind="stable").reset_index(drop=True)
    print(f"dev trades={len(dev_tr)} heldout trades={len(ho_tr)} tau={tau} t={time.time()-t0:.0f}s", flush=True)

    # ---- DEV: choose the rule
    dP, d_idx = M.gather(dev_tr, df_by, M.atr_series(tab, dev_tr))
    d_own, d_opp = checkin_scores(dev_tr, d_idx, dev_pred)
    dev_base = M.simulate(dP)
    folds = dev_tr.loc[d_idx, "fold"].to_numpy()
    dev_rows = {}
    for rule in RULES:
        fire = rule_mask(rule, d_own, d_opp, tau)
        r = M.simulate(dP, close_hook(fire))
        dd = r["net"] - dev_base["net"]
        by_fold = {f: float(dd[folds == f].mean()) for f in sorted(set(folds))}
        dev_rows[rule] = {"delta": float(dd.mean()), "folds_positive": int(sum(v > 0 for v in by_fold.values())), "n_folds": len(by_fold),
                          "by_fold": {k: round(v, 5) for k, v in by_fold.items()}, "share_closed": float(np.mean(first_fire(fire) >= 0)),
                          "check_in_coverage": float(np.mean(~np.isnan(d_own)))}
    chosen = max(RULES, key=lambda r: (dev_rows[r]["delta"], -RULES.index(r)))
    cd = dev_rows[chosen]
    res = {"schema": SCHEMA, "unit": a.unit, "entry_tau": tau, "base": f"static {M.BASE_SL}/{M.BASE_TP} ATR, {M.H}h",
           "dev": {"trades": len(dev_tr), "hold_mean_net_r": float(dev_base["net"].mean()), "rules": dev_rows, "chosen": chosen}, "heldout": None}
    dev_ok = cd["delta"] > 0 and cd["folds_positive"] >= DEV_FOLDS_POSITIVE_MIN
    if not dev_ok:
        v, why = "fail", (f"dev stage: chosen rule {chosen} pooled dev delta {cd['delta']:+.5f}, positive in {cd['folds_positive']}/{cd['n_folds']} folds "
                          f"(needs > 0 and >= {DEV_FOLDS_POSITIVE_MIN}): held-out NOT read (registered)")
    else:
        claim = M.claim_read(a, f"reverse-{chosen}")
        hP, h_idx = M.gather(ho_tr, df_by, M.atr_series(tab, ho_tr))
        h_own, h_opp = checkin_scores(ho_tr, h_idx, ho_pred)
        hb = M.simulate(hP)
        fire = rule_mask(chosen, h_own, h_opp, tau)
        r = M.simulate(hP, close_hook(fire))
        d = r["net"] - hb["net"]
        sy = ho_tr.loc[h_idx, "symbol"].to_numpy()
        ts = ho_tr.loc[h_idx, "ts"].to_numpy()
        s = M.stats(r["net"], hb["net"], sy)
        ci = M.paired_boot(d, bar=(claim or {}).get("bar"))
        acted = first_fire(fire) >= 0
        res["heldout"] = {**s, "hold": M.stats(hb["net"], hb["net"], sy), "delta_ci": ci, "ci_tag": M._ci_tag(claim),
                          "n_closed": int(acted.sum()), "mean_delta_per_closed": float(d[acted].mean()) if acted.any() else None,
                          "closed_at_checkin": {str(M.CHECKINS[c]): int((first_fire(fire) == c).sum()) for c in range(len(M.CHECKINS))},
                          "day_clustered": day_clustered_se(d, ts), "matched_random": random_matched(hP, fire, hb),
                          "peek": M.peek_report(d, sy), "by_month_delta": M.month_split(ts, d),
                          "by_side_delta": {("long" if sd == 1 else "short"): float(d[ho_tr.loc[h_idx, 'side'].to_numpy() == sd].mean()) for sd in (1, -1)},
                          "giveback_r": M.giveback(r), "giveback_r_hold": M.giveback(hb)}
        res["holdout_claim"] = claim
        if s["n"] < M.MIN_TRADES or s["n_symbols"] < M.MIN_SYMBOLS:
            v, why = "indeterminate", f"held-out trades={s['n']} / symbols={s['n_symbols']} below floor"
        elif s["delta_vs_hold"] > 0 and ci[0] > 0:
            v, why = "pass", f"rule {chosen}: delta vs hold-to-bracket {s['delta_vs_hold']:+.4f} R/trade, {M._ci_tag(claim)} [{ci[0]:+.4f}, {ci[1]:+.4f}] > 0 at n={s['n']}"
        else:
            v, why = "fail", f"rule {chosen}: delta vs hold-to-bracket {s['delta_vs_hold']:+.4f} R/trade, {M._ci_tag(claim)} [{ci[0]:+.4f}, {ci[1]:+.4f}] does not clear 0 at n={s['n']}"
    res.update(git_sha=E._git_sha(), elapsed_s=round(time.time() - t0))
    (out / "summary.json").write_text(json.dumps({**res, "verdict": v, "why": why}, indent=1, default=str) + "\n")
    vj = {"verdict": v, "read_state": "measured", "n": res["heldout"]["n"] if res["heldout"] else len(dev_tr), "measurement": res, "note": why,
          "decision_rule": {"id": "RULE-RQ20261112-0be0-01-REVCLOSE", "registered_at": "2026-11-12", "registered_before_run": True},
          "population": (f"frozen ENTRY (tau {tau}) trades, static {M.BASE_SL}/{M.BASE_TP} ATR {M.H}h, 60-perp bp2-f4271084b120; dev "
                         f"{E.DEV_FOLDS[0]}..{E.HOLDOUT_START} (walk-forward OOS); held-out {E.HOLDOUT_START}..{E.END}; full cost stack; paired vs hold-to-bracket")}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ self-test
def _self_test() -> None:
    P, _ = M._synthetic(n=40, seed=3)
    base = M.simulate(P)
    none = np.zeros((P.n, len(M.CHECKINS)), bool)
    assert np.allclose(M.simulate(P, close_hook(none))["net"], base["net"]), "no fire must equal hold"
    allf = np.ones_like(none)
    r = M.simulate(P, close_hook(allf))
    alive_at_4 = base["bars"] > M.CHECKINS[0]
    assert np.all(r["bars"][alive_at_4] == M.CHECKINS[0]), "fire at every check-in closes at the first one"
    assert np.all(r["reason"][alive_at_4] == 3)
    assert np.allclose(r["net"][~alive_at_4], base["net"][~alive_at_4]), "trades already exited are untouched"
    own = np.array([[0.1, -0.2, np.nan, 0.3, 0.0]])
    opp = np.array([[0.2, 0.0, 0.5, np.nan, 0.05]])
    assert rule_mask("own_le0", own, opp, 0.1).tolist() == [[False, True, False, False, True]]
    assert rule_mask("opp_gt_tau", own, opp, 0.1).tolist() == [[True, False, True, False, False]]
    assert rule_mask("either", own, opp, 0.1).tolist() == [[True, True, True, False, True]]
    assert first_fire(np.array([[False, True, True, False, False], [False] * 5])).tolist() == [1, -1]
    tr = pd.DataFrame({"symbol": ["A", "A"], "i": [10, 50], "side": [1, -1]})
    pred = pd.DataFrame({"symbol": ["A"] * 4, "i": [14, 18, 54, 58], "pl": [0.3, -0.1, 0.2, 0.0], "ps": [-0.2, 0.4, -0.3, 0.1]})
    o, p = checkin_scores(tr, np.array([0, 1]), pred)
    assert o[0, :2].tolist() == [0.3, -0.1] and p[0, :2].tolist() == [-0.2, 0.4]
    assert o[1, :2].tolist() == [-0.3, 0.1] and p[1, :2].tolist() == [0.2, 0.0]
    assert np.isnan(o[0, 2])
    print("ml_decision_manage_reverse self-test OK")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run"])
    ap.add_argument("--entry-summary", default=str(REPO / "comms/research/RQ-20261101-c692-01/local-20261101T0835Z/summary.json"))
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out", default="/tmp/ml_decision_manage_reverse_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--smoke", action="store_true", help="dev-only plumbing check on 10 symbols; never touches the sealed window")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
