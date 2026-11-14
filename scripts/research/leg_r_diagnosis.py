#!/usr/bin/env python3
"""Where does a leg's R go? -- the diagnosis behind an iteration unit (row DEMO-FLOOR-ITER-20261113).

The research-ops iteration procedure (.claude/skills/research-ops/SKILL.md, "How to run an iteration") starts from the
FAILED result's own rows: which trades, regimes and months lost; gross vs net; entry vs exit vs filter. This reads one or
more Stage-0 trades JSONL files (the harness rows a faithful evidence record's ``source_run`` points at) and splits NET R
the same way for every leg, so the lever an iteration unit picks is chosen from the same evidence each time:

  folds      N equal CALENDAR folds of [first entry, last entry] (default 6) -- is the loss everywhere or one stretch?
  direction  long vs short
  regime     ADX-14 at entry, live cut points 20 / 25 (adx_at_entry from the row; else computed on --candles-csv)
  exit       exit_reason (stop vs target vs timeout vs signal ...)
  hour       UTC entry hour, grouped in 4 h blocks (a session effect)
  cost       net vs fee-only vs gross: how much of the loss is the cost stack, and which part (fee / slippage / funding)
  mfe        where the row carries mfe_r: R given back from the best excursion (exit inefficiency) vs never-in-profit

Every split reports n, net R sum, mean and the share of the total loss it carries. Read-only; writes only --out.
Tier 1: research tooling.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

ADX_CUTS = (20.0, 25.0)   # the live regime attribution cut points (regime_adx_cutpoint_sweep.py: "live 20/25")


def load_rows(paths: List[str]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    if "exit_time" in df:
        df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True, errors="coerce")
    for c in ("net_r", "net_r_fee_only", "gross_r", "cost_fee_r", "cost_slippage_r", "cost_funding_r", "mfe_r",
              "adx_at_entry"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("entry_time").reset_index(drop=True)


def adx14(candles: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX on timestamp/open/high/low/close; indexed by bar timestamp (the bar's OPEN)."""
    hi, lo, c = candles["high"], candles["low"], candles["close"]
    up, dn = hi.diff(), -lo.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([hi - lo, (hi - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    a = 1.0 / period
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=candles.index).ewm(alpha=a, adjust=False).mean() / atr
    ndi = 100 * pd.Series(ndm, index=candles.index).ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean()


def attach_adx(df: pd.DataFrame, candles_csv: Optional[str]) -> str:
    """Fill adx_at_entry where missing, from the last CLOSED bar before entry. Returns where it came from."""
    have = "adx_at_entry" in df and df["adx_at_entry"].notna().all()
    if have:
        return "row"
    if not candles_csv:
        return "unavailable"
    cd = pd.read_csv(candles_csv)
    cd["timestamp"] = pd.to_datetime(cd["timestamp"], utc=True)
    cd = cd.sort_values("timestamp").set_index("timestamp")
    adx = adx14(cd)
    step = cd.index.to_series().diff().median()
    closed = adx.copy()
    closed.index = closed.index + step          # ADX known at the bar's CLOSE
    pos = closed.index.searchsorted(df["entry_time"], side="right") - 1
    # A trade that enters after the bars end would otherwise take the LAST bar's ADX (searchsorted clamps to the
    # final index): a stale tag, not a reading. Past the last close + one bar it stays NaN ("unknown").
    horizon = closed.index[-1] + step if len(closed) else None
    vals = [float(closed.iloc[i]) if i >= 0 and (horizon is None or t <= horizon) else np.nan
            for i, t in zip(pos, df["entry_time"])]
    if "adx_at_entry" in df:
        df["adx_at_entry"] = df["adx_at_entry"].fillna(pd.Series(vals, index=df.index))
    else:
        df["adx_at_entry"] = vals
    return f"computed: ADX-14 on {Path(candles_csv).name}, last closed bar before entry"


def regime(x: float) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "unknown"
    return "adx<20" if x < ADX_CUTS[0] else ("adx20-25" if x < ADX_CUTS[1] else "adx>=25")


def split(df: pd.DataFrame, key: pd.Series, total_loss: float) -> List[Dict[str, Any]]:
    out = []
    for k, g in df.groupby(key, sort=True):
        s = float(g["net_r"].sum())
        out.append({"key": str(k), "n": int(len(g)), "net_r": round(s, 3), "mean_r": round(float(g["net_r"].mean()), 4),
                    "win_rate": round(float((g["net_r"] > 0).mean()), 3),
                    "loss_share": round(s / total_loss, 3) if total_loss < 0 and s < 0 else None})
    return out


def diagnose(df: pd.DataFrame, *, folds: int = 6, candles_csv: Optional[str] = None) -> Dict[str, Any]:
    if df.empty:
        return {"read_state": "no_data", "n": None}
    total = float(df["net_r"].sum())
    adx_src = attach_adx(df, candles_csv)
    lo, hi = df["entry_time"].min(), df["entry_time"].max()
    edges = pd.date_range(lo, hi, periods=folds + 1)
    fold = pd.Series(np.clip(np.searchsorted(edges, df["entry_time"], side="right") - 1, 0, folds - 1), index=df.index)
    rep: Dict[str, Any] = {
        "read_state": "measured", "n": int(len(df)), "net_r": round(total, 3), "mean_r": round(total / len(df), 4),
        "win_rate": round(float((df["net_r"] > 0).mean()), 3),
        "window": [str(lo), str(hi)],
        "folds": split(df, fold.map(lambda i: f"F{i + 1}"), total),
        "folds_positive": int(sum(1 for f in split(df, fold, total) if f["net_r"] > 0)),
        "direction": split(df, df["direction"].astype(str), total) if "direction" in df else None,
        "regime": split(df, df["adx_at_entry"].map(regime), total) if "adx_at_entry" in df else None,
        "regime_source": adx_src,
        "exit": split(df, df["exit_reason"].astype(str), total) if "exit_reason" in df else None,
        "hour_utc": split(df, (df["entry_time"].dt.hour // 4 * 4).map(lambda h: f"{h:02d}-{h + 4:02d}h"), total),
    }
    # cost stack: gross -> fee-only -> net. A row without gross_r reports what it carries, never a guess.
    cost: Dict[str, Any] = {"net_r": round(total, 3)}
    if "net_r_fee_only" in df:
        cost["net_r_fee_only"] = round(float(df["net_r_fee_only"].sum()), 3)
    for c in ("cost_fee_r", "cost_slippage_r", "cost_funding_r"):
        if c in df:
            cost[c] = round(float(df[c].sum()), 3)
    if "gross_r" in df and df["gross_r"].notna().all():
        g = float(df["gross_r"].sum())
        cost["gross_r"] = round(g, 3)
        cost["cost_total_r"] = round(g - total, 3)
        cost["gross_positive"] = g > 0
        cost["reading"] = ("the strategy loses before costs (gross <= 0): an ENTRY/EXIT problem, not a cost problem"
                           if g <= 0 else "gross positive, net negative: the cost stack eats the edge -- a sizing/cost lever"
                           if total <= 0 else "net positive")
    else:
        cost["gross_r"] = None
        cost["reading"] = "gross_r not emitted by this harness: the fee share is unmeasured (net and slippage/funding only)"
    rep["cost"] = cost
    if "mfe_r" in df and df["mfe_r"].notna().any():
        m = df.dropna(subset=["mfe_r"])
        losers = m[m["net_r"] <= 0]
        rep["mfe"] = {
            "n": int(len(m)),
            "mean_mfe_r": round(float(m["mfe_r"].mean()), 3),
            "giveback_r_total": round(float((m["mfe_r"] - m["net_r"]).clip(lower=0).sum()), 3),
            "losers_that_reached_1r": int((losers["mfe_r"] >= 1.0).sum()),
            "losers_never_positive": int((losers["mfe_r"] <= 0.05).sum()),
            "losers_n": int(len(losers)),
        }
    else:
        rep["mfe"] = None
    if "exit_time" in df and df["exit_time"].notna().any():
        hold = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 3600
        rep["hold_hours"] = {"median": round(float(hold.median()), 2), "winners_median": round(float(hold[df["net_r"] > 0].median()), 2)
                             if (df["net_r"] > 0).any() else None,
                             "losers_median": round(float(hold[df["net_r"] <= 0].median()), 2) if (df["net_r"] <= 0).any() else None}
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--trades", action="append", default=[], help="trades JSONL (repeatable)")
    ap.add_argument("--leg", help="label for the report")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--candles-csv", help="leg-timeframe candles, to compute ADX where rows lack adx_at_entry")
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.trades:
        ap.error("--trades is required")
    rep = {"leg": a.leg, **diagnose(load_rows(a.trades), folds=a.folds, candles_csv=a.candles_csv)}
    txt = json.dumps(rep, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)
    return 0


def _self_test() -> int:
    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            raise SystemExit(1)
    t = pd.date_range("2025-01-01", periods=60, freq="1D", tz="UTC")
    rows = [{"entry_time": str(x), "direction": "long" if i % 2 else "short", "net_r": (-1.0 if i % 2 else 0.5),
             "gross_r": (-0.9 if i % 2 else 0.6), "net_r_fee_only": (-0.95 if i % 2 else 0.55), "exit_reason": "sl" if i % 2 else "tp",
             "adx_at_entry": 18.0 if i < 30 else 30.0, "mfe_r": 1.2 if i % 4 == 1 else 0.0} for i, x in enumerate(t)]
    df = pd.DataFrame(rows)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    r = diagnose(df, folds=6)
    check("totals: 30 longs at -1, 30 shorts at +0.5 -> -15", r["net_r"] == -15.0 and r["n"] == 60)
    d = {x["key"]: x for x in r["direction"]}
    check("direction split carries the loss", d["long"]["net_r"] == -30.0 and d["long"]["loss_share"] == 2.0)
    check("regime from the row", r["regime_source"] == "row" and {x["key"] for x in r["regime"]} == {"adx<20", "adx>=25"})
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        bars = Path(td) / "b.csv"
        ts = pd.date_range("2024-01-01", periods=60, freq="h", tz="UTC")
        pd.DataFrame({"timestamp": ts, "open": range(60), "high": [x + 1.5 for x in range(60)],
                      "low": [x - 0.5 for x in range(60)], "close": [x + 1.0 for x in range(60)]}).to_csv(bars, index=False)
        late = pd.DataFrame({"entry_time": pd.to_datetime(["2024-01-02T06:00:00Z", "2024-03-01T00:00:00Z"], utc=True)})
        attach_adx(late, str(bars))
        check("attach_adx: inside the bars -> a value; past the bars' end -> NaN, not the last bar's ADX",
              not np.isnan(late["adx_at_entry"].iloc[0]) and np.isnan(late["adx_at_entry"].iloc[1]))
    check("gross <= 0 reads as an entry/exit problem", r["cost"]["gross_positive"] is False and "ENTRY/EXIT" in r["cost"]["reading"])
    check("six calendar folds", len(r["folds"]) == 6)
    check("mfe: losers that reached 1R counted", r["mfe"]["losers_that_reached_1r"] == 15)
    no_gross = df.drop(columns=["gross_r"])
    check("no gross_r -> fee share unmeasured, never guessed", diagnose(no_gross)["cost"]["gross_r"] is None)
    check("empty -> no_data, n null", diagnose(pd.DataFrame())["n"] is None)
    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
