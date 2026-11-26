#!/usr/bin/env python3
# wiring: run by the DESK-MACRO-DAILY brief lane after the packet (.claude/skills/trading-desk/SKILL.md section 7b); writes comms/desk/macro/packets/analysis-<stamp>.json
"""Desk macro ANALYSIS stage: the brief's own forecasts, computed in-run from data (not aggregated from the news).

Why (operator, 2026-11-26, verbatim): "It also shouldn't just be looking for forecasts. It should be looking at data to develop its
own forecasts, right? Like, let's be clear, that's what we're trying to get at here. Not just aggregating open source data, but
actually making inferences of deep big data analysis." Each output below is a FORECAST with a point, an interval, its method, its
inputs and its own out-of-sample error record, so the brief can cite it in ``forecasts[]`` and the grader can score it later against
the realised value, consensus and a naive baseline (macro-research invariant 5: beat the naive floor, not just the correlation bar).

Stages (each carries a read_state; could-not-look is never written as empty):
  nowcasts    next-release forecasts for US releases inside the packet's calendar window, from public FRED series (keyless
              fredgraph.csv, CURRENT vintage: stamped pit_basis=current_vintage) with the repo's pre-registered point-in-time model
              scripts/macro/econ_expectation.py (seasonal AR OLS, expanding window, leakage-safe by construction). Each nowcast
              carries the model's own walk-forward RMSE over the last N releases next to a naive (last value) RMSE, so a reader
              sees whether the model beats naive on this series before trusting it; the 80% interval is point +/- 1.2816 RMSE.
  rv_screen   relative-value dislocations across the whole packet panel: each symbol's 5-day return residual against its
              benchmark beta (SPY for equities/ETFs/futures, BTCUSDT for crypto), beta and residual sigma fit on the 55 days before
              the last 5, z = residual_5d / (sigma * sqrt 5). Not the names in the news: every measured symbol is scanned.
  priors      for each candidate trade the lane drafts (``--candidates FILE``): the EMPIRICAL rate at which the same geometry
              (entry offset, stop and TP in ATR multiples, horizon) hit TP before SL on the symbol's own daily history (up to 1000
              bars from the trader's bar API), unconditional and conditioned on today's state (5-day return sign, distance to SMA20
              within 1 ATR). Gross of costs, same-bar stop-first convention as the desk replayer. This is the brief's own p_hit.

  python3 scripts/ops/desk_macro_analysis.py --packet PACKET.json [--candidates CANDS.json] [--out-dir comms/desk/macro/packets]
  python3 scripts/ops/desk_macro_analysis.py --self-test

CANDS.json: [{"symbol": "ETHUSDT", "side": "short", "entry": 1750, "stop": 1870, "tp": 1590, "horizon_bars": 10, "good_till_bars": 3}]
Read-only research: no order, no config, no DB write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "macro"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import econ_expectation as ee  # noqa: E402

SCHEMA = "desk_macro_analysis/1"
OUT_DIR = REPO / "comms" / "desk" / "macro" / "packets"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
API = "https://ict-bot.duckdns.org/api/bot/candles"
Z80 = 1.2816
BACKTEST_N = 36
# calendar kind -> the FRED series and transform whose next value IS that release's headline
NOWCASTS = {
    "nfp": {"fred": "PAYEMS", "cadence": "monthly", "transform": "diff", "unit": "thousands, m/m change"},
    "core_cpi_mom": {"fred": "CPILFESL", "cadence": "monthly", "transform": "pct", "unit": "% m/m"},
    "cpi_mom": {"fred": "CPIAUCSL", "cadence": "monthly", "transform": "pct", "unit": "% m/m"},
    "initial_jobless_claims": {"fred": "ICSA", "cadence": "weekly", "transform": "level", "unit": "claims"},
    "continuing_jobless_claims": {"fred": "CCSA", "cadence": "weekly", "transform": "level", "unit": "claims"},
    "unemployment_rate": {"fred": "UNRATE", "cadence": "monthly", "transform": "level", "unit": "%"},
    "retail_sales_mom": {"fred": "RSAFS", "cadence": "monthly", "transform": "pct", "unit": "% m/m"},
    "average_hourly_earnings_mom": {"fred": "CES0500000003", "cadence": "monthly", "transform": "pct", "unit": "% m/m"},
}


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def code_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes() + Path(ee.__file__).read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------------------------ nowcasts
def fred_series(sid: str) -> list[tuple[str, float]]:
    import requests
    r = requests.get(FRED.format(sid=sid), timeout=30)
    r.raise_for_status()
    out = []
    for line in r.text.splitlines()[1:]:
        d, _, v = line.partition(",")
        try:
            out.append((d, float(v)))
        except ValueError:  # allow-silent: FRED writes '.' for a missing observation; it is skipped, never zero
            continue
    if not out:
        raise ValueError(f"FRED {sid}: no observations (blocked or renamed?)")
    return out


def transform(obs: list[tuple[str, float]], how: str) -> list[tuple[str, float]]:
    if how == "level":
        return obs
    out = []
    for (_, a), (d, b) in zip(obs, obs[1:]):
        if how == "diff":
            out.append((d, b - a))
        elif how == "pct" and a:
            out.append((d, (b / a - 1.0) * 100.0))
    return out


def next_period(last: str, cadence: str) -> str:
    t = datetime.fromisoformat(last)
    if cadence == "weekly":
        return (t + timedelta(days=7)).date().isoformat()
    y, m = (t.year + (t.month // 12), t.month % 12 + 1)
    return f"{y:04d}-{m:02d}-01"


def nowcast_series(values: list[float], period: int, n_back: int = BACKTEST_N) -> dict:
    """Point forecast of the NEXT value + the model's and naive's walk-forward RMSE over the last n_back observations."""
    point = ee.expectation_at(values, len(values), period=period)
    errs, naive = [], []
    for i in range(max(1, len(values) - n_back), len(values)):
        e = ee.expectation_at(values, i, period=period)
        if e is not None:
            errs.append(values[i] - e)
            naive.append(values[i] - values[i - 1])
    rmse = math.sqrt(sum(x * x for x in errs) / len(errs)) if errs else None
    nrmse = math.sqrt(sum(x * x for x in naive) / len(naive)) if naive else None
    return {"point": point, "rmse": rmse, "naive_rmse": nrmse, "n_backtest": len(errs),
            "beats_naive": (rmse < nrmse) if (rmse is not None and nrmse) else None}


def part_nowcasts(packet: dict, get: Callable[[str], list] = fred_series) -> dict:
    cal = (packet.get("parts") or {}).get("calendar") or {}
    if cal.get("read_state") not in ("measured", "partial"):
        return {"read_state": "could_not_look", "reason": f"packet calendar is {cal.get('read_state')}"}
    upcoming: dict[str, dict] = {}
    for e in cal.get("events") or []:
        k = e.get("kind")
        if k in NOWCASTS and e.get("country") == "US" and not e.get("schedule_unconfirmed") and k not in upcoming:
            upcoming[k] = e
    out = {}
    for k, ev in upcoming.items():
        spec = NOWCASTS[k]
        try:
            raw = get(spec["fred"])
            ser = transform(raw, spec["transform"])
            vals = [v for _, v in ser]
            nc = nowcast_series(vals, ee.period_for_cadence(spec["cadence"]))
            if nc["point"] is None or nc["rmse"] is None:
                out[k] = {"read_state": "could_not_look", "reason": "too little history for the pre-registered model"}
                continue
            cons = (ev.get("expected") or {}).get("consensus")
            pt = nc["point"]
            out[k] = {"read_state": "measured", "release": ev.get("event_name"), "release_at": ev.get("scheduled_at"),
                      "event_id": ev.get("event_id"), "target_period": next_period(ser[-1][0], spec["cadence"]),
                      "series": spec["fred"], "transform": spec["transform"], "unit": spec["unit"],
                      "last_obs": {"date": ser[-1][0], "value": round(ser[-1][1], 6)},
                      "own_point": round(pt, 6), "interval_80": [round(pt - Z80 * nc["rmse"], 6), round(pt + Z80 * nc["rmse"], 6)],
                      "naive_point": round(ser[-1][1], 6), "model_rmse": round(nc["rmse"], 6),
                      "naive_rmse": round(nc["naive_rmse"], 6) if nc["naive_rmse"] else None,
                      "beats_naive_backtest": nc["beats_naive"], "n_backtest": nc["n_backtest"],
                      "consensus": cons, "own_minus_consensus": round(pt - float(cons), 6) if cons is not None else None,
                      "method": f"{ee.SPEC_VERSION} on FRED {spec['fred']} ({spec['transform']}), walk-forward RMSE interval",
                      "pit_basis": "current_vintage"}
            out[k]["brief_forecast"] = {
                "forecast_id": f"F-{k}", "target": {"kind": "release", "key": ev.get("event_id") or k, "resolves_at": ev.get("scheduled_at"),
                                                    "series": spec["fred"], "transform": spec["transform"], "period": out[k]["target_period"],
                                                    "naive_point": out[k]["naive_point"], "unit": spec["unit"]},
                "own_point": out[k]["own_point"], "interval": {"lo": out[k]["interval_80"][0], "hi": out[k]["interval_80"][1], "level": 0.8},
                "method": out[k]["method"], "inputs": {"analysis_ref": None},
                "consensus": cons, "own_minus_consensus": out[k]["own_minus_consensus"],
                "consensus_read_state": "measured" if cons is not None else "could_not_look",
                "consensus_source": "S1" if cons is not None else None,
                "consensus_reason": None if cons is not None else "no consensus in the packet calendar; search it (Bigdata.com / web) and fill it",
                "gap_z": (round(out[k]["own_minus_consensus"] / nc["rmse"], 6) if cons is not None and nc["rmse"] else None)}
        except Exception as exc:  # noqa: BLE001  # allow-silent: per-release could_not_look with the reason
            out[k] = {"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    if not upcoming:
        return {"read_state": "not_applicable", "reason": f"no release of {sorted(NOWCASTS)} in the calendar window", "releases": {}}
    n_ok = sum(1 for v in out.values() if v["read_state"] == "measured")
    return {"read_state": "measured" if n_ok == len(out) else ("could_not_look" if n_ok == 0 else "partial"), "releases": out}


# ----------------------------------------------------------------------------------------------------------- rv screen
def _logret(c: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(c, c[1:]) if a > 0 and b > 0]


def residual_z(c: list[float], cb: list[float], fit: int = 55, recent: int = 5) -> dict | None:
    r, rb = _logret(c), _logret(cb)
    n = min(len(r), len(rb))
    if n < fit + recent:
        return None
    r, rb = r[-(fit + recent):], rb[-(fit + recent):]
    x, y = rb[:fit], r[:fit]
    mx, my = sum(x) / fit, sum(y) / fit
    vx = sum((a - mx) ** 2 for a in x)
    if vx <= 0:
        return None
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / vx
    alpha = my - beta * mx
    res = [b - alpha - beta * a for a, b in zip(x, y)]
    sd = math.sqrt(sum(e * e for e in res) / (fit - 2))
    if sd <= 0:
        return None
    r5 = sum(b - alpha - beta * a for a, b in zip(rb[fit:], r[fit:]))
    return {"beta": round(beta, 4), "resid_5d_pct": round(r5 * 100, 4), "z": round(r5 / (sd * math.sqrt(recent)), 3)}


def part_rv_screen(packet: dict, top: int = 12) -> dict:
    syms = ((packet.get("parts") or {}).get("prices") or {}).get("symbols") or {}
    bench = {k: (syms.get(k) or {}).get("closes_61") for k in ("SPY", "BTCUSDT")}
    rows = []
    for s, v in syms.items():
        c = v.get("closes_61") if v.get("read_state") == "measured" else None
        b = "BTCUSDT" if s.endswith("USDT") else "SPY"
        if not c or not bench[b] or s == b:
            continue
        rz = residual_z(c, bench[b])
        if rz:
            rows.append({"symbol": s, "benchmark": b, **rz})
    if not rows:
        return {"read_state": "could_not_look", "reason": "no symbol had 61 closes alongside its benchmark"}
    rows.sort(key=lambda r: -abs(r["z"]))
    return {"read_state": "measured", "population": f"{len(rows)} panel symbols with 61 closes", "method":
            "5d residual vs benchmark beta fit on the prior 55 daily log returns; z = resid_5d / (sigma sqrt 5)",
            "rich": [r for r in rows if r["z"] > 0][:top], "cheap": [r for r in rows if r["z"] < 0][:top]}


# --------------------------------------------------------------------------------------------------------------- priors
def fetch_daily(symbol: str, limit: int = 1000, retry_pause_s: float = 11.0) -> list[dict]:
    """Daily bars; ONE delayed retry of an empty answer (under load the web API's Alpaca path cools down and its 10 s cache
    serves the empty result, the same class desk_macro_packet.part_prices retries)."""
    import time

    import requests
    for attempt in (0, 1):
        r = requests.get(API, params={"symbol": symbol, "interval": "1d", "limit": limit}, timeout=90)
        r.raise_for_status()
        bars = r.json().get("candles") or []
        if bars or attempt:
            return bars
        time.sleep(retry_pause_s)
    return []


def _atr_series(h, lo, c, n=14):
    tr = [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, len(c))]
    out = [None] * len(c)
    if len(c) <= n:
        return out
    a = sum(tr[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(c)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def geometry_prior(bars: list[dict], side: str, entry_off: float, stop_atr: float, tp_atr: float, horizon: int,
                   good_till: int, state: dict | None = None) -> dict:
    """Empirical TP-before-SL rate of this geometry on the symbol's own closed daily history (gross of costs)."""
    b = sorted(bars, key=lambda x: x["time"])
    h, lo, c = ([float(x[k]) for x in b] for k in ("high", "low", "close"))
    atr = _atr_series(h, lo, c)
    long_ = side == "long"
    res_all, res_cond = [], []
    for t in range(50, len(c) - good_till - horizon - 1):
        a = atr[t]
        if not a:
            continue
        e = c[t] + entry_off * a
        stop = e - stop_atr * a if long_ else e + stop_atr * a
        tp = e + tp_atr * a if long_ else e - tp_atr * a
        fill = next((k for k in range(t + 1, t + 1 + good_till) if lo[k] <= e <= h[k]), None)
        if fill is None:
            continue
        r = None
        for k in range(fill, min(fill + horizon, len(c))):
            hit_sl = lo[k] <= stop if long_ else h[k] >= stop
            hit_tp = h[k] >= tp if long_ else lo[k] <= tp
            if hit_sl:
                r = -1.0
                break
            if hit_tp:
                r = tp_atr / stop_atr
                break
        if r is None:
            k = min(fill + horizon, len(c)) - 1
            r = ((c[k] - e) if long_ else (e - c[k])) / (stop_atr * a)
        res_all.append(r)
        if state:
            ret5 = c[t] / c[t - 5] - 1
            sma20 = sum(c[t - 19:t + 1]) / 20
            if (ret5 > 0) == (state["ret_5d_pct"] > 0) and abs((c[t] - sma20) / a - state["dist_sma20_atr"]) <= 1.0:
                res_cond.append(r)
    win = tp_atr / stop_atr

    def summ(xs):
        if not xs:
            return {"n": 0, "p_tp": None, "mean_r_gross": None}
        return {"n": len(xs), "p_tp": round(sum(1 for x in xs if x == win) / len(xs), 4),
                "mean_r_gross": round(sum(xs) / len(xs), 4)}
    return {"all": summ(res_all), "conditional": summ(res_cond), "n_bars": len(c)}


