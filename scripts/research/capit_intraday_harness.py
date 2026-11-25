#!/usr/bin/env python3
# wiring: research/queue/RQ-20261125-1e07-01..04.yaml (once, research-script-run.yml); row INDEX-CAPIT-1X-LEG (shorter-timeframe spec, 2026-11-25 06:35Z)
"""Capitulation trigger on SHORTER timeframes (1h / 4h): the INDEX-CAPIT-1X-LEG daily spec kept in BARS of the new timeframe, never re-tuned.

Tier 1 research tooling. Reads market-data bars (Alpaca read-only historical stock bars for the ETFs; the keyless Binance Vision USDT-M futures
archive for the crypto majors) and writes only ``--out``. No order path, no config, no served model.

THE SPEC (frozen on row INDEX-CAPIT-1X-LEG before any run; the daily harness's own functions are reused so the trigger is byte-identical):
  flush   close <= mean(close, 5 bars) - 1.5 x ATR14 AND low < min(low of the prior 20 bars)  (index_signal_etf_harness.signals_capitulation_wide)
  trigger the first up-close within 5 bars of the flush; enter at the NEXT bar's open; stop = the lowest low from the flush bar to the signal bar
  TP      K* calibrated on the first 60% of each symbol's no-TP trades (index_signal_etf_harness.calibrate_tp; TP doctrine, never tp_r 50)
  hold    10 bars of the timeframe; one position per symbol at a time; MIN_RISK_FRAC 0.25%
BARS
  ETFs    Alpaca SIP 30-minute bars (split-adjusted), REGULAR SESSION only (09:30-16:00 America/New_York), resampled into session-anchored buckets:
          1h = 09:30, 10:30, ..., 15:30 (the last bucket is 30 minutes); 4h = 09:30-13:30 and 13:30-16:00. A bucket never spans the overnight gap.
  crypto  Binance Vision USDT-M monthly klines at the native 1h / 4h timeframe.
COSTS (net of the full cost stack, src/runtime/execution_costs.roundtrip_cost_r on every trade)
  ETFs    fee = resolve_fee_bps_roundtrip (0.0, commission-free) + slippage 5 bps PER SIDE (10 bps round trip, the daily harness's basis and
          stricter than the canonical 5 bps round trip), no funding.
  crypto  fee = resolve_fee_bps_roundtrip (11 bps round trip, bybit:linear measured) + slippage resolve_cost_policy (3 bps round trip) + funding
          resolve_cost_policy (1 bp per 8h window crossed).
  2x      the slippage term doubled (fee and funding unchanged).
GRADE (POOLED per unit; RULE text in RULES)
  PASS iff pooled n >= 25 AND pooled net_r > 0 AND pooled net_r > 0 at 2x slippage AND the pooled actual net_r beats >= 95% of 200 re-timed draws
  (each signal moved 40-400 BARS either way, same stop geometry, K* and cost) AND a strict majority of symbols net_r > 0 AND the chronologically
  latest 40% of the pooled trades net_r > 0; INDETERMINATE if pooled n < 25; FAIL otherwise.

  python3 scripts/research/capit_intraday_harness.py --unit RQ-20261125-1e07-01 --out DIR [--cache-dir DIR]
  python3 scripts/research/capit_intraday_harness.py --self-test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
import math
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import index_signal_etf_harness as H

from src.runtime.execution_costs import (
    resolve_cost_policy,
    resolve_fee_bps_roundtrip,
    roundtrip_cost_r,
)

FAMILY = "capitulation_wide"
HOLD_CAP_BARS = 10
ETF_SLIP_BPS_RT = 10.0                       # 5 bps per side, the daily harness's basis
SESSION_OPEN, SESSION_CLOSE = (9, 30), (16, 0)
TZ_NY = "America/New_York"
LATEST_FRAC = 0.40
TIMING_DRAWS = 200
TIMING_SHIFT = (40, 400)                     # bars, either direction
TIMING_SEED = 11
TIMING_GATE = 0.05                           # share_of_draws_ge_actual <= 0.05
ETF18 = [t for t, _, _ in H.PAIRS["capitulation_1x_fresh"]] + [t for t, _, _ in H.PAIRS["capitulation_1x_confirm"]]
CRYPTO_MAJORS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"]
WINDOW = {"etf": ("2016-01-01", "2026-10-22"), "crypto": ("2020-01-01", "2026-10-22")}
_BV = "https://data.binance.vision/data/futures/um/monthly/klines"

UNITS = {
    "RQ-20261125-1e07-01": {"kind": "etf", "tf": "1h", "symbols": ETF18},
    "RQ-20261125-1e07-02": {"kind": "etf", "tf": "4h", "symbols": ETF18},
    "RQ-20261125-1e07-03": {"kind": "crypto", "tf": "1h", "symbols": CRYPTO_MAJORS},
    "RQ-20261125-1e07-04": {"kind": "crypto", "tf": "4h", "symbols": CRYPTO_MAJORS},
}


def rule_text(spec: dict) -> str:
    n = len(spec["symbols"])
    maj = n // 2 + 1
    pop = "the 18 INDEX-CAPIT-1X-LEG ETFs, US regular session" if spec["kind"] == "etf" else "6 crypto majors (Binance USDT-M)"
    return (f"UNFILTERED capitulation trigger (daily spec kept in {spec['tf']} BARS, not re-tuned) on {pop}, graded POOLED: PASS IFF pooled n>=25 "
            f"AND pooled net_r>0 AND pooled net_r>0 at 2x slippage AND the pooled actual net_r beats >= 95% of 200 re-timed draws "
            f"(share_of_draws_ge_actual <= 0.05) AND >= {maj} of {n} symbols net_r>0 (strict majority) AND the chronologically latest 40% of "
            f"pooled trades net_r>0; INDETERMINATE if pooled n<25; FAIL otherwise")


# ------------------------------------------------------------------------------------------------------------ bars ----------
def session_buckets(bars30: pd.DataFrame, tf: str) -> pd.DataFrame:
    """30-minute bars (tz-aware UTC index, columns open/high/low/close) -> regular-session, session-anchored 1h or 4h OHLC buckets."""
    if bars30.empty:
        return bars30
    ny = bars30.tz_convert(TZ_NY)
    mins = ny.index.hour * 60 + ny.index.minute
    o, c = SESSION_OPEN[0] * 60 + SESSION_OPEN[1], SESSION_CLOSE[0] * 60 + SESSION_CLOSE[1]
    ny = ny[(mins >= o) & (mins < c)]
    mins = ny.index.hour * 60 + ny.index.minute
    width = {"1h": 60, "4h": 240}[tf]
    slot = (mins - o) // width
    day = ny.index.normalize()
    start = day + pd.to_timedelta(o + slot * width, unit="m")
    g = ny.groupby(start)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
    out.index = pd.DatetimeIndex(out.index).tz_convert("UTC")
    return out.sort_index().dropna()


def fetch_etf(symbols: list[str], tf: str, start: str, end: str, cache: Path | None, client=None) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    todo = []
    for s in symbols:
        p = cache / f"alpaca30_{s}_{start}_{end}.pkl" if cache else None
        if p is not None and p.exists():
            out[s] = session_buckets(pd.read_pickle(p), tf)
        else:
            todo.append(s)
    if todo:
        if client is None:
            import alpaca_readonly
            client = alpaca_readonly.AlpacaReadOnly.from_env()
        for s in todo:                                   # one symbol per call: the page token walks one series at a time
            raw = client.bars([s], "30Min", f"{start}T00:00:00Z", f"{end}T23:59:59Z").get(s, [])
            df = pd.DataFrame([{"t": b["t"], "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"]} for b in raw])
            if df.empty:
                out[s] = df
                continue
            df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("t"), utc=True))
            df = df[~df.index.duplicated(keep="first")].sort_index().astype(float)
            if cache:
                cache.mkdir(parents=True, exist_ok=True)
                df.to_pickle(cache / f"alpaca30_{s}_{start}_{end}.pkl")
            out[s] = session_buckets(df, tf)
    return out


def _bv_month(sym: str, tf: str, month: str) -> pd.DataFrame | None:
    import requests
    url = f"{_BV}/{sym}/{tf}/{sym}-{tf}-{month}.zip"
    last = None
    for wait in (0, 2, 4, 8):
        time.sleep(wait)
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            raw = zf.read(zf.namelist()[0]).decode()
            df = pd.read_csv(io.StringIO(raw), header=0 if raw.split("\n", 1)[0].startswith("open_time") else None).iloc[:, :5]
            df.columns = ["open_time", "open", "high", "low", "close"]
            return df
        except Exception as e:  # noqa: BLE001  # allow-silent: retried with backoff; the final failure raises below
            last = e
            continue
    raise RuntimeError(f"Binance Vision fetch failed {url}: {last}")


def fetch_crypto(symbols: list[str], tf: str, start: str, end: str, cache: Path | None) -> dict[str, pd.DataFrame]:
    def one(sym: str) -> tuple[str, pd.DataFrame]:
        p = cache / f"bv_{sym}_{tf}_{start}_{end}.pkl" if cache else None
        if p is not None and p.exists():
            return sym, pd.read_pickle(p)
        months = [m.strftime("%Y-%m") for m in pd.period_range(start[:7], end[:7], freq="M")]
        frames = [d for d in (_bv_month(sym, tf, m) for m in months) if d is not None]
        if not frames:
            return sym, pd.DataFrame(columns=["open", "high", "low", "close"])
        df = pd.concat(frames, ignore_index=True)
        df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
        df = df.dropna().drop_duplicates("open_time").sort_values("open_time")
        df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("open_time").astype("int64"), unit="ms", utc=True))
        df = df.astype(float)
        df = df[(df.index >= pd.Timestamp(start, tz="UTC")) & (df.index < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))]
        if p is not None:
            cache.mkdir(parents=True, exist_ok=True)
            df.to_pickle(p)
        return sym, df

    with cf.ThreadPoolExecutor(6) as ex:
        return dict(ex.map(one, symbols))


def to_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The daily harness's frame layout (index columns i_* = execution columns e_*: a 1x instrument trades its own chart)."""
    f = pd.DataFrame({"i_o": df["open"], "i_h": df["high"], "i_l": df["low"], "i_c": df["close"]}, index=df.index)
    for a, b in (("i_o", "e_o"), ("i_h", "e_h"), ("i_l", "e_l"), ("i_c", "e_c")):
        f[b] = f[a]
    return f.dropna()


