#!/usr/bin/env python3
# wiring: .github/workflows/market-data-lake.yml (crypto shards) -> scripts/data_lake/hf_publish.py -> HF dataset
"""Crypto half of the market data lake: EVERY Binance USD-M perp + the major spot pairs, full history, keyless.

WHY (operator, 2026-11-01 12:38Z): the general (pooled) ML models train on as much market data as can be found, and the
datasets are created and stored on Hugging Face / Kaggle, not on our VMs. Row MARKET-DATA-LAKE; design
docs/data/market-data-lake.md.

SOURCE  data.binance.vision (Binance's public archive). The symbol list comes from the archive's own S3 listing, so it
        INCLUDES DELISTED contracts (survivorship-free) -- never from the live exchangeInfo (which 451s from US hosts and
        lists only what trades today).
        Licence: Binance Terms of Use; no open-data licence => PRIVATE stores only (private HF / Kaggle dataset).

OUTPUT  <out>/crypto/<market>/<tf>/<SYMBOL>.parquet   (market = um_perp | spot)
        columns: ts (UTC, bar OPEN), open, high, low, close, volume, quote_volume, trades,
                 taker_buy_volume, taker_buy_quote_volume
        <out>/_manifests/crypto-<market>-<tf>-<shard>.json   one entry per symbol (see ``_entry``)

POINT-IN-TIME  Every bar is stamped at its open and carries only that bar's trades; nothing is forward-filled; gaps are
        COUNTED in the manifest, never patched. Each monthly zip is checked against Binance's own .CHECKSUM (sha256).

    python3 scripts/data_lake/binance_vision_lake.py --market um_perp --tf 1h --list-only
    python3 scripts/data_lake/binance_vision_lake.py --market um_perp --tf 1h --shard 0/8 --out lake
    python3 scripts/data_lake/binance_vision_lake.py --market spot --tf 1h --symbols-from config  --out lake
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
from typing import Dict, List, Optional, Sequence, Tuple

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
        prefixes += [p.text for p in root.findall("s3:CommonPrefixes/s3:Prefix", _NS)]
        keys += [k.text for k in root.findall("s3:Contents/s3:Key", _NS)]
        truncated = (root.findtext("s3:IsTruncated", default="false", namespaces=_NS) == "true")
        if not truncated:
            return prefixes, keys
        marker = root.findtext("s3:NextMarker", default="", namespaces=_NS) or (keys[-1] if keys else prefixes[-1])


def list_symbols(market: str) -> List[str]:
    prefixes, _ = s3_list(f"{MARKETS[market]}/monthly/klines/")
    return sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in prefixes)


def list_files(market: str, symbol: str, tf: str, period: str = "monthly") -> List[str]:
    _, keys = s3_list(f"{MARKETS[market]}/{period}/klines/{symbol}/{tf}/", delimiter="")
    return sorted(k for k in keys if k.endswith(".zip"))


def parse_kline_csv(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8", "replace")
    has_header = text[:20].lower().startswith("open_time")
    df = pd.read_csv(io.StringIO(text), header=0 if has_header else None, names=None if has_header else RAW_COLS)
    df.columns = RAW_COLS[: len(df.columns)]
    if df.empty:
        return pd.DataFrame(columns=OUT_COLS)
    ot = pd.to_numeric(df["open_time"], errors="coerce")
    # Binance switched spot files to MICROseconds from 2025-01; perps stay ms. Decide per file by magnitude.
    unit = "us" if ot.max() > 10 ** 14 else "ms"
    out = pd.DataFrame({"ts": pd.to_datetime(ot, unit=unit, utc=True)})
    for c in OUT_COLS[1:]:
        out[c] = pd.to_numeric(df[c], errors="coerce")
    out["trades"] = out["trades"].astype("int64", errors="ignore")
    return out.dropna(subset=["ts"])


def fetch_zip(key: str, verify: bool = True) -> Tuple[pd.DataFrame, str]:
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
        name = zf.namelist()[0]
        return parse_kline_csv(zf.read(name)), state


def gap_stats(ts: pd.Series, tf: str) -> Dict[str, object]:
    step = pd.Timedelta(minutes=TF_MINUTES[tf])
    if len(ts) < 2:
        return {"expected_rows": int(len(ts)), "missing_bars": 0, "gaps": 0, "largest_gap_bars": 0}
    d = ts.diff().dropna()
    big = d[d > step]
    missing = int(((big / step) - 1).round().sum()) if len(big) else 0
    expected = int(((ts.iloc[-1] - ts.iloc[0]) / step)) + 1
    return {"expected_rows": expected, "missing_bars": missing, "gaps": int(len(big)),
            "largest_gap_bars": int(round(big.max() / step) - 1) if len(big) else 0}


def build_symbol(market: str, symbol: str, tf: str, out: Path, daily_tail: bool = True,
                 workers: int = 8) -> Dict[str, object]:
    keys = list_files(market, symbol, tf, "monthly")
    entry: Dict[str, object] = {"asset_class": "crypto", "market": market, "symbol": symbol, "tf": tf,
                                "source": "data.binance.vision", "licence": "Binance ToU; private store only",
                                "months": len(keys), "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    frames: List[pd.DataFrame] = []
    checks: Dict[str, int] = {}
    errors: List[str] = []

    def one(k: str):
        try:
            return fetch_zip(k)
        except Exception as e:  # contained per file; counted, retried next run
            return e

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, res in zip(keys, ex.map(one, keys)):
            if isinstance(res, Exception):
                errors.append(f"{k.rsplit('/', 1)[-1]}: {res}"[:200])
                continue
            df, st = res
            checks[st] = checks.get(st, 0) + 1
            frames.append(df)
    if daily_tail and keys:
        # The current month exists only as daily files; add the days after the last monthly file.
        last_month = re.search(r"(\d{4}-\d{2})\.zip$", keys[-1]).group(1)
        dkeys = [k for k in list_files(market, symbol, tf, "daily")
                 if re.search(r"(\d{4}-\d{2})-\d{2}\.zip$", k).group(1) > last_month]
        entry["daily_files"] = len(dkeys)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for k, res in zip(dkeys, ex.map(one, dkeys)):
                if isinstance(res, Exception):
                    errors.append(f"{k.rsplit('/', 1)[-1]}: {res}"[:200])
                    continue
                checks[res[1]] = checks.get(res[1], 0) + 1
                frames.append(res[0])
    entry["checksum"] = checks
    entry["errors"] = errors[:20]
    entry["n_errors"] = len(errors)
    if not frames:
        entry.update({"rows": 0, "first": None, "last": None, "state": "empty" if not errors else "error"})
        return entry
    df = pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    path = out / "crypto" / market / tf / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df[OUT_COLS].to_parquet(path, index=False, compression="zstd")
    entry.update({"rows": int(len(df)), "first": df["ts"].iloc[0].isoformat(), "last": df["ts"].iloc[-1].isoformat(),
                  "path": str(path.relative_to(out)), "bytes": path.stat().st_size,
                  "median_quote_volume_usd": float(df["quote_volume"].median()),
                  "state": "ok" if not errors else "partial"})
    entry.update(gap_stats(df["ts"], tf))
    return entry


def shard(items: Sequence[str], spec: str) -> List[str]:
    i, n = (int(x) for x in spec.split("/"))
    return [s for j, s in enumerate(items) if j % n == i]


def symbols_from_config(market: str, tf: str) -> Optional[List[str]]:
    """Explicit symbol list from config/data_universe.yaml for (market, tf), or None meaning ALL."""
    import yaml
    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "data_universe.yaml").read_text())
    spec = (((cfg.get("crypto") or {}).get(market)) or {})
    tiers = spec.get("timeframes") or {}
    sel = tiers.get(tf)
    if sel in (None, "all"):
        return None
    return list(sel)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", choices=sorted(MARKETS), required=True)
    ap.add_argument("--tf", choices=sorted(TF_MINUTES), required=True)
    ap.add_argument("--out", default="lake")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--symbols", default="", help="comma list; default = config/data_universe.yaml selection")
    ap.add_argument("--quote", default="", help="keep only symbols ending in this quote (e.g. USDT)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--census", action="store_true", help="list the archive only: per-symbol months, no downloads")
    ap.add_argument("--workers", type=int, default=8, help="parallel file downloads per symbol")
    ap.add_argument("--parallel", type=int, default=4, help="symbols built concurrently")
    a = ap.parse_args(argv)
    out = Path(a.out)
    listed = list_symbols(a.market)
    chosen = [s.strip() for s in a.symbols.split(",") if s.strip()] or symbols_from_config(a.market, a.tf) or listed
    missing_from_archive = sorted(set(chosen) - set(listed))
    chosen = [s for s in chosen if s in set(listed)]
    if a.quote:
        chosen = [s for s in chosen if s.endswith(a.quote)]
    chosen = shard(sorted(chosen), a.shard)
    if a.limit:
        chosen = chosen[: a.limit]
    print(f"[lake] {a.market} {a.tf}: archive lists {len(listed)} symbols; this shard {a.shard} builds {len(chosen)}"
          f"; requested-but-not-in-archive {len(missing_from_archive)}", flush=True)
    if a.census:
        # Archive census without downloading: monthly files per symbol -> first/last month, months, bar-count bound.
        def cen(sym):
            try:
                ks = list_files(a.market, sym, a.tf, "monthly")
            except Exception as ex:
                return {"symbol": sym, "error": str(ex)[:120]}
            ms = [re.search(r"(\d{4}-\d{2})\.zip$", k).group(1) for k in ks]
            return {"symbol": sym, "months": len(ms), "first_month": ms[0] if ms else None, "last_month": ms[-1] if ms else None}
        with ThreadPoolExecutor(max_workers=32) as ex:
            rows = list(ex.map(cen, chosen))
        mdir = out / "_census"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / f"crypto-{a.market}-{a.tf}.json").write_text(json.dumps(rows, indent=1))
        have = [r for r in rows if r.get("months")]
        months = sum(r["months"] for r in have)
        per = 30.44 * 1440 / TF_MINUTES[a.tf]
        print(json.dumps({"market": a.market, "tf": a.tf, "symbols_with_data": len(have), "symbols_listed": len(rows),
                          "first_month": min((r["first_month"] for r in have), default=None),
                          "last_month": max((r["last_month"] for r in have), default=None),
                          "symbol_months": months, "rows_upper_bound": int(months * per)}))
        return 0
    if a.list_only:
        print(json.dumps({"listed": len(listed), "chosen": chosen, "not_in_archive": missing_from_archive}))
        return 0
    entries = []
    t0 = time.time()

    def run(sym: str) -> Dict[str, object]:
        try:
            return build_symbol(a.market, sym, a.tf, out, workers=a.workers)
        except Exception as ex:  # contained per symbol (no-halting): recorded, the next run retries
            return {"asset_class": "crypto", "market": a.market, "symbol": sym, "tf": a.tf, "state": "error",
                    "errors": [str(ex)[:300]], "rows": 0}

    with ThreadPoolExecutor(max_workers=max(1, a.parallel)) as ex:
        for n, e in enumerate(ex.map(run, chosen), 1):
            entries.append(e)
            print(f"[lake] {n}/{len(chosen)} {e['symbol']} {a.tf}: {e.get('state')} rows={e.get('rows')} "
                  f"{e.get('first')}..{e.get('last')} missing={e.get('missing_bars')} ({time.time() - t0:.0f}s)",
                  flush=True)
    mdir = out / "_manifests"
    mdir.mkdir(parents=True, exist_ok=True)
    tag = a.shard.replace("/", "of")
    (mdir / f"crypto-{a.market}-{a.tf}-{tag}.json").write_text(json.dumps(entries, indent=1))
    bad = [e["symbol"] for e in entries if e.get("state") == "error"]
    print(f"[lake] done: {len(entries)} symbols, {sum(int(e.get('rows') or 0) for e in entries)} rows, errors {len(bad)}")
    return 0  # per-symbol failures are in the manifest; the run itself is not failed by one symbol


if __name__ == "__main__":
    sys.exit(main())
