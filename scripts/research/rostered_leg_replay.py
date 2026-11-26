#!/usr/bin/env python3
# wiring: research/queue/RQ-20261125-f1a0-24.yaml (row REGIME-ROSTERED-CONFIG-REPLAY: the R3 confirmation on the configs we actually trade)
"""REGIME-ROSTERED-CONFIG-REPLAY: replay every ROSTERED crypto leg (a `mode: live` book, real-money / prop / demo floor) of the trend, pullback,
fade and squeeze families with its DECLARED config/strategies.yaml params over one pinned window, then grade the REGIME-PROGRAM R3 / R4 tilts on
those legs as books. The confirmation population of RQ-20261125-f1a0-20 (R3 PASS on the sweep corpus): different trades (declared configs, not
averaged sweep variants), the legs a sizing proposal would act on.

Replay: the evidence builder's own path, nothing reimplemented: exit_lever_ablation.fetch_candles (regime_debt_matrix._fetch_csv, keyless Binance
Vision) + exit_lever_ablation.build_arm_argv (regime_debt_matrix.build_harness_cmd, the harness's own venue-aware fee + slippage + funding) with
--start/--end pinned to WINDOW. A leg whose harness fails is a recorded state (`legs.<leg>.state`), never dropped silently.

Grade (RULE-REGIME-R3-CONFIRM-ROSTERED-20261125): books = leg x direction; the regime_r2_family_router machinery unchanged (weekly books, causal
trailing / same-cell prior means, 2.0 / 0.5 tilt renormalised weekly, 1,000 week-bootstrap draws, 200 within-week permutations). Arms: advol and hmm2
state tilts (f1a0-20) and the no-state tilt (f1a0-23's control), each vs equal risk. An arm PASSES iff delta >= +0.01 R/trade AND t >= 2 AND
permutation share <= 0.0167 (three arms, Bonferroni of 0.05) AND >= 4 of 5 test years > 0. UNIT PASS iff any arm passes; FAIL iff every arm has
delta <= 0 or share >= 0.5; else INDETERMINATE. Reported, not graded: the state-vs-no-state week-paired deltas (decomp), per-leg trade counts / net R.

TRADE-STATE (``--mode tradestate``, unit RQ-20261125-f1a0-25, RULE-REGIME-TRADESTATE-20261125), from f1a0-24 (book-level BTC-state and book-quality
tilts NOT confirmed on the rostered legs; f1a0-23 showed BTC state adds nothing beyond book quality): condition each TRADE on its OWN symbol's state at
entry (the traded symbol's last daily close before the entry day above / below its 50-day mean x its 20-day realised vol above / below its trailing
365-day median), tilting 2.0 / 0.5 by the sign of the mean net R of that leg x direction's PRIOR trades in the same cell that had EXITED before this
entry (>= TS_MIN_N of them, else 1.0), renormalised within each leg x calendar month (same risk per leg-month). Statistic: weighted minus unweighted net
R per trade, 1,000 entry-week bootstrap draws; control: the raw tilts permuted within each leg x month (200 draws). PASS iff delta >= +0.01 AND t >= 2
AND permutation share <= 0.05 AND >= 4 of 5 years > 0; FAIL iff delta <= 0 or share >= 0.5; else INDETERMINATE.

    python3 scripts/research/rostered_leg_replay.py --out DIR [--legs a,b] [--work DIR] [--mode book|tradestate]
    python3 scripts/research/rostered_leg_replay.py --self-test
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import regime_r2_family_router as RR  # noqa: E402

FAMILIES = ("trend", "pullback", "fade", "squeeze")
WINDOW = ("2020-09-01", "2026-10-26")          # pinned: the R2-R3 corpus window
FETCH_DAYS = 2350
TS_MIN_N = 20
RULE_TS = {"id": "RULE-REGIME-TRADESTATE-20261125", "min_delta_r": 0.01, "min_t": 2.0, "max_random_share": 0.05, "min_years_positive": 4,
           "n_test_years": 5, "fail_random_share": 0.5}
#: METASTATE (RQ-20261125-f1a0-26): the f1a0-25 tilt machinery with the cell-mean prior replaced by a walk-forward LightGBM on each trade's own-symbol AND
#: BTC daily state (continuous, as of the prior day's close) + leg / direction. Same tilt sizes, leg-month renormalisation, permutation control and grade.
RULE_MS = {"id": "RULE-REGIME-METASTATE-20261125", "min_delta_r": 0.01, "min_t": 2.0, "max_random_share": 0.05, "min_years_positive": 4,
           "n_test_years": 5, "fail_random_share": 0.5}
MS_FEATS = ["own_sma50", "own_sma200", "own_ret20", "own_ret5", "own_rv_ratio", "own_rv5_20", "own_hi20",
            "btc_sma50", "btc_sma200", "btc_ret20", "btc_ret5", "btc_rv_ratio", "btc_rv5_20", "btc_hi20", "dir", "leg", "fam"]
MS_LGB = {"n_estimators": 200, "learning_rate": 0.03, "num_leaves": 15, "min_child_samples": 50, "subsample": 0.8, "subsample_freq": 1,
          "colsample_bytree": 0.8, "reg_lambda": 1.0, "random_state": 20261125, "deterministic": True, "force_row_wise": True, "verbose": -1, "n_jobs": 2}
MS_CLIP_R = 3.0
#: FRESH POPULATION (RQ-20261125-f1a0-28): the rostered leg configs replayed on liquid USDT perps NONE of them trades (fixed before any run), so the
#: metastate recipe is confirmed on trades it has never seen, with no re-tune. Leg key = "<leg>@<symbol>".
FRESH_SYMBOLS = ("BNBUSDT", "DOGEUSDT", "LINKUSDT", "LTCUSDT")
RULE_MS_FRESH = dict(RULE_MS, id="RULE-REGIME-METASTATE-FRESH-20261125")
#: FRESH POPULATION 2 (RQ-20261125-f1a0-30): a third, disjoint population for the same frozen recipe (fixed before any run); f1a0-26 and f1a0-28 are
#: REPORTED beside it (inverse-variance pooled), never part of its verdict.
FRESH_SYMBOLS_2 = ("DOTUSDT", "ATOMUSDT", "BCHUSDT", "ETCUSDT")
RULE_MS_FRESH2 = dict(RULE_MS, id="RULE-REGIME-METASTATE-FRESH2-20261125")
_FETCHED: Dict[Tuple[str, str], Tuple[str, Dict[str, Any]]] = {}
#: INTRADAY STATE (RQ-20261125-f1a0-32): the metastate machinery with the DAILY own-symbol + BTC block replaced by the leg's OWN-TIMEFRAME state at
#: entry (the REGIME-PROGRAM next form after f1a0-30 FAIL). Features from the last bar fully CLOSED at or before the entry time.
ID_FEATS = ["id_rangepos48", "id_volburst", "id_ret12", "id_hi96", "dir", "leg", "fam"]
RULE_ID = dict(RULE_MS, id="RULE-REGIME-INTRADAY-20261125")
MS_MIN_TRAIN = 300
# ENTRY FILTER (--mode filter, unit RQ-20261125-f1a0-35, the registered fail_action of f1a0-32): the f1a0-26 walk-forward model, but a trade whose
# prediction is below the TRAINING predictions' 1/3 quantile is SKIPPED (contributes 0 R), every other trade taken at size 1; no renormalisation.
RULE_FILTER = dict(RULE_MS, id="RULE-REGIME-ENTRY-FILTER-20261125")
# EQUITIES / FUTURES UNIVERSE (--universe equities, unit RQ-20261126-e9a4-01; the registered next subject after the crypto regime forms closed with
# f1a0-35 and the F8 regime-as-input FAIL): the same frozen recipe on the ROSTERED non-crypto legs (Alpaca ETFs, IB micro futures), candles from the
# Dukascopy lane (research-script-run installs dukascopy-python, not yfinance; some symbols resolve to a PROXY instrument, recorded per leg), and the
# market anchor block (the btc_* columns) built from SPY daily closes instead of BTC. Nothing re-tuned.
RULE_FILTER_EQ = dict(RULE_MS, id="RULE-REGIME-ENTRY-FILTER-EQ-20261126")
# ADX-CELL REMOVAL CONFIRMATION (--mode adxcell, unit RQ-20261126-4d1c-01; the walk-forward-before-Tier-3 read the manager required after
# c4f2-01 priced the LIVE htf_pullback_trend_2h ADX drops at +1.08 R each on a bracket replay): the leg replayed through its OWN harness, each
# trade tagged with the ADX-14 regime of the last bar CLOSED at or before its entry (src/runtime/regime/detector.py: wilder_adx + regime_label,
# the live detector), and the 1-D cells of config/regime_policy.yaml applied. Framed as REMOVAL vs the cells: a dropped trade weighs 2, a kept one 1,
# so delta = (sum of the dropped trades' net R) / all trades = what removing the cells adds back; the permutations add back the same count of random
# trades within leg x month (the matched-random control). Graded by RR.tilt_verdict on the RULE_MS thresholds, unchanged.
RULE_ADX = dict(RULE_MS, id="RULE-HTF-ADX-CELL-REMOVAL-20261126")
# RATES / RISK-OFF HAND RULE (--mode ratesrule, unit RQ-20261126-b71e-01; REGIME-PROGRAM's registered next form after the learned filters failed on
# crypto (f1a0-35) and non-crypto (e9a4-01)): ONE fixed hand rule on the rostered BOND and GOLD legs. Skip a LONG entry when the US 10-year REAL
# yield (FRED DFII10, the last observation dated strictly before the entry day) rose by more than RATES_SHOCK_BP over the prior RATES_LOOKBACK
# observations: a real-rate shock is the textbook headwind for duration and for gold. Shorts and every other leg are untouched.
RATES_SERIES = "DFII10"
RATES_LOOKBACK = 20
RATES_SHOCK_BP = 20.0
RATES_LEGS = ("tlt_pullback_1d", "tlt_pullback_1h", "ief_pullback_1d", "gld_pullback_1d", "iaum_pullback_1d", "mgc_pullback_1d", "mgc_trend_1h")
RULE_RATES = dict(RULE_MS, id="RULE-REGIME-RATES-SHOCK-20261126")
RULE_MS_EQ = dict(RULE_MS, id="RULE-REGIME-METASTATE-EQ-20261126")
EQ_ANCHOR = {"symbols": ["SPY"], "timeframe": "1d"}
NON_CRYPTO_SOURCE = "auto"
# EVENT-DAY ENTRY CONDITIONING (--mode eventday, unit RQ-20261126-d3a5-01; DESK-MACRO-DAILY step 3a): do the rostered legs' trades ENTERED within
# EV_WINDOW_H hours of a scheduled US release (fomc_decision / cpi / nfp, comms/research/event_span_history/us_releases.jsonl) differ in net R from
# their other trades? ENTRY-conditioned on purpose: a5b3-01's spanning-vs-not report is confounded by hold length (a trade that spans a release is a
# longer hold, and long holds are the trend winners). Two-sided, with an equivalence bound, so a FAIL is a measured "no material effect".
EV_RELEASES = REPO / "comms/research/event_span_history/us_releases.jsonl"
EV_CLASSES = ("fomc_decision", "cpi", "nfp")
EV_WINDOW_H = 24.0
EV_PLACEBO_SHIFT_DAYS = (5, 15)
RULE_EV = {"id": "RULE-DESK-3A-EVENTDAY-20261126", "min_abs_diff_r": 0.10, "equivalence_r": 0.10, "max_placebo_share": 0.05,
           "min_flagged": 200, "n_boot": 1000, "n_placebo": 200}
RULE = {"id": "RULE-REGIME-R3-CONFIRM-ROSTERED-20261125", "min_delta_r": 0.01, "min_t": 2.0, "max_random_share": 0.05 / 3,
        "min_years_positive": 4, "n_test_years": 5, "fail_random_share": 0.5}


def load_cells(path: Path = REPO / "config/regime_policy.yaml") -> Dict[str, Dict[str, Dict[str, str]]]:
    """The 1-D ADX cells: {regime: {strategy: {"long": on|off, "short": on|off}}} for regime in chop / transitional / trending."""
    import yaml
    pol = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    def norm(x) -> str:   # YAML 1.1 reads bare on/off as booleans True/False
        if isinstance(x, bool):
            return "on" if x else "off"
        return "off" if str(x).strip().lower() in ("off", "false", "0", "no") else "on"
    return {r: {k: {sd: norm(v.get(sd, "on")) for sd in ("long", "short")} for k, v in (pol.get(r) or {}).items() if isinstance(v, dict)}
            for r in ("chop", "transitional", "trending")}


def adx_regime_at_entry(bars: pd.DataFrame, when: pd.Series, tf_sec: float) -> pd.Series:
    """The live detector's label (wilder_adx(14) + regime_label) of the last bar whose CLOSE (open + tf) is <= each entry time; 'unknown' before
    the first closed bar."""
    sys.path.insert(0, str(REPO))
    from src.runtime.regime.detector import regime_label, wilder_adx
    adx = wilder_adx(bars, period=14)
    close_t = pd.DatetimeIndex(bars.index).as_unit("ns").asi8 + int(tf_sec * 1e9)
    x = pd.DatetimeIndex(pd.to_datetime(when, utc=True)).as_unit("ns").asi8
    i = np.searchsorted(close_t, x, side="right") - 1
    vals = adx.to_numpy()
    return pd.Series([regime_label(float(vals[j])) if j >= 0 else "unknown" for j in i], index=when.index)


def grade_adxcell(tr: pd.DataFrame, bars: Dict[str, pd.DataFrame], tf: Dict[str, float], cells: Dict[str, Any],
                  seed: int = RR.SEED) -> Dict[str, Any]:
    """Removal of each leg's 1-D ADX cells vs the cells as configured, over the test years (>= RR.TEST_START)."""
    tr = tr.copy().reset_index(drop=True)
    reg = pd.Series("unknown", index=tr.index, dtype=object)
    for leg, g in tr.groupby("family"):
        if leg in bars:
            reg.loc[g.index] = adx_regime_at_entry(bars[leg], g.ts, tf[leg]).to_numpy()
    side = np.where(tr.direction.astype(str).str.lower().str.startswith(("short", "sell")), "short", "long")
    on = np.array([cells.get(r, {}).get(f, {}).get(sd, "on") != "off" for r, f, sd in zip(reg, tr.family, side)])
    keep = (tr.ts >= pd.Timestamp(RR.TEST_START, tz="UTC")).to_numpy()
    t = tr[keep].reset_index(drop=True)
    raw = np.where(on[keep], 1.0, 2.0)
    g = grade_raw(t, raw, RULE_ADX, seed, normalise=False)
    rk, sk, ok = reg.to_numpy()[keep], side[keep], on[keep]
    per_cell = {}
    for r in ("trending", "transitional", "chop", "unknown"):
        for sd in ("long", "short"):
            m = (rk == r) & (sk == sd)
            if m.any():
                per_cell[f"{r}/{sd}"] = {"cell": "on" if ok[m][0] else "off", "n": int(m.sum()),
                                         "mean_net_r": round(float(t.net_r[m].mean()), 4), "sum_net_r": round(float(t.net_r[m].sum()), 3)}
    dropped = raw == 2.0
    g["dropped"] = {"n": int(dropped.sum()), "share": round(float(dropped.mean()), 4),
                    "mean_net_r": round(float(t.net_r[dropped].mean()), 5) if dropped.any() else None,
                    "kept_mean_net_r": round(float(t.net_r[~dropped].mean()), 5) if (~dropped).any() else None}
    g["per_cell_reported"] = per_cell
    g["regime_unknown_trades"] = int((rk == "unknown").sum())
    return {"arms": {"remove_cells": g}, "verdict": g["verdict"], "n_legs": int(t.family.nunique())}
