#!/usr/bin/env python3
# wiring: research/queue units of programme P8 (research/programmes/08-alpaca-live-book.yaml; lane ALPACA-LIVE-BOOK-PLAN, 2026-11-11)
# wiring: research/queue/blocked/RQ-20261118-f7c1-03.yaml (--section features, P8-Q5) and RQ-20261118-f7c1-04.yaml (--section horizon, P8-Q8)
"""THE ALPACA_LIVE BOOK, AS THE ACCOUNT CAN ACTUALLY TRADE IT (programme P8, docs/research/programmes/08-ALPACA-LIVE-BOOK.md).

Operator, 2026-11-11 ~22:40Z (relayed by Manager Session 2026-11-11a): "we need to make sure we have a plan for finding something
better" than the live alpaca_live strategy (Foxhound-4, ml_entry_eq_struct, artifact ml-entry-eq-struct-ens5-v1).

WHY THIS EXISTS. Every number behind Foxhound-4 (RQ-20261107-98e3-06: +0.49 R/trade, n 207) is measured in R per trade with
ONE POSITION PER SYMBOL and no cash (scripts/research/ml_entry_alpaca_score.py::take; the evidence record lists "live whole-share
cash-book sizing on alpaca_live is not modelled" under known_gaps). The account it trades is a small CASH book (MEASURED
/api/diag/broker_account_status 2026-11-11T22:44Z: multiplier 1, cash = equity = buying power, shorting_enabled false; the balance is
NEVER committed, supply it at run time via ALPACA_LIVE_CASH0 -- the default below is SYNTHETIC),
long only (config/accounts.yaml side_filter: long), bracket orders in WHOLE shares (alpaca_client.place), the live sizer
(RiskManager.position_size: risk qty floored, rounded UP to one share when that share's risk <= 1.5 x the budget, then capped at
0.9 x available cash), T+1 settlement armed (ALPACA_CASH_SETTLEMENT_MODE=apply, so the whole balance recycles every trade), and
in practice ONE position at a time. This module replays any trade list through that book so every candidate -- the live leg,
a tau / label / policy variant, or a challenger leg -- is scored on the same constraints and the same cost stack.

Subcommands (each writes <out>/<unit>.json + <out>/verdict.json with read_state, verdict, note, measurement):

  foxhound --section book|calib|label   Foxhound-4 recipe (config B, structure exit pivot=5;sl_only, 5-seed ensemble) re-fit on
                                        the purged DEV walk-forward (dates <= 2025-06-30, folds of ml_entry_equity.DEV_FOLDS).
                                        NO confirming-window row is loaded: the 2025-07-15.. window has been read three times
                                        (holdout ledger family ENTRY-EQ), so every diagnosis here runs where iteration is free
                                        (principles M13).
  foxhound --section features           P8-Q5: config B + ONE named feature family per arm (ml_entry_equity.FAMILY_FEATURES), plus the
                                        9-pure-noise-column control; each arm re-fit with the same recipe, scored on the live book.
  foxhound --section horizon            P8-Q8: the label/exit time stop (24 -> 48 / 72 bars) and a DAILY decision bar, each arm
                                        re-labelled and re-fit, scored on the live book.
  h2h --strategy <leg> [--trades-from]  P8-Q4-h2h: each challenger alone and the combined book (Foxhound-4 picks first, the
                                        current book leg included) vs Foxhound-4 on their common window, graded by plan s 5.2/5.4.
  legs --strategy <leg> ...             each rostered leg's Stage-0 trade list (scripts/ops/build_strategy_evidence.py, the
                                        config-exact harness that writes comms/strategy_evidence/) through the same book, one
                                        leg at a time and all legs competing for the one slot.

    python3 scripts/research/alpaca_live_book.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

SCHEMA = "alpaca_live_book/1"
CASH0_SOURCE = "env" if os.environ.get("ALPACA_LIVE_CASH0") else "synthetic-default"
CASH0 = float(os.environ.get("ALPACA_LIVE_CASH0") or 200.0)  # alpaca_live capacity.cash, read at run time; 200.0 is SYNTHETIC, not the account
TAU_LIVE = 0.25           # config/strategies.yaml ml_entry_eq_struct (artifact tau; evidence record fidelity_basis)
ENS_SEEDS = [1, 2, 3, 4, 5]
OVERLAP = 6               # 24-bar label on a 4-bar decision step: consecutive decisions share 5/6 of a label window
TAU_GRID = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
CALIB_ALTERNATIVES = ["tau0.15", "tau0.20", "tau0.30", "top1_pos", "top3_pos", "adaptive_q995_30d"]   # 6 registered draws


def _live_sizer_constants() -> Dict[str, Any]:
    """The live sizer's constants, imported (never re-declared) with a recorded fallback."""
    out: Dict[str, Any] = {}
    try:
        from src.units.accounts import risk as R
        out.update(wall=float(R._MARGIN_SAFETY_BUFFER), roundup=float(R._ROUND_UP_BUDGET_MULT), source="src/units/accounts/risk.py")
    except Exception as exc:  # noqa: BLE001  # allow-silent: falls back to the documented literals AND records the import failure in the result row's sizer.source
        out.update(wall=0.9, roundup=1.5, source=f"fallback literals (risk.py import failed: {type(exc).__name__})")
    try:
        from src.config.accounts_loader import load_accounts_dict
        accs = load_accounts_dict()
        out["risk_pct"] = float(accs["alpaca_live"]["risk"]["risk_pct"])
        out["side_filter"] = accs["alpaca_live"].get("side_filter")
    except Exception as exc:  # noqa: BLE001  # allow-silent: falls back to 0.02 AND records the read failure in sizer.risk_pct_source
        out.update(risk_pct=0.02, side_filter="long", risk_pct_source=f"fallback (accounts.yaml read failed: {type(exc).__name__})")
    return out


# ------------------------------------------------------------------------------------------------ the cash book
def _ny_date(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return t.tz_convert("America/New_York").normalize().tz_localize(None)


def replay(trades: List[Dict[str, Any]], cash0: float = CASH0, risk_pct: float = 0.02, wall: float = 0.9, roundup: float = 1.5,
           settle_bdays: int = 1, one_slot: bool = True,  # one_slot=False: an upper-bound arm (cash is not committed per position)
           long_only: bool = True, compound: bool = True) -> Dict[str, Any]:
    """Walk a trade list through the alpaca_live cash book. A trade is {symbol, entry_time, exit_time, entry, sl, net_r,
    direction?, score?}; net_r is NET of the full cost stack, in R of |entry - sl|. Simultaneous candidates are taken in the
    live pick order: predicted score descending (src/runtime/ml_pool_scoring.picks), then symbol."""
    # provenance: picks -- `score` is the regressed net R the live pick order sorts on (ml_pool_scoring.picks), not a probability
    rows = sorted(trades, key=lambda t: (pd.Timestamp(t["entry_time"]), -float(t.get("score") or 0.0), str(t["symbol"])))
    equity, busy_until, settled_from = float(cash0), None, None
    refused: Dict[str, int] = {}
    taken: List[Dict[str, Any]] = []
    for t in rows:
        et, xt = pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])
        why = None
        if long_only and str(t.get("direction", "long")).lower() not in ("long", "buy"):
            why = "short_unexecutable"
        elif one_slot and busy_until is not None and et < busy_until:
            why = "slot_busy"
        elif settle_bdays and settled_from is not None and _ny_date(et) < settled_from:
            why = "unsettled_t1"
        rps = abs(float(t["entry"]) - float(t["sl"]))
        if why is None and not (rps > 0 and float(t["entry"]) > 0):
            why = "bad_risk"
        basis = equity if compound else float(cash0)
        if why is None:
            budget = basis * risk_pct
            q = math.floor(budget / rps)
            if q < 1:
                q = 1 if rps <= roundup * budget else 0
            if q < 1:
                why = "risk_roundup_refused"
            else:
                cap = math.floor(wall * basis / float(t["entry"]))
                if cap < 1:
                    why = "unaffordable_whole_share"
                else:
                    q = min(q, cap)
        if why:
            refused[why] = refused.get(why, 0) + 1
            continue
        pnl = q * rps * float(t["net_r"])
        equity += pnl
        taken.append({"symbol": t["symbol"], "entry_time": str(et), "exit_time": str(xt), "qty": q, "risk_usd": round(q * rps, 4),
                      "notional_usd": round(q * float(t["entry"]), 2), "net_r": float(t["net_r"]), "pnl_usd": round(pnl, 4),
                      # provenance: picks -- the regressed net R carried through for the record, not a probability
                      "equity_after": round(equity, 4), "score": t.get("score")})
        busy_until = xt
        settled_from = (_ny_date(xt) + pd.offsets.BDay(settle_bdays)).normalize() if settle_bdays else None
    return book_summary(rows, taken, refused, cash0)


def book_summary(cands: List[Dict[str, Any]], taken: List[Dict[str, Any]], refused: Dict[str, int], cash0: float) -> Dict[str, Any]:
    if not cands:
        return {"n_candidates": 0, "n_taken": 0, "read_state": "no_candidates"}
    t0 = min(pd.Timestamp(c["entry_time"]) for c in cands)
    t1 = max(pd.Timestamp(c["exit_time"]) for c in cands)
    months = pd.period_range(_ny_date(t0), _ny_date(t1), freq="M")
    n_mo = max(1, len(months))
    monthly = pd.Series(0.0, index=months.astype(str))
    for x in taken:
        monthly[str(_ny_date(x["exit_time"]).to_period("M"))] += x["pnl_usd"] / cash0 * 100.0
    eq = np.array([cash0] + [x["equity_after"] for x in taken])
    dd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) > 1 else 0.0
    cand_r = np.array([float(c["net_r"]) for c in cands])
    tk_r = np.array([x["net_r"] for x in taken]) if taken else np.array([])
    se_mo = float(monthly.std(ddof=1) / math.sqrt(n_mo)) if n_mo > 1 else None
    return {
        "n_candidates": len(cands), "n_taken": len(taken), "taken_share": round(len(taken) / len(cands), 4),
        "refused": refused,
        "candidates_mean_net_r": float(cand_r.mean()), "candidates_sum_net_r": float(cand_r.sum()),
        "taken_mean_net_r": float(tk_r.mean()) if len(tk_r) else None, "taken_sum_net_r": float(tk_r.sum()) if len(tk_r) else 0.0,
        "taken_se_net_r": float(tk_r.std(ddof=1) / math.sqrt(len(tk_r))) if len(tk_r) > 1 else None,
        "pnl_usd": round(float(sum(x["pnl_usd"] for x in taken)), 4), "final_equity": round(float(eq[-1]), 4),
        "months": n_mo, "return_pct_per_month": float(monthly.mean()), "return_pct_per_month_se": se_mo,
        "return_t_month_clustered": (float(monthly.mean()) / se_mo) if se_mo else None,
        "months_with_no_trade": int((monthly == 0).sum()), "max_drawdown_usd": round(dd, 4),
        "median_risk_usd": float(np.median([x["risk_usd"] for x in taken])) if taken else None,
        "monthly_return_pct": {k: round(float(v), 4) for k, v in monthly.items()},
        "taken_head": taken[:20],
    }


