#!/usr/bin/env python3
# wiring: .github/workflows/market-data-lake.yml (after each capture shard) -> validate.py -> hf_publish.py
"""Deterministic resampler: higher timeframes are DERIVED from the stored base (1m), never fetched separately.

Operator 2026-11-01: "we should also be keeping the smallest timeframe data available - we can always reconstruct
higher timeframes on top of that". Row MARKET-DATA-LAKE.

For every base partition <out>/<asset>/<market>/<base>/<SYM>/<YYYY-MM>.parquet present in --out (i.e. built or rebuilt
this run), writes ONE <out>/<asset>/<market>/derived/<SYM>/<partition>.parquet holding every target tf (column `tf`). A calendar month is a whole
number of every target bar (5m..1d all divide 00:00 UTC), so a month partition resamples on its own, exactly.

RULES (identical for every symbol, every run)
  * bars are left-closed, labelled at their OPEN (same convention as the base);
  * open = first, high = max, low = min, close = last; volume / quote_volume / trades / taker_* = sum;
  * a bar is emitted only if at least one base bar exists inside it (no forward fill);
  * ``n_base`` = number of base bars in the bar, ``complete`` = n_base == tf/base -- consumers see thin or partial
    bars (the still-open last bar of a refresh, or a bar with archive gaps) instead of a silently "normal" one.

    python3 scripts/data_lake/resample.py --out lake --base 1m --tfs 5m,15m,1h,4h,1d
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd

MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
SUM_COLS = ["volume", "quote_volume", "trades", "taker_buy_volume", "taker_buy_quote_volume"]


def resample_frame(df: pd.DataFrame, base: str, tf: str) -> pd.DataFrame:
    if df.empty:
        return df
    rule = f"{MINUTES[tf]}min"
    g = df.set_index("ts").sort_index()
    agg: Dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last"}
    for c in SUM_COLS:
        if c in g.columns:
            agg[c] = "sum"
    r = g.resample(rule, label="left", closed="left")
    out = r.agg(agg)
    out["n_base"] = r["close"].count()
    out = out[out["n_base"] > 0].copy()
    out["complete"] = out["n_base"] == (MINUTES[tf] // MINUTES[base])
    out["n_base"] = out["n_base"].astype("int32")
    return out.reset_index()


def run(out: Path, base: str, tfs: List[str]) -> List[Dict]:
    """One DERIVED file per base partition, holding every target tf (column ``tf``), so derived data adds one file per
    partition, not one per timeframe (HF repo file budget). Manifest entries stay per tf, pointing at the shared file
    with ``tf_col``; ml/datasets/lake.py filters on it."""
    entries: Dict[tuple, Dict] = {}
    bases = sorted(out.glob(f"*/*/{base}/*/*.parquet"))
    for p in bases:
        asset, market, _, sym, fname = p.relative_to(out).parts
        df = pd.read_parquet(p)
        frames = []
        for tf in tfs:
            d = resample_frame(df, base, tf)
            if not d.empty:
                d.insert(1, "tf", tf)
                frames.append(d)
        if not frames:
            continue
        allv = pd.concat(frames, ignore_index=True)
        q = out / asset / market / "derived" / sym / fname
        q.parent.mkdir(parents=True, exist_ok=True)
        allv.to_parquet(q, index=False, compression="zstd", row_group_size=200_000)
        pkey = fname[:-8]
        for tf, d in allv.groupby("tf", sort=False):
            key = (asset, market, tf, sym)
            e = entries.setdefault(key, {"asset_class": asset, "market": market, "tf": tf, "symbol": sym,
                                         "derived_from": base, "source": "resample.py", "tf_col": "tf",
                                         "partitions": {}, "state": "ok"})
            e["partitions"][pkey] = {"rows": int(len(d)), "first": d["ts"].iloc[0].isoformat(),
                                     "last": d["ts"].iloc[-1].isoformat(),
                                     # the file is shared by every tf: apportion its bytes by row share (no double count)
                                     "bytes": int(q.stat().st_size * len(d) / len(allv)),
                                     "incomplete_bars": int((~d["complete"]).sum()),
                                     "path": str(q.relative_to(out)), "src": "derived"}
    return list(entries.values())


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="lake")
    ap.add_argument("--base", default="1m")
    ap.add_argument("--tfs", default="5m,15m,1h,4h,1d")
    ap.add_argument("--tag", default="resample")
    a = ap.parse_args(argv)
    out = Path(a.out)
    entries = run(out, a.base, [t for t in a.tfs.split(",") if t])
    (out / "_manifests").mkdir(parents=True, exist_ok=True)
    (out / "_manifests" / f"derived-{a.tag}.json").write_text(json.dumps(entries, indent=1))
    print(f"[resample] {len(entries)} derived series from base {a.base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
