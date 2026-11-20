"""Venue gap (PI-20261120-7ITMUEB1-0005, manager 02:22Z): each live crypto leg's Stage-0 evidence argv run on the
trainer's BYBIT file vs the Binance-vision USD-M native feed, same window, both aggregated OPEN-stamped to the leg's
timeframe (so the harness `--resample <tf>` is an identity on both sides). Usage:
  python3 venue_gap.py --main /home/ubuntu/ict-trading-bot --bn-dir /tmp/vg/bn --work /tmp/vg --legs a,b,c --start S --end E
Binance native files must already be in --bn-dir as <SYM>_<tf>.csv (fetched by the caller)."""
import argparse, json, os, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd
import yaml

sys.path[:0] = ["scripts/research", "."]
import regime_debt_matrix as rdm  # noqa: E402
from m20_fleet_exit_sweep import resolve_data  # noqa: E402

RULE = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1D"}


def to_tf(src: str, tf: str, out: Path, start: str, end: str) -> tuple:
    d = pd.read_csv(src)
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    d = d.dropna(subset=["timestamp"]).sort_values("timestamp")
    d = d[(d.timestamp >= pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=60)) & (d.timestamp <= pd.Timestamp(end, tz="UTC"))]
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in d.columns:
        agg["volume"] = "sum"
    g = d.set_index("timestamp").resample(RULE[tf], label="left", closed="left").agg(agg).dropna(subset=["close"]).reset_index()
    g.to_csv(out, index=False)
    return (str(g.timestamp.min()) if len(g) else None, str(g.timestamp.max()) if len(g) else None, len(g))


def run(name, cfg, h, csv, tf, tag, work: Path, start, end, timeout):
    emit, jout = work / f"{tag}.jsonl", work / f"{tag}.json"
    for p in (emit, jout):
        if p.exists():
            p.unlink()
    argv, faithful, omitted = rdm.build_harness_cmd(name, cfg, h, str(csv), tf, str(emit), str(jout))
    argv = argv + ["--start", start, "--end", end]
    env = {k: v for k, v in os.environ.items() if k != "BACKTEST_DATA_PATH"}
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
        rc, err = p.returncode, (p.stderr or "")[-300:]
    except subprocess.TimeoutExpired:
        return {"rc": "timeout", "rows": []}
    rows = [json.loads(l) for l in open(emit)] if emit.exists() else []
    return {"rc": rc, "err": err if rc else "", "rows": rows, "faithful": faithful, "omitted": omitted}


