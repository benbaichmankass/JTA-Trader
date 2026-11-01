#!/usr/bin/env python3
# wiring: manual-only - helper imported by RESEARCH-EDGE study scripts; the evaluation standard is in .claude/skills/backtesting/SKILL.md (not a CI guard).
"""Regime-robustness clause (operator 2026-11-01): per-year table, concentration, long/short split, sub-period signs."""
from __future__ import annotations
import pandas as pd

MIN_DAYS = 200   # calendar days of data for a year to count


def clause(net: pd.Series, long_net: pd.Series | None = None, short_net: pd.Series | None = None, two_sided: bool = True, subperiods: int = 2) -> dict:
    """net/long_net/short_net: daily fractional returns. Returns the table and each item's pass flag (None = not applicable)."""
    net = net.dropna()
    yrs = {}
    for y, g in net.groupby(net.index.year):
        span = (g.index[-1] - g.index[0]).days + 1
        yrs[int(y)] = {"net": round(float((1 + g).prod() - 1), 4), "pnl_sum": float(g.sum()), "days": int(len(g)), "counts": span >= MIN_DAYS}
    counted = {y: v for y, v in yrs.items() if v["counts"]}
    npos = sum(1 for v in counted.values() if v["pnl_sum"] > 0)
    need = 3 if len(counted) <= 4 else max(3, int(-(-0.75 * len(counted) // 1)))
    total = sum(v["pnl_sum"] for v in counted.values())
    top = max((v["pnl_sum"] for v in counted.values()), default=0.0)
    out = {"per_year": {y: {"net": v["net"], "counted": v["counts"]} for y, v in yrs.items()},
           "years_positive": f"{npos} of {len(counted)} (need {need})", "years_ok": npos >= need,
           "top_year_share_of_total": round(top / total, 3) if total > 0 else None, "concentration_ok": bool(total > 0 and top / total <= 0.5)}
    if long_net is not None and short_net is not None:
        ln, sn = float(long_net.sum()), float(short_net.sum())
        out["long_net_sum"], out["short_net_sum"] = round(ln, 4), round(sn, 4)
        out["sides_ok"] = (ln >= 0 and sn >= 0) if two_sided else None
    else:
        out["sides_ok"] = None
    n = len(net); k = max(2, subperiods); cuts = [net.iloc[i * n // k:(i + 1) * n // k] for i in range(k)]
    out["subperiod_sums"] = [round(float(c.sum()), 4) for c in cuts]; out["subperiods_ok"] = all(c.sum() > 0 for c in cuts)
    flags = [out["years_ok"], out["concentration_ok"], out["subperiods_ok"]] + ([out["sides_ok"]] if out["sides_ok"] is not None else [])
    out["clause_pass"] = all(flags)
    return out


def split_sides(W, ret, F, side_bps):
    """Long-side and short-side daily net (price pnl - funding - per-side cost on |delta w| of that side)."""
    def one(Wx):
        return (Wx * ret.reindex_like(Wx).fillna(0) - Wx * F.reindex_like(Wx).fillna(0) - Wx.diff().abs().fillna(0) * side_bps / 1e4).sum(axis=1)
    return one(W.clip(lower=0)), one(W.clip(upper=0))
