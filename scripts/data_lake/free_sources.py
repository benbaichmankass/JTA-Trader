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
UA = {"User-Agent": "jta-trader-market-data-lake/1 (research; contact via github.com/benbaichmankass)"}
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
    """Publish the ETF-HISTORY-PIPELINE store into the lake. Store layout (that lane's contract, 2026-11-01):
    <SYM>/<tf>/<YYYY>.parquet, column ``timestamp`` (UTC bar-open), MANIFEST.json series["SYM/tf"] = {status, feed,
    adjustment, ...}, corporate_actions.csv at the root. Lake layout: us_equity/alpaca/<tf>/<SYM>/<YYYY>.parquet
    (column ``ts``), one partition per year exactly as stored. The ETF lane owns the fetch; this only publishes.
    An empty or absent store (before that lane's first backfill) is recorded, not an error."""
    src, out = Path(a.src), Path(a.out)
    entries: List[Dict] = []
    meta = {}
    if (src / "MANIFEST.json").exists():
        try:
            meta = (json.loads((src / "MANIFEST.json").read_text()).get("series") or {})
        except Exception:
            meta = {}
    files = sorted(src.glob("*/*/*.parquet")) if src.exists() else []
    series: Dict[tuple, List[Path]] = {}
    for f in files:
        series.setdefault((f.parent.parent.name, f.parent.name), []).append(f)
    for (sym, tf), fs in sorted(series.items()):
        m = meta.get(f"{sym}/{tf}") or {}
        e = {"asset_class": "us_equity", "market": "alpaca", "tf": tf, "symbol": sym, "partitions": {},
             "source": "alpaca market data (ETF-HISTORY-PIPELINE)", "licence": "Alpaca market-data terms; private store only",
             "feed": m.get("feed"), "adjustment": m.get("adjustment", "split"), "vendor_status": m.get("status"),
             "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "state": "ok"}
        for f in fs:
            try:
                df = pd.read_parquet(f)
                if "timestamp" in df.columns:
                    df = df.rename(columns={"timestamp": "ts"})
                df["ts"] = pd.to_datetime(df["ts"], utc=True)
                df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
                if df.empty:
                    continue
                p = out / "us_equity" / "alpaca" / tf / sym / f.name
                p.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(p, index=False, compression="zstd")
                e["partitions"][f.stem] = {"rows": int(len(df)), "first": df["ts"].iloc[0].isoformat(),
                                           "last": df["ts"].iloc[-1].isoformat(), "bytes": p.stat().st_size,
                                           "path": str(p.relative_to(out)), "src": "etf_history"}
            except Exception as ex:
                e["state"] = "partial"
                e.setdefault("errors", []).append(f"{f.name}: {str(ex)[:150]}")
        entries.append(e)
    if (src / "corporate_actions.csv").exists():
        d = out / "us_equity" / "alpaca" / "corporate_actions"
        d.mkdir(parents=True, exist_ok=True)
        (d / "corporate_actions.csv").write_bytes((src / "corporate_actions.csv").read_bytes())
    _write_manifest(out, "us_equity-alpaca", entries)
    print(f"[etf] imported {len(entries)} series ({len(files)} year files) from {src}")
    return 0


# ---------------------------------------------------------------- options: CBOE implied-vol indices (VIX family)
def cmd_cboe(a) -> int:
    out = Path(a.out)
    spec = _cfg()["options_sources"]["cboe_iv_indices"]
    entries = []
    for sym in spec["symbols"]:
        try:
            raw = _get(f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{sym}_History.csv").decode()
            df = pd.read_csv(io.StringIO(raw))
            df.columns = [c.strip().lower() for c in df.columns]
            df = df.rename(columns={"date": "ts"})
            df["ts"] = pd.to_datetime(df["ts"], format="%m/%d/%Y", utc=True)
            df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
            p = out / "options" / "cboe_iv" / "1d" / f"{sym}.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False)
            e = _entry("options", "cboe_iv", "1d", sym, df, p, out, source="cdn.cboe.com daily_prices",
                       licence=spec["licence"], pit=True)
        except Exception as ex:
            e = _entry("options", "cboe_iv", "1d", sym, None, None, out, source="cboe", licence=spec["licence"],
                       state="error", errors=[str(ex)[:200]])
        entries.append(e)
        print(f"[cboe] {sym}: {e['state']} rows={e['rows']} {e.get('first')}..{e.get('last')}", flush=True)
    _write_manifest(out, "options-cboe", entries)
    return 0


# ---------------------------------------------------------------- CFTC Commitments of Traders (Socrata, keyless)
COT_DATASETS = {"legacy_futures": "6dca-aqww", "disaggregated_futures": "72hh-3qpy", "tff_futures": "gpe5-46if"}


def cmd_cot(a) -> int:
    out = Path(a.out)
    entries = []
    for name, ds in COT_DATASETS.items():
        rows: List[Dict] = []
        off, page = 0, 50000
        try:
            while True:
                url = (f"https://publicreporting.cftc.gov/resource/{ds}.json?$limit={page}&$offset={off}"
                       f"&$order=report_date_as_yyyy_mm_dd,cftc_contract_market_code")
                chunk = json.loads(_get(url, timeout=120))
                rows += chunk
                if len(chunk) < page:
                    break
                off += page
            df = pd.DataFrame(rows)
            df["ts"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"], utc=True)
            for c in df.columns:
                if c not in ("ts",) and df[c].dtype == object:
                    num = pd.to_numeric(df[c], errors="coerce")
                    if num.notna().mean() > 0.95:
                        df[c] = num
            df = df.sort_values(["ts", "cftc_contract_market_code"]).reset_index(drop=True)
            p = out / "macro" / "cftc_cot" / "1w" / f"{name}.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False, compression="zstd")
            # COT is as-of the Tuesday position date but RELEASED the following Friday: a PIT reader must lag 3 days.
            e = _entry("macro", "cftc_cot", "1w", name, df, p, out, source=f"publicreporting.cftc.gov {ds}",
                       licence="CFTC; US government public domain", n_markets=int(df["cftc_contract_market_code"].nunique()),
                       pit_note="ts = position date (Tue); published Fri 15:30 ET -> lag >= 3 days for PIT use")
        except Exception as ex:
            e = _entry("macro", "cftc_cot", "1w", name, None, None, out, source="cftc", licence="public domain",
                       state="error", errors=[str(ex)[:200]])
        entries.append(e)
        print(f"[cot] {name}: {e['state']} rows={e['rows']} markets={e.get('n_markets')} {e.get('first')}..{e.get('last')}",
              flush=True)
    _write_manifest(out, "macro-cot", entries)
    return 0


# ---------------------------------------------------------------- US stocks + ETFs: Alpaca daily for the WHOLE universe
def cmd_alpaca_daily(a) -> int:
    """1d split-adjusted SIP bars for every US-listed stock + ETF in today's universe snapshot PLUS Alpaca's INACTIVE
    (delisted) assets -- the broad daily layer. Intraday for ETFs is ETF-HISTORY-PIPELINE's. Keys from env only."""
    import os
    import requests
    out = Path(a.out)
    kid = os.environ.get("ALPACA_API_KEY_ID_LIVE") or os.environ.get("ALPACA_API_KEY_ID")
    sec = os.environ.get("ALPACA_API_SECRET_KEY_LIVE") or os.environ.get("ALPACA_API_SECRET_KEY")
    if not (kid and sec):
        print("[alpaca] no Alpaca data keys in env; skipping (recorded)")
        _write_manifest(out, "us_equity-alpaca-1d", [])
        return 0
    s = requests.Session()
    s.headers.update({"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec, **UA})
    snap = sorted((out / "universe" / "us_equity").glob("*.csv"))
    uni = pd.read_csv(snap[-1]) if snap else pd.DataFrame(columns=["symbol", "is_etf", "is_common"])
    uni = uni[(uni["is_etf"]) | (uni["is_common"])]
    kind = dict(zip(uni["symbol"], uni["is_etf"].map({True: "etf", False: "stock"})))
    inactive = []
    try:
        r = s.get("https://paper-api.alpaca.markets/v2/assets", params={"status": "inactive", "asset_class": "us_equity"},
                  timeout=120)
        r.raise_for_status()
        inactive = [x["symbol"] for x in r.json() if x.get("symbol") and "." not in x["symbol"]]
    except Exception as ex:
        print(f"[alpaca] inactive asset list unavailable: {str(ex)[:150]}")
    for sym in inactive:
        kind.setdefault(sym, "delisted")
    syms = sorted(kind)
    if a.limit:
        syms = syms[: a.limit]
    print(f"[alpaca] universe: {len(syms)} symbols ({len(inactive)} inactive listed)", flush=True)
    bars: Dict[str, List[Dict]] = {}
    for i in range(0, len(syms), 100):
        batch = syms[i:i + 100]
        tok = None
        while True:
            params = {"symbols": ",".join(batch), "timeframe": "1Day", "start": f"{a.since_year or 2016}-01-01T00:00:00Z",
                      "limit": 10000,
                      "adjustment": "split", "feed": "sip"}
            if tok:
                params["page_token"] = tok
            for attempt in range(8):
                r = s.get("https://data.alpaca.markets/v2/stocks/bars", params=params, timeout=120)
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(min(60, 2 ** attempt))
                    continue
                break
            if r.status_code >= 400:
                print(f"[alpaca] batch {i}: http {r.status_code} {r.text[:120]}")
                break
            j = r.json()
            for sym, bl in (j.get("bars") or {}).items():
                bars.setdefault(sym, []).extend(bl)
            tok = j.get("next_page_token")
            if not tok:
                break
        print(f"[alpaca] {min(i + 100, len(syms))}/{len(syms)} symbols, {sum(map(len, bars.values())):,} bars", flush=True)
    entries = []
    for sym in syms:
        bl = bars.get(sym)
        if not bl:
            entries.append(_entry("us_equity", "alpaca_sip", "1d", sym, None, None, out, source="alpaca",
                                  licence="Alpaca market-data terms; private store only", kind=kind[sym]))
            continue
        df = pd.DataFrame(bl).rename(columns={"t": "ts", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
                                              "n": "trades", "vw": "vwap"})
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
        e = {"asset_class": "us_equity", "market": "alpaca_sip", "tf": "1d", "symbol": sym, "partitions": {},
             "source": "alpaca /v2/stocks/bars sip", "licence": "Alpaca market-data terms; private store only",
             "kind": kind[sym], "adjustment": "split", "state": "ok",
             "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        for yr, g in df.groupby(df["ts"].dt.year):
            p = out / "us_equity" / "alpaca_sip" / "1d" / sym / f"{yr}.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            g.to_parquet(p, index=False, compression="zstd")
            e["partitions"][str(yr)] = {"rows": int(len(g)), "first": g["ts"].iloc[0].isoformat(),
                                        "last": g["ts"].iloc[-1].isoformat(), "bytes": p.stat().st_size,
                                        "path": str(p.relative_to(out)), "src": "alpaca"}
        entries.append(e)
    _write_manifest(out, "us_equity-alpaca-1d", entries)
    ok = [e for e in entries if e.get("partitions")]
    rows = sum(p["rows"] for e in ok for p in e["partitions"].values())
    print(f"[alpaca] wrote {len(ok)} / {len(entries)} series, {rows:,} rows")
    return 0


# ---------------------------------------------------------------- DoltHub (options chains, IV history, stocks) via `dolt sql -r csv`
def cmd_import_csv(a) -> int:
    """Partition a CSV exported by `dolt sql -r csv` into the lake. --kind chain|volatility|stocks."""
    out = Path(a.out)
    kinds = {"chain": ("options", "dolthub_chain", "1d"), "volatility": ("options", "dolthub_iv", "1d"),
             "stocks": ("us_equity", "dolthub", "1d")}
    ac, market, tf = kinds[a.kind]
    entries = []
    df = pd.read_csv(a.csv, low_memory=False)
    df["ts"] = pd.to_datetime(df["date"], utc=True)
    df = df.drop(columns=["date"])
    for sym, g in df.groupby("act_symbol"):
        g = g.sort_values("ts").reset_index(drop=True)
        p = out / ac / market / tf / f"{sym}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        g.to_parquet(p, index=False, compression="zstd")
        entries.append(_entry(ac, market, tf, str(sym), g, p, out, source="dolthub post-no-preference",
                              licence="DoltHub repo licence (see repo README); private store only",
                              distinct_days=int(g["ts"].nunique())))
    _write_manifest(out, f"dolthub-{a.kind}", entries)
    print(f"[dolt] {a.kind}: {len(entries)} symbols, {len(df):,} rows")
    return 0


# ---------------------------------------------------------------- options: ETF-HISTORY-PIPELINE daily chain snapshots
def cmd_import_option_snapshots(a) -> int:
    src, out = Path(a.src), Path(a.out)
    entries = []
    for und in sorted(d for d in src.glob("*") if d.is_dir()) if src.exists() else []:
        frames = []
        for f in sorted(und.glob("*.parquet")):
            try:
                frames.append(pd.read_parquet(f))
            except Exception:
                pass
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        tcol = next((c for c in ("ts", "snapshot_ts", "timestamp", "date") if c in df.columns), None)
        if tcol is None:
            continue
        df["ts"] = pd.to_datetime(df[tcol], utc=True)
        df = df.sort_values("ts").reset_index(drop=True)
        p = out / "options" / "alpaca_snapshot" / "1d" / f"{und.name}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False, compression="zstd")
        entries.append(_entry("options", "alpaca_snapshot", "1d", und.name, df, p, out,
                              source="ETF-HISTORY-PIPELINE options-snapshot-capture", licence="Alpaca terms; private",
                              distinct_days=int(df["ts"].dt.date.nunique())))
    _write_manifest(out, "options-snapshots", entries)
    print(f"[opt-snap] {len(entries)} underlyings from {src}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["universe", "fred", "futures", "import-etf", "cboe", "cot", "alpaca-daily",
                                    "import-csv", "import-option-snapshots"])
    ap.add_argument("--kind", choices=["chain", "volatility", "stocks"], default="volatility")
    ap.add_argument("--csv", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--since-year", type=int, default=0, help="alpaca-daily refresh: fetch from Jan 1 of this year only")
    ap.add_argument("--out", default="lake")
    ap.add_argument("--src", default="store", help="import-etf: the ETF-HISTORY-PIPELINE store directory")
    a = ap.parse_args(argv)
    return {"universe": cmd_universe, "fred": cmd_fred, "futures": cmd_futures,
            "import-etf": cmd_import_etf, "cboe": cmd_cboe, "cot": cmd_cot, "alpaca-daily": cmd_alpaca_daily,
            "import-csv": cmd_import_csv, "import-option-snapshots": cmd_import_option_snapshots}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
