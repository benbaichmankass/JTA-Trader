#!/usr/bin/env python3
# wiring: .github/workflows/market-data-lake.yml (crypto shards) -> resample.py -> validate.py -> hf_publish.py -> HF
"""Crypto half of the market data lake: EVERY Binance USD-M perp + spot pairs at the FINEST timeframe the archive
publishes, keyless, stored once, incrementally refreshed.

WHY (operator, 2026-11-01): the general (pooled) ML models train on as much market data as can be found, stored on
Hugging Face, not our VMs; and "we should also be keeping the smallest timeframe data available - we can always
reconstruct higher timeframes on top of that". Row MARKET-DATA-LAKE; design docs/data/market-data-lake.md.

SOURCE  data.binance.vision. Symbols come from the archive's own S3 listing, so DELISTED contracts are included
        (survivorship-free). Licence: Binance Terms of Use, no open-data licence => PRIVATE stores only.

STREAMS (finest grain each publishes; higher klines timeframes are DERIVED by resample.py, never fetched)
  klines       1m OHLCV + quote volume, trade count, taker-buy volume   monthly zips + daily zips for the open month
  fundingRate  every funding event (8h / 4h / 1h per contract)           monthly zips            (um_perp only)
  metrics      5m open interest, top-trader + global long/short, taker  daily zips              (um_perp only)

OUTPUT  <out>/crypto/<market>/<label>/<SYMBOL>/<YYYY-MM>.parquet   label = 1m | funding | metrics_5m
        One partition per calendar month, so a daily refresh rewrites ONE small file per symbol, not its history.
        <out>/_manifests/crypto-<market>-<label>-<shard>.json : one entry per symbol with per-partition stats
        (rows, first, last, src monthly|daily, files, checksum states, missing_bars, gaps).

POINT-IN-TIME  ts = bar OPEN (klines), funding calc_time, metrics create_time (treat as window END: lag one 5m step).
        Nothing forward-filled; gaps COUNTED, never patched; every zip that has a .CHECKSUM is sha256-checked.

REFRESH (--refresh-from MANIFEST.json): a month is rebuilt only if it is absent, was built from daily files and a
        monthly file now exists, or is the newest month. Everything else is left untouched.

    python3 scripts/data_lake/binance_vision_lake.py --market um_perp --stream klines --census
    python3 scripts/data_lake/binance_vision_lake.py --market um_perp --stream klines --shard 0/12 --out lake
    python3 scripts/data_lake/binance_vision_lake.py --market um_perp --stream metrics --refresh-from MANIFEST.json
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FILES = "https://data.binance.vision"
MARKETS = {"um_perp": "data/futures/um", "spot": "data/spot"}
TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}
RAW_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades",
            "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
OUT_COLS = ["ts", "open", "high", "low", "close", "volume", "quote_volume", "trades",
            "taker_buy_volume", "taker_buy_quote_volume"]
_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
UA = {"User-Agent": "jta-trader-market-data-lake/1"}
LICENCE = "Binance ToU; private store only"


def _get(url: str, tries: int = 6, timeout: int = 60) -> bytes:
    last: Optional[Exception] = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # network blip: contained, retried (no-halting rule)
            last = e
        time.sleep(min(30, 2 ** i))
    raise RuntimeError(f"GET failed after {tries} tries: {url}: {last}")


def s3_list(prefix: str, delimiter: str = "/") -> Tuple[List[str], List[str]]:
    """(common_prefixes, keys) under ``prefix``, following pagination."""
    prefixes: List[str] = []
    keys: List[str] = []
    marker = ""
    while True:
        q = f"{LISTING}?delimiter={delimiter}&prefix={urllib.request.quote(prefix)}"
        if marker:
            q += f"&marker={urllib.request.quote(marker)}"
        root = ET.fromstring(_get(q))
        page_p = [p.text for p in root.findall("s3:CommonPrefixes/s3:Prefix", _NS)]
        page_k = [k.text for k in root.findall("s3:Contents/s3:Key", _NS)]
        prefixes += page_p
        keys += page_k
        if root.findtext("s3:IsTruncated", default="false", namespaces=_NS) != "true":
            return prefixes, keys
        marker = root.findtext("s3:NextMarker", default="", namespaces=_NS) or (page_k or page_p)[-1]


def list_symbols(market: str) -> List[str]:
    prefixes, _ = s3_list(f"{MARKETS[market]}/monthly/klines/")
    return sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in prefixes)


# ---------------------------------------------------------------- parsers (one per stream)
def _read_csv(raw: bytes, cols: Optional[List[str]], header_token: str) -> pd.DataFrame:
    text = raw.decode("utf-8", "replace")
    has_header = text[:40].lower().startswith(header_token)
    df = pd.read_csv(io.StringIO(text), header=0 if has_header else None, names=None if has_header else cols)
    if cols and not has_header:
        df.columns = cols[: len(df.columns)]
    return df


def _epoch(series: pd.Series) -> pd.Series:
    v = pd.to_numeric(series, errors="coerce")
    # Binance switched spot files to MICROseconds from 2025-01; perps stay ms. Decide per file by magnitude.
    unit = "us" if v.max() > 10 ** 14 else "ms"
    return pd.to_datetime(v, unit=unit, utc=True)


def parse_kline_csv(raw: bytes) -> pd.DataFrame:
    df = _read_csv(raw, RAW_COLS, "open_time")
    # header-row files name the trade-count column `count` (and older ones have no header): always rename by position
    df.columns = RAW_COLS[: len(df.columns)]
    if df.empty:
        return pd.DataFrame(columns=OUT_COLS)
    out = pd.DataFrame({"ts": _epoch(df["open_time"])})
    for c in OUT_COLS[1:]:
        out[c] = pd.to_numeric(df[c], errors="coerce")
    return out.dropna(subset=["ts"])


def parse_funding_csv(raw: bytes) -> pd.DataFrame:
    df = _read_csv(raw, ["calc_time", "funding_interval_hours", "last_funding_rate"], "calc_time")
    return pd.DataFrame({"ts": _epoch(df["calc_time"]),
                         "funding_interval_hours": pd.to_numeric(df["funding_interval_hours"], errors="coerce"),
                         "funding_rate": pd.to_numeric(df["last_funding_rate"], errors="coerce")}).dropna(subset=["ts"])


METRIC_COLS = ["sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
               "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]


def parse_metrics_csv(raw: bytes) -> pd.DataFrame:
    df = _read_csv(raw, ["create_time", "symbol"] + METRIC_COLS, "create_time")
    out = pd.DataFrame({"ts": pd.to_datetime(df["create_time"], utc=True, errors="coerce")})
    for c in METRIC_COLS:
        out[c] = pd.to_numeric(df.get(c), errors="coerce")
    # daily metrics files since 2026-08 are not sorted / irregular: sort on read (ML-FEATURE-INFRA finding)
    return out.dropna(subset=["ts"]).sort_values("ts")


# stream -> (label, monthly path tmpl, daily path tmpl, parser, markets, bar minutes for gap stats or None)
STREAMS: Dict[str, dict] = {
    "klines": {"label": "1m", "monthly": "{b}/monthly/klines/{s}/1m/", "daily": "{b}/daily/klines/{s}/1m/",
               "parse": parse_kline_csv, "markets": ("um_perp", "spot"), "step_min": 1},
    "fundingRate": {"label": "funding", "monthly": "{b}/monthly/fundingRate/{s}/", "daily": None,
                    "parse": parse_funding_csv, "markets": ("um_perp",), "step_min": None},
    "metrics": {"label": "metrics_5m", "monthly": None, "daily": "{b}/daily/metrics/{s}/",
                "parse": parse_metrics_csv, "markets": ("um_perp",), "step_min": 5},
}


def list_zips(prefix_tmpl: Optional[str], market: str, symbol: str) -> List[str]:
    if not prefix_tmpl:
        return []
    _, keys = s3_list(prefix_tmpl.format(b=MARKETS[market], s=symbol), delimiter="")
    return sorted(k for k in keys if k.endswith(".zip"))


def _month_of(key: str) -> str:
    return re.search(r"(\d{4}-\d{2})(?:-\d{2})?\.zip$", key).group(1)


def fetch_zip(key: str, parse: Callable[[bytes], pd.DataFrame], verify: bool = True) -> Tuple[pd.DataFrame, str]:
    blob = _get(f"{FILES}/{key}")
    sha = hashlib.sha256(blob).hexdigest()
    state = "unchecked"
    if verify:
        try:
            want = _get(f"{FILES}/{key}.CHECKSUM").decode().split()[0].strip().lower()
            state = "ok" if want == sha else "MISMATCH"
        except Exception:
            state = "no_checksum"
    if state == "MISMATCH":
        raise ValueError(f"sha256 mismatch for {key}")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return parse(zf.read(zf.namelist()[0])), state


def gap_stats(ts: pd.Series, step_min: Optional[int]) -> Dict[str, int]:
    if not step_min or len(ts) < 2:
        return {"expected_rows": int(len(ts)), "missing_bars": 0, "gaps": 0, "largest_gap_bars": 0}
    step = pd.Timedelta(minutes=step_min)
    d = ts.diff().dropna()
    big = d[d > step]
    missing = int(((big / step) - 1).round().sum()) if len(big) else 0
    expected = int(((ts.iloc[-1] - ts.iloc[0]) / step)) + 1
    return {"expected_rows": expected, "missing_bars": missing, "gaps": int(len(big)),
            "largest_gap_bars": int(round(big.max() / step) - 1) if len(big) else 0}


def plan_months(monthly: List[str], daily: List[str], have: Dict[str, dict]) -> Dict[str, Tuple[str, List[str]]]:
    """month -> (src, keys) for every month that must be (re)built. A month is built from its monthly zip when one
    exists, else from its daily zips. Skip a month already in the lake unless it was daily-built and a monthly file
    now exists, or it is the newest month (still filling)."""
    by_month: Dict[str, Tuple[str, List[str]]] = {}
    for k in monthly:
        by_month[_month_of(k)] = ("monthly", [k])
    for k in daily:
        m = _month_of(k)
        if m not in by_month or by_month[m][0] == "daily":
            by_month.setdefault(m, ("daily", []))[1].append(k)
    if not by_month:
        return {}
    newest = max(by_month)
    out = {}
    for m, (src, keys) in by_month.items():
        prev = have.get(m)
        if prev is None or m == newest or (prev.get("src") == "daily" and src == "monthly"):
            out[m] = (src, sorted(keys))
    return out


def build_symbol(market: str, stream: str, symbol: str, out: Path, have: Optional[Dict[str, dict]] = None,
                 workers: int = 8) -> Dict[str, object]:
    spec = STREAMS[stream]
    label = spec["label"]
    entry: Dict[str, object] = {"asset_class": "crypto", "market": market, "tf": label, "symbol": symbol,
                                "stream": stream, "source": "data.binance.vision", "licence": LICENCE,
                                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "partitions": {}}
    monthly = list_zips(spec["monthly"], market, symbol)
    daily = list_zips(spec["daily"], market, symbol)
    if spec["monthly"] and spec["daily"] and monthly:
        # klines: daily files only matter after the last monthly file (the open month)
        last_m = _month_of(monthly[-1])
        daily = [k for k in daily if _month_of(k) > last_m]
    plan = plan_months(monthly, daily, have or {})
    errors: List[str] = []

    def one(k: str):
        try:
            return fetch_zip(k, spec["parse"])
        except Exception as e:  # contained per file; counted, retried next run
            return e

    for month, (src, keys) in sorted(plan.items()):
        frames, checks = [], {}
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for k, res in zip(keys, ex.map(one, keys)):
                if isinstance(res, Exception):
                    errors.append(f"{k.rsplit('/', 1)[-1]}: {res}"[:200])
                    continue
                checks[res[1]] = checks.get(res[1], 0) + 1
                frames.append(res[0])
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        path = out / "crypto" / market / label / symbol / f"{month}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, compression="zstd")
        part = {"rows": int(len(df)), "first": df["ts"].iloc[0].isoformat(), "last": df["ts"].iloc[-1].isoformat(),
                "src": src, "files": len(keys), "checksum": checks, "bytes": path.stat().st_size,
                "path": str(path.relative_to(out))}
        part.update(gap_stats(df["ts"], spec["step_min"]))
        if "quote_volume" in df.columns:
            part["quote_volume_usd"] = float(df["quote_volume"].sum())
            # a frozen post-delist month: no volume and a constant close (ML-FEATURE-INFRA finding) -> flag, keep
            part["frozen"] = bool(df["volume"].fillna(0).sum() == 0 and df["close"].nunique() <= 1)
        entry["partitions"][month] = part
    entry["planned_months"] = len(plan)
    entry["errors"] = errors[:20]
    entry["n_errors"] = len(errors)
    entry["state"] = "error" if errors and not entry["partitions"] else ("partial" if errors else "ok")
    return entry


def shard(items: Sequence[str], spec: str) -> List[str]:
    i, n = (int(x) for x in spec.split("/"))
    return [s for j, s in enumerate(items) if j % n == i]


def symbols_from_config(market: str, stream: str) -> Optional[List[str]]:
    """Explicit symbol list from config/data_universe.yaml crypto.<market>.streams.<stream>, or None meaning ALL."""
    import yaml
    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "data_universe.yaml").read_text())
    spec = (((cfg.get("crypto") or {}).get(market)) or {})
    sel = (spec.get("streams") or {}).get(stream, "all")
    if sel in (None, "all"):
        return None
    return list(sel)


def previous_partitions(manifest_path: Optional[str], market: str, label: str) -> Dict[str, Dict[str, dict]]:
    if not manifest_path or not Path(manifest_path).exists():
        return {}
    m = json.loads(Path(manifest_path).read_text())
    return {e["symbol"]: e.get("partitions") or {} for e in m.get("files", [])
            if e.get("asset_class") == "crypto" and e.get("market") == market and e.get("tf") == label}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", choices=sorted(MARKETS), required=True)
    ap.add_argument("--stream", choices=sorted(STREAMS), default="klines")
    ap.add_argument("--out", default="lake")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--symbols", default="", help="comma list; default = config/data_universe.yaml selection")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh-from", default="", help="previous lake MANIFEST.json: rebuild only what changed")
    ap.add_argument("--census", action="store_true", help="list the archive only: per-symbol months, no downloads")
    ap.add_argument("--workers", type=int, default=8, help="parallel file downloads per symbol")
    ap.add_argument("--parallel", type=int, default=4, help="symbols built concurrently")
    a = ap.parse_args(argv)
    spec = STREAMS[a.stream]
    if a.market not in spec["markets"]:
        print(f"[lake] stream {a.stream} does not exist for {a.market}")
        return 0
    out = Path(a.out)
    listed = list_symbols(a.market)
    chosen = [s.strip() for s in a.symbols.split(",") if s.strip()] or symbols_from_config(a.market, a.stream) or listed
    chosen = sorted(s for s in chosen if s in set(listed))
    chosen = shard(chosen, a.shard)
    if a.limit:
        chosen = chosen[: a.limit]
    label = spec["label"]
    print(f"[lake] {a.market} {a.stream}: archive lists {len(listed)}; shard {a.shard} builds {len(chosen)}", flush=True)
    if a.census:
        def cen(sym):
            try:
                ks = list_zips(spec["monthly"] or spec["daily"], a.market, sym)
            except Exception as ex:
                return {"symbol": sym, "error": str(ex)[:120]}
            ms = sorted({_month_of(k) for k in ks})
            return {"symbol": sym, "files": len(ks), "months": len(ms), "first_month": ms[0] if ms else None,
                    "last_month": ms[-1] if ms else None}
        with ThreadPoolExecutor(max_workers=32) as ex:
            rows = list(ex.map(cen, chosen))
        (out / "_census").mkdir(parents=True, exist_ok=True)
        (out / "_census" / f"crypto-{a.market}-{label}.json").write_text(json.dumps(rows, indent=1))
        have = [r for r in rows if r.get("months")]
        months = sum(r["months"] for r in have)
        bound = int(months * 30.44 * 1440 / spec["step_min"]) if spec["step_min"] else None
        print(json.dumps({"market": a.market, "stream": a.stream, "label": label, "symbols_with_data": len(have),
                          "symbols_listed": len(rows), "files": sum(r["files"] for r in have),
                          "first_month": min((r["first_month"] for r in have), default=None),
                          "last_month": max((r["last_month"] for r in have), default=None),
                          "symbol_months": months, "rows_upper_bound": bound}))
        return 0
    prev = previous_partitions(a.refresh_from, a.market, label)
    entries = []
    t0 = time.time()

    def run(sym: str) -> Dict[str, object]:
        try:
            return build_symbol(a.market, a.stream, sym, out, prev.get(sym), workers=a.workers)
        except Exception as ex:  # contained per symbol (no-halting): recorded, the next run retries
            return {"asset_class": "crypto", "market": a.market, "tf": label, "symbol": sym, "stream": a.stream,
                    "state": "error", "errors": [str(ex)[:300]], "n_errors": 1, "partitions": {}}

    with ThreadPoolExecutor(max_workers=max(1, a.parallel)) as ex:
        for n, e in enumerate(ex.map(run, chosen), 1):
            entries.append(e)
            parts = e.get("partitions") or {}
            print(f"[lake] {n}/{len(chosen)} {e['symbol']} {label}: {e.get('state')} built {len(parts)} months "
                  f"rows={sum(p['rows'] for p in parts.values())} errors={e.get('n_errors')} ({time.time() - t0:.0f}s)",
                  flush=True)
    mdir = out / "_manifests"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / f"crypto-{a.market}-{label}-{a.shard.replace('/', 'of')}.json").write_text(json.dumps(entries, indent=1))
    print(f"[lake] done: {len(entries)} symbols, errors {sum(1 for e in entries if e.get('state') == 'error')}")
    return 0  # per-symbol failures are in the manifest + health record; one symbol never fails the run


if __name__ == "__main__":
    sys.exit(main())
