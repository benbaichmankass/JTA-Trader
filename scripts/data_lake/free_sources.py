#!/usr/bin/env python3
# wiring: .github/workflows/market-data-lake.yml (universe / macro / futures jobs) -> scripts/data_lake/hf_publish.py
"""Non-crypto free sources for the market data lake: universe snapshots, FRED rates/FX/macro, daily futures fronts.

Row MARKET-DATA-LAKE; design docs/data/market-data-lake.md; selection in config/data_universe.yaml.

    python3 scripts/data_lake/free_sources.py universe --out lake      # universe/us_equity/<date>.csv (+ crypto lists)
    python3 scripts/data_lake/free_sources.py fred     --out lake      # macro/fred/1d|1mo/<SERIES>.parquet
    python3 scripts/data_lake/free_sources.py futures  --out lake      # futures/yahoo_cont/1d/<ROOT>.parquet
    python3 scripts/data_lake/free_sources.py import-etf --src store --out lake   # ETF-HISTORY-PIPELINE store -> lake

Every series writes a manifest entry (source, licence, first/last, rows) to <out>/_manifests/. A failing series is
recorded and skipped -- the run never halts on one series; the next run retries it.

POINT-IN-TIME caveats, stated rather than hidden:
  * FRED values are the CURRENT vintage. Revised series (CPI, payrolls, INDPRO...) are therefore NOT point-in-time;
    the manifest marks them `pit: false`. A PIT read needs ALFRED vintages (filed as a follow-up in the design doc).
    Market-observed series (yields, FX, spreads, VIX) are not revised and are marked `pit: true`.
  * Yahoo `=F` continuous fronts are back-adjusted by nobody (raw roll jumps); marked `roll: raw_front`.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
UA = {"User-Agent": "Mozilla/5.0 (jta-trader market-data-lake)"}
REVISED = {"CPIAUCSL", "CPILFESL", "PCEPILFE", "UNRATE", "PAYEMS", "INDPRO", "M2SL", "UMCSENT", "HOUST", "RSAFS",
           "ICSA", "NFCI", "STLFSI4"}


def _cfg() -> Dict:
    return yaml.safe_load((REPO_ROOT / "config" / "data_universe.yaml").read_text())


def _get(url: str, tries: int = 6, timeout: int = 60) -> bytes:
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 404):
                raise
        except Exception as e:
            last = e
        time.sleep(min(60, 3 * 2 ** i))
    raise RuntimeError(f"GET failed: {url}: {last}")


def _write_manifest(out: Path, name: str, entries: List[Dict]) -> None:
    d = out / "_manifests"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(entries, indent=1))


def _entry(asset_class, market, tf, symbol, df, path, out, **kw) -> Dict:
    e = {"asset_class": asset_class, "market": market, "tf": tf, "symbol": symbol,
         "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **kw}
    if df is None or df.empty:
        e.update(rows=0, first=None, last=None, state=kw.get("state", "empty"))
        return e
    e.update(rows=int(len(df)), first=pd.Timestamp(df["ts"].iloc[0]).isoformat(),
             last=pd.Timestamp(df["ts"].iloc[-1]).isoformat(), path=str(path.relative_to(out)),
             bytes=path.stat().st_size, state="ok")
    return e


# ---------------------------------------------------------------- universe
def parse_nasdaqtraded(text: str) -> pd.DataFrame:
    rows = [ln.split("|") for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df[df["Test Issue"] == "N"].copy()
    df["is_etf"] = df["ETF"] == "Y"
    name = df["Security Name"].str.lower()
    junk = name.str.contains(r"\b(?:warrant|right|unit|units|preferred|depositary shares? representing|notes due)\b",
                             regex=True)
    df["is_common"] = (~df["is_etf"]) & (~junk) & (~df["Symbol"].str.contains(r"[\.\$\^=]", regex=True))
    return df[["Symbol", "Security Name", "Listing Exchange", "is_etf", "is_common"]].rename(
        columns={"Symbol": "symbol", "Security Name": "name", "Listing Exchange": "exchange"})


def cmd_universe(a) -> int:
    out = Path(a.out)
    today = date.today().isoformat()
    df = parse_nasdaqtraded(_get("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt").decode())
    d = out / "universe" / "us_equity"
    d.mkdir(parents=True, exist_ok=True)
    df.to_csv(d / f"{today}.csv", index=False)
    summary = {"date": today, "us_listed": int(len(df)), "etf": int(df["is_etf"].sum()),
               "common_stock": int(df["is_common"].sum()), "source": "nasdaqtrader.com nasdaqtraded.txt"}
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from binance_vision_lake import list_symbols  # noqa: E402
    for m in ("um_perp", "spot"):
        syms = list_symbols(m)
        cd = out / "universe" / "crypto"
        cd.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"symbol": syms}).to_csv(cd / f"{m}-{today}.csv", index=False)
        summary[f"binance_{m}_archive_symbols"] = len(syms)
    (out / "universe" / "SUMMARY.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))
    return 0


# ---------------------------------------------------------------- FRED
def fred_series(sid: str) -> pd.DataFrame:
    raw = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}").decode()
    df = pd.read_csv(io.StringIO(raw))
    df.columns = ["ts", "value"]
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED writes '.' for no observation
    return df.dropna().reset_index(drop=True)


def cmd_fred(a) -> int:
    out = Path(a.out)
    cfg = _cfg()
    jobs: List[tuple] = []
    for s in (cfg["fx"]["daily"]["series"]):
        jobs.append(("fx", "fred", "1d", s, cfg["fx"]["daily"]["licence"]))
    for grp, series in cfg["macro"]["daily"]["series"].items():
        for s in series:
            jobs.append(("macro", f"fred_{grp}", "1d", s, cfg["macro"]["daily"]["licence"]))
    for s in cfg["macro"]["monthly"]["series"]:
        jobs.append(("macro", "fred_monthly", "1mo", s, cfg["macro"]["daily"]["licence"]))
    entries = []
    for ac, market, tf, sid, lic in jobs:
        try:
            df = fred_series(sid)
            p = out / ac / market / tf / f"{sid}.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False)
            e = _entry(ac, market, tf, sid, df, p, out, source="fred.stlouisfed.org", licence=lic,
                       pit=sid not in REVISED)
        except Exception as ex:
            e = _entry(ac, market, tf, sid, None, None, out, source="fred", licence=lic, state="error",
                       errors=[str(ex)[:200]])
        entries.append(e)
        print(f"[fred] {sid}: {e['state']} rows={e['rows']} {e.get('first')}..{e.get('last')}", flush=True)
        time.sleep(0.3)
    _write_manifest(out, "fred", entries)
    return 0


# ---------------------------------------------------------------- futures (Yahoo daily continuous fronts)
def yahoo_daily(sym: str) -> pd.DataFrame:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}"
           f"?period1=0&period2={int(time.time())}&interval=1d&events=div%2Csplit")
    j = json.loads(_get(url))
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": pd.to_datetime(r["timestamp"], unit="s", utc=True), "open": q["open"],
                       "high": q["high"], "low": q["low"], "close": q["close"], "volume": q["volume"]})
    return df.dropna(subset=["close"]).reset_index(drop=True)


def cmd_futures(a) -> int:
    out = Path(a.out)
    spec = _cfg()["futures"]["daily_continuous"]
    entries = []
    for sym in spec["symbols"]:
        root = sym.replace("=F", "")
        try:
            df = yahoo_daily(sym)
            p = out / "futures" / "yahoo_cont" / "1d" / f"{root}.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False)
            e = _entry("futures", "yahoo_cont", "1d", root, df, p, out, source="yahoo chart", licence=spec["licence"],
                       roll="raw_front")
        except Exception as ex:
            e = _entry("futures", "yahoo_cont", "1d", root, None, None, out, source="yahoo", licence=spec["licence"],
                       state="error", errors=[str(ex)[:200]])
        entries.append(e)
        print(f"[futures] {sym}: {e['state']} rows={e['rows']} {e.get('first')}..{e.get('last')}", flush=True)
        time.sleep(1.0)
    _write_manifest(out, "futures-yahoo", entries)
    return 0


# ---------------------------------------------------------------- ETF/equity bars (ETF-HISTORY-PIPELINE store)
TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}


def cmd_import_etf(a) -> int:
    """Re-shape the ETF-HISTORY-PIPELINE store (<SYM>/<tf>.parquet, column ``timestamp``) into the lake layout
    us_equity/alpaca/<tf>/<SYM>.parquet (column ``ts``), carrying its MANIFEST (feed, adjustment) per series.
    The ETF lane owns the fetch; this only publishes what it built."""
    src, out = Path(a.src), Path(a.out)
    if not src.exists():
        print(f"[etf] no ETF-HISTORY-PIPELINE store at {src}; nothing to publish (state recorded)")
        _write_manifest(out, "us_equity-alpaca", [])
        return 0
    meta = {}
    mp = src / "MANIFEST.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text())
        except Exception:
            meta = {}
    entries = []
    for f in sorted(src.glob("*/*.parquet")):
        sym, tf = f.parent.name, f.stem
        try:
            df = pd.read_parquet(f)
            if "timestamp" in df.columns:
                df = df.rename(columns={"timestamp": "ts"})
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
            p = out / "us_equity" / "alpaca" / tf / f"{sym}.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False, compression="zstd")
            m = ((meta.get("series") or meta).get(sym) or {}) if isinstance(meta, dict) else {}
            m = m.get(tf, m) if isinstance(m, dict) else {}
            e = _entry("us_equity", "alpaca", tf, sym, df, p, out, source="alpaca market data (ETF-HISTORY-PIPELINE)",
                       licence="Alpaca market-data terms; private store only",
                       feed=m.get("feed"), adjustment=m.get("adjustment", "split"))
            e["is_etf"] = True
        except Exception as ex:
            e = _entry("us_equity", "alpaca", tf, sym, None, None, out, source="alpaca", licence="alpaca",
                       state="error", errors=[str(ex)[:200]])
        entries.append(e)
    _write_manifest(out, "us_equity-alpaca", entries)
    print(f"[etf] imported {sum(e['state'] == 'ok' for e in entries)} / {len(entries)} series from {src}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["universe", "fred", "futures", "import-etf"])
    ap.add_argument("--out", default="lake")
    ap.add_argument("--src", default="store", help="import-etf: the ETF-HISTORY-PIPELINE store directory")
    a = ap.parse_args(argv)
    return {"universe": cmd_universe, "fred": cmd_fred, "futures": cmd_futures,
            "import-etf": cmd_import_etf}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