def load_releases(path: Path = EV_RELEASES, classes=EV_CLASSES) -> pd.DataFrame:
    """The committed point-in-time US release history: one row per graded release (class, release_utc)."""
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    df = pd.DataFrame([{"cls": r.get("class"), "t": r.get("release_utc")} for r in rows if r.get("class") in classes and r.get("release_utc")])
    df["t"] = pd.to_datetime(df.t, utc=True, errors="coerce")
    return df.dropna(subset=["t"]).sort_values("t").reset_index(drop=True)


def event_flags(ts: pd.Series, rel: pd.Series, window_h: float = EV_WINDOW_H) -> np.ndarray:
    """True where an entry time lies within +-window_h of any release time in ``rel``."""
    r = np.sort(pd.DatetimeIndex(pd.to_datetime(rel.dropna(), utc=True)).as_unit("ns").asi8)
    x = pd.DatetimeIndex(pd.to_datetime(ts, utc=True)).as_unit("ns").asi8
    if len(r) == 0:
        return np.zeros(len(x), dtype=bool)
    w = int(window_h * 3600 * 1e9)
    i = np.searchsorted(r, x)
    lo = np.abs(x - r[np.clip(i - 1, 0, len(r) - 1)])
    hi = np.abs(r[np.clip(i, 0, len(r) - 1)] - x)
    return np.minimum(lo, hi) <= w