# ------------------------------------------------------------------------------------------------------ simulate ------------
def cost_spec(kind: str, symbol: str) -> dict[str, float]:
    if kind == "etf":
        return {"fee": resolve_fee_bps_roundtrip(symbol), "slip": ETF_SLIP_BPS_RT, "fund": 0.0}
    slip, fund = resolve_cost_policy(symbol)
    return {"fee": resolve_fee_bps_roundtrip(symbol), "slip": float(slip), "fund": float(fund)}


def simulate(frame: pd.DataFrame, sigs: list[dict[str, Any]], hold_cap: int, cost: dict[str, float], slip_mult: float = 1.0,
             tp_k: float | None = None) -> dict[str, Any]:
    """index_signal_etf_harness.simulate's bar logic (long, 1x) with timestamps kept and the canonical cost stack on every trade."""
    ix = frame.index
    eo, eh, el, ec = (frame[c].to_numpy(float) for c in ("e_o", "e_h", "e_l", "e_c"))
    n = len(frame)
    trades: list[dict[str, Any]] = []
    skips: dict[str, int] = {}
    last_exit = -1
    for s in sigs:
        i, j = s["i"], s["i"] + 1
        if j >= n:
            continue
        if s.get("stop_idx") is None:
            skips["no_stop"] = skips.get("no_stop", 0) + 1
            continue
        if j <= last_exit:
            skips["in_position"] = skips.get("in_position", 0) + 1
            continue
        entry, stop = eo[j], s["stop_idx"]
        if not stop < entry:
            skips["stop_wrong_side_at_entry"] = skips.get("stop_wrong_side_at_entry", 0) + 1
            continue
        risk = entry - stop
        if not (risk > 0 and risk / entry >= H.MIN_RISK_FRAC and stop > 0):
            skips["risk_degenerate"] = skips.get("risk_degenerate", 0) + 1
            continue
        tp = entry + tp_k * risk if tp_k else None
        k_exit = min(j + hold_cap - 1, n - 1)
        exit_px, why, mfe = ec[k_exit], "timeout", 0.0
        for k in range(j, min(j + hold_cap, n)):
            o = eo[k]
            if k > j and o <= stop:
                exit_px, why, k_exit = o, "stop", k
                break
            if k > j and tp is not None and o >= tp:
                exit_px, why, k_exit = o, "take_profit", k
                break
            if el[k] <= stop:
                exit_px, why, k_exit = stop, "stop", k
                break
            mfe = max(mfe, (eh[k] - entry) / risk)
            if tp is not None and eh[k] >= tp:
                exit_px, why, k_exit = tp, "take_profit", k
                break
        t_in = ix[j]
        bar_end = ix[k_exit + 1] if k_exit + 1 < n else ix[k_exit] + (ix[k_exit] - ix[k_exit - 1] if k_exit else pd.Timedelta(hours=1))
        c = roundtrip_cost_r(entry=entry, exit_price=float(exit_px), risk=risk, entry_time=t_in.to_pydatetime(),
                             exit_time=bar_end.to_pydatetime(), fee_bps_roundtrip=cost["fee"], slippage_bps_roundtrip=cost["slip"] * slip_mult,
                             funding_bps_per_window=cost["fund"])
        gross = (float(exit_px) - entry) / risk
        trades.append({"entry_date": t_in.isoformat(), "exit_date": ix[k_exit].isoformat(), "signal_date": ix[i].isoformat(),
                       "entry": round(entry, 6), "risk": round(risk, 6), "exit": round(float(exit_px), 6), "why": why, "bars": k_exit - j + 1,
                       "gross_r": round(gross, 4), "cost_r": round(c["total_cost_r"], 4), "fee_r": round(c["fee_r"], 4),
                       "slippage_r": round(c["slippage_r"], 4), "funding_r": round(c["funding_r"], 4),
                       "net_r": round(gross - c["total_cost_r"], 4), "mfe_r": round(mfe, 4)})
        last_exit = k_exit
    return {"trades": trades, "skips": skips}


