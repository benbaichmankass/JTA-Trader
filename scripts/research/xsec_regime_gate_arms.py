#!/usr/bin/env python3
# wiring: research/queue units authored by RESEARCH-FILL-20261122 (run.command via research-script-run.yml; public Binance-vision closes + Bybit funding -> runner)
"""XSEC-CRYPTO REGIME-GATE ARMS (lane RESEARCH-FILL-20261122; iteration of RQ-20261101-58e4-02, orphan `xsec-crypto`).

58e4-02 diagnosis (from its result): shorts -0.21 vs longs +1.86 and 2021 is 68% of net, i.e. the book earns in one regime. The lever
families it left untested include the REGIME GATE. This is the driver: one fixed arm list on the SAME engine, panel and funding series
that frontier_momentum_runner's xsec mode uses (scripts/backtest_xsec_momentum.run_backtest, fee + slippage + SIGNED settled funding),
each arm a BTC-state `btc_risk_off` mask the engine already honours (read on the rebalance day with information <= that day):

  G0            no gate (the baseline control, same engine and panel)
  SMA<n>        risk-off when BTC close < its n-day SMA, n in --sma-days (default 20,50,100,200)
  VOL<w>_P<q>   risk-off when BTC realized-vol (w-day stdev of daily returns) exceeds its trailing 365-day q-th percentile

Every arm is counted (denominator = number of gate arms, stated in the output). Each arm is judged against a MATCHED-RANDOM gate:
`--draws` random risk-off masks in 7-day blocks with the same risk-off fraction, same engine; control_p = (#draws with net >= arm net
+ 1)/(draws + 1). Reported per arm: net total R (sum of daily fractional book returns), delta vs G0, per-calendar-year net and
delta, weeks gated, control_p. Verdict is the unit's registered rule (--delta-min, --alpha, --min-years); this script grades it
verbatim and the grade is a function of the numbers only.

    python3 scripts/research/xsec_regime_gate_arms.py --days 1460 --out O
    python3 scripts/research/xsec_regime_gate_arms.py --self-test
Writes <out>/verdict.json (+ arms.json). Tier-1 research tooling; no config, no order path.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts"), str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops")]

DEFAULT_SYMBOLS = "ETHUSDT,SOLUSDT,ADAUSDT,AVAXUSDT,BNBUSDT,LINKUSDT"
SEED = 20261122


def risk_off_sma(btc: pd.Series, n: int) -> pd.Series:
    sma = btc.rolling(n, min_periods=n).mean()
    return (btc < sma) & sma.notna()


def risk_off_vol(btc: pd.Series, window: int, q: float, lookback: int = 365) -> pd.Series:
    vol = btc.pct_change().rolling(window, min_periods=window).std()
    thr = vol.rolling(lookback, min_periods=lookback // 2).quantile(q)      # trailing only: no look-ahead
    return (vol > thr) & thr.notna()


def _book(panel, funds, mask: Optional[pd.Series], fee_mult: float, rebalance: int, formation: int):
    import backtest_xsec_momentum as xsec
    r = xsec.run_backtest(panel, formation=formation, skip=0, rebalance=rebalance, quantile=0.3333, fee_bps=xsec.FEE_BPS_ROUNDTRIP,
                          fee_mult=fee_mult, venue="perp", funding_series=funds, btc_risk_off=mask)
    per_year: Dict[str, float] = {}
    for day, net, _ in r["daily"]:
        per_year[str(day.year)] = per_year.get(str(day.year), 0.0) + float(net)
    s = r["summary"]
    return {"net": float(s["net_total_return"]), "per_year": {k: round(v, 6) for k, v in per_year.items()},
            "weeks_gated": int(s.get("weeks_gated", 0)), "weeks_total": int(s.get("weeks_total", 0)),
            "n_trades": int(sum(v["n_trades"] for v in s["per_symbol"].values()))}


def random_mask(index: pd.DatetimeIndex, frac: float, rng: random.Random, block: int = 7) -> pd.Series:
    n_blocks = (len(index) + block - 1) // block
    on = [rng.random() < frac for _ in range(n_blocks)]
    return pd.Series([on[i // block] for i in range(len(index))], index=index)


def grade(arms: List[dict], base: dict, delta_min: float, alpha: float, min_years: int, n_floor: int) -> dict:
    if base["n_trades"] < n_floor:
        return {"verdict": "indeterminate", "why": f"baseline n_trades {base['n_trades']} < floor {n_floor}", "passing": []}
    passing = []
    for a in arms:
        ys = [y for y in base["per_year"] if y in a["per_year"]]
        wins = sum(1 for y in ys if a["per_year"][y] - base["per_year"][y] > 0)
        tot = a["delta"]
        top = max((a["per_year"][y] - base["per_year"][y] for y in ys), default=0.0)
        a["years_improved"], a["years_n"] = wins, len(ys)
        a["max_year_share"] = round(top / tot, 3) if tot > 0 else None
        a["pass"] = bool(tot >= delta_min and a["control_p"] <= alpha and a["net"] > 0 and wins >= min(min_years, len(ys))
                         and a["max_year_share"] is not None and a["max_year_share"] <= 0.5)
        if a["pass"]:
            passing.append(a["arm"])
    if passing:
        return {"verdict": "pass", "why": f"{passing} beat G0 by >= {delta_min} with matched-random p <= {alpha}, net > 0, "
                                          f">= {min_years} improved years and no year > 50% of the gain", "passing": passing}
    if all(a["delta"] < delta_min for a in arms):
        return {"verdict": "fail", "why": f"no gate arm beats G0 by {delta_min} (best {max(a['delta'] for a in arms):.4f}; "
                                          f"{len(arms)} arms counted)", "passing": []}
    return {"verdict": "indeterminate", "why": "some arm clears the delta but not the control / years / concentration tests", "passing": []}


def run(a, inputs: Optional[dict] = None, btc: Optional[pd.Series] = None) -> dict:
    import frontier_momentum_runner as F
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    inp = inputs or F.build_inputs(symbols, a.days)
    if inp["panel"] is None or inp["panel"].empty:
        return {"verdict": "not_applicable", "read_state": "no_data", "population": "xsec gate arms: no usable panel", "n": None,
                "note": f"no_data for {inp.get('empty')}: nothing graded", "measurement": {"coverage": inp["coverage"]}}
    panel, funds = inp["panel"], inp["funding"]
    if btc is None:
        btc = F._fetch_closes("BTCUSDT", inp["start"] - pd.Timedelta(days=400).to_pytimedelta(), inp["end"])
    if len(btc) < 300:
        return {"verdict": "not_applicable", "read_state": "no_data", "population": "xsec gate arms: BTC closes missing", "n": None,
                "note": f"BTC closes {len(btc)} rows < 300: gate masks undefined", "measurement": {}}
    btc = btc.sort_index()
    base = _book(panel, funds, None, a.fee_multiplier, a.rebalance_days, a.formation_days)
    masks = {f"SMA{n}": risk_off_sma(btc, n) for n in [int(x) for x in a.sma_days.split(",")]}
    for w in [int(x) for x in a.vol_windows.split(",")]:
        masks[f"VOL{w}_P{int(a.vol_q * 100)}"] = risk_off_vol(btc, w, a.vol_q)
    rng = random.Random(SEED)
    arms = []
    for name, m in masks.items():
        res = _book(panel, funds, m, a.fee_multiplier, a.rebalance_days, a.formation_days)
        sub = m.reindex(panel.index).fillna(False)
        frac = float(sub.mean())
        ge = 0
        for _ in range(a.draws):
            ge += _book(panel, funds, random_mask(panel.index, frac, rng), a.fee_multiplier, a.rebalance_days,
                        a.formation_days)["net"] >= res["net"]
        arms.append({"arm": name, **res, "delta": round(res["net"] - base["net"], 6), "risk_off_frac": round(frac, 4),
                     "control_p": round((ge + 1) / (a.draws + 1), 4), "draws": a.draws})
    g = grade(arms, base, a.delta_min, a.alpha, a.min_years, a.n_floor)
    return {"verdict": g["verdict"], "read_state": "measured", "note": g["why"], "n": base["n_trades"],
            "population": f"xsec long/short, {sorted(panel.columns)}, daily {panel.index[0].date()}..{panel.index[-1].date()} "
                          f"({len(panel)} days), {len(arms)} gate arms vs G0, matched-random {a.draws} draws",
            "measurement": {"baseline": base, "arms": arms, "arm_denominator": len(arms), "grade": g,
                            "rule": {"delta_min": a.delta_min, "alpha": a.alpha, "min_years": a.min_years, "n_floor": a.n_floor},
                            "coverage": inp["coverage"], "unit_note": "net is the sum of daily FRACTIONAL book returns (no stop distance in this engine)"}}


def _selftest() -> None:
    rng = np.random.default_rng(5)
    idx = pd.date_range("2021-01-01", periods=1500, freq="D", tz="UTC")
    btc = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.03, len(idx)))), index=idx)
    ro = risk_off_sma(btc, 50)
    assert not ro.iloc[:49].any() and ro.dtype == bool
    rv = risk_off_vol(btc, 30, 0.7)
    assert not rv.iloc[:200].any()                         # trailing percentile undefined early: never gated on nothing
    # no look-ahead: changing the future must not change today's mask
    b2 = btc.copy()
    b2.iloc[1000:] *= 3
    assert (risk_off_sma(b2, 50).iloc[:1000] == ro.iloc[:1000]).all()
    assert (risk_off_vol(b2, 30, 0.7).iloc[:1000] == rv.iloc[:1000]).all()
    m = random_mask(idx, 0.4, random.Random(1))
    assert len(m) == len(idx) and 0.2 < m.mean() < 0.6
    base = {"net": 1.0, "per_year": {"2021": 0.4, "2022": 0.3, "2023": 0.3}, "n_trades": 200}
    good = {"arm": "A", "net": 2.0, "delta": 1.0, "control_p": 0.01, "per_year": {"2021": 0.8, "2022": 0.6, "2023": 0.6}}
    assert grade([dict(good)], base, 0.3, 0.05, 3, 100)["verdict"] == "pass"
    conc = {**good, "per_year": {"2021": 1.6, "2022": 0.3, "2023": 0.1}}
    assert grade([conc], base, 0.3, 0.05, 2, 100)["verdict"] == "indeterminate"          # one year carries the gain
    assert grade([{**good, "delta": 0.01, "net": 1.01}], base, 0.3, 0.05, 3, 100)["verdict"] == "fail"
    assert grade([dict(good)], {**base, "n_trades": 10}, 0.3, 0.05, 3, 100)["verdict"] == "indeterminate"
    print("self-test OK")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--days", type=int, default=1460)
    ap.add_argument("--sma-days", default="20,50,100,200")
    ap.add_argument("--vol-windows", default="30")
    ap.add_argument("--vol-q", type=float, default=0.7)
    ap.add_argument("--draws", type=int, default=300)
    ap.add_argument("--delta-min", type=float, default=0.25, help="min net-R gain vs G0 (sum of daily fractional returns)")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--min-years", type=int, default=3)
    ap.add_argument("--n-floor", type=int, default=39)
    ap.add_argument("--rebalance-days", type=int, default=7)
    ap.add_argument("--formation-days", type=int, default=28)
    ap.add_argument("--fee-multiplier", type=float, default=1.0)
    ap.add_argument("--out", default="out/xsec_gate")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _selftest()
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        v = run(a)
    except Exception as exc:  # allow-silent: landed as producer_failed with the reason in verdict.json
        v = {"verdict": "not_applicable", "read_state": "producer_failed", "population": "xsec gate arms", "n": None,
             "note": f"{type(exc).__name__}: {exc}"}
    (out / "verdict.json").write_text(json.dumps(v, indent=1, default=str))
    if v.get("measurement", {}).get("arms"):
        (out / "arms.json").write_text(json.dumps(v["measurement"]["arms"], indent=1, default=str))
    print(json.dumps({k: v.get(k) for k in ("verdict", "read_state", "note", "n")}, default=str))
    return 0 if v["read_state"] in ("measured", "no_data") else 2


if __name__ == "__main__":
    sys.exit(main())