def _diff_ci(net: np.ndarray, flag: np.ndarray, weeks: np.ndarray, rng: np.random.Generator, n_boot: int) -> Tuple[float, List[float]]:
    """mean(flagged) - mean(unflagged), and its 95% CI from a week-cluster bootstrap."""
    d = float(net[flag].mean() - net[~flag].mean())
    uw = np.unique(weeks)
    idx = {w: np.flatnonzero(weeks == w) for w in uw}
    bs = []
    for _ in range(n_boot):
        take = np.concatenate([idx[w] for w in rng.choice(uw, size=len(uw), replace=True)])
        f = flag[take]
        if f.any() and (~f).any():
            bs.append(net[take][f].mean() - net[take][~f].mean())
    return d, [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))] if bs else [float("nan"), float("nan")]


def grade_eventday(tr: pd.DataFrame, rel: pd.DataFrame, rule: Dict[str, Any] = RULE_EV, seed: int = RR.SEED) -> Dict[str, Any]:
    """Per class and pooled ANY: event-entry vs other trades (net R), week-cluster bootstrap CI, and a placebo that shifts every release of the class
    by a random +-5..15 days (seeded per draw); placebo share = share of placebo |diff| >= the actual |diff|. Decided on the pooled ANY class."""
    rng = np.random.default_rng(seed)
    lo_cov, hi_cov = rel.t.min().floor("D"), rel.t.max().ceil("D")
    t = tr[(tr.ts >= lo_cov) & (tr.ts <= hi_cov)].reset_index(drop=True)
    net = t.net_r.to_numpy(dtype=float)
    weeks = t.ts.dt.tz_convert(None).dt.to_period("W").astype(str).to_numpy()
    out: Dict[str, Any] = {"covered_window": [str(lo_cov.date()), str(hi_cov.date())], "n_trades": int(len(t)),
                           "excluded_outside_history": int(len(tr) - len(t)), "classes": {}}
    for cls in EV_CLASSES + ("any",):
        r = rel.t if cls == "any" else rel[rel.cls == cls].t
        flag = event_flags(t.ts, r)
        nf = int(flag.sum())
        if nf < 2 or nf > len(t) - 2:
            out["classes"][cls] = {"n_flagged": nf, "read_state": "could_not_compute"}
            continue
        d, ci = _diff_ci(net, flag, weeks, rng, rule["n_boot"])
        pl = []
        for _ in range(rule["n_placebo"]):
            sh = pd.to_timedelta(rng.integers(EV_PLACEBO_SHIFT_DAYS[0], EV_PLACEBO_SHIFT_DAYS[1] + 1, size=len(r)) * rng.choice([-1, 1], size=len(r)), unit="D")
            pf = event_flags(t.ts, pd.Series(r.to_numpy()) + sh)
            if pf.any() and (~pf).any():
                pl.append(abs(net[pf].mean() - net[~pf].mean()))
        share = float(np.mean([p >= abs(d) for p in pl])) if pl else None
        by_leg = {}
        for leg, g in t.groupby("family"):
            f = event_flags(g.ts, r)
            if f.sum() >= 5 and (~f).sum() >= 5:
                by_leg[leg] = {"n_flagged": int(f.sum()), "n_other": int((~f).sum()), "diff_r": round(float(g.net_r[f].mean() - g.net_r[~f].mean()), 4)}
        out["classes"][cls] = {"n_flagged": nf, "n_other": int(len(t) - nf), "mean_flagged": round(float(net[flag].mean()), 4),
                               "mean_other": round(float(net[~flag].mean()), 4), "diff_r": round(d, 4), "ci95": [round(ci[0], 4), round(ci[1], 4)],
                               "placebo_share": share, "placebo_draws": len(pl), "by_leg_reported": by_leg, "read_state": "measured"}
    a = out["classes"].get("any", {})
    if a.get("read_state") != "measured" or a["n_flagged"] < rule["min_flagged"]:
        verdict, why = "indeterminate", f"pooled ANY: n_flagged {a.get('n_flagged')} < {rule['min_flagged']} or not computable"
    elif abs(a["diff_r"]) >= rule["min_abs_diff_r"] and (a["ci95"][0] > 0 or a["ci95"][1] < 0) and a["placebo_share"] is not None \
            and a["placebo_share"] <= rule["max_placebo_share"]:
        verdict, why = "pass", f"event-entry trades differ by {a['diff_r']:+.4f} R (CI {a['ci95']}, placebo share {a['placebo_share']})"
    elif -rule["equivalence_r"] < a["ci95"][0] and a["ci95"][1] < rule["equivalence_r"]:
        verdict, why = "fail", f"no material effect: CI {a['ci95']} inside +-{rule['equivalence_r']} R"
    else:
        verdict, why = "indeterminate", f"diff {a['diff_r']:+.4f} R, CI {a['ci95']}, placebo share {a['placebo_share']}: not separable, not ruled out"
    out.update({"verdict": verdict, "why": why})
    return out


def fetch_fred(series: str, cache: Optional[Path] = None) -> pd.Series:
    """A FRED series via the keyless fredgraph CSV (the same route index_signal_etf_harness uses on the runner): values indexed by observation date;
    '.' (missing) rows dropped. Raises on any fetch / parse failure (the caller records it; never a silent empty series)."""
    import io
    import requests
    if cache is not None and cache.exists():
        text = cache.read_text()
    else:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=60)
        r.raise_for_status()
        text = r.text
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text)
    d = pd.read_csv(io.StringIO(text))
    d.columns = ["date", "value"]
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d = d.dropna()
    return pd.Series(d["value"].to_numpy(dtype=float), index=pd.to_datetime(d["date"], utc=True)).sort_index()


def rates_shock(series: pd.Series, when: pd.Series, lookback: int = RATES_LOOKBACK, shock_bp: float = RATES_SHOCK_BP) -> np.ndarray:
    """True where the series' change over the prior ``lookback`` observations, as of the last observation dated strictly BEFORE the entry day, exceeds
    ``shock_bp`` basis points (the series is in percent). False where there is not enough history (the rule never skips on missing data)."""
    chg = (series - series.shift(lookback)) * 100.0
    idx = pd.DatetimeIndex(series.index).as_unit("ns").asi8
    day = pd.DatetimeIndex(pd.to_datetime(when, utc=True).dt.floor("D")).as_unit("ns").asi8
    i = np.searchsorted(idx, day, side="left") - 1      # strictly before the entry day: no same-day print
    vals = chg.to_numpy()
    out = np.zeros(len(day), dtype=bool)
    ok = i >= 0
    out[ok] = np.nan_to_num(vals[i[ok]], nan=0.0) > shock_bp
    return out


def grade_ratesrule(tr: pd.DataFrame, series: Optional[pd.Series], seed: int = RR.SEED) -> Dict[str, Any]:
    """The hand rule over the test years: keep = not (long AND real-rate shock); graded like the entry filter (skipped = 0 R, matched random skips)."""
    if series is None or not len(series):
        return {"verdict": "indeterminate", "why": f"FRED {RATES_SERIES} could not be read", "read_state": "could_not_look"}
    tr = tr.copy().reset_index(drop=True)
    long_ = ~tr.direction.astype(str).str.lower().str.startswith(("short", "sell")).to_numpy()
    skip = long_ & rates_shock(series, tr.ts)
    keep = (tr.ts >= pd.Timestamp(RR.TEST_START, tz="UTC")).to_numpy()
    t = tr[keep].reset_index(drop=True)
    sk = skip[keep]
    g = grade_raw(t, np.where(sk, 0.0, 1.0), RULE_RATES, seed, normalise=False)
    g["skipped"] = {"n": int(sk.sum()), "share": round(float(sk.mean()), 4), "mean_net_r": round(float(t.net_r[sk].mean()), 5) if sk.any() else None,
                    "kept_mean_net_r": round(float(t.net_r[~sk].mean()), 5) if (~sk).any() else None}
    g["by_leg_reported"] = {leg: {"n": int(m.sum()), "skipped": int((m & sk).sum()), "delta": round(float(-(t.net_r.to_numpy(float)[m & sk]).sum() / max(m.sum(), 1)), 5)}
                            for leg in sorted(t.family.unique()) for m in [(t.family == leg).to_numpy()]}
    g["rule"] = {"series": RATES_SERIES, "lookback_obs": RATES_LOOKBACK, "shock_bp": RATES_SHOCK_BP, "applies_to": "long entries"}
    return {"arms": {"rates_shock_skip": g}, "verdict": g["verdict"], "n_legs": int(t.family.nunique())}


def rostered_legs(root: Path = REPO, universe: str = "crypto") -> Dict[str, Dict[str, Any]]:
    """Legs on a `mode: live` book whose cfg classifies into FAMILIES: {leg: {cfg, book, harness}}. universe crypto = USDT symbols (the original);
    equities = every other symbol (ETFs, futures)."""
    import yaml
    import regime_debt_matrix as rdm
    spec = importlib.util.spec_from_file_location("mlc", root / "scripts/ci/check_research_queue_ml_consumer.py")
    mlc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mlc)
    book = mlc.books(root)
    st = yaml.safe_load((root / "config/strategies.yaml").read_text(encoding="utf-8"))["strategies"]
    out = {}
    for leg, b in sorted(book.items()):
        cfg = st.get(leg)
        if not isinstance(cfg, dict):
            continue
        sym = (cfg.get("symbols") or [None])[0]
        h = rdm.classify(cfg)
        if sym and (str(sym).endswith("USDT") == (universe == "crypto")) and h in FAMILIES:
            out[leg] = {"cfg": cfg, "book": b, "harness": h}
    return out