def run_symbol(frame: pd.DataFrame, cost: dict[str, float]) -> dict[str, Any]:
    sigs = H.index_signals(frame, FAMILY)
    base = simulate(frame, sigs, HOLD_CAP_BARS, cost)
    cal = H.calibrate_tp(base["trades"])
    k = cal["k_star"]
    g1 = simulate(frame, sigs, HOLD_CAP_BARS, cost, 1.0, k)
    g2 = simulate(frame, sigs, HOLD_CAP_BARS, cost, 2.0, k)
    st = H.stats(g1["trades"], H.fold_edges(frame)) if len(frame) else H.stats([])
    tr = g1["trades"]
    return {"n_signals": len(sigs), "skips": g1["skips"], "tp_calibration": cal, **st, "net_r_2x_slip": H.stats(g2["trades"])["net_r"],
            "mean_bars_held": round(float(np.mean([t["bars"] for t in tr])), 2) if tr else None,
            "mean_cost_r": round(float(np.mean([t["cost_r"] for t in tr])), 4) if tr else None,
            "mean_funding_r": round(float(np.mean([t["funding_r"] for t in tr])), 4) if tr else None,
            "data_start": str(frame.index[0]) if len(frame) else None, "data_end": str(frame.index[-1]) if len(frame) else None,
            "n_bars": len(frame), "trades": tr}


