#!/usr/bin/env python3
# wiring: research/queue/RQ-20261012-5bd1-*.yaml run.commands via .github/workflows/research-script-run.yml (scripts/research/script_run.py)
"""NEWS-ALPHA harness -- point-in-time feature -> target information-coefficient tests for the 14 pre-registered
NEWS-ALPHA units (checklist NEWS-ALPHA-HARNESS; program NEWS-ALPHA-PROGRAM; index
docs/research/news-alpha-program-2026-10-12.md).

ONE UNIT, TWO LEDGERED INVOCATIONS
----------------------------------
    news_alpha_ic.py --unit RQ-20261012-5bd1-02 --phase discovery --out <out_dir>
    news_alpha_ic.py --unit RQ-20261012-5bd1-02 --phase holdout   --out <out_dir>

A unit declares both as ``run.commands`` (research-script-run.yml runs them in order in one dispatch). The
discovery phase never reads a holdout row; it ledgers every cell's p and fixes the survivor set. The holdout
phase reads ONLY the cells the discovery phase ledgered as survivors (it refuses anything else) and writes the
unit's ``verdict.json`` (the script_run contract: ``{verdict, read_state, population, n, measurement, note,
records}``).

WHAT IT READS FROM THE UNIT (nothing here re-states the rule; it executes the registered one)
  * ``grid`` + ``grid_cells``       -- the cells, enumerated and COUNTED; a mismatch is producer_failed.
  * ``power.min_detectable_effect`` -- the per-cell n floor, n >= 7.85 / d^2 (the units' own basis formula).
  * ``decision_rule``                -- id/registered_at ride on the record (script_run reads them).
  * ``news_alpha``                   -- the DATA BINDING only: source, design (ts | xsec | event), bar,
    price source, populations -> symbols, discovery start, holdout window. Added at unblock time, before any
    run; it restates populations and windows the unit's text already registered.

THE STATISTICS (decision_rule.statistic, executed literally)
  * time-series cells: Spearman IC pooled across symbols after per-symbol demeaning; p from a Newey-West t on
    the per-timestamp mean of the standardized rank products, lag = ceil(1.5 x horizon in bars).
    Vol / |ret| / volume targets are INCREMENTAL: the IC is taken against the residual of the declared baseline
    (HAR-RV on log realized vol; AR(5) on log volume) fitted on the discovery window.
  * cross-sectional cells: per-timestamp Spearman across symbols (>= 5), NW t of the IC series; the quintile
    long-short is the trading arm.
  * event cells: mean CAR / abnormal log RV vs a matched baseline (same symbol, same hour-of-week, 10:1, seeded);
    p from a 2,000-resample day-block bootstrap.
  * discovery survivors: p <= 0.10 * r / 600, r = the cell's p-rank within the unit (family BH at q = 0.10 over
    the declared wave budget, unrun cells counted as p = 1).
  * holdout: one test per survivor; Holm at alpha 0.05 over every ledgered holdout test with m = the wave cap
    (20) -- unrun tests count as p = 1, the same conservative completion the discovery rule uses.
  * DIRECTION PASS additionally needs the sign-of-feature (ts) / quintile long-short (xsec) / event-direction
    trade's holdout mean return NET of src/runtime/execution_costs (fee via profile_loader.roundtrip_fee_bps_for,
    slippage + perp funding via resolve_cost_policy) with NW t >= 2.0 and a positive discovery-window net mean;
    rank-only confirmation reads PASS_RANK_ONLY (information, not edge).
  * VOL PASS: holdout QLIKE (vol) / MSE-of-log (volume) of baseline+feature beats baseline by >= 2% with a
    one-sided Diebold-Mariano p that survives the same Holm adjustment.

LEAKAGE CHECKS (gate the run; a failure is read_state producer_failed, never a verdict)
  L1  every feature row asserts max(item available_at) < the open of the bar its target window starts at.
  L2  a +1-bar FUTURE-shifted feature's IC is computed and reported on the vol cells (alignment flag).
  L3  survivors only: a circular-shift placebo (offset >= 30 days, 200 draws) must put the true statistic
      outside the placebo's central 95% to count.
  L4  --phase discovery drops every row whose target window touches the holdout before any statistic, and
      asserts it; --phase holdout reads only ledgered survivors.

THE THREE RESULT STATES (never collapsed)
  measured         read_state measured, verdict pass / fail / no_action_warranted (rank-only)
  insufficient     read_state measured, verdict indeterminate -- no cell reached its n floor (we looked; too few)
  producer_failed  read_state producer_failed, verdict not_applicable, n null -- we could not look (input
                   missing, leakage check failed, budget refusal)

INTERPRETATION, MARKED (INFERRED from the units' own power.basis text, "reported, not graded"): a cell whose
effective n (non-overlapping symbol-periods / IC periods / events) is below the floor is reported but is not
graded and cannot be a survivor; a unit FAILS when >= 1 cell is graded and no graded cell confirms.

THE TEST LEDGER. A runner can only write under its own out_dir, so the harness appends its rows to
``<out_dir>/ledger_rows.jsonl``; the family ledger is the FOLD of research/news_alpha/TEST-LEDGER.jsonl and every
landed ``comms/research/RQ-20261012-5bd1-*/*/ledger_rows.jsonl``. The budget check reads that fold.

numpy + pandas only (research-script-run.yml installs nothing else). Tier-1 research tooling: no config, no
order path, no live VM.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FAMILY = "NEWS-ALPHA"
LEDGER = REPO / "research" / "news_alpha" / "TEST-LEDGER.jsonl"
RUNS_GLOB = "comms/research/RQ-20261012-5bd1-*/*/ledger_rows.jsonl"
DEFAULT_BUDGET = 600
DEFAULT_HOLDOUT_CAP = 20
BH_Q = 0.10
HOLM_ALPHA = 0.05
NET_T_MIN = 2.0
VOL_IMPROVEMENT_MIN = 0.02
DM_ALPHA = 0.05
PLACEBO_DRAWS = 200
PLACEBO_MIN_DAYS = 30
BOOT_RESAMPLES = 2000
EVENT_MATCH_RATIO = 10
XSEC_MIN_SYMBOLS = 5
SEED = 20261012

DIRECTION_TARGETS = ("fwd_ret", "car")
VOL_TARGETS = ("fwd_rv", "fwd_absret", "fwd_volume", "abn_rv")
BAR_MIN = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}
HORIZON_MIN = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440, "5d": 7200}


class ProducerFailed(Exception):
    """We could not look (input missing, leakage, refusal). Carries the reason into verdict.json."""


# ── statistics primitives ───────────────────────────────────────────────────────────────────────────────
def norm_p_two_sided(t: float) -> float:
    return float(math.erfc(abs(t) / math.sqrt(2.0))) if np.isfinite(t) else float("nan")


def norm_p_one_sided(t: float) -> float:
    return float(0.5 * math.erfc(t / math.sqrt(2.0))) if np.isfinite(t) else float("nan")


def nw_tstat(u: np.ndarray, lag: int) -> Tuple[float, float, int]:
    """(mean, NW t, T) of a series; Bartlett kernel."""
    u = np.asarray(u, dtype=float)
    u = u[np.isfinite(u)]
    T = len(u)
    if T < 3:
        return float("nan"), float("nan"), T
    m = u.mean()
    e = u - m
    var = float(e @ e) / T
    for k in range(1, min(lag, T - 1) + 1):
        var += 2.0 * (1.0 - k / (lag + 1.0)) * float(e[k:] @ e[:-k]) / T
    if var <= 0:
        return m, float("nan"), T
    return float(m), float(m / math.sqrt(var / T)), T


def nw_lag(h_bars: int) -> int:
    return int(math.ceil(1.5 * h_bars))


def bh_survivor(p: float, rank: int, budget: int, q: float = BH_Q) -> bool:
    return bool(np.isfinite(p) and p <= q * rank / budget)


def holm_rejections(pvals: Sequence[float], m: int, alpha: float = HOLM_ALPHA) -> List[bool]:
    """Holm step-down with m tests (unrun tests count as p = 1, i.e. sit at the end)."""
    order = np.argsort(np.asarray(pvals, dtype=float))
    rej = [False] * len(pvals)
    for k, idx in enumerate(order):
        if pvals[idx] <= alpha / (m - k):
            rej[idx] = True
        else:
            break
    return rej


def _zrank(x: pd.Series) -> pd.Series:
    r = x.rank(method="average")
    sd = r.std(ddof=0)
    return (r - r.mean()) / sd if sd and sd > 0 else r * np.nan


def ts_ic(df: pd.DataFrame, xcol: str, ycol: str, h_bars: int,
          demean: Optional[Dict[str, Tuple[float, float]]] = None) -> Dict[str, Any]:
    """Pooled Spearman IC with per-symbol demeaning; NW t on the per-ts mean rank product."""
    d = df[["ts", "symbol", xcol, ycol]].dropna()
    if len(d) < 10:
        return {"ic": None, "t": None, "p": None, "rows": int(len(d)), "periods": 0}
    if demean is None:
        mx = d.groupby("symbol")[xcol].transform("mean")
        my = d.groupby("symbol")[ycol].transform("mean")
    else:
        mx = d["symbol"].map(lambda s: demean.get(s, (np.nan, np.nan))[0])
        my = d["symbol"].map(lambda s: demean.get(s, (np.nan, np.nan))[1])
    zx, zy = _zrank(d[xcol] - mx), _zrank(d[ycol] - my)
    prod = (zx * zy).groupby(d["ts"]).mean().sort_index()
    ic = float((zx * zy).mean())
    _, t, T = nw_tstat(prod.values, nw_lag(h_bars))
    return {"ic": ic, "t": t, "p": norm_p_two_sided(t), "rows": int(len(d)), "periods": int(T)}


def xsec_ic(df: pd.DataFrame, xcol: str, ycol: str, h_bars: int) -> Dict[str, Any]:
    d = df[["ts", "symbol", xcol, ycol]].dropna()
    ics = []
    for ts, g in d.groupby("ts"):
        if len(g) >= XSEC_MIN_SYMBOLS:
            a, b = g[xcol].rank(), g[ycol].rank()
            if a.std() > 0 and b.std() > 0:
                ics.append((ts, float(np.corrcoef(a, b)[0, 1])))
    if len(ics) < 3:
        return {"ic": None, "t": None, "p": None, "rows": int(len(d)), "periods": len(ics)}
    s = pd.Series([v for _, v in ics], index=[t for t, _ in ics]).sort_index()
    m, t, T = nw_tstat(s.values, nw_lag(h_bars))
    return {"ic": m, "t": t, "p": norm_p_two_sided(t), "rows": int(len(d)), "periods": int(T)}


def ols_fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta


def ols_predict(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X]) @ beta


def qlike(var_real: np.ndarray, var_fc: np.ndarray) -> np.ndarray:
    r = var_real / var_fc
    return r - np.log(r) - 1.0


# ── costs (the ONE cost stack) ──────────────────────────────────────────────────────────────────────────
def cost_model(symbol: str) -> Dict[str, float]:
    from src.core.profile_loader import roundtrip_fee_bps_for
    from src.runtime import execution_costs as ec
    fee = roundtrip_fee_bps_for(symbol)
    fee = ec.DEFAULT_FEE_BPS_ROUNDTRIP if fee is None else float(fee)
    slip, fund = ec.resolve_cost_policy(symbol)
    return {"fee_bps_rt": fee, "slippage_bps_rt": float(slip), "funding_bps_per_window": float(fund),
            "per_side": (fee + float(slip)) / 2.0 / 1e4, "funding": float(fund) / 1e4}


def funding_windows(h_bars: int, bar_min: int) -> float:
    from src.runtime.execution_costs import FUNDING_WINDOW_HOURS
    return h_bars * bar_min / 60.0 / FUNDING_WINDOW_HOURS


# ── unit + spec ─────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Cell:
    feature: str
    target: str
    horizon: str
    population: str
    regime: str = "all"

    @property
    def id(self) -> str:
        return "|".join((self.feature, self.target, self.horizon, self.population, self.regime))

    @property
    def kind(self) -> str:
        return "direction" if self.target in DIRECTION_TARGETS else "vol"


@dataclass
class Spec:
    unit: str
    raw: Dict[str, Any]
    design: str
    bar: str
    source: str
    price_source: str
    populations: Dict[str, List[str]]
    entity_of: Dict[str, str]
    discovery_start: pd.Timestamp
    holdout_start: pd.Timestamp
    holdout_end: pd.Timestamp
    floor: float
    cells: List[Cell] = field(default_factory=list)
    panel_dir: str = "comms/news_alpha/gdelt_panel"
    #: per-population overrides (a unit mixing hourly crypto and daily ETF cells, e.g. U07)
    pop_bar: Dict[str, str] = field(default_factory=dict)
    pop_price_source: Dict[str, str] = field(default_factory=dict)

    def view(self, pop: str) -> "Spec":
        """The spec as seen by one population: its bar, its price source, only its symbols."""
        from dataclasses import replace
        return replace(self, bar=self.pop_bar.get(pop, self.bar),
                       price_source=self.pop_price_source.get(pop, self.price_source),
                       populations={pop: self.populations[pop]})

    @property
    def bars(self) -> List[str]:
        return sorted({self.pop_bar.get(p, self.bar) for p in {c.population for c in self.cells}})

    def view_for_bar(self, bar: str) -> "Spec":
        from dataclasses import replace
        pops = {p: v for p, v in self.populations.items() if self.pop_bar.get(p, self.bar) == bar}
        src = {self.pop_price_source.get(p, self.price_source) for p in pops}
        if len(src) > 1:
            raise ProducerFailed(f"populations on {bar} bars name more than one price source {sorted(src)}")
        return replace(self, bar=bar, price_source=src.pop() if src else self.price_source, populations=pops)

    @property
    def bar_min(self) -> int:
        return BAR_MIN[self.bar]

    def h_bars(self, horizon: str) -> int:
        hm = HORIZON_MIN[horizon]
        if hm % self.bar_min:
            raise ProducerFailed(f"horizon {horizon} is not a whole number of {self.bar} bars")
        return hm // self.bar_min

    @property
    def symbols(self) -> List[str]:
        out: List[str] = []
        for syms in self.populations.values():
            out += [s for s in syms if s not in out]
        return out


def find_unit(unit: str, queue_dir: Path) -> Path:
    for p in (queue_dir / f"{unit}.yaml", queue_dir / "blocked" / f"{unit}.yaml"):
        if p.is_file():
            return p
    raise ProducerFailed(f"unit {unit} not found under {queue_dir} (or blocked/)")


def _pop_horizons(grid: Dict[str, Any], pop: str) -> List[str]:
    for k, v in grid.items():
        if k.startswith("horizons_") and pop.startswith(k[len("horizons_"):]):
            return list(v)
    return list(grid.get("horizons") or [])


def enumerate_cells(unit_raw: Dict[str, Any]) -> List[Cell]:
    g = unit_raw.get("grid") or {}
    cells: List[Cell] = []
    if "event_classes" in g:
        pop = (list(g.get("populations") or ["all"]))[0]
        for ec_, tg, hz in product(g["event_classes"], g["targets"], g["horizons"]):
            cells.append(Cell(ec_, tg, hz, pop))
        return cells
    pops = list(g.get("populations") or g.get("assets") or ["all"])
    regimes = list(g.get("regime") or ["all"])
    for f in g.get("features") or []:
        for tg in g.get("targets") or []:
            for pop in pops:
                for hz in _pop_horizons(g, pop):
                    for rg in regimes:
                        cells.append(Cell(f, tg, hz, pop, rg))
    return cells


def load_spec(unit: str, queue_dir: Path) -> Spec:
    import yaml
    path = find_unit(unit, queue_dir)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    na = raw.get("news_alpha")
    if not isinstance(na, dict):
        raise ProducerFailed(f"{path.name} has no `news_alpha` data-binding block -- the harness cannot "
                             "know which panel / prices / windows the registered grid reads")
    cells = enumerate_cells(raw)
    want = raw.get("grid_cells")
    if want != len(cells):
        raise ProducerFailed(f"grid enumerates {len(cells)} cells but grid_cells declares {want!r}")
    pops = {str(k): [str(s) for s in v] for k, v in (na.get("populations") or {}).items()}
    g = raw.get("grid") or {}
    if "assets" in g:
        for a in g["assets"]:
            pops.setdefault(str(a), [str(na.get("asset_symbol", {}).get(a, a))])
    missing = sorted({c.population for c in cells} - set(pops))
    if missing:
        raise ProducerFailed(f"news_alpha.populations does not bind population(s) {missing}")
    mde = float((raw.get("power") or {}).get("min_detectable_effect") or 0)
    if mde <= 0:
        raise ProducerFailed("power.min_detectable_effect missing -- no n floor")
    ent = {str(k): str(v) for k, v in (na.get("entity_of") or {}).items()}
    spec = Spec(
        unit=unit, raw=raw, design=str(na.get("design")), bar=str(na.get("bar")),
        source=str(na.get("source")), price_source=str(na.get("price_source")),
        populations=pops, entity_of=ent,
        discovery_start=pd.Timestamp(na["discovery_start"], tz="UTC"),
        holdout_start=pd.Timestamp(na["holdout"][0], tz="UTC"),
        holdout_end=pd.Timestamp(na["holdout"][1], tz="UTC") + pd.Timedelta(days=1),
        floor=7.85 / mde ** 2, cells=cells, panel_dir=str(na.get("panel_dir") or "comms/news_alpha/gdelt_panel"),
        pop_bar={str(k): str(v) for k, v in (na.get("population_bars") or {}).items()},
        pop_price_source={str(k): str(v) for k, v in (na.get("population_price_source") or {}).items()})
    if spec.design not in ("ts", "xsec", "event"):
        raise ProducerFailed(f"news_alpha.design {spec.design!r} not in ts|xsec|event")
    for b in [spec.bar, *spec.pop_bar.values()]:
        if b not in BAR_MIN:
            raise ProducerFailed(f"news_alpha bar {b!r} not supported")
    for s in spec.symbols:
        spec.entity_of.setdefault(s, s[:-4] if s.endswith("USDT") else s)
    for c in cells:
        spec.view(c.population).h_bars(c.horizon)
    return spec


# ── prices + targets ────────────────────────────────────────────────────────────────────────────────────
def fetch_prices(spec: Spec, start: pd.Timestamp, end: pd.Timestamp,
                 prices_dir: Optional[Path]) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for sym in spec.symbols:
        if prices_dir is not None:
            p = Path(prices_dir) / f"{sym}_{spec.bar}.csv"
            if not p.is_file():
                continue
            df = pd.read_csv(p)
        else:
            sys.path.insert(0, str(REPO / "scripts" / "ops"))
            import fetch_backtest_candles as fbc  # noqa: E402
            interval = {"1h": "60", "1d": "D", "4h": "240", "15m": "15"}[spec.bar]
            s_ms, e_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
            try:
                if spec.price_source == "binance_vision":
                    rows = fbc.fetch_klines_binance_vision(sym, interval, s_ms, e_ms)
                elif spec.price_source == "dukascopy":
                    rows = fbc.fetch_klines_dukascopy(sym, interval, s_ms, e_ms)
                else:
                    raise ProducerFailed(f"price_source {spec.price_source!r} unsupported")
            except ProducerFailed:
                raise
            except Exception as exc:  # noqa: BLE001  # allow-silent: the symbol is recorded as missing in prices_manifest + population
                print(f"prices: {sym} fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            df = pd.DataFrame(rows)
        if df.empty:
            continue
        df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.drop_duplicates("ts").sort_values("ts").set_index("ts")
        out[sym] = df[["open", "high", "low", "close", "volume"]].astype(float)
    return out


def bar_targets(px: pd.DataFrame, h: int, bar: str) -> pd.DataFrame:
    """Targets for the window that OPENS at each bar's open and spans h bars, plus baseline predictors that use
    only bars strictly before it."""
    o, hi, lo, c, v = (px[k] for k in ("open", "high", "low", "close", "volume"))
    pv = (np.log(hi / lo) ** 2) / (4.0 * math.log(2.0))
    r2 = np.log(c / c.shift(1)) ** 2
    pv = pv.where(pv > 0, r2)
    out = pd.DataFrame(index=px.index)
    out["fwd_ret"] = c.shift(-(h - 1)) / o - 1.0
    out["fwd_absret"] = out["fwd_ret"].abs()
    out["fwd_rv"] = np.sqrt(pv[::-1].rolling(h, min_periods=h).sum()[::-1])
    vs = v[::-1].rolling(h, min_periods=h).sum()[::-1]
    out["fwd_volume"] = np.log(vs.where(vs > 0))
    d, w = (24, 168) if bar == "1h" else (5, 22)
    for name, k in (("har_1", h), ("har_d", d), ("har_w", w)):
        out[name] = np.log(pv.shift(1).rolling(k, min_periods=k).mean() * h)
    vb = v.shift(1).rolling(h, min_periods=h).sum()
    for j in range(1, 6):
        out[f"ar_vol_{j}"] = np.log(vb.shift((j - 1) * h).where(vb.shift((j - 1) * h) > 0))
    out["t_end"] = out.index + pd.Timedelta(minutes=BAR_MIN[bar] * h)
    out["valid"] = c.shift(-(h - 1)).notna()
    return out


def regime_labels(px: pd.DataFrame) -> pd.Series:
    from src.runtime.regime.detector import regime_label, wilder_adx
    adx = wilder_adx(px).shift(1)                  # known before the bar opens
    return adx.map(regime_label)


# ── data assembly + leakage ─────────────────────────────────────────────────────────────────────────────
def assemble(spec: Spec, feats: pd.DataFrame, prices: Dict[str, pd.DataFrame], cell: Cell) -> pd.DataFrame:
    h = spec.h_bars(cell.horizon)
    syms = [s for s in spec.populations[cell.population] if s in prices]
    frames = []
    for s in syms:
        t = bar_targets(prices[s], h, spec.bar)
        if cell.regime != "all":
            t["regime"] = regime_labels(prices[s])
        t["symbol"] = s
        frames.append(t.reset_index())
    if not frames:
        return pd.DataFrame()
    tg = pd.concat(frames, ignore_index=True)
    f = feats[feats["symbol"].isin(syms)]
    keep = ["ts", "symbol", "max_available_at"] + [c for c in f.columns if c == cell.feature or c.startswith("cls_")]
    d = tg.merge(f[list(dict.fromkeys(keep))], on=["ts", "symbol"], how="left")
    if cell.regime != "all":
        d = d[d["regime"] == cell.regime]
    return d[d["valid"]]


def assert_l1(d: pd.DataFrame, feature_cols: Sequence[str]) -> int:
    """L1: every row that carries a feature value read only items available strictly before the window opens."""
    has = d[list(feature_cols)].notna().any(axis=1)
    rows = d[has]
    if rows.empty:
        return 0
    ma = pd.to_datetime(rows["max_available_at"], utc=True)
    bad = rows[~(ma < rows["ts"])]
    if len(bad):
        ex = bad.iloc[0]
        raise ProducerFailed(f"L1 leakage: {len(bad)} feature row(s) read an item available at or after the bar "
                             f"open, e.g. {ex['symbol']} ts={ex['ts']} max_available_at={ex['max_available_at']}")
    return int(len(rows))


def phase_slice(spec: Spec, d: pd.DataFrame, phase: str) -> pd.DataFrame:
    if d.empty:
        return d
    if phase == "discovery":
        out = d[(d["ts"] >= spec.discovery_start) & (d["t_end"] <= spec.holdout_start)]
        assert (out["t_end"] <= spec.holdout_start).all(), "L4: a discovery row touches the holdout"
        return out
    return d[(d["ts"] >= spec.holdout_start) & (d["t_end"] <= spec.holdout_end)]


# ── per-cell statistics ─────────────────────────────────────────────────────────────────────────────────
def _baseline_cols(target: str) -> List[str]:
    return [f"ar_vol_{j}" for j in range(1, 6)] if target == "fwd_volume" else ["har_1", "har_d", "har_w"]


def _log_target(d: pd.DataFrame, target: str) -> pd.Series:
    if target == "fwd_volume":
        return d["fwd_volume"]
    return np.log(d[target].where(d[target] > 0))


def fit_baseline(disc: pd.DataFrame, target: str) -> Optional[np.ndarray]:
    cols = _baseline_cols(target)
    y = _log_target(disc, target)
    m = pd.concat([disc[cols], y.rename("y")], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(m) < 50:
        return None
    return ols_fit(m[cols].values, m["y"].values)


def add_residual(d: pd.DataFrame, target: str, beta: np.ndarray) -> pd.DataFrame:
    cols = _baseline_cols(target)
    d = d.copy()
    X = d[cols].replace([np.inf, -np.inf], np.nan)
    ok = X.notna().all(axis=1)
    pred = pd.Series(np.nan, index=d.index)
    pred[ok] = ols_predict(beta, X[ok].values)
    d["_y"] = _log_target(d, target).replace([np.inf, -np.inf], np.nan)
    d["_resid"] = d["_y"] - pred
    d["_pred"] = pred
    return d


def cell_ycol(cell: Cell) -> str:
    return cell.target if cell.kind == "direction" else "_resid"


def n_eff_of(stat: Dict[str, Any], design: str, h: int) -> int:
    if design == "event":
        return int(stat.get("events") or 0)
    if design == "xsec":
        return int((stat.get("periods") or 0) // h)
    return int((stat.get("rows") or 0) // h)


def events_of(d: pd.DataFrame, cls: str) -> pd.Series:
    """First bar with a class hit after >= 24h of silence for that symbol (bar b reads the hour before it)."""
    col = f"cls_{cls}"
    if col not in d.columns:
        raise ProducerFailed(f"panel carries no {col} column")
    hit = d[col].fillna(0) > 0
    out = pd.Series(False, index=d.index)
    gap = pd.Timedelta(hours=24)
    for _, g in d[hit].groupby("symbol"):
        last = None
        for idx, ts in g["ts"].items():
            if last is None or ts - last >= gap:
                out[idx] = True
            last = ts
    return out


def event_stat(d: pd.DataFrame, cell: Cell, rng: np.random.Generator) -> Dict[str, Any]:
    ev = events_of(d, cell.feature)
    tcol = "fwd_ret" if cell.target == "car" else "_lrv"
    d = d.copy()
    d["_lrv"] = np.log(d["fwd_rv"].where(d["fwd_rv"] > 0))
    d["_how"] = d["ts"].dt.dayofweek * 24 + d["ts"].dt.hour
    base = d[~ev & d[tcol].notna()]
    pool = {k: g[tcol].values for k, g in base.groupby(["symbol", "_how"])}
    rows = []
    for idx in d.index[ev]:
        r = d.loc[idx]
        if not np.isfinite(r[tcol]):
            continue
        cand = pool.get((r["symbol"], r["_how"]))
        if cand is None or len(cand) < EVENT_MATCH_RATIO:
            continue
        m = rng.choice(cand, EVENT_MATCH_RATIO, replace=False).mean()
        rows.append((r["ts"], r["symbol"], float(r[tcol] - m), float(r["fwd_ret"])))
    if len(rows) < 3:
        return {"stat": None, "p": None, "events": len(rows)}
    e = pd.DataFrame(rows, columns=["ts", "symbol", "abn", "fwd_ret"])
    mean = float(e["abn"].mean())
    days = e["ts"].dt.floor("D")
    by_day = [g["abn"].values for _, g in e.groupby(days)]
    boots = np.empty(BOOT_RESAMPLES)
    for b in range(BOOT_RESAMPLES):
        pick = rng.integers(0, len(by_day), len(by_day))
        boots[b] = np.concatenate([by_day[i] for i in pick]).mean()
    p = float(np.mean(np.abs(boots - mean) >= abs(mean)))
    return {"stat": mean, "p": max(p, 1.0 / BOOT_RESAMPLES), "events": int(len(e)), "_events": e}


def compute_cell(spec: Spec, cell: Cell, d: pd.DataFrame, rng: np.random.Generator) -> Dict[str, Any]:
    h = spec.h_bars(cell.horizon)
    if spec.design == "event":
        st = event_stat(d, cell, rng)
        st.pop("_events", None)
        return {"stat": st["stat"], "p": st["p"], "events": st["events"]}
    y = cell_ycol(cell)
    if spec.design == "xsec":
        st = xsec_ic(d, cell.feature, y if cell.kind == "direction" else cell.target, h)
    else:
        st = ts_ic(d, cell.feature, y, h)
    return {"stat": st["ic"], "p": st["p"], "t": st["t"], "rows": st["rows"], "periods": st["periods"]}


def placebo(spec: Spec, cell: Cell, d: pd.DataFrame, true_stat: float, rng: np.random.Generator) -> Dict[str, Any]:
    """L3: circular shift of the feature per symbol by >= 30 days; true stat must sit outside the central 95%."""
    min_shift = int(PLACEBO_MIN_DAYS * 1440 / spec.bar_min)
    draws = []
    for _ in range(PLACEBO_DRAWS):
        dd = d.copy()
        for s, g in dd.groupby("symbol"):
            n = len(g)
            if n <= 2 * min_shift:
                continue
            k = int(rng.integers(min_shift, n - min_shift))
            cols = [cell.feature] if spec.design != "event" else [c for c in g.columns if c.startswith("cls_")]
            for c in cols:
                dd.loc[g.index, c] = np.roll(g[c].values, k)
        st = compute_cell(spec, cell, dd, rng)
        if st["stat"] is not None and np.isfinite(st["stat"]):
            draws.append(st["stat"])
    if len(draws) < 20:
        return {"ran": False, "draws": len(draws), "outside_central_95": None}
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return {"ran": True, "draws": len(draws), "lo": float(lo), "hi": float(hi),
            "outside_central_95": bool(true_stat < lo or true_stat > hi)}


def future_shift_ic(spec: Spec, cell: Cell, d: pd.DataFrame) -> Optional[float]:
    """L2: the IC of the feature shifted one bar into the future (it reads information it could not have)."""
    if spec.design == "event":
        return None
    dd = d.sort_values(["symbol", "ts"]).copy()
    dd[cell.feature] = dd.groupby("symbol")[cell.feature].shift(-1)
    h = spec.h_bars(cell.horizon)
    st = ts_ic(dd, cell.feature, cell_ycol(cell), h) if spec.design == "ts" else \
        xsec_ic(dd, cell.feature, cell.target, h)
    return st["ic"]


# ── trading arms (net of the full cost stack) ───────────────────────────────────────────────────────────
def ts_net_returns(spec: Spec, d: pd.DataFrame, feature: str, h: int, sign: float,
                   centers: Dict[str, float]) -> pd.Series:
    rets = {}
    nw = funding_windows(h, spec.bar_min)
    for s, g in d.sort_values("ts").groupby("symbol"):
        cm = cost_model(s)
        g = g.iloc[::h]
        x = g[feature] - centers.get(s, 0.0)
        pos = (np.sign(x) * sign).fillna(0.0)
        prev = pos.shift(1).fillna(0.0)
        net = pos * g["fwd_ret"] - (pos - prev).abs() * cm["per_side"] - pos.abs() * cm["funding"] * nw
        rets[s] = pd.Series(net.values, index=g["ts"].values)
    if not rets:
        return pd.Series(dtype=float)
    return pd.DataFrame(rets).mean(axis=1).dropna().sort_index()


def xsec_net_returns(spec: Spec, d: pd.DataFrame, feature: str, h: int, sign: float) -> pd.Series:
    nw = funding_windows(h, spec.bar_min)
    costs = {s: cost_model(s) for s in d["symbol"].unique()}
    stamps = sorted(d["ts"].unique())[::h]
    prev_w: Dict[str, float] = {}
    out = []
    for ts in stamps:
        g = d[(d["ts"] == ts)].dropna(subset=[feature, "fwd_ret"])
        if len(g) < XSEC_MIN_SYMBOLS:
            continue
        q = g[feature].rank(pct=True) * sign
        k = max(1, len(g) // 5)
        order = q.sort_values()
        w = {s: 0.0 for s in g["symbol"]}
        for i in order.index[-k:]:
            w[g.loc[i, "symbol"]] = 1.0 / k
        for i in order.index[:k]:
            w[g.loc[i, "symbol"]] = -1.0 / k
        gross = sum(w[s] * r for s, r in zip(g["symbol"], g["fwd_ret"]))
        turn = sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) * costs[s]["per_side"] for s in set(w) | set(prev_w))
        fund = sum(abs(w[s]) * costs[s]["funding"] * nw for s in w)
        out.append((ts, gross - turn - fund))
        prev_w = w
    return pd.Series([v for _, v in out], index=[t for t, _ in out], dtype=float)


def event_net_returns(spec: Spec, d: pd.DataFrame, cell: Cell, sign: float, rng: np.random.Generator) -> pd.Series:
    h = spec.h_bars(cell.horizon)
    st = event_stat(d, cell, rng)
    e = st.get("_events")
    if e is None:
        return pd.Series(dtype=float)
    nw = funding_windows(h, spec.bar_min)
    vals = []
    for _, r in e.sort_values("ts").iterrows():
        cm = cost_model(r["symbol"])
        vals.append((r["ts"], sign * r["fwd_ret"] - 2 * cm["per_side"] - cm["funding"] * nw))
    return pd.Series([v for _, v in vals], index=[t for t, _ in vals], dtype=float)


# ── the ledger ──────────────────────────────────────────────────────────────────────────────────────────
def fold_ledger(repo: Path, ledger: Path, out_dir: Optional[Path]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    paths = [ledger] + sorted(repo.glob(RUNS_GLOB))
    if out_dir is not None:
        mine = Path(out_dir) / "ledger_rows.jsonl"
        if mine.resolve() not in {p.resolve() for p in paths}:
            paths.append(mine)
    for p in paths:
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("family", FAMILY) == FAMILY:
                    r.setdefault("_src", str(p))
                    rows.append(r)
    return rows


def budget_of(rows: List[Dict[str, Any]]) -> Tuple[int, int]:
    disc, hold = DEFAULT_BUDGET, DEFAULT_HOLDOUT_CAP
    for r in rows:
        if r.get("kind") == "budget":
            disc = int(r.get("discovery_budget_tests", disc))
            hold = int(r.get("holdout_cap_tests", hold))
    disc += sum(int(r.get("extra_tests", 0)) for r in rows if r.get("kind") == "amendment")
    return disc, hold


def append_ledger(out_dir: Path, rows: List[Dict[str, Any]]) -> None:
    p = out_dir / "ledger_rows.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")


# ── phases ──────────────────────────────────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(v: Any) -> Any:
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def run_discovery(spec_all: Spec, feats_by_bar: Dict[str, pd.DataFrame],
                  prices_by_bar: Dict[str, Dict[str, pd.DataFrame]], out_dir: Path,
                  ledger_rows: List[Dict[str, Any]], run_id: str) -> Dict[str, Any]:
    spec = spec_all
    budget, _ = budget_of(ledger_rows)
    prior = [r for r in ledger_rows if r.get("kind") == "discovery_test" and r.get("unit") == spec.unit]
    if prior:
        raise ProducerFailed(f"refused: {spec.unit} already has {len(prior)} ledgered discovery test(s) "
                             f"(run {prior[0].get('run_id')}); a re-run would spend the family budget twice "
                             "without a ledgered pre-run amendment")
    used = {(r["unit"], r["cell"]) for r in ledger_rows if r.get("kind") == "discovery_test"}
    if len(used) + len(spec.cells) > budget:
        raise ProducerFailed(f"refused: {len(used)} ledgered + {len(spec.cells)} new discovery tests exceeds the "
                             f"declared family budget {budget} (no ledgered amendment covers it)")
    rng = np.random.default_rng(SEED)
    results: List[Dict[str, Any]] = []
    l1_rows = 0
    baselines: Dict[Tuple[str, str], Any] = {}
    for cell in spec_all.cells:
        spec = spec_all.view(cell.population)
        feats, prices = feats_by_bar[spec.bar], prices_by_bar[spec.bar]
        h = spec.h_bars(cell.horizon)
        d = assemble(spec, feats, prices, cell)
        fcols = [cell.feature] if spec.design != "event" else [c for c in d.columns if c.startswith("cls_")]
        if d.empty or not set(fcols) <= set(d.columns):
            results.append({"cell": cell.id, "state": "no_data", "stat": None, "p": None, "n_eff": 0})
            continue
        l1_rows += assert_l1(d, fcols)
        disc = phase_slice(spec, d, "discovery")
        rec: Dict[str, Any] = {"cell": cell.id, "kind": cell.kind, "h_bars": h}
        if cell.kind == "vol" and spec.design != "event":
            beta = fit_baseline(disc, cell.target)
            if beta is None:
                results.append({**rec, "state": "no_data", "stat": None, "p": None, "n_eff": 0,
                                "note": "baseline could not be fitted (< 50 rows)"})
                continue
            baselines[(cell.target, cell.horizon)] = beta
            disc = add_residual(disc, cell.target, beta)
            if spec.design == "ts":
                rec["l2_future_shift_ic"] = _clean(future_shift_ic(spec, cell, disc))
        st = compute_cell(spec, cell, disc, rng)
        n_eff = n_eff_of(st, spec.design, h)
        rec.update({"stat": _clean(st["stat"]), "p": _clean(st["p"]), "t": _clean(st.get("t")),
                    "rows": st.get("rows"), "periods": st.get("periods"), "events": st.get("events"),
                    "n_eff": n_eff, "floor": round(spec.floor, 1), "graded": bool(n_eff >= spec.floor),
                    "symbols": sorted(disc["symbol"].unique().tolist()) if not disc.empty else [],
                    "window": [str(disc["ts"].min()) if not disc.empty else None,
                               str(disc["ts"].max()) if not disc.empty else None],
                    "state": "measured" if st["stat"] is not None else "no_data"})
        if cell.kind == "direction" and st["stat"] is not None and spec.design != "event":
            sign = 1.0 if st["stat"] >= 0 else -1.0
            centers = disc.groupby("symbol")[cell.feature].mean().to_dict()
            net = (ts_net_returns(spec, disc, cell.feature, h, sign, centers) if spec.design == "ts"
                   else xsec_net_returns(spec, disc, cell.feature, h, sign))
            m, t, T = nw_tstat(net.values, 2)
            rec["discovery_net"] = {"mean": _clean(m), "t": _clean(t), "periods": T}
        if spec.design == "event" and cell.kind == "direction" and st["stat"] is not None:
            net = event_net_returns(spec, disc, cell, 1.0 if st["stat"] >= 0 else -1.0, rng)
            m, t, T = nw_tstat(net.values, 1)
            rec["discovery_net"] = {"mean": _clean(m), "t": _clean(t), "periods": T}
        results.append(rec)
    # survivors: within-unit p-rank over the REGISTERED cells (unmeasured cells count as p = 1)
    ps = [(r["p"] if r.get("p") is not None else 1.0) for r in results]
    order = np.argsort(ps, kind="stable")
    for rank, idx in enumerate(order, start=1):
        r = results[idx]
        r["p_rank"] = rank
        surv = bh_survivor(ps[idx], rank, budget)
        r["bh_pass"] = surv
        r["lead"] = bool(r.get("p") is not None and r["p"] < 0.05 and not surv)
    for r, cell in zip(results, spec_all.cells):
        r["survivor"] = False
        if r.get("bh_pass") and r.get("graded"):
            spec = spec_all.view(cell.population)
            feats, prices = feats_by_bar[spec.bar], prices_by_bar[spec.bar]
            d = phase_slice(spec, assemble(spec, feats, prices, cell), "discovery")
            if cell.kind == "vol" and spec.design != "event":
                d = add_residual(d, cell.target, baselines[(cell.target, cell.horizon)])
            pl = placebo(spec, cell, d, r["stat"], rng)
            r["l3_placebo"] = pl
            r["survivor"] = bool(pl.get("outside_central_95"))
    rows = [{"kind": "discovery_test", "family": FAMILY, "wave": 1, "unit": spec.unit, "cell": r["cell"],
             "p": r.get("p"), "stat": r.get("stat"), "n_eff": r.get("n_eff"), "graded": r.get("graded", False),
             "survivor": r["survivor"], "run_id": run_id, "at": _now()} for r in results]
    append_ledger(out_dir, rows)
    doc = {"unit": spec.unit, "phase": "discovery", "run_id": run_id, "generated_at": _now(),
           "design": spec.design, "bar": spec_all.bar, "population_bars": spec_all.pop_bar,
           "budget": budget, "floor": spec.floor,
           "discovery_window": [str(spec.discovery_start), str(spec.holdout_start)],
           "l1_rows_asserted": l1_rows, "cells": results,
           "survivors": [r["cell"] for r in results if r["survivor"]]}
    (out_dir / "discovery.json").write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    return doc


def run_holdout(spec_all: Spec, feats_by_bar: Dict[str, pd.DataFrame],
                prices_by_bar: Dict[str, Dict[str, pd.DataFrame]], out_dir: Path,
                ledger_rows: List[Dict[str, Any]], run_id: str, disc_doc: Dict[str, Any]) -> Dict[str, Any]:
    spec = spec_all
    _, cap = budget_of(ledger_rows)
    surv_ledgered = {r["cell"] for r in ledger_rows if r.get("kind") == "discovery_test"
                     and r.get("unit") == spec.unit and r.get("survivor")}
    by_id = {r["cell"]: r for r in disc_doc["cells"]}
    survivors = list(disc_doc.get("survivors") or [])
    for c in survivors:
        if c not in surv_ledgered:
            raise ProducerFailed(f"refused: holdout read for {c}, which is not a ledgered discovery survivor")
    done = {(r["unit"], r["cell"]) for r in ledger_rows if r.get("kind") == "holdout_test"}
    for c in survivors:
        if (spec.unit, c) in done:
            raise ProducerFailed(f"refused: {c} already has its one holdout test ledgered")
    prior_hold = [r for r in ledger_rows if r.get("kind") == "holdout_test"]
    if len(prior_hold) + len(survivors) > cap:
        raise ProducerFailed(f"refused: {len(prior_hold)} ledgered + {len(survivors)} new holdout tests exceed the "
                             f"wave cap {cap}")
    rng = np.random.default_rng(SEED + 1)
    cells = {c.id: c for c in spec.cells}
    hold: List[Dict[str, Any]] = []
    for cid in survivors:
        cell, dr = cells[cid], by_id[cid]
        spec = spec_all.view(cell.population)
        feats, prices = feats_by_bar[spec.bar], prices_by_bar[spec.bar]
        h = spec.h_bars(cell.horizon)
        full = assemble(spec, feats, prices, cell)
        disc, ho = phase_slice(spec, full, "discovery"), phase_slice(spec, full, "holdout")
        rec: Dict[str, Any] = {"cell": cid, "kind": cell.kind, "h_bars": h}
        if cell.kind == "vol" and spec.design != "event":
            beta = fit_baseline(disc, cell.target)
            ho = add_residual(ho, cell.target, beta)
            st = compute_cell(spec, cell, ho, rng)
            same = st["stat"] is not None and np.sign(st["stat"]) == np.sign(dr["stat"])
            cols = _baseline_cols(cell.target)
            dd = add_residual(disc, cell.target, beta)
            m = pd.concat([dd[cols + [cell.feature, "_y"]]], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
            beta_aug = ols_fit(m[cols + [cell.feature]].values, m["_y"].values)
            hm = ho[["ts"] + cols + [cell.feature, "_y"]].replace([np.inf, -np.inf], np.nan).dropna()
            pb = ols_predict(beta, hm[cols].values)
            pa = ols_predict(beta_aug, hm[cols + [cell.feature]].values)
            if cell.target == "fwd_volume":
                lb, la = (hm["_y"].values - pb) ** 2, (hm["_y"].values - pa) ** 2
            else:
                real = np.exp(2 * hm["_y"].values)
                lb, la = qlike(real, np.exp(2 * pb)), qlike(real, np.exp(2 * pa))
            dl = pd.Series(lb - la, index=hm["ts"].values).groupby(level=0).mean().sort_index()
            _, dm_t, T = nw_tstat(dl.values, nw_lag(h))
            impr = float(1.0 - la.mean() / lb.mean()) if len(lb) and lb.mean() > 0 else None
            rec.update({"holdout_ic": _clean(st["stat"]), "same_sign": bool(same), "rows": int(len(hm)),
                        "improvement": _clean(impr), "dm_t": _clean(dm_t), "p": _clean(norm_p_one_sided(dm_t)),
                        "loss": "mse_log" if cell.target == "fwd_volume" else "qlike"})
        else:
            st = compute_cell(spec, cell, ho, rng)
            same = st["stat"] is not None and np.sign(st["stat"]) == np.sign(dr["stat"])
            sign = 1.0 if dr["stat"] >= 0 else -1.0
            if spec.design == "event":
                net = event_net_returns(spec, ho, cell, sign, rng)
                lagn = 1
            elif spec.design == "ts":
                centers = disc.groupby("symbol")[cell.feature].mean().to_dict()
                net, lagn = ts_net_returns(spec, ho, cell.feature, h, sign, centers), 2
            else:
                net, lagn = xsec_net_returns(spec, ho, cell.feature, h, sign), 2
            nm, nt, nT = nw_tstat(net.values, lagn)
            rec.update({"holdout_stat": _clean(st["stat"]), "same_sign": bool(same), "p": _clean(st["p"]),
                        "rows": st.get("rows"), "events": st.get("events"),
                        "net": {"mean": _clean(nm), "t": _clean(nt), "periods": nT},
                        "discovery_net": dr.get("discovery_net")})
        hold.append(rec)
    # Holm over every ledgered holdout test + this run's, m = the wave cap
    all_p = [float(r["p"]) if r.get("p") is not None else 1.0 for r in prior_hold]
    mine_p = [(float(r["p"]) if (r.get("p") is not None and r.get("same_sign")) else 1.0) for r in hold]
    rej = holm_rejections(all_p + mine_p, cap)[len(all_p):]
    for r, rj in zip(hold, rej):
        r["holm_reject"] = bool(rj)
        if r["kind"] == "vol":
            ok = rj and r.get("improvement") is not None and r["improvement"] >= VOL_IMPROVEMENT_MIN \
                and r.get("p") is not None and r["p"] < DM_ALPHA
            r["outcome"] = "PASS" if ok else "FAIL"
        else:
            dn = (r.get("discovery_net") or {}).get("mean")
            net_ok = (r["net"]["t"] is not None and r["net"]["t"] >= NET_T_MIN and dn is not None and dn > 0)
            r["outcome"] = ("PASS" if (rj and net_ok) else "PASS_RANK_ONLY" if rj else "FAIL")
    rows = [{"kind": "holdout_test", "family": FAMILY, "wave": 1, "unit": spec.unit, "cell": r["cell"],
             "p": r.get("p"), "same_sign": r.get("same_sign"), "holm_reject": r["holm_reject"],
             "outcome": r["outcome"], "run_id": run_id, "at": _now()} for r in hold]
    if rows:
        append_ledger(out_dir, rows)
    return {"unit": spec.unit, "phase": "holdout", "run_id": run_id, "generated_at": _now(),
            "holdout_window": [str(spec.holdout_start), str(spec.holdout_end)], "holm_m": cap, "cells": hold}


# ── verdict ─────────────────────────────────────────────────────────────────────────────────────────────
def _population(spec: Spec, disc: Dict[str, Any]) -> str:
    syms = sorted({s for c in disc.get("cells", []) for s in (c.get("symbols") or [])})
    return (f"{spec.unit}: {len(spec.cells)} registered cells ({spec.design}, {spec.bar} bars), symbols "
            f"{','.join(syms) or 'none'}; discovery {spec.discovery_start.date()}..{spec.holdout_start.date()} "
            f"(target windows purged at the holdout), holdout {spec.holdout_start.date()}.."
            f"{(spec.holdout_end - pd.Timedelta(days=1)).date()}; n floor {spec.floor:.1f} effective obs per cell")


def build_verdict(spec: Spec, disc: Dict[str, Any], hold: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cells = disc["cells"]
    graded = [c for c in cells if c.get("graded")]
    hmap = {c["cell"]: c for c in (hold or {}).get("cells", [])}
    records = []
    for c in cells:
        h = hmap.get(c["cell"])
        if c.get("state") != "measured":
            v, rs, n = "not_applicable", "no_data", None
        elif not c.get("graded"):
            v, rs, n = "indeterminate", "measured", int(c.get("n_eff") or 0)
        elif h is not None:
            v = {"PASS": "pass", "PASS_RANK_ONLY": "no_action_warranted"}.get(h["outcome"], "fail")
            rs, n = "measured", int(c.get("n_eff") or 0)
        else:
            v, rs, n = ("indeterminate" if c.get("survivor") else "fail"), "measured", int(c.get("n_eff") or 0)
        records.append({"verdict": v, "read_state": rs, "n": n,
                        "population": f"{spec.unit} cell {c['cell']} ({spec.design}, {spec.bar}); "
                                      f"symbols {','.join(c.get('symbols') or []) or 'none'}",
                        "measurement": {k: c.get(k) for k in ("stat", "p", "t", "p_rank", "n_eff", "floor",
                                                              "graded", "bh_pass", "lead", "survivor",
                                                              "discovery_net", "l2_future_shift_ic", "l3_placebo")}
                        | ({"holdout": h} if h else {}),
                        "note": ("underpowered: reported, not graded" if c.get("state") == "measured"
                                 and not c.get("graded") else "")})
    passes = [c for c in hmap.values() if c["outcome"] == "PASS"]
    rank_only = [c for c in hmap.values() if c["outcome"] == "PASS_RANK_ONLY"]
    survivors = disc.get("survivors") or []
    n_total = int(sum(int(c.get("n_eff") or 0) for c in graded))
    if not any(c.get("state") == "measured" for c in cells):
        return {**failed_verdict(spec.unit, "no registered cell could be measured (every cell no_data: "
                                 "missing prices, features or baseline)"), "read_state": "no_data",
                "result_state": "producer_failed", "records": records}
    if passes:
        verdict, state = "pass", "measured"
        note = f"PASS cells: {[c['cell'] for c in passes]}. A PASS is not a promotion; it files a prospective unit."
    elif not graded:
        verdict, state = "indeterminate", "insufficient"
        note = "insufficient: no registered cell reached its n floor; nothing was graded"
    elif rank_only and hold is not None:
        verdict, state = "no_action_warranted", "measured"
        note = f"PASS_RANK_ONLY (information, not edge, net of cost): {[c['cell'] for c in rank_only]}"
    elif survivors and hold is None:
        verdict, state = "indeterminate", "measured"
        note = f"{len(survivors)} discovery survivor(s) awaiting the ledgered holdout phase: {survivors}"
    else:
        verdict, state = "fail", "measured"
        note = ("no graded cell survived discovery" if not survivors else
                "every discovery survivor failed its holdout test") + \
               "; a FAIL closes only the configurations tested, never 'news'"
    leads = [c["cell"] for c in cells if c.get("lead")]
    under = [c["cell"] for c in cells if c.get("state") == "measured" and not c.get("graded")]
    if leads:
        note += f" | LEADS (p<0.05 unadjusted, non-survivors; wave-2 seeds on untouched data only): {leads}"
    if under:
        note += f" | {len(under)} underpowered cell(s) reported, not graded"
    return {"verdict": verdict, "read_state": "measured", "result_state": state,
            "population": _population(spec, disc), "n": n_total,
            "measurement": {"graded_cells": len(graded), "registered_cells": len(cells),
                            "survivors": survivors, "passes": [c["cell"] for c in passes],
                            "rank_only": [c["cell"] for c in rank_only], "leads": leads,
                            "l1_rows_asserted": disc.get("l1_rows_asserted")},
            "note": note, "records": records}


def failed_verdict(unit: str, reason: str) -> Dict[str, Any]:
    return {"verdict": "not_applicable", "read_state": "producer_failed", "result_state": "producer_failed",
            "population": f"{unit}: NEVER MEASURED -- {reason}", "n": None,
            "note": f"producer_failed: {reason}"}


# ── loading inputs ──────────────────────────────────────────────────────────────────────────────────────
def load_inputs(spec: Spec, *, features_csv: Optional[Path], panel_dir: Optional[Path],
                prices_dir: Optional[Path]) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Dict[str, pd.DataFrame]]]:
    """-> ({bar: feature panel}, {bar: {symbol: OHLCV}}) for every bar a population of the unit uses."""
    feats_by_bar: Dict[str, pd.DataFrame] = {}
    prices_by_bar: Dict[str, Dict[str, pd.DataFrame]] = {}
    panel = cov = None
    for bar in spec.bars:
        sv = spec.view_for_bar(bar)
        if features_csv is not None:
            feats = pd.read_csv(features_csv)
            feats["ts"] = pd.to_datetime(feats["ts"], utc=True)
        else:
            if spec.source != "gdelt_panel":
                raise ProducerFailed(f"news_alpha.source {spec.source!r} has no loader in this harness")
            from scripts.research import news_alpha_features as naf
            if panel is None:
                try:
                    panel, cov = naf.load_panel(panel_dir or (REPO / spec.panel_dir))
                except FileNotFoundError as exc:
                    raise ProducerFailed(f"input missing: {exc}") from exc
            feats = naf.build_features(panel, cov, bar=bar,
                                       symbols_to_entity={s: spec.entity_of[s] for s in sv.symbols})
        feats["max_available_at"] = pd.to_datetime(feats["max_available_at"], utc=True)
        if feats.empty:
            raise ProducerFailed("feature panel is empty")
        start = max(spec.discovery_start, feats["ts"].min()) - pd.Timedelta(days=45)
        end = min(spec.holdout_end, pd.Timestamp.now(tz="UTC")) + pd.Timedelta(days=7)
        prices = fetch_prices(sv, start, end, prices_dir)
        if not prices:
            raise ProducerFailed(f"no price series could be loaded for any symbol on {bar} bars")
        feats_by_bar[bar], prices_by_bar[bar] = feats, prices
    return feats_by_bar, prices_by_bar


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unit", required=True)
    ap.add_argument("--phase", choices=["discovery", "holdout"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--queue-dir", default=str(REPO / "research" / "queue"))
    ap.add_argument("--panel-dir", default=None, help="override news_alpha.panel_dir")
    ap.add_argument("--prices-dir", default=None, help="<SYM>_<bar>.csv files instead of fetching (tests/local)")
    ap.add_argument("--features-csv", default=None, help="a precomputed feature panel (tests)")
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--repo-root", default=str(REPO), help="where landed run ledgers are folded from")
    ap.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID") or "local")
    ap.add_argument("--plan", action="store_true", help="print the enumerated cells and exit")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        spec = load_spec(a.unit, Path(a.queue_dir))
        if a.plan:
            print(f"{spec.unit}: {len(spec.cells)} cells, design={spec.design} bar={spec.bar} "
                  f"symbols={len(spec.symbols)} floor={spec.floor:.1f}")
            for c in spec.cells:
                print("  " + c.id)
            return 0
        ledger_rows = fold_ledger(Path(a.repo_root), Path(a.ledger), out)
        if a.phase == "holdout":
            dpath = out / "discovery.json"
            if not dpath.is_file():
                prev = out / "verdict.json"
                why = (json.loads(prev.read_text()).get("note") if prev.is_file() else "no discovery.json")
                raise ProducerFailed(f"holdout phase has no discovery result in {out}: {why}")
            disc = json.loads(dpath.read_text(encoding="utf-8"))
            if disc.get("survivors"):
                feats, prices = load_inputs(spec, features_csv=Path(a.features_csv) if a.features_csv else None,
                                            panel_dir=Path(a.panel_dir) if a.panel_dir else None,
                                            prices_dir=Path(a.prices_dir) if a.prices_dir else None)
                hold = run_holdout(spec, feats, prices, out, ledger_rows, a.run_id, disc)
            else:
                hold = {"unit": spec.unit, "phase": "holdout", "cells": [], "note": "no survivors: holdout not read"}
            (out / "holdout.json").write_text(json.dumps(hold, indent=2, default=str) + "\n", encoding="utf-8")
            verdict = build_verdict(spec, disc, hold)
        else:
            feats, prices = load_inputs(spec, features_csv=Path(a.features_csv) if a.features_csv else None,
                                        panel_dir=Path(a.panel_dir) if a.panel_dir else None,
                                        prices_dir=Path(a.prices_dir) if a.prices_dir else None)
            (out / "prices_manifest.json").write_text(json.dumps(
                {f"{s}@{b}": {"bars": int(len(df)), "first": str(df.index.min()), "last": str(df.index.max())}
                 for b, px in prices.items() for s, df in px.items()}, indent=2) + "\n", encoding="utf-8")
            disc = run_discovery(spec, feats, prices, out, ledger_rows, a.run_id)
            verdict = build_verdict(spec, disc, None)
    except ProducerFailed as exc:
        verdict = failed_verdict(a.unit, str(exc))
    except Exception as exc:  # noqa: BLE001  # allow-silent: written as producer_failed verdict and exit 3
        traceback.print_exc()
        verdict = failed_verdict(a.unit, f"unexpected {type(exc).__name__}: {exc}")
        (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str) + "\n", encoding="utf-8")
        return 3
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: verdict.get(k) for k in ("verdict", "read_state", "result_state", "n", "note")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
