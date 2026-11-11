#!/usr/bin/env python3
# wiring: research/queue/RQ-20261111-f5c8-01.yaml + RQ-20261111-f5c8-02.yaml (run.command via research-script-run.yml); row VOLUME-COMPOSITION-RESEARCH
"""VOLUME COMPOSITION: is a volume spike made of MORE trades or BIGGER trades, and does the split predict the next move
beyond plain volume?

WHY (operator 2026-11-11 ~08:15Z, row VOLUME-COMPOSITION-RESEARCH): "are volume spikes driven by bigger trades or more
trades, and does that predict moves?" Plain volume is the baseline to beat, net of cost.

DECOMPOSITION (exact, per bar t). volume V = trades N x average trade size S, so log V = log N + log S. Each is turned
into a SURPRISE against its own seasonal norm: x_surp = log x_t - mean(log x over the same slot-of-day on the previous
--season-days days), strictly before bar t. Because the norm is linear the identity survives:
    sv (volume surprise) = sn (count surprise) + ss (size surprise).
So conditioning on sv, the size surprise ss and the composition ss - sn carry the same information; the unit tests ss
GIVEN sv. A PASS therefore means "WHO traded (size) matters beyond HOW MUCH traded".

TWO TARGETS (one per unit; --target):
  direction   y = log(close[t+h] / close[t]). Feature x = ss_t * sign(r_t) (a size-led bar continues its own direction?).
              Baseline B = {sv_t * sign(r_t), r_t}. Claim: EDGE -- also graded as a trading rule net of the full cost stack.
  volatility  y = |log(close[t+h] / close[t])|. Feature x = ss_t. Baseline B = {sv_t, |r_t|}. Claim: MODEL QUALITY (an ML
              feature that adds information on the size of the next move); no trading rule.

STATISTIC. Partial rank IC per (symbol, calendar month): rank x, B and y within the month; residualise rank(x) on the
ranks of B by OLS; IC = Pearson(residual, rank(y)). Months are averaged across the symbols measured that month, then
t = mean / (sd / sqrt(M)) over the M monthly values (months are the independent unit; bars inside a month are not).
Discovery span and held-out span are graded separately; the verdict reads the HELD-OUT span.

TRADING RULE (direction only, causal). At bar t, a COMPOSITION trigger fires when ss_t is above its own trailing
--trigger-q quantile over the previous --trigger-days days (strictly before t) and r_t != 0; the trade takes
side = sign(r_t) * sign(discovery IC) for h bars, taker in / taker out. The BASELINE trigger is the same with sv in place
of ss (a plain volume spike). Net return per trade = side * y - cost, cost = fee + venue slippage + funding x expected 8h
windows crossed, all from the ONE cost model (scripts/research/timeframe_breakeven.py::cost_stack ->
src/runtime/execution_costs.py). h = 1 bar means trades never overlap within a symbol.

DATA. Binance USD-M perpetual 1h klines from data.binance.vision (monthly zips; keyless). Binance carries the per-bar
trade count (field 8); Bybit klines do not, so Bybit linear is PROXIED by Binance USD-M (stated in the output). Bars
coarser than 1h are resampled from 1h (volume and count summed). The raw zips are not stored.

VERDICT (verdict.json, the script_run.py contract). Thresholds are the UNIT's flags; defaults are documentation.
  direction:  pass  iff held-out mean IC has the discovery sign, |mean| >= --ic-min, t >= --t-heldout, discovery
                    t >= --t-discovery, AND the held-out composition rule's net mean per trade > 0 AND > the baseline
                    rule's net mean, with >= --min-trades composition trades.
  volatility: pass  iff held-out mean IC has the discovery sign, |mean| >= --ic-min, t >= --t-heldout, discovery
                    t >= --t-discovery.
  indeterminate iff fewer than --min-symbols symbols measured or fewer than --min-months held-out months, or (direction)
                    fewer than --min-trades composition trades in the held-out span.
  fail         otherwise.

    python3 scripts/research/volume_composition_ic.py --target direction --out /tmp/vc
    python3 scripts/research/volume_composition_ic.py --self-test
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

VISION = "https://data.binance.vision/data/futures/um"
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT")  # = timeframe_breakeven.CRYPTO_CORE
BAR_HOURS = {"1h": 1, "2h": 2, "4h": 4, "8h": 8}


def _warn(msg: str) -> None:
    print(f"[volume_composition_ic] {msg}", file=sys.stderr)


# ---- data ------------------------------------------------------------------------------------------------------
def _months(start: str, end: str) -> list[str]:
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def parse_kline_csv(text: str):
    """Binance-vision kline CSV -> DataFrame[ts, open, high, low, close, volume, trades, taker_buy]. Header-tolerant;
    open_time in ms or us (Binance re-cut some 2025 files in us)."""
    import pandas as pd
    rows = []
    for line in text.splitlines():
        f = line.split(",")
        try:
            t = int(f[0])
        except (ValueError, IndexError):
            continue  # header
        t = t // 1000 if t >= 10 ** 14 else t
        rows.append((t, float(f[1]), float(f[2]), float(f[3]), float(f[4]), float(f[5]), float(f[8]), float(f[9])))
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "trades", "taker_buy"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


def fetch_symbol(symbol: str, start: str, end: str) -> tuple[Any, dict[str, Any]]:
    """Monthly 1h zips for [start, end] (YYYY-MM). Returns (frame, coverage)."""
    import pandas as pd
    import requests
    parts, missing = [], []
    for ym in _months(start, end):
        url = f"{VISION}/monthly/klines/{symbol}/1h/{symbol}-1h-{ym}.zip"
        body = None
        for attempt in range(4):
            try:
                r = requests.get(url, timeout=60)
                if r.status_code == 404:
                    break
                r.raise_for_status()
                body = r.content
                break
            except requests.RequestException as exc:  # allow-silent: retried with backoff; a month that never arrives is listed in coverage.missing_months
                _warn(f"{symbol} {ym}: {exc} (attempt {attempt + 1})")
                time.sleep(2 ** attempt)
        if body is None:
            missing.append(ym)
            continue
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            parts.append(parse_kline_csv(zf.read(zf.namelist()[0]).decode("utf-8")))
    if not parts:
        return pd.DataFrame(), {"months_requested": len(_months(start, end)), "months_missing": missing}
    df = pd.concat(parts).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df, {"months_requested": len(_months(start, end)), "months_missing": missing, "bars_1h": len(df),
                "first_ts": str(df["ts"].iloc[0]), "last_ts": str(df["ts"].iloc[-1])}


def resample(df, bar: str):
    if bar == "1h":
        return df.copy()
    rule = f"{BAR_HOURS[bar]}h"
    out = (df.set_index("ts").resample(rule, label="left", closed="left")
             .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "trades": "sum",
                   "taker_buy": "sum"}).dropna(subset=["close"]).reset_index())
    return out


# ---- features --------------------------------------------------------------------------------------------------
def features(df, *, bar: str, horizon: int, season_days: int):
    """Adds sv, sn, ss, r, y_fwd to a bar frame. Seasonal norm = mean over the same slot-of-day on the previous
    `season_days` days, strictly before the bar (shift by one day inside each slot)."""
    import numpy as np
    d = df.copy()
    d = d[(d["volume"] > 0) & (d["trades"] > 0)].reset_index(drop=True)
    d["lv"] = np.log(d["volume"])
    d["ln"] = np.log(d["trades"])
    d["ls"] = d["lv"] - d["ln"]
    d["slot"] = d["ts"].dt.hour // BAR_HOURS[bar]
    for col, out in (("lv", "sv"), ("ln", "sn"), ("ls", "ss")):
        norm = d.groupby("slot")[col].transform(lambda s: s.shift(1).rolling(season_days, min_periods=season_days // 2).mean())
        d[out] = d[col] - norm
    lc = np.log(d["close"])
    d["r"] = lc.diff()
    d["y_fwd"] = lc.shift(-horizon) - lc
    return d.dropna(subset=["sv", "sn", "ss", "r", "y_fwd"]).reset_index(drop=True)


def _rank(a):
    import pandas as pd
    return pd.Series(a).rank(method="average").to_numpy()


def partial_rank_ic(x, base: list[Any], y) -> float | None:
    """Pearson(resid(rank x | ranks of base), rank y). None when degenerate."""
    import numpy as np
    n = len(x)
    if n < 30:
        return None
    rx, ry = _rank(x), _rank(y)
    X = np.column_stack([np.ones(n)] + [_rank(b) for b in base])
    beta, *_ = np.linalg.lstsq(X, rx, rcond=None)
    e = rx - X @ beta
    if e.std() < 1e-12 or ry.std() < 1e-12:
        return None
    return float(np.corrcoef(e, ry)[0, 1])


def target_arrays(d, target: str):
    import numpy as np
    sgn = np.sign(d["r"].to_numpy())
    if target == "direction":
        return d["ss"].to_numpy() * sgn, [d["sv"].to_numpy() * sgn, d["r"].to_numpy()], d["y_fwd"].to_numpy()
    return d["ss"].to_numpy(), [d["sv"].to_numpy(), np.abs(d["r"].to_numpy())], np.abs(d["y_fwd"].to_numpy())


def monthly_ic(d, target: str) -> dict[str, float]:
    out = {}
    for ym, g in d.groupby(d["ts"].dt.strftime("%Y-%m")):
        x, base, y = target_arrays(g, target)
        ic = partial_rank_ic(x, base, y)
        if ic is not None and math.isfinite(ic):
            out[str(ym)] = ic
    return out


def summarise(pooled: dict[str, float]) -> dict[str, Any]:
    import numpy as np
    v = np.array([pooled[k] for k in sorted(pooled)], dtype=float)
    m = len(v)
    if m < 2:
        return {"months": m, "mean_ic": float(v.mean()) if m else None, "sd": None, "t": None}
    sd = float(v.std(ddof=1))
    return {"months": m, "mean_ic": float(v.mean()), "sd": sd, "t": float(v.mean() / (sd / math.sqrt(m))) if sd > 0 else None,
            "share_positive": float((v > 0).mean())}


def trades(d, *, col: str, q: float, trigger_days: int, bar: str, side_sign: float, cost_bps: float):
    """Causal trigger on `col` above its trailing q-quantile (previous trigger_days days, strictly before t).
    Returns a numpy array of net returns (in bps) per trade."""
    import numpy as np
    win = trigger_days * 24 // BAR_HOURS[bar]
    thr = d[col].shift(1).rolling(win, min_periods=win // 2).quantile(q)
    fire = (d[col] > thr) & (d["r"] != 0)
    g = d[fire]
    side = np.sign(g["r"].to_numpy()) * side_sign
    return side * g["y_fwd"].to_numpy() * 1e4 - cost_bps, g["ts"]


# ---- run ---------------------------------------------------------------------------------------------------------
def grade(target: str, disc: dict[str, Any], held: dict[str, Any], rule: dict[str, Any] | None, *, n_symbols: int,
          a: argparse.Namespace) -> tuple[str, str]:
    if n_symbols < a.min_symbols:
        return "indeterminate", f"{n_symbols} symbols measured < {a.min_symbols}"
    if (held.get("months") or 0) < a.min_months:
        return "indeterminate", f"{held.get('months')} held-out months < {a.min_months}"
    if target == "direction" and rule is not None and rule["held_out"]["composition"]["n"] < a.min_trades:
        return "indeterminate", f"{rule['held_out']['composition']['n']} held-out composition trades < {a.min_trades}"
    d_mean, h_mean = disc.get("mean_ic"), held.get("mean_ic")
    d_t, h_t = disc.get("t"), held.get("t")
    why = []
    ok = True
    if d_mean is None or h_mean is None or d_t is None or h_t is None:
        return "indeterminate", "an IC summary is undefined (too few months or zero variance)"
    if math.copysign(1, d_mean) != math.copysign(1, h_mean):
        ok = False
        why.append(f"held-out sign {h_mean:+.4f} differs from discovery {d_mean:+.4f}")
    if abs(h_mean) < a.ic_min:
        ok = False
        why.append(f"|held-out IC| {abs(h_mean):.4f} < {a.ic_min}")
    if abs(h_t) < a.t_heldout:
        ok = False
        why.append(f"|held-out t| {abs(h_t):.2f} < {a.t_heldout}")
    if abs(d_t) < a.t_discovery:
        ok = False
        why.append(f"|discovery t| {abs(d_t):.2f} < {a.t_discovery}")
    if target == "direction" and rule is not None:
        c, b = rule["held_out"]["composition"], rule["held_out"]["baseline"]
        if not (c["mean_net_bps"] is not None and c["mean_net_bps"] > 0):
            ok = False
            why.append(f"held-out composition rule net {c['mean_net_bps']} bps/trade <= 0")
        if b["mean_net_bps"] is not None and c["mean_net_bps"] is not None and c["mean_net_bps"] <= b["mean_net_bps"]:
            ok = False
            why.append(f"composition rule {c['mean_net_bps']:.2f} <= baseline rule {b['mean_net_bps']:.2f} bps/trade")
    return ("pass", "every clause holds") if ok else ("fail", "; ".join(why))


def _stats(arr) -> dict[str, Any]:
    import numpy as np
    n = len(arr)
    if n == 0:
        return {"n": 0, "mean_net_bps": None, "se_bps": None, "share_positive": None}
    return {"n": n, "mean_net_bps": float(np.mean(arr)), "se_bps": float(np.std(arr, ddof=1) / math.sqrt(n)) if n > 1 else None,
            "share_positive": float((arr > 0).mean())}


def run_frames(frames: dict[str, Any], a: argparse.Namespace, coverage: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    per_symbol: dict[str, dict[str, float]] = {}
    feats: dict[str, Any] = {}
    for sym, raw in frames.items():
        if raw is None or len(raw) == 0:
            continue
        d = features(resample(raw, a.bar), bar=a.bar, horizon=a.horizon, season_days=a.season_days)
        if len(d) < 500:
            coverage.setdefault(sym, {})["state"] = f"thin: {len(d)} bars after features"
            continue
        feats[sym] = d
        per_symbol[sym] = monthly_ic(d, a.target)
        coverage.setdefault(sym, {})["state"] = "measured"
    # pool across symbols per month
    months = sorted({m for v in per_symbol.values() for m in v})
    pooled = {m: float(np.mean([v[m] for v in per_symbol.values() if m in v])) for m in months}
    disc = summarise({m: x for m, x in pooled.items() if a.start <= m <= a.discovery_end})
    held = summarise({m: x for m, x in pooled.items() if a.heldout_start <= m <= a.end})
    per_sym_summary = {s: {"discovery": summarise({m: x for m, x in v.items() if m <= a.discovery_end}),
                           "held_out": summarise({m: x for m, x in v.items() if m >= a.heldout_start})}
                       for s, v in per_symbol.items()}
    rule = None
    if a.target == "direction" and feats:
        from scripts.research.timeframe_breakeven import cost_bps_for_hold, cost_stack
        side_sign = 1.0 if (disc.get("mean_ic") or 0.0) >= 0 else -1.0
        hold_h = a.horizon * BAR_HOURS[a.bar]
        acc = {"discovery": {"composition": [], "baseline": []}, "held_out": {"composition": [], "baseline": []}}
        costs = {}
        for sym, d in feats.items():
            st = cost_stack(sym)
            c_bps = cost_bps_for_hold(st, hold_h)
            costs[sym] = {"cost_bps_roundtrip": c_bps, **st}
            for name, col in (("composition", "ss"), ("baseline", "sv")):
                net, ts = trades(d, col=col, q=a.trigger_q, trigger_days=a.trigger_days, bar=a.bar, side_sign=side_sign,
                                 cost_bps=c_bps)
                ym = ts.dt.strftime("%Y-%m").to_numpy()
                acc["discovery"][name].append(net[(ym >= a.start) & (ym <= a.discovery_end)])
                acc["held_out"][name].append(net[(ym >= a.heldout_start) & (ym <= a.end)])
        rule = {span: {k: _stats(np.concatenate(v) if v else np.array([])) for k, v in arms.items()} for span, arms in acc.items()}
        rule["side_sign_from_discovery"] = side_sign
        rule["cost_per_symbol"] = costs
        rule["hold_hours"] = hold_h
    verdict, why = grade(a.target, disc, held, rule, n_symbols=len(feats), a=a)
    return {"verdict": verdict, "why": why, "discovery": disc, "held_out": held, "per_symbol": per_sym_summary,
            "trading_rule": rule, "n_symbols": len(feats), "pooled_monthly_ic": pooled,
            "bars_used": {s: len(d) for s, d in feats.items()}}


def run(a: argparse.Namespace) -> dict[str, Any]:
    symbols = tuple(s for s in a.symbols.split(",") if s)
    frames, coverage = {}, {}
    for sym in symbols:
        try:
            df, cov = fetch_symbol(sym, a.start, a.end)
        except Exception as exc:  # allow-silent: a failed symbol lands as state fetch_failed in coverage; the denominator stays whole  # noqa: BLE001
            df, cov = None, {"state": "fetch_failed", "why": f"{type(exc).__name__}: {exc}"}
            _warn(f"{sym}: {cov['why']}")
        frames[sym], coverage[sym] = df, cov
    res = run_frames(frames, a, coverage)
    measured = res["n_symbols"]
    read_state = "measured" if measured else "no_data"
    verdict = res["verdict"] if measured else "indeterminate"
    h, dd = res["held_out"], res["discovery"]
    fmt = lambda v, p=4: "—" if v is None else f"{v:+.{p}f}"
    note = (f"{verdict.upper()}: {res['why']}. target={a.target}, bar={a.bar}, h={a.horizon} bar(s). "
            f"Held-out {a.heldout_start}..{a.end}: mean partial rank IC {fmt(h.get('mean_ic'))}, t {fmt(h.get('t'), 2)}, "
            f"{h.get('months')} months. Discovery {a.start}..{a.discovery_end}: {fmt(dd.get('mean_ic'))}, t {fmt(dd.get('t'), 2)}. "
            f"{measured}/{len(symbols)} symbols measured. Binance USD-M 1h klines (trade count field), PROXY for Bybit linear.")
    if res["trading_rule"]:
        c, b = res["trading_rule"]["held_out"]["composition"], res["trading_rule"]["held_out"]["baseline"]
        note += (f" Held-out rule net of full cost: composition {fmt(c['mean_net_bps'], 2)} bps/trade (n={c['n']}), "
                 f"plain-volume baseline {fmt(b['mean_net_bps'], 2)} bps/trade (n={b['n']}).")
    out = {
        "verdict": verdict, "read_state": read_state,
        "population": (f"Binance USD-M perps {','.join(symbols)} 1h klines {a.start}..{a.end} resampled to {a.bar}; "
                       f"discovery {a.start}..{a.discovery_end}, held-out {a.heldout_start}..{a.end}; target {a.target}, "
                       f"horizon {a.horizon} bar(s); IC unit = (symbol, month), pooled per month across symbols"),
        "n": h.get("months"),
        "note": note,
        "decision_rule_id": a.rule_id,
        "registered_at": a.registered_at,
        "data_inputs": [],
        "measurement": {**res, "coverage": coverage,
                        "thresholds": {k: getattr(a, k) for k in ("ic_min", "t_heldout", "t_discovery", "min_trades",
                                                                  "min_symbols", "min_months", "trigger_q", "trigger_days",
                                                                  "season_days")},
                        "source": "data.binance.vision futures/um monthly 1h klines (keyless); Bybit linear proxied"},
    }
    od = Path(a.out)
    od.mkdir(parents=True, exist_ok=True)
    (od / "verdict.json").write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    return out


# ---- self-test -------------------------------------------------------------------------------------------------
def _synthetic(seed: int, effect: float, n_days: int = 900):
    """1h frame where (direction) the next bar continues a size-led bar's direction with strength `effect`."""
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    n = n_days * 24
    ts = pd.date_range("2021-01-01", periods=n, freq="1h", tz="UTC")
    hod = np.tile(np.arange(24), n_days)
    lnum = 6.0 + 0.4 * np.sin(hod / 24 * 2 * np.pi) + rng.normal(0, 0.3, n)
    lsize = 0.0 + rng.normal(0, 0.3, n)
    r = rng.normal(0, 0.01, n)
    ss_proxy = lsize - lsize.mean()
    r[1:] += effect * 0.01 * np.sign(r[:-1]) * ss_proxy[:-1] / 0.3
    close = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame({"ts": ts, "open": close, "high": close, "low": close, "close": close,
                         "volume": np.exp(lnum + lsize), "trades": np.exp(lnum), "taker_buy": np.exp(lnum + lsize) / 2})