def timing_draws(frame: pd.DataFrame, cost: dict[str, float], k_star: float | None, ndraw: int = TIMING_DRAWS, seed: int = TIMING_SEED) -> np.ndarray:
    """H.timing_control in BARS of this timeframe with this cost stack: each real signal keeps its stop/close ratio and moves 40-400 bars."""
    sigs = [s for s in H.index_signals(frame, FAMILY) if s.get("stop_idx") is not None]
    ic = frame["i_c"].to_numpy(float)
    n = len(frame)
    rng = np.random.default_rng(seed)
    out = np.zeros(ndraw)
    for d in range(ndraw):
        ss = []
        for s in sigs:
            off = int(rng.integers(*TIMING_SHIFT)) * (1 if rng.random() < 0.5 else -1)
            ni = s["i"] + off
            if 60 <= ni < n - 1:
                ss.append({"i": ni, "stop_idx": ic[ni] * s["stop_idx"] / ic[s["i"]]})
        ss.sort(key=lambda x: x["i"])
        out[d] = sum(t["net_r"] for t in simulate(frame, ss, HOLD_CAP_BARS, cost, 1.0, k_star)["trades"])
    return out


def grade_pooled(per: dict[str, dict[str, Any]], draws: np.ndarray) -> dict[str, Any]:
    trades = sorted((t for v in per.values() for t in v["trades"]), key=lambda t: t["entry_date"])
    npool = len(trades)
    net = float(sum(t["net_r"] for t in trades))
    net2 = float(sum(v["net_r_2x_slip"] for v in per.values()))
    n_late = math.ceil(LATEST_FRAC * npool)
    late = trades[npool - n_late:] if n_late else []
    late_net = float(sum(t["net_r"] for t in late))
    nsym = len(per)
    maj = nsym // 2 + 1
    npos = sum(1 for v in per.values() if v["net_r"] > 0)
    share = float((draws >= net).mean()) if len(draws) else 1.0
    chk = {"pooled_n_ge_floor": npool >= H.N_FLOOR, "pooled_net_gt_0": net > 0, "pooled_net_gt_0_at_2x_slip": net2 > 0,
           "beats_timing_control_95": share <= TIMING_GATE, f"symbols_positive_ge_{maj}_of_{nsym}": npos >= maj, "latest_40pct_net_gt_0": late_net > 0}
    v = "indeterminate" if npool < H.N_FLOOR else ("pass" if all(chk.values()) else "fail")
    return {"n": npool, "net_r": round(net, 4), "net_r_2x_slip": round(net2, 4), "symbols_positive": npos, "latest_40pct": {"n": n_late,
            "net_r": round(late_net, 4), "from": late[0]["entry_date"] if late else None},
            "timing_control": {"draws": len(draws), "shift_bars": f"{TIMING_SHIFT[0]}..{TIMING_SHIFT[1]} either direction",
                               "mean_net_r": round(float(draws.mean()), 3) if len(draws) else None,
                               "p95_net_r": round(float(np.percentile(draws, 95)), 3) if len(draws) else None, "share_of_draws_ge_actual": round(share, 3)},
            "checks": chk, "verdict": v}


