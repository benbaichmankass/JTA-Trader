#!/usr/bin/env python3
# wiring: research/queue unit RQ-20261120-mgc-ib-feed (PI-20261120-FILLW47B-0014) via research-script-run-trainer.yml; no schedule consumes it.
"""Is the Dukascopy XAU_USD spot proxy adequate for ict_scalp_mgc_15m? Measured against the leg's OWN IB bars.

WHY. ``ict_scalp_mgc_15m`` (testing, ib_paper) reads net R -176.10 over n 526 on a Dukascopy XAU_USD 15m corpus, 2019..2026
(RQ-20261117-9e1c-12, RQ-20261118-abab-28/-29). ``scripts/ops/dukascopy_instruments.py`` adjudicates that series REL_PROXY for the
CME micro-gold future the leg trades (no roll, spot session calendar, a level basis). A retirement input must rest on the leg's own
bars (manager 2026-11-20 07:43Z), so this driver, run ON THE TRAINER where the IB shards are resident, does two things on the span the
IB bars cover:

 1. FEED  - build 15m bars from the IB MGC 5m series (open-stamped, complete 3-bar bins only), fetch the Dukascopy XAU_USD 15m series
            for the same dates, and report: common / one-side-only bars, 15m log-return correlation, p99 |return difference| in bps,
            level basis (IB / spot - 1) median and DRIFT (last 20 days minus first 20 days, in bps).
 2. REPLAY - run the incumbent arm A (``exit_lever_ablation.py --leg ict_scalp_mgc_15m --arm A= --grade stage0``) on EACH corpus over the
            SAME window, net of the harness's full cost stack, and compare n, net R, net R per trade and the share of IB trades that
            have a Dukascopy trade (same direction, entry within one 15m bar).

THE RULE (registered BEFORE any run; every threshold is a flag whose default IS the registered value)
  INDETERMINATE if the IB bars are missing or hold n(A) < --n-floor (39) trades on the overlap window, or the Dukascopy fetch fails.
  PROXY_ADEQUATE (verdict pass) iff ALL of:
    (F1) 15m return correlation >= --min-corr (0.985);
    (F2) p99 |15m return difference| <= --max-p99-bps (8.0);
    (R1) sign(net R IB) == sign(net R Dukascopy) for arm A on the same window;
    (R2) |net R per trade (IB) - net R per trade (Dukascopy)| <= --max-pertrade-r (0.05);
    (R3) >= --min-match (0.70) of IB trades have a matching Dukascopy trade.
  PROXY_INADEQUATE (verdict fail) otherwise, at n(A) >= 39.
  WHY THESE BARS: 0.05 R per trade is the size of the lever effects the proxy has been used to read (AX40 +0.058, S_LATE +0.029,
  LONG +0.204 R per trade on the Dukascopy corpus), so a proxy bias below it cannot by itself manufacture those effects; the leg's live
  stop is 0.26-0.40% of price, so a p99 15m return gap of 8 bps is at most about a third of a stop. DISCLOSURE: the thresholds were
  fixed after the Dukascopy A-arm numbers above and after a feed check of Dukascopy against the only committed MGC 15m futures file
  (a Yahoo-style series, 54 days: return correlation 0.9929, p99 4.74 bps, basis median +87.7 bps wandering 52-121); no IB result was read.
  Level basis and its drift are REPORTED, not gated: R is measured on the leg's own stop distance, not on price level.

Changes no config, places no order, proposes nothing; writes only under --out.

    python3 scripts/research/mgc_feed_adequacy.py --self-test
"""
from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]

#: Where the IB MGC 5m shard may live on the trainer, tried in order; the first that exists is used and PRINTED.
IB_CANDIDATES = (
    "data/ibkr_datasets/market_raw/MGC/5m/*/data.jsonl",
    "/home/ubuntu/trainer-data/ibkr_datasets/market_raw/MGC/5m/*/data.jsonl",
    "/home/ubuntu/m27_data/MGC_5m.csv",
)
LEG = "ict_scalp_mgc_15m"


