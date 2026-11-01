#!/usr/bin/env python3
# wiring: .github/workflows/options-snapshot-capture.yml (runner holding the Alpaca secrets; store synced to the trainer)
"""Daily end-of-day option-chain snapshot (quotes + IV + greeks) -> the canonical store. WHAT is captured (underlyings, expiries,
moneyness) is config/data_universe.yaml `options:`.

WHY (operator, 2026-11-01): there is no keyless historical option/IV data, so we ACCRUE our own. Every trading day
this records the near-the-money slice of the first expiries for the liquid underlyings; in a year that is a
point-in-time IV history nobody else can sell us back. Row OPTIONS-IV-HISTORY-GAP.

STORE (``--out``, trainer ``data/options_history/``)::

    <source>/<UNDERLYING>/<YYYY-MM-DD>.parquet   source = alpaca (keyed) | cboe (keyless delayed-quotes CDN, adds OI + volume)
    MANIFEST.json                       per underlying: last capture, rows, iv coverage

Row fields: asof_date, captured_at, underlying, spot, symbol (OCC), expiry, cp, strike, bid, ask, bid_size, ask_size,
quote_ts, last, last_ts, iv, delta, gamma, theta, vega, rho, feed. Absent = NaN (never 0): the free ``indicative``
feed omits greeks/IV on illiquid contracts and says so by omission.

SLICE: contracts with |strike/spot - 1| <= ``--moneyness`` (default 6%) in the first ``--expiries`` (default 3)
distinct expiries on/after today. Idempotent per day (rewrites that day's file). Market data only; keys from env only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_universe as du  # noqa: E402

DATA_URL = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets").rstrip("/")
_OCC = re.compile(r"^([A-Z0-9]{1,8}?)(\d{6})([CP])(\d{8})$")  # CBOE prefixes some roots ("B1SPY...")
COLS = ["asof_date", "captured_at", "underlying", "spot", "symbol", "expiry", "cp", "strike", "bid", "ask", "bid_size",
        "ask_size", "quote_ts", "last", "last_ts", "iv", "delta", "gamma", "theta", "vega", "rho", "open_interest", "volume", "feed"]
Getter = Callable[[str, Dict[str, Any]], Any]


def make_cboe_getter() -> Getter:
    """Keyless: the CBOE delayed-quotes CDN. No credential is read or sent."""
    import requests

    def get(path: str, params: Dict[str, Any]) -> Any:
        for attempt in range(6):
            r = requests.get("https://cdn.cboe.com" + path, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(60, 2 ** attempt))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code} {path}")
            return r.json()
        raise RuntimeError(f"HTTP retries exhausted {path}")

    return get


def make_getter() -> Getter:
    import requests

    k, s = os.environ.get("ALPACA_API_KEY_ID_LIVE"), os.environ.get("ALPACA_API_SECRET_KEY_LIVE")
    if not (k and s):
        raise SystemExit("no Alpaca keys in the environment (ALPACA_API_KEY_ID_LIVE / ALPACA_API_SECRET_KEY_LIVE)")
    sess = requests.Session()
    sess.headers.update({"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})

    def get(path: str, params: Dict[str, Any]) -> Any:
        for attempt in range(8):
            r = sess.get(DATA_URL + path, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(60, 2 ** attempt))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code} {path}: {r.text[:200]}")
            return r.json()
        raise RuntimeError(f"HTTP retries exhausted {path}")

    return get


def parse_occ(sym: str) -> Optional[Dict[str, Any]]:
    m = _OCC.match(sym)
    if not m:
        return None
    root, ymd, cp, k = m.groups()
    return {"root": root, "expiry": datetime.strptime(ymd, "%y%m%d").date(), "cp": cp, "strike": int(k) / 1000.0}


def spot_price(get: Getter, und: str) -> Optional[float]:
    j = get(f"/v2/stocks/{und}/trades/latest", {"feed": "iex"})
    p = (j.get("trade") or {}).get("p")
    return float(p) if p else None


def fetch_chain(get: Getter, und: str, spot: float, today: date, moneyness: float, feed: str) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "feed": feed, "limit": 1000,
        "strike_price_gte": round(spot * (1 - moneyness), 2), "strike_price_lte": round(spot * (1 + moneyness), 2),
        "expiration_date_gte": today.isoformat(), "expiration_date_lte": (today + timedelta(days=45)).isoformat(),
    }
    snaps: Dict[str, Any] = {}
    while True:
        j = get(f"/v1beta1/options/snapshots/{und}", params)
        snaps.update(j.get("snapshots") or {})
        tok = j.get("next_page_token")
        if not tok:
            break
        params["page_token"] = tok
    return snaps


def cboe_frame(und: str, j: Dict[str, Any], today: date, n_expiries: int, moneyness: float, now: datetime) -> pd.DataFrame:
    """Keyless CBOE delayed-quotes chain (cdn.cboe.com) -> the same row shape; adds open_interest + volume."""
    d = j.get("data") or {}
    spot = float(d.get("current_price") or 0)
    if not spot:
        raise RuntimeError(f"{und}: cboe chain has no current_price")
    qts = j.get("timestamp")
    recs = []
    for o in d.get("options") or []:
        p = parse_occ(o.get("option", ""))
        if not p or und not in p["root"] or p["expiry"] < today or abs(p["strike"] / spot - 1) > moneyness:
            continue
        recs.append((p, o))
    expiries = sorted({p["expiry"] for p, _ in recs})[:n_expiries]
    rows = []
    nz = lambda v: v if v else None  # CBOE reports 0.0 for "no quote / no IV": that is absent, never a real zero
    for p, o in recs:
        if p["expiry"] not in expiries:
            continue
        rows.append({"asof_date": today.isoformat(), "captured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "underlying": und,
                     "spot": spot, "symbol": o["option"], "expiry": p["expiry"].isoformat(), "cp": p["cp"], "strike": p["strike"],
                     "bid": o.get("bid"), "ask": o.get("ask"), "bid_size": o.get("bid_size"), "ask_size": o.get("ask_size"),
                     "quote_ts": qts, "last": nz(o.get("last_trade_price")), "last_ts": o.get("last_trade_time"),
                     "iv": nz(o.get("iv")), "delta": o.get("delta"), "gamma": o.get("gamma"), "theta": o.get("theta"),
                     "vega": o.get("vega"), "rho": o.get("rho"), "open_interest": o.get("open_interest"),
                     "volume": o.get("volume"), "feed": "cboe_delayed"})
    return pd.DataFrame(rows, columns=COLS).sort_values(["expiry", "cp", "strike"]).reset_index(drop=True)


def to_frame(und: str, spot: float, snaps: Dict[str, Any], today: date, n_expiries: int, feed: str, now: datetime) -> pd.DataFrame:
    parsed = {s: parse_occ(s) for s in snaps}
    expiries = sorted({p["expiry"] for p in parsed.values() if p and p["root"] == und and p["expiry"] >= today})[:n_expiries]
    rows: List[Dict[str, Any]] = []
    for sym, snap in snaps.items():
        p = parsed[sym]
        if not p or p["root"] != und or p["expiry"] not in expiries:
            continue
        q, t, g = snap.get("latestQuote") or {}, snap.get("latestTrade") or {}, snap.get("greeks") or {}
        rows.append({
            "asof_date": today.isoformat(), "captured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "underlying": und, "spot": spot,
            "symbol": sym, "expiry": p["expiry"].isoformat(), "cp": p["cp"], "strike": p["strike"],
            "bid": q.get("bp"), "ask": q.get("ap"), "bid_size": q.get("bs"), "ask_size": q.get("as"), "quote_ts": q.get("t"),
            "last": t.get("p"), "last_ts": t.get("t"), "iv": snap.get("impliedVolatility"),
            "delta": g.get("delta"), "gamma": g.get("gamma"), "theta": g.get("theta"), "vega": g.get("vega"), "rho": g.get("rho"),
            "open_interest": None, "volume": None, "feed": feed})
    df = pd.DataFrame(rows, columns=COLS)
    return df.sort_values(["expiry", "cp", "strike"]).reset_index(drop=True)


def capture(get: Getter, root: Path, und: str, today: date, n_expiries: int, moneyness: float, feed: str,
            source: str = "alpaca") -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    if source == "cboe":
        df = cboe_frame(und, get(f"/api/global/delayed_quotes/options/{und}.json", {}), today, n_expiries, moneyness, now)
        feed = "cboe_delayed"
    else:
        spot = spot_price(get, und)
        if not spot:
            raise RuntimeError(f"{und}: no spot price")
        df = to_frame(und, spot, fetch_chain(get, und, spot, today, moneyness, feed), today, n_expiries, feed, now)
    if df.empty:
        raise RuntimeError(f"{und}: empty chain slice")
    p = root / und / f"{today.isoformat()}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, p)
    return {"underlying": und, "asof_date": today.isoformat(), "rows": int(len(df)), "expiries": int(df["expiry"].nunique()),
            "iv_coverage": round(float(df["iv"].notna().mean()), 3), "quote_coverage": round(float(df["bid"].notna().mean()), 3),
            "latest_quote_ts": str(df["quote_ts"].dropna().max()) if df["quote_ts"].notna().any() else None, "feed": feed}


def verify(root: Path, unds: List[str], stale_days: float, now: datetime) -> int:
    bad: List[str] = []
    print("| underlying | days | first | last | last_rows | iv_cov | age_d | status |\n|---|---|---|---|---|---|---|---|")
    for und in unds:
        files = sorted((root / und).glob("*.parquet")) if (root / und).exists() else []
        if not files:
            bad.append(und)
            print(f"| {und} | 0 | — | — | — | — | — | MISSING |")
            continue
        last = pd.read_parquet(files[-1])
        age = (now.date() - date.fromisoformat(files[-1].stem)).days
        stale = age > stale_days
        if stale:
            bad.append(und)
        print(f"| {und} | {len(files)} | {files[0].stem} | {files[-1].stem} | {len(last)} | {last['iv'].notna().mean():.2f} | {age} | "
              f"{'STALE' if stale else 'ok'} |")
    print(f"underlyings={len(unds)} stale_or_missing={len(bad)} {bad}")
    return 1 if bad else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["capture", "verify", "probe"], required=True)
    ap.add_argument("--out", default="data/options_history")
    ap.add_argument("--universe", default=None, help="path to data_universe.yaml (default config/data_universe.yaml)")
    ap.add_argument("--underlyings", default=None, help="comma list overriding the universe")
    ap.add_argument("--expiries", type=int, default=None)
    ap.add_argument("--moneyness", type=float, default=None)
    ap.add_argument("--source", choices=["alpaca", "cboe"], default="alpaca",
                    help="alpaca = keyed (indicative/opra feed); cboe = keyless delayed-quotes CDN (adds open_interest, volume)")
    ap.add_argument("--feed", choices=["indicative", "opra"], default="indicative")
    ap.add_argument("--stale-days", type=float, default=4.0)
    a = ap.parse_args(argv)
    uni = du.load(a.universe)
    opt = uni.get("options") or {}
    unds = [u.strip().upper() for u in a.underlyings.split(",") if u.strip()] if a.underlyings else du.options_underlyings(uni)
    a.expiries = a.expiries if a.expiries is not None else int(opt.get("expiries", 3))
    a.moneyness = a.moneyness if a.moneyness is not None else float(opt.get("moneyness", 0.06))
    root = Path(a.out) / a.source
    now = datetime.now(timezone.utc)
    if a.mode == "verify":
        return verify(root, unds, a.stale_days, now)
    get = make_cboe_getter() if a.source == "cboe" else make_getter()
    if a.mode == "probe":  # what does the plan serve? one SPY slice per feed, no store write
        for feed in ("opra", "indicative"):
            try:
                spot = spot_price(get, "SPY") or 0
                sn = fetch_chain(get, "SPY", spot, now.date(), 0.02, feed)
                iv = sum(1 for v in sn.values() if v.get("impliedVolatility") is not None)
                print(json.dumps({"feed": feed, "status": "ok", "contracts": len(sn), "with_iv": iv}))
            except RuntimeError as e:
                print(json.dumps({"feed": feed, "status": "refused", "error": str(e)[:160]}))
        # Historical depth of Alpaca's option BARS/TRADES (no IV/greeks in history): ask for an expired SPY contract's
        # daily bars from 2023 and report the earliest returned. Contracts are listed from the Trading API contracts
        # endpoint is NOT used here; these OCC symbols (SPY 2024-03-15 / 2025-03-21 / 2026-03-20 monthly, ATM-ish) are
        # probes, a 'no bars' answer for one of them is a finding about that contract, not about the whole plan.
        for sym in ("SPY240315C00510000", "SPY250321C00570000", "SPY260320C00660000"):
            try:
                j = get("/v1beta1/options/bars", {"symbols": sym, "timeframe": "1Day", "start": "2023-01-01T00:00:00Z",
                                                  "end": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 3, "sort": "asc"})
                b = (j.get("bars") or {}).get(sym) or []
                print(json.dumps({"hist_option_bars": sym, "status": "ok", "earliest": b[0]["t"] if b else None, "n_first_page": len(b)}))
            except RuntimeError as e:
                print(json.dumps({"hist_option_bars": sym, "status": "refused", "error": str(e)[:160]}))
        return 0
    manifest_p = root / "MANIFEST.json"
    manifest = json.loads(manifest_p.read_text()) if manifest_p.exists() else {"underlyings": {}}
    failures: List[str] = []
    for und in unds:
        try:
            rec = capture(get, root, und, now.date(), a.expiries, a.moneyness, a.feed, a.source)
            manifest["underlyings"][und] = rec
            print(json.dumps(rec), flush=True)
        except Exception as e:  # contained per item
            failures.append(f"{und}: {str(e)[:160]}")
            print(f"FAIL {und}: {str(e)[:160]}", file=sys.stderr, flush=True)
    manifest["failures"], manifest["updated_at"] = failures, now.strftime("%Y-%m-%dT%H:%M:%SZ")
    root.mkdir(parents=True, exist_ok=True)
    manifest_p.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