def run_unit(unit: str, out: Path, cache: Path | None, frames: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    spec = UNITS[unit]
    start, end = WINDOW[spec["kind"]]
    if frames is None:
        raw = (fetch_etf if spec["kind"] == "etf" else fetch_crypto)(spec["symbols"], spec["tf"], start, end, cache)
        frames = {s: to_frame(d) for s, d in raw.items() if len(d)}
    per: dict[str, dict[str, Any]] = {}
    draws = np.zeros(TIMING_DRAWS)
    missing = [s for s in spec["symbols"] if s not in frames or len(frames[s]) < 100]
    for s in spec["symbols"]:
        f = frames.get(s)
        if f is None or len(f) < 100:
            continue
        cost = cost_spec(spec["kind"], s)
        per[s] = run_symbol(f, cost)
        per[s]["cost_bps"] = cost
        draws += timing_draws(f, cost, per[s]["tp_calibration"].get("k_star"))
    pooled = grade_pooled(per, draws) if per else {"n": 0, "verdict": "indeterminate", "checks": {}}
    # symbols with no bars count as NOT positive in the majority clause (the denominator is the registered population)
    nsym = len(spec["symbols"])
    if per:
        maj = nsym // 2 + 1
        key = next(k for k in pooled["checks"] if k.startswith("symbols_positive"))
        pooled["checks"].pop(key)
        pooled["checks"][f"symbols_positive_ge_{maj}_of_{nsym}"] = pooled["symbols_positive"] >= maj
        if pooled["verdict"] != "indeterminate":
            pooled["verdict"] = "pass" if all(pooled["checks"].values()) else "fail"
    out.mkdir(parents=True, exist_ok=True)
    for s, v in per.items():
        (out / f"trades_{H.artifact_safe(s)}.jsonl").write_text("\n".join(json.dumps(t) for t in v["trades"]) + "\n")
    slim = {s: {k: v for k, v in r.items() if k != "trades"} for s, r in per.items()}
    rec = {"schema_version": 1, "research_unit": unit, "read_state": "measured" if per else "no_data", "verdict": pooled["verdict"],
           "n": pooled["n"],
           "note": f"capitulation {spec['tf']} {spec['kind']}: {pooled['verdict'].upper()} (pooled n {pooled['n']}); symbols without bars: {missing or 'none'}",
           "decision_rule": {"id": f"RULE-{unit}", "rule": rule_text(spec)},
           "population": (f"{len(per)} of {nsym} symbols with bars ({spec['kind']}, {spec['tf']}, {start}..{end}); "
                          + ("Alpaca SIP 30Min regular-session bars resampled session-anchored" if spec["kind"] == "etf"
                             else "Binance Vision USDT-M klines") + "; trades net of the full cost stack (fee + slippage + funding)"),
           "measurement": {"family": FAMILY, "timeframe": spec["tf"], "kind": spec["kind"], "window": [start, end], "hold_cap_bars": HOLD_CAP_BARS,
                           "symbols": slim, "symbols_missing": missing, "pooled": pooled, "provenance": "ESTIMATED"},
           "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    (out / "measurement.json").write_text(json.dumps(rec["measurement"], indent=1, default=str) + "\n")
    return rec


# ------------------------------------------------------------------------------------------------------ self-test -----------
def _synthetic_30m(days: int = 400, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2020-01-02", periods=days):
        for m in range(-60, 450, 30):                      # 08:30..16:00 ET incl. pre/post bars that must be dropped
            idx.append(pd.Timestamp(d.year, d.month, d.day, 9, 30, tz=TZ_NY) + pd.Timedelta(minutes=m))
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(idx))))
    o = np.r_[c[0], c[:-1]]
    h, lo = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c}, index=pd.DatetimeIndex(idx).tz_convert("UTC"))


