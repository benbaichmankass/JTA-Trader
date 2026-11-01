#!/usr/bin/env python3
# wiring: .github/workflows/etf-history-pipeline.yml (runner holding the Alpaca Actions secrets; store synced to the trainer)
"""Multi-year equity/ETF bar history from the Alpaca Market Data API -> the canonical store. BASE TIMEFRAME 1m.

WHY (operator, 2026-11-01): "there's no way we are limited to 2 years of etf data", "we need to be collecting data on far more symbols
than that, even if we're not trading them yet", and (binding) "we should also be keeping the smallest timeframe data available - we can
always reconstruct higher timeframes on top of that". Lanes fell back to Yahoo 1h (~730 d cap) because the Alpaca keys live only in
Actions secrets / on the VMs, never in a lane sandbox. This runs WHERE THE KEYS ARE (a runner) and lands the data where the ML/research
lanes read. WHAT is collected is config/data_universe.yaml (a config edit widens it).

STORE (``--out``; on the trainer ``data/etf_history/``)::

    <SYM>/1m/<YYYY-MM>.parquet  the BASE: 1-minute bars, one file per MONTH so a daily refresh pulls/rewrites ~a month, not the history
    <SYM>/<tf>/<YYYY>.parquet   any other STORED timeframe (none by default), one file per year
                                columns: timestamp(UTC bar-open), open, high, low, close, volume, trade_count, vwap
    corporate_actions.csv       dividends + splits, SEPARATE from the bars (bars are split-adjusted ONLY)
    MANIFEST.json               per symbol/tf: status ok|no_data, feed, first, last, rows, years{}, long_gaps, fetched_at; run{}; failures[]

READER: ``read_bars(root, sym, tf, start=None, end=None)``. 5m / 15m / 30m / 1h / 4h are DERIVED on read from the 1m base by
``resample_bars`` (left-closed, labelled at the bar open, ``n_base`` + ``complete`` columns, never forward-filled); they are not fetched.

SEMANTICS (the contract a reader can rely on)
  * adjustment = ``split``: split-adjusted, NOT dividend-adjusted. Dividends are in corporate_actions.csv (ex_date, rate), so a
    total-return series is reconstructable and nothing is baked in.
  * point-in-time: every bar is stamped at its bar-OPEN (UTC) and carries only that bar's trades; no later bar fills an earlier
    one. Split adjustment is as-of-today by construction; the splits table lets a reader reconstruct raw prices. A refresh that
    sees an already-stored bar change (a new split re-adjusted history) refetches that symbol from scratch and says so.
  * feed: ``sip`` (consolidated tape; the free plan serves historical SIP with a 15-minute delay) is preferred, ``iex`` is the
    fallback. The feed actually used is recorded PER symbol/tf -- never assumed.
  * a symbol the vendor does not serve (delisted, renamed, wrong ticker) is ``no_data`` in the manifest: MEASURED, not an error.

BEHAVIOUR: resumable (a symbol already fresh is skipped in ``backfill``), rate-limited (default ~150 requests/min, under Alpaca's 200),
time-budgeted (``--budget-min``: stop cleanly, the next run resumes), and a failing symbol never halts the run.

KEYS: ``ALPACA_API_KEY_ID_LIVE``/``ALPACA_API_SECRET_KEY_LIVE`` (or the paper pair) from the environment only. Nothing here prints
or writes a key, a balance or an account number. Market data only.

    python3 scripts/ops/fetch_etf_history.py --mode probe
    python3 scripts/ops/fetch_etf_history.py --mode backfill --out store --budget-min 130
    python3 scripts/ops/fetch_etf_history.py --mode refresh  --out store
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_universe as du  # noqa: E402

DATA_URL = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets").rstrip("/")
TF_API = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "1h": "1Hour", "1d": "1Day"}
DEFAULT_START = "2016-01-04"  # Alpaca's documented start of stock bar history
OVERLAP_DAYS = 7              # a refresh re-reads this many days to detect re-adjustment (splits)
MIN_INTERVAL_S = 0.4          # ~150 requests/min
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
    last = [0.0]

    def get(path: str, params: Dict[str, Any]) -> Any:
        for attempt in range(8):
            wait = MIN_INTERVAL_S - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
            r = sess.get(DATA_URL + path, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(60, 2 ** attempt))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code} {path}: {r.text[:200]}")  # a key is in a header we never echo
            return r.json()
        raise RuntimeError(f"HTTP retries exhausted {path}")

    return get


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    return df[_BASE_COLS].drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def fetch_bars(get: Getter, sym: str, tf: str, start: datetime, end: datetime, feed: str) -> pd.DataFrame:
    """All bars for ``sym`` in [start, end], split-adjusted, paged to exhaustion."""
    rows: List[Dict[str, Any]] = []
    params: Dict[str, Any] = {"symbols": sym, "timeframe": TF_API[tf], "start": _iso(start), "end": _iso(end),
                              "adjustment": "split", "feed": feed, "limit": 10000, "sort": "asc"}
    while True:
        j = get("/v2/stocks/bars", params)
        rows.extend((j.get("bars") or {}).get(sym) or [])
        tok = j.get("next_page_token")
        if not tok:
            break
        params["page_token"] = tok
    return bars_to_frame(rows)


def fetch_corporate_actions(get: Getter, syms: List[str], start: datetime, end: datetime) -> pd.DataFrame:
    """Cash dividends + splits, one row each. Batches fail independently (a bad ticker in a batch drops that batch only)."""
    out: List[Dict[str, Any]] = []
    cols = ["kind", "symbol", "ex_date", "rate", "new_rate", "old_rate", "record_date", "payable_date"]
    for i in range(0, len(syms), 20):
        params: Dict[str, Any] = {"symbols": ",".join(syms[i:i + 20]), "types": "cash_dividend,forward_split,reverse_split",
                                  "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "limit": 1000}
        try:
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
        except RuntimeError as e:
            print(f"corporate actions batch {i // 20} failed: {str(e)[:120]}", file=sys.stderr)
    if not out:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(out, columns=cols).sort_values(["symbol", "ex_date"]).reset_index(drop=True)


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


# ------------------------------------------------------------------------------------------------ the partitioned store
# 1m (the BASE, operator 2026-11-01: "keep the smallest timeframe available") is partitioned by MONTH (<YYYY-MM>.parquet) so a
# daily refresh pulls/rewrites ~a month; every other stored timeframe is partitioned by YEAR (<YYYY>.parquet).
MONTHLY_TFS = {"1m"}
DERIVED_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def _ydir(root: Path, sym: str, tf: str) -> Path:
    return root / sym / tf


def _part_files(root: Path, sym: str, tf: str) -> List[Path]:
    d = _ydir(root, sym, tf)
    return sorted(d.glob("[0-9][0-9][0-9][0-9]*.parquet")) if d.exists() else []


def _part_key(ts: "pd.Series", tf: str) -> "pd.Series":
    return ts.dt.strftime("%Y-%m") if tf in MONTHLY_TFS else ts.dt.strftime("%Y")


def resample_bars(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Derive ``tf`` bars from 1m bars, deterministically (same rule for every symbol and run; identical in semantics to the lake's
    scripts/data_lake/resample.py): left-closed, labelled at the bar OPEN, aligned to whole UTC multiples of ``tf`` (equity sessions open
    on :30 so the first bar of a session is partial -- see ``complete``); open=first, high=max, low=min, close=last, volume and
    trade_count = sum, vwap = volume-weighted; a bar exists only if >= 1 base bar is in it (no forward fill). ``n_base`` = base bars
    inside the bar, ``complete`` = n_base == minutes in the bar, so thin/partial bars are visible instead of looking normal."""
    if df.empty:
        return df
    g = df.set_index("timestamp").sort_index()
    pv = (g["vwap"] * g["volume"]).where(g["volume"] > 0)
    g = g.assign(_pv=pv.fillna(0.0), _v=g["volume"].where(g["volume"] > 0, 0.0))
    r = g.resample(f"{DERIVED_MINUTES[tf]}min", label="left", closed="left")
    out = r.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "trade_count": "sum",
                 "_pv": "sum", "_v": "sum"})
    out["n_base"] = r["close"].count()
    out = out[out["n_base"] > 0].copy()
    out["vwap"] = (out["_pv"] / out["_v"]).where(out["_v"] > 0)
    out["complete"] = out["n_base"] == DERIVED_MINUTES[tf]
    out["n_base"] = out["n_base"].astype("int32")
    return out.drop(columns=["_pv", "_v"]).reset_index()[_BASE_COLS + ["n_base", "complete"]]


