#!/usr/bin/env python3
# wiring: research/queue units of programme P8 (research/programmes/08-alpaca-live-book.yaml; lane ALPACA-LIVE-BOOK-PLAN, 2026-11-11)
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


def dev_oof(tab: pd.DataFrame, target: str = "net_long", log=print) -> pd.DataFrame:
    """Foxhound-4's recipe on the dev walk-forward: config B features, 5-seed pinned ensemble, purge, folds DEV_FOLDS.
    Rows <= TRAIN_END only; returns the out-of-fold rows with `pred` and `fold`, session-gated as the harness does."""
    import ml_entry_equity as M
    te = pd.Timestamp(M.TRAIN_END, tz="UTC") + pd.Timedelta(days=1)
    dev = tab[tab.ts < te].dropna(subset=["net_long", target])
    feats = M.CONFIGS["B"]["features"]
    bounds = [pd.Timestamp(x, tz="UTC") for x in M.DEV_FOLDS] + [te]
    oof = []
    for k in range(len(M.DEV_FOLDS)):
        tr = M.purge(dev[dev.ts < bounds[k]], bounds[k]).dropna(subset=feats)
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


def main_foxhound(a) -> Dict[str, Any]:
    import ml_entry_equity as M
    import ml_entry_alpaca_score as S
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip
    sizer = _live_sizer_constants()
    slip, _ = resolve_cost_policy("SPY")
    fee = resolve_fee_bps_roundtrip("SPY")
    pool, prep, bars, client = M._pool_and_bars(a, M.TRAIN_END)          # bars END at TRAIN_END: the confirm window is never fetched
    tab = M.build_table(bars, pool, slip, fee, struct=M.STRUCT_SPEC)
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
    else:
        r = section_label(tab, o, sizer)
    r.update({"sizer": sizer, "cash0_source": CASH0_SOURCE, "costs": {"slippage_bps": slip, "fee_bps": fee, "regulatory_bps": S.REGULATORY_BPS},
              "n_pool": len(pool), "pool": {k: v for k, v in prep.items() if k != "excluded"}, "train_end": M.TRAIN_END,
              "structure_exit": M.STRUCT_SPEC, "ensemble_seeds": ENS_SEEDS, "alpaca_calls": client.calls,
              "population": f"DEV walk-forward OOF restricted-LONG decisions of the Foxhound-4 recipe on the {len(pool)}-ETF pool, "
                            f"folds {M.DEV_FOLDS} to {M.TRAIN_END}; no confirming-window row loaded"})
    return r


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
    return {"verdict": v, "note": why, "per_leg": per, "combined_one_slot": combined, "harness_runs": runs, "sizer": sizer,
            "cash0_source": CASH0_SOURCE, "days": a.days,
            "population": f"Stage-0 trade lists of {len(a.strategy)} rostered equity legs (build_strategy_evidence, last {a.days} days, "
                          f"config-exact harness, net of its cost stack) replayed through the alpaca_live cash book"}


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
    print(f"{len(fails)} failure(s)")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("foxhound", "legs"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--unit", required=True)
        p.add_argument("--where", default="local")
        p.add_argument("--rule-id", required=True)
        p.add_argument("--registered-at", required=True)
        if name == "foxhound":
            p.add_argument("--cache", required=True)
            p.add_argument("--section", required=True, choices=["book", "calib", "label"])
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
    r = main_foxhound(a) if a.cmd == "foxhound" else main_legs(a)
    row = {"schema_version": 1, "schema": SCHEMA, "research_unit": a.unit, "read_state": "measured", "verdict": r["verdict"],
           "note": r["note"], "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
           "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
           "population": r.get("population"), "measurement": {**r, "runtime_s": round(time.time() - t0, 1)},
           "produced_by": {"tool": f"python3 scripts/research/alpaca_live_book.py {a.cmd}", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"{a.cmd.upper()} {row['verdict']}: {row['note']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