def fresh_legs(cfgs: Dict[str, Dict[str, Any]], symbols=FRESH_SYMBOLS) -> Dict[str, Dict[str, Any]]:
    """Every rostered leg config re-pointed at each FRESH symbol it does not already trade: {"<leg>@<sym>": {cfg, book, harness, base_leg}}."""
    out = {}
    for leg, v in cfgs.items():
        own = v["cfg"]["symbols"][0]
        for sym in symbols:
            if sym != own:
                out[f"{leg}@{sym}"] = {"cfg": dict(v["cfg"], symbols=[sym]), "book": v["book"], "harness": v["harness"], "base_leg": leg}
    return out


def replay_leg(leg: str, cfg: Dict[str, Any], work: Path) -> Dict[str, Any]:
    import exit_lever_ablation as ela
    work.mkdir(parents=True, exist_ok=True)
    csv, emit, jout, log = (str(work / f"{leg}{x}") for x in (".csv", "__trades.jsonl", "__bt.json", ".log"))
    key = (str(cfg["symbols"][0]), str(cfg.get("timeframe")))
    try:
        if key in _FETCHED and Path(_FETCHED[key][0]).is_file():   # the same symbol x timeframe already fetched this run: reuse the bytes + feed
            shutil.copyfile(_FETCHED[key][0], csv)
            feed = _FETCHED[key][1]
        else:
            feed = ela.fetch_candles(leg, cfg, FETCH_DAYS, csv, non_crypto_source=NON_CRYPTO_SOURCE)
            _FETCHED[key] = (csv, feed)
    except (subprocess.CalledProcessError, ValueError, OSError) as e:
        return {"state": "fetch_failed", "why": f"{type(e).__name__}: {e}"[:300]}
    argv, omitted = ela.build_arm_argv(leg, cfg, csv, str(feed["resample"]), emit, jout, [], WINDOW[0], WINDOW[1])
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT, cwd=str(REPO), timeout=3600, check=False).returncode
    if rc != 0 or not Path(jout).is_file():
        return {"state": "harness_failed", "why": f"exit {rc}", "argv": argv[1:]}
    trades = ela._load_trades(emit) if Path(emit).is_file() else []
    return {"state": "measured", "n": len(trades), "net_r": round(float(sum(t.get("net_r") or 0.0 for t in trades)), 3),
            "omitted_levers": omitted, "argv": argv[1:], "trades": trades, "feed": {k: feed.get(k) for k in ("source", "ticker") if k in feed}}


