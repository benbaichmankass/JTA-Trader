#!/usr/bin/env python3
# wiring: scripts/research/ml_entry_alpaca_score.py --structure-pivot (unit RQ-20261102-5e03-01) and, later, the ml_entry_levers structure units (row STRUCTURE-EXITS-DEFAULT)
"""Structure-based SL/TP arm for the first-passage ML entry harness (row STRUCTURE-EXITS-DEFAULT).

``ml_entry_levers.label_cell`` labels every decision bar with a FIXED ATR bracket via
``ml_decision_entry.bracket_outcome``. This is the same labeller with the bracket
taken from causal market structure instead: SL beyond the last CONFIRMED swing
(minus an ATR buffer, distance clamped to [0.5, 3.0] x the declared ATR stop),
TP at the nearest opposing swing / unfilled FVG edge >= ``min_r`` R, SL ratcheting
toward price and TP extend-only as new levels confirm (src/runtime/structure_levels.py,
the SAME code the trend/pullback harnesses and the live monitor import).

Same clock, same cost stack, same columns as ``label_cell`` -- so it drops into any
ml_entry_levers unit. Per-trade risk differs from the fixed bracket, so the output
carries ``risk_r_unit`` (price distance of 1R for that trade) and gross/net are in
that trade's own R, exactly as the other arms' R is in theirs. Tie -> SL; gap
through the stop fills at the open (same as ``bracket_outcome``).

Trades with no confirmed adverse swing (or an unusable stop) fall back to the
declared ATR bracket and are flagged ``fallback=1`` so the caller can report them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ml_decision_entry as E  # noqa: E402
from src.runtime.structure_levels import StructureExit, StructureLevels  # noqa: E402


def structure_outcome(levels: StructureLevels, o, h, lo, c, cand, entry, atr, side: int, *,
                      sl_atr: float, tp_atr: float, buffer_atr: float = 0.25,
                      min_r: float = 1.0, fvg: bool = True, t_map=None):
    """Per-candidate walk. o/h/lo/c are (N, H) windows of bars t+1..t+H; ``cand`` the decision-bar
    index t (structure is read as of t's close). ``t_map`` (optional, len = bars) maps a bar index to the
    index of the LAST COMPLETED structure bar known at that bar -- e.g. hourly bars reading DAILY levels as of the previous
    session -- default identity. Returns (px, j[1..H], reason 0/1/2, risk, fallback)."""
    n, H = o.shape
    px = np.empty(n)
    jj = np.empty(n, dtype=int)
    rs = np.zeros(n, dtype=np.int8)
    risk = np.empty(n)
    fb = np.zeros(n, dtype=np.int8)
    for k in range(n):
        t0, e, a = int(cand[k]), float(entry[k]), float(atr[k])
        tm = (lambda b: b) if t_map is None else (lambda b: int(t_map[b]))
        t = tm(t0)
        if not np.isfinite(a) or t < 0:        # no completed structure bar yet: no read
            px[k], jj[k], rs[k], risk[k], fb[k] = np.nan, H, 0, np.nan, 1
            continue
        sx = StructureExit.start(levels, t, e, side > 0, a, sl_atr * a, buffer_atr=buffer_atr,
                                 min_r=min_r, fvg=fvg)
        if sx is None:                       # declared ATR bracket for this trade
            fb[k] = 1
            sl, r = e - side * sl_atr * a, sl_atr * a
            tp = e + side * tp_atr * a
            sx = None
        else:
            sl, r, tp = sx.sl, sx.risk, sx.tp
        risk[k] = r
        px[k], jj[k], rs[k] = c[k, H - 1], H, 0
        for j in range(H):
            if side > 0:
                if lo[k, j] <= sl:
                    px[k], jj[k], rs[k] = min(sl, o[k, j]), j + 1, 1
                    break
                if tp is not None and h[k, j] >= tp:
                    px[k], jj[k], rs[k] = tp, j + 1, 2
                    break
            else:
                if h[k, j] >= sl:
                    px[k], jj[k], rs[k] = max(sl, o[k, j]), j + 1, 1
                    break
                if tp is not None and lo[k, j] <= tp:
                    px[k], jj[k], rs[k] = tp, j + 1, 2
                    break
            if sx is not None:               # bar t+1+j has CLOSED: levels bind from the next bar
                sl, tp = sx.on_bar_close(tm(t0 + 1 + j), float(c[k, j]), sl, tp, e)
    return px, jj, rs, risk, fb


def label_cell_structure(df: pd.DataFrame, pivot_n: int, sl: float = E.SL_ATR, tp: float = E.TP_ATR, *,
                         buffer_atr: float = 0.25, min_r: float = 1.0, fvg: bool = True,
                         sides=("long", "short")) -> pd.DataFrame:
    """``ml_entry_levers.label_cell`` with the bracket from structure. ``sl``/``tp`` are the DECLARED
    ATR bracket (the clamp reference and the no-swing fallback)."""
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    atr = pd.Series(tr).rolling(E.ATR_N, min_periods=E.ATR_N).mean().to_numpy()
    ts = df["ts"]
    close_hour = (ts + pd.Timedelta(hours=1)).dt.hour.to_numpy()
    N, H = len(df), E.HORIZON_H
    cand = np.where((close_hour % E.DECISION_EVERY_H == 0) & ~np.isnan(atr))[0]
    cand = cand[cand + H < N]
    t_ns = ts.to_numpy().astype("datetime64[ns]").astype("int64")
    cand = cand[(t_ns[cand + H] - t_ns[cand]) == H * 3_600_000_000_000]
    win = cand[:, None] + np.arange(1, H + 1)[None, :]
    Ob, Hh, Lb, Cb = o[win], h[win], lo[win], c[win]
    entry, a = Ob[:, 0], atr[cand]
    levels = StructureLevels(h, lo, pivot_n)
    out = {"i": cand}
    t_entry_s = t_ns[cand + 1] / 1e9
    for name, side in (("long", 1), ("short", -1)):
        if name not in sides:
            continue
        px, j, reason, risk, fb = structure_outcome(levels, Ob, Hh, Lb, Cb, cand, entry, a, side, sl_atr=sl,
                                                    tp_atr=tp, buffer_atr=buffer_atr, min_r=min_r, fvg=fvg)
        gross = side * (px - entry) / risk
        fee, slip, fund = E._cost_r(entry, px, risk, t_entry_s, t_ns[cand + j] / 1e9 + 3600.0)
        out[f"gross_{name}"], out[f"net_{name}"] = gross, gross - fee - slip - fund
        out[f"cost_{name}"], out[f"reason_{name}"], out[f"bars_{name}"] = fee + slip + fund, reason, j
        out[f"risk_r_unit_{name}"], out[f"fallback_{name}"] = risk, fb
    return pd.DataFrame(out)