def paired_monthly(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Mean and t of (a - b) monthly return %, over the months both books span."""
    ma, mb = a.get("monthly_return_pct") or {}, b.get("monthly_return_pct") or {}
    keys = sorted(set(ma) & set(mb))
    if len(keys) < 2:
        return {"n_months": len(keys), "mean_diff_pct": None, "t": None}
    d = np.array([ma[k] - mb[k] for k in keys])
    se = d.std(ddof=1) / math.sqrt(len(d))
    return {"n_months": len(keys), "mean_diff_pct": float(d.mean()), "se": float(se), "t": float(d.mean() / se) if se > 0 else None}


# ------------------------------------------------------------------------------------------------ Foxhound-4 dev OOF
def _atr14(df: pd.DataFrame) -> np.ndarray:
    """Identical to ml_entry_equity.symbol_rows: simple 14-bar mean of the true range."""
    h, lo, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    return pd.Series(tr).rolling(14, min_periods=14).mean().to_numpy()


def attach_prices(tab: pd.DataFrame, bars: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """entry (next RTH open), sl (entry - 2 ATR14 at the decision bar), entry_time, exit_time (bar i + bars_long) and raw_ret,
    the label-window return without cost and without the R normalisation (direction only)."""
    parts = []
    for sym, g in tab.groupby("symbol", sort=False):
        df = bars[sym].reset_index(drop=True)
        o = df["open"].to_numpy(float)
        atr = _atr14(df)
        i = g["i"].to_numpy(int)
        xi = np.minimum(i + g["bars_long"].to_numpy(int), len(df) - 1)
        entry = o[i + 1]
        risk = 2.0 * atr[i]
        ets = pd.to_datetime(df["ts"], utc=True).to_numpy()
        cts = pd.to_datetime(df["close_ts"], utc=True).to_numpy()
        parts.append(g.assign(entry=entry, sl=entry - risk, entry_time=ets[i + 1], exit_time=cts[xi],
                              raw_ret=g["gross_long"].to_numpy(float) * risk / entry))
    return pd.concat(parts)


def dev_oof(tab: pd.DataFrame, target: str = "net_long", log=print, feats=None, purge_days=None) -> pd.DataFrame:
    """Foxhound-4's recipe on the dev walk-forward: config B features, 5-seed pinned ensemble, purge, folds DEV_FOLDS.
    Rows <= TRAIN_END only; returns the out-of-fold rows with `pred` and `fold`, session-gated as the harness does.
    ``feats`` (P8-Q5) / ``purge_days`` (P8-Q8) override config B's features / the purge; None = the live recipe, unchanged."""
    import ml_entry_equity as M
    te = pd.Timestamp(M.TRAIN_END, tz="UTC") + pd.Timedelta(days=1)
    dev = tab[tab.ts < te].dropna(subset=["net_long", target])
    feats = list(feats) if feats is not None else M.CONFIGS["B"]["features"]
    pdays = M.PURGE_DAYS if purge_days is None else int(purge_days)
    bounds = [pd.Timestamp(x, tz="UTC") for x in M.DEV_FOLDS] + [te]
    oof = []
    for k in range(len(M.DEV_FOLDS)):
        tr = M.purge(dev[dev.ts < bounds[k]], bounds[k], pdays).dropna(subset=feats)
        ts_ = dev[(dev.ts >= bounds[k]) & (dev.ts < bounds[k + 1])].dropna(subset=feats)
        if len(tr) < 1000 or len(ts_) == 0:
            continue
        m = M._lgb({"_ens_seeds": ENS_SEEDS}).fit(tr[feats], tr[target])
        # provenance: predict -- mean of 5 pinned LGBMRegressors' regressed target (net R of the LONG side for the live label)
        oof.append(ts_.assign(pred=m.predict(ts_[feats]), fold=k))
        log(f"[oof] target {target} fold {k} train={len(tr)} test={len(ts_)} t={time.strftime('%H:%M:%S')}")
    o = pd.concat(oof)
    return o[M.session_mask(o.ts)]


def take(o: pd.DataFrame, pred: np.ndarray, tau: float) -> pd.DataFrame:
    """The harness's own selection (restricted-LONG, one position per symbol), joined back to prices for the book."""
    import ml_entry_equity as M
    o = o.assign(_p=pred)
    tk = M.taken_trades(o, o["_p"].to_numpy(), tau)
    key = o.set_index(["symbol", "ts"])
    j = key.loc[list(zip(tk.symbol, tk.ts))]
    return tk.assign(entry=j["entry"].to_numpy(), sl=j["sl"].to_numpy(), entry_time=j["entry_time"].to_numpy(),
                     exit_time=j["exit_time"].to_numpy(), fold=j["fold"].to_numpy(), score=tk["pred"].to_numpy())


def policy_pred(o: pd.DataFrame, policy: str) -> tuple:
    """(pred vector, tau) for a registered selection policy. top-k / adaptive policies mask non-selected rows to -inf."""
    p = o["pred"].to_numpy(float).copy()
    if policy.startswith("tau"):
        return p, float(policy[3:])
    if policy in ("top1_pos", "top3_pos"):
        k = int(policy[3])
        r = o.groupby("ts")["pred"].rank(ascending=False, method="first").to_numpy()
        p[r > k] = -np.inf
        return p, 0.0
    if policy == "adaptive_q995_30d":   # causal: tau at a close = the 99.5th pct of all pool scores in the PRIOR 30 days
        ts = pd.to_datetime(o["ts"], utc=True)
        order = np.argsort(ts.to_numpy())
        tsv, pv = ts.to_numpy()[order], o["pred"].to_numpy(float)[order]
        thr = np.full(len(o), np.inf)
        uniq = np.unique(tsv)
        lo = 0
        for u in uniq:
            while lo < len(tsv) and tsv[lo] < u - np.timedelta64(30, "D"):
                lo += 1
            hi = np.searchsorted(tsv, u, side="left")
            if hi - lo >= 500:
                q = float(np.quantile(pv[lo:hi], 0.995))
                idx = order[np.searchsorted(tsv, u, side="left"):np.searchsorted(tsv, u, side="right")]
                thr[idx] = max(q, 0.0)
        p = np.where(p > thr, p, -np.inf)
        return p, 0.0
    raise ValueError(policy)


def _trades(tk: pd.DataFrame) -> List[Dict[str, Any]]:
    return [{"symbol": r.symbol, "entry_time": r.entry_time, "exit_time": r.exit_time, "entry": float(r.entry), "sl": float(r.sl),
             "net_r": float(r.net_r), "direction": "long", "score": float(r.score)} for r in tk.itertuples(index=False)]


def trade_stats(tk: pd.DataFrame) -> Dict[str, Any]:
    if tk.empty:
        return {"n": 0, "mean_net_r": None}
    mo = pd.to_datetime(tk.ts, utc=True).dt.strftime("%Y-%m")
    folds = tk.groupby("fold").net_r.mean()
    return {"n": int(len(tk)), "mean_net_r": float(tk.net_r.mean()), "se": float(tk.net_r.std(ddof=1) / math.sqrt(len(tk))) if len(tk) > 1 else None,
            "trades_per_month": float(len(tk) / max(1, mo.nunique())), "months_traded": int(mo.nunique()),
            "folds_positive": int((folds > 0).sum()), "by_fold": {int(k): round(float(v), 4) for k, v in folds.items()}}


def section_book(o, sizer) -> Dict[str, Any]:
    tk = take(o, o["pred"].to_numpy(), TAU_LIVE)
    tr = _trades(tk)
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    live = replay(tr, CASH0, **kw)
    arms = {"live_book": live,
            "cash_x10_one_slot": replay(tr, CASH0 * 10, **kw),
            "no_t1_one_slot": replay(tr, CASH0, settle_bdays=0, **kw),
            "multi_slot_cash_x100_no_t1": replay(tr, CASH0 * 100, settle_bdays=0, one_slot=False, **kw)}
    unc = trade_stats(tk)
    n, m_c, m_u = live["n_taken"], live.get("taken_mean_net_r"), unc.get("mean_net_r")
    if n < 30:
        v, why = "indeterminate", f"live-book n_taken {n} < 30"
    elif m_c is not None and m_c > 0 and m_u and m_c >= 0.5 * m_u:
        v, why = "pass", f"edge survives the account: book mean {m_c:+.4f} R over n={n} vs unconstrained {m_u:+.4f} R (n={unc['n']})"
    else:
        v, why = "fail", f"edge does not survive the account: book mean {m_c} R over n={n} vs unconstrained {m_u} R (n={unc['n']})"
    return {"verdict": v, "note": why, "unconstrained": unc, "arms": arms}


def section_calib(o, sizer) -> Dict[str, Any]:
    import holdout_lock as HL
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    q = [0.5, 0.9, 0.99, 0.999]
    dist = {int(k): {**{f"q{x}": float(np.quantile(g.pred, x)) for x in q}, "max": float(g.pred.max()),
                     **{f"share_gt_{t}": float((g.pred > t).mean()) for t in TAU_GRID}, "n": int(len(g))}
            for k, g in o.groupby("fold")}
    daymax = o.groupby(pd.to_datetime(o.ts, utc=True).dt.strftime("%Y-%m-%d")).pred.max()
    pols = {f"tau{t:.2f}": None for t in TAU_GRID}
    pols.update({p: None for p in CALIB_ALTERNATIVES})
    res = {}
    for name in pols:
        p, tau = policy_pred(o, name)
        tk = take(o, p, tau)
        res[name] = {"trades": trade_stats(tk), "book": replay(_trades(tk), CASH0, **kw)}
    base = res[f"tau{TAU_LIVE:.2f}"]
    bar = HL.bar_for(len(CALIB_ALTERNATIVES))
    cmp = {}
    for name in CALIB_ALTERNATIVES:
        pm = paired_monthly(res[name]["book"], base["book"])
        ok = (res[name]["book"]["n_taken"] >= 30 and pm["mean_diff_pct"] is not None and pm["mean_diff_pct"] >= 0.25
              and (pm["t"] or 0) >= bar["point_t_min"] and res[name]["trades"].get("folds_positive", 0) >= 3)
        cmp[name] = {**pm, "clears": bool(ok)}
    winners = [k for k, c in cmp.items() if c["clears"]]
    if base["book"]["n_taken"] < 30 and not winners:
        v, why = "indeterminate", f"baseline tau {TAU_LIVE} book n_taken {base['book']['n_taken']} < 30 and no alternative clears"
    elif winners:
        best = max(winners, key=lambda k: cmp[k]["mean_diff_pct"])
        v, why = "pass", f"{best} beats tau {TAU_LIVE} on the live book by {cmp[best]['mean_diff_pct']:+.3f} %/month (t {cmp[best]['t']:.2f} >= {bar['point_t_min']})"
    else:
        v, why = "fail", f"no registered alternative beats tau {TAU_LIVE} on the live book (bar t >= {bar['point_t_min']}, >= +0.25 %/month, n >= 30, >= 3/5 folds)"
    return {"verdict": v, "note": why, "score_distribution_by_fold": dist,
            "daily_max_score": {"q10": float(daymax.quantile(0.1)), "q50": float(daymax.quantile(0.5)), "q90": float(daymax.quantile(0.9)),
                                "share_days_max_below_tau_live": float((daymax <= TAU_LIVE).mean()), "n_days": int(len(daymax))},
            "policies": res, "vs_baseline": cmp, "bar": bar}


def _ic_by_ts(o: pd.DataFrame, x: str, y: str) -> Dict[str, Any]:
    vals = []
    for _, g in o.groupby("ts"):
        if len(g) >= 10 and g[x].nunique() > 1 and g[y].nunique() > 1:
            vals.append(g[x].rank().corr(g[y].rank()))
    v = np.array([z for z in vals if z == z])
    if len(v) < 10:
        return {"ic": None, "n_ts": int(len(v))}
    se = v.std(ddof=1) / math.sqrt(len(v) / OVERLAP)
    return {"ic": float(v.mean()), "se_overlap_adj": float(se), "t": float(v.mean() / se) if se > 0 else None, "n_ts": int(len(v))}


def section_label(tab_dev: pd.DataFrame, o_base: pd.DataFrame, sizer, log=print) -> Dict[str, Any]:
    import holdout_lock as HL
    import ml_entry_equity as M
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    feats = M.CONFIGS["B"]["features"]
    ic = {y: {x: _ic_by_ts(o_base, x, y) for x in ["pred"] + [f for f in feats if f not in ("hour", "dow")]}
          for y in ("net_long", "gross_long", "raw_ret", "cost_long")}
    ob = o_base.assign(_q=o_base.groupby("ts")["atr_pct"].rank(pct=True).mul(5).clip(upper=4.999).astype(int))
    neut = []
    for _, g in ob.groupby(["ts", "_q"]):
        if len(g) >= 5 and g.pred.nunique() > 1 and g.raw_ret.nunique() > 1:
            neut.append(g.pred.rank().corr(g.raw_ret.rank()))
    nv = np.array([z for z in neut if z == z])
    nse = nv.std(ddof=1) / math.sqrt(max(1.0, len(nv) / OVERLAP)) if len(nv) > 1 else None
    base_tk = take(o_base, o_base["pred"].to_numpy(), TAU_LIVE)
    n_above = int((o_base["pred"] > TAU_LIVE).sum())
    out = {"baseline": {"trades": trade_stats(base_tk), "book": replay(_trades(base_tk), CASH0, **kw), "n_rows_above_tau": n_above}}
    for name, target in (("L1_gross_r", "gross_long"), ("L2_raw_return", "raw_ret")):
        o = dev_oof(tab_dev, target=target, log=log)
        thr = float(np.sort(o["pred"].to_numpy())[::-1][min(max(n_above, 1), len(o)) - 1])   # count-matched threshold (declared)
        tk = take(o, o["pred"].to_numpy(), thr - 1e-12)
        out[name] = {"count_matched_tau": thr, "trades": trade_stats(tk), "book": replay(_trades(tk), CASH0, **kw)}
    bar = HL.bar_for(2)
    b = out["baseline"]["trades"]
    win = []
    for name in ("L1_gross_r", "L2_raw_return"):
        t = out[name]["trades"]
        if t["n"] >= 30 and b["n"] >= 30 and t["se"] and b["se"]:
            d = t["mean_net_r"] - b["mean_net_r"]
            tt = d / math.sqrt(t["se"] ** 2 + b["se"] ** 2)
            out[name]["vs_baseline"] = {"diff_net_r": d, "t": tt}
            if d >= 0.03 and tt >= bar["point_t_min"] and t["folds_positive"] >= 3:
                win.append(name)
    diag = {"ic_pred_vs_cost_long": ic["cost_long"]["pred"].get("ic"), "ic_pred_vs_raw_ret": ic["raw_ret"]["pred"].get("ic"),
            "atr_neutral_ic_pred_vs_raw_ret": float(nv.mean()) if len(nv) else None,
            "atr_neutral_t": (float(nv.mean() / nse) if nse else None)}
    # None = could not compute (never folded into False): the IC needs >= 10 symbols at >= 10 closes
    diag["reads_cost_per_r"] = (None if diag["ic_pred_vs_cost_long"] is None or diag["atr_neutral_t"] is None else
                                bool(diag["ic_pred_vs_cost_long"] <= -0.2 and diag["atr_neutral_t"] < 2.0))
    if b["n"] < 30:
        v, why = "indeterminate", f"baseline n {b['n']} < 30"
    elif win:
        v, why = "pass", f"label redesign {win} beats the net-R label by >= 0.03 R (t >= {bar['point_t_min']}, >= 3/5 folds)"
    else:
        v, why = "fail", "neither direction-only label beats the net-R label at matched trade count by the registered bar"
    return {"verdict": v, "note": why + f"; diagnostic reads_cost_per_r={diag['reads_cost_per_r']}", "diagnostic": diag, "ic": ic,
            "variants": out, "bar": bar}


def atr_neutral_target(tab: pd.DataFrame, y: str = "net_long", q: int = 5) -> pd.Series:
    """RQ-20261117-c21d-06 arm A1: the net-R target with its (decision close x atr_pct quintile) mean removed. RQ-20261111-207f-03
    diagnosed that the net-R model ranks COST PER R (IC pred vs cost_long -0.527) rather than direction; cost per R moves with
    ATR/price, so removing each ATR bucket's mean at each close leaves the within-bucket, direction-driven part. Computed on the
    target only (no feature change); NaN where the bucket has < 2 rows."""
    b = np.floor(tab.groupby("ts")["atr_pct"].rank(pct=True).mul(q).clip(upper=q - 1e-9).fillna(-1).to_numpy(float)).astype(int)
    g = tab[y].groupby([tab["ts"], b])
    cnt = g.transform("count")
    out = tab[y] - g.transform("mean")
    return out.where(cnt >= 2)


def section_neutral(tab_dev: pd.DataFrame, o_base: pd.DataFrame, sizer, log=print) -> Dict[str, Any]:
    """RQ-20261117-c21d-06: two one-factor target arms against the live Foxhound-4 net-R recipe at TAU_LIVE, count-matched,
    graded on the realised net_long of the taken trades (the same comparison and bar as section_label / 207f-03).
      A1_atr_neutral_net   target = atr_neutral_target(net_long); score = prediction
      A2_gross_minus_cost  target = gross_long (direction head); score = prediction - cost_long (the pre-trade cost per R)"""
    import holdout_lock as HL
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    base_tk = take(o_base, o_base["pred"].to_numpy(), TAU_LIVE)
    n_above = int((o_base["pred"] > TAU_LIVE).sum())
    out = {"baseline": {"trades": trade_stats(base_tk), "book": replay(_trades(base_tk), CASH0, **kw), "n_rows_above_tau": n_above}}
    t1 = tab_dev.assign(_a1=atr_neutral_target(tab_dev))
    arms = {"A1_atr_neutral_net": (t1, "_a1", False), "A2_gross_minus_cost": (tab_dev, "gross_long", True)}
    for name, (tb, target, minus_cost) in arms.items():
        o = dev_oof(tb, target=target, log=log)
        score = o["pred"].to_numpy(float) - (o["cost_long"].to_numpy(float) if minus_cost else 0.0)
        thr = float(np.sort(score)[::-1][min(max(n_above, 1), len(o)) - 1])   # count-matched threshold (declared)
        tk = take(o, score, thr - 1e-12)
        out[name] = {"count_matched_tau": thr, "trades": trade_stats(tk), "book": replay(_trades(tk), CASH0, **kw)}
    bar = HL.bar_for(2)
    b = out["baseline"]["trades"]
    win = []
    for name in arms:
        t = out[name]["trades"]
        if t["n"] >= 30 and b["n"] >= 30 and t["se"] and b["se"]:
            d = t["mean_net_r"] - b["mean_net_r"]
            tt = d / math.sqrt(t["se"] ** 2 + b["se"] ** 2)
            out[name]["vs_baseline"] = {"diff_net_r": d, "t": tt}
            if d >= 0.03 and tt >= bar["point_t_min"] and t["folds_positive"] >= 3:
                win.append(name)
    if b["n"] < 30:
        v, why = "indeterminate", f"baseline n {b['n']} < 30"
    elif win:
        v, why = "pass", f"target arm(s) {win} beat the live net-R recipe by >= 0.03 R (t >= {bar['point_t_min']}, >= 3/5 folds)"
    else:
        v, why = "fail", "neither the ATR-neutral target nor gross-minus-cost beats the live net-R recipe at matched trade count"
    return {"verdict": v, "note": why, "variants": out, "bar": bar}


# ------------------------------------------------------------------------------------------------ P8-Q5 / P8-Q8 arms
FEATURE_FAMILIES = ["volregime", "familyrs"]   # built families (ml_entry_equity.FAMILY_FEATURES); FOMC/CPI not built (no PIT calendar)
HORIZON_ARMS = {"h48": {"hold": 48, "daily": False}, "h72": {"hold": 72, "daily": False}, "daily_h24": {"hold": 24, "daily": True}}
MATERIAL_PCT_MONTH = 0.25


def _arm_vs_base(arm: Dict[str, Any], base: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    """The P8 live-book comparison (section_calib's): paired monthly return % vs the baseline book, n_taken >= 30,
    mean diff >= +0.25 %/month, t >= the deflated point bar, >= 3 of 5 dev folds with positive mean net R."""
    pm = paired_monthly(arm["book"], base["book"])
    ok = (arm["book"]["n_taken"] >= 30 and pm["mean_diff_pct"] is not None and pm["mean_diff_pct"] >= MATERIAL_PCT_MONTH
          and (pm["t"] or 0) >= bar["point_t_min"] and arm["trades"].get("folds_positive", 0) >= 3)
    return {**pm, "clears": bool(ok)}


def section_features(tab_dev: pd.DataFrame, o_base: pd.DataFrame, sizer, families=None, log=print) -> Dict[str, Any]:
    """P8-Q5 (RQ-20261118-f7c1-03): config B + each family, config B + all families, and config B + 9 pure-noise columns, every arm
    re-fit with the live recipe (5-seed pinned ensemble, same folds / purge), taken at TAU_LIVE, replayed through the cash book.
    LOFO = (all families) minus each family; with the two built families LOFO equals the single-family arms, so it adds no draw
    (declared). Draws for the bar = number of families + 1 (all). NOISE GATE: if the noise arm itself clears the bar, the recipe
    gains from noise and the section is INDETERMINATE; a family clears only if it also beats the noise arm's monthly mean diff."""
    import holdout_lock as HL
    import ml_entry_equity as M
    fams = list(families or FEATURE_FAMILIES)
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    base_feats = M.CONFIGS["B"]["features"]
    base_tk = take(o_base, o_base["pred"].to_numpy(), TAU_LIVE)
    out = {"baseline": {"features": base_feats, "trades": trade_stats(base_tk), "book": replay(_trades(base_tk), CASH0, **kw)}}
    arms = {f"B+{f}": [f] for f in fams}
    if len(fams) > 1:
        arms["B+all"] = fams
    arms["B+noise9"] = ["noise9"]
    for name, add in arms.items():
        extra = [c for f in add for c in M.FAMILY_FEATURES[f]]
        o = dev_oof(tab_dev, log=log, feats=base_feats + extra)
        tk = take(o, o["pred"].to_numpy(), TAU_LIVE)
        out[name] = {"features_added": extra, "trades": trade_stats(tk), "book": replay(_trades(tk), CASH0, **kw)}
    draws = [k for k in arms if k != "B+noise9"]
    bar = HL.bar_for(len(draws))
    cmp = {k: _arm_vs_base(out[k], out["baseline"], bar) for k in arms}
    noise_diff = cmp["B+noise9"]["mean_diff_pct"]
    winners = [k for k in draws if cmp[k]["clears"] and (noise_diff is None or cmp[k]["mean_diff_pct"] > noise_diff)]
    b = out["baseline"]["book"]["n_taken"]
    if cmp["B+noise9"]["clears"]:
        v, why = "indeterminate", "the 9-pure-noise-column arm itself clears the bar: the recipe gains from noise (overfitting), no family read"
    elif b < 30 and not winners:
        v, why = "indeterminate", f"baseline book n_taken {b} < 30 and no family arm clears"
    elif winners:
        best = max(winners, key=lambda k: cmp[k]["mean_diff_pct"])
        v, why = "pass", f"{best} beats config B on the live book by {cmp[best]['mean_diff_pct']:+.3f} %/month (t {cmp[best]['t']:.2f} >= {bar['point_t_min']}), above the noise arm"
    else:
        v, why = "fail", f"no feature family beats config B on the live book (bar t >= {bar['point_t_min']}, >= +{MATERIAL_PCT_MONTH} %/month, n >= 30, >= 3/5 folds, > noise arm)"
    return {"verdict": v, "note": why, "families_built": fams, "families_not_built": {"events": "no point-in-time FOMC/CPI calendar in the repo"},
            "lofo_note": "with 2 families, all-minus-one == the single-family arms", "variants": out, "vs_baseline": cmp, "bar": bar, "n_draws": len(draws)}


def section_horizon(bars, pool, slip, fee, o_base: pd.DataFrame, sizer, arms=None, log=print) -> Dict[str, Any]:
    """P8-Q8 (RQ-20261118-f7c1-04): each arm re-labels the table (ml_entry_equity.build_table hold= / daily=; the structure exit stays
    SL-only with the 3-ATR TP, TP doctrine), re-fits the live recipe with the purge scaled to the label (purge_days_for), takes at
    TAU_LIVE (the regressed net R is in R units at every horizon) and replays through the cash book. The session gate stays the live
    one (declared: one factor, the label/exit). Draws for the bar = number of arms."""
    import holdout_lock as HL
    import ml_entry_equity as M
    names = list(arms or HORIZON_ARMS)
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    base_tk = take(o_base, o_base["pred"].to_numpy(), TAU_LIVE)
    out = {"baseline": {"hold": M.H, "daily": False, "trades": trade_stats(base_tk), "book": replay(_trades(base_tk), CASH0, **kw)}}
    te = pd.Timestamp(M.TRAIN_END, tz="UTC") + pd.Timedelta(days=1)
    for name in names:
        cfg = HORIZON_ARMS[name]
        t = attach_prices(M.build_table(bars, pool, slip, fee, struct=M.STRUCT_SPEC, hold=cfg["hold"], daily=cfg["daily"]), bars)
        t = t[t.ts < te]
        o = dev_oof(t, log=log, purge_days=M.purge_days_for(cfg["hold"]))
        tk = take(o, o["pred"].to_numpy(), TAU_LIVE)
        out[name] = {**cfg, "purge_days": M.purge_days_for(cfg["hold"]), "dev_rows": int(len(t)), "trades": trade_stats(tk),
                     "book": replay(_trades(tk), CASH0, **kw)}
    bar = HL.bar_for(len(names))
    cmp = {k: _arm_vs_base(out[k], out["baseline"], bar) for k in names}
    winners = [k for k in names if cmp[k]["clears"]]
    b = out["baseline"]["book"]["n_taken"]
    if b < 30 and not winners:
        v, why = "indeterminate", f"baseline book n_taken {b} < 30 and no horizon arm clears"
    elif winners:
        best = max(winners, key=lambda k: cmp[k]["mean_diff_pct"])
        v, why = "pass", f"{best} beats the 24-bar 4h-cadence recipe on the live book by {cmp[best]['mean_diff_pct']:+.3f} %/month (t {cmp[best]['t']:.2f} >= {bar['point_t_min']})"
    else:
        v, why = "fail", f"no horizon / daily arm beats the live recipe on the live book (bar t >= {bar['point_t_min']}, >= +{MATERIAL_PCT_MONTH} %/month, n >= 30, >= 3/5 folds)"
    return {"verdict": v, "note": why, "variants": out, "vs_baseline": cmp, "bar": bar, "n_draws": len(names)}


def main_foxhound(a) -> Dict[str, Any]:
    import ml_entry_equity as M
    import ml_entry_alpaca_score as S
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip
    sizer = _live_sizer_constants()
    slip, _ = resolve_cost_policy("SPY")
    fee = resolve_fee_bps_roundtrip("SPY")
    pool, prep, bars, client = M._pool_and_bars(a, M.TRAIN_END)          # bars END at TRAIN_END: the confirm window is never fetched
    tab = M.build_table(bars, pool, slip, fee, struct=M.STRUCT_SPEC)
    if a.section == "features":
        tab = M.add_feature_families(tab, bars, list(dict.fromkeys((a.families.split(",") if a.families else FEATURE_FAMILIES) + ["noise9"])))
    tab = attach_prices(tab, bars)
    te = pd.Timestamp(M.TRAIN_END, tz="UTC") + pd.Timedelta(days=1)
    if (tab.ts >= te).any():
        tab = tab[tab.ts < te]
    print(f"[table] {len(tab)} dev rows, {tab.symbol.nunique()} symbols", flush=True)
    o = dev_oof(tab)
    if a.section == "book":
        r = section_book(o, sizer)
    elif a.section == "calib":
        r = section_calib(o, sizer)
    elif a.section == "neutral":
        r = section_neutral(tab, o, sizer)
    elif a.section == "features":
        r = section_features(tab, o, sizer, families=a.families.split(",") if a.families else None)
    elif a.section == "horizon":
        r = section_horizon(bars, pool, slip, fee, o, sizer, arms=a.horizon_arms.split(",") if a.horizon_arms else None)
    else:
        r = section_label(tab, o, sizer)
    # n = the DEV OOF decisions the section read (script_run --derive-record requires a top-level n; without it every
    # P8 run landed producer_failed: 207f-01/-04 and c21d-06, PROGRAMME-REVIEW-20261118).
    r.setdefault("n", len(o))
    r.update({"sizer": sizer, "cash0_source": CASH0_SOURCE, "costs": {"slippage_bps": slip, "fee_bps": fee, "regulatory_bps": S.REGULATORY_BPS},
              "n_pool": len(pool), "pool": {k: v for k, v in prep.items() if k != "excluded"}, "train_end": M.TRAIN_END,
              "structure_exit": M.STRUCT_SPEC, "ensemble_seeds": ENS_SEEDS, "alpaca_calls": client.calls,
              "population": f"DEV walk-forward OOF restricted-LONG decisions of the Foxhound-4 recipe on the {len(pool)}-ETF pool, "
                            f"folds {M.DEV_FOLDS} to {M.TRAIN_END}; no confirming-window row loaded"})
    return r


# ------------------------------------------------------------------------------------------------ frozen artifact, live book, confirm window
# PI-20261119-K7ZSW5Z7-0003 / RQ-20261119-a10d-04: the deciding read for the real-money leg ml_entry_eq_struct. Every earlier book
# read (207f-01: -0.0576 R n 97) was a DEV-window REFIT on a live-rebuilt pool at synthetic cash; the dev reads disagree with each
# other (98e3-06 +0.132 n 1691, c21d-06 +0.0845 n 1628, 207f-01 -0.0015 n 1016) because the pool and bar snapshot moved between runs.
# This read removes both moving parts: the FROZEN served boosters (no refit), the artifact's PINNED pool_symbols, the graded confirm
# window, and the live cash book. The live balance is never committed and no workflow supplies it, so the book is read on a fixed
# CASH GRID and the unit verdict needs the grid to agree.
FROZEN_ARTIFACT = "ml/candidates/ml_entry_eq_v3_struct_ens5/model.json"
FROZEN_CASH_GRID = [250.0, 1000.0, 5000.0]
FROZEN_MIN_TAKEN = 30
FROZEN_FAMILY = "ENTRY-EQ"


def frozen_arm_verdict(book: Dict[str, Any], bar: Dict[str, Any]) -> tuple:
    """Per cash arm (registered): INDETERMINATE if n_taken < 30; PASS if taken mean net R > 0 AND mean >= point_t_min(N) x se;
    FAIL if the deflated CI upper bound (mean + ci_z(N) x se) < 0; INDETERMINATE otherwise."""
    n, m, se = book.get("n_taken") or 0, book.get("taken_mean_net_r"), book.get("taken_se_net_r")
    if n < FROZEN_MIN_TAKEN or m is None or se is None:
        return "indeterminate", f"n_taken {n} < {FROZEN_MIN_TAKEN}"
    if m > 0 and m >= bar["point_t_min"] * se:
        return "pass", f"mean {m:+.4f} R >= {bar['point_t_min']} x se {se:.4f} (n {n})"
    if m + bar["ci_z"] * se < 0:
        return "fail", f"mean {m:+.4f} R, deflated CI upper {m + bar['ci_z'] * se:+.4f} < 0 (n {n})"
    return "indeterminate", f"mean {m:+.4f} R, se {se:.4f}: neither above the deflated point bar nor below 0 at ci_z {bar['ci_z']} (n {n})"


def frozen_unit_verdict(arms: Dict[str, str], reproduces: bool) -> tuple:
    """Unit (registered): INDETERMINATE unless the frozen population reproduces 98e3-06 exactly (n 207, mean 0.4922070639835765);
    PASS iff every cash arm PASSES; FAIL iff every cash arm FAILS; INDETERMINATE otherwise (the verdict depends on the balance)."""
    if not reproduces:
        return "indeterminate", "the frozen population did not reproduce 98e3-06 (n / mean mismatch): the book read is not of the graded population"
    vs = set(arms.values())
    if vs == {"pass"}:
        return "pass", "the edge survives the live cash book at every cash level on the grid"
    if vs == {"fail"}:
        return "fail", "the live cash book loses at every cash level on the grid"
    return "indeterminate", "cash-dependent or unresolved: " + ", ".join(f"{k} {v}" for k, v in arms.items())


def main_frozen_book(a) -> Dict[str, Any]:
    import holdout_lock as HL
    import ml_entry_equity as M
    import ml_entry_alpaca_score as S
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip
    sizer = _live_sizer_constants()
    slip, _ = resolve_cost_policy("SPY")
    fee = resolve_fee_bps_roundtrip("SPY")
    art = json.loads((REPO / a.artifact).read_text())
    pool = list(art["pool_symbols"])
    feats, tau, predict, model_id = M._artifact_scorer(a.artifact)
    claim = HL.claim_read(f"{FROZEN_FAMILY}-{model_id}-LIVEBOOK", a.start, a.end, a.unit, a.where, train_end=M.TRAIN_END,
                          family=FROZEN_FAMILY)
    bar = claim["bar"]
    bars, client = M._pinned_pool_and_bars(a, a.end, pool)
    tab = M.build_table(bars, pool, slip, fee, struct=art.get("structure_exit") or M.STRUCT_SPEC)
    rep, tk0 = M.reproduce_frozen(tab, a.artifact, a.start, a.end, int(a.expect_n), float(a.expect_mean), pool, bars.keys())
    tab = attach_prices(tab, bars)
    hs, he = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC") + pd.Timedelta(days=1)
    test = tab[(tab.ts >= hs) & (tab.ts < he)].dropna(subset=feats + ["net_long"])
    test = test[M.session_mask(test.ts)]
    test = test.assign(fold=pd.to_datetime(test.ts, utc=True).dt.year * 100 + pd.to_datetime(test.ts, utc=True).dt.month)
    tk = take(test, predict(test), tau)   # provenance: predict -- mean regressed LONG net R of the frozen boosters, not a probability
    tr = _trades(tk)
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    books = {f"cash_{int(c)}": replay(tr, c, **kw) for c in FROZEN_CASH_GRID}
    arm_v = {}
    for k, b in books.items():
        v_, why_ = frozen_arm_verdict(b, bar)
        b["verdict"], b["reason"] = v_, why_
        arm_v[k] = v_
    reported = {f"cash_{int(c)}_no_t1": replay(tr, c, settle_bdays=0, **kw) for c in FROZEN_CASH_GRID}
    reported["multi_slot_no_cash_limit"] = replay(tr, 1e9, settle_bdays=0, one_slot=False, **kw)
    reproduces = bool(rep["reproduction"]["reproduces"]) and len(tk) == len(tk0)
    v, why = frozen_unit_verdict(arm_v, reproduces)
    note = (f"{why}; frozen {model_id} on its pinned {len(pool)}-ETF pool, {a.start}..{a.end}: unconstrained n {len(tk)} mean "
            f"{float(tk.net_r.mean()) if len(tk) else float('nan'):+.4f} R; " + "; ".join(
                f"{k}: n_taken {b['n_taken']} mean {b.get('taken_mean_net_r')} -> {b['verdict']}" for k, b in books.items())
            + f"; bar N={bar['n_tries']} (t_min {bar['point_t_min']}, ci_z {bar['ci_z']})")
    return {"verdict": v, "note": note, "n": int(len(tk)), "books": books, "reported_arms": reported, "reproduction": rep,
            "holdout_claim": {k: claim[k] for k in ("model_id", "family", "n_tries", "bar", "read_at")},
            "sizer": sizer, "cash_grid": FROZEN_CASH_GRID, "cash0_source": "grid (the live balance is never committed)",
            "costs": {"slippage_bps": slip, "fee_bps": fee, "regulatory_bps": S.REGULATORY_BPS}, "alpaca_calls": client.calls,
            "population": (f"FROZEN {model_id} (no refit) restricted-LONG decisions on its pinned {len(pool)}-ETF pool_symbols, confirm window "
                           f"{a.start}..{a.end}, net of the Alpaca cost stack, walked through the alpaca_live one-slot whole-share T+1 cash book "
                           f"at cash {FROZEN_CASH_GRID}")}


# ------------------------------------------------------------------------------------------------ slot policy (a10d-09)
# RQ-20261119-a10d-09 (manager 2026-11-19 11:44Z, after a10d-04 graded INDETERMINATE): the one-slot book took 22 of 207 frozen
# eq_struct signals (slot busy ~88%) and those 22 averaged below zero while the 207 average +0.49 R. Two questions, one read:
# (1) is that gap the book's SELECTION or NOISE; (2) does a different slot policy carry the population's edge into the book.
SLOT_POLICIES = ["first_signal", "score_gate_p50_30d", "slots_2", "slots_3"]
SLOT_CHALLENGERS = ["score_gate_p50_30d", "slots_2", "slots_3"]
SLOT_NULL_DRAWS = 2000
SLOT_NULL_SEED = 20261119
SLOT_NOISE_P = 0.10


def replay_slots(trades: List[Dict[str, Any]], cash0: float, k: int, risk_pct: float = 0.02, wall: float = 0.9,
                 roundup: float = 1.5, settle_bdays: int = 1, long_only: bool = True) -> Dict[str, Any]:
    """The alpaca_live cash book with k concurrent positions (k >= 2). Same pick order, sizer and cost basis as replay(); the
    cash ledger is explicit: an open position commits its notional, a closed one's proceeds are unsettled until T+settle_bdays
    (NY dates), and a new position is capped at min(wall x equity / k, free settled cash) whole shares. P&L is booked at exit.
    k == 1 is NOT routed here: the registered status quo is replay() itself, reproduced exactly."""
    assert k >= 2, "k == 1 is replay(); this ledger is for the multi-slot arms"
    # provenance: picks -- `score` is the regressed net R the live pick order sorts on (ml_pool_scoring.picks), not a probability
    rows = sorted(trades, key=lambda t: (pd.Timestamp(t["entry_time"]), -float(t.get("score") or 0.0), str(t["symbol"])))
    equity = float(cash0)
    open_pos: List[Dict[str, Any]] = []      # {exit, notional, pnl, rec}
    unsettled: List[tuple] = []              # (settle NY date, amount)
    refused: Dict[str, int] = {}
    taken: List[Dict[str, Any]] = []

    def close_until(ts):
        nonlocal equity
        for pos in sorted([p_ for p_ in open_pos if p_["exit"] <= ts], key=lambda p_: p_["exit"]):
            equity += pos["pnl"]
            pos["rec"]["equity_after"] = round(equity, 4)
            if settle_bdays:
                unsettled.append(((_ny_date(pos["exit"]) + pd.offsets.BDay(settle_bdays)).normalize(), pos["notional"] + pos["pnl"]))
            open_pos.remove(pos)

    for t in rows:
        et, xt = pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])
        close_until(et)
        today = _ny_date(et)
        unsettled[:] = [(d, amt) for d, amt in unsettled if d > today]
        committed = sum(p_["notional"] for p_ in open_pos)
        free = equity - committed - sum(amt for _, amt in unsettled)
        why = None
        if long_only and str(t.get("direction", "long")).lower() not in ("long", "buy"):
            why = "short_unexecutable"
        elif len(open_pos) >= k:
            why = "slot_busy"
        rps = abs(float(t["entry"]) - float(t["sl"]))
        if why is None and not (rps > 0 and float(t["entry"]) > 0):
            why = "bad_risk"
        q = 0
        if why is None:
            budget = equity * risk_pct
            q = math.floor(budget / rps)
            if q < 1:
                q = 1 if rps <= roundup * budget else 0
            if q < 1:
                why = "risk_roundup_refused"
            else:
                cap = math.floor(min(wall * equity / k, free) / float(t["entry"]))
                if cap < 1:
                    why = "unsettled_t1" if math.floor(wall * equity / k / float(t["entry"])) >= 1 else "unaffordable_whole_share"
                else:
                    q = min(q, cap)
        if why:
            refused[why] = refused.get(why, 0) + 1
            continue
        pnl = q * rps * float(t["net_r"])
        rec = {"symbol": t["symbol"], "entry_time": str(et), "exit_time": str(xt), "qty": q, "risk_usd": round(q * rps, 4),
               "notional_usd": round(q * float(t["entry"]), 2), "net_r": float(t["net_r"]), "pnl_usd": round(pnl, 4),
               "equity_after": None, "score": t.get("score")}   # provenance: picks -- regressed net R, not a probability
        taken.append(rec)
        open_pos.append({"exit": xt, "notional": q * float(t["entry"]), "pnl": pnl, "rec": rec})
    if open_pos:
        close_until(max(p_["exit"] for p_ in open_pos))
    # book_summary walks equity_after in taken order; for overlapping positions that is the equity at each one's exit
    return book_summary(rows, taken, refused, cash0)


