#!/usr/bin/env python3
# wiring: .github/workflows/etf-history-pipeline.yml (runner holding the Alpaca Actions secrets; store synced to the trainer)
"""Multi-year ETF/equity bar history from the Alpaca Market Data API -> the canonical store.

WHY (operator, 2026-11-01): "there's no way we are limited to 2 years of etf data". Lanes fell back to Yahoo 1h
(~730 d cap) because the Alpaca keys live only in Actions secrets / on the VMs, never in a lane sandbox. This
is the pipeline that runs WHERE THE KEYS ARE (a runner) and lands the data where the ML/research lanes read.

STORE (``--out``, on the trainer ``data/etf_history/``)::

    <SYM>/<tf>.parquet        timestamp(UTC), open, high, low, close, volume, trade_count, vwap
    corporate_actions.csv     dividends + splits, SEPARATE from the bars (bars are split-adjusted ONLY)
    MANIFEST.json             per symbol/tf: feed, first, last, rows, adjustment, fetched_at

SEMANTICS (the contract a reader can rely on)
  * adjustment = ``split`` : prices are split-adjusted, NOT dividend-adjusted. Dividends are in
    corporate_actions.csv (ex_date, rate) so a total-return series is reconstructable and nothing is baked in.
  * point-in-time : every bar is stamped at its bar-OPEN (UTC) and carries only that bar's trades. No later
    bar is ever used to fill an earlier one. (Split adjustment is as-of-today by construction; the splits table
    lets a reader reconstruct raw prices.) A refresh that sees an already-stored bar change (a new split
    re-adjusted history) refetches that symbol from scratch and says so in the manifest.
  * feed : ``sip`` (consolidated tape, 2016+; the free plan serves historical SIP with a 15-minute delay) is
    preferred; ``iex`` (single exchange, thinner volume) is the fallback. The feed actually used is recorded
    PER symbol/tf in the manifest -- never assumed.

KEYS: ``ALPACA_API_KEY_ID_LIVE``/``ALPACA_API_SECRET_KEY_LIVE`` (or the paper pair) from the environment only.
Nothing here prints or writes a key, a balance or an account number. Market data only.

    python3 scripts/ops/fetch_etf_history.py --mode probe
    python3 scripts/ops/fetch_etf_history.py --mode backfill --out data/etf_history
    python3 scripts/ops/fetch_etf_history.py --mode refresh  --out data/etf_history
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import pandas as pd

DATA_URL = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets").rstrip("/")
# Alpaca timeframe token per our label.
TF_API = {"5m": "5Min", "15m": "15Min", "1h": "1Hour", "1d": "1Day"}
# Universe: every ETF/equity the alpaca_* and ib_* legs trade (config/accounts.yaml symbols) + the liquid set.
ROSTER = ["SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "SLV", "GDX", "USO", "TQQQ", "QLD", "SPYM", "SPLG", "IAUM", "SCHA"]
LIQUID = ["XLE", "XLF", "XLK", "XLV", "XLI", "XLP", "XLU", "XLB", "XLY", "DIA", "HYG", "LQD", "EEM", "EFA", "VNQ", "SMH"]
UNIVERSE = ROSTER + [s for s in LIQUID if s not in ROSTER]
DEFAULT_START = "2016-01-04"  # Alpaca's documented start of stock bar history
OVERLAP_BARS_DAYS = 7  # refresh re-reads this many days to detect re-adjustment (splits)
_BASE_COLS = ["timestamp", "open", "high", "low", "close", "volume", "trade_count", "vwap"]

Getter = Callable[[str, Dict[str, Any]], Any]


def _keys() -> Dict[str, str]:
    for k, s in (("ALPACA_API_KEY_ID_LIVE", "ALPACA_API_SECRET_KEY_LIVE"), ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")):
        if os.environ.get(k) and os.environ.get(s):
            return {"APCA-API-KEY-ID": os.environ[k], "APCA-API-SECRET-KEY": os.environ[s]}
    raise SystemExit("no Alpaca data keys in the environment (ALPACA_API_KEY_ID_LIVE / ALPACA_API_SECRET_KEY_LIVE)")


def make_getter() -> Getter:
    import requests

    sess = requests.Session()
    sess.headers.update(_keys())

    def get(path: str, params: Dict[str, Any]) -> Any:
        for attempt in range(8):
            r = sess.get(DATA_URL + path, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(60, 2 ** attempt))
                continue
            if r.status_code >= 400:
                # Body can carry a message, never a key (the key is in a header we do not echo).
                raise RuntimeError(f"HTTP {r.status_code} {path}: {r.text[:200]}")
            return r.json()
        raise RuntimeError(f"HTTP retries exhausted {path}")

    return get


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_bars(get: Getter, sym: str, tf: str, start: datetime, end: datetime, feed: str) -> pd.DataFrame:
    """All bars for ``sym`` in [start, end], split-adjusted, paged to exhaustion."""
    rows: List[Dict[str, Any]] = []
    params: Dict[str, Any] = {
        "symbols": sym, "timeframe": TF_API[tf], "start": _iso(start), "end": _iso(end),
        "adjustment": "split", "feed": feed, "limit": 10000, "sort": "asc",
    }
    while True:
        j = get("/v2/stocks/bars", params)
        rows.extend((j.get("bars") or {}).get(sym) or [])
        tok = j.get("next_page_token")
        if not tok:
            break
        params["page_token"] = tok
    return bars_to_frame(rows)


def bars_to_frame(rows: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    if df.empty:
        return pd.DataFrame(columns=_BASE_COLS)
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
                            "n": "trade_count", "vw": "vwap"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for c in _BASE_COLS:
        if c not in df.columns:
            df[c] = float("nan")
    df = df[_BASE_COLS].drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return df


def fetch_corporate_actions(get: Getter, syms: List[str], start: datetime, end: datetime) -> pd.DataFrame:
    """Cash dividends + splits (one row each). Failure is returned as an empty frame + reason, never a crash."""
    out: List[Dict[str, Any]] = []
    for i in range(0, len(syms), 20):
        params: Dict[str, Any] = {
            "symbols": ",".join(syms[i:i + 20]), "types": "cash_dividend,forward_split,reverse_split",
            "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "limit": 1000,
        }
        while True:
            j = get("/v1/corporate-actions", params)
            for kind, recs in (j.get("corporate_actions") or {}).items():
                for r in recs or []:
                    out.append({"kind": kind, "symbol": r.get("symbol"), "ex_date": r.get("ex_date") or r.get("process_date"),
                                "rate": r.get("rate"), "new_rate": r.get("new_rate"), "old_rate": r.get("old_rate"),
                                "record_date": r.get("record_date"), "payable_date": r.get("payable_date")})
            tok = j.get("next_page_token")
            if not tok:
                break
            params["page_token"] = tok
    cols = ["kind", "symbol", "ex_date", "rate", "new_rate", "old_rate", "record_date", "payable_date"]
    return pd.DataFrame(out, columns=cols).sort_values(["symbol", "ex_date"]).reset_index(drop=True) if out else pd.DataFrame(columns=cols)


def pick_feed(get: Getter, preferred: str) -> str:
    """sip if the plan serves it, else iex. Probed with a tiny request; the answer is recorded, not assumed."""
    if preferred != "auto":
        return preferred
    end = datetime.now(timezone.utc) - timedelta(minutes=30)
    try:
        get("/v2/stocks/bars", {"symbols": "SPY", "timeframe": "1Day", "start": _iso(end - timedelta(days=10)),
                               "end": _iso(end), "feed": "sip", "limit": 1})
        return "sip"
    except RuntimeError as e:
        print(f"feed probe: sip refused ({str(e)[:120]}); using iex", file=sys.stderr)
        return "iex"


def _path(root: Path, sym: str, tf: str) -> Path:
    return root / sym / f"{tf}.parquet"


def read_bars(root: Path, sym: str, tf: str) -> pd.DataFrame:
    """THE reader. ``read_bars(Path('data/etf_history'), 'SPY', '1h')`` -> UTC-indexed-by-column OHLCV frame."""
    p = _path(Path(root), sym, tf)
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=_BASE_COLS)


def _write_atomic(df: pd.DataFrame, p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, p)


def update_symbol(get: Getter, root: Path, sym: str, tf: str, feed: str, start: datetime, end: datetime,
                  full: bool) -> Dict[str, Any]:
    old = pd.DataFrame(columns=_BASE_COLS) if full else read_bars(root, sym, tf)
    note = ""
    if len(old):
        last = old["timestamp"].max()
        since = last - timedelta(days=OVERLAP_BARS_DAYS)
        new = fetch_bars(get, sym, tf, since.to_pydatetime(), end, feed)
        ov = old.merge(new, on="timestamp", suffixes=("_o", "_n"))
        if len(ov) and ((ov["close_o"] - ov["close_n"]).abs() / ov["close_o"].abs().clip(lower=1e-9) > 1e-6).any():
            note = "re-adjusted (split) -> full refetch"
            new = fetch_bars(get, sym, tf, start, end, feed)
            merged = new
        else:
            merged = pd.concat([old, new[new["timestamp"] > last]], ignore_index=True)
    else:
        merged = fetch_bars(get, sym, tf, start, end, feed)
    if len(merged) < len(old):
        raise RuntimeError(f"{sym} {tf}: refusing a shrinking write ({len(old)} -> {len(merged)})")
    merged = merged.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    if len(merged):
        _write_atomic(merged, _path(root, sym, tf))
    return {"symbol": sym, "tf": tf, "feed": feed, "adjustment": "split", "rows": int(len(merged)),
            "first": _iso(merged["timestamp"].min().to_pydatetime()) if len(merged) else None,
            "last": _iso(merged["timestamp"].max().to_pydatetime()) if len(merged) else None,
            "added": int(len(merged) - len(old)), "note": note,
            "fetched_at": _iso(datetime.now(timezone.utc))}


def probe(get: Getter) -> List[Dict[str, Any]]:
    """MEASURE what the plan serves: per feed x timeframe, the earliest bar and a bar count for SPY, 2016 onward."""
    end = datetime.now(timezone.utc) - timedelta(minutes=30)
    start = datetime.fromisoformat(DEFAULT_START).replace(tzinfo=timezone.utc)
    out = []
    for feed in ("sip", "iex"):
        for tf in ("1d", "1h", "5m"):
            rec: Dict[str, Any] = {"feed": feed, "tf": tf}
            try:
                j = get("/v2/stocks/bars", {"symbols": "SPY", "timeframe": TF_API[tf], "start": _iso(start), "end": _iso(end),
                                            "adjustment": "split", "feed": feed, "limit": 5, "sort": "asc"})
                bars = (j.get("bars") or {}).get("SPY") or []
                rec.update(status="ok", earliest=bars[0]["t"] if bars else None)
                j2 = get("/v2/stocks/bars", {"symbols": "SPY", "timeframe": TF_API[tf], "start": _iso(end - timedelta(days=30)),
                                             "end": _iso(end), "adjustment": "split", "feed": feed, "limit": 1, "sort": "desc"})
                b2 = (j2.get("bars") or {}).get("SPY") or []
                rec["latest"] = b2[0]["t"] if b2 else None
            except RuntimeError as e:
                rec.update(status="refused", error=str(e)[:160])
            out.append(rec)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["probe", "backfill", "refresh"], required=True)
    ap.add_argument("--out", default="data/etf_history")
    ap.add_argument("--symbols", default=",".join(UNIVERSE))
    ap.add_argument("--tfs", default="1h,5m")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--feed", choices=["auto", "sip", "iex"], default="auto")
    a = ap.parse_args(argv)

    get = make_getter()
    if a.mode == "probe":
        print(json.dumps(probe(get), indent=1))
        return 0

    root = Path(a.out)
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    tfs = [t.strip() for t in a.tfs.split(",") if t.strip()]
    feed = pick_feed(get, a.feed)
    end = datetime.now(timezone.utc) - timedelta(minutes=30)  # free-plan SIP is 15-min delayed
    start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
    mpath = root / "MANIFEST.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"series": {}}
    failures: List[str] = []
    for sym in syms:
        for tf in tfs:
            try:
                rec = update_symbol(get, root, sym, tf, feed, start, end, full=(a.mode == "backfill"))
                manifest["series"][f"{sym}/{tf}"] = rec
                print(f"{sym} {tf} [{feed}] rows={rec['rows']} +{rec['added']} {rec['first']} -> {rec['last']} {rec['note']}", flush=True)
            except Exception as e:  # contained per item (Prime Directive: a failing item never halts the pipeline)
                failures.append(f"{sym}/{tf}: {str(e)[:160]}")
                print(f"FAIL {sym} {tf}: {str(e)[:160]}", file=sys.stderr, flush=True)
    try:
        ca = fetch_corporate_actions(get, syms, start, end)
        root.mkdir(parents=True, exist_ok=True)
        ca.to_csv(root / "corporate_actions.csv", index=False)
        manifest["corporate_actions"] = {"rows": int(len(ca)), "fetched_at": _iso(datetime.now(timezone.utc))}
    except Exception as e:
        failures.append(f"corporate_actions: {str(e)[:160]}")
        manifest["corporate_actions"] = {"error": str(e)[:160]}
    manifest["failures"] = failures
    manifest["updated_at"] = _iso(datetime.now(timezone.utc))
    root.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
