#!/usr/bin/env python3
# wiring: .github/workflows/ml-data-export-bp2-kaggle.yml (stage step), scripts/research/market_data_export.py (DATASETS["metis-market-bp2"])
"""ML-DATA-PUBLISH-WIDEN-BP2 (2026-11-26): stage market_raw + market_features 1h for the bp2 60-perp universe OFF the trainer.

WHY. Kaggle units may only read PUBLISHED data, and the one published ML dataset (metis-market-data) covers BTC/ETH/SOL. The
operator (2026-11-25: "these resources are free and should never sit idle") wants the Kaggle GPU busy; pooled 60-perp
sequence models (row ML-GRU-POOLED-BP2) need the widened data. This builds it on a GitHub runner, from the public
data.binance.vision USD-M perp archive, so the saturated trainer does no work and holds no new data.

HOW (per symbol, a thread pool fetches; the builds run serially):
  1. klines: scripts/ops/fetch_backtest_candles.fetch_klines_binance_vision(sym, "60", start, now): monthly zips, then daily
     zips for the current month (the same fetcher exit_head_kaggle_bakeoff and fetch_backtest_candles use).
  2. market_raw: `python -m ml.datasets build market_raw ... adapter=csv` (the canonical builder; no new parser).
  3. market_features: `python -m ml.datasets build market_features` with the trainer's EXACT label params
     (scripts/ops/build_trainer_datasets.sh::build_bybit_features: vol_window_n=20 forward_window_m=5 vol_threshold=0.005
     trend_threshold=0.005 n_vol_buckets=3), so regime_label means the same thing it means in metis-market-data.
  4. KLINE-ONLY PROJECTION: the builder also emits ~85 side-stream columns (funding/OI, order flow, cross-asset, forecasts,
     embeddings, macro). With no side-stream supplied they are 0.0 on every row, which reads as a measurement but means
     "not looked at" (collapsed-state rule). They are DROPPED, not shipped; metadata.json lists them under
     projection.dropped_absent_columns. What ships is exactly KEEP_FEATURES (all computed from OHLCV alone).

VERSION DIR. Shards land under .../1h/v102/ (the v002 builder schema rebuilt from Binance-vision; metadata requires vNNN), never .../v002/: the trainer's v002
is BYBIT klines, and the same path must never mean two different series. BTC/ETH/SOL are rebuilt here too (same venue as the
other 57) so a pooled read is one venue end to end.

What is NOT claimed: no Bybit basis is measured; the bp2 universe is the frozen ml_decision_entry manifest list; a symbol the
archive cannot serve is recorded could_not_look in STAGE_REPORT.json and absent from the shards, never invented.

    python3 scripts/research/market_data_bp2.py stage --out DIR [--symbols A,B] [--years 5] [--workers 8]
    python3 scripts/research/market_data_bp2.py self-test

Tier-1 tooling: market data only, writes only --out. No config, model, registry or order path.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "scripts" / "ops", _REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

VERSION = "v102"
TIMEFRAME = "1h"
SOURCE = "binance_vision_um_perp_klines"
#: The trainer's market_features params (build_trainer_datasets.sh::build_bybit_features). They DEFINE regime_label.
FEATURE_PARAMS = {"vol_window_n": "20", "forward_window_m": "5", "vol_threshold": "0.005", "trend_threshold": "0.005",
                  "n_vol_buckets": "3"}
#: The market_features columns computed from OHLCV alone (verified 2026-11-26 on ADAUSDT 1h: these 20 are the only columns
#: not identically 0.0 when no side-stream is supplied). Labels are forward-only and stay labels (never features).
KEEP_FEATURES = ("ts", "symbol", "timeframe", "source", "log_return", "log_return_lag_1", "log_return_lag_2",
                 "rolling_log_return_vol", "vol_bucket", "hour_of_day", "dayofweek", "parkinson_vol", "garman_klass_vol",
                 "rogers_satchell_vol", "yang_zhang_vol", "forward_log_return", "forward_log_return_vol", "regime_label",
                 "trend_regime_label", "direction_label")


def universe() -> List[str]:
    from scripts.research import market_data_export as mde  # the frozen bp2 manifest, the list ml_decision_entry trades
    syms = mde.bp2_symbols()
    if not syms:
        raise SystemExit("refused: the bp2 manifest is unreadable; no universe to stage")
    return syms


def fetch_csv(sym: str, dst: Path, start: datetime, end: datetime) -> Dict[str, Any]:
    import fetch_backtest_candles as fbc
    import pandas as pd
    rows = fbc.fetch_klines_binance_vision(sym, "60", int(start.timestamp() * 1000), int(end.timestamp() * 1000))
    if not rows:
        return {"read_state": "could_not_look", "why": "binance_vision returned no klines"}
    df = pd.DataFrame(rows).drop_duplicates("timestamp").sort_values("timestamp")
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    cols = ["ts", "open", "high", "low", "close"] + (["volume"] if "volume" in df.columns else [])
    dst.parent.mkdir(parents=True, exist_ok=True)
    df[cols].to_csv(dst, index=False)
    return {"read_state": "measured", "bars": int(len(df)), "first_ts": df["ts"].iloc[0], "last_ts": df["ts"].iloc[-1]}


def _build(family: str, out: Path, sym: str, source: str, kv: List[str]) -> None:
    cmd = [sys.executable, "-m", "ml.datasets", "build", family, "--output-dir", str(out), "--version", VERSION,
           "--source", source, "--symbol-scope", sym, "--timeframe", TIMEFRAME, "--overwrite", *kv]
    r = subprocess.run(cmd, cwd=str(_REPO), capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"{family} build failed rc={r.returncode}: {(r.stderr or r.stdout)[-600:]}")


def _rewrite_source(path: Path, keep: Optional[tuple] = None) -> Dict[str, Any]:
    """Stamp the real source on every row (the csv adapter writes "csv") and, for features, keep only `keep`.
    Returns the columns dropped because they were 0.0/empty on EVERY row (absent side-streams)."""
    tmp = path.with_suffix(".tmp")
    seen_nonzero: Dict[str, bool] = {}
    rows = 0
    with path.open(encoding="utf-8") as fi, tmp.open("w", encoding="utf-8") as fo:
        for line in fi:
            if not line.strip():
                continue
            r = json.loads(line)
            for k, v in r.items():
                if v not in (0, 0.0, None, ""):
                    seen_nonzero[k] = True
                else:
                    seen_nonzero.setdefault(k, False)
            r["source"] = SOURCE
            if keep is not None:
                r = {k: r.get(k) for k in keep}
            fo.write(json.dumps(r, sort_keys=True) + "\n")
            rows += 1
    tmp.replace(path)
    dropped = sorted(k for k in seen_nonzero if keep is not None and k not in keep)
    live_dropped = sorted(k for k in dropped if seen_nonzero[k])
    return {"rows": rows, "dropped": dropped, "dropped_but_nonzero": live_dropped}


def _patch_metadata(meta_path: Path, extra: Dict[str, Any]) -> None:
    m = json.loads(meta_path.read_text(encoding="utf-8"))
    m["source"] = SOURCE                      # the builder records a local tmp path here; the venue is what a reader needs
    m.update(extra)
    meta_path.write_text(json.dumps(m, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def build_symbol(sym: str, csv: Path, out: Path) -> Dict[str, Any]:
    root = out / "datasets-out"
    _build("market_raw", root, sym, SOURCE, ["adapter=csv", f"csv_path={csv}", f"symbol={sym}", f"timeframe={TIMEFRAME}"])
    raw = root / "market_raw" / sym / TIMEFRAME / VERSION
    raw_facts = _rewrite_source(raw / "data.jsonl")
    _patch_metadata(raw / "metadata.json", {"adapter_note": "csv adapter over data.binance.vision USD-M perp 1h klines"})
    _build("market_features", root, sym, f"market_raw/{sym}/{TIMEFRAME}/{VERSION}",
           [f"market_raw_path={raw}", *[f"{k}={v}" for k, v in FEATURE_PARAMS.items()]])
    feat = root / "market_features" / sym / TIMEFRAME / VERSION
    f = _rewrite_source(feat / "data.jsonl", KEEP_FEATURES)
    if f["dropped_but_nonzero"]:
        raise RuntimeError(f"{sym}: projection would drop columns that carry data: {f['dropped_but_nonzero']}")
    _patch_metadata(feat / "metadata.json", {"projection": {
        "kind": "kline_only", "kept_columns": list(KEEP_FEATURES), "dropped_absent_columns": f["dropped"],
        "why": "side-stream columns are 0.0 on every row when the stream is not supplied; shipped as 0.0 they would read as "
               "measured values (collapsed-state rule), so they are dropped (ML-DATA-PUBLISH-WIDEN-BP2)"}})
    for p in (feat / "parquet", feat / "data.parquet"):
        if p.exists() and p.is_file():
            p.unlink()
    return {"raw_rows": raw_facts["rows"], "feature_rows": f["rows"], "dropped_columns": len(f["dropped"])}


def stage(out: Path, symbols: List[str], years: float = 5.0, workers: int = 8, now: Optional[datetime] = None,
          fetcher: Callable[[str, Path, datetime, datetime], Dict[str, Any]] = fetch_csv) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=int(365.25 * years))).replace(hour=0, minute=0, second=0, microsecond=0)
    work = out / "_work"
    t0 = time.time()

    def one(sym: str) -> Dict[str, Any]:
        try:
            return fetcher(sym, work / f"{sym}.csv", start, now)
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as could_not_look per symbol in STAGE_REPORT.json
            return {"read_state": "could_not_look", "why": f"{type(exc).__name__}: {exc}"[:400]}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        fetched = dict(zip(symbols, ex.map(one, symbols)))
    report: Dict[str, Any] = {}
    for sym in symbols:
        rec = dict(fetched[sym])
        if rec.get("read_state") == "measured":
            try:
                rec.update(build_symbol(sym, work / f"{sym}.csv", out))
            except Exception as exc:  # noqa: BLE001  # allow-silent: a per-symbol build failure is recorded, the rest still ship
                rec = {**rec, "read_state": "build_failed", "why": f"{type(exc).__name__}: {exc}"[:600]}
        report[sym] = rec
    built = [s for s, r in report.items() if r.get("feature_rows")]
    summary = {"generated_at": now.isoformat(), "version": VERSION, "timeframe": TIMEFRAME, "source": SOURCE,
               "start": start.isoformat(), "feature_params": FEATURE_PARAMS, "universe": "bp2", "n_symbols": len(symbols),
               "n_built": len(built), "not_built": sorted(set(symbols) - set(built)), "seconds": round(time.time() - t0, 1),
               "symbols": report}
    (out / "STAGE_REPORT.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    return summary


def _self_test() -> int:
    """Offline: a synthetic random-walk 'fetcher' through the REAL builders + projection + export manifest."""
    import numpy as np
    import pandas as pd

    def fake(sym: str, dst: Path, start: datetime, end: datetime) -> Dict[str, Any]:
        if sym == "NOPEUSDT":
            return {"read_state": "could_not_look", "why": "synthetic miss"}
        n = 600
        rng = np.random.default_rng(len(sym))
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        ts = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
        df = pd.DataFrame({"ts": ts, "open": c, "high": c * 1.004, "low": c * 0.996, "close": c, "volume": 1000.0})
        dst.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(dst, index=False)
        return {"read_state": "measured", "bars": n, "first_ts": ts[0], "last_ts": ts[-1]}

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "stage"
        s = stage(out, ["AAAUSDT", "NOPEUSDT"], fetcher=fake, workers=2)
        assert s["n_built"] == 1 and s["not_built"] == ["NOPEUSDT"], s
        assert s["symbols"]["NOPEUSDT"]["read_state"] == "could_not_look"
        feat = out / "datasets-out/market_features/AAAUSDT/1h" / VERSION
        first = json.loads((feat / "data.jsonl").open().readline())
        assert tuple(sorted(first)) == tuple(sorted(KEEP_FEATURES)), sorted(first)
        assert first["source"] == SOURCE and first["regime_label"] in ("range", "volatile"), first
        meta = json.loads((feat / "metadata.json").read_text())
        assert meta["build_params"]["vol_threshold"] == 0.005 and meta["source"] == SOURCE, meta
        assert "funding_rate" in meta["projection"]["dropped_absent_columns"], meta["projection"]
        raw = json.loads((out / "datasets-out/market_raw/AAAUSDT/1h" / VERSION / "data.jsonl").open().readline())
        assert raw["source"] == SOURCE and raw["close"] > 0, raw
        from scripts.research import market_data_export as mde
        m = mde.build(out / "datasets-out", Path(td) / "pub", username="u", dataset="metis-market-bp2", allow=mde.allow_for("metis-market-bp2", ["AAAUSDT"]))
        assert len(m["files"]) == 4 and not m["withheld"], m
        assert mde.verify(Path(td) / "pub")["ok"]
        assert mde.covers(f"datasets-out/market_features/AAAUSDT/1h/{VERSION}/data.jsonl", dataset="metis-market-bp2",
                          allow=mde.allow_for("metis-market-bp2", ["AAAUSDT"]))
    print("market_data_bp2 self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("self-test")
    st = sub.add_parser("stage")
    st.add_argument("--out", required=True)
    st.add_argument("--symbols", default="", help="comma list; default = the bp2 universe")
    st.add_argument("--years", type=float, default=5.0, help="history depth (trainer default: rolling 5 years)")
    st.add_argument("--workers", type=int, default=int(os.environ.get("BP2_FETCH_WORKERS", "8")))
    a = ap.parse_args(argv)
    if a.cmd == "self-test":
        return _self_test()
    if a.cmd == "stage":
        syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or universe()
        s = stage(Path(a.out), syms, years=a.years, workers=a.workers)
        print(json.dumps({k: s[k] for k in ("n_symbols", "n_built", "not_built", "seconds", "start")}))
        return 0 if s["n_built"] else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
