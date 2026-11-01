#!/usr/bin/env python3
"""Binance Vision USD-M perpetual streams beyond OHLCV -> pickle cache (row ML-FS-ARCHIVE, Tier 1).

Streams (all public, keyless, data.binance.vision): ``klines12`` (1h, ALL 12 columns incl. taker-buy volume,
trade count, quote volume), ``funding`` (settled funding), ``premium`` (1h premium-index OHLC) and ``metrics``
(5m open interest, long/short ratios, taker ratio; daily files).

Rules (docs/research/ml-feature-inventory-2026-11-01.md): missing stays NaN/absent, never 0; metrics are SORTED on
read (BTC daily files since 2026-08 are unsorted and irregular); a delisted-contract month (volume 0 and a single
constant close on every bar) is flagged in the manifest, not silently kept.

    python3 scripts/research/vision_streams.py --out /tmp/vs --streams klines12,funding,premium --workers 16
    python3 scripts/research/vision_streams.py --out /tmp/vs --streams metrics --start 2021-12-01 --workers 24
    python3 scripts/research/vision_streams.py --self-test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
import sys
import time
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

BASE = "https://data.binance.vision/data/futures/um"
REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "comms/research/broad_paths/bp2-f4271084b120/manifest.json"
K12 = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
       "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def universe() -> list[str]:
    return [s["symbol"] for s in json.loads(MANIFEST.read_text())["hash_inputs"]["symbols"]]


def _get(url: str) -> bytes | None:
    for wait in (0, 2, 4, 8):
        time.sleep(wait)
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
            if e.code == 404:
                return None
        except Exception:  # noqa: BLE001  # allow-silent: retried with backoff; final failure returns None and is counted
            continue
    return None


def _csv(raw: bytes) -> pd.DataFrame:
    txt = zipfile.ZipFile(io.BytesIO(raw)).read(zipfile.ZipFile(io.BytesIO(raw)).namelist()[0]).decode()
    first = txt.split("\n", 1)[0]
    return pd.read_csv(io.StringIO(txt), header=None if first[:1].isdigit() else 0)


def parse_klines(raw: bytes) -> pd.DataFrame:
    d = _csv(raw)
    if d.shape[1] == 12 and not isinstance(d.columns[0], str):
        d.columns = K12
    d["open_time"] = pd.to_numeric(d["open_time"], errors="coerce")
    return d.dropna(subset=["open_time"])


def parse_funding(raw: bytes) -> pd.DataFrame:
    return _csv(raw)


def parse_metrics(raw: bytes) -> pd.DataFrame:
    d = _csv(raw)
    d["create_time"] = pd.to_datetime(d["create_time"], utc=True)
    return d.sort_values("create_time").drop_duplicates("create_time").reset_index(drop=True)


def delist_flag(k: pd.DataFrame) -> bool:
    """True if EVERY bar has volume 0 and the close never changes (a frozen post-delisting month)."""
    return bool(len(k) and (k["volume"] == 0).all() and k["close"].nunique() == 1)


def months(start: str, end: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start[:7], end[:7], freq="M")]


def days(start: str, end: str) -> list[str]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a + timedelta(n)).isoformat() for n in range((b - a).days + 1)]


def jobs(stream: str, syms: list[str], start: str, end: str):
    if stream == "klines12":
        return [(s, m, f"{BASE}/monthly/klines/{s}/1h/{s}-1h-{m}.zip") for s in syms for m in months(start, end)]
    if stream == "funding":
        return [(s, m, f"{BASE}/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip") for s in syms for m in months(start, end)]
    if stream == "premium":
        return [(s, m, f"{BASE}/monthly/premiumIndexKlines/{s}/1h/{s}-1h-{m}.zip") for s in syms for m in months(start, end)]
    if stream == "metrics":
        return [(s, d, f"{BASE}/daily/metrics/{s}/{s}-metrics-{d}.zip") for s in syms for d in days(start, end)]
    raise SystemExit(f"unknown stream {stream}")


PARSE = {"klines12": parse_klines, "funding": parse_funding, "premium": parse_klines, "metrics": parse_metrics}


def run(out: Path, streams: list[str], start: str, end: str, workers: int, syms: list[str]) -> dict:
    report = {}
    for st in streams:
        t0 = time.time()
        js = jobs(st, syms, start, end)
        frames: dict[str, list[pd.DataFrame]] = {s: [] for s in syms}
        missing: dict[str, int] = {s: 0 for s in syms}
        frozen: dict[str, list[str]] = {s: [] for s in syms}

        def one(j):
            s, key, url = j
            raw = _get(url)
            if raw is None:
                return s, key, None
            return s, key, PARSE[st](raw)

        with cf.ThreadPoolExecutor(workers) as ex:
            for s, key, df in ex.map(one, js):
                if df is None:
                    missing[s] += 1
                    continue
                if st == "klines12" and delist_flag(df):
                    frozen[s].append(key)
                frames[s].append(df)
        (out / st).mkdir(parents=True, exist_ok=True)
        man = {}
        for s in syms:
            if not frames[s]:
                man[s] = {"rows": 0, "missing_files": missing[s]}
                continue
            d = pd.concat(frames[s], ignore_index=True)
            tcol = {"klines12": "open_time", "premium": "open_time", "funding": "calc_time", "metrics": "create_time"}[st]
            d = d.sort_values(tcol).drop_duplicates(tcol).reset_index(drop=True)
            d.to_pickle(out / st / f"{s}.pkl")  # pickle: same as ml_decision_entry cache; no pyarrow on the runner image
            man[s] = {"rows": len(d), "first": str(d[tcol].iloc[0]), "last": str(d[tcol].iloc[-1]),
                      "missing_files": missing[s], "frozen_post_delist_months": frozen[s]}
        (out / st / "MANIFEST.json").write_text(json.dumps(
            {"stream": st, "start": start, "end": end, "files": len(js), "seconds": round(time.time() - t0, 1),
             "files_per_s": round(len(js) / max(time.time() - t0, 1e-9), 1), "symbols": man}, indent=1))
        report[st] = {"files": len(js), "seconds": round(time.time() - t0, 1)}
        print(f"{st}: {len(js)} files in {report[st]['seconds']}s", flush=True)
    return report


def self_test() -> None:
    # frozen post-delist month is flagged; a live month is not; unsorted metrics come back sorted
    frozen = pd.DataFrame({"volume": [0.0] * 5, "close": [1.0] * 5})
    live = pd.DataFrame({"volume": [1.0, 0, 2, 3, 4], "close": [1, 1, 2, 3, 3.0]})
    assert delist_flag(frozen) and not delist_flag(live)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as z:
        z.writestr("m.csv", "create_time,symbol,sum_open_interest\n2026-10-15 01:20:00,X,2\n2026-10-15 01:15:00,X,1\n")
    m = parse_metrics(raw.getvalue())
    assert list(m["sum_open_interest"]) == [1, 2] and m["create_time"].is_monotonic_increasing
    nohdr = io.BytesIO()
    with zipfile.ZipFile(nohdr, "w") as z:
        z.writestr("k.csv", "1577836800000,1,2,0.5,1.5,10,1577840399999,15,3,6,9,0\n")
    k = parse_klines(nohdr.getvalue())
    assert "taker_buy_volume" in k.columns and k["taker_buy_volume"].iloc[0] == 6
    print("vision_streams self-test OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/vision_streams")
    ap.add_argument("--streams", default="klines12,funding,premium")
    ap.add_argument("--start", default="2020-07-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    syms = a.symbols.split(",") if a.symbols else universe()
    run(Path(a.out), a.streams.split(","), a.start, a.end, a.workers, syms)


if __name__ == "__main__":
    sys.exit(main())
