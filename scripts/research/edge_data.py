#!/usr/bin/env python3
# wiring: manual-only - research data loader for scripts/research/edge_portfolio_discovery.py (lane RESEARCH-EDGE).
"""Binance Vision USD-M perp DAILY klines + settled funding, whole archive, cached as pickles.

Discovery window only is ever loaded by the study (END_DISCOVERY 2024-06-30, HOLDOUT-LOCK): ``load`` refuses
a month after ``MAX_MONTH`` unless ``allow_holdout=True``, which no study here passes.
Missing monthly files are recorded (not silently skipped) in ``manifest``.
"""

from __future__ import annotations
import io
import re
import zipfile
import pickle
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd

HOST = "https://data.binance.vision/data/futures/um/monthly"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
START_MONTH, MAX_MONTH = "2019-09", "2024-06"
COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "tbv",
    "tbqv",
    "ignore",
]


def months(a=START_MONTH, b=MAX_MONTH):
    return [p.strftime("%Y-%m") for p in pd.period_range(a, b, freq="M")]


def list_symbols():
    out, marker = [], ""
    while True:
        url = (
            f"{S3}?delimiter=/&prefix=data/futures/um/monthly/klines/&max-keys=1000"
            + (f"&marker={marker}" if marker else "")
        )
        x = urllib.request.urlopen(url, timeout=60).read().decode()
        out += re.findall(r"klines/([A-Z0-9_]+)/</Prefix>", x)
        if "<IsTruncated>true" in x:
            marker = re.findall(r"<NextMarker>([^<]+)</NextMarker>", x)[0]
        else:
            return sorted(set(out))


def _get(url, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except (urllib.error.URLError, OSError):
            continue  # transient network error: retry; RuntimeError is raised after the last try
    raise RuntimeError(f"fetch failed {url}")


def _month(args):
    kind, sym, m, root, market, iv = args
    f = (
        root
        / "raw"
        / (
            (kind if market == "um" else kind + "_" + market)
            + ("" if iv == "1d" else "_" + iv)
        )
        / f"{sym}-{m}.pkl"
    )
    if f.exists():
        return pickle.load(open(f, "rb"))
    host = HOST if market == "um" else "https://data.binance.vision/data/spot/monthly"
    url = (
        f"{host}/klines/{sym}/{iv}/{sym}-{iv}-{m}.zip"
        if kind == "k"
        else f"{HOST}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip"
    )
    b = _get(url)
    df = None
    if b is not None:
        z = zipfile.ZipFile(io.BytesIO(b))
        df = pd.read_csv(z.open(z.namelist()[0]), header=None if kind == "k" else 0)
        if kind == "k":
            if str(df.iloc[0, 0]).lower().startswith("open"):
                df = df.iloc[1:]
            df.columns = COLS
            df = df[
                ["open_time", "open", "high", "low", "close", "volume", "quote_volume"]
            ].astype(float)
            df.index = pd.to_datetime(
                df.pop("open_time").astype("int64"), unit="ms", utc=True
            )
            if iv == "1d":
                df.index = df.index.normalize()
        else:
            df = df.rename(columns=lambda c: c.strip())
            df.index = pd.to_datetime(
                df["calc_time"].astype("int64"), unit="ms", utc=True
            )
            df = df[["last_funding_rate"]].astype(float)
    f.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump(df, open(f, "wb"))
    return df


def fetch(
    symbols, root, kinds=("k", "f"), workers=48, ms=None, market="um", interval="1d"
):
    root = Path(root)
    ms = ms or months()
    jobs = [
        (k, s, m, root, market, interval) for s in symbols for k in kinds for m in ms
    ]
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(_month, jobs))
    out = {}
    for (k, s, m, _, _mk, _iv), df in zip(jobs, res):
        out.setdefault((k, s), []).append((m, df))
    return out


def assemble(fetched, kind):
    series, manifest = {}, {}
    for (k, s), lst in fetched.items():
        if k != kind:
            continue
        have = [d for _, d in lst if d is not None]
        if not have:
            continue
        df = pd.concat(have).sort_index()
        df = df[~df.index.duplicated()]
        series[s] = df
        manifest[s] = {
            "first": str(df.index[0].date()),
            "last": str(df.index[-1].date()),
            "months_missing_inside": sum(1 for _, d in lst if d is None),
        }
    return series, manifest