def self_test() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("  ok   " if cond else "  FAIL ") + name)
    raw = _synthetic_30m()
    b1, b4 = session_buckets(raw, "1h"), session_buckets(raw, "4h")
    ny1 = b1.index.tz_convert(TZ_NY)
    check("1h buckets start 09:30..15:30 ET only", set(zip(ny1.hour, ny1.minute)) == {(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)})
    ny4 = b4.index.tz_convert(TZ_NY)
    check("4h buckets are 09:30 and 13:30 ET", set(zip(ny4.hour, ny4.minute)) == {(9, 30), (13, 30)})
    day0 = raw.tz_convert(TZ_NY)
    d0 = day0[(day0.index.date == day0.index[0].date()) & (day0.index.hour * 60 + day0.index.minute >= 570) & (day0.index.hour * 60 + day0.index.minute < 960)]
    check("4h morning bucket OHLC = the session's first 8 half-hours", abs(b4.iloc[0]["high"] - d0.iloc[:8]["high"].max()) < 1e-9
          and abs(b4.iloc[0]["open"] - d0.iloc[0]["open"]) < 1e-9 and abs(b4.iloc[0]["close"] - d0.iloc[7]["close"]) < 1e-9)
    f = to_frame(b1)
    cost_e, cost_c = cost_spec("etf", "XLB"), {"fee": 11.0, "slip": 3.0, "fund": 1.0}
    r = run_symbol(f, cost_e)
    check("runs on synthetic bars, trades carry cost terms", r["n"] == 0 or all("cost_r" in t and t["cost_r"] > 0 for t in r["trades"]))
    sig = [{"i": 30, "stop_idx": float(f["e_o"].iloc[31]) * 0.99}]
    t_e = simulate(f, sig, 10, cost_e)["trades"]
    t_c = simulate(f, sig, 10, cost_c)["trades"]
    t_c2 = simulate(f, sig, 10, cost_c, 2.0)["trades"]
    check("one synthetic trade replays", len(t_e) == 1 and len(t_c) == 1)
    if t_e and t_c and t_c2:
        check("ETF cost has no funding; crypto cost adds fee + funding", t_e[0]["funding_r"] == 0.0 and t_c[0]["fee_r"] > 0 and t_e[0]["fee_r"] == 0.0)
        check("2x doubles slippage only", abs(t_c2[0]["slippage_r"] - 2 * t_c[0]["slippage_r"]) < 2e-4 and t_c2[0]["fee_r"] == t_c[0]["fee_r"])
        check("entry is the NEXT bar's open (no signal-bar lookahead)", abs(t_e[0]["entry"] - float(f["e_o"].iloc[31])) < 1e-6)
    per = {"A": {"trades": [{"entry_date": "2021-01-01T00:00:00+00:00", "net_r": 1.0}], "net_r": 1.0, "net_r_2x_slip": 0.9},
           "B": {"trades": [{"entry_date": "2022-01-01T00:00:00+00:00", "net_r": -0.5}], "net_r": -0.5, "net_r_2x_slip": -0.6}}
    g = grade_pooled(per, np.zeros(200))
    check("pooled n<25 is INDETERMINATE", g["verdict"] == "indeterminate")
    check("latest-40% split takes the chronologically last trades", g["latest_40pct"]["from"] == "2022-01-01T00:00:00+00:00")
    check("every unit has a rule naming its strict majority", all(f">= {len(u['symbols']) // 2 + 1} of {len(u['symbols'])}" in rule_text(u) for u in UNITS.values()))
    print("SELF-TEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unit", choices=sorted(UNITS))
    ap.add_argument("--out")
    ap.add_argument("--cache-dir")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not (a.unit and a.out):
        ap.error("--unit and --out are required")
    rec = run_unit(a.unit, Path(a.out), Path(a.cache_dir) if a.cache_dir else None)
    print(json.dumps({"unit": a.unit, "verdict": rec["verdict"], "n": rec["n"], "note": rec["note"]}))
    for s, v in rec["measurement"]["symbols"].items():
        print(f"  {s:9s} n={v['n']:4d} net_r={v['net_r']:9.3f} 2x={v['net_r_2x_slip']:9.3f} K*={v['tp_calibration'].get('k_star')}")
    print(json.dumps(rec["measurement"]["pooled"], default=str)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
