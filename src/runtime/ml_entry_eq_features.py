"""Serving features for the EQUITY-NATIVE ENTRY model ``ml_entry_eq`` (row ML-ENTRY-EQUITY-NATIVE; Tier 1 pure module, no I/O except the snapshot file).

The SERVING copy of ``scripts/research/ml_entry_equity.build_table`` for config B (15 own-symbol features + 6 pool features; NO market-proxy and NO crypto
feature). The own-symbol part reuses ``src.runtime.ml_decision_features.features_symbol`` (already pinned to the research harness); the pool part
(``xs_rank_ret24``, ``xs_rank_ret168``, ``xs_rank_vol24``, ``xs_rank_volz``, ``breadth_up24``, ``rel_vol``) is computed ACROSS the 173-ETF pool at one
decision close. Parity with the harness is pinned by ``tests/test_ml_entry_eq_features.py`` (same bars in, same numbers out).

THE POOL SNAPSHOT (spec docs/research/ml-entry-eq-serve-spec-2026-11-06.md § 4): the pool features need every ETF's bars at the decision close, which
must NEVER be fetched inside a signal tick (MEASURED in #23619: one unpaced 173-symbol pass = 217 calls, 104 x 429). A separate refresher builds ONE
snapshot per closed RTH bar with ``build_snapshot`` and writes it with ``write_snapshot``; the signal builder only calls ``read_snapshot`` (a local file).
A stale or incomplete snapshot is a named per-trade refusal, never a halt.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from src.runtime.ml_decision_features import features_symbol

SCHEMA = "ml_entry_eq_snapshot/1"
OWN = ["ret_1", "ret_4", "ret_12", "ret_24", "ret_72", "ret_168", "vol24", "vol_ratio", "atr_pct", "range_pos_24",
       "range_pos_168", "vol_z", "rsi14", "hour", "dow"]
POOL = ["xs_rank_ret24", "xs_rank_ret168", "xs_rank_vol24", "xs_rank_volz", "breadth_up24", "rel_vol"]
FEATURES_B = OWN + POOL
MIN_BARS = 169 + 168            # the same warm-up as the v1 serving module (ret_168 / vol_z windows)
MIN_COVERAGE = 0.80             # share of the pool that must be present in a snapshot
REFUSE_STALE = "pool_snapshot_stale"
REFUSE_INCOMPLETE = "pool_incomplete"
REFUSE_MISSING = "pool_snapshot_missing"


def rth_close_ts(ts: pd.Series) -> pd.Series:
    """Close time of an Alpaca hour-aligned RTH bar: open + 1h capped at the 16:00 ET session close (as ``rth_hourly`` in the harness)."""
    t = pd.to_datetime(ts, utc=True)
    et = t.dt.tz_convert("America/New_York")
    session_close = (et.dt.normalize() + pd.Timedelta(hours=16)).dt.tz_convert("UTC")
    return pd.concat([t + pd.Timedelta(hours=1), session_close], axis=1).min(axis=1)


def own_last_row(df: pd.DataFrame) -> Optional[Dict[str, float]]:
    """The 15 own features (+ the raw 24/168-bar returns the pool ranks need) at the LAST bar of ``df`` (closed RTH 1h bars: ts open, open, high, low,
    close, volume), or None when the history is shorter than ``MIN_BARS``."""
    if df is None or len(df) < MIN_BARS:
        return None
    df = df.reset_index(drop=True)
    f = features_symbol(df[["ts", "open", "high", "low", "close", "volume"]])
    close_ts = rth_close_ts(df["ts"])
    f["hour"] = close_ts.dt.hour.to_numpy()
    f["dow"] = close_ts.dt.day_of_week.to_numpy()
    last = f.iloc[-1]
    c = df["close"].astype(float)
    row = {k: float(last[k]) for k in OWN}
    row["ret24_raw"] = float(np.log(c.iloc[-1]) - np.log(c.iloc[-25]))
    row["ret168_raw"] = float(np.log(c.iloc[-1]) - np.log(c.iloc[-169]))
    row["_close_ts"] = close_ts.iloc[-1]
    return row


def pool_features(rows: Mapping[str, Mapping[str, float]]) -> Dict[str, Dict[str, float]]:
    """Pool features per symbol from each symbol's ``own_last_row`` at the SAME close (pandas pct ranks, as ``groupby('ts').rank(pct=True)`` in the harness)."""
    if not rows:
        return {}
    d = pd.DataFrame({s: r for s, r in rows.items()}).T
    out = pd.DataFrame(index=d.index)
    out["xs_rank_ret24"] = d["ret24_raw"].astype(float).rank(pct=True)
    out["xs_rank_ret168"] = d["ret168_raw"].astype(float).rank(pct=True)
    out["xs_rank_vol24"] = d["vol24"].astype(float).rank(pct=True)
    out["xs_rank_volz"] = d["vol_z"].astype(float).rank(pct=True)
    out["breadth_up24"] = float((d["ret24_raw"].astype(float) > 0).mean())
    out["rel_vol"] = d["vol24"].astype(float) / float(d["vol24"].astype(float).median())
    return {s: {k: float(out.loc[s, k]) for k in POOL} for s in out.index}