def part_priors(packet: dict, cands: list[dict], fetch: Callable[[str], list] = fetch_daily) -> dict:
    syms = ((packet.get("parts") or {}).get("prices") or {}).get("symbols") or {}
    out = []
    for cd in cands:
        rec = {k: cd.get(k) for k in ("symbol", "side", "entry", "stop", "tp", "horizon_bars", "good_till_bars")}
        try:
            bars = fetch(cd["symbol"])
            if len(bars) < 80:
                raise ValueError(f"only {len(bars)} daily bars (need >= 80 for a geometry history)")
            st = syms.get(cd["symbol"]) or {}
            if st.get("read_state") != "measured":
                from desk_macro_packet import bar_stats
                st = bar_stats(bars, datetime.now(timezone.utc))
            a, last = st["atr14"], st["last_close"]
            geo = {"entry_off_atr": (cd["entry"] - last) / a, "stop_atr": abs(cd["entry"] - cd["stop"]) / a,
                   "tp_atr": abs(cd["tp"] - cd["entry"]) / a}
            g = geometry_prior(bars, cd["side"], geo["entry_off_atr"], geo["stop_atr"], geo["tp_atr"], int(cd["horizon_bars"]),
                               int(cd.get("good_till_bars") or 3), {"ret_5d_pct": st["ret_5d_pct"], "dist_sma20_atr": st["dist_sma20_atr"]})
            rec.update({"read_state": "measured" if g["all"]["n"] else "could_not_look",
                        "geometry_atr": {k: round(v, 3) for k, v in geo.items()}, **g,
                        "method": "own daily history, same ATR geometry, stop-first on a both-touch bar, gross of costs"})
        except Exception as exc:  # noqa: BLE001  # allow-silent: per-candidate could_not_look with the reason
            rec.update({"read_state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}"[:200]})
        out.append(rec)
    n_ok = sum(1 for r in out if r["read_state"] == "measured")
    return {"read_state": "not_applicable" if not out else ("measured" if n_ok == len(out) else ("could_not_look" if not n_ok else "partial")),
            "candidates": out}


