"""The ml_entry MOVING-TP policy, serving copy (row ML-ENTRY-TP-REVISION; unit RQ-20261101-383f-01; Tier 3 when declared).

At each 4h check-in of an open ml_entry position (4, 8, 12, 16, 20 closed 1h bars after the decision bar), one pooled
LightGBM multiclass model predicts the FIRST-PASSAGE outcome of the rest of the trade over a fixed TP grid (x ATR14 at
entry, from entry): 18 classes = (highest grid level touched before the stop, 0..8) x (stop hit). The expected net R
of each level follows from the class probabilities and the training rows' class means; the TP moves to the best valid
level iff it beats the resting TP by more than the dev-chosen margin. The SL is never touched.

Evidence + spec: ``research/results/RQ-20261101-383f-01/``, ``docs/research/ml-decision-models-2026-11-01/TP-REVISION.md``.
The research harness is ``scripts/research/ml_entry_tp_revision.py``; every function here is pinned to its harness twin
by ``tests/test_ml_entry_tp_revision_parity.py`` (same inputs, same numbers / same choice).

PURE except :func:`load_tp_model` (reads the served artifact, cached by mtime). Never places or sizes anything.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import numpy as np

ARTIFACT = Path(__file__).resolve().parents[2] / "ml" / "served" / "ml_entry_tp_revision_v1" / "model.json"
_CACHE: Dict[str, Any] = {}


def load_tp_model(path: Path = ARTIFACT) -> Dict[str, Any]:
    """``{"meta": ..., "booster": Booster}``, cached by mtime. Raises when the artifact is unreadable."""
    import lightgbm as lgb
    st = path.stat()
    hit = _CACHE.get(str(path))
    if hit and hit[0] == st.st_mtime:
        return hit[1]
    art = json.loads(path.read_text(encoding="utf-8"))
    model = {"meta": {k: v for k, v in art.items() if k != "booster_txt"},
             "booster": lgb.Booster(model_str=art["booster_txt"])}
    _CACHE[str(path)] = (st.st_mtime, model)
    return model


def expected_net_r(probs: Sequence[float], means: Sequence[float], level_cost_r: Sequence[float],
                   grid: Sequence[float], sl_atr: float) -> np.ndarray:
    """Expected net R of a TP at each grid level, from one row of 2*(len(grid)+1) class probabilities."""
    p, m = np.asarray(probs, float), np.asarray(means, float)
    G = len(grid) + 1
    p_free, p_stop, m_free, m_stop = p[:G], p[G:], m[:G], m[G:]
    out = np.empty(len(grid))
    for q in range(1, len(grid) + 1):
        p_tp = p_free[q:].sum() + p_stop[q:].sum()
        rest = (p_free[:q] * m_free[:q]).sum() + (p_stop[:q] * m_stop[:q]).sum()
        out[q - 1] = p_tp * (grid[q - 1] / sl_atr - level_cost_r[q - 1]) + rest
    return out


def valid_levels(side: int, entry: float, atr: float, close: float, grid: Sequence[float], min_gap_atr: float,
                 cap_pct: float) -> np.ndarray:
    """A level must rest >= ``min_gap_atr`` beyond the check-in close (never through price) and inside the venue cap."""
    lv = entry + side * np.asarray(grid, float) * atr
    return (side * (lv - close) >= min_gap_atr * atr) & (np.abs(lv - close) <= cap_pct * close)


def level_cost(entry: float, atr: float, side: int, grid: Sequence[float], sl_atr: float, fee_bps: float,
               slip_bps: float, fund_bps: float) -> np.ndarray:
    """Cost (R) of a TP fill at each level: fee + slippage on the mean price, funding at 1.5 windows."""
    risk = sl_atr * atr
    lv = entry + side * np.asarray(grid, float) * atr
    per_r = ((abs(entry) + np.abs(lv)) / 2.0) / risk
    return (fee_bps + slip_bps + 1.5 * fund_bps) / 1e4 * per_r


def choose(probs: Sequence[float], means: Sequence[float], *, side: int, entry: float, atr: float, close: float,
           resting_idx: int, grid: Sequence[float], sl_atr: float, min_gap_atr: float, cap_pct: float, margin: float,
           cost: Sequence[float]) -> Dict[str, Any]:
    """The policy at one check-in. ``{"move_to": idx | None, "ev": [...], "ev_resting": x, "ev_best": y}``."""
    ok = valid_levels(side, entry, atr, close, grid, min_gap_atr, cap_pct)
    ev = expected_net_r(probs, means, cost, grid, sl_atr)
    cand = np.where(ok, ev, -np.inf)
    best = int(np.argmax(cand))
    move = (best if (np.isfinite(cand[best]) and best != resting_idx and cand[best] - ev[resting_idx] > margin)
            else None)
    return {"move_to": move, "ev": [round(float(x), 5) for x in ev], "ev_resting": float(ev[resting_idx]),
            "ev_best": float(cand[best]) if np.isfinite(cand[best]) else None, "valid": [bool(x) for x in ok]}


def state_features(*, side: int, entry: float, atr_entry: float, sl: float, highs: Sequence[float],
                   lows: Sequence[float], close_now: float, atr_now: float, ret_4: float, ret_24: float,
                   bars_held: int, sl_atr: float) -> Dict[str, float]:
    """The 9 position-state features at a check-in. ``highs`` / ``lows``: the CLOSED bars after the decision bar up
    to and including the check-in bar (``bars_held`` of them)."""
    risk = sl_atr * atr_entry
    h, lo = np.asarray(highs, float), np.asarray(lows, float)
    fav = h.max() - entry if side > 0 else entry - lo.min()
    adv = lo.min() - entry if side > 0 else entry - h.max()
    return {"side": float(side), "bars_held": float(bars_held), "open_r": side * (close_now - entry) / risk,
            "mfe_r": fav / risk, "mae_r": adv / risk, "dist_sl_atr": side * (close_now - sl) / atr_entry,
            "atr_ratio": atr_now / atr_entry, "sret_4": side * ret_4, "sret_24": side * ret_24}


def class_probs(model: Mapping[str, Any], row: Mapping[str, float]) -> np.ndarray:
    """The full 18-vector of first-passage class probabilities for one feature row."""
    import pandas as pd
    meta = model["meta"]
    x = pd.DataFrame([[row[k] for k in meta["features"]]], columns=meta["features"])
    # provenance: predict — a multiclass Booster returns the class probabilities of the first-passage classes
    p = np.asarray(model["booster"].predict(x))[0]
    full = np.zeros(2 * (len(meta["grid_atr"]) + 1))
    full[list(meta["classes"])] = p
    return full


def grid_index(level_px: Optional[float], entry: float, atr: float, side: int, grid: Sequence[float],
               tol_atr: float = 0.02) -> Optional[int]:
    """The grid index a resting TP sits on, or None when it is off-grid (a clamp, a desk amend): could not look."""
    if level_px is None or not atr > 0:
        return None
    k = side * (float(level_px) - entry) / atr
    d = np.abs(np.asarray(grid, float) - k)
    i = int(np.argmin(d))
    return i if d[i] <= tol_atr else None
