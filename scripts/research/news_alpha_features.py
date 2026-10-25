#!/usr/bin/env python3
# wiring: imported by scripts/research/news_alpha_ic.py (the NEWS-ALPHA harness); tests/test_news_alpha_ic.py
"""NEWS-ALPHA feature family -- the GDELT hourly PANEL -> point-in-time features at a bar frequency.

Checklist rows: NEWS-ALPHA-FEATURES (this module is its GDELT part; the live-log and Kalshi PM adapters are
NOT built here) and NEWS-ALPHA-HARNESS (the consumer). Program index: docs/research/news-alpha-program-2026-10-12.md.

INPUT -- the aggregate-on-ingest panel written by ``scripts/research/news_hist_fetch.py --aggregate``
(checklist NEWS-ALPHA-CORPUS-SLICE1), one pair of files per UTC month under ``comms/news_alpha/gdelt_panel/``:

  panel_YYYY-MM.csv.gz     hour, entity, n, n_dom, tone_sum, tone_sq, tone_min, tone_max, cls_<c>..., top_<t>...
                           one row per (aggregation hour, entity) with >= 1 matching article; ``hour`` is the START
                           of the hour of GDELT *ingest* (V2.1DATE), never the publisher's time.
  coverage_YYYY-MM.csv.gz  hour, files_ok, files_missing, files_error, max_avail
                           one row per hour: how many of its four 15-min GKG files were read, and the latest
                           ingest stamp read (the availability time of everything in that hour).

STATES, NEVER COLLAPSED (CLAUDE-RULES-CANONICAL § "Collapsed states"):
  * an entity absent from a FULLY covered hour  -> n = 0  (we looked and found nothing)
  * any hour with files_ok < 4                  -> every feature reading that hour is NaN (we could not look)
  * a 24h window with zero articles             -> tone features NaN (no tone was observed), never 0.0

POINT IN TIME. A feature row for the bar that OPENS at T is built only from hours whose ``max_avail`` < T, and
carries ``max_available_at`` (the latest ingest stamp it read) so the harness's L1 check can assert it per row.
Hourly bars: hour h -> bar h+1h. Daily bars: the UTC day D-1 -> bar D (opens 00:00 UTC D).

Pure pandas/numpy (the research runner installs nothing else). Tier-1 research tooling; no live path.
"""
from __future__ import annotations

import gzip
import io
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

PANEL_COLS_BASE = ("n", "n_dom", "n_tone", "tone_sum", "tone_sq", "tone_min", "tone_max")
FULL_COVERAGE_FILES = 4          # four 15-min GKG files per hour
MACRO_ENTITY = "MACRO"

#: Features computed on the ENTITY's own rows.
ENTITY_FEATURES = ("count_shock_z", "breadth_shock_z", "tone_level", "tone_change_24h", "tone_novelty_z",
                   "tone_dispersion", "org_count_shock_z")
#: Topic features: read from the MACRO entity's topic counts, broadcast to every symbol.
TOPIC_FEATURES = ("conflict", "central_bank", "inflation", "energy", "trade_policy")


# ── loading ──────────────────────────────────────────────────────────────────────────────────────────────
def _read_csv_any(path: Path) -> pd.DataFrame:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return pd.read_csv(io.StringIO(fh.read()))
    return pd.read_csv(path)


def load_panel(panel_dir: Path) -> "tuple[pd.DataFrame, pd.DataFrame]":
    """-> (panel, coverage). Raises FileNotFoundError when the directory holds no month (could not look)."""
    panel_dir = Path(panel_dir)
    pfiles = sorted(panel_dir.glob("panel_*.csv*"))
    cfiles = sorted(panel_dir.glob("coverage_*.csv*"))
    if not pfiles or not cfiles:
        raise FileNotFoundError(f"no panel_*/coverage_* months under {panel_dir}")
    panel = pd.concat([_read_csv_any(p) for p in pfiles], ignore_index=True)
    cov = pd.concat([_read_csv_any(p) for p in cfiles], ignore_index=True)
    panel["hour"] = pd.to_datetime(panel["hour"], utc=True)
    cov["hour"] = pd.to_datetime(cov["hour"], utc=True)
    cov["max_avail"] = pd.to_datetime(cov["max_avail"], utc=True, errors="coerce")
    cov = cov.drop_duplicates("hour", keep="last").sort_values("hour").reset_index(drop=True)
    return panel, cov


