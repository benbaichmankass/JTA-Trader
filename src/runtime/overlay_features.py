"""Point-in-time decision features for the real-money meta-label overlay (ML-REAL-MONEY-OVERLAY).

ONE function computes the overlay's feature row, and BOTH sides call it: the offline evaluation
(`scripts/research/ml_overlay_noninferior.py`, over each leg's Stage-0 candle CSV) and the live serve path
(the advisory scorer, over the leg's own closed candles). That is the serve-parity property by construction:
there is no second implementation to drift.

Point-in-time contract: ``bars`` holds the leg's OWN timeframe candles up to AND INCLUDING the decision bar
(the closed bar whose close is the entry price; verified on the RQ-20261024-09a6-01 corpus: entry == close of
the bar stamped ``entry_time`` on 2,627 / 2,627 trades). Nothing after that bar is read.

The feature set is fixed by the pre-registered unit (RULE-ML-OVERLAY-NONINFERIOR-V1); changing it is a new
configuration and must be counted, never a silent edit.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

FEATURES: tuple[str, ...] = (
    "dir_sign",            # +1 long / -1 short
    "adx14",               # Wilder ADX(14) / 100
    "atr_pct",             # ATR(14) / close
    "atr_pctl_200",        # percentile rank of atr_pct over the last 200 bars, in [0, 1]
    "ret20_signed",        # direction x log-return over 20 bars / (atr_pct x sqrt(20))
    "ret5_signed",         # direction x log-return over 5 bars / (atr_pct x sqrt(5))
    "dist_ma50_signed",    # direction x (close - SMA50) / ATR
    "vol_ratio_20_100",    # stdev(log-ret, 20) / stdev(log-ret, 100)
    "range_pos20_signed",  # where the close sits in the 20-bar range, measured in the trade's direction
)
MIN_BARS = 201  # 200-bar percentile window + the decision bar


def _wilder(vals: Sequence[float], n: int) -> list[float]:
    out: list[float] = []
    s = None
    for i, v in enumerate(vals):
        if i < n - 1:
            out.append(float("nan"))
            continue
        if s is None:
            s = sum(vals[i - n + 1:i + 1]) / n
        else:
            s = (s * (n - 1) + v) / n
        out.append(s)
    return out


def _std(xs: Sequence[float]) -> float:
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / max(len(xs) - 1, 1))


def decision_features(bars: Mapping[str, Sequence[float]], direction: str) -> dict[str, float] | None:
    """Feature row at the LAST bar of ``bars`` (keys high/low/close, oldest first). ``None`` when there is
    not enough history (fewer than MIN_BARS bars) or a value is not finite: the caller treats that as
    "not scored" (factor 1.0), never as a score."""
    h, lo, c = list(map(float, bars["high"])), list(map(float, bars["low"])), list(map(float, bars["close"]))
    n = len(c)
    if n < MIN_BARS or len(h) != n or len(lo) != n:
        return None
    d = 1.0 if str(direction).lower() in ("long", "buy", "1") else -1.0
    # Use only the trailing window that every feature needs (ADX warm-up included) so serve cost is flat.
    w = 400
    h, lo, c = h[-w:], lo[-w:], c[-w:]
    m = len(c)
    tr = [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, m)]
    pdm = [0.0] + [max(h[i] - h[i - 1], 0.0) if (h[i] - h[i - 1]) > (lo[i - 1] - lo[i]) else 0.0
                   for i in range(1, m)]
    ndm = [0.0] + [max(lo[i - 1] - lo[i], 0.0) if (lo[i - 1] - lo[i]) > (h[i] - h[i - 1]) else 0.0
                   for i in range(1, m)]
    atr = _wilder(tr, 14)
    sp, sn = _wilder(pdm, 14), _wilder(ndm, 14)
    dx = []
    for a, p_, q_ in zip(atr, sp, sn):
        if not (a == a) or a <= 0:
            dx.append(float("nan"))
            continue
        pdi, ndi = 100 * p_ / a, 100 * q_ / a
        dx.append(100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) > 0 else 0.0)
    dx_valid = [x for x in dx if x == x]
    adx = _wilder(dx_valid, 14)[-1] if len(dx_valid) >= 14 else float("nan")
    atr_last = atr[-1]
    close = c[-1]
    atr_pct_series = [a / cc for a, cc in zip(atr[-200:], c[-200:])]
    atr_pct = atr_last / close
    pctl = sum(1 for x in atr_pct_series if x <= atr_pct) / len(atr_pct_series)
    lr = [math.log(c[i] / c[i - 1]) for i in range(1, m)]
    r20 = math.log(close / c[-21])
    r5 = math.log(close / c[-6])
    sma50 = sum(c[-50:]) / 50
    hi20, lo20 = max(h[-20:]), min(lo[-20:])
    rp = (close - lo20) / (hi20 - lo20) if hi20 > lo20 else 0.5
    row = {
        "dir_sign": d,
        "adx14": adx / 100.0,
        "atr_pct": atr_pct,
        "atr_pctl_200": pctl,
        "ret20_signed": d * r20 / (atr_pct * math.sqrt(20)),
        "ret5_signed": d * r5 / (atr_pct * math.sqrt(5)),
        "dist_ma50_signed": d * (close - sma50) / atr_last,
        "vol_ratio_20_100": _std(lr[-20:]) / _std(lr[-100:]),
        "range_pos20_signed": rp if d > 0 else 1.0 - rp,
    }
    if not all(isinstance(v, float) and math.isfinite(v) for v in row.values()):
        return None
    return row


def score_overlay(model: Mapping[str, Any], row: Mapping[str, float]) -> float:
    """P(win) from an exported overlay artifact (standardised L2-logistic: features, mean, std, coef,
    intercept). Pure arithmetic, no sklearn at serve time."""
    z = float(model["intercept"])
    for f, mu, sd, b in zip(model["features"], model["mean"], model["std"], model["coef"]):
        z += float(b) * ((float(row[f]) - float(mu)) / (float(sd) or 1.0))
    return 1.0 / (1.0 + math.exp(-z))


def overlay_multiplier(model: Mapping[str, Any], row: Mapping[str, float] | None) -> float:
    """REDUCE-ONLY: the artifact's fixed multiplier when P(win) < tau, else 1.0. Never > 1.0, never 0 unless
    the artifact itself declares a veto multiplier; an unscored row is 1.0."""
    if row is None:
        return 1.0
    mult = min(max(float(model["multiplier"]), 0.0), 1.0)
    return mult if score_overlay(model, row) < float(model["tau"]) else 1.0
