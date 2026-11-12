#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-cdb2-01.yaml via .github/workflows/research-script-run.yml
"""SLV-ITERATION (a): fixed-parameter, full-history Stage-0 test of slv_trend_1h on RTH 1h bars.

WHY (lane SLV-ITERATION, 2026-11-12). slv_trend_1h went to real money on 2026-11-12 on the
operator's decision. Its promotion record covers 2025-04..2026-09 (n 68). This driver measures the
SAME parameters, fixed, over 2019-01..2026-10 on bars restricted to the US cash session, and grades
the per-trade mean against the rule registered in the unit BEFORE the run (RULE-RQ-20261112-cdb2-01).

WHAT IT DOES, in order
  1. Fetches Dukascopy 1h bars for each declared source (``--source LABEL=INSTRUMENT``), e.g.
     ``XAG=INSTRUMENT_FX_METALS_XAG_USD`` (spot silver, the SLV proxy) and
     ``CFD=INSTRUMENT_ETF_CFD_US_SLV_US_USD`` (the SLV CFD).
  2. Keeps only RTH bars: weekdays, bars whose START hour is in 13..19 UTC in Apr-Oct and 14..20 UTC
     otherwise. Those are the clock-aligned hourly bars that overlap the 13:30/14:30-20:00/21:00 UTC cash
     session. The DST months are the approximation ``src.runtime.market_hours`` uses. US holidays are
     NOT removed: spot silver trades on them and SLV does not.
  3. Runs ``exit_lever_ablation.py --grade stage0 --data-csv`` per source. Every arm goes through the
     committed-record argv builder, so the cost stack is the one the harness resolves for an Alpaca
     equity (fee 0 + 5 bps RT slippage + 0 funding). Each arm is printed with its fingerprint.
  4. Over the PRIMARY arm's trades, computes n, the mean net R/trade, a two-sided 95% t-interval, a trade
     bootstrap 95% interval (descriptive), 4 calendar folds, by-year and by-direction. Then it applies the
     registered rule, writing ``<out>/verdict.json`` (script_run contract) with one record per source.

Thresholds come from the unit's flags, never from defaults chosen here. Tier-1 research tooling: it
writes only under ``--out``, edits no config and places no order.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "scripts" / "ops"), str(REPO / "scripts" / "research"), str(REPO / "scripts")]

FULL_DST_MONTHS = {4, 5, 6, 7, 8, 9, 10}
# t quantile, two-sided 95%; the normal value is used for df > 120 (n here is in the hundreds)
Z975 = 1.959964


def rth_keep(ts: datetime) -> bool:
    if ts.weekday() >= 5:
        return False
    lo, hi = (13, 19) if ts.month in FULL_DST_MONTHS else (14, 20)
    return lo <= ts.hour <= hi


def fetch_rth_csv(instrument: str, start: str, end: str, path: Path) -> dict[str, Any]:
    import dukascopy_python.instruments as I
    from fetch_dukascopy_ohlcv import fetch

    if not hasattr(I, instrument):
        near = sorted(n for n in dir(I) if instrument.split("_")[-2] in n) if "_" in instrument else []
        raise SystemExit(f"unknown dukascopy instrument {instrument!r}; near matches: {near[:10]}")
    s = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    df = fetch(instrument, s, e, "1h")
    if df.empty:
        raise SystemExit(f"no data for {instrument} {start}..{end}")
    n_all = len(df)
    df = df[df["timestamp"].map(lambda t: rth_keep(t.to_pydatetime()))].reset_index(drop=True)
    df.to_csv(path, index=False)
    return {"instrument": instrument, "bars_fetched": n_all, "bars_rth": len(df),
            "first": str(df["timestamp"].iloc[0]), "last": str(df["timestamp"].iloc[-1])}


def load_trades(p: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def stats(rs: list[float], *, boot: int, seed: int) -> dict[str, Any]:
    n = len(rs)
    if n < 2:
        return {"n": n}
    mean = sum(rs) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1))
    se = sd / math.sqrt(n)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(rs, k=n)) / n for _ in range(boot))
    return {"n": n, "net_total_r": round(sum(rs), 4), "mean_r": round(mean, 4), "sd_r": round(sd, 4),
            "se_r": round(se, 4), "t": round(mean / se, 3) if se else None,
            "ci95_t": [round(mean - Z975 * se, 4), round(mean + Z975 * se, 4)],
            "ci95_boot": [round(means[int(0.025 * boot)], 4), round(means[int(0.975 * boot) - 1], 4)],
            "boot": {"resamples": boot, "seed": seed, "unit": "trade (iid; ignores serial dependence)"},
            "mde_r_at_n_one_sided_a05_p80": round(2.486 * se, 4)}


def ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def folds(trades: list[dict[str, Any]], lo: datetime, hi: datetime, k: int) -> list[dict[str, Any]]:
    step = (hi - lo) / k
    out = []
    for i in range(k):
        a, b = lo + step * i, lo + step * (i + 1)
        rs = [float(t["net_r"]) for t in trades if a <= ts(t["entry_time"]) < b or (i == k - 1 and ts(t["entry_time"]) == b)]
        out.append({"fold": i + 1, "start": str(a), "end": str(b), "n": len(rs), "net_r": round(sum(rs), 4)})
    return out


def grade(st: dict[str, Any], fl: list[dict[str, Any]], *, n_floor: int, fold_majority: int) -> dict[str, Any]:
    pos = sum(1 for f in fl if f["net_r"] > 0)
    if st.get("n", 0) < n_floor:
        return {"verdict": "indeterminate", "label": "underpowered", "folds_positive": pos,
                "why": f"n={st.get('n')} < n_floor {n_floor}"}
    if st["mean_r"] <= 0:
        return {"verdict": "fail", "label": "no_edge", "folds_positive": pos,
                "why": f"mean {st['mean_r']} R/trade <= 0 at n={st['n']}"}
    if st["ci95_t"][0] > 0 and pos >= fold_majority:
        return {"verdict": "pass", "label": "edge_confirmed", "folds_positive": pos,
                "why": f"mean {st['mean_r']} R, 95% CI lower {st['ci95_t'][0]} > 0, {pos}/{len(fl)} folds positive"}
    return {"verdict": "indeterminate", "label": "positive_unresolved", "folds_positive": pos,
            "why": f"mean {st['mean_r']} R > 0 but CI lower {st['ci95_t'][0]} <= 0 or folds {pos}/{len(fl)} < {fold_majority}"}


def breakdown(trades: list[dict[str, Any]], key) -> dict[str, Any]:
    out: dict[str, dict[str, float]] = {}
    for t in trades:
        k = str(key(t))
        d = out.setdefault(k, {"n": 0, "net_r": 0.0})
        d["n"] += 1
        d["net_r"] = round(d["net_r"] + float(t["net_r"]), 4)
    return dict(sorted(out.items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", default="slv_trend_1h")
    ap.add_argument("--source", action="append", required=True, help="LABEL=DUKASCOPY_INSTRUMENT; the first is PRIMARY")
    ap.add_argument("--arm", action="append", required=True,
                    help="LABEL=tok;tok forwarded to exit_lever_ablation; the first is graded")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--n-floor", type=int, required=True)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--fold-majority", type=int, required=True)
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20261112)
    ap.add_argument("--research-unit", default=None)
    ap.add_argument("--data-dir", default=None, help="reuse <dir>/<LABEL>.csv instead of fetching (tests)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    primary_arm = a.arm[0].split("=", 1)[0]
    lo, hi = ts(a.start + "T00:00:00+00:00"), ts(a.end + "T00:00:00+00:00")

    records, meta = [], {}
    for k, spec in enumerate(a.source):
        label, _, inst = spec.partition("=")
        csv = (Path(a.data_dir) / f"{label}.csv") if a.data_dir else out / f"{label}__rth_1h.csv"
        try:
            meta[label] = {"instrument": inst, "csv": csv.name} if a.data_dir else fetch_rth_csv(inst, a.start, a.end, csv)
        except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- recorded as a producer failure
            meta[label] = {"instrument": inst, "error": str(exc)}
            records.append({"verdict": "indeterminate", "read_state": "producer_failed", "population": f"{a.leg} {label}",
                            "n": 0, "note": f"fetch failed: {exc}", "measurement": {"source": label}})
            continue
        abl = out / f"ablation_{label}"
        cmd = [sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", a.leg,
               "--data-csv", str(csv), "--start", a.start, "--end", a.end + " 00:00", "--grade", "stage0",
               "--baseline", primary_arm, "--delta-r", "0", "--folds", str(a.folds),
               "--fold-majority", str(a.fold_majority), "--n-floor", str(a.n_floor), "--out", str(abl)]
        for arm in a.arm:
            cmd += ["--arm", arm]
        rc = subprocess.run(cmd, cwd=str(REPO)).returncode
        tp = abl / "arms" / f"{primary_arm}__trades.jsonl"
        if rc != 0 or not tp.exists():
            records.append({"verdict": "indeterminate", "read_state": "producer_failed", "population": f"{a.leg} {label}",
                            "n": 0, "note": f"exit_lever_ablation rc={rc}", "measurement": {"source": label}})
            continue
        arms = {}
        for arm in a.arm:
            al = arm.split("=", 1)[0]
            tr = load_trades(abl / "arms" / f"{al}__trades.jsonl")
            arms[al] = {"spec": arm, **stats([float(t["net_r"]) for t in tr], boot=a.boot, seed=a.seed)}
        trades = load_trades(tp)
        st = stats([float(t["net_r"]) for t in trades], boot=a.boot, seed=a.seed)
        fl = folds(trades, lo, hi, a.folds)
        g = grade(st, fl, n_floor=a.n_floor, fold_majority=a.fold_majority)
        role = "primary" if k == 0 else "corroboration"
        records.append({
            "verdict": g["verdict"], "read_state": "measured", "population": f"{a.leg} {primary_arm} on {label} RTH 1h "
            f"{a.start}..{a.end}, every trade the harness closed", "n": st["n"],
            "measurement": {"role": role, "source": label, "grade": g, "stats": st, "folds": fl,
                            "by_year": breakdown(trades, lambda t: str(t["entry_time"])[:4]),
                            "by_direction": breakdown(trades, lambda t: t.get("direction")),
                            "by_exit_reason": breakdown(trades, lambda t: t.get("exit_reason")),
                            "arms": arms, "data": meta[label]},
            "note": f"{role.upper()} {label}: {g['verdict'].upper()} / {g['label']}: {g['why']}"})

    prim = records[0] if records else {"verdict": "indeterminate", "read_state": "producer_failed"}
    verdict = {"verdict": prim["verdict"], "read_state": prim["read_state"],
               "population": prim.get("population", a.leg), "n": prim.get("n", 0),
               "measurement": {"research_unit": a.research_unit, "rule_applied_to": "primary record only",
                               "data": meta}, "note": prim.get("note", ""), "records": records}
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict["verdict"], "notes": [r.get("note") for r in records]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
