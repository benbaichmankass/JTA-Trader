#!/usr/bin/env python3
# wiring: manual-only - one-off SPOTCANDLES-AUDIT measurement run on the trainer via trainer-vm-diag (needs api.bybit.com)
"""spot-perp-candle-gap: what does feeding a perp-traded Bybit leg SPOT candles change? (SPOTCANDLES-AUDIT)

WHY. ``BybitConnector`` built ccxt with ``defaultType: spot`` and every Bybit signal builder passes a bare id
(``BTCUSDT``), so ccxt resolved the live candle read to the SPOT market, while every Bybit account trades the
LINEAR perp and every Stage-0 corpus is linear (``fetch_backtest_candles.py`` category=linear / Binance USDM;
``ml/datasets/adapters/bybit_offvm.py`` ccxt default ``swap``). PI-20261103-SPOTCANDLES-0001 asks for the
measured gap per leg. This script measures it on ONE recent window per leg:

  1. Fetches Bybit V5 public klines for the leg's (symbol, timeframe) twice, ``category=spot`` and
     ``category=linear``, over the same window (plus warm-up).
  2. PRICE-LEVEL gap per (symbol, timeframe): close basis (spot - perp) in bps, |high|/|low| differences,
     ATR(14) relative difference, and the Jaccard overlap of Donchian-20 breakout bars.
  3. DECISION-LEVEL gap per leg: runs the leg's own config-exact harness (``m20_fleet_exit_sweep.base_args``,
     the same args every Stage-0 sweep uses) on each frame with ``--emit-trades``, and compares the entry
     sets (exact-bar Jaccard), trade counts and summed net R.

Read-only research code: no venue keys, no DB, no registry; writes only ``--out``. Runs where api.bybit.com
is reachable (the trainer VM; GitHub runners are geoblocked).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(os.environ.get("SPG_REPO") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "research"))

KLINE_URL = "https://api.bybit.com/v5/market/kline"
INTERVAL = {"5m": "5", "15m": "15", "1h": "60", "2h": "120", "4h": "240"}
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "2h": 120, "4h": 240}
#: Trade window per timeframe (days), chosen so the 1-OCPU trainer finishes the fleet inside one diag job.
WINDOW_DAYS = {"5m": 45, "15m": 90, "1h": 270, "2h": 365, "4h": 365}
WARMUP_BARS = 300


def fetch(symbol: str, tf: str, category: str, start_ms: int, end_ms: int) -> List[dict]:
    import requests
    rows: Dict[int, dict] = {}
    cur = start_ms
    step = TF_MIN[tf] * 60_000
    while cur < end_ms:
        params = {"category": category, "symbol": symbol, "interval": INTERVAL[tf], "start": cur, "limit": 1000}
        data = None
        for attempt in range(5):
            try:
                r = requests.get(KLINE_URL, params=params, timeout=20)
                data = r.json()
                if data.get("retCode") == 0:
                    break
            except (requests.RequestException, ValueError) as exc:
                print(f"kline fetch retry {attempt} {symbol} {tf} {category}: {exc}", file=sys.stderr)
                data = None
            time.sleep(2 ** attempt)
        lst = ((data or {}).get("result") or {}).get("list") or []
        if not lst:
            break
        newest = cur
        for k in lst:
            ts = int(k[0])
            if start_ms <= ts < end_ms:
                rows[ts] = {"ts": ts, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                            "close": float(k[4]), "volume": float(k[5])}
            newest = max(newest, ts)
        if newest <= cur:
            break
        cur = newest + step
    return [rows[t] for t in sorted(rows)]


def write_csv(rows: List[dict], path: Path) -> None:
    import pandas as pd
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df[["timestamp", "open", "high", "low", "close", "volume"]].to_csv(path, index=False)


def _q(s, q):
    return None if len(s) == 0 else round(float(s.quantile(q)), 3)


def price_gap(spot: List[dict], perp: List[dict]) -> Dict[str, Any]:
    import pandas as pd
    a = pd.DataFrame(spot).set_index("ts")
    b = pd.DataFrame(perp).set_index("ts")
    j = a.join(b, lsuffix="_s", rsuffix="_p", how="inner")
    out: Dict[str, Any] = {"n_bars_joined": int(len(j)), "n_spot": len(a), "n_perp": len(b)}
    if not len(j):
        return out
    basis = (j["close_s"] - j["close_p"]) / j["close_p"] * 1e4
    out["close_basis_bps"] = {"median": _q(basis, 0.5), "p05": _q(basis, 0.05), "p95": _q(basis, 0.95),
                              "mean_abs": round(float(basis.abs().mean()), 3)}
    for col in ("high", "low"):
        d = ((j[f"{col}_s"] - j[f"{col}_p"]) / j[f"{col}_p"] * 1e4).abs()
        out[f"{col}_absdiff_bps"] = {"median": _q(d, 0.5), "p95": _q(d, 0.95)}

    def atr(df, sfx):
        pc = df[f"close_{sfx}"].shift(1)
        tr = pd.concat([df[f"high_{sfx}"] - df[f"low_{sfx}"], (df[f"high_{sfx}"] - pc).abs(),
                        (df[f"low_{sfx}"] - pc).abs()], axis=1).max(axis=1)
        return tr.rolling(14).mean()
    ar = ((atr(j, "s") - atr(j, "p")) / atr(j, "p") * 100).abs().dropna()
    out["atr14_absdiff_pct"] = {"median": _q(ar, 0.5), "p95": _q(ar, 0.95)}

    def brk(sfx):
        hi = j[f"high_{sfx}"].rolling(20).max().shift(1)
        lo = j[f"low_{sfx}"].rolling(20).min().shift(1)
        up = set(j.index[j[f"close_{sfx}"] > hi])
        dn = set(j.index[j[f"close_{sfx}"] < lo])
        return up, dn
    (us, ds), (up, dp) = brk("s"), brk("p")
    s_all = {("u", t) for t in us} | {("d", t) for t in ds}
    p_all = {("u", t) for t in up} | {("d", t) for t in dp}
    un = s_all | p_all
    out["donchian20_breakouts"] = {"spot": len(s_all), "perp": len(p_all), "both": len(s_all & p_all),
                                   "jaccard": round(len(s_all & p_all) / len(un), 4) if un else None}
    return out


def run_harness(leg: str, cfg: dict, data_dir: Path, out: Path, start: str, end: str) -> Dict[str, Any]:
    import m20_fleet_exit_sweep as m20
    fam = m20.classify(leg)
    if fam not in m20.FAMILY_HARNESS:
        return {"error": f"family {fam!r} has no config-exact harness args"}
    tf = str(cfg.get("timeframe") or "1h")
    sym = (cfg.get("symbols") or ["?"])[0]
    path = data_dir / f"{sym}_{tf}.csv"
    emit = out.with_suffix(".jsonl")
    summ = out.with_suffix(".json")
    args = m20.base_args(leg, cfg, fam, str(path), None, m20.LIVE_TP_CAP_PCT)
    cmd = [sys.executable, str(REPO / m20.FAMILY_HARNESS[fam]), *args, "--start", start, "--end", end,
           "--emit-trades", str(emit), "--json", str(summ)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1500, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    if p.returncode != 0:
        # some harnesses reject --strategy-name/unknown flags; report verbatim
        return {"error": (p.stderr or p.stdout)[-300:]}
    trades = []
    if emit.exists():
        for line in emit.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return {"trades": trades}


def leg_gap(spot: Dict[str, Any], perp: Dict[str, Any], tf: str) -> Dict[str, Any]:
    import pandas as pd
    if "error" in spot or "error" in perp:
        return {"error": spot.get("error") or perp.get("error")}

    def keyset(tr):
        return {(str(t.get("side") or t.get("direction") or ""), pd.Timestamp(t["entry_time"]).value)
                for t in tr if t.get("entry_time")}
    ks, kp = keyset(spot["trades"]), keyset(perp["trades"])
    un = ks | kp
    tol = TF_MIN[tf] * 60 * 10 ** 9
    near = sum(1 for (sd, t) in ks if any(sd == pd_ and abs(t - tp) <= tol for (pd_, tp) in kp))

    def net(tr):
        return round(sum(float(t.get("net_r") or 0.0) for t in tr), 3)
    return {"n_spot": len(spot["trades"]), "n_perp": len(perp["trades"]), "same_entry_bar": len(ks & kp),
            "within_1bar": near, "entry_jaccard": round(len(ks & kp) / len(un), 4) if un else None,
            "net_r_spot": net(spot["trades"]), "net_r_perp": net(perp["trades"]),
            "net_r_delta_spot_minus_perp": round(net(spot["trades"]) - net(perp["trades"]), 3)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--legs", default="", help="comma list; default = every leg on a Bybit account roster")
    ap.add_argument("--end", default=None, help="window end (ISO date, exclusive); default today UTC")
    ap.add_argument("--no-harness", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    (out / "spot").mkdir(parents=True, exist_ok=True)
    (out / "linear").mkdir(parents=True, exist_ok=True)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    from src.config.accounts_loader import load_accounts_dict
    accts = load_accounts_dict(REPO / "config/accounts.yaml")
    from src.units.strategies import load_strategy_config
    strats = dict(load_strategy_config() or {})
    roster: Dict[str, List[str]] = {}
    for acct, c in accts.items():
        if str(c.get("exchange", "")).lower() == "bybit":
            for s in c.get("strategies") or []:
                roster.setdefault(s, []).append(acct)
    legs = [x for x in a.legs.split(",") if x] or sorted(roster)
    end_dt = (datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) if a.end
              else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))
    fetched: Dict[tuple, Any] = {}
    result: Dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "end": end_dt.isoformat(),
                              "price": {}, "legs": {}}
    for leg in legs:
        cfg = strats.get(leg) or {}
        tf = str(cfg.get("timeframe") or "")
        syms = [s for s in (cfg.get("symbols") or []) if str(s).endswith("USDT")]
        rec: Dict[str, Any] = {"accounts": roster.get(leg, []), "timeframe": tf, "symbols": syms}
        if tf not in INTERVAL or not syms:
            rec["skipped"] = f"no candle-replayable (timeframe, USDT symbol): tf={tf!r}"
            result["legs"][leg] = rec
            continue
        days = WINDOW_DAYS[tf]
        start_dt = end_dt - timedelta(days=days)
        warm = start_dt - timedelta(minutes=TF_MIN[tf] * WARMUP_BARS)
        for sym in syms:
            key = (sym, tf)
            if key not in fetched:
                s = fetch(sym, tf, "spot", int(warm.timestamp() * 1000), int(end_dt.timestamp() * 1000))
                p = fetch(sym, tf, "linear", int(warm.timestamp() * 1000), int(end_dt.timestamp() * 1000))
                fetched[key] = (s, p)
                if s:
                    write_csv(s, out / "spot" / f"{sym}_{tf}.csv")
                if p:
                    write_csv(p, out / "linear" / f"{sym}_{tf}.csv")
                result["price"][f"{sym}_{tf}"] = {"window_start": warm.isoformat(), **price_gap(s, p)} \
                    if s and p else {"error": f"fetch empty spot={len(s)} perp={len(p)}"}
        rec["window"] = [start_dt.date().isoformat(), end_dt.date().isoformat()]
        if not a.no_harness and len(syms) == 1 and fetched[(syms[0], tf)][0] and fetched[(syms[0], tf)][1]:
            rs = run_harness(leg, cfg, out / "spot", out / "runs" / f"{leg}.spot",
                             start_dt.date().isoformat(), end_dt.date().isoformat())
            rp = run_harness(leg, cfg, out / "linear", out / "runs" / f"{leg}.linear",
                             start_dt.date().isoformat(), end_dt.date().isoformat())
            rec["decision_gap"] = leg_gap(rs, rp, tf)
        else:
            rec["decision_gap"] = {"skipped": "multi-symbol leg or harness disabled; price-level gap only"}
        result["legs"][leg] = rec
        (out / "gap.json").write_text(json.dumps(result, indent=1, default=str))
        print(f"{leg}: {json.dumps(rec.get('decision_gap'))}", flush=True)
    (out / "gap.json").write_text(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