def find_ib_source(candidates: Sequence[str] = IB_CANDIDATES) -> Tuple[Optional[str], List[str]]:
    """First candidate that exists (the highest version dir wins within a glob). Prints the pick; returns the tried list too."""
    tried: List[str] = []
    for pat in candidates:
        hits = sorted(glob.glob(pat))
        tried.append(f"{pat} -> {len(hits)} file(s)")
        if hits:
            print(f"IB source: {hits[-1]} (of {len(hits)} matching {pat})", file=sys.stderr)
            return hits[-1], tried
    return None, tried


def load_ib_5m(path: str) -> pd.DataFrame:
    """IB 5m bars as a UTC-indexed frame: JSONL rows {ts,open,high,low,close,volume} or a CSV with a timestamp column."""
    if path.endswith(".jsonl"):
        rows = [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
        df = pd.DataFrame(rows).rename(columns={"ts": "timestamp"})
    else:
        df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed")
    return df.drop_duplicates("timestamp").set_index("timestamp").sort_index()[["open", "high", "low", "close", "volume"]]


def to_15m(df5: pd.DataFrame) -> pd.DataFrame:
    """Open-stamped 15m bars from 5m bars; only COMPLETE bins (3 sub-bars) are kept, so a partial bin never becomes a bar."""
    g = df5.resample("15min", label="left", closed="left")
    out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    out["n"] = g["close"].count()
    return out[out["n"] == 3].drop(columns="n").dropna()


def feed_metrics(ib15: pd.DataFrame, duka15: pd.DataFrame, edge_days: int = 20) -> Dict[str, Any]:
    """Agreement of the two 15m series on their overlap. A null means 'could not look' (never 0)."""
    lo, hi = max(ib15.index.min(), duka15.index.min()), min(ib15.index.max(), duka15.index.max())
    a, b = ib15[lo:hi], duka15[lo:hi]
    j = a[["close"]].join(b[["close"]], lsuffix="_ib", rsuffix="_dk", how="inner")
    out: Dict[str, Any] = {"overlap": [str(lo), str(hi)], "bars_ib": int(len(a)), "bars_duka": int(len(b)), "common": int(len(j)),
                           "only_ib": int(len(a) - len(j)), "only_duka": int(len(b) - len(j))}
    if len(j) < 100:
        out.update(corr=None, p99_bps=None, median_bps=None, basis_median_bps=None, basis_drift_bps=None)
        return out
    r_ib, r_dk = np.log(j.close_ib).diff(), np.log(j.close_dk).diff()
    d = ((r_ib - r_dk).abs() * 1e4).dropna()
    basis = (j.close_ib / j.close_dk - 1) * 1e4
    daily = basis.groupby(basis.index.date).mean()
    k = min(edge_days, max(1, len(daily) // 2))
    out.update(corr=float(r_ib.corr(r_dk)), p99_bps=float(d.quantile(0.99)), median_bps=float(d.median()),
               basis_median_bps=float(basis.median()), basis_drift_bps=float(daily.iloc[-k:].mean() - daily.iloc[:k].mean()),
               basis_p5_bps=float(basis.quantile(0.05)), basis_p95_bps=float(basis.quantile(0.95)))
    return out


def _bar(ts: Any) -> pd.Timestamp:
    return pd.Timestamp(ts).tz_convert("UTC").floor("15min") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts, tz="UTC").floor("15min")


def replay_metrics(ib_trades: List[Dict[str, Any]], dk_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """n, net R, per-trade R on each corpus and the share of IB trades with a same-direction Dukascopy trade within one 15m bar."""
    def stat(t: List[Dict[str, Any]]) -> Tuple[int, float, Optional[float]]:
        n = len(t)
        net = float(sum(float(x["net_r"]) for x in t))
        return n, net, (net / n if n else None)
    n_ib, net_ib, pt_ib = stat(ib_trades)
    n_dk, net_dk, pt_dk = stat(dk_trades)
    dk_keys = {(x["direction"], _bar(x["entry_time"])) for x in dk_trades}
    step = pd.Timedelta(minutes=15)
    matched = sum(1 for x in ib_trades if any((x["direction"], _bar(x["entry_time"]) + k * step) in dk_keys for k in (-1, 0, 1)))
    return {"n_ib": n_ib, "n_duka": n_dk, "net_r_ib": net_ib, "net_r_duka": net_dk, "per_trade_ib": pt_ib, "per_trade_duka": pt_dk,
            "match_share": (matched / n_ib) if n_ib else None, "matched": matched}


def grade(feed: Dict[str, Any], rep: Dict[str, Any], *, min_corr: float, max_p99_bps: float, max_pertrade_r: float,
          min_match: float, n_floor: int) -> Dict[str, Any]:
    """The registered rule. INDETERMINATE when n(A) < floor or a needed number is missing; never a pass on a null."""
    m: Dict[str, Any] = {"feed": feed, "replay": rep}
    if rep["n_ib"] < n_floor:
        m.update(verdict="indeterminate", conditions={}, note=f"INDETERMINATE: n(A) on the IB bars = {rep['n_ib']} < {n_floor} over the overlap window")
        return m
    if feed.get("corr") is None or rep["per_trade_duka"] is None or rep["match_share"] is None:
        m.update(verdict="indeterminate", conditions={}, note="INDETERMINATE: a needed measurement is missing (too little overlap or no Dukascopy trades)")
        return m
    c = {
        "F1_corr": feed["corr"] >= min_corr,
        "F2_p99": feed["p99_bps"] <= max_p99_bps,
        "R1_sign": (rep["net_r_ib"] > 0) == (rep["net_r_duka"] > 0),
        "R2_per_trade": abs(rep["per_trade_ib"] - rep["per_trade_duka"]) <= max_pertrade_r,
        "R3_match": rep["match_share"] >= min_match,
    }
    ok = all(c.values())
    m.update(verdict="pass" if ok else "fail", conditions=c, label="PROXY_ADEQUATE" if ok else "PROXY_INADEQUATE")
    m["note"] = (
        f"{m['label']}: corr {feed['corr']:.4f}, p99 {feed['p99_bps']:.2f} bps, basis median {feed['basis_median_bps']:.1f} bps "
        f"(drift {feed['basis_drift_bps']:+.1f}); A on the same window: IB n {rep['n_ib']} net {rep['net_r_ib']:+.2f} R ({rep['per_trade_ib']:+.4f}/trade) "
        f"vs Dukascopy n {rep['n_duka']} net {rep['net_r_duka']:+.2f} R ({rep['per_trade_duka']:+.4f}/trade); IB trades matched {rep['match_share']:.0%}; "
        f"failed: {[k for k, v in c.items() if not v] or 'none'}"
    )
    return m


def read_trades(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def run_arm_a(csv: Path, start: str, end: str, out: Path) -> Tuple[int, List[Dict[str, Any]]]:
    """Arm A of the leg on one candle CSV through the standard harness (stage0 grade is the single-arm form)."""
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", LEG, "--arm", "A=", "--data-csv", str(csv),
           "--start", start, "--end", end, "--grade", "stage0", "--baseline", "A", "--delta-r", "0", "--folds", "4",
           "--fold-majority", "1", "--n-floor", "25", "--out", str(out)]
    rc = subprocess.run(cmd, cwd=str(REPO)).returncode
    tf = out / "arms" / "A__trades.jsonl"
    return rc, (read_trades(tf) if rc == 0 and tf.exists() else [])


def fetch_duka(days: int, dest: Path) -> int:
    cmd = [sys.executable, str(REPO / "scripts/ops/fetch_backtest_candles.py"), "--symbol", "MGC", "--interval", "15", "--days", str(days),
           "--source", "dukascopy", "--output", str(dest)]
    return subprocess.run(cmd, cwd=str(REPO)).returncode


def _write(out: Path, rec: Dict[str, Any]) -> None:
    (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")


def run(a: argparse.Namespace, *, source: Optional[Callable[[], Tuple[Optional[str], List[str]]]] = None) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    thr = dict(min_corr=a.min_corr, max_p99_bps=a.max_p99_bps, max_pertrade_r=a.max_pertrade_r, min_match=a.min_match, n_floor=a.n_floor)

    def fail(note: str, **extra: Any) -> int:
        _write(out, {"verdict": "indeterminate", "read_state": "unmeasured", "n": 0, "population": f"{LEG} IB-vs-Dukascopy feed adequacy: {note}",
                     "measurement": extra, "note": note, "decision_rule_id": a.rule_id})
        return 0

    path, tried = (source or find_ib_source)()
    if not path:
        return fail("no IB MGC 5m source found on this host", tried=tried)
    ib15 = to_15m(load_ib_5m(path))
    if len(ib15) < 500:
        return fail(f"IB MGC 15m series too short ({len(ib15)} complete bars)", ib_source=path)
    ib_csv = out / "ib_MGC_15m.csv"
    ib15.reset_index().rename(columns={"index": "timestamp"}).to_csv(ib_csv, index=False)
    days = (pd.Timestamp.now(tz="UTC") - ib15.index.min()).days + 5
    dk_csv = out / "duka_MGC_15m.csv"
    if fetch_duka(days, dk_csv) != 0 or not dk_csv.exists():
        return fail("Dukascopy XAU_USD 15m fetch failed", ib_source=path)
    dk = pd.read_csv(dk_csv)
    dk["timestamp"] = pd.to_datetime(dk["timestamp"], utc=True, format="mixed")
    dk15 = dk.drop_duplicates("timestamp").set_index("timestamp").sort_index()
    feed = feed_metrics(ib15, dk15)
    lo, hi = feed["overlap"]
    win = (str(pd.Timestamp(lo).date()), f"{pd.Timestamp(hi).date()} 23:59")
    rc_ib, t_ib = run_arm_a(ib_csv, win[0], win[1], out / "ib")
    rc_dk, t_dk = run_arm_a(dk_csv, win[0], win[1], out / "duka")
    if rc_ib != 0 or rc_dk != 0:
        return fail(f"arm A exited rc ib={rc_ib} duka={rc_dk}", ib_source=path, feed=feed)
    m = grade(feed, replay_metrics(t_ib, t_dk), **thr)
    arms = out / "arms"
    arms.mkdir(exist_ok=True)
    for label, t in (("A_IB", t_ib), ("A_DUKA", t_dk)):
        (arms / f"{label}__trades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in t), encoding="utf-8")
    rec = {"verdict": m["verdict"], "read_state": "measured", "n": m["replay"]["n_ib"],
           "population": f"{LEG} {win[0]}..{win[1]}: {m['replay']['n_ib']} IB trades vs {m['replay']['n_duka']} Dukascopy XAU_USD trades, arm A, "
                         f"net of the harness's full cost stack; IB source {path}",
           "measurement": {**m, "window": list(win), "ib_source": path, "thresholds": thr}, "note": m["note"], "decision_rule_id": a.rule_id}
    _write(out, rec)
    print(json.dumps({"verdict": rec["verdict"], "note": rec["note"]}, indent=1))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out")
    p.add_argument("--min-corr", type=float, default=0.985)
    p.add_argument("--max-p99-bps", type=float, default=8.0)
    p.add_argument("--max-pertrade-r", type=float, default=0.05)
    p.add_argument("--min-match", type=float, default=0.70)
    p.add_argument("--n-floor", type=int, default=39)
    p.add_argument("--rule-id", default=None)
    p.add_argument("--research-unit", default=None)
    a = p.parse_args(argv)
    if a.self_test:
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_mgc_feed_adequacy.py"], cwd=str(REPO)).returncode
    if not a.out:
        p.error("--out is required")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
