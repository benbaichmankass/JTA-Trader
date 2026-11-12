#!/usr/bin/env python3
"""Tradeify FUTURES fit -- Stage 0, prop survival and an ML filter on session-flat CME micros.

Lane TRADEIFY-FUTURES-FRONTIER (2026-11-12). The rules live in the units, registered before any run:
  RQ-20261112-09d2-01  --stage stage0    ORB cells {MES,MNQ,MGC} x {OR15,OR30}, flat by 16:40 ET, Tradeify per-contract costs
  RQ-20261112-09d2-02  --stage survival  Tradeify Growth / Select / Lightning 50K, EOD-trailing DD enforced intraday
  RQ-20261112-09d2-03  --stage ml        gbdt meta-label filter over the same ORB candidates, frozen 2025-26 holdout

Account facts (docs/research/tradeify-futures-frontier-2026-11-12.md section 1, Tradeify help-center pages fetched 2026-11-12):
flat by 16:45 ET; EOD trailing drawdown enforced in real time on net liquidation; MES/MNQ $1.82 and MGC $2.12 round turn
all-in; 50K: DD $2,000, target $3,000, max 4 minis = 40 micros.

DATA: Dukascopy 5m bid candles, PROXIES, not the futures: E_SANDP_500 CFD for MES, E_NQ_100 CFD for MNQ, XAU/USD spot for
MGC (scripts/ops/dukascopy_instruments.py adjudication: "CFD vs future", "spot vs future"). R-denominated results are
level-free; the basis, roll and futures-only microstructure are NOT modelled. A PASS here is a proxy Stage 0 and the
units say what confirms it on the real contract.

Offline research only: imports nothing from src/, places no order, changes no config.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
ET = ZoneInfo("America/New_York")

# instrument -> (dukascopy instrument, $ per point per micro, tick size, round-turn all-in commission $)
INSTR = {
    "MES": ("INSTRUMENT_IDX_AMERICA_E_SANDP_500", 5.0, 0.25, 1.82),
    "MNQ": ("INSTRUMENT_IDX_AMERICA_E_NQ_100", 2.0, 0.25, 1.82),
    "MGC": ("INSTRUMENT_FX_METALS_XAU_USD", 10.0, 0.10, 2.12),
}
GROUP = {"MES": "equity_index", "MNQ": "equity_index", "MGC": "metals"}
OR_MINUTES = (15, 30)
RTH_OPEN = time(9, 30)
ENTRY_CUTOFF = time(15, 0)       # no new entry at or after 15:00 ET
FLAT_AT = time(16, 40)           # forced flat 5 minutes before Tradeify's 16:45 ET cutoff
TP_R = 2.0
MIN_STOP_TICKS = 4
DISC = ("2019-01-01", "2024-12-31")
HOLD = ("2025-01-01", "2026-10-31")
N_FLOOR = 100
HOLD_N_FLOOR = 30
FOLD_MAJ = 4
Z_BONF = 2.638                   # two-sided alpha 0.05 / 6 cells


# ------------------------------------------------------------------ data
def load_bars(sym: str, corpus: Path, start: str, end: str) -> pd.DataFrame:
    """Read cached yearly CSVs from ``corpus``; fetch any missing year from Dukascopy (pinned dukascopy-python==4.0.1)."""
    corpus.mkdir(parents=True, exist_ok=True)
    inst = INSTR[sym][0]
    y0, y1 = int(start[:4]), int(end[:4])
    frames = []
    for y in range(y0, y1 + 1):
        p = corpus / f"{sym}_{y}.csv"
        if not p.exists():
            sys.path.insert(0, str(REPO / "scripts" / "ops"))
            from fetch_dukascopy_ohlcv import fetch
            s = datetime(y, 1, 1, tzinfo=timezone.utc)
            e = min(datetime(y + 1, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc))
            df = fetch(inst, s, e, "5m")
            df.to_csv(p, index=False)
        frames.append(pd.read_csv(p))
    df = pd.concat(frames, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    df["et"] = df["timestamp"].dt.tz_convert(ET)
    df["d"] = df["et"].dt.date
    df["t"] = df["et"].dt.time
    lo, hi = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    return df[(df["d"] >= lo) & (df["d"] <= hi)].reset_index(drop=True)


def load_ibkr_percontract(path: Path) -> tuple[pd.DataFrame, dict]:
    """Real CME bars from IB's free history (FUT-CME-INTRADAY-HIST): a per-contract jsonl written by
    ``pull-ibkr-history per_contract: 1`` (``market_raw_percontract/<SYM>/<tf>/<ver>/data.jsonl``; each bar
    carries ``contract`` = expiry YYYYMMDD and cross-contract overlaps are kept).

    ROLL ON VOLUME, PER SESSION: for each ET calendar date, take the contract with the largest volume that date,
    never stepping back to an older expiry once rolled. The splice is at a session boundary, so no intraday bar
    mixes contracts. No back-adjustment: every trade opens and closes inside one session, the result is in R
    (level-free) and the ATR feature uses day ranges, so a constant level shift changes nothing.
    Returns (bars, provenance) where provenance states the span actually served and the roll calendar.
    """
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit(f"no bars in {path}")
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["ts"], utc=True)
    df["et"] = df["timestamp"].dt.tz_convert(ET)
    df["d"] = df["et"].dt.date
    vol = df.groupby(["d", "contract"])["volume"].sum().reset_index()
    chosen: dict = {}
    floor = ""
    for d, g in vol.groupby("d"):
        g = g[g["contract"] >= floor]
        if g.empty:
            continue
        c = str(g.sort_values(["volume", "contract"], ascending=[False, True]).iloc[0]["contract"])
        chosen[d] = c
        floor = c
    df = df[df.apply(lambda r: chosen.get(r["d"]) == r["contract"], axis=1)]
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    df["t"] = df["et"].dt.time
    rolls, prev = [], None
    for d in sorted(chosen):
        if chosen[d] != prev:
            rolls.append({"from_session": str(d), "contract": chosen[d]})
            prev = chosen[d]
    per_contract = {c: {"first_ts": str(g["timestamp"].min()), "last_ts": str(g["timestamp"].max()), "bars": int(len(g))}
                    for c, g in pd.DataFrame(rows).assign(timestamp=lambda x: pd.to_datetime(x["ts"], utc=True))
                    .groupby("contract")}
    prov = {"path": str(path), "bars_raw": len(rows), "bars_continuous": int(len(df)),
            "first_ts": str(df["timestamp"].min()), "last_ts": str(df["timestamp"].max()),
            "contracts_served": per_contract, "roll_calendar": rolls,
            "roll_rule": "per ET session, max-volume contract, monotonic; no back-adjustment"}
    return df[["timestamp", "open", "high", "low", "close", "volume", "et", "d", "t"]], prov


# ------------------------------------------------------------------ ORB engine
@dataclass
class Trade:
    sym: str
    arm: str
    day: str
    entry_time: str
    exit_time: str
    direction: int
    entry: float
    stop: float
    tp: float
    exit: float
    exit_reason: str
    risk_pts: float
    gross_r: float
    cost_r: float
    net_r: float
    mae_r: float
    risk_usd_1c: float           # $ at risk for ONE micro incl. costs: stop distance + commission + slippage
    feats: dict


def _mins(t: time) -> int:
    """Minutes after midnight of a wall-clock time."""
    return t.hour * 60 + t.minute


def orb_trades(df: pd.DataFrame, sym: str, or_min: int) -> list[Trade]:
    _, mult, tick, comm = INSTR[sym]
    out: list[Trade] = []
    m_end = _mins(RTH_OPEN) + or_min
    or_end = time(m_end // 60, m_end % 60)
    days = sorted(df["d"].unique())
    by_day = {d: g for d, g in df.groupby("d")}
    prev_close = None
    atr_hist: list[float] = []
    for d in days:
        g = by_day[d]
        rth = g[(g["t"] >= RTH_OPEN) & (g["t"] < FLAT_AT)]
        if len(rth) < 60:
            if len(rth):
                prev_close = float(rth["close"].iloc[-1])
            continue
        rng = rth[rth["t"] < or_end]
        if len(rng) < or_min // 5:
            continue
        hi, lo = float(rng["high"].max()), float(rng["low"].min())
        day_range = float(rth["high"].max() - rth["low"].min())
        atr20 = st.fmean(atr_hist[-20:]) if len(atr_hist) >= 20 else None
        after = rth[rth["t"] >= or_end].reset_index(drop=True)
        trade = None
        for i in range(len(after) - 1):
            bar = after.iloc[i]
            if bar["t"] >= ENTRY_CUTOFF:
                break
            c = float(bar["close"])
            direction = 1 if c > hi else (-1 if c < lo else 0)
            if not direction:
                continue
            nxt = after.iloc[i + 1]
            entry = float(nxt["open"])
            stop = lo if direction == 1 else hi
            risk = (entry - stop) * direction
            if risk < MIN_STOP_TICKS * tick:
                break                       # one decision per day: a degenerate stop skips the day
            tp = entry + direction * TP_R * risk
            mae = 0.0
            exit_px, reason, exit_t = None, None, None
            for j in range(i + 1, len(after)):
                b = after.iloc[j]
                if b["t"] >= FLAT_AT:
                    break
                lo_b, hi_b = float(b["low"]), float(b["high"])
                adverse = (entry - lo_b) if direction == 1 else (hi_b - entry)
                mae = max(mae, adverse)
                hit_stop = (lo_b <= stop) if direction == 1 else (hi_b >= stop)
                hit_tp = (hi_b >= tp) if direction == 1 else (lo_b <= tp)
                if hit_stop:                # stop wins a tie (conservative)
                    exit_px, reason, exit_t = stop, "stop", b["et"]
                    break
                if hit_tp:
                    exit_px, reason, exit_t = tp, "take_profit", b["et"]
                    break
            if exit_px is None:             # forced flat: last bar before 16:40 closes the trade
                last = after[after["t"] < FLAT_AT].iloc[-1]
                exit_px, reason, exit_t = float(last["close"]), "session_flat", last["et"]
            slip_ticks = 1 + (0 if reason == "take_profit" else 1)
            cost_usd = comm + slip_ticks * tick * mult
            risk_usd = risk * mult
            gross = (exit_px - entry) * direction / risk
            cost_r = cost_usd / risk_usd
            feats = {
                "or_width_atr": (hi - lo) / atr20 if atr20 else None,
                "gap_atr": ((float(rth["open"].iloc[0]) - prev_close) / atr20) if (atr20 and prev_close) else None,
                "breakout_min": float(_mins(bar["t"]) - _mins(RTH_OPEN)),
                "dow": pd.Timestamp(d).dayofweek,
                "dir": direction,
                "atr_pct": (atr20 / entry) if atr20 else None,
                "inst": list(INSTR).index(sym),
                "or_min": or_min,
            }
            trade = Trade(sym, f"OR{or_min}", str(d), str(nxt["et"]), str(exit_t), direction, entry, stop, tp, exit_px,
                          reason, risk, round(gross, 5), round(cost_r, 5), round(gross - cost_r, 5),
                          round(mae / risk, 5), round(risk_usd + cost_usd, 2), feats)
            break
        if trade:
            out.append(trade)
        prev_close = float(rth["close"].iloc[-1])
        atr_hist.append(day_range)
    return out


# ------------------------------------------------------------------ Stage 0
def ci(xs: list[float], z: float) -> dict:
    n = len(xs)
    if n < 2:
        return {"n": n, "mean": None, "lo": None}
    m, se = st.fmean(xs), st.stdev(xs) / math.sqrt(n)
    return {"n": n, "mean": round(m, 5), "se": round(se, 5), "lo": round(m - z * se, 5), "hi": round(m + z * se, 5), "z": z}


def grade_cell(trades: list[Trade]) -> dict:
    disc = [t for t in trades if DISC[0] <= t.day <= DISC[1]]
    hold = [t for t in trades if HOLD[0] <= t.day <= HOLD[1]]
    folds = {}
    for t in disc:
        folds.setdefault(t.day[:4], []).append(t.net_r)
    fold_net = {y: round(sum(v), 3) for y, v in sorted(folds.items())}
    n_pos = sum(1 for v in fold_net.values() if v > 0)
    dn = [t.net_r for t in disc]
    hn = [t.net_r for t in hold]
    c = ci(dn, Z_BONF)
    out = {
        "n_disc": len(dn), "net_r_disc": round(sum(dn), 3), "folds": fold_net, "folds_positive": n_pos,
        "edge_ci_disc": c, "n_hold": len(hn), "net_r_hold": round(sum(hn), 3),
        "mean_r_hold": round(st.fmean(hn), 5) if hn else None,
        "gross_r_disc": round(sum(t.gross_r for t in disc), 3), "cost_r_disc": round(sum(t.cost_r for t in disc), 3),
        "median_risk_usd_1c": round(st.median([t.risk_usd_1c for t in trades]), 2) if trades else None,
        "by_reason": {r: sum(1 for t in trades if t.exit_reason == r) for r in ("stop", "take_profit", "session_flat")},
    }
    if len(dn) < N_FLOOR:
        v = "indeterminate"
    elif (sum(dn) > 0 and n_pos >= FOLD_MAJ and c["lo"] is not None and c["lo"] > 0
          and len(hn) >= HOLD_N_FLOOR and sum(hn) > 0):
        v = "pass"
    elif len(hn) < HOLD_N_FLOOR and sum(dn) > 0 and n_pos >= FOLD_MAJ and c["lo"] > 0:
        v = "indeterminate"
    else:
        v = "fail"
    out["verdict"] = v
    return out


def grade_cell_sessions(trades: list[Trade], sessions: list[str], disc_frac: float = 0.75, n_folds: int = 6) -> dict:
    """RULE-RQ-20261112-09d2-05 window: discovery = the first 75% of the RTH sessions served, in 6 equal folds
    (by session count); holdout = the last 25%. Clauses as grade_cell (N_FLOOR, FOLD_MAJ, Z_BONF, holdout floor)."""
    sessions = sorted(sessions)
    cut = int(len(sessions) * disc_frac)
    disc_s, hold_s = sessions[:cut], sessions[cut:]
    fold_of = {d: min(i * n_folds // max(len(disc_s), 1), n_folds - 1) for i, d in enumerate(disc_s)}
    disc = [t for t in trades if t.day in fold_of]
    hold = [t for t in trades if hold_s and t.day >= hold_s[0]]
    folds: dict = {f"F{k + 1}": [] for k in range(n_folds)}
    for t in disc:
        folds[f"F{fold_of[t.day] + 1}"].append(t.net_r)
    fold_net = {k: round(sum(v), 3) for k, v in folds.items()}
    n_pos = sum(1 for v in fold_net.values() if v > 0)
    dn, hn = [t.net_r for t in disc], [t.net_r for t in hold]
    c = ci(dn, Z_BONF)
    out = {
        "window": {"sessions": len(sessions), "discovery": [disc_s[0], disc_s[-1]] if disc_s else None,
                   "holdout": [hold_s[0], hold_s[-1]] if hold_s else None,
                   "fold_bounds": {f"F{k + 1}": [min(d for d in disc_s if fold_of[d] == k), max(d for d in disc_s if fold_of[d] == k)]
                                   for k in range(n_folds) if any(fold_of[d] == k for d in disc_s)}},
        "n_disc": len(dn), "net_r_disc": round(sum(dn), 3), "folds": fold_net, "folds_positive": n_pos,
        "edge_ci_disc": c, "n_hold": len(hn), "net_r_hold": round(sum(hn), 3),
        "mean_r_hold": round(st.fmean(hn), 5) if hn else None,
        "gross_r_disc": round(sum(t.gross_r for t in disc), 3), "cost_r_disc": round(sum(t.cost_r for t in disc), 3),
        "median_risk_usd_1c": round(st.median([t.risk_usd_1c for t in trades]), 2) if trades else None,
        "by_reason": {r: sum(1 for t in trades if t.exit_reason == r) for r in ("stop", "take_profit", "session_flat")},
    }
    if len(dn) < N_FLOOR:
        v = "indeterminate"
    elif sum(dn) > 0 and n_pos >= FOLD_MAJ and c["lo"] is not None and c["lo"] > 0 and len(hn) >= HOLD_N_FLOOR and sum(hn) > 0:
        v = "pass"
    else:
        v = "fail"
    out["verdict"] = v
    return out


# ------------------------------------------------------------------ survival
PLANS = {
    # fee = list price 2026-11-12 (promotions ignored); dd EOD trailing, enforced intraday; dll soft (pause for the day)
    "growth_50k": {"fee": 145.0, "dd": 2000.0, "dll": 1250.0, "target": 3000.0, "min_days": 1, "eval_consistency": None,
                   "funded": "growth"},
    "select_50k": {"fee": 165.0, "dd": 2000.0, "dll": None, "target": 3000.0, "min_days": 3, "eval_consistency": 0.40,
                   "funded": "select_flex"},
    "lightning_50k": {"fee": 492.0, "dd": 2000.0, "dll": 1250.0, "target": None, "min_days": 0, "eval_consistency": None,
                      "funded": "lightning"},
}
START = 50000.0
MAX_MICROS = 40
FUNDED_DAYS = 250
RISK_GRID = (100.0, 200.0, 300.0)
PRIMARY_RISK = 200.0
SEEDS = (1, 2, 3, 4, 5)
PATHS = 2000


def day_ledgers(trades: list[Trade], all_days: list[str]) -> list[list[Trade]]:
    by = {}
    for t in trades:
        by.setdefault(t.day, []).append(t)
    return [sorted(by.get(d, []), key=lambda t: t.entry_time) for d in all_days]


def run_path(days: list[list[Trade]], plan: dict, risk_usd: float, rng: np.random.Generator) -> dict:
    """One account life: evaluation (if any) then funded, on days drawn i.i.d. from the cell's day pool."""
    bal = START
    peak_eod = START
    floor = START - plan["dd"]
    locked = False
    phase = "eval" if plan["target"] else "funded"
    eval_days, eval_day_pnls = 0, []
    payouts, since_payout, qual_days, n_payout = [], [], 0, 0
    funded_days = 0
    while True:
        day = days[rng.integers(len(days))]
        day_pnl = 0.0
        open_by_group: dict[str, int] = {}
        for t in day:
            if plan["dll"] is not None and day_pnl <= -plan["dll"]:
                break                                   # soft DLL: paused for the rest of the session
            n = min(MAX_MICROS, int(risk_usd // t.risk_usd_1c))
            if n < 1:
                continue
            g = GROUP[t.sym]
            if open_by_group.get(g, 0) == -t.direction:
                continue                                # opposite direction in one product group is prohibited
            usd_per_r = t.risk_pts * INSTR[t.sym][1] * n
            worst = bal - t.mae_r * usd_per_r
            if worst <= floor:                          # EOD-trailing DD is enforced intraday on net liquidation
                return {"breach": True, "phase": phase, "payouts": payouts, "eval_days": eval_days}
            pnl = t.net_r * usd_per_r
            bal += pnl
            day_pnl += pnl
            open_by_group[g] = t.direction
            if bal <= floor:
                return {"breach": True, "phase": phase, "payouts": payouts, "eval_days": eval_days}
        # end of day: trailing floor updates on the EOD balance
        if phase == "funded" and not locked and bal >= START + plan["dd"] + 100:
            locked, floor = True, START + 100
        if not locked:
            peak_eod = max(peak_eod, bal)
            floor = max(floor, peak_eod - plan["dd"])
        if phase == "eval":
            eval_days += 1
            if day:
                eval_day_pnls.append(day_pnl)
            prof = bal - START
            ok_cons = True
            if plan["eval_consistency"] and prof > 0:
                ok_cons = max(eval_day_pnls) / prof <= plan["eval_consistency"]
            if prof >= plan["target"] and eval_days >= plan["min_days"] and ok_cons:
                phase = "funded"                        # funded account restarts at the starting balance
                bal, peak_eod, floor, locked = START, START, START - plan["dd"], False
            elif eval_days > 500:
                return {"breach": False, "phase": "eval_timeout", "payouts": payouts, "eval_days": eval_days}
            continue
        funded_days += 1
        if day:
            since_payout.append(day_pnl)
        kind = plan["funded"]
        prof = sum(since_payout)
        if kind in ("growth", "select_flex"):
            if day_pnl >= 150:
                qual_days += 1
            cons_ok = (kind == "select_flex") or (prof > 0 and max(since_payout) / prof <= 0.35)
            if qual_days >= 5 and prof > 0 and cons_ok:
                if kind == "growth":
                    cap = [1500, 2000, 2500][min(n_payout, 2)] if n_payout < 3 else 3000
                    amt = min(cap, bal - 53000.0)
                    ok = amt >= 500
                else:
                    amt = min(2500.0, 0.5 * (bal - START))
                    ok = amt >= 250
                if ok:
                    payouts.append(amt)
                    bal -= amt
                    n_payout += 1
                    since_payout, qual_days = [], 0
                    locked, floor = True, START + 100   # a payout request locks the floor
        else:  # lightning
            goal = 3000.0 if n_payout == 0 else 2000.0
            cons = [0.20, 0.25, 0.30][min(n_payout, 2)]
            if prof >= goal and max(since_payout) / prof <= cons:
                cap = 2000.0 if n_payout < 3 else 2500.0
                amt = min(cap, prof)
                if amt >= 1000:
                    payouts.append(amt)
                    bal -= amt
                    n_payout += 1
                    since_payout = []
                    locked, floor = True, START + 100
        if funded_days >= FUNDED_DAYS:
            return {"breach": False, "phase": "funded_horizon", "payouts": payouts, "eval_days": eval_days}


def survival(trades: list[Trade], all_days: list[str], plan_name: str, risk_usd: float, demean: bool = False) -> dict:
    tr = trades
    if demean and trades:
        mu = st.fmean(t.net_r for t in trades)
        tr = [Trade(**{**asdict(t), "net_r": t.net_r - mu}) for t in trades]
    days = day_ledgers(tr, all_days)
    plan = PLANS[plan_name]
    per_seed = []
    for s in SEEDS:
        rng = np.random.default_rng(s)
        ev, n_pass, n_breach, n_paid = [], 0, 0, 0
        for _ in range(PATHS):
            r = run_path(days, plan, risk_usd, rng)
            paid = 0.9 * sum(r["payouts"])
            ev.append(paid - plan["fee"])
            n_pass += r["phase"] not in ("eval", "eval_timeout")
            n_breach += r["breach"]
            n_paid += bool(r["payouts"])
        per_seed.append({"seed": s, "ev_net_usd": round(st.fmean(ev), 2), "p_pass_eval": round(n_pass / PATHS, 4),
                         "p_breach": round(n_breach / PATHS, 4), "p_any_payout": round(n_paid / PATHS, 4)})
    return {"plan": plan_name, "risk_usd": risk_usd, "demeaned": demean, "seeds": per_seed,
            "ev_min": min(p["ev_net_usd"] for p in per_seed), "ev_mean": round(st.fmean(p["ev_net_usd"] for p in per_seed), 2)}


# ------------------------------------------------------------------ ML meta-label
FEATS = ["or_width_atr", "gap_atr", "breakout_min", "dow", "dir", "atr_pct", "inst", "or_min"]


def ml_filter(trades: list[Trade]) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    rows = [{**t.feats, "y": int(t.net_r > 0), "net_r": t.net_r, "year": int(t.day[:4]), "day": t.day} for t in trades]
    df = pd.DataFrame(rows)
    X = df[FEATS].astype(float)
    disc_years = list(range(2021, 2025))
    scored = []
    # discovery walk-forward: train on every year before, score the year; threshold = median train-score
    for y in disc_years + ["hold"]:
        if y == "hold":
            tr = df["year"] <= 2024
            te = df["day"] >= HOLD[0]
        else:
            tr = df["year"] < y
            te = df["year"] == y
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, random_state=0)
        m.fit(X[tr], df.loc[tr, "y"])
        thr = float(np.median(m.predict_proba(X[tr])[:, 1]))
        p = m.predict_proba(X[te])[:, 1]
        sub = df[te].copy()
        sub["keep"] = p > thr
        sub["fold"] = str(y)
        scored.append(sub)
    s = pd.concat(scored)
    hold = s[s["fold"] == "hold"]
    kept, allr = hold[hold["keep"]]["net_r"].to_numpy(), hold["net_r"].to_numpy()
    rng = np.random.default_rng(0)
    diffs = []
    for _ in range(5000):
        idx = rng.integers(len(hold), size=len(hold))
        b = hold.iloc[idx]
        k = b[b["keep"]]["net_r"]
        if len(k):
            diffs.append(k.mean() - b["net_r"].mean())
    lo = float(np.percentile(diffs, 2.5)) if diffs else None
    disc = s[s["fold"] != "hold"]
    res = {
        "n_hold_all": len(allr), "n_hold_kept": len(kept),
        "mean_r_hold_all": round(float(allr.mean()), 5), "mean_r_hold_kept": round(float(kept.mean()), 5) if len(kept) else None,
        "net_r_hold_kept": round(float(kept.sum()), 3), "uplift_ci95_lo": round(lo, 5) if lo is not None else None,
        "disc_by_year": {f: {"n_kept": int(g["keep"].sum()), "mean_kept": round(float(g[g["keep"]]["net_r"].mean()), 5),
                             "mean_all": round(float(g["net_r"].mean()), 5)} for f, g in disc.groupby("fold")},
    }
    if len(kept) < 60:
        v = "indeterminate"
    elif len(kept) and kept.mean() > allr.mean() and lo is not None and lo > 0 and kept.sum() > 0:
        v = "pass"
    else:
        v = "fail"
    res["verdict"] = v
    return res


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage", choices=("stage0", "survival", "ml"), required=True)
    ap.add_argument("--corpus", default=str(Path.home() / ".cache" / "tradeify-futures-5m"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--unit", required=True)
    ap.add_argument("--stage0-json", help="survival: the stage0 result to read the PASS cells from")
    ap.add_argument("--source", choices=("dukascopy", "ibkr"), default="dukascopy",
                    help="ibkr = real CME bars from IB's free history (per-contract jsonl, --ibkr-percontract); stage0 only")
    ap.add_argument("--ibkr-percontract", action="append", default=[], metavar="SYM=PATH",
                    help="with --source ibkr: a per-contract jsonl per symbol (repeatable)")
    ap.add_argument("--cells", default="", help="comma list of cells to run, e.g. MNQ_OR15 (default: all)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    corpus = Path(a.corpus)
    cells: dict[str, list[Trade]] = {}
    all_days: set[str] = set()
    want = {c.strip() for c in a.cells.split(",") if c.strip()}
    if a.source == "ibkr":
        if a.stage != "stage0":
            raise SystemExit("--source ibkr supports --stage stage0 only (RULE-RQ-20261112-09d2-05)")
        paths = dict(x.split("=", 1) for x in a.ibkr_percontract)
        provs, sess_by_sym = {}, {}
        for sym, pth in paths.items():
            df, provs[sym] = load_ibkr_percontract(Path(pth))
            rth_days = {str(d) for d, g in df[(df["t"] >= RTH_OPEN) & (df["t"] < FLAT_AT)].groupby("d") if len(g) >= 60}
            sess_by_sym[sym] = sorted(rth_days)
            for orm in OR_MINUTES:
                k = f"{sym}_OR{orm}"
                if not want or k in want:
                    cells[k] = orb_trades(df, sym, orm)
        rec = {"research_unit": a.unit, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "produced_by": "scripts/research/tradeify_futures_fit.py --source ibkr", "stage": a.stage,
               "population": {k: len(v) for k, v in cells.items()},
               "data": "IB reqHistoricalData TRADES, real CME contracts, per-session volume roll (load_ibkr_percontract)",
               "data_provenance": provs,
               "cells": {k: grade_cell_sessions(v, sess_by_sym[k.split("_")[0]]) for k, v in cells.items()}}
        with open(out / "trades.jsonl", "w") as f:
            for k, v in cells.items():
                f.writelines(json.dumps({"cell": k, **asdict(t)}, default=str) + "\n" for t in v)
        vs = [c["verdict"] for c in rec["cells"].values()]
        rec["verdict"] = "pass" if "pass" in vs else ("fail" if vs and all(v == "fail" for v in vs) else "indeterminate")
        rec["read_state"] = "complete"
        (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
        print(json.dumps({k: rec[k] for k in ("research_unit", "stage", "verdict", "population")}, default=str))
        return 0
    for sym in INSTR:
        df = load_bars(sym, corpus, DISC[0], HOLD[1])
        all_days |= {str(d) for d in df[(df["t"] >= RTH_OPEN) & (df["t"] < FLAT_AT)]["d"].unique()}
        for orm in OR_MINUTES:
            cells[f"{sym}_OR{orm}"] = orb_trades(df, sym, orm)
    days_sorted = sorted(all_days)
    with open(out / "trades.jsonl", "w") as f:
        for k, v in cells.items():
            f.writelines(json.dumps({"cell": k, **asdict(t)}, default=str) + "\n" for t in v)
    rec = {"research_unit": a.unit, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "produced_by": "scripts/research/tradeify_futures_fit.py", "stage": a.stage,
           "population": {k: len(v) for k, v in cells.items()},
           "window": {"discovery": DISC, "holdout": HOLD}, "data": "dukascopy 5m bid proxies (see module doc)"}
    if a.stage == "stage0":
        rec["cells"] = {k: grade_cell(v) for k, v in cells.items()}
        rec["verdict"] = "pass" if any(c["verdict"] == "pass" for c in rec["cells"].values()) else (
            "fail" if all(c["verdict"] == "fail" for c in rec["cells"].values()) else "indeterminate")
    elif a.stage == "survival":
        s0 = json.loads(Path(a.stage0_json).read_text())
        passing = [k for k, c in s0["cells"].items() if c["verdict"] == "pass"]
        # descriptive (NOT a verdict) runs on the best discovery cell even when nothing passed
        best = max(s0["cells"], key=lambda k: s0["cells"][k]["net_r_disc"])
        targets = passing + ([f"BOOK({'+'.join(passing)})"] if len(passing) > 1 else [])
        if not passing:
            targets = [best]
        res = {}
        for tgt in targets:
            tr = [t for k in passing for t in cells[k]] if tgt.startswith("BOOK") else cells[tgt]
            res[tgt] = {"stage0_pass": tgt in passing or tgt.startswith("BOOK"), "runs": []}
            for plan in PLANS:
                for r in RISK_GRID:
                    run = survival(tr, days_sorted, plan, r)
                    null = survival(tr, days_sorted, plan, r, demean=True)
                    run["null_ev_mean"] = null["ev_mean"]
                    run["verdict"] = ("pass" if (res[tgt]["stage0_pass"] and run["ev_min"] > 0 and run["ev_mean"] > null["ev_mean"])
                                      else ("not_a_verdict" if not res[tgt]["stage0_pass"] else "fail"))
                    res[tgt]["runs"].append(run)
        rec["targets"] = res
        prim = [r for t in res.values() for r in t["runs"] if r["risk_usd"] == PRIMARY_RISK and r["verdict"] == "pass"]
        rec["verdict"] = "pass" if prim else ("not_applicable" if not passing else "fail")
    else:
        rec["ml"] = ml_filter([t for v in cells.values() for t in v])
        rec["verdict"] = rec["ml"]["verdict"]
    (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    print(json.dumps({k: rec[k] for k in ("research_unit", "stage", "verdict", "population")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