def score_gate_p50_30d(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep a candidate only if its score >= the median score of the candidates whose entry is in the PRIOR 30 days (causal; a
    candidate with fewer than 5 prior-30-day candidates is kept). Reserves the one slot for the stronger signals."""
    rows = sorted(trades, key=lambda t: pd.Timestamp(t["entry_time"]))
    ts = [pd.Timestamp(t["entry_time"]) for t in rows]
    # provenance: picks -- `score` is the regressed net R (ml_pool_scoring.picks order key), not a probability
    sc = [float(t.get("score") or 0.0) for t in rows]
    out = []
    for i, t in enumerate(rows):
        prior = [sc[j] for j in range(i) if ts[i] - pd.Timedelta(days=30) <= ts[j] < ts[i]]
        if len(prior) < 5 or sc[i] >= float(np.median(prior)):
            out.append(t)
    return out


def slot_book(trades: List[Dict[str, Any]], policy: str, cash0: float, **kw) -> Dict[str, Any]:
    if policy == "first_signal":
        return replay(trades, cash0, **kw)
    if policy == "score_gate_p50_30d":
        b = replay(score_gate_p50_30d(trades), cash0, **kw)
        b["gated_out"] = len(trades) - b.get("n_candidates", 0)
        return b
    if policy.startswith("slots_"):
        return replay_slots(trades, cash0, int(policy.split("_")[1]), **kw)
    raise ValueError(policy)


def selection_null(trades: List[Dict[str, Any]], cash0: float, draws: int = SLOT_NULL_DRAWS, seed: int = SLOT_NULL_SEED,
                   **kw) -> Dict[str, Any]:
    """Is the status-quo book's taken mean explained by WHICH trades the one slot picks (selection) or by chance (noise)?
    Null: shuffle net_r across the candidates (times, prices and scores kept), replay the status quo, record the taken mean.
    p_low = share of null draws with taken mean <= the observed taken mean."""
    obs = replay(trades, cash0, **kw)
    m_obs = obs.get("taken_mean_net_r")
    rng = np.random.default_rng(seed)
    r = np.array([float(t["net_r"]) for t in trades])
    vals = []
    for _ in range(draws):
        perm = rng.permutation(r)
        sh = [dict(t, net_r=float(x)) for t, x in zip(trades, perm)]
        m = replay(sh, cash0, **kw).get("taken_mean_net_r")
        if m is not None:
            vals.append(m)
    vals = np.array(vals)
    p_low = float(np.mean(vals <= m_obs)) if len(vals) and m_obs is not None else None
    return {"observed_taken_mean": m_obs, "n_taken": obs.get("n_taken"), "null_mean": float(vals.mean()) if len(vals) else None,
            "null_sd": float(vals.std(ddof=1)) if len(vals) > 1 else None, "p_low": p_low, "draws": int(len(vals)), "seed": seed}


def selection_verdict(nulls: Dict[str, Dict[str, Any]], alpha: float) -> tuple:
    """Registered: SELECTION if p_low < alpha (the claim's Sidak alpha at N) at EVERY cash level; NOISE if p_low >= 0.10 at every
    cash level; UNRESOLVED otherwise."""
    ps = [v.get("p_low") for v in nulls.values()]
    if any(p_ is None for p_ in ps):
        return "unresolved", "a null could not be scored"
    if all(p_ < alpha for p_ in ps):
        return "selection", f"p_low {ps} all < alpha {alpha}"
    if all(p_ >= SLOT_NOISE_P for p_ in ps):
        return "noise", f"p_low {ps} all >= {SLOT_NOISE_P}"
    return "unresolved", f"p_low {ps} between alpha {alpha} and {SLOT_NOISE_P}"


def slot_unit_verdict(arm_v: Dict[str, Dict[str, str]], reproduces: bool) -> tuple:
    """Registered: INDETERMINATE unless the population AND the first_signal book reproduce a10d-04 exactly. PASS iff some challenger
    policy PASSES at every cash level; FAIL iff every challenger FAILS at every cash level; INDETERMINATE otherwise."""
    if not reproduces:
        return "indeterminate", "the population or the first_signal book did not reproduce a10d-04: not the graded book"
    passing = [p_ for p_ in SLOT_CHALLENGERS if set(arm_v[p_].values()) == {"pass"}]
    if passing:
        return "pass", "challenger(s) carrying the edge at every cash level: " + ", ".join(passing)
    if all(set(arm_v[p_].values()) == {"fail"} for p_ in SLOT_CHALLENGERS):
        return "fail", "every challenger slot policy loses at every cash level"
    return "indeterminate", "no challenger passes at every cash level: " + "; ".join(
        f"{p_} " + ",".join(f"{c}={v}" for c, v in arm_v[p_].items()) for p_ in SLOT_CHALLENGERS)


A10D04_FIRST_SIGNAL = {"cash_250": (22, -0.03453278230010933), "cash_1000": (22, -0.19676036273692965),
                       "cash_5000": (22, -0.08179399402889383)}


def main_slot_book(a) -> Dict[str, Any]:
    import holdout_lock as HL
    import ml_entry_equity as M
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip
    sizer = _live_sizer_constants()
    slip, _ = resolve_cost_policy("SPY")
    fee = resolve_fee_bps_roundtrip("SPY")
    art = json.loads((REPO / a.artifact).read_text())
    pool = list(art["pool_symbols"])
    feats, tau, predict, model_id = M._artifact_scorer(a.artifact)
    claim = HL.claim_read(f"{FROZEN_FAMILY}-{model_id}-SLOTPOLICY", a.start, a.end, a.unit, a.where, train_end=M.TRAIN_END,
                          family=FROZEN_FAMILY)
    bar = claim["bar"]
    bar_ch = HL.bar_for(int(bar["n_tries"]) + len(SLOT_CHALLENGERS) - 1)   # three challengers in one read: +2 tries
    bars, client = M._pinned_pool_and_bars(a, a.end, pool)
    tab = M.build_table(bars, pool, slip, fee, struct=art.get("structure_exit") or M.STRUCT_SPEC)
    rep, tk0 = M.reproduce_frozen(tab, a.artifact, a.start, a.end, int(a.expect_n), float(a.expect_mean), pool, bars.keys())
    tab = attach_prices(tab, bars)
    hs, he = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC") + pd.Timedelta(days=1)
    test = tab[(tab.ts >= hs) & (tab.ts < he)].dropna(subset=feats + ["net_long"])
    test = test[M.session_mask(test.ts)]
    test = test.assign(fold=pd.to_datetime(test.ts, utc=True).dt.year * 100 + pd.to_datetime(test.ts, utc=True).dt.month)
    tk = take(test, predict(test), tau)   # provenance: predict -- mean regressed LONG net R of the frozen boosters, not a probability
    tr = _trades(tk)
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    books: Dict[str, Dict[str, Any]] = {}
    arm_v: Dict[str, Dict[str, str]] = {}
    for pol in SLOT_POLICIES:
        books[pol], arm_v[pol] = {}, {}
        for c in FROZEN_CASH_GRID:
            b = slot_book(tr, pol, c, **kw)
            v_, why_ = frozen_arm_verdict(b, bar_ch if pol in SLOT_CHALLENGERS else bar)
            b["verdict"], b["reason"] = v_, why_
            books[pol][f"cash_{int(c)}"], arm_v[pol][f"cash_{int(c)}"] = b, v_
    fs_ok = all(books["first_signal"][k].get("n_taken") == n and books["first_signal"][k].get("taken_mean_net_r") is not None
                and abs(books["first_signal"][k]["taken_mean_net_r"] - m) < 1e-9 for k, (n, m) in A10D04_FIRST_SIGNAL.items())
    reproduces = bool(rep["reproduction"]["reproduces"]) and len(tk) == len(tk0) and fs_ok
    nulls = {f"cash_{int(c)}": selection_null(tr, c, **kw) for c in FROZEN_CASH_GRID}
    sel, sel_why = selection_verdict(nulls, float(bar["alpha_one_sided"]))
    v, why = slot_unit_verdict(arm_v, reproduces)
    note = (f"{why}; selection-vs-noise: {sel} ({sel_why}); frozen {model_id}, {len(pool)}-ETF pool, {a.start}..{a.end}, unconstrained n "
            f"{len(tk)}; first_signal reproduces a10d-04: {fs_ok}; " + "; ".join(
                f"{p_}: " + ", ".join(f"{c} n {books[p_][c].get('n_taken')} mean {books[p_][c].get('taken_mean_net_r')} -> {arm_v[p_][c]}"
                                      for c in books[p_]) for p_ in SLOT_POLICIES)
            + f"; bar N={bar['n_tries']} (status quo), challengers N={bar_ch['n_tries']} (t_min {bar_ch['point_t_min']}, ci_z {bar_ch['ci_z']})")
    return {"verdict": v, "note": note, "n": int(len(tk)), "books": books, "arm_verdicts": arm_v, "selection_null": nulls,
            "selection_verdict": sel, "first_signal_reproduces_a10d04": fs_ok, "reproduction": rep,
            "holdout_claim": {k: claim[k] for k in ("model_id", "family", "n_tries", "bar", "read_at")}, "challenger_bar": bar_ch,
            "sizer": sizer, "cash_grid": FROZEN_CASH_GRID, "cash0_source": "grid (the live balance is never committed)",
            "costs": {"slippage_bps": slip, "fee_bps": fee}, "alpaca_calls": client.calls,
            "population": (f"FROZEN {model_id} (no refit) restricted-LONG decisions on its pinned {len(pool)}-ETF pool_symbols, {a.start}..{a.end}, "
                           f"net of the Alpaca cost stack, walked through the alpaca_live whole-share T+1 cash book under slot policies "
                           f"{SLOT_POLICIES} at cash {FROZEN_CASH_GRID}")}


# ------------------------------------------------------------------------------------------------ challenger legs
def leg_trades(name: str, workdir: Path, days: int) -> tuple:
    cmd = [sys.executable, str(REPO / "scripts/ops/build_strategy_evidence.py"), "--strategy", name, "--workdir", str(workdir),
           "--out", str(workdir / "evidence"), "--days", str(days)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    f = workdir / f"{name}__trades.jsonl"
    rows = [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []
    out = []
    for r in rows:
        if all(k in r for k in ("entry_time", "exit_time", "entry", "sl", "net_r")):
            out.append({"symbol": r.get("symbol") or name, "entry_time": pd.Timestamp(r["entry_time"]), "exit_time": pd.Timestamp(r["exit_time"]),
                        "entry": float(r["entry"]), "sl": float(r["sl"]), "net_r": float(r["net_r"]),
                        "direction": r.get("direction", "long"), "score": 0.0, "leg": name})
    ev = workdir / "evidence" / f"{name}.json"
    err = None
    try:
        err = json.loads(ev.read_text()).get("error") if ev.exists() else "no evidence record written"
    except Exception as exc:  # noqa: BLE001  # allow-silent: the unreadable record is reported per leg in harness_runs.evidence_error
        err = f"evidence record unreadable: {type(exc).__name__}"
    return out, {"returncode": p.returncode, "rows": len(rows), "usable": len(out), "evidence_error": err, "stderr_tail": p.stderr[-600:]}


def main_legs(a) -> Dict[str, Any]:
    sizer = _live_sizer_constants()
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    work = Path(tempfile.mkdtemp(prefix="alb_legs_"))
    per, allt, runs = {}, [], {}
    for name in a.strategy:
        tr, info = leg_trades(name, work, a.days)
        runs[name] = info
        per[name] = replay(tr, CASH0, **kw) if tr else {"n_candidates": 0, "n_taken": 0, "read_state": "no_trades"}
        allt += tr
    combined = replay(allt, CASH0, **kw) if allt else {"n_candidates": 0, "n_taken": 0}
    qual = [k for k, v in per.items() if v.get("n_taken", 0) >= 30 and (v.get("return_t_month_clustered") or 0) >= 1.0
            and (v.get("taken_mean_net_r") or 0) > 0]
    if not any(v.get("n_taken", 0) >= 30 for v in per.values()):
        v, why = "indeterminate", "no leg reaches n_taken >= 30 on the live book"
    elif qual:
        v, why = "pass", f"legs that qualify for a head-to-head with Foxhound-4: {qual}"
    else:
        v, why = "fail", "no leg reaches n_taken >= 30 with book mean net R > 0 and month-clustered t >= 1.0"
    return {"verdict": v, "note": why, "n": int(combined.get("n_candidates") or 0), "per_leg": per, "combined_one_slot": combined,
            "harness_runs": runs, "sizer": sizer,
            "cash0_source": CASH0_SOURCE, "days": a.days,
            "population": f"Stage-0 trade lists of {len(a.strategy)} rostered equity legs (build_strategy_evidence, last {a.days} days, "
                          f"config-exact harness, net of its cost stack) replayed through the alpaca_live cash book"}


# ------------------------------------------------------------------------------------------------ head-to-head (P8-Q4-h2h)
H2H_MATERIALITY_PCT = 0.25      # docs/research/programmes/08-ALPACA-LIVE-BOOK.md s 5.2: >= +0.25 % of the book per month
H2H_DD_MULT = 1.5               # s 5.2: max drawdown no worse than 1.5x the incumbent's
H2H_MIN_TAKEN = 30              # s 5.2: n_taken >= 30 for both books


def load_trades(path: Path) -> List[Dict[str, Any]]:
    """A trade list from a .jsonl (one trade per line) or a .json ({"trades": [...]} or a list), in replay()'s shape."""
    txt = Path(path).read_text()
    rows = [json.loads(x) for x in txt.splitlines() if x.strip()] if str(path).endswith(".jsonl") else json.loads(txt)
    if isinstance(rows, dict):
        rows = rows.get("trades") or []
    out = []
    for r in rows:
        # provenance: picks -- `score` is the regressed net R the live pick order sorts on (ml_pool_scoring.picks), carried through
        out.append({"symbol": r["symbol"], "entry_time": pd.Timestamp(r["entry_time"]), "exit_time": pd.Timestamp(r["exit_time"]),
                    "entry": float(r["entry"]), "sl": float(r["sl"]), "net_r": float(r["net_r"]),
                    "direction": r.get("direction", "long"), "score": float(r.get("score") or 0.0), "leg": r.get("leg")})
    return out


def _utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def common_window(*lists: List[Dict[str, Any]]) -> tuple:
    """[latest first entry, earliest last entry] over the non-empty lists: the span every list covers."""
    spans = [(min(_utc(t["entry_time"]) for t in x), max(_utc(t["entry_time"]) for t in x)) for x in lists if x]
    if not spans:
        return None, None
    return max(s[0] for s in spans), min(s[1] for s in spans)


def clip(trades: List[Dict[str, Any]], lo, hi) -> List[Dict[str, Any]]:
    return [t for t in trades if lo <= _utc(t["entry_time"]) <= hi]


def h2h_grade(arm: Dict[str, Any], inc: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    """s 5.2 of the P8 plan, every clause reported: paired monthly mean diff >= +0.25 %, paired t >= bar point_t_min,
    n_taken >= 30 for both, max drawdown <= 1.5x the incumbent's."""
    pm = paired_monthly(arm, inc)
    na, ni = int(arm.get("n_taken") or 0), int(inc.get("n_taken") or 0)
    dda, ddi = float(arm.get("max_drawdown_usd") or 0.0), float(inc.get("max_drawdown_usd") or 0.0)
    cl = {"materiality": pm["mean_diff_pct"] is not None and pm["mean_diff_pct"] >= H2H_MATERIALITY_PCT,
          "paired_t": pm["t"] is not None and pm["t"] >= bar["point_t_min"],
          "n_taken_both": na >= H2H_MIN_TAKEN and ni >= H2H_MIN_TAKEN,
          "drawdown": dda <= H2H_DD_MULT * ddi if ddi > 0 else dda == 0.0}
    return {"paired_monthly": pm, "n_taken": na, "n_taken_incumbent": ni, "max_drawdown_usd": dda,
            "max_drawdown_usd_incumbent": ddi, "clauses": cl, "clears": all(cl.values())}


def h2h_verdict(books: Dict[str, Dict[str, Any]], challengers: List[str], bar: Dict[str, Any]) -> Dict[str, Any]:
    """s 5.4: JOIN iff the combined book clears vs the incumbent; REPLACE iff a challenger alone clears vs the incumbent AND
    beats the combined book by the same test. INDETERMINATE when the incumbent or the combined book is under n_taken 30."""
    inc = books["incumbent"]
    grades = {c: h2h_grade(books[c], inc, bar) for c in challengers}
    grades["combined"] = h2h_grade(books["combined"], inc, bar)
    replace = [c for c in challengers if grades[c]["clears"] and h2h_grade(books[c], books["combined"], bar)["clears"]]
    join = grades["combined"]["clears"]
    if int(inc.get("n_taken") or 0) < H2H_MIN_TAKEN or int(books["combined"].get("n_taken") or 0) < H2H_MIN_TAKEN:
        v, why = "indeterminate", f"n_taken under {H2H_MIN_TAKEN} on the incumbent or the combined book"
    elif replace:
        v, why = "pass", f"REPLACE: {replace} beat Foxhound-4 alone and the combined book on the alpaca_live book"
    elif join:
        v, why = "pass", "JOIN: the combined book (Foxhound-4 picks first) beats Foxhound-4 alone on the alpaca_live book"
    else:
        v, why = "fail", "no challenger, alone or combined, clears s 5.2 against Foxhound-4 on the common window"
    return {"verdict": v, "note": why, "grades": grades, "replace": replace, "join": join, "bar": bar}


def _foxhound_dev_trades(a) -> tuple:
    """Foxhound-4 as configured (tau 0.25) on the purged DEV walk-forward: the same table and OOF as `foxhound --section book`."""
    import ml_entry_equity as M
    pool, prep, bars, client = M._pool_and_bars(a, M.TRAIN_END)
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip
    tab = attach_prices(M.build_table(bars, pool, resolve_cost_policy("SPY")[0], resolve_fee_bps_roundtrip("SPY"), struct=M.STRUCT_SPEC), bars)
    tab = tab[tab.ts < pd.Timestamp(M.TRAIN_END, tz="UTC") + pd.Timedelta(days=1)]
    o = dev_oof(tab)
    return [{**t, "leg": "foxhound4"} for t in _trades(take(o, o["pred"].to_numpy(), TAU_LIVE))], {"n_pool": len(pool), "dev_rows": len(tab)}


def main_h2h(a) -> Dict[str, Any]:
    import holdout_lock
    sizer = _live_sizer_constants()
    kw = dict(risk_pct=sizer["risk_pct"], wall=sizer["wall"], roundup=sizer["roundup"])
    out = Path(a.out)
    if a.trades_from:
        fox, fox_info = load_trades(Path(a.trades_from)), {"trades_from": a.trades_from}
    else:
        fox, fox_info = _foxhound_dev_trades(a)
        (out / "foxhound4_dev_trades.jsonl").write_text("".join(json.dumps(t, default=str) + "\n" for t in fox))
    work = Path(tempfile.mkdtemp(prefix="alb_h2h_"))
    legs, runs = {}, {}
    for name in list(dict.fromkeys(a.strategy + ([a.book_leg] if a.book_leg else []))):
        legs[name], runs[name] = leg_trades(name, work, a.days)
    lo, hi = common_window(fox, *[legs[c] for c in a.strategy])
    if lo is None or lo >= hi:
        return {"verdict": "indeterminate", "note": "no common window between Foxhound-4 and the challengers", "n": 0, "harness_runs": runs}
    fox_c = clip(fox, lo, hi)
    books = {"incumbent": replay(fox_c, CASH0, **kw)}
    for c in a.strategy:
        books[c] = replay(clip(legs[c], lo, hi), CASH0, **kw)
    comb = fox_c + [t for name, tr in legs.items() for t in clip(tr, lo, hi)]     # leg trades carry score 0: Foxhound-4 picks first
    books["combined"] = replay(comb, CASH0, **kw)
    bar = holdout_lock.bar_for(len(a.strategy) + 1)
    r = h2h_verdict(books, a.strategy, bar)
    overlaps_confirm = hi >= pd.Timestamp("2025-07-15", tz="UTC")
    r.update({"n": int(books["combined"].get("n_candidates") or 0), "common_window": [str(lo), str(hi)],
              "overlaps_entry_eq_confirm_window": bool(overlaps_confirm),
              "books": {k: {kk: v.get(kk) for kk in ("n_candidates", "n_taken", "taken_mean_net_r", "return_pct_per_month",
                                                       "return_t_month_clustered", "max_drawdown_usd", "refused", "months")}
                        for k, v in books.items()},
              "slot_priority": "Foxhound-4 first (score = its regressed net R; leg trades score 0), then symbol",
              "book_leg": a.book_leg, "foxhound": fox_info, "harness_runs": runs, "sizer": sizer, "cash0_source": CASH0_SOURCE,
              "population": f"Foxhound-4 DEV OOF trades (tau {TAU_LIVE}) and the Stage-0 trades of {a.strategy} (+ {a.book_leg} in the "
                            f"combined book), clipped to their common window {str(lo)[:10]}..{str(hi)[:10]}, replayed through the "
                            f"alpaca_live cash book"})
    return r


# ------------------------------------------------------------------------------------------------ self-test
def _self_test() -> int:
    fails = []

    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    T = pd.Timestamp
    base = dict(direction="long", score=0.0)
    # 1 share of a $100 ETF with $1 stop: budget cash0*0.02 -> q=3, cap floor(0.9*cash0/100)=1 -> 1 share
    r = replay([{**base, "symbol": "A", "entry_time": T("2025-01-06 15:30Z"), "exit_time": T("2025-01-07 20:00Z"), "entry": 100, "sl": 99, "net_r": 1.0}])
    check("cash wall clamps to 1 share", r["n_taken"] == 1 and r["taken_head"][0]["qty"] == 1 and abs(r["pnl_usd"] - 1.0) < 1e-9)
    # unaffordable: $250 share
    r = replay([{**base, "symbol": "B", "entry_time": T("2025-01-06 15:30Z"), "exit_time": T("2025-01-07 20:00Z"), "entry": 250, "sl": 249, "net_r": 1.0}])
    check("whole share above the wall refused", r["n_taken"] == 0 and r["refused"].get("unaffordable_whole_share") == 1)
    # round-up: $10 stop on a $50 share: budget 3.89 -> q=0; one-share risk 10 > 1.5*3.89 -> refused
    r = replay([{**base, "symbol": "C", "entry_time": T("2025-01-06 15:30Z"), "exit_time": T("2025-01-07 20:00Z"), "entry": 50, "sl": 40, "net_r": 1.0}])
    check("round-up refused above 1.5x budget", r["refused"].get("risk_roundup_refused") == 1)
    # one slot + T+1 + score order
    tr = [{**base, "symbol": "D", "entry_time": T("2025-01-06 15:30Z"), "exit_time": T("2025-01-07 20:00Z"), "entry": 20, "sl": 19.5, "net_r": 1.0, "score": 0.3},
          {**base, "symbol": "E", "entry_time": T("2025-01-06 15:30Z"), "exit_time": T("2025-01-07 20:00Z"), "entry": 20, "sl": 19.5, "net_r": -1.0, "score": 0.5},
          {**base, "symbol": "F", "entry_time": T("2025-01-07 21:00Z"), "exit_time": T("2025-01-09 20:00Z"), "entry": 20, "sl": 19.5, "net_r": 1.0},
          {**base, "symbol": "G", "entry_time": T("2025-01-08 15:30Z"), "exit_time": T("2025-01-09 20:00Z"), "entry": 20, "sl": 19.5, "net_r": 1.0},
          {**base, "symbol": "H", "entry_time": T("2025-01-08 15:30Z"), "exit_time": T("2025-01-09 20:00Z"), "entry": 20, "sl": 19.5, "net_r": 1.0, "direction": "short"}]
    r = replay(tr)
    check("higher score takes the slot", r["taken_head"][0]["symbol"] == "E")
    check("slot busy refusal", r["refused"].get("slot_busy") == 1)
    check("T+1: same-day re-entry refused, next business day allowed",
          r["refused"].get("unsettled_t1") == 1 and [x["symbol"] for x in r["taken_head"]] == ["E", "G"])
    check("short refused on a long-only book", r["refused"].get("short_unexecutable") == 1)
    r0 = replay(tr, settle_bdays=0)
    check("no-T+1 arm takes F", [x["symbol"] for x in r0["taken_head"]] == ["E", "F"])
    # multi-slot: both D and E taken
    rm = replay(tr, cash0=10000, settle_bdays=0, one_slot=False)
    check("multi-slot arm takes concurrent trades", rm["n_taken"] == 4)
    # paired monthly arithmetic
    pm = paired_monthly({"monthly_return_pct": {"2025-01": 2.0, "2025-02": 1.0, "2025-03": 3.0}},
                        {"monthly_return_pct": {"2025-01": 1.0, "2025-02": 1.0, "2025-03": 1.0}})
    check("paired monthly mean diff", abs(pm["mean_diff_pct"] - 1.0) < 1e-12 and pm["n_months"] == 3)
    # policies on a toy OOF frame
    ts = pd.date_range("2024-01-02 16:00", periods=40, freq="4h", tz="UTC").repeat(30)
    rng = np.random.default_rng(0)
    o = pd.DataFrame({"ts": ts, "pred": rng.normal(0, 0.1, len(ts))})
    p1, t1 = policy_pred(o, "top1_pos")
    sel = pd.Series(np.isfinite(p1)).groupby(o.ts.to_numpy()).sum()
    check("top1 keeps one row per close", int(sel.max()) == 1 and t1 == 0.0)
    p3, _ = policy_pred(o, "top3_pos")
    check("top3 keeps three rows per close", int(pd.Series(np.isfinite(p3)).groupby(o.ts.to_numpy()).sum().max()) == 3)
    pt, tt = policy_pred(o, "tau0.15")
    check("tau policy passes preds through", tt == 0.15 and np.allclose(pt, o.pred))
    pa, _ = policy_pred(o, "adaptive_q995_30d")
    check("adaptive threshold is causal (first close has no prior window)", not np.isfinite(pa[:30]).any())
    # c21d-06 A1: the ATR-neutral target removes each (close, atr quintile) mean, so it is uncorrelated with an ATR-only signal
    nts = pd.date_range("2024-01-02 16:00", periods=20, freq="4h", tz="UTC").repeat(50)
    atr = rng.uniform(0.005, 0.05, len(nts))
    tabn = pd.DataFrame({"ts": nts, "atr_pct": atr, "net_long": -10 * atr + rng.normal(0, 0.01, len(nts))})
    an = atr_neutral_target(tabn)
    gm = an.groupby([tabn.ts, tabn.groupby("ts")["atr_pct"].rank(pct=True).mul(5).clip(upper=4.999).astype(int)]).mean()
    check("ATR-neutral target has zero mean in every (close, quintile) bucket", float(gm.abs().max()) < 1e-12)
    check("ATR-neutral target strips most of an ATR-driven target",
          abs(np.corrcoef(an.dropna(), atr[an.notna().to_numpy()])[0, 1]) < abs(np.corrcoef(tabn.net_long, atr)[0, 1]) / 2)
    # P8-Q5 / Q8 arm comparison and registered arm sets
    bar = {"point_t_min": 2.0}
    mk = lambda months, n, fp: {"book": {"n_taken": n, "monthly_return_pct": months}, "trades": {"folds_positive": fp}}  # noqa: E731
    basem = mk({"2024-01": 0.0, "2024-02": 0.0, "2024-03": 0.0, "2024-04": 0.0}, 40, 3)
    good = mk({"2024-01": 1.0, "2024-02": 1.1, "2024-03": 0.9, "2024-04": 1.0}, 40, 4)
    check("arm clears with +1 %/month, t high, n 40, 4 folds", _arm_vs_base(good, basem, bar)["clears"])
    check("arm refused under n 30", not _arm_vs_base(mk(good["book"]["monthly_return_pct"], 29, 4), basem, bar)["clears"])
    check("arm refused under 3 positive folds", not _arm_vs_base(mk(good["book"]["monthly_return_pct"], 40, 2), basem, bar)["clears"])
    small = mk({"2024-01": 0.2, "2024-02": 0.21, "2024-03": 0.19, "2024-04": 0.2}, 40, 4)
    check("arm refused below +0.25 %/month materiality", not _arm_vs_base(small, basem, bar)["clears"])
    check("registered horizon arms: 48, 72 bars and daily at 24", HORIZON_ARMS == {"h48": {"hold": 48, "daily": False},
          "h72": {"hold": 72, "daily": False}, "daily_h24": {"hold": 24, "daily": True}})
    import ml_entry_equity as M
    check("built feature families exist in the equity module", all(f in M.FAMILY_FEATURES for f in FEATURE_FAMILIES + ["noise9"]))
    # P8-Q4-h2h grading (s 5.2 / 5.4)
    mo = lambda v, n, dd: {"n_taken": n, "max_drawdown_usd": dd, "n_candidates": n,  # noqa: E731
                           "monthly_return_pct": {f"2024-{m:02d}": v + (0.05 if m % 2 else -0.05) * (1 + v) for m in range(1, 13)}}
    b1 = holdout_lock_bar = {"point_t_min": 2.0}
    inc, ch, cb = mo(0.0, 40, 10.0), mo(1.0, 40, 12.0), mo(0.5, 40, 11.0)
    check("h2h: +1 %/month, n 40, dd 1.2x clears", h2h_grade(ch, inc, b1)["clears"])
    check("h2h: drawdown above 1.5x refused", not h2h_grade(mo(1.0, 40, 16.0), inc, b1)["clears"])
    check("h2h: under +0.25 %/month refused", not h2h_grade(mo(0.2, 40, 10.0), inc, b1)["clears"])
    check("h2h: n_taken 29 refused", not h2h_grade(mo(1.0, 29, 10.0), inc, b1)["clears"])
    hv = h2h_verdict({"incumbent": inc, "X": ch, "combined": cb}, ["X"], holdout_lock_bar)
    check("h2h: a challenger that beats the incumbent AND the combined book REPLACES", hv["verdict"] == "pass" and hv["replace"] == ["X"])
    hv = h2h_verdict({"incumbent": inc, "X": mo(0.1, 40, 10.0), "combined": cb}, ["X"], holdout_lock_bar)
    check("h2h: only the combined book clears -> JOIN", hv["verdict"] == "pass" and hv["join"] and not hv["replace"])
    hv = h2h_verdict({"incumbent": mo(0.0, 20, 10.0), "X": ch, "combined": cb}, ["X"], holdout_lock_bar)
    check("h2h: thin incumbent -> indeterminate", hv["verdict"] == "indeterminate")
    tA = [{"entry_time": T("2024-01-01"), "x": 1}, {"entry_time": T("2024-06-01"), "x": 2}]
    tB = [{"entry_time": T("2024-03-01"), "x": 3}, {"entry_time": T("2024-09-01"), "x": 4}]
    lo, hi = common_window(tA, tB)
    check("h2h: common window is [latest start, earliest end] (UTC, naive inputs ok)",
          (lo, hi) == (T("2024-03-01", tz="UTC"), T("2024-06-01", tz="UTC")) and len(clip(tA, lo, hi)) == 1)
    lo2, _ = common_window([{"entry_time": T("2024-03-01 00:00Z")}], tA)
    check("h2h: tz-aware and naive lists mix without error", lo2 == T("2024-03-01", tz="UTC"))
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "t.jsonl"
        fp.write_text(json.dumps({"symbol": "Q", "entry_time": "2024-01-02T15:30:00Z", "exit_time": "2024-01-03T20:00:00Z",
                                  "entry": 10, "sl": 9.5, "net_r": 0.5, "score": 0.3}) + "\n")
        lt = load_trades(fp)
        # provenance: picks -- the round-tripped regressed net R (ml_pool_scoring.picks order key), not a probability
        check("h2h: --trades-from jsonl loads in replay() shape", len(lt) == 1 and lt[0]["score"] == 0.3 and replay(lt)["n_taken"] == 1)
    # frozen-book (RQ-20261119-a10d-04): per-arm and unit verdicts, registered
    b5 = {"n_tries": 5, "point_t_min": 1.1926, "ci_z": 2.5723}
    check("frozen arm: thin is indeterminate", frozen_arm_verdict({"n_taken": 20, "taken_mean_net_r": 1.0, "taken_se_net_r": 0.1}, b5)[0] == "indeterminate")
    check("frozen arm: mean 0.30 se 0.10 passes at N=5", frozen_arm_verdict({"n_taken": 60, "taken_mean_net_r": 0.30, "taken_se_net_r": 0.10}, b5)[0] == "pass")
    check("frozen arm: mean 0.10 se 0.10 is indeterminate", frozen_arm_verdict({"n_taken": 60, "taken_mean_net_r": 0.10, "taken_se_net_r": 0.10}, b5)[0] == "indeterminate")
    check("frozen arm: mean -0.30 se 0.10 fails", frozen_arm_verdict({"n_taken": 60, "taken_mean_net_r": -0.30, "taken_se_net_r": 0.10}, b5)[0] == "fail")
    check("frozen unit: all pass", frozen_unit_verdict({"a": "pass", "b": "pass"}, True)[0] == "pass")
    check("frozen unit: mixed is indeterminate", frozen_unit_verdict({"a": "pass", "b": "fail"}, True)[0] == "indeterminate")
    check("frozen unit: all fail", frozen_unit_verdict({"a": "fail", "b": "fail"}, True)[0] == "fail")
    check("frozen unit: no reproduction is indeterminate", frozen_unit_verdict({"a": "pass"}, False)[0] == "indeterminate")
    # slot policy (RQ-20261119-a10d-09)
    def tr_(sym, e, x, net, score=0.1, entry=10.0, sl=9.0):
        return {"symbol": sym, "entry_time": e, "exit_time": x, "entry": entry, "sl": sl, "net_r": net, "direction": "long", "score": score}
    ov = [tr_("A", "2025-01-06 15:00Z", "2025-01-10 15:00Z", 1.0), tr_("B", "2025-01-07 15:00Z", "2025-01-09 15:00Z", 1.0),
          tr_("C", "2025-01-08 15:00Z", "2025-01-09 15:00Z", 1.0)]
    check("slots: one slot takes 1 of 3 overlapping", replay(ov, 10000.0)["n_taken"] == 1)
    b2 = replay_slots(ov, 10000.0, 2)
    check("slots: k=2 takes 2 of 3 overlapping and refuses the third as slot_busy",
          b2["n_taken"] == 2 and b2["refused"].get("slot_busy") == 1)
    check("slots: k=3 takes all 3", replay_slots(ov, 10000.0, 3)["n_taken"] == 3)
    capped = replay_slots([tr_("A", "2025-01-06 15:00Z", "2025-01-10 15:00Z", 1.0, entry=100.0, sl=99.9)], 1000.0, 2)
    check("slots: a position is capped at wall x equity / k whole shares (1000 x 0.9 / 2 / 100 = 4)", capped["taken_head"][0]["qty"] == 4)
    # cash 600, k 2: each slot caps at floor(0.9 x 600 / 2 / 250) = 1 share; A and B commit 500, so after A exits on day 2 its
    # 250 is unsettled until day 3 and free cash is 100 < 250 -> C refused unsettled_t1 (the wall would allow 1 share)
    t1 = [tr_("A", "2025-01-06 15:00Z", "2025-01-07 15:00Z", 0.0, entry=250.0, sl=249.0),
          tr_("B", "2025-01-06 16:00Z", "2025-01-08 15:00Z", 0.0, entry=250.0, sl=249.0),
          tr_("C", "2025-01-07 16:00Z", "2025-01-09 15:00Z", 0.0, entry=250.0, sl=249.0)]
    bt = replay_slots(t1, 600.0, 2)
    check("slots: proceeds of a same-day exit are unsettled until T+1 (C refused while A's cash settles)",
          bt["refused"].get("unsettled_t1") == 1 and bt["n_taken"] == 2)
    gate_in = [tr_(f"S{i}", f"2025-01-{6 + i:02d} 15:00Z", f"2025-01-{6 + i:02d} 18:00Z", 0.0, score=float(i)) for i in range(6)]
    gate_in.append(tr_("LOW", "2025-01-13 15:00Z", "2025-01-13 18:00Z", 0.0, score=0.5))
    gate_in.append(tr_("HIGH", "2025-01-14 15:00Z", "2025-01-14 18:00Z", 0.0, score=9.0))
    kept = {t["symbol"] for t in score_gate_p50_30d(gate_in)}
    check("slots: the score gate drops a weak signal and keeps a strong one once 5 prior-30d candidates exist",
          "LOW" not in kept and "HIGH" in kept and "S0" in kept)
    # selection null: the one slot always takes the FIRST of each overlapping pair; make those the losers -> selection
    pairs = []
    for i in range(40):
        d = pd.Timestamp("2025-02-03") + pd.Timedelta(days=3 * i)
        pairs.append(tr_(f"F{i}", str(d + pd.Timedelta(hours=15)), str(d + pd.Timedelta(days=1, hours=15)), -1.0))
        pairs.append(tr_(f"L{i}", str(d + pd.Timedelta(hours=16)), str(d + pd.Timedelta(days=1, hours=14)), 1.0))
    ns = selection_null(pairs, 1e6, draws=200, settle_bdays=0)
    check("slots: the null flags a book that systematically takes the losers (p_low < 0.01)", ns["p_low"] is not None and ns["p_low"] < 0.01)
    rng_ = np.random.default_rng(1)
    for t_ in pairs:
        t_["net_r"] = float(rng_.choice([-1.0, 1.0]))
    nn = selection_null(pairs, 1e6, draws=200, settle_bdays=0)
    check("slots: the null does not flag a book whose picks are unrelated to outcome (p_low >= 0.05)", nn["p_low"] >= 0.05)
    check("slots: selection verdict needs every cash level under alpha",
          selection_verdict({"a": {"p_low": 0.001}, "b": {"p_low": 0.001}}, 0.004)[0] == "selection"
          and selection_verdict({"a": {"p_low": 0.001}, "b": {"p_low": 0.2}}, 0.004)[0] == "unresolved"
          and selection_verdict({"a": {"p_low": 0.3}, "b": {"p_low": 0.2}}, 0.004)[0] == "noise")
    allc = {c: "indeterminate" for c in ("cash_250", "cash_1000", "cash_5000")}
    av = {p_: dict(allc) for p_ in SLOT_POLICIES}
    av["slots_3"] = {c: "pass" for c in allc}
    check("slots: unit PASS when one challenger passes at every cash level", slot_unit_verdict(av, True)[0] == "pass")
    check("slots: unit INDETERMINATE without reproduction", slot_unit_verdict(av, False)[0] == "indeterminate")
    av2 = {p_: {c: "fail" for c in allc} for p_ in SLOT_POLICIES}
    check("slots: unit FAIL when every challenger fails everywhere", slot_unit_verdict(av2, True)[0] == "fail")
    av2["slots_2"]["cash_250"] = "indeterminate"
    check("slots: one non-fail cell keeps the unit INDETERMINATE", slot_unit_verdict(av2, True)[0] == "indeterminate")
    import holdout_lock as HL
    bb = HL.bar_for(5)
    check("registered N=5 bar matches holdout_lock", bb["point_t_min"] == b5["point_t_min"] and bb["ci_z"] == b5["ci_z"])
    print(f"{len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("foxhound", "legs", "h2h", "frozen-book", "slot-book"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--unit", required=True)
        p.add_argument("--where", default="local")
        p.add_argument("--rule-id", required=True)
        p.add_argument("--registered-at", required=True)
        if name == "foxhound":
            p.add_argument("--cache", required=True)
            p.add_argument("--section", required=True, choices=["book", "calib", "label", "neutral", "features", "horizon"])
            p.add_argument("--families", default="", help="features: comma list of ml_entry_equity.FAMILY_FEATURES keys (default all built)")
            p.add_argument("--horizon-arms", default="", help="horizon: comma list of HORIZON_ARMS keys (default all)")
        elif name == "h2h":
            p.add_argument("--cache", default=None, help="Foxhound-4 refit cache (needed unless --trades-from)")
            p.add_argument("--trades-from", default=None, help="Foxhound-4 trades (.jsonl / .json) from an earlier h2h run")
            p.add_argument("--strategy", action="append", required=True, help="challenger leg (repeatable)")
            p.add_argument("--book-leg", default="tqqq_trend_long_1d", help="the current book's other leg, in the combined replay")
            p.add_argument("--days", type=int, default=1460)
        elif name in ("frozen-book", "slot-book"):
            p.add_argument("--cache", required=True)
            p.add_argument("--artifact", default=FROZEN_ARTIFACT)
            p.add_argument("--start", default="2025-07-15")
            p.add_argument("--end", default="2026-10-31")
            p.add_argument("--expect-n", dest="expect_n", default="207")
            p.add_argument("--expect-mean", dest="expect_mean", default="0.4922070639835765")
        else:
            p.add_argument("--strategy", action="append", required=True)
            p.add_argument("--days", type=int, default=700)
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.cmd:
        ap.error("a subcommand or --self-test is required")
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "h2h" and not (a.trades_from or a.cache):
        ap.error("h2h needs --cache (refit Foxhound-4) or --trades-from")
    r = (main_foxhound(a) if a.cmd == "foxhound" else main_h2h(a) if a.cmd == "h2h"
         else main_frozen_book(a) if a.cmd == "frozen-book" else main_slot_book(a) if a.cmd == "slot-book" else main_legs(a))
    row = {"schema_version": 1, "schema": SCHEMA, "research_unit": a.unit, "read_state": "measured", "verdict": r["verdict"],
           "n": r.get("n"), "note": r["note"], "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "population": r.get("population"), "measurement": {**r, "runtime_s": round(time.time() - t0, 1)},
           "produced_by": {"tool": f"python3 scripts/research/alpaca_live_book.py {a.cmd}", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"{a.cmd.upper()} {row['verdict']}: {row['note']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