# ── the dense per-entity hourly frame ────────────────────────────────────────────────────────────────────
def entity_hourly(panel: pd.DataFrame, cov: pd.DataFrame, entity: str) -> pd.DataFrame:
    """Dense hourly frame for one entity over the coverage span: counts 0 where covered-and-absent,
    NaN where the hour was not fully read."""
    grid = cov[["hour", "files_ok", "max_avail"]].copy().set_index("hour")
    sub = panel[panel["entity"] == entity].drop(columns=["entity"]).groupby("hour").sum(numeric_only=True)
    if "tone_min" in sub.columns:   # min/max do not sum: recompute from the rows
        g = panel[panel["entity"] == entity].groupby("hour")
        sub["tone_min"] = g["tone_min"].min()
        sub["tone_max"] = g["tone_max"].max()
    df = grid.join(sub, how="left")
    count_cols = [c for c in df.columns if c not in ("files_ok", "max_avail", "tone_min", "tone_max")]
    df[count_cols] = df[count_cols].fillna(0.0)
    bad = df["files_ok"].fillna(0) < FULL_COVERAGE_FILES
    df.loc[bad, [c for c in df.columns if c not in ("files_ok", "max_avail")]] = np.nan
    return df


def _shock_z(level: pd.Series, season_lags: Sequence[int], sd_window: int, sd_min: int) -> pd.Series:
    """(level - mean of the same seasonal slot over the previous lags) / trailing sd of that residual.
    Only strictly-past values enter the seasonal mean and the sd."""
    seas = pd.concat([level.shift(k) for k in season_lags], axis=1)
    m = seas.mean(axis=1, skipna=True).where(seas.notna().sum(axis=1) >= 2)
    resid = level - m
    sd = resid.shift(1).rolling(sd_window, min_periods=sd_min).std()
    return resid / sd.replace(0.0, np.nan)


def _trailing_z(x: pd.Series, window: int, minp: int, gap: int = 1) -> pd.Series:
    mu = x.shift(gap).rolling(window, min_periods=minp).mean()
    sd = x.shift(gap).rolling(window, min_periods=minp).std()
    return (x - mu) / sd.replace(0.0, np.nan)


def hourly_features(dense: pd.DataFrame) -> pd.DataFrame:
    """Entity features indexed by the aggregation hour h (known at h+1h)."""
    out = pd.DataFrame(index=dense.index)
    l_n = np.log1p(dense["n"])
    l_d = np.log1p(dense["n_dom"])
    week = [168 * k for k in (1, 2, 3, 4)]               # same hour-of-week, previous 30 days
    out["count_shock_z"] = _shock_z(l_n, week, 720, 168)
    out["breadth_shock_z"] = _shock_z(l_d, week, 720, 168)
    out["org_count_shock_z"] = out["count_shock_z"]
    nt = dense["n_tone"] if "n_tone" in dense.columns else dense["n"]
    n24 = nt.rolling(24, min_periods=24).sum()
    s24 = dense["tone_sum"].rolling(24, min_periods=24).sum()
    q24 = dense["tone_sq"].rolling(24, min_periods=24).sum()
    tone24 = (s24 / n24).where(n24 > 0)
    out["tone_level"] = tone24
    out["tone_change_24h"] = tone24 - tone24.shift(24)
    t1 = (dense["tone_sum"] / nt).where(nt > 0)
    out["tone_novelty_z"] = _trailing_z(t1, 720, 168)
    var24 = (q24 / n24 - tone24 ** 2).where(n24 >= 5)
    out["tone_dispersion"] = np.sqrt(var24.clip(lower=0.0))
    for c in dense.columns:
        if c.startswith("cls_"):
            out[c] = dense[c]
    return out