def _self_test() -> int:
    import numpy as np
    a = build_parser().parse_args(["--out", "/dev/null", "--bar", "1h", "--start", "2021-01", "--discovery-end", "2022-06",
                                   "--heldout-start", "2022-07", "--end", "2023-06", "--min-months", "6", "--min-symbols", "2",
                                   "--min-trades", "50"])
    planted = run_frames({"A": _synthetic(1, 0.3), "B": _synthetic(2, 0.3)}, a, {})
    assert planted["held_out"]["mean_ic"] > 0.05 and planted["held_out"]["t"] > 3, planted["held_out"]
    null = run_frames({"A": _synthetic(3, 0.0), "B": _synthetic(4, 0.0)}, a, {})
    assert abs(null["held_out"]["mean_ic"]) < 0.03, null["held_out"]
    assert null["verdict"] in ("fail", "indeterminate"), null["verdict"]
    # identity: sv == sn + ss exactly
    d = features(_synthetic(5, 0.0), bar="1h", horizon=1, season_days=20)
    assert np.allclose(d["sv"], d["sn"] + d["ss"]), "decomposition identity broken"
    # resample keeps sums
    r4 = resample(_synthetic(6, 0.0, n_days=3), "4h")
    assert len(r4) == 18
    # partial IC: x fully explained by base -> ~0
    x = np.arange(200, dtype=float)
    assert abs(partial_rank_ic(x, [x * 2], np.random.default_rng(0).normal(size=200)) or 0.0) < 1e-6
    # csv parser: header + us timestamps
    txt = "open_time,o,h,l,c,v,ct,qv,count,tbb,tbq,ig\n1735689600000000,1,2,0.5,1.5,10,0,0,7,4,0,0\n"
    p = parse_kline_csv(txt)
    assert len(p) == 1 and p["trades"].iloc[0] == 7 and str(p["ts"].iloc[0]).startswith("2025-01-01")
    h, z = planted["held_out"], null["held_out"]
    print(f"self-test ok: planted effect found (IC {h['mean_ic']:.3f}, t {h['t']:.1f}); null {z['mean_ic']:.3f} -> {null['verdict']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--target", choices=("direction", "volatility"), default="direction")
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    p.add_argument("--bar", choices=tuple(BAR_HOURS), default="4h")
    p.add_argument("--horizon", type=int, default=1, help="forward bars")
    p.add_argument("--start", default="2021-01")
    p.add_argument("--discovery-end", default="2024-06")
    p.add_argument("--heldout-start", default="2024-07")
    p.add_argument("--end", default="2026-09")
    p.add_argument("--season-days", type=int, default=20)
    p.add_argument("--trigger-q", type=float, default=0.8)
    p.add_argument("--trigger-days", type=int, default=90)
    p.add_argument("--ic-min", type=float, default=0.02)
    p.add_argument("--t-heldout", type=float, default=2.5)
    p.add_argument("--t-discovery", type=float, default=2.0)
    p.add_argument("--min-trades", type=int, default=200)
    p.add_argument("--min-symbols", type=int, default=4)
    p.add_argument("--min-months", type=int, default=18)
    p.add_argument("--rule-id", default="")
    p.add_argument("--registered-at", default="")
    p.add_argument("--unit", default="")
    p.add_argument("--out", required=False, default="")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out:
        print("--out is required", file=sys.stderr)
        return 2
    v = run(a)
    print(v["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