def trades_frame(per_leg: Dict[str, Dict[str, Any]], cfgs: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for leg, r in per_leg.items():
        if r.get("state") != "measured":
            continue
        sym, tf = cfgs[leg]["cfg"]["symbols"][0], str(cfgs[leg]["cfg"].get("timeframe"))
        for t in r["trades"]:
            if t.get("net_r") is None or t.get("entry_time") is None:
                continue
            rows.append((leg, sym, tf, str(t["entry_time"])[:19], str(t.get("direction")), float(t["net_r"]), str(t.get("exit_time") or "")[:19]))
    df = pd.DataFrame(rows, columns=["family", "symbol", "tf", "entry_time", "direction", "net_r", "exit_time"])
    df["ts"] = pd.to_datetime(df.entry_time, utc=True, errors="coerce")
    df["xts"] = pd.to_datetime(df.exit_time, utc=True, errors="coerce")
    return df.dropna(subset=["ts"])


def tf_seconds(tf: str) -> float:
    """'15m' / '1h' / '4h' / '1d' -> seconds."""
    tf = str(tf).strip().lower()
    return float(int(tf[:-1]) * {"m": 60, "h": 3600, "d": 86400}[tf[-1]])


def ohlc_bars(csv: Path) -> pd.DataFrame:
    """The fetched candle CSV as an OHLC frame indexed by bar OPEN time (UTC), the same time-column rules as daily_closes."""
    d = pd.read_csv(csv)
    cols = {c.lower(): c for c in d.columns}
    tcol = next((cols[c] for c in ("timestamp", "time", "datetime", "date", "open_time") if c in cols), d.columns[0])
    t = d[tcol]
    num = pd.api.types.is_numeric_dtype(t)
    ts = pd.to_datetime(t, unit="ms", utc=True) if num and t.max() > 1e11 else (
        pd.to_datetime(t, unit="s", utc=True) if num else pd.to_datetime(t, utc=True, errors="coerce"))
    out = pd.DataFrame({k: d[cols.get(k, k)].astype(float).to_numpy() for k in ("open", "high", "low", "close")}, index=ts)
    return out[~out.index.isna()].sort_index()


def intraday_features(bars: pd.DataFrame, when: pd.Series, tf_sec: float) -> pd.DataFrame:
    """ID_FEATS (minus the codes) at each entry, from the last bar whose CLOSE (open + tf) is <= the entry time: close position in the 48-bar range,
    6-bar / 96-bar mean true range, 12-bar log return over the 96-bar return vol x sqrt(12), close / 96-bar high - 1."""
    c, h, lo = bars["close"], bars["high"], bars["low"]
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    lr = np.log(c).diff()
    f = pd.DataFrame({"id_rangepos48": (c - lo.rolling(48).min()) / (h.rolling(48).max() - lo.rolling(48).min()),
                      "id_volburst": tr.rolling(6).mean() / tr.rolling(96).mean(),
                      "id_ret12": np.log(c / c.shift(12)) / (lr.rolling(96).std() * np.sqrt(12)),
                      "id_hi96": c / h.rolling(96).max() - 1})
    close_t = bars.index + pd.Timedelta(seconds=tf_sec)
    idx = close_t.searchsorted(pd.DatetimeIndex(when), side="right") - 1
    out = f.iloc[np.clip(idx, 0, None)].reset_index(drop=True)
    out.loc[idx < 0, :] = np.nan
    out.index = when.index
    return out.replace([np.inf, -np.inf], np.nan)


def daily_closes(csv: Path) -> pd.Series:
    """Daily closes (UTC) from a fetched candle CSV (fetch_backtest_candles output); the time column is the first datetime-like column."""
    d = pd.read_csv(csv)
    cols = {c.lower(): c for c in d.columns}
    tcol = next((cols[c] for c in ("timestamp", "time", "datetime", "date", "open_time") if c in cols), d.columns[0])
    t = d[tcol]
    num = pd.api.types.is_numeric_dtype(t)
    ts = pd.to_datetime(t, unit="ms", utc=True) if num and t.max() > 1e11 else (
        pd.to_datetime(t, unit="s", utc=True) if num else pd.to_datetime(t, utc=True, errors="coerce"))
    c = d[cols.get("close", "close")].astype(float)
    return pd.Series(c.to_numpy(), index=ts).dropna().sort_index().resample("1D").last().dropna()


def symbol_cell(close: pd.Series, when: pd.Series) -> pd.Series:
    """Cell of the traded symbol at each entry: last daily close strictly before the entry DAY."""
    sma = close.rolling(50).mean()
    rv = np.log(close).diff().rolling(20).std()
    med = rv.rolling(365, min_periods=180).median()
    st = pd.DataFrame({"up": close > sma, "hv": rv > med, "ok": sma.notna() & med.notna()})
    st.index = st.index + pd.Timedelta(days=1)                  # a day's state is usable from the NEXT day on
    idx = st.index.searchsorted(when.dt.floor("D").to_numpy(), side="right") - 1
    out = []
    for i in idx:
        if i < 0 or not st.ok.iloc[i]:
            out.append(None)
        else:
            out.append(f"{'up' if st.up.iloc[i] else 'dn'}_{'hv' if st.hv.iloc[i] else 'lv'}")
    return pd.Series(out, index=when.index)


def fetch_btc_closes(btc_cfg: Dict[str, Any], work: Path) -> Optional[pd.Series]:
    """The market ANCHOR's daily closes for the state features (BTC for crypto; SPY for --universe equities) when the population has no leg on the
    anchor symbol; None (anchor features NaN, recorded) if the fetch fails."""
    import exit_lever_ablation as ela
    csv = work / "_btc_state.csv"
    try:
        ela.fetch_candles("btc_state", btc_cfg, FETCH_DAYS, str(csv), non_crypto_source=NON_CRYPTO_SOURCE)
        return daily_closes(csv)
    except (subprocess.CalledProcessError, ValueError, OSError) as e:  # allow-silent: grade_metastate records btc_state "absent (NaN features)" in the measurement
        print(json.dumps({"btc_state_fetch": "failed", "why": f"{type(e).__name__}: {e}"[:200]}), flush=True)
        return None


def state_features(close: pd.Series, when: pd.Series, prefix: str) -> pd.DataFrame:
    """Continuous daily state of ``close`` at each entry, from the last daily close strictly before the entry DAY (shifted a day, as symbol_cell):
    close / SMA50 - 1, close / SMA200 - 1, 20d and 5d log return, 20d realised vol / its 365d median, 5d / 20d realised vol, close / 20d high - 1."""
    lc = np.log(close)
    rv20 = lc.diff().rolling(20).std()
    f = pd.DataFrame({f"{prefix}_sma50": close / close.rolling(50).mean() - 1, f"{prefix}_sma200": close / close.rolling(200).mean() - 1,
                      f"{prefix}_ret20": lc.diff(20), f"{prefix}_ret5": lc.diff(5),
                      f"{prefix}_rv_ratio": rv20 / rv20.rolling(365, min_periods=180).median(),
                      f"{prefix}_rv5_20": lc.diff().rolling(5).std() / rv20, f"{prefix}_hi20": close / close.rolling(20).max() - 1})
    f.index = f.index + pd.Timedelta(days=1)                    # a day's state is usable from the NEXT day on
    idx = f.index.searchsorted(when.dt.floor("D").to_numpy(), side="right") - 1
    out = f.iloc[np.clip(idx, 0, None)].reset_index(drop=True)
    out.loc[idx < 0, :] = np.nan
    out.index = when.index
    return out


def intraday_frame(tr: pd.DataFrame, bars: Dict[str, pd.DataFrame], tf: Dict[str, float]) -> pd.DataFrame:
    """ID_FEATS per trade: the leg's own-timeframe state at entry plus direction / leg / family codes (as metastate_frame)."""
    X = pd.DataFrame(index=tr.index, columns=ID_FEATS, dtype=float)
    for leg, g in tr.groupby("family"):
        if leg in bars:
            X.loc[g.index, [c for c in ID_FEATS if c.startswith("id_")]] = intraday_features(bars[leg], g.ts, tf[leg]).to_numpy()
    X["dir"] = np.where(tr.direction.str.lower().isin(["long", "buy"]), 1.0, -1.0)
    X["leg"] = tr.family.map({k: i for i, k in enumerate(sorted(tr.family.unique()))}).astype(float)
    X["fam"] = tr.get("harness", pd.Series("", index=tr.index)).map({k: i for i, k in enumerate(FAMILIES)}).astype(float)
    return X


def metastate_frame(tr: pd.DataFrame, closes: Dict[str, pd.Series], btc: Optional[pd.Series]) -> pd.DataFrame:
    """MS_FEATS per trade: own-symbol state, BTC state (NaN when no BTC series), direction (+1 long / -1 short), leg and family codes."""
    X = pd.DataFrame(index=tr.index, columns=MS_FEATS, dtype=float)
    for leg, g in tr.groupby("family"):
        if leg in closes:
            X.loc[g.index, [c for c in MS_FEATS if c.startswith("own_")]] = state_features(closes[leg], g.ts, "own").to_numpy()
    if btc is not None and len(btc):
        X.loc[:, [c for c in MS_FEATS if c.startswith("btc_")]] = state_features(btc, tr.ts, "btc").to_numpy()
    X["dir"] = np.where(tr.direction.str.lower().isin(["long", "buy"]), 1.0, -1.0)
    legs = {k: i for i, k in enumerate(sorted(tr.family.unique()))}
    X["leg"] = tr.family.map(legs).astype(float)
    fam = {k: i for i, k in enumerate(FAMILIES)}
    X["fam"] = tr.get("harness", pd.Series("", index=tr.index)).map(fam).astype(float)
    return X


def metastate_raw(tr: pd.DataFrame, X: pd.DataFrame, test_start: str, feats: Optional[List[str]] = None,
                  kind: str = "tilt") -> Tuple[np.ndarray, Dict[str, Any]]:
    """Walk-forward by calendar year from ``test_start``: fit a LightGBM regressor on net_r (clipped at +-MS_CLIP_R) over the trades that EXITED
    before Jan 1 of the year, predict that year's entries, TILT up (RR.TILT[0]) above the training predictions' 2/3 quantile and down below the 1/3
    quantile, else 1. Trades before ``test_start`` keep 1 (they are training only). ``kind="filter"``: 0 (skip) below the 1/3 quantile, else 1."""
    import lightgbm as lgb
    raw = np.ones(len(tr))
    info: Dict[str, Any] = {}
    y = tr.net_r.clip(-MS_CLIP_R, MS_CLIP_R).to_numpy(float)
    feats = feats or MS_FEATS
    Xv = X[feats].to_numpy(float)
    years = sorted(int(v) for v in tr.ts[tr.ts >= pd.Timestamp(test_start, tz="UTC")].dt.year.unique())
    for yr in years:
        cut = pd.Timestamp(f"{yr}-01-01", tz="UTC")
        lo = max(cut, pd.Timestamp(test_start, tz="UTC"))
        trn = np.flatnonzero((tr.xts < cut).to_numpy() & (tr.ts < cut).to_numpy())
        tst = np.flatnonzero(((tr.ts >= lo) & (tr.ts < pd.Timestamp(f"{yr + 1}-01-01", tz="UTC"))).to_numpy())
        if len(trn) < MS_MIN_TRAIN or not len(tst):
            info[str(yr)] = {"n_train": int(len(trn)), "n_test": int(len(tst)), "skipped": "train < MS_MIN_TRAIN" if len(trn) < MS_MIN_TRAIN else "no test"}
            continue
        m = lgb.LGBMRegressor(objective="huber", **MS_LGB)
        m.fit(Xv[trn], y[trn], categorical_feature=[feats.index("leg"), feats.index("fam")])
        # provenance: predict -- the model's predicted net R per trade; training-row predictions only set the tercile cuts
        p_tr, p_te = m.predict(Xv[trn]), m.predict(Xv[tst])
        q1, q2 = np.quantile(p_tr, [1 / 3, 2 / 3])
        raw[tst] = (np.where(p_te < q1, 0.0, 1.0) if kind == "filter"
                    else np.where(p_te > q2, RR.TILT[0], np.where(p_te < q1, RR.TILT[1], 1.0)))
        info[str(yr)] = {"n_train": int(len(trn)), "n_test": int(len(tst)), "q1": round(float(q1), 5), "q2": round(float(q2), 5),
                         "corr_pred_r_test": round(float(np.corrcoef(p_te, y[tst])[0, 1]), 4) if len(tst) > 2 and np.std(p_te) > 0 else None}
    return raw, info


def tradestate_raw(tr: pd.DataFrame) -> np.ndarray:
    """Per trade: TILT by the sign of the mean net R of the same leg x direction x cell trades that EXITED before this entry (>= TS_MIN_N)."""
    raw = np.ones(len(tr))
    for _, g in tr.groupby(["family", "direction"]):
        g = g.sort_values("ts")
        for pos, (i, row) in enumerate(g.iterrows()):
            if row.cell is None:
                continue
            prior = g[(g.cell == row.cell) & (g.xts < row.ts)]
            if len(prior) >= TS_MIN_N:
                raw[tr.index.get_loc(i)] = RR.TILT[0] if prior.net_r.mean() > 0 else RR.TILT[1]
    return raw


def ts_weights(tr: pd.DataFrame, raw: np.ndarray) -> np.ndarray:
    key = tr.family + "|" + tr.ts.dt.strftime("%Y-%m")
    s = pd.Series(raw, index=tr.index).groupby(key).transform("mean").to_numpy()
    return raw / s


def grade_tradestate(tr: pd.DataFrame, closes: Dict[str, pd.Series], seed: int = RR.SEED) -> Dict[str, Any]:
    tr = tr.copy().reset_index(drop=True)
    cells = pd.Series([None] * len(tr), dtype=object)
    for leg, g in tr.groupby("family"):
        if leg in closes:
            cells.loc[g.index] = symbol_cell(closes[leg], g.ts).to_numpy()
    tr["cell"] = cells
    test = tr[tr.ts >= pd.Timestamp(RR.TEST_START, tz="UTC")]
    raw_all = tradestate_raw(tr)
    t = test.copy()
    raw = raw_all[t.index.to_numpy()]
    t = t.reset_index(drop=True)
    g = grade_raw(t, raw, RULE_TS, seed)
    g["cell_counts_test"] = {str(k): int(v) for k, v in t.cell.value_counts(dropna=False).items()}
    return {"arms": {"tradestate": g}, "verdict": g["verdict"], "n_legs": int(t.family.nunique())}


def grade_metastate(tr: pd.DataFrame, closes: Dict[str, pd.Series], btc: Optional[pd.Series], seed: int = RR.SEED) -> Dict[str, Any]:
    tr = tr.copy().reset_index(drop=True)
    X = metastate_frame(tr, closes, btc)
    raw_all, info = metastate_raw(tr, X, RR.TEST_START)
    keep = (tr.ts >= pd.Timestamp(RR.TEST_START, tz="UTC")).to_numpy()
    t = tr[keep].reset_index(drop=True)
    g = grade_raw(t, raw_all[keep], RULE_MS, seed)
    g["walk_forward"] = info
    g["btc_state"] = "present" if btc is not None and len(btc) else "absent (NaN features)"
    g["feature_coverage"] = {c: round(float(X.loc[keep, c].notna().mean()), 4) for c in MS_FEATS}
    return {"arms": {"metastate": g}, "verdict": g["verdict"], "n_legs": int(t.family.nunique())}


def grade_filter(tr: pd.DataFrame, closes: Dict[str, pd.Series], btc: Optional[pd.Series], seed: int = RR.SEED) -> Dict[str, Any]:
    """ENTRY FILTER: the f1a0-26 frozen recipe (MS_FEATS, MS_LGB, yearly walk-forward), skip the bottom training tercile, no renormalisation."""
    tr = tr.copy().reset_index(drop=True)
    X = metastate_frame(tr, closes, btc)
    raw_all, info = metastate_raw(tr, X, RR.TEST_START, kind="filter")
    keep = (tr.ts >= pd.Timestamp(RR.TEST_START, tz="UTC")).to_numpy()
    t = tr[keep].reset_index(drop=True)
    g = grade_raw(t, raw_all[keep], RULE_FILTER, seed, normalise=False)
    sk = raw_all[keep] == 0.0
    g["skipped"] = {"n": int(sk.sum()), "share": round(float(sk.mean()), 4), "mean_net_r": round(float(t.net_r[sk].mean()), 5) if sk.any() else None,
                    "kept_mean_net_r": round(float(t.net_r[~sk].mean()), 5) if (~sk).any() else None}
    g["per_family"] = {f: {"n": int(m.sum()), "skip_share": round(float(sk[m].mean()), 4),
                           "delta": round(float(-(t.net_r.to_numpy(float)[m & sk]).sum() / max(m.sum(), 1)), 5)}
                       for f in sorted(t.harness.unique()) for m in [(t.harness == f).to_numpy()]} if "harness" in t else {}
    g["walk_forward"] = info
    g["btc_state"] = "present" if btc is not None and len(btc) else "absent (NaN features)"
    return {"arms": {"filter": g}, "verdict": g["verdict"], "n_legs": int(t.family.nunique())}


def grade_intraday(tr: pd.DataFrame, bars: Dict[str, pd.DataFrame], tf: Dict[str, float], seed: int = RR.SEED) -> Dict[str, Any]:
    tr = tr.copy().reset_index(drop=True)
    X = intraday_frame(tr, bars, tf)
    raw_all, info = metastate_raw(tr, X, RR.TEST_START, ID_FEATS)
    keep = (tr.ts >= pd.Timestamp(RR.TEST_START, tz="UTC")).to_numpy()
    t = tr[keep].reset_index(drop=True)
    g = grade_raw(t, raw_all[keep], RULE_ID, seed)
    g["walk_forward"] = info
    g["feature_coverage"] = {c: round(float(X.loc[keep, c].notna().mean()), 4) for c in ID_FEATS}
    return {"arms": {"intraday": g}, "verdict": g["verdict"], "n_legs": int(t.family.nunique())}


def grade_raw(t: pd.DataFrame, raw: np.ndarray, rule: Dict[str, Any], seed: int = RR.SEED, normalise: bool = True) -> Dict[str, Any]:
    """The f1a0-25 grade for any per-trade raw tilt: leg-month renormalised weights, week-bootstrap se, 200 within leg x month permutations.
    ``normalise=False`` (entry filter): weights are the raw 0/1 keep flags, so delta = -(sum of skipped net R) / all trades, and each
    permutation is a random skip of the same count within the same leg x month (the matched-random control)."""
    wf = (lambda x: ts_weights(t, x)) if normalise else (lambda x: np.asarray(x, float))
    w = wf(raw)
    r = t.net_r.to_numpy(float)
    n = len(t)
    delta = float(((w - 1.0) * r).sum() / n)
    wk = t.ts.dt.strftime("%G-%V").to_numpy()
    ws = pd.Series((w - 1.0) * r).groupby(wk).sum()
    wn = pd.Series(np.ones(n)).groupby(wk).sum()
    rng = np.random.default_rng(seed)
    W = len(ws)
    boots = [float(ws.to_numpy()[ix].sum() / wn.to_numpy()[ix].sum()) for ix in (rng.integers(0, W, W) for _ in range(RR.N_BOOT))]
    se = float(np.std(boots))
    key = (t.family + "|" + t.ts.dt.strftime("%Y-%m")).to_numpy()
    groups = [np.flatnonzero(key == k) for k in np.unique(key)]
    draws = []
    for _ in range(RR.N_RANDOM):
        pr = raw.copy()
        for ii in groups:
            pr[ii] = pr[ii][rng.permutation(len(ii))]
        draws.append(float(((wf(pr) - 1.0) * r).sum() / n))
    draws = np.array(draws)
    share = float(np.mean(draws >= delta))
    yrs = {str(y): round(float(((w - 1.0) * r)[t.ts.dt.year.to_numpy() == y].sum() / max((t.ts.dt.year == y).sum(), 1)), 4)
           for y in sorted(t.ts.dt.year.unique())}
    g = {"n_trades": n, "money_base": round(float(r.mean()), 5), "money_arm": round(float((w * r).mean()), 5), "delta": round(delta, 5),
         "se_week_boot": round(se, 5), "t": round(delta / se, 3) if se > 0 else None,
         "random": {"draws": RR.N_RANDOM, "kind": "raw tilts permuted within leg x month", "mean": round(float(draws.mean()), 5),
                    "p95": round(float(np.percentile(draws, 95)), 5), "share_ge_arm": round(share, 4)},
         "yearly_delta": yrs, "share_tilted": round(float((raw != 1.0).mean()), 4), "share_up_tilt": round(float((raw == RR.TILT[0]).mean()), 4)}
    v, g["checks"] = RR.tilt_verdict(g, rule)
    g["verdict"] = v
    return g


def grade(trades: pd.DataFrame, btc: Optional[pd.Series] = None, seed: int = RR.SEED) -> Dict[str, Any]:
    S, N = RR.weekly_books(trades, "family")
    f = RR.features(S, N)
    test_weeks = [w for w in S.index if w >= pd.Timestamp(RR.TEST_START)]
    btc = btc if btc is not None else RR.btc_daily()
    raws = {"nostate": RR.state_raw(f, pd.Series("all", index=S.index)), "advol": RR.state_raw(f, RR.cells_advol(btc, list(S.index))),
            "hmm2": RR.state_raw(f, RR.cells_hmm2(btc, list(S.index))[0])}
    arms, verdicts = {}, {}
    for k, raw in raws.items():
        g = RR.grade_tilt(f, test_weeks, np.random.default_rng(seed), raw_all=raw)
        v, g["checks"] = RR.tilt_verdict(g, RULE)
        g["verdict"] = verdicts[k] = v
        arms[k] = g
    sums = {k: RR.tilt_week_sums(f, test_weeks, r) for k, r in raws.items()}
    decomp = {f"{k}_vs_nostate": RR.paired_delta(sums[k], sums["nostate"], np.random.default_rng(seed + 1)) for k in ("advol", "hmm2")}
    uv = "pass" if "pass" in verdicts.values() else ("fail" if all(v == "fail" for v in verdicts.values()) else "indeterminate")
    return {"arms": arms, "decomp_reported": decomp, "verdict": uv, "n_books": int(S.shape[1]), "n_test_weeks": len(test_weeks)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/rostered_replay")
    ap.add_argument("--work", default="")
    ap.add_argument("--legs", default="")
    ap.add_argument("--unit", default="")
    ap.add_argument("--mode", choices=["book", "tradestate", "metastate", "intraday", "filter", "eventday", "ratesrule", "adxcell"], default="book")
    ap.add_argument("--population", choices=["rostered", "fresh", "fresh2"], default="rostered",
                    help="fresh / fresh2: the rostered configs on FRESH_SYMBOLS / FRESH_SYMBOLS_2 (metastate only; RULE_MS_FRESH / RULE_MS_FRESH2)")
    ap.add_argument("--universe", choices=["crypto", "equities", "all"], default="crypto",
                    help="equities: the rostered non-crypto legs, Dukascopy candles, SPY as the market anchor (filter / metastate; RULE_FILTER_EQ / RULE_MS_EQ)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(a.work) if a.work else out / "work"
    global NON_CRYPTO_SOURCE
    eq = a.universe == "equities"
    if a.universe == "all" and a.mode != "eventday":
        ap.error("--universe all is defined for --mode eventday only")
    if a.mode == "eventday" and a.population != "rostered":
        ap.error("--mode eventday is defined for --population rostered only")
    if a.universe == "all":
        NON_CRYPTO_SOURCE = "dukascopy"
    if eq:
        if a.mode not in ("metastate", "filter", "ratesrule") or a.population != "rostered":
            ap.error("--universe equities is defined for --mode metastate / filter on --population rostered only")
        NON_CRYPTO_SOURCE = "dukascopy"
    cfgs = ({**rostered_legs(universe="crypto"), **rostered_legs(universe="equities")} if a.universe == "all"
            else rostered_legs(universe=a.universe))
    anchor_sym = "SPY" if eq else "BTCUSDT"
    btc_cfg = EQ_ANCHOR if eq else next((v["cfg"] for v in cfgs.values() if v["cfg"]["symbols"][0] == "BTCUSDT"), None)
    if a.population in ("fresh", "fresh2"):
        if a.mode not in ("metastate", "intraday", "filter"):
            ap.error("--population fresh/fresh2 is defined for --mode metastate / intraday only")
        cfgs = fresh_legs(cfgs, FRESH_SYMBOLS if a.population == "fresh" else FRESH_SYMBOLS_2)
    if a.legs:
        cfgs = {k: v for k, v in cfgs.items() if k in set(a.legs.split(","))}
    per = {}
    for leg, c in cfgs.items():
        per[leg] = replay_leg(leg, c["cfg"], work)
        print(json.dumps({"leg": leg, "state": per[leg]["state"], "n": per[leg].get("n")}), flush=True)
    tr = trades_frame(per, cfgs)
    tr = tr[(tr.ts >= pd.Timestamp(WINDOW[0], tz="UTC")) & (tr.ts < pd.Timestamp(WINDOW[1], tz="UTC"))]
    (out / "legs").mkdir(exist_ok=True)
    for leg, r in per.items():
        if r.get("state") == "measured":
            with open(out / "legs" / f"{leg}__trades.jsonl", "w", encoding="utf-8") as fh:
                for t in r["trades"]:
                    fh.write(json.dumps(t, default=str) + "\n")
    if a.mode == "tradestate":
        closes = {leg: daily_closes(work / f"{leg}.csv") for leg, r in per.items() if r.get("state") == "measured" and (work / f"{leg}.csv").exists()}
        m = grade_tradestate(tr, closes) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
        rule_used = RULE_TS
    elif a.mode == "intraday":
        meas = [leg for leg, r in per.items() if r.get("state") == "measured" and (work / f"{leg}.csv").exists()]
        bars = {leg: ohlc_bars(work / f"{leg}.csv") for leg in meas}
        tfs = {leg: tf_seconds(cfgs[leg]["cfg"].get("timeframe")) for leg in meas}
        tr = tr.assign(harness=tr.family.map({k: v["harness"] for k, v in cfgs.items()}))
        m = grade_intraday(tr, bars, tfs) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
        rule_used = RULE_ID
    elif a.mode == "adxcell":
        if not a.legs:
            ap.error("--mode adxcell needs --legs (the legs whose ADX cells are graded)")
        meas = [leg for leg, r in per.items() if r.get("state") == "measured" and (work / f"{leg}.csv").exists()]
        bars = {leg: ohlc_bars(work / f"{leg}.csv") for leg in meas}
        tfs = {leg: tf_seconds(cfgs[leg]["cfg"].get("timeframe")) for leg in meas}
        m = grade_adxcell(tr, bars, tfs, load_cells()) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
        rule_used = RULE_ADX
    elif a.mode == "ratesrule":
        try:
            series = fetch_fred(RATES_SERIES, work / f"fred_{RATES_SERIES}.csv")
        except Exception as exc:  # allow-silent: an unreadable FRED series grades INDETERMINATE with read_state could_not_look, recorded
            print(json.dumps({"fred_fetch": "failed", "series": RATES_SERIES, "why": f"{type(exc).__name__}: {exc}"[:200]}), flush=True)
            series = None
        m = grade_ratesrule(tr, series) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
        rule_used = RULE_RATES
    elif a.mode == "eventday":
        m = grade_eventday(tr, load_releases()) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
        rule_used = RULE_EV
    elif a.mode in ("metastate", "filter"):
        closes = {leg: daily_closes(work / f"{leg}.csv") for leg, r in per.items() if r.get("state") == "measured" and (work / f"{leg}.csv").exists()}
        btc_leg = next((leg for leg in sorted(closes) if cfgs[leg]["cfg"]["symbols"][0] == anchor_sym and str(cfgs[leg]["cfg"].get("timeframe")) == "1d"),
                       None) if eq else next((leg for leg in sorted(closes) if cfgs[leg]["cfg"]["symbols"][0] == "BTCUSDT"), None)
        btc = closes.get(btc_leg)
        if btc is None and btc_cfg is not None:                    # fresh population: no BTC leg in it, so fetch BTC on the rostered BTC leg's timeframe
            btc = fetch_btc_closes(btc_cfg, work)
        tr = tr.assign(harness=tr.family.map({k: v["harness"] for k, v in cfgs.items()}))
        gfn = grade_filter if a.mode == "filter" else grade_metastate
        m = gfn(tr, closes, btc) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
        rule_used = ((RULE_FILTER_EQ if eq else RULE_FILTER) if a.mode == "filter"
                     else (RULE_MS_EQ if eq else {"fresh": RULE_MS_FRESH, "fresh2": RULE_MS_FRESH2}.get(a.population, RULE_MS)))
    else:
        m = grade(tr) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
        rule_used = RULE
    legs_report = {k: {x: v[x] for x in v if x != "trades"} | {"book": cfgs[k]["book"], "harness": cfgs[k]["harness"]} for k, v in per.items()}
    fsyms = {"fresh": FRESH_SYMBOLS, "fresh2": FRESH_SYMBOLS_2}.get(a.population)
    what = (f"rostered crypto leg configs on the FRESH symbols {'/'.join(fsyms)} (leg@symbol)" if fsyms
            else ("rostered NON-crypto legs (ETFs / micro futures; Dukascopy candles, proxies recorded per leg; anchor SPY daily)" if eq
                  else ("ALL rostered legs (crypto via the evidence builder's feed + non-crypto via Dukascopy)" if a.universe == "all" else "rostered crypto legs")))
    pop = (f"{sum(1 for v in per.values() if v.get('state') == 'measured')} of {len(per)} {what} ({'/'.join(FAMILIES)} harnesses) "
           f"replayed with DECLARED params over {WINDOW[0]}..{WINDOW[1]} ({len(tr)} trades, harness net_r full cost stack); books = leg x direction; "
           f"test weeks {RR.TEST_START}..{WINDOW[1]}")
    why = "; ".join(f"{k}: {g['verdict']} delta {g['delta']:+.4f} t {g['t']} share {g['random']['share_ge_arm']}" for k, g in (m.get("arms") or {}).items())
    if not why and m.get("why"):
        why = str(m["why"])
    summ = {"schema": "rostered_leg_replay/1", "unit": a.unit, "mode": a.mode, "population_kind": a.population, "universe": a.universe, "verdict": m["verdict"], "why": why, "rule": rule_used, "population": pop,
            "window": WINDOW, "legs": legs_report, "measurement": m, "git_sha": RR._git_sha(), "elapsed_s": round(time.time() - t0), "read_state": "measured"}
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=str) + "\n")
    (out / "verdict.json").write_text(json.dumps({"verdict": m["verdict"], "read_state": "measured", "n": int(len(tr)), "note": why, "population": pop,
                                                  "rule": rule_used, "data_window": {"start": WINDOW[0], "end": WINDOW[1], "legs": sorted(per)},
                                                  "measurement": m}, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": m["verdict"], "why": why}), flush=True)
    return 0


def _self_test() -> int:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")

    legs = rostered_legs()
    check("rostered legs found in the four families", len(legs) >= 10 and all(v["harness"] in FAMILIES for v in legs.values()))
    check("every rostered leg is a crypto symbol", all(str(v["cfg"]["symbols"][0]).endswith("USDT") for v in legs.values()))
    eql = rostered_legs(universe="equities")
    check("equities universe: rostered non-crypto legs in the families, disjoint from crypto",
          len(eql) >= 5 and not any(str(v["cfg"]["symbols"][0]).endswith("USDT") for v in eql.values()) and not set(eql) & set(legs)
          and all(v["harness"] in FAMILIES for v in eql.values()))
    per = {"L1": {"state": "measured", "trades": [{"entry_time": "2023-01-02 00:00:00", "direction": "long", "net_r": 1.0}]},
           "L2": {"state": "harness_failed"}}
    tf = trades_frame(per, {"L1": {"cfg": {"symbols": ["BTCUSDT"], "timeframe": "1h"}}, "L2": {"cfg": {"symbols": ["X"]}}})
    check("trades frame keeps measured legs only, family = leg", list(tf.family) == ["L1"] and tf.net_r.iloc[0] == 1.0)
    # the grade runs the router on leg books: a synthetic BTC-trend-conditioned edge must be found by advol
    days = pd.date_range("2019-01-01", "2026-10-26", freq="1D", tz="UTC")
    rng = np.random.default_rng(5)
    regime = np.repeat(rng.choice([1.0, -1.0], size=len(days) // 60 + 1), 60)[:len(days)]
    btc = pd.Series(100 * np.exp(np.cumsum(0.004 * regime + rng.normal(0, 0.01, len(days)))), index=days)
    syn = RR._synthetic(persistent=False)
    up = btc > btc.rolling(50).mean()
    st = up.reindex(syn.ts.dt.floor("D")).fillna(False).to_numpy()
    syn = syn.assign(net_r=syn.net_r + 0.3 * np.where(syn.direction == "long", 1.0, -1.0) * np.where(st, 1.0, -1.0))
    g = grade(syn, btc=btc)
    check("grade: advol finds a trend-conditioned edge on leg books", g["arms"]["advol"]["delta"] > 0.02 and g["arms"]["advol"]["random"]["share_ge_arm"] <= 0.05)
    check("grade: decomp reported", "advol_vs_nostate" in g["decomp_reported"])
    # tradestate: a leg whose edge sign follows its OWN symbol's trend must be found; and the prior uses EXITED trades only
    sym = pd.Series(100 * np.exp(np.cumsum(0.004 * regime + rng.normal(0, 0.01, len(days)))), index=days)
    ents = pd.date_range("2020-09-02", "2026-10-20", freq="13h", tz="UTC")
    upx = (sym > sym.rolling(50).mean()).shift(1).reindex(ents.floor("D")).fillna(False).to_numpy()
    r0 = rng.normal(0, 1, len(ents)) + np.where(upx, 0.3, -0.3)
    trd = pd.DataFrame({"family": "L", "symbol": "S", "tf": "1h", "entry_time": ents.astype(str), "direction": "long", "net_r": r0,
                        "exit_time": (ents + pd.Timedelta(hours=10)).astype(str), "ts": ents, "xts": ents + pd.Timedelta(hours=10)})
    gt = grade_tradestate(trd, {"L": sym})
    check("tradestate: an own-symbol trend edge is found and beats the permutation control",
          gt["arms"]["tradestate"]["delta"] > 0.02 and gt["arms"]["tradestate"]["random"]["share_ge_arm"] <= 0.05)
    tiny = trd.iloc[:30].copy()
    tiny["xts"] = tiny.ts + pd.Timedelta(days=3650)              # nothing exits before any later entry
    tiny["cell"] = "up_lv"
    check("tradestate: a trade still open is never in a prior", (tradestate_raw(tiny.reset_index(drop=True)) == 1.0).all())
    # metastate: an edge that follows the BTC trend (not the own symbol) must be found by the walk-forward model; shuffled R must not pass
    upb = (btc > btc.rolling(50).mean()).shift(1).reindex(ents.floor("D")).fillna(False).to_numpy()
    r1 = rng.normal(0, 1, len(ents)) + np.where(upb, 0.5, -0.5)
    trm = trd.assign(net_r=r1, harness="trend")
    gm = grade_metastate(trm, {"L": sym}, btc)["arms"]["metastate"]
    check("metastate: a BTC-trend edge is found and beats the permutation control", gm["delta"] > 0.02 and gm["random"]["share_ge_arm"] <= 0.05)
    gn = grade_metastate(trm.assign(net_r=rng.permutation(r1)), {"L": sym}, btc)["arms"]["metastate"]
    check("metastate: shuffled R does not pass", gn["verdict"] != "pass")
    X = metastate_frame(trm.iloc[:5].reset_index(drop=True), {"L": sym}, btc)
    d0 = trm.ts.iloc[0].floor("D")
    exp = sym[sym.index < d0].iloc[-1] / sym[sym.index < d0].iloc[-50:].mean() - 1
    check("metastate: own_sma50 is the last close strictly before the entry day", abs(X.own_sma50.iloc[0] - exp) < 1e-9)
    fl = fresh_legs({"L1": {"cfg": {"symbols": ["BNBUSDT"], "timeframe": "4h"}, "book": "money", "harness": "trend"},
                     "L2": {"cfg": {"symbols": ["ETHUSDT"], "timeframe": "1h"}, "book": "demo_floor", "harness": "fade"}})
    check("fresh: every leg on every FRESH symbol it does not already trade, own symbol skipped",
          sorted(fl) == sorted([f"L1@{x}" for x in FRESH_SYMBOLS if x != "BNBUSDT"] + [f"L2@{x}" for x in FRESH_SYMBOLS])
          and fl["L2@DOGEUSDT"]["cfg"] == {"symbols": ["DOGEUSDT"], "timeframe": "1h"} and fl["L1@LTCUSDT"]["harness"] == "trend")
    check("fresh: no FRESH symbol is traded by a rostered leg", not ({v["cfg"]["symbols"][0] for v in legs.values()} & set(FRESH_SYMBOLS)))
    check("fresh2: disjoint from the rostered symbols AND from FRESH_SYMBOLS",
          not ({v["cfg"]["symbols"][0] for v in legs.values()} & set(FRESH_SYMBOLS_2)) and not (set(FRESH_SYMBOLS) & set(FRESH_SYMBOLS_2)))
    # intraday: features come from the last bar CLOSED at or before entry (no lookahead), and an injected range-position edge is found
    hb = pd.date_range("2020-09-01", periods=24 * 2000, freq="1h", tz="UTC")
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(hb))))
    bars = pd.DataFrame({"open": px, "high": px * 1.004, "low": px * 0.996, "close": px}, index=hb)
    e1 = pd.Series([hb[500] + pd.Timedelta(minutes=30), hb[500] + pd.Timedelta(hours=1)])
    f1 = intraday_features(bars, e1, 3600.0)
    full = intraday_features(bars, pd.Series(hb[[499, 500]] + pd.Timedelta(hours=1)), 3600.0)
    check("intraday: an entry inside bar k reads bar k-1; at bar k's close it reads bar k",
          np.allclose(f1.iloc[0].to_numpy(), full.iloc[0].to_numpy(), equal_nan=True) and np.allclose(f1.iloc[1].to_numpy(), full.iloc[1].to_numpy(), equal_nan=True))
    ents2 = hb[200::13][:3000] + pd.Timedelta(hours=1)
    rp = intraday_features(bars, pd.Series(ents2), 3600.0)["id_rangepos48"].to_numpy()
    r2 = rng.normal(0, 1, len(ents2)) + np.where(rp > 0.5, 0.6, -0.6)
    tri = pd.DataFrame({"family": "L", "direction": "long", "net_r": r2, "ts": ents2, "xts": ents2 + pd.Timedelta(hours=10), "harness": "trend"})
    gi = grade_intraday(tri, {"L": bars}, {"L": 3600.0})["arms"]["intraday"]
    check("intraday: an injected range-position edge is found and beats the permutation control", gi["delta"] > 0.02 and gi["random"]["share_ge_arm"] <= 0.05)
    check("intraday: tf parse", tf_seconds("4h") == 14400.0 and tf_seconds("15m") == 900.0)
    # filter: skipping the predicted-bad tercile of a BTC-trend edge is found; shuffled R does not pass; the arithmetic is -(skipped R)/n
    gf = grade_filter(trm, {"L": sym}, btc)["arms"]["filter"]
    check("filter: a BTC-trend edge's bad tercile is skipped and the skip beats random skips of the same count",
          gf["delta"] > 0.02 and gf["random"]["share_ge_arm"] <= 0.05 and 0.2 < gf["skipped"]["share"] < 0.65 and gf["skipped"]["mean_net_r"] < 0)
    gfn = grade_filter(trm.assign(net_r=rng.permutation(r1)), {"L": sym}, btc)["arms"]["filter"]
    check("filter: shuffled R does not pass", gfn["verdict"] != "pass")
    tt = trm.iloc[:400].reset_index(drop=True)
    kf = np.r_[np.zeros(100), np.ones(300)]
    ga = grade_raw(tt, kf, RULE_FILTER, normalise=False)
    check("filter: delta = -(sum of skipped net R) / n, no renormalisation",
          abs(ga["delta"] - (-tt.net_r.iloc[:100].sum() / 400)) < 1e-4 and abs(ga["money_arm"] - tt.net_r.iloc[100:].sum() / 400) < 1e-4)
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
