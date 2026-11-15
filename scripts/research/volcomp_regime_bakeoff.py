#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-9b1e-01.yaml run.command ["python3","scripts/research/volcomp_regime_bakeoff.py",...]
#         via .github/workflows/research-script-run.yml (runner) or a local session run (same command)
"""VOLUME COMPOSITION -> REGIME-VOL HEAD: does adding the size/count surprise (ss, sn) to the shipped 15m regime-head
recipe improve it, beyond plain volume, in that head's own bake-off?

WHY (registered consequence of RQ-20261111-f5c8-02 PASS, row VOLUME-COMPOSITION-RESEARCH)
----------------------------------------------------------------------------------------
f5c8-02 found, at the 4h bar on 6 crypto perps, that a SIZE-led volume surprise carries held-out rank information on the
size of the next move beyond plain volume and the bar's range (partial rank IC -0.069, t -8.19, 27 months). Its
registered consequence is an ML feature-add unit judged by the consuming head's own bake-off. One passing univariate
unit is not a feature: this bake-off decides.

WHAT THIS DOES
--------------
1. Fetches Binance USD-M 15m klines (they carry the trade count; Bybit klines do not, so Binance PROXIES Bybit linear)
   for each symbol from the keyless public archive (data.binance.vision). Nothing is stored in the repo.
2. Feeds those bars as ``market_raw`` rows through the REAL ``MarketFeaturesBuilder.iter_rows`` with the fleet's 15m
   regime-head build parameters (vol_window_n 20, forward_window_m 5, vol_threshold 0.005, n_vol_buckets 3), so the
   champion's feature columns and ``regime_label`` come from the shipped builder, not a re-implementation.
3. Appends the composition features, all strictly past-only at bar t (bar t is closed when its row is scored):
     15m grain:  sv15 = log V - seasonal norm, sn15 = log N - norm, ss15 = log(V/N) - norm, where the norm is the mean
                 over the same 15m slot-of-day on the previous ``--season-days`` days (shifted one day inside a slot).
     4h grain:   the same over trailing 16-bar sums of V and N (the grain f5c8-02 measured), slot-of-day norm likewise.
4. Writes one CSV per symbol under ``--cache-dir`` and runs ``scripts/research/ml_bakeoff.py::run_spec`` on the unit's
   registered ``ml_bakeoff`` block with ``ML_DATA_ROOT`` pointed at that directory. verdict.json is ml_bakeoff's, plus a
   ``dataset_build`` block (coverage, row counts, label base rate). The arms' metrics are produced only by ml_bakeoff.

Tier-1 research tooling: reads public market data, writes only ``--out`` and ``--cache-dir``. No config, model,
registry or order path is touched.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts" / "research"))

VISION = "https://data.binance.vision/data/futures/um"
BARS_PER_DAY = 96          # 15m
TRAIL_4H = 16              # 16 x 15m = 4h
# Fleet 15m regime-head build parameters (market_features call sites: 0.005 = Bybit / trainer-offload / ETH builds;
# vol_window_n / forward_window_m from the btc-regime-15m-lgbm-v2 / eth-regime-15m-lgbm-xasset-v1 manifests).
BUILD = {"vol_window_n": 20, "forward_window_m": 5, "vol_threshold": 0.005, "trend_threshold": 0.01,
         "n_vol_buckets": 3}
CHAMPION_COLS = ["rolling_log_return_vol", "log_return", "log_return_lag_1", "log_return_lag_2", "hour_of_day",
                 "dayofweek"]
COMP_COLS = ["sv15", "sn15", "ss15", "sv4h", "sn4h", "ss4h"]


def _warn(msg: str) -> None:
    print(f"volcomp_regime_bakeoff: {msg}", file=sys.stderr)


def fetch_15m(symbol: str, start: str, end: str) -> Tuple[Any, Dict[str, Any]]:
    """Monthly 15m kline zips for [start, end] (YYYY-MM) -> (frame, coverage)."""
    import pandas as pd
    import requests
    from volume_composition_ic import _months, parse_kline_csv
    parts, missing = [], []
    for ym in _months(start, end):
        url = f"{VISION}/monthly/klines/{symbol}/15m/{symbol}-15m-{ym}.zip"
        body = None
        for attempt in range(4):
            try:
                r = requests.get(url, timeout=60)
                if r.status_code == 404:
                    break
                r.raise_for_status()
                body = r.content
                break
            except requests.RequestException as exc:  # allow-silent: retried with backoff; a month that never arrives is listed in coverage.months_missing
                _warn(f"{symbol} {ym}: {exc} (attempt {attempt + 1})")
                time.sleep(2 ** attempt)
        if body is None:
            missing.append(ym)
            continue
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            parts.append(parse_kline_csv(zf.read(zf.namelist()[0]).decode("utf-8")))
    if not parts:
        return pd.DataFrame(), {"months_requested": len(_months(start, end)), "months_missing": missing}
    df = pd.concat(parts).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df, {"months_requested": len(_months(start, end)), "months_missing": missing, "bars_15m": int(len(df)),
                "first_ts": str(df["ts"].iloc[0]), "last_ts": str(df["ts"].iloc[-1])}


def composition_features(k, season_days: int):
    """Adds sv/sn/ss at the 15m and trailing-4h grains to a 15m kline frame (ts, volume, trades). Past-only."""
    import numpy as np
    d = k[["ts", "volume", "trades"]].copy().sort_values("ts").reset_index(drop=True)
    d["slot"] = d["ts"].dt.hour * 4 + d["ts"].dt.minute // 15
    vol = d["volume"].where(d["volume"] > 0)
    trd = d["trades"].where(d["trades"] > 0)
    v4 = d["volume"].rolling(TRAIL_4H, min_periods=TRAIL_4H).sum().where(lambda s: s > 0)
    n4 = d["trades"].rolling(TRAIL_4H, min_periods=TRAIL_4H).sum().where(lambda s: s > 0)
    raw = {"15": (np.log(vol), np.log(trd)), "4h": (np.log(v4), np.log(n4))}
    for g, (lv, ln) in raw.items():
        for name, series in (("sv", lv), ("sn", ln), ("ss", lv - ln)):
            norm = series.groupby(d["slot"]).transform(
                lambda s: s.shift(1).rolling(season_days, min_periods=season_days // 2).mean())
            d[f"{name}{g}"] = series - norm
    d["ts"] = d["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return d[["ts", *COMP_COLS]]


def champion_frame(k, symbol: str):
    """Run the real MarketFeaturesBuilder over the kline bars; returns ts, regime_label and the champion columns."""
    import pandas as pd
    from ml.datasets.families.market_features import MarketFeaturesBuilder
    with tempfile.TemporaryDirectory() as td:
        with open(Path(td) / "data.jsonl", "w", encoding="utf-8") as fh:
            for r in k.itertuples(index=False):
                fh.write(json.dumps({"ts": r.ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "symbol": symbol, "timeframe": "15m",
                                     "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                                     "volume": r.volume}) + "\n")
        keep = ["ts", "regime_label", *CHAMPION_COLS]
        rows = [{c: row.get(c) for c in keep} for row in MarketFeaturesBuilder().iter_rows(market_raw_path=td, **BUILD)]
    return pd.DataFrame(rows)


def build_symbol(symbol: str, a: argparse.Namespace, cache: Path) -> Dict[str, Any]:
    k, cov = fetch_15m(symbol, a.start, a.end)
    if k.empty:
        return {"symbol": symbol, "state": "producer_failed", "why": "no kline months fetched", "coverage": cov}
    champ = champion_frame(k, symbol)
    comp = composition_features(k, a.season_days)
    df = champ.merge(comp, on="ts", how="left")
    df = df.dropna(subset=["regime_label", *COMP_COLS]).reset_index(drop=True)
    path = cache / f"{symbol}_15m.csv"
    df.to_csv(path, index=False)
    vc = df["regime_label"].value_counts(normalize=True).to_dict()
    return {"symbol": symbol, "state": "built", "path": str(path), "rows": int(len(df)), "coverage": cov,
            "first_ts": str(df["ts"].iloc[0]) if len(df) else None, "last_ts": str(df["ts"].iloc[-1]) if len(df) else None,
            "label_share": {str(c): round(float(v), 4) for c, v in vc.items()}}


def run(a: argparse.Namespace) -> int:
    import ml_bakeoff
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache_dir or (out / "dataset")).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]
    builds = [build_symbol(s, a, cache) for s in symbols]
    (out / "dataset_build.json").write_text(json.dumps(builds, indent=2, default=str) + "\n", encoding="utf-8")
    if a.build_only:
        print(json.dumps([{k: b.get(k) for k in ("symbol", "state", "rows", "first_ts", "last_ts")} for b in builds]))
        return 0
    spec = ml_bakeoff.load_unit_spec(a.unit, Path(a.queue_dir) if a.queue_dir else None)
    os.environ["ML_DATA_ROOT"] = str(cache)
    try:
        verdict = ml_bakeoff.run_spec(spec, unit=a.unit)
    except Exception as e:  # allow-silent: error.txt + stderr + exit 1; script_run derives producer_failed
        (out / "error.txt").write_text(f"{type(e).__name__}: {e}\n", encoding="utf-8")
        _warn(f"{type(e).__name__}: {e}")
        return 1
    verdict["dataset_build"] = builds
    verdict.setdefault("caveats", []).append(
        "Binance USD-M 15m klines PROXY Bybit linear (Bybit klines carry no trade count); champion columns and "
        "regime_label come from the real MarketFeaturesBuilder over those bars; vol_bucket (string categorical) and "
        "the 60-day recency sample weight are not reproduced by ml_bakeoff (identical for every arm).")
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"volcomp_regime_bakeoff {a.unit}: verdict={verdict['verdict']} read_state={verdict['read_state']} "
          f"n={verdict['n']}")
    return 0


def _self_test() -> int:
    """Synthetic: the composition features are past-only and exact (sv = sn + ss)."""
    import numpy as np
    import pandas as pd
    n = BARS_PER_DAY * 40
    rng = np.random.default_rng(3)
    ts = pd.date_range("2020-01-01", periods=n, freq="15min", tz="UTC")
    k = pd.DataFrame({"ts": ts, "volume": np.exp(rng.normal(5, 0.5, n)), "trades": np.exp(rng.normal(3, 0.5, n))})
    f = composition_features(k, 20)
    ok = f.dropna()
    assert len(ok) > 0, "no complete rows"
    assert np.allclose(ok["sv15"], ok["sn15"] + ok["ss15"]), "15m decomposition not exact"
    assert np.allclose(ok["sv4h"], ok["sn4h"] + ok["ss4h"]), "4h decomposition not exact"
    # past-only: perturbing the LAST bar changes no earlier feature row
    k2 = k.copy()
    k2.loc[n - 1, "volume"] *= 50
    f2 = composition_features(k2, 20)
    assert f.iloc[:-1].fillna(0).equals(f2.iloc[:-1].fillna(0)), "a future bar leaked into an earlier row"
    print("volcomp_regime_bakeoff self-test OK")
    return 0


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--unit")
    ap.add_argument("--out")
    ap.add_argument("--queue-dir", default=None)
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-09")
    ap.add_argument("--season-days", type=int, default=20)
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--build-only", action="store_true", help="build the dataset and stop (mechanics smoke only)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out or (not a.unit and not a.build_only):
        ap.error("--out (and --unit unless --build-only) are required")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
