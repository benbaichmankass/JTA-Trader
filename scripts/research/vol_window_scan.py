#!/usr/bin/env python3
# wiring: research/queue/RQ-20261031-28bf-01 run.command via research-script-run.yml (programme 07 TIMEFRAMES, row VOL-WINDOW-RESEARCH)
"""Stage A of VOL-WINDOW-RESEARCH: which repeatable clock windows are (1) volatile versus the symbol's own baseline,
stably, and (2) directionally predictable EARLY in the window, net of the full cost stack?

WHY A NEW SCRIPT. No cost-complete clock/window harness exists (row IR-INTRADAY-SEASONALITY-HARNESS is a queued build; the
only opening-range harness, scripts/backtest_orb.py, is fee-only and EXCLUDED from every corpus by CLAUDE.md D1). This
driver reads 5-minute candles through the same public lanes the other research harnesses use
(`scripts/ops/fetch_backtest_candles.py`: Binance Vision for *USDT perps as the proxy for Bybit linear; Dukascopy or Yahoo
for ETFs / futures proxies) and charges the repo's ONE cost definition (`src/runtime/execution_costs`: venue fee,
venue slippage, perp funding per 8h boundary crossed). It never imports backtest_orb.py or src/backtest/backtester.py.

THE DESIGN (fixed by the unit's decision_rule; nothing here is tuned after a result)
  windows    anchors x lengths {15,30,60} min, plus the 168 hour-of-week slots (60 min, UTC):
             us_open 09:30 ET, us_close (window ENDS 16:00 ET), globex_open 18:00 ET, london_open 08:00 London,
             asia_open_00z (09:00 JST == 00:00Z == funding 00Z, one cell not two), funding_08z, funding_16z. DST-aware
             through zoneinfo. One occurrence per day; a day with a gap in the window's 5m bars is skipped.
  vol ratio  RMS of the window's 5m log-returns / RMS over ALL aligned same-length windows of the same symbol, per fold.
  rules      (all enter at the open of the bar AFTER the signal, exit at the window's last close; one trade a day)
             C5 / C15  follow the sign of the first 5 / 15 minutes      F5 / F15  fade it (the mirror)
             O15       break of the first-15-minute range (first 5m CLOSE beyond it), L >= 30 only
  R unit     the trailing median (previous 20 occurrences, causal) of that window's high-low range in bps. Net R =
             (gross bps - fee - slippage - funding) / R. Stop-less time exit, so R is a SCALE, not a risk stop; the
             statistic is graded on net R and reported in bps too.
  folds      K=6 calendar folds of [start,end). Folds 1-3 = DISCOVERY, 4-6 = CONFIRMATION (held out). +-1 day embargo
             at every fold edge (windows are intraday and independent across days, so this is the whole purge).
  gate V     vol ratio >= theta in >= 2 of 3 discovery folds AND >= 2 of 3 confirmation folds (>= 4 of 6, both halves).
  shortlist  gate V AND discovery n >= n_floor AND discovery mean net R > 0 with one-sided p <= 0.05 (UNCORRECTED).
  qualify    shortlisted AND confirmation n >= n_floor AND the Bonferroni-over-the-shortlist lower confidence bound of
             confirmation mean net R > 0 (one-sided alpha / M, M = shortlist size) AND >= 2 of 3 confirmation folds net > 0.
             Reported beside it: the SAME test at M = every (symbol, window, rule) cell evaluated (the conservative
             sensitivity), the expected number of uncorrected shortlist false positives, and a 2x-cost stress.
  verdict    pass iff >= 1 qualifying cell; fail iff none (and the crypto core measured); indeterminate otherwise.

A symbol with no usable candles is NAMED in `symbols_without_data` and skipped; nothing is fabricated or substituted.
A pass is a LEAD that opens programme nodes (Stage-0 strategy, ML direction head, desk wake); never a roster act.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts"), str(REPO)]

BAR_S = 300
LENGTHS = (15, 30, 60)
RULES = ("C5", "C15", "F5", "F15", "O15")
# (name, tz, hour, minute, mode, weekdays-in-LOCAL-tz (0=Mon) or None for every day)
ANCHORS = (
    ("us_open", "America/New_York", 9, 30, "start", (0, 1, 2, 3, 4)),
    ("us_close", "America/New_York", 16, 0, "end", (0, 1, 2, 3, 4)),
    ("globex_open", "America/New_York", 18, 0, "start", (6, 0, 1, 2, 3)),
    ("london_open", "Europe/London", 8, 0, "start", (0, 1, 2, 3, 4)),
    ("asia_open_00z", "UTC", 0, 0, "start", None),
    ("funding_08z", "UTC", 8, 0, "start", None),
    ("funding_16z", "UTC", 16, 0, "start", None),
)
DOW = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CORE_PERPS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT")
DEFAULT_SYMBOLS = CORE_PERPS + ("SPY", "QQQ", "GLD", "SLV", "USO", "IAUM", "MES", "MGC")
ND = NormalDist()


# ---- data ------------------------------------------------------------------------------------------------------
def load_bars(path: Path) -> dict[str, np.ndarray]:
    df = pd.read_csv(path)
    col = "timestamp" if "timestamp" in df.columns else df.columns[0]
    ts = pd.to_datetime(df[col], utc=True, format="mixed", errors="coerce")
    ok = ts.notna().to_numpy()
    df = df.loc[ok].copy()
    ts = ts[ok]
    t = (ts.astype("int64") // 10**9).to_numpy() if ts.dt.tz is not None else ts.astype("int64").to_numpy() // 10**9
    # pandas >= 2 stores datetime64[ns/us]; normalise to epoch seconds explicitly
    t = np.asarray(ts.dt.as_unit("s").astype("int64"), dtype=np.int64) if hasattr(ts.dt, "as_unit") else t
    o = np.argsort(t, kind="stable")
    t = t[o]
    keep = np.concatenate(([True], np.diff(t) > 0))
    cols = {k: df[k].to_numpy(dtype=float)[o][keep] for k in ("open", "high", "low", "close")}
    cols["ts"] = t[keep]
    return cols


def _starts_for_anchor(anchor: tuple, length_min: int, d0: date, d1: date) -> np.ndarray:
    _name, tzname, hh, mm, mode, wdays = anchor
    tz = ZoneInfo(tzname)
    out: list[int] = []
    d = d0
    while d <= d1:
        if wdays is None or d.weekday() in wdays:
            loc = datetime.combine(d, time(hh, mm), tzinfo=tz)
            u = loc.astimezone(timezone.utc)
            if mode == "end":
                u = u - timedelta(minutes=length_min)
            out.append(int(u.timestamp()))
        d += timedelta(days=1)
    return np.asarray(out, dtype=np.int64)


def _starts_how(dow: int, hour: int, d0: date, d1: date) -> np.ndarray:
    d = d0
    while d.weekday() != dow:
        d += timedelta(days=1)
    out = []
    while d <= d1:
        out.append(int(datetime.combine(d, time(hour, 0), tzinfo=timezone.utc).timestamp()))
        d += timedelta(days=7)
    return np.asarray(out, dtype=np.int64)


def window_specs(anchors: tuple[str, ...] | None, how: bool, d0: date, d1: date):
    """Yield (name, length_min, starts_utc_epoch)."""
    for a in ANCHORS:
        if anchors is not None and a[0] not in anchors:
            continue
        for L in LENGTHS:
            yield a[0], L, _starts_for_anchor(a, L, d0, d1)
    if how:
        for dw in range(7):
            for h in range(24):
                yield f"how_{DOW[dw]}_{h:02d}z", 60, _starts_how(dw, h, d0, d1)


def extract(bars: dict[str, np.ndarray], starts: np.ndarray, nb: int) -> dict[str, np.ndarray] | None:
    """Matrices (days x nb) for the windows whose nb bars are ALL present and contiguous; else dropped."""
    ts = bars["ts"]
    if len(starts) == 0 or len(ts) == 0:
        return None
    i = np.searchsorted(ts, starts)
    ok = i + nb <= len(ts)
    i = np.where(ok, i, 0)
    ok &= ts[i] == starts
    last = np.where(ok, i + nb - 1, 0)
    ok &= ts[last] == starts + (nb - 1) * BAR_S
    if not ok.any():
        return None
    ii = i[ok][:, None] + np.arange(nb)[None, :]
    return {"start": starts[ok], "O": bars["open"][ii], "H": bars["high"][ii], "L": bars["low"][ii], "C": bars["close"][ii]}


def rv2(w: dict[str, np.ndarray]) -> np.ndarray:
    return (np.log(w["C"] / w["O"]) ** 2).sum(axis=1)


# ---- costs (the repo's ONE definition) ---------------------------------------------------------------------------
def cost_policy(symbol: str) -> dict[str, Any]:
    from src.runtime import execution_costs as ec
    slip, fund = ec.resolve_cost_policy(symbol)
    return {"fee_bps_rt": ec.resolve_fee_bps_roundtrip(symbol), "slip_bps_rt": slip, "funding_bps_per_window": fund,
            "perp": bool(ec.is_perp(symbol)), "window_h": float(ec.FUNDING_WINDOW_HOURS)}


def funding_crossed(entry: np.ndarray, exit_: np.ndarray, window_h: float) -> np.ndarray:
    w = window_h * 3600.0
    return np.floor(exit_ / w) - np.floor(entry / w)


# ---- stats -------------------------------------------------------------------------------------------------------
def mean_sd(x: np.ndarray) -> tuple[int, float, float]:
    n = len(x)
    if n == 0:
        return 0, float("nan"), float("nan")
    return n, float(np.mean(x)), float(np.std(x, ddof=1)) if n > 1 else float("nan")


def one_sided_p(n: int, mean: float, sd: float) -> float:
    """P(mean this large | true mean 0). Normal approximation: every graded n is >= n_floor (>= 100)."""
    if n < 2 or not sd or math.isnan(sd) or sd <= 0:
        return float("nan")
    return 1.0 - ND.cdf(mean / (sd / math.sqrt(n)))


def lower_bound(n: int, mean: float, sd: float, alpha_one_sided: float) -> float:
    if n < 2 or not sd or math.isnan(sd):
        return float("nan")
    return mean - ND.inv_cdf(1.0 - alpha_one_sided) * sd / math.sqrt(n)


# ---- trades for one window ---------------------------------------------------------------------------------------
def rule_trades(w: dict[str, np.ndarray], rule: str, nb: int) -> dict[str, np.ndarray] | None:
    """Per-day (side, entry_price, entry_epoch) for `rule`; days with no signal are absent. None if the rule needs more bars."""
    O, H, L, C, st = w["O"], w["H"], w["L"], w["C"], w["start"]
    if rule in ("C5", "F5"):
        if nb < 2:
            return None
        sig = np.sign(C[:, 0] / O[:, 0] - 1.0)
        side = sig if rule == "C5" else -sig
        k = np.full(len(st), 1)
    elif rule in ("C15", "F15"):
        if nb < 4:
            return None
        sig = np.sign(C[:, 2] / O[:, 0] - 1.0)
        side = sig if rule == "C15" else -sig
        k = np.full(len(st), 3)
    elif rule == "O15":
        if nb < 5:
            return None
        hi, lo = H[:, :3].max(axis=1), L[:, :3].min(axis=1)
        js = np.arange(3, nb - 1)
        up = C[:, js] > hi[:, None]
        dn = C[:, js] < lo[:, None]
        brk = up | dn
        has = brk.any(axis=1)
        first = brk.argmax(axis=1)
        jj = js[first]
        rows = np.arange(len(st))
        side = np.where(up[rows, first], 1.0, -1.0) * has
        k = jj + 1
    else:
        raise ValueError(rule)
    m = side != 0
    rows = np.arange(len(st))
    return {"side": side[m], "entry": O[rows, k][m], "entry_t": (st + k * BAR_S)[m], "idx": rows[m]}


def window_cells(sym: str, name: str, L: int, w: dict[str, np.ndarray], cost: dict[str, Any], fold_of, edges: np.ndarray,
                 rules: tuple[str, ...], embargo_s: int, k_folds: int) -> list[dict[str, Any]]:
    nb = L // 5
    st = w["start"]
    rng_bps = (w["H"].max(axis=1) - w["L"].min(axis=1)) / w["O"][:, 0] * 1e4
    rmed = pd.Series(rng_bps).shift(1).rolling(20, min_periods=20).median().to_numpy()  # causal: previous 20 occurrences
    exit_px = w["C"][:, -1]
    exit_t = st + nb * BAR_S
    cells = []
    for rule in rules:
        tr = rule_trades(w, rule, nb)
        if tr is None or len(tr["side"]) == 0:
            continue
        idx = tr["idx"]
        gross = tr["side"] * (exit_px[idx] / tr["entry"] - 1.0) * 1e4
        fund = (funding_crossed(tr["entry_t"].astype(float), exit_t[idx].astype(float), cost["window_h"])
                * cost["funding_bps_per_window"]) if cost["perp"] else np.zeros(len(idx))
        base = cost["fee_bps_rt"] + cost["slip_bps_rt"]
        net = gross - base - fund
        net2 = gross - 2.0 * (base + fund)
        R = rmed[idx]
        fold = fold_of(st[idx])
        near_edge = np.min(np.abs(st[idx][:, None] - edges[None, :]), axis=1) < embargo_s
        use = (~near_edge) & (fold >= 0) & np.isfinite(R) & (R > 0)
        if not use.any():
            continue
        nr, nr2, nbps, fo = net[use] / R[use], net2[use] / R[use], net[use], fold[use]
        row = {"symbol": sym, "window": name, "length_min": L, "rule": rule,
               "n_by_fold": [int((fo == f).sum()) for f in range(k_folds)],
               "mean_net_r_by_fold": [float(nr[fo == f].mean()) if (fo == f).any() else None for f in range(k_folds)],
               "_nr": nr, "_nr2": nr2, "_nbps": nbps, "_fold": fo}
        cells.append(row)
    return cells


def vol_by_fold(w: dict[str, np.ndarray], fold_of, k_folds: int) -> np.ndarray:
    f = fold_of(w["start"])
    r = rv2(w)
    return np.array([r[f == k].mean() if (f == k).any() else np.nan for k in range(k_folds)])


# ---- scan --------------------------------------------------------------------------------------------------------
def scan_symbol(sym: str, bars: dict[str, np.ndarray], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    k_folds = cfg["folds"]
    t0, t1 = cfg["t0"], cfg["t1"]
    span = (t1 - t0) / k_folds
    edges = t0 + span * np.arange(1, k_folds)

    def fold_of(s: np.ndarray) -> np.ndarray:
        f = np.floor((s - t0) / span).astype(int)
        return np.where((s >= t0) & (s < t1), np.clip(f, 0, k_folds - 1), -1)

    cost = cost_policy(sym)
    d0 = datetime.fromtimestamp(max(t0, int(bars["ts"][0])), tz=timezone.utc).date() - timedelta(days=1)
    d1 = datetime.fromtimestamp(min(t1, int(bars["ts"][-1])), tz=timezone.utc).date() + timedelta(days=1)
    base_vol: dict[int, np.ndarray] = {}
    for L in LENGTHS:
        step = L * 60
        first = (int(bars["ts"][0]) // step + 1) * step
        starts = np.arange(first, int(bars["ts"][-1]), step, dtype=np.int64)
        wb = extract(bars, starts, L // 5)
        base_vol[L] = vol_by_fold(wb, fold_of, k_folds) if wb is not None else np.full(k_folds, np.nan)
    out: list[dict[str, Any]] = []
    for name, L, starts in window_specs(cfg["anchors"], cfg["how"], d0, d1):
        w = extract(bars, starts, L // 5)
        if w is None or len(w["start"]) < 100:
            continue
        ratio = np.sqrt(vol_by_fold(w, fold_of, k_folds) / base_vol[L])
        for c in window_cells(sym, name, L, w, cost, fold_of, edges, cfg["rules"], int(cfg["embargo_days"] * 86400), k_folds):
            c["vol_ratio_by_fold"] = [None if not np.isfinite(x) else round(float(x), 3) for x in ratio]
            c["_ratio"] = ratio
            c["cost"] = cost
            out.append(c)
    return out


def grade(cells: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    half = cfg["folds"] // 2
    theta, nfl, alpha = cfg["vol_ratio"], cfg["n_floor"], cfg["alpha"]
    n_eval = len(cells)
    stable = shortlisted = 0
    for c in cells:
        r = c["_ratio"]
        d_ok = int(np.nansum(r[:half] >= theta)) >= 2
        c_ok = int(np.nansum(r[half:] >= theta)) >= 2
        c["vol_stable"] = bool(d_ok and c_ok)
        fo = c["_fold"]
        dm, cm = fo < half, fo >= half
        c["disc"] = dict(zip(("n", "mean_net_r", "sd"), mean_sd(c["_nr"][dm])))
        c["conf"] = dict(zip(("n", "mean_net_r", "sd"), mean_sd(c["_nr"][cm])))
        c["conf_bps"] = dict(zip(("n", "mean_net_bps", "sd"), mean_sd(c["_nbps"][cm])))
        c["conf_stress2x_mean_net_r"] = float(c["_nr2"][cm].mean()) if cm.any() else None
        c["disc_p"] = one_sided_p(c["disc"]["n"], c["disc"]["mean_net_r"], c["disc"]["sd"])
        c["shortlisted"] = bool(c["vol_stable"] and c["disc"]["n"] >= nfl and c["disc"]["mean_net_r"] > 0
                                and np.isfinite(c["disc_p"]) and c["disc_p"] <= alpha)
        stable += c["vol_stable"]
        shortlisted += c["shortlisted"]
    m = max(shortlisted, 1)
    qual = []
    for c in cells:
        n, mu, sd = c["conf"]["n"], c["conf"]["mean_net_r"], c["conf"]["sd"]
        c["conf_p"] = one_sided_p(n, mu, sd)
        c["conf_p_bonf"] = min(1.0, c["conf_p"] * m) if np.isfinite(c["conf_p"]) else None
        c["conf_lb_adj"] = lower_bound(n, mu, sd, alpha / m)
        c["conf_lb_alltests"] = lower_bound(n, mu, sd, alpha / max(n_eval, 1))
        c["conf_ci95_two_sided"] = [lower_bound(n, mu, sd, 0.025), 2 * mu - lower_bound(n, mu, sd, 0.025)] if n > 1 else None
        pos = sum(1 for v in c["mean_net_r_by_fold"][cfg["folds"] // 2:] if v is not None and v > 0)
        c["conf_folds_positive"] = pos
        c["qualifies"] = bool(c["shortlisted"] and n >= nfl and np.isfinite(c["conf_lb_adj"]) and c["conf_lb_adj"] > 0 and pos >= 2)
        c["qualifies_under_all_tests_correction"] = bool(c["qualifies"] and c["conf_lb_alltests"] > 0)
        if c["qualifies"]:
            qual.append(c)
    qual.sort(key=lambda c: c["conf_lb_adj"], reverse=True)
    return {"cells_evaluated": n_eval, "vol_stable": stable, "shortlisted": shortlisted, "M_bonferroni": m,
            "expected_false_shortlist_if_no_edge": round(stable * alpha, 2), "qualifying": qual}


def public(c: dict[str, Any]) -> dict[str, Any]:
    def r(x):
        return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(x, 5) if isinstance(x, float) else x
    return {"symbol": c["symbol"], "window": c["window"], "length_min": c["length_min"], "rule": c["rule"],
            "vol_ratio_by_fold": c["vol_ratio_by_fold"], "vol_stable": c["vol_stable"], "shortlisted": c["shortlisted"],
            "discovery": {k: r(v) for k, v in c["disc"].items()}, "discovery_p_uncorrected": r(c["disc_p"]),
            "confirmation": {k: r(v) for k, v in c["conf"].items()}, "confirmation_mean_net_bps": r(c["conf_bps"]["mean_net_bps"]),
            "confirmation_ci95_two_sided": None if not c["conf_ci95_two_sided"] else [r(v) for v in c["conf_ci95_two_sided"]],
            "confirmation_lb_bonferroni_shortlist": r(c["conf_lb_adj"]), "confirmation_lb_bonferroni_all_cells": r(c["conf_lb_alltests"]),
            "confirmation_p_bonferroni_shortlist": r(c["conf_p_bonf"]), "confirmation_folds_positive": c["conf_folds_positive"],
            "mean_net_r_by_fold": [r(v) for v in c["mean_net_r_by_fold"]], "n_by_fold": c["n_by_fold"],
            "stress_2x_cost_confirmation_mean_net_r": r(c["conf_stress2x_mean_net_r"]), "qualifies": c["qualifies"],
            "qualifies_under_all_cells_correction": c["qualifies_under_all_tests_correction"], "cost": c["cost"]}


# ---- run ---------------------------------------------------------------------------------------------------------
def run(a: argparse.Namespace) -> dict[str, Any]:
    t0 = int(datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc).timestamp())
    t1 = int(datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc).timestamp())
    cfg = {"folds": a.folds, "t0": t0, "t1": t1, "vol_ratio": a.vol_ratio, "n_floor": a.n_floor, "alpha": a.alpha,
           "embargo_days": a.embargo_days, "anchors": tuple(a.anchors.split(",")) if a.anchors else None,
           "how": not a.no_hour_of_week, "rules": RULES}
    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]
    given = dict(x.split("=", 1) for x in (a.data_csv or []))
    data_dir = Path(a.data_dir or (Path(a.out) / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    status: dict[str, Any] = {}
    cells: list[dict[str, Any]] = []
    inputs: list[str] = []
    for sym in symbols:
        try:
            if sym in given:
                path = Path(given[sym])
            else:
                from harness_stage0 import fetch_csv
                path = fetch_csv(sym, "5m", days=a.days, data_dir=data_dir, non_crypto_source=a.non_crypto_source) \
                    if not a.no_fetch else data_dir / f"{sym}_5.csv"
            bars = load_bars(path)
            if len(bars["ts"]) < 5000:
                raise RuntimeError(f"only {len(bars['ts'])} 5m bars")
            status[sym] = {"state": "measured", "bars": len(bars["ts"]),
                           "first": datetime.fromtimestamp(int(bars["ts"][0]), tz=timezone.utc).isoformat(),
                           "last": datetime.fromtimestamp(int(bars["ts"][-1]), tz=timezone.utc).isoformat()}
            inputs.append(str(path))
            cells.extend(scan_symbol(sym, bars, cfg))
        except Exception as exc:  # noqa: BLE001  # allow-silent: not silent, the failure is recorded per symbol in symbol_status and symbols_without_data; never fabricated or substituted
            status[sym] = {"state": "no_data", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    g = grade(cells, cfg)
    measured = [s for s, v in status.items() if v["state"] == "measured"]
    core = [s for s in CORE_PERPS if s in measured]
    if not measured or (any(s in symbols for s in CORE_PERPS) and len(core) < 4):
        verdict, rs = "indeterminate", "measured" if measured else "producer_failed"
    else:
        verdict, rs = ("pass" if g["qualifying"] else "fail"), "measured"
    ranked = [public(c) for c in g["qualifying"]]
    shortlist = sorted((public(c) for c in cells if c["shortlisted"]), key=lambda r: -(r["confirmation_lb_bonferroni_shortlist"] or -9))
    vol_top = sorted((public(c) for c in cells if c["vol_stable"] and c["rule"] == "C5"),
                     key=lambda r: -np.nanmean([x if x is not None else np.nan for x in r["vol_ratio_by_fold"]]))[:60]
    out = {
        "verdict": verdict if measured else "not_applicable", "read_state": rs,
        "population": (f"symbols measured {len(measured)} of {len(symbols)} ({','.join(measured)}); 5m candles; "
                       f"window {a.start}..{a.end}; {g['cells_evaluated']} (symbol x window x rule) cells evaluated, "
                       f"{g['vol_stable']} vol-stable, {g['shortlisted']} shortlisted on discovery, "
                       f"{len(ranked)} qualify; trades net of fee+slippage+perp funding"),
        "n": sum(c["conf"]["n"] for c in g["qualifying"]) if g["qualifying"] else 0,
        "note": (f"{verdict.upper()}: {len(ranked)} qualifying cell(s). M (Bonferroni over shortlist) = {g['M_bonferroni']}; "
                 f"uncorrected false shortlist expected if no edge ~ {g['expected_false_shortlist_if_no_edge']} of {g['vol_stable']} "
                 f"vol-stable cells. Symbols without data: {[s for s, v in status.items() if v['state'] != 'measured'] or 'none'}. "
                 "Crypto candles are Binance USD-M (PROXY for Bybit linear); funding is a directionless magnitude per 8h boundary crossed."),
        "decision_rule_id": a.rule_id, "data_inputs": sorted(set(inputs)),
        "measurement": {"thresholds": {"folds": a.folds, "vol_ratio": a.vol_ratio, "n_floor": a.n_floor, "alpha": a.alpha,
                                       "embargo_days": a.embargo_days, "lengths_min": list(LENGTHS), "rules": list(RULES)},
                        "counts": {k: v for k, v in g.items() if k != "qualifying"},
                        "symbol_status": status, "symbols_without_data": [s for s, v in status.items() if v["state"] != "measured"],
                        "ranked_qualifying_cells": ranked, "shortlisted_cells": shortlist[:200], "vol_stable_top_by_ratio": vol_top},
    }
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "verdict.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [f"# Vol-window scan stage A -- {verdict}", "", out["note"], "", out["population"], "",
             "| rank | symbol | window | len | rule | n(conf) | mean net R | CI95 (2-sided) | LB (Bonf. shortlist) | folds+ |", "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(ranked, 1):
        ci = r["confirmation_ci95_two_sided"] or [None, None]
        lines.append(f"| {i} | {r['symbol']} | {r['window']} | {r['length_min']} | {r['rule']} | {r['confirmation']['n']} | "
                     f"{r['confirmation']['mean_net_r']} | [{ci[0]}, {ci[1]}] | {r['confirmation_lb_bonferroni_shortlist']} | {r['confirmation_folds_positive']}/3 |")
    if not ranked:
        lines.append("| - | none qualify | | | | | | | | |")
    (Path(a.out) / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---- self-test ---------------------------------------------------------------------------------------------------
def _synth(seed: int, days: int, plant: bool, start: str = "2022-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t0 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    n = days * 288
    ts = t0 + BAR_S * np.arange(n)
    sig = np.full(n, 0.0004)  # 4 bps per 5m bar
    r = rng.normal(0, 1, n) * sig
    if plant:
        sod = (ts % 86400) // 60
        w = (sod >= 16 * 60) & (sod < 17 * 60)  # funding_16z, 60 min
        r[w] *= 3.0  # vol x3 in the window
        day_idx = np.arange(n) // 288
        first15 = w & (sod < 16 * 60 + 15)
        s = np.sign(np.add.reduceat(np.where(first15, r, 0.0), np.arange(0, n, 288)))  # first-15m sign per day
        later = w & (sod >= 16 * 60 + 15)
        r[later] += s[day_idx[later]] * 0.0016  # +16 bps/bar over 9 later bars ~ 14 bps/day drift, follows early sign
    c = 100.0 * np.exp(np.cumsum(r))
    o = np.concatenate(([100.0], c[:-1]))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 1, n)) * 0.0001)
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 1, n)) * 0.0001)
    return pd.DataFrame({"timestamp": pd.to_datetime(ts, unit="s", utc=True), "open": o, "high": hi, "low": lo, "close": c, "volume": 1.0})


def _self_test() -> int:
    import tempfile
    # 1. DST-aware anchors: US cash open is 14:30Z in winter, 13:30Z in summer
    a = ANCHORS[0]
    w = _starts_for_anchor(a, 30, date(2023, 1, 3), date(2023, 1, 3))
    s = _starts_for_anchor(a, 30, date(2023, 7, 3), date(2023, 7, 3))
    assert datetime.fromtimestamp(int(w[0]), tz=timezone.utc).strftime("%H:%M") == "14:30", w
    assert datetime.fromtimestamp(int(s[0]), tz=timezone.utc).strftime("%H:%M") == "13:30", s
    # us_close window of 30 min starts 30 min before 16:00 ET
    c = _starts_for_anchor(ANCHORS[1], 30, date(2023, 1, 3), date(2023, 1, 3))
    assert datetime.fromtimestamp(int(c[0]), tz=timezone.utc).strftime("%H:%M") == "20:30", c
    # weekend filter: us_open skips Sat/Sun
    assert len(_starts_for_anchor(a, 30, date(2023, 1, 7), date(2023, 1, 8))) == 0
    # 2. funding boundaries agree with the repo's own function
    from src.runtime import execution_costs as ec
    for e, x in ((1_700_000_000, 1_700_003_600), (1_700_025_000, 1_700_040_000), (1_700_000_000, 1_700_000_100)):
        assert funding_crossed(np.array([float(e)]), np.array([float(x)]), ec.FUNDING_WINDOW_HOURS)[0] == ec.funding_windows_crossed(e, x), (e, x)
    # 3. gaps drop a day, never silently interpolate
    df = _synth(1, 400, False)
    b = {k: df[k].to_numpy() for k in ("open", "high", "low", "close")}
    b["ts"] = (df["timestamp"].astype("int64") // 10**9).to_numpy() if df["timestamp"].dt.unit == "ns" else \
        df["timestamp"].dt.as_unit("s").astype("int64").to_numpy()
    st = _starts_for_anchor(ANCHORS[6], 60, date(2022, 1, 1), date(2022, 1, 5))
    full = extract(b, st, 12)
    assert full is not None and len(full["start"]) == 5
    keep = np.ones(len(b["ts"]), bool)
    keep[int(np.searchsorted(b["ts"], st[1])) + 4] = False
    gap = {k: v[keep] for k, v in b.items()}
    assert len(extract(gap, st, 12)["start"]) == 4
    # 4. end to end on synthetic data: a planted continuation window qualifies, a pure random walk does not
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        _synth(7, 1500, True).to_csv(tdp / "PLANTUSDT.csv", index=False)
        _synth(8, 1500, False).to_csv(tdp / "NULLUSDT.csv", index=False)
        ns = argparse.Namespace(symbols="PLANTUSDT,NULLUSDT,GHOSTUSDT", days=0, start="2022-01-01", end="2026-02-01", folds=6,
                                vol_ratio=1.5, n_floor=150, alpha=0.05, embargo_days=1, anchors="funding_16z,funding_08z,us_open",
                                no_hour_of_week=False, data_csv=[f"PLANTUSDT={tdp/'PLANTUSDT.csv'}", f"NULLUSDT={tdp/'NULLUSDT.csv'}"],
                                data_dir=str(tdp), no_fetch=True, non_crypto_source="yfinance", rule_id="SELFTEST", out=str(tdp / "out"))
        out = run(ns)
        ranked = out["measurement"]["ranked_qualifying_cells"]
        syms = {r["symbol"] for r in ranked}
        assert "PLANTUSDT" in syms, out["note"]
        assert "NULLUSDT" not in syms, [r for r in ranked if r["symbol"] == "NULLUSDT"]
        assert any(r["window"] == "funding_16z" and r["rule"] in ("C5", "C15", "O15") for r in ranked if r["symbol"] == "PLANTUSDT"), ranked
        assert not any(r["rule"] in ("F5", "F15") for r in ranked if r["symbol"] == "PLANTUSDT" and r["window"] == "funding_16z"), ranked
        assert out["measurement"]["symbols_without_data"] == ["GHOSTUSDT"], out["measurement"]["symbol_status"]
        top = ranked[0]
        assert all(v is not None and v >= 1.5 for v in top["vol_ratio_by_fold"][:3]), top["vol_ratio_by_fold"]
        assert top["cost"]["perp"] and top["cost"]["fee_bps_rt"] > 0 and top["cost"]["slip_bps_rt"] > 0, top["cost"]
        assert (Path(td) / "out" / "verdict.json").exists() and out["decision_rule_id"] == "SELFTEST"
    print("vol_window_scan self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--days", type=int, default=2500, help="trailing days to fetch of 5m candles")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-10-31")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--vol-ratio", type=float, default=1.5)
    ap.add_argument("--n-floor", type=int, default=150)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--embargo-days", type=float, default=1.0)
    ap.add_argument("--anchors", default=None, help="comma subset of anchor names (tests); default all")
    ap.add_argument("--no-hour-of-week", action="store_true")
    ap.add_argument("--non-crypto-source", choices=("yfinance", "dukascopy"), default="dukascopy")
    ap.add_argument("--data-csv", action="append", default=None, metavar="SYM=PATH")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--rule-id", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out:
        ap.error("--out is required")
    if a.folds % 2:
        ap.error("--folds must be even (discovery / confirmation halves)")
    v = run(a)
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n", "note")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
