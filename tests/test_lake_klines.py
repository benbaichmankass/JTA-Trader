"""Parity: the lake-built klines cache equals the stream-built cache on the overlap (row ML-DATA-WIRING)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.datasets import lake, lake_klines as LK  # noqa: E402


def _bars(n=300, seed=1):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    c = 100 + rng.normal(0, 1, n).cumsum()
    df = pd.DataFrame({"ts": ts, "open": c, "high": c + 1, "low": c - 1, "close": c + 0.2, "volume": rng.uniform(1, 9, n)})
    df.loc[5, ["volume", "high", "low"]] = [0.0, 100.0, 100.0]   # flat zero-volume bar: both paths drop it
    return df


def _lake(tmp_path, bars):
    base = tmp_path / "lake"
    d = base / "crypto" / "um_perp" / "1h"
    d.mkdir(parents=True)
    ents = []
    for s, df in bars.items():
        df.to_parquet(d / f"{s}.parquet", index=False)
        ents.append({"asset_class": "crypto", "market": "um_perp", "tf": "1h", "symbol": s, "rows": len(df),
                     "first": df.ts.iloc[0].isoformat(), "last": df.ts.iloc[-1].isoformat(), "path": f"crypto/um_perp/1h/{s}.parquet"})
    (base / "MANIFEST.json").write_text(json.dumps({"generated_at": "t", "files": ents}))
    return base


def _stream_cache(tmp_path, bars, start):
    """What build_base_table does today to a klines12 stream (open_time ms), re-implemented here as the reference."""
    c = tmp_path / "klines"
    c.mkdir()
    for s, df in bars.items():
        k = pd.DataFrame({"open_time": (df.ts.dt.as_unit("ns").astype("int64") // 10**6).astype("int64")})
        k = pd.concat([k, df[["open", "high", "low", "close", "volume"]]], axis=1)
        k["ts"] = pd.to_datetime(k["open_time"], unit="ms", utc=True).astype("datetime64[ns, UTC]")
        k = k.sort_values("ts").drop_duplicates("ts")
        k = k[~((k["volume"] == 0) & (k["high"] == k["low"])) & (k.ts >= pd.Timestamp(start, tz="UTC"))]
        k[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True).to_pickle(c / f"{s}.pkl")
    return c


def test_lake_cache_parity_with_streams(tmp_path, monkeypatch):
    bars = {"AAAUSDT": _bars(300, 1), "BBBUSDT": _bars(300, 2)}
    monkeypatch.setenv("LAKE_LOCAL_DIR", str(_lake(tmp_path, bars)))
    lake._MANIFEST_CACHE.clear()
    ref = _stream_cache(tmp_path, bars, "2024-01-02")
    cache, written, info = LK.build_klines_cache(tmp_path, ["AAAUSDT", "BBBUSDT", "GONEUSDT"], "2024-01-02")
    assert written == ["AAAUSDT", "BBBUSDT"] and info["symbols_missing"] == ["GONEUSDT"]
    p = LK.parity(ref, cache, ["AAAUSDT", "BBBUSDT"])
    assert p["identical"], p["diffs"]
    assert all(v["overlap_rows"] > 250 for v in p["per_symbol"].values())   # not a vacuous pass


def test_parity_reports_a_difference(tmp_path, monkeypatch):
    bars = {"AAAUSDT": _bars(300, 1)}
    ref = _stream_cache(tmp_path, bars, "2024-01-02")
    bad = {"AAAUSDT": bars["AAAUSDT"].drop(index=50)}
    monkeypatch.setenv("LAKE_LOCAL_DIR", str(_lake(tmp_path, bad)))
    lake._MANIFEST_CACHE.clear()
    cache, _, _ = LK.build_klines_cache(tmp_path, ["AAAUSDT"], "2024-01-02")
    p = LK.parity(ref, cache, ["AAAUSDT"])
    assert not p["identical"] and p["diffs"][0]["only_stream"] == 1


def test_selection_and_freshness_declared():
    assert LK.dataset_selection("ml_entry")["status"] == "wired"
    f = LK.freshness("regime_btc_eth")
    assert f["read_state"] == "unknown"      # planned path: unknown, never 0