def daily_features(dense: pd.DataFrame) -> pd.DataFrame:
    """Entity features indexed by UTC day D (built from day D's hours; known at D+1 00:00)."""
    full = dense["n"].notna()
    day = dense.index.floor("D")
    agg = dense.groupby(day).sum(min_count=1, numeric_only=True)
    complete = full.groupby(day).all()
    agg.loc[~complete] = np.nan
    out = pd.DataFrame(index=agg.index)
    l_n, l_d = np.log1p(agg["n"]), np.log1p(agg["n_dom"])
    wk = [7, 14, 21, 28]                                  # same weekday, previous 4 weeks
    out["count_shock_z"] = _shock_z(l_n, wk, 90, 28)
    out["breadth_shock_z"] = _shock_z(l_d, wk, 90, 28)
    out["org_count_shock_z"] = out["count_shock_z"]
    nt = agg["n_tone"] if "n_tone" in agg.columns else agg["n"]
    tone = (agg["tone_sum"] / nt).where(nt > 0)
    out["tone_level"] = tone
    out["tone_change_24h"] = tone - tone.shift(1)
    out["tone_novelty_z"] = _trailing_z(tone, 30, 15)
    var = (agg["tone_sq"] / nt - tone ** 2).where(nt >= 5)
    out["tone_dispersion"] = np.sqrt(var.clip(lower=0.0))
    for c in agg.columns:
        if c.startswith("cls_"):
            out[c] = agg[c]
    return out


def _topic_hourly(dense_macro: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=dense_macro.index)
    n24 = dense_macro["n"].rolling(24, min_periods=24).sum()
    for t in TOPIC_FEATURES:
        col = f"top_{t}"
        if col not in dense_macro.columns:
            continue
        share = (dense_macro[col].rolling(24, min_periods=24).sum() / n24).where(n24 > 0)
        out[t] = _trailing_z(share, 720, 168, gap=24)
    return out


def _topic_daily(dense_macro: pd.DataFrame) -> pd.DataFrame:
    day = dense_macro.index.floor("D")
    complete = dense_macro["n"].notna().groupby(day).all()
    agg = dense_macro.groupby(day).sum(min_count=1, numeric_only=True)
    agg.loc[~complete] = np.nan
    out = pd.DataFrame(index=agg.index)
    for t in TOPIC_FEATURES:
        col = f"top_{t}"
        if col not in agg.columns:
            continue
        share = (agg[col] / agg["n"]).where(agg["n"] > 0)
        out[t] = _trailing_z(share, 30, 15)
    return out


def build_features(panel: pd.DataFrame, cov: pd.DataFrame, *, bar: str,
                   symbols_to_entity: Dict[str, str]) -> pd.DataFrame:
    """Long frame: one row per (bar open ``ts``, ``symbol``) with ``max_available_at`` + every feature.

    ``ts`` is the open of the bar the feature may first inform; every input hour has max_avail < ts.
    """
    if bar not in ("1h", "1d"):
        raise ValueError(f"bar {bar!r} not in ('1h', '1d')")
    avail = cov.set_index("hour")["max_avail"]
    macro_dense = entity_hourly(panel, cov, MACRO_ENTITY)
    topics = _topic_hourly(macro_dense) if bar == "1h" else _topic_daily(macro_dense)
    frames: List[pd.DataFrame] = []
    cache: Dict[str, pd.DataFrame] = {}
    for sym, ent in symbols_to_entity.items():
        if ent not in cache:
            dense = entity_hourly(panel, cov, ent)
            cache[ent] = hourly_features(dense) if bar == "1h" else daily_features(dense)
        f = cache[ent].join(topics, how="left")
        if bar == "1h":
            f["max_available_at"] = avail.reindex(f.index)
            f.index = f.index + pd.Timedelta(hours=1)
        else:
            day_avail = avail.groupby(avail.index.floor("D")).max()
            f["max_available_at"] = day_avail.reindex(f.index)
            f.index = f.index + pd.Timedelta(days=1)
        f.index.name = "ts"
        f = f.reset_index()
        f["symbol"] = sym
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def entities_in(panel: pd.DataFrame) -> List[str]:
    return sorted(set(panel["entity"].astype(str)))


def available_features(feats: pd.DataFrame) -> Iterable[str]:
    return [c for c in feats.columns if c not in ("ts", "symbol", "max_available_at")]