def build_snapshot(bars_by_symbol: Mapping[str, pd.DataFrame], pool_size: int, bar_close: Optional[pd.Timestamp] = None) -> Dict[str, Any]:
    """ONE snapshot for the decision close: every pool symbol whose last bar closes at ``bar_close`` (default: the modal last close) and has enough
    history contributes its 21 config-B features. ``covered``/``pool_size`` let the reader refuse an incomplete one."""
    rows: Dict[str, Dict[str, float]] = {}
    for s, df in bars_by_symbol.items():
        r = own_last_row(df)
        if r is not None:
            rows[s] = r
    if not rows:
        return {"schema": SCHEMA, "bar_close": None, "pool_size": int(pool_size), "covered": 0, "symbols": {}}
    closes = pd.Series({s: r["_close_ts"] for s, r in rows.items()})
    bc = pd.Timestamp(bar_close) if bar_close is not None else closes.mode().iloc[0]
    rows = {s: r for s, r in rows.items() if closes[s] == bc}
    pf = pool_features(rows)
    syms = {s: {**{k: rows[s][k] for k in OWN}, **pf[s]} for s in rows}
    return {"schema": SCHEMA, "bar_close": pd.Timestamp(bc).isoformat(), "pool_size": int(pool_size), "covered": len(syms), "symbols": syms}


def write_snapshot(path: Path, snap: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(snap), encoding="utf-8")
    os.replace(tmp, path)


def read_snapshot(path: Path, now: pd.Timestamp, max_age_h: float = 4.0, min_coverage: float = MIN_COVERAGE) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(snapshot, None) or (None, refusal_reason). LOCAL FILE ONLY: no network, safe on the signal tick. Never raises."""
    try:
        snap = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- a missing/corrupt file is a named refusal, not a crash
        return None, REFUSE_MISSING
    if snap.get("schema") != SCHEMA or not snap.get("bar_close"):
        return None, REFUSE_MISSING
    age_h = (pd.Timestamp(now) - pd.Timestamp(snap["bar_close"])) / pd.Timedelta(hours=1)
    if age_h > max_age_h:
        return None, REFUSE_STALE
    if snap.get("pool_size") and snap.get("covered", 0) < min_coverage * snap["pool_size"]:
        return None, REFUSE_INCOMPLETE
    return snap, None


def feature_vector(snap: Mapping[str, Any], symbol: str, features=FEATURES_B) -> Optional[Dict[str, float]]:
    s = (snap.get("symbols") or {}).get(symbol)
    return None if s is None else {k: float(s[k]) for k in features}