def read_bars(root: Path | str, sym: str, tf: str, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    """THE reader: ``read_bars('data/etf_history', 'SPY', '1h', start='2020-01-01')`` -> OHLCV frame sorted by UTC ``timestamp``.

    A timeframe that is not stored (5m, 15m, 30m, 1h, 4h) is DERIVED from the stored 1m base by ``resample_bars`` (adds ``n_base`` and
    ``complete`` columns); a stored one is read as is."""
    root = Path(root)
    files = _part_files(root, sym, tf)
    derive = False
    if not files and tf in DERIVED_MINUTES:
        files, derive = _part_files(root, sym, "1m"), True
    if start:
        files = [f for f in files if int(f.stem[:4]) >= int(start[:4])]
    if end:
        files = [f for f in files if int(f.stem[:4]) <= int(end[:4])]
    if not files:
        return pd.DataFrame(columns=_BASE_COLS)
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    if derive:
        df = resample_bars(df, tf)
    if start:
        df = df[df["timestamp"] >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df["timestamp"] <= pd.Timestamp(end, tz="UTC")]
    return df.reset_index(drop=True)


def _write_part(root: Path, sym: str, tf: str, key: str, df: pd.DataFrame) -> None:
    p = _ydir(root, sym, tf) / f"{key}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, p)


def _long_gaps(df: pd.DataFrame, max_days: float = 5.0) -> int:
    if len(df) < 2:
        return 0
    return int((df["timestamp"].diff().dropna() > pd.Timedelta(days=max_days)).sum())


def update_symbol(get: Getter, root: Path, sym: str, tf: str, feed: str, start: datetime, end: datetime, full: bool,
                  prior: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create / extend one series. ``prior`` is the manifest entry: it carries what the partitions NOT pulled onto this runner hold
    (rows per year, first bar), so a refresh never needs the whole store."""
    prior = prior or {}
    files = [] if full else _part_files(root, sym, tf)
    note = ""
    if not files and not full and prior.get("status") == "ok" and prior.get("last"):
        # The manifest says this series exists but no partition was pulled onto this runner. For an ACTIVE series that means the pull
        # window missed it (fall through to a full fetch). For one whose last bar is >40 days old it simply ENDED (delisted / liquidated):
        # re-pulling its whole history every day would be pure waste, so only look for resumed trading since its last bar.
        last_prior = datetime.fromisoformat(prior["last"].replace("Z", "+00:00"))
        if (end - last_prior).days > 40:
            probe_new = fetch_bars(get, sym, tf, last_prior - timedelta(days=OVERLAP_DAYS), end, feed)
            if probe_new[probe_new["timestamp"] > pd.Timestamp(last_prior)].empty:
                return {**prior, "added": 0, "note": "ended (no bars after last)", "fetched_at": _iso(datetime.now(timezone.utc))}
            note = "resumed trading -> full refetch"
    if files:
        tail = pd.read_parquet(files[-1])
        if tail.empty and len(files) > 1:
            tail = pd.read_parquet(files[-2])
        last = tail["timestamp"].max()
        since = last - timedelta(days=OVERLAP_DAYS)
        new = fetch_bars(get, sym, tf, since.to_pydatetime(), end, feed)
        old_overlap = read_bars(root, sym, tf, start=str(since.date()))
        ov = old_overlap.merge(new, on="timestamp", suffixes=("_o", "_n"))
        readj = len(ov) and ((ov["close_o"] - ov["close_n"]).abs() / ov["close_o"].abs().clip(lower=1e-9) > 1e-6).any()
        if readj:
            return _full(get, root, sym, tf, feed, start, end, "re-adjusted (split) -> full refetch")
        delta = new[new["timestamp"] > last]  # strictly after the stored last bar, so the row counts below are additive
        gap_new = _long_gaps(pd.concat([tail.tail(1), delta], ignore_index=True))
        years: Dict[str, int] = dict(prior.get("years") or {})
        for key, grp in delta.groupby(_part_key(delta["timestamp"], tf)):
            ppath = _ydir(root, sym, tf) / f"{key}.parquet"
            cur = pd.read_parquet(ppath) if ppath.exists() else pd.DataFrame(columns=_BASE_COLS)
            merged = pd.concat([cur, grp], ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
            if len(merged) < len(cur):
                raise RuntimeError(f"{sym} {tf} {key}: refusing a shrinking write")
            _write_part(root, sym, tf, key, merged)
            years[key[:4]] = years.get(key[:4], 0) + int(len(merged) - len(cur))
        if not years:  # no manifest entry for an existing store: recount from whatever is on disk (partial if only some pulled)
            for f in files:
                years[f.stem[:4]] = years.get(f.stem[:4], 0) + int(len(pd.read_parquet(f, columns=["timestamp"])))
        last_ts = max(last, delta["timestamp"].max()) if len(delta) else last
        return {"symbol": sym, "tf": tf, "status": "ok", "feed": prior.get("feed", feed), "adjustment": "split",
                "rows": int(sum(years.values())), "first": prior.get("first") or _iso(pd.read_parquet(files[0])["timestamp"].min().to_pydatetime()),
                "last": _iso(last_ts.to_pydatetime()), "years": years, "long_gaps": int(prior.get("long_gaps", 0)) + gap_new,
                "added": int(len(delta)), "note": note, "fetched_at": _iso(datetime.now(timezone.utc))}
    return _full(get, root, sym, tf, feed, start, end, note)


def _full(get: Getter, root: Path, sym: str, tf: str, feed: str, start: datetime, end: datetime, note: str) -> Dict[str, Any]:
    df = fetch_bars(get, sym, tf, start, end, feed)
    base = {"symbol": sym, "tf": tf, "feed": feed, "adjustment": "split", "fetched_at": _iso(datetime.now(timezone.utc)), "note": note}
    if df.empty:
        return {**base, "status": "no_data", "rows": 0, "first": None, "last": None, "years": {}, "long_gaps": 0, "added": 0}
    years: Dict[str, int] = {}
    keys = set()
    for key, grp in df.groupby(_part_key(df["timestamp"], tf)):
        _write_part(root, sym, tf, key, grp.reset_index(drop=True))
        years[key[:4]] = years.get(key[:4], 0) + int(len(grp))
        keys.add(f"{key}.parquet")
    for f in _part_files(root, sym, tf):  # a re-adjusted series must not keep a partition the new fetch no longer has
        if f.name not in keys:
            f.unlink()
    return {**base, "status": "ok", "rows": int(len(df)), "first": _iso(df["timestamp"].min().to_pydatetime()),
            "last": _iso(df["timestamp"].max().to_pydatetime()), "years": years, "long_gaps": _long_gaps(df), "added": int(len(df))}


# ---------------------------------------------------------------------------------------------------------- probe
def probe(get: Getter) -> List[Dict[str, Any]]:
    """MEASURE what the plan serves: per feed x timeframe, the earliest and latest SPY bar from 2016 onward."""
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


def _fresh(prior: Dict[str, Any], now: datetime, days: float = 3.0) -> bool:
    last = prior.get("last")
    return bool(last) and (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() < days * 86400


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["probe", "backfill", "refresh"], required=True)
    ap.add_argument("--out", default="data/etf_history")
    ap.add_argument("--universe", default=None, help="path to data_universe.yaml (default config/data_universe.yaml)")
    ap.add_argument("--symbols", default=None, help="comma list overriding the universe")
    ap.add_argument("--universe-snapshot", default=None,
                    help="dated lake universe snapshot CSV (universe/us_equity/<date>.csv): its symbols are APPENDED to the configured list")
    ap.add_argument("--tfs", default=None, help="comma list overriding the universe timeframes")
    ap.add_argument("--start", default=None)
    ap.add_argument("--feed", choices=["auto", "sip", "iex"], default="auto")
    ap.add_argument("--budget-min", type=float, default=0.0, help="stop cleanly after this many minutes (0 = no limit); the next run resumes")
    ap.add_argument("--skip-fetched-after", default=None,
                    help="ISO time: a series whose manifest fetched_at is >= this was already done THIS run (the workflow clears the local "
                         "store between chunks, so without this a later chunk would re-fetch it from scratch)")
    ap.add_argument("--max-new", type=int, default=0,
                    help="stop cleanly after fetching this many series (0 = no limit); the workflow loops chunks, syncing + clearing the local store "
                         "between them so the runner disk never holds the whole store. manifest run.remaining says how many are left")
    a = ap.parse_args(argv)

    get = make_getter()
    if a.mode == "probe":
        print(json.dumps(probe(get), indent=1))
        return 0

    u = du.load(a.universe)
    eq = u.get("us_equity_bars") or {}
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] if a.symbols else du.equity_symbols(u, snapshot=a.universe_snapshot)
    tfs = [t.strip() for t in a.tfs.split(",") if t.strip()] if a.tfs else list(eq.get("timeframes") or ["1h", "5m"])
    start = datetime.fromisoformat(a.start or eq.get("start") or DEFAULT_START).replace(tzinfo=timezone.utc)
    root = Path(a.out)
    feed = pick_feed(get, a.feed)
    now = datetime.now(timezone.utc)
    end = now - timedelta(minutes=30)  # free-plan SIP is 15-min delayed
    deadline = time.monotonic() + a.budget_min * 60 if a.budget_min else None
    mpath = root / "MANIFEST.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"series": {}}
    failures: List[str] = []
    done = skipped = no_data = 0
    stopped = False
    for tf in tfs:  # timeframe-major; within a timeframe the universe order is priority order (core first)
        for sym in syms:
            if (deadline and time.monotonic() > deadline) or (a.max_new and done >= a.max_new):
                stopped = True
                break
            key = f"{sym}/{tf}"
            prior = manifest["series"].get(key) or {}
            if a.skip_fetched_after and (prior.get("fetched_at") or "") >= a.skip_fetched_after:
                skipped += 1
                continue
            if a.mode == "backfill" and prior.get("status") in ("ok", "no_data") and (prior.get("status") == "no_data" or _fresh(prior, now)):
                skipped += 1
                continue
            try:
                rec = update_symbol(get, root, sym, tf, feed, start, end, full=False, prior=prior if prior.get("status") == "ok" else None)
                manifest["series"][key] = rec
                done += 1
                no_data += rec["status"] == "no_data"
                print(f"{key} [{rec['feed']}] {rec['status']} rows={rec['rows']} +{rec['added']} {rec['first']} -> {rec['last']} {rec['note']}", flush=True)
            except Exception as e:  # contained per item: one symbol never halts the run
                failures.append(f"{key}: {str(e)[:140]}")
                print(f"FAIL {key}: {str(e)[:140]}", file=sys.stderr, flush=True)
        if stopped:
            break
    if not stopped:
        try:
            ca = fetch_corporate_actions(get, syms, start, end)
            root.mkdir(parents=True, exist_ok=True)
            ca.to_csv(root / "corporate_actions.csv", index=False)
            manifest["corporate_actions"] = {"rows": int(len(ca)), "fetched_at": _iso(now)}
        except Exception as e:
            failures.append(f"corporate_actions: {str(e)[:140]}")
            manifest["corporate_actions"] = {"error": str(e)[:140]}
    manifest["failures"] = failures[:200]
    manifest["updated_at"] = _iso(datetime.now(timezone.utc))
    pending = 0
    for tf in tfs:
        for sym in syms:
            pr = manifest["series"].get(f"{sym}/{tf}") or {}
            done_now = bool(a.skip_fetched_after) and (pr.get("fetched_at") or "") >= a.skip_fetched_after
            if not (done_now or pr.get("status") == "no_data" or (pr.get("status") == "ok" and _fresh(pr, now))):
                pending += 1
    manifest["run"] = {"mode": a.mode, "symbols": len(syms), "tfs": tfs, "fetched": done, "skipped_fresh": skipped, "no_data": no_data,
                       "failed": len(failures), "stopped_early": stopped, "remaining": pending}
    root.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(json.dumps(manifest["run"]), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