def analyze(packet: dict, cands: list[dict] | None = None, now: datetime | None = None, fred=fred_series, fetch=fetch_daily) -> dict:
    now = now or datetime.now(timezone.utc)
    a = {"schema": SCHEMA, "analysis_id": f"DMA-{now.strftime('%Y%m%dT%H%M%SZ')}", "computed_at": _iso(now),
         "packet_id": packet.get("packet_id"), "packet_sha": packet.get("packet_sha"), "code_sha": code_sha(),
         "nowcasts": part_nowcasts(packet, fred), "rv_screen": part_rv_screen(packet),
         "priors": part_priors(packet, cands or [], fetch)}
    for v in (a["nowcasts"].get("releases") or {}).values():
        if v.get("brief_forecast"):
            v["brief_forecast"]["inputs"]["analysis_ref"] = a["analysis_id"]
    a["analysis_sha"] = hashlib.sha256(json.dumps(a, sort_keys=True, default=str).encode()).hexdigest()
    return a


# ------------------------------------------------------------------------------------------------------------ self-test
def self_test() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)
    # nowcast: a clean seasonal monthly series is forecast near its true next value, and beats naive
    vals = [100 + 10 * math.sin(2 * math.pi * i / 12) + 0.5 * i for i in range(120)]
    nc = nowcast_series(vals, 12)
    true_next = 100 + 10 * math.sin(2 * math.pi * 120 / 12) + 0.5 * 120
    check("nowcast: point near the true next value of a seasonal series", abs(nc["point"] - true_next) < 0.5)
    check("nowcast: model beats naive on a seasonal series", nc["beats_naive"] is True and nc["n_backtest"] == BACKTEST_N)
    check("transform diff / pct", transform([("a", 100.0), ("b", 110.0)], "diff") == [("b", 10.0)]
          and abs(transform([("a", 100.0), ("b", 110.0)], "pct")[0][1] - 10.0) < 1e-9)
    check("next_period monthly rolls the year", next_period("2026-12-01", "monthly") == "2027-01-01")
    pkt = {"parts": {"calendar": {"read_state": "measured", "events": [
        {"kind": "nfp", "country": "US", "event_name": "Nonfarm Payrolls", "scheduled_at": "2026-12-04T13:30:00Z",
         "event_id": "evt-nfp", "expected": {"consensus": 60.0}, "schedule_unconfirmed": False},
        {"kind": "core_cpi_mom", "country": "US", "event_name": "phantom", "schedule_unconfirmed": True}]}}}
    obs = [(f"20{10 + i // 12:02d}-{i % 12 + 1:02d}-01", 1000.0 + 15 * i + 5 * math.sin(i)) for i in range(150)]
    pn = part_nowcasts(pkt, lambda sid: obs)
    r = pn["releases"].get("nfp", {})
    check("nowcasts: NFP from PAYEMS diff with interval, consensus gap and naive baseline", r.get("read_state") == "measured"
          and r["interval_80"][0] < r["own_point"] < r["interval_80"][1] and r["own_minus_consensus"] == round(r["own_point"] - 60.0, 6)
          and r["naive_rmse"] is not None)
    check("nowcasts: a schedule_unconfirmed row is skipped (no forecast for a phantom release)", "core_cpi_mom" not in pn["releases"])
    check("nowcasts: FRED down -> could_not_look with the reason", part_nowcasts(pkt, lambda sid: (_ for _ in ()).throw(OSError("blocked")))
          ["releases"]["nfp"]["read_state"] == "could_not_look")
    # rv: a symbol that moved 5% vs a flat benchmark in the last 5 days has a large positive z
    base = [100 * math.exp(0.002 * math.sin(i)) for i in range(61)]
    own = [b * math.exp(0.003 * math.cos(1.7 * i)) for i, b in enumerate(base)]      # same beta, its own noise
    up = own[:56] + [own[55] * (1 + 0.01 * k) for k in range(1, 6)]
    rz = residual_z(up, base)
    check("rv: a 5-day idiosyncratic move gives a large z", rz is not None and rz["z"] > 3)
    rv = part_rv_screen({"parts": {"prices": {"symbols": {"SPY": {"read_state": "measured", "closes_61": base},
                                                          "XLE": {"read_state": "measured", "closes_61": up}}}}})
    check("rv: screen ranks it rich", rv["rich"][0]["symbol"] == "XLE")
    # prior: on a steady uptrend a long with a near TP hits far more often than a short with the mirror geometry
    t0 = 1_700_000_000
    bars = [{"time": t0 + i * 86400, "open": 100 + i, "high": 101.5 + i, "low": 99.5 + i, "close": 100.5 + i} for i in range(300)]
    gl = geometry_prior(bars, "long", 0.0, 1.0, 1.0, 5, 2)
    gs = geometry_prior(bars, "short", 0.0, 1.0, 1.0, 5, 2)
    check("prior: geometry hit-rate follows the path (long > short on an uptrend)", gl["all"]["p_tp"] > gs["all"]["p_tp"] and gl["all"]["n"] > 100)
    check("prior: no bars -> could_not_look", part_priors({}, [{"symbol": "X", "side": "long", "entry": 1, "stop": 0.9, "tp": 1.2,
                                                                "horizon_bars": 5}], lambda s: [])["candidates"][0]["read_state"] == "could_not_look")
    a = analyze(pkt, [], datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc), fred=lambda sid: obs, fetch=lambda s: bars)
    body = {k: v for k, v in a.items() if k != "analysis_sha"}
    check("analysis is sha-stamped and tied to its packet", a["analysis_sha"] == hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest())
    print("self-test " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packet", type=Path)
    ap.add_argument("--candidates", type=Path)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.packet:
        ap.error("--packet is required")
    cands = json.loads(a.candidates.read_text()) if a.candidates else []
    res = analyze(json.loads(a.packet.read_text()), cands)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    out = a.out_dir / f"analysis-{res['analysis_id'].removeprefix('DMA-')}.json"
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(f"wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    for k, v in (res["nowcasts"].get("releases") or {}).items():
        print(f"  nowcast {k}: {v.get('own_point')} {v.get('interval_80')} (model rmse {v.get('model_rmse')} vs naive {v.get('naive_rmse')}; "
              f"consensus {v.get('consensus')}) {v.get('reason', '')}")
    for r in (res["rv_screen"].get("rich") or [])[:3] + (res["rv_screen"].get("cheap") or [])[:3]:
        print(f"  rv {r['symbol']}: z {r['z']} (resid {r['resid_5d_pct']}%, beta {r['beta']} vs {r['benchmark']})")
    for c in res["priors"].get("candidates") or []:
        print(f"  prior {c['symbol']} {c['side']}: all {c.get('all')} conditional {c.get('conditional')} {c.get('reason', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
