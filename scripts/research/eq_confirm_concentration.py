#!/usr/bin/env python3
# wiring: research/queue/RQ-20261126-7c11-03.yaml (row ML-ENTRY-EQ-CORP-EVENTS; manager 2026-11-26 10:20Z)
"""Month / regime decomposition of ml_entry_eq confirm-window trades: is the edge spread over time or one month's?

RQ-20261126-7c11-02 PASSED on iid t 4.87 but its month-clustered t is ~0.97: 113 of 213 trades fall in 2026-03. The served
artifact (98e3-06, n 207) reads month-clustered t ~2.06. This reads, per model, from its per-trade file (one JSON row per
trade: symbol, ts, net_r):

* by month: n, mean, sum net R; the month-clustered t (sum of monthly sums / its sd across months);
* leave-largest-month-out: the mean net R with the month carrying the largest positive SUM removed;
* by regime cell (reported, never graded): SPY daily close vs its 50-day SMA (trend up/down) x SPY 20-day realized vol
  vs the window median (vol high/low), read before the entry day from Alpaca 1Day SPY bars;
* top-5 symbol share of total net R.

Rule (per model, registered in the unit): ROBUST iff leave-largest-month-out mean > 0 AND month-clustered t >= 1.3;
CONCENTRATED otherwise. The run verdict is pass iff the SERVED model reads ROBUST (it is the one a widening would scale);
the security-keyed model is reported beside it. Read-only; writes only under --out.

    python3 scripts/research/eq_confirm_concentration.py --self-test
    python3 scripts/research/eq_confirm_concentration.py --trades served=PATH --trades seckey=PATH --gate served --out DIR
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

CLUSTER_T_MIN = 1.3


def _load(path: str) -> List[Dict[str, Any]]:
    rows = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            rows.append({"symbol": str(r["symbol"]), "ts": str(r["ts"]), "net_r": float(r["net_r"])})
    return rows


def month_of(ts: str) -> str:
    return ts[:7]


def decompose(trades: List[Dict[str, Any]], regime_of=None) -> Dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"n": 0, "state": "no_trades"}
    by_m: Dict[str, List[float]] = {}
    for t in trades:
        by_m.setdefault(month_of(t["ts"]), []).append(t["net_r"])
    sums = {m: sum(v) for m, v in by_m.items()}
    k = len(sums)
    total = sum(sums.values())
    clustered_t = None
    if k >= 3:
        sd = statistics.stdev(sums.values())
        clustered_t = (total / k) / (sd / math.sqrt(k)) if sd > 0 else None
    top_m = max(sums, key=lambda m: sums[m])
    rest = [t["net_r"] for t in trades if month_of(t["ts"]) != top_m]
    lomo = sum(rest) / len(rest) if rest else None
    by_sym: Dict[str, float] = {}
    for t in trades:
        by_sym[t["symbol"]] = by_sym.get(t["symbol"], 0.0) + t["net_r"]
    top5 = sorted(by_sym.values(), reverse=True)[:5]
    regimes = None
    if regime_of is not None:
        regimes = {}
        for t in trades:
            c = regime_of(t["ts"]) or "unknown"
            regimes.setdefault(c, []).append(t["net_r"])
        regimes = {c: {"n": len(v), "mean_net_r": round(sum(v) / len(v), 4)} for c, v in sorted(regimes.items())}
    robust = lomo is not None and lomo > 0 and clustered_t is not None and clustered_t >= CLUSTER_T_MIN
    return {"n": n, "mean_net_r": round(total / n, 4), "months": k,
            "by_month": {m: {"n": len(v), "mean_net_r": round(sum(v) / len(v), 4), "sum_net_r": round(sum(v), 4)}
                         for m, v in sorted(by_m.items())},
            "month_clustered_t": None if clustered_t is None else round(clustered_t, 3),
            "largest_month": top_m, "largest_month_share_of_trades": round(len(by_m[top_m]) / n, 4),
            "leave_largest_month_out_mean": None if lomo is None else round(lomo, 4),
            "top5_symbol_share_of_net": round(sum(top5) / total, 4) if total else None,
            "by_regime": regimes, "robust": robust}


def spy_regime_fn(client) -> Any:
    """SPY 1Day bars -> f(ts) = 'trend_{up|down}/vol_{high|low}', each read from bars strictly before the entry day."""
    import pandas as pd  # noqa: PLC0415
    got = client.bars(["SPY"], "1Day", "2024-09-01T00:00:00Z", "2026-11-26T00:00:00Z").get("SPY", [])
    df = pd.DataFrame(got).rename(columns={"t": "ts", "c": "close"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["sma50"] = df.close.rolling(50).mean()
    df["rv20"] = df.close.pct_change().rolling(20).std()
    med = float(df["rv20"].loc[df.ts >= pd.Timestamp("2025-07-15", tz="UTC")].median())

    def f(ts: str) -> Optional[str]:
        t = pd.Timestamp(ts)
        t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
        prior = df[df.ts < t.normalize()]
        if prior.empty or pd.isna(prior.sma50.iloc[-1]) or pd.isna(prior.rv20.iloc[-1]):
            return None
        last = prior.iloc[-1]
        return f"trend_{'up' if last.close >= last.sma50 else 'down'}/vol_{'high' if last.rv20 >= med else 'low'}"
    return f


def grade(models: Dict[str, Dict[str, Any]], gate: str) -> Dict[str, Any]:
    g = models.get(gate) or {}
    if not g.get("n"):
        return {"verdict": "indeterminate", "read_state": "no_data", "n": None, "note": f"no trades for the gated model {gate!r}"}
    v = "pass" if g["robust"] else "fail"
    parts = [f"{m}: n {d.get('n')}, mean {d.get('mean_net_r')}, month-clustered t {d.get('month_clustered_t')}, "
             f"leave-largest-month ({d.get('largest_month')}, {d.get('largest_month_share_of_trades')} of trades) out mean "
             f"{d.get('leave_largest_month_out_mean')} -> {'ROBUST' if d.get('robust') else 'CONCENTRATED'}"
             for m, d in models.items()]
    return {"verdict": v, "read_state": "measured", "n": int(g["n"]), "note": "; ".join(parts)}


def self_test() -> None:
    even = [{"symbol": f"S{i % 7}", "ts": f"2026-{1 + i % 10:02d}-15 15:00:00+00:00", "net_r": 0.3 + 0.1 * ((i % 3) - 1)}
            for i in range(200)]
    d = decompose(even)
    assert d["robust"] and d["months"] == 10 and d["leave_largest_month_out_mean"] > 0, d
    lumpy = [{"symbol": "A", "ts": "2026-03-10 15:00:00+00:00", "net_r": 1.0} for _ in range(100)] + \
            [{"symbol": "B", "ts": f"2026-{m:02d}-10 15:00:00+00:00", "net_r": -0.2} for m in (1, 2, 4, 5, 6, 7) for _ in range(10)]
    d2 = decompose(lumpy)
    assert not d2["robust"] and d2["largest_month"] == "2026-03" and d2["leave_largest_month_out_mean"] < 0, d2
    g = grade({"served": d, "seckey": d2}, "served")
    assert g["verdict"] == "pass" and "CONCENTRATED" in g["note"]
    assert grade({"served": d2}, "served")["verdict"] == "fail"
    assert decompose(even, regime_of=lambda ts: "trend_up/vol_low")["by_regime"]["trend_up/vol_low"]["n"] == 200
    print("SELF-TEST PASS")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trades", action="append", default=[], help="name=path (one JSON row per trade)")
    ap.add_argument("--gate", default="served")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-regime", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    regime = None
    if not a.no_regime:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from alpaca_readonly import AlpacaReadOnly  # noqa: PLC0415
            regime = spy_regime_fn(AlpacaReadOnly.from_env())
        except Exception as exc:  # noqa: BLE001  # allow-silent: regime cells are reported only; recorded as could-not-look
            print(f"regime unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    models = {}
    for spec in a.trades:
        name, path = spec.split("=", 1)
        models[name] = decompose(_load(path), regime)
    g = grade(models, a.gate)
    pop = ("ml_entry_eq confirm-window trades 2025-07-15..2026-10-31 per model: " +
           ", ".join(f"{m} n={d.get('n')}" for m, d in models.items()) + f"; gated model {a.gate}; regime cells "
           + ("from SPY 1Day (50d SMA x 20d realized vol vs window median)" if regime else "NOT read (could not look)"))
    rows = [{"verdict": g["verdict"] if m == a.gate else ("pass" if d.get("robust") else "fail"),
             "read_state": "measured" if d.get("n") else "no_data", "population": f"{m}: {pop}",
             "n": int(d["n"]) if d.get("n") else None, "measurement": d} for m, d in models.items()]
    v = {**g, "population": pop, "measurement": {"models": models, "cluster_t_min": CLUSTER_T_MIN}, "records": rows}
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n")
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n", "note")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