def key(x):
    t = pd.Timestamp(x.get("entry_time"))
    t = t.tz_convert("UTC") if t.tzinfo else t.tz_localize("UTC")
    return (str(x.get("direction") or x.get("side")), t.isoformat())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", required=True)
    ap.add_argument("--bn-dir", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--legs", required=True)
    ap.add_argument("--start", default="2023-02-01")
    ap.add_argument("--end", default="2026-11-15")
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    S = yaml.safe_load(open("config/strategies.yaml"))["strategies"]
    A = yaml.safe_load(open("config/accounts.yaml"))
    A = A.get("accounts", A)
    real = set(A.get("bybit_2", {}).get("strategies") or [])
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    results = []
    for leg in a.legs.split(","):
        cfg = S[leg]
        sym, tf = cfg["symbols"][0], str(cfg["timeframe"])
        h = rdm.classify(cfg)
        rec = {"leg": leg, "symbol": sym, "tf": tf, "real_money": leg in real, "harness": h}
        by_path, _proxy, by_rs = resolve_data(sym, tf, Path(a.main) / "data")
        bn_src = Path(a.bn_dir) / f"{sym}_{tf}.csv"
        if not by_path or not bn_src.exists() or h is None:
            rec["state"] = f"skipped: bybit={by_path} binance={bn_src.exists()} harness={h}"
            results.append(rec); print(json.dumps(rec)); continue
        by_csv, bn_csv = work / f"{leg}__bybit.csv", work / f"{leg}__binance.csv"
        rec["bybit_source"] = Path(by_path).name
        rec["bybit_span"] = to_tf(by_path, tf, by_csv, a.start, a.end)
        rec["binance_span"] = to_tf(str(bn_src), tf, bn_csv, a.start, a.end)
        lo = max(pd.Timestamp(rec["bybit_span"][0]), pd.Timestamp(rec["binance_span"][0]), pd.Timestamp(a.start, tz="UTC"))
        hi = min(pd.Timestamp(rec["bybit_span"][1]), pd.Timestamp(rec["binance_span"][1]), pd.Timestamp(a.end, tz="UTC"))
        start, end = str(lo.date()), str(hi.date())
        rec["window"] = [start, end]
        B = run(leg, cfg, h, bn_csv, tf, f"{leg}__bn", work, start, end, a.timeout)
        Y = run(leg, cfg, h, by_csv, tf, f"{leg}__by", work, start, end, a.timeout)
        rec["rc"] = [B["rc"], Y["rc"]]
        if B.get("err") or Y.get("err"):
            rec["err"] = [B.get("err", ""), Y.get("err", "")]
        rb = [x["net_r"] for x in B["rows"] if x.get("net_r") is not None]
        ry = [x["net_r"] for x in Y["rows"] if x.get("net_r") is not None]
        kb = {key(x): x for x in B["rows"] if x.get("net_r") is not None}
        ky = {key(x): x for x in Y["rows"] if x.get("net_r") is not None}
        both = set(kb) & set(ky)
        rec.update({"n_binance": len(rb), "n_bybit": len(ry),
                    "sum_r_binance": round(float(np.sum(rb)), 3) if rb else 0.0,
                    "sum_r_bybit": round(float(np.sum(ry)), 3) if ry else 0.0,
                    "matched": len(both),
                    "match_rate": round(len(both) / max(len(rb), 1), 3),
                    "matched_dr_median": round(float(np.median([ky[k]["net_r"] - kb[k]["net_r"] for k in both])), 4) if both else None})
        n = max(len(rb), 1)
        rec["dr_per_trade"] = round((rec["sum_r_bybit"] - rec["sum_r_binance"]) / n, 4) if rb else None
        rec["state"] = "measured" if (B["rc"] == 0 and Y["rc"] == 0) else "producer_failed"
        results.append(rec)
        print(json.dumps({k: v for k, v in rec.items() if k not in ("err",)}), flush=True)
    meas = [r for r in results if r.get("state") == "measured" and r.get("n_binance", 0) >= 20 and r.get("dr_per_trade") is not None]
    d = np.array([r["dr_per_trade"] for r in meas])
    summ = {"population": f"{len(meas)} legs measured with n_binance >= 20 (of {len(results)} requested)"}
    if len(d):
        from math import comb
        neg, pos = int((d < 0).sum()), int((d > 0).sum())
        m = neg + pos
        p_two = min(1.0, 2 * sum(comb(m, k) for k in range(0, min(neg, pos) + 1)) / 2 ** m) if m else None
        rng = np.random.default_rng(42)
        boots = [rng.choice(d, len(d), replace=True).mean() for _ in range(10000)]
        summ.update({"legs_bybit_worse": neg, "legs_bybit_better": pos, "sign_test_p_two_sided": p_two,
                     "mean_dr_per_trade": round(float(d.mean()), 4), "median_dr_per_trade": round(float(np.median(d)), 4),
                     "bootstrap95_mean_dr_per_trade": [round(float(np.quantile(boots, .025)), 4), round(float(np.quantile(boots, .975)), 4)],
                     "real_money_legs": [{k: r.get(k) for k in ("leg", "n_binance", "n_bybit", "sum_r_binance", "sum_r_bybit", "dr_per_trade", "match_rate")} for r in meas if r["real_money"]]})
    print("SUMMARY " + json.dumps(summ))
    json.dump({"legs": results, "summary": summ}, open(a.out, "w"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
