#!/usr/bin/env python3
"""ml_entry's VENUE PENALTY, measured: its Stage-0 held-out population re-scored on Bybit bars (VENUE-GAP-20261120 re-test (b)).

WHY. ml_entry trades on Bybit; its Stage-0 evidence (comms/strategy_evidence/ml_entry.json: arm F = the live exit, 907
held-out decisions 2025-10-01..2026-09-30, expectancy 0.0371 R) is scored on Binance-vision USD-M 1h klines. The fleet
venue-gap measurement (comms/research/VENUE-GAP-20261120/record.json) found harness legs earn a trade-weighted 0.0185
R/trade less on the trainer's Bybit bars; ml_entry has no harness argv, so its own penalty was never measured and its
margin (0.0371) is only 2.0x the pooled figure. Manager 2026-11-20 03:52Z: measure it.

METHOD (fixed before the run):
1. ``ml_decision_entry.fetch`` fills the Binance cache (keyless; idempotent), exactly as the evidence run does.
2. BYBIT cache = a copy of it in which, for every universe symbol with a trainer Bybit linear file, every 1h bar at or
   after ``ml_decision_entry.HOLDOUT_START`` is replaced by the Bybit bar (finest trainer file <= 1h, aggregated
   OPEN-stamped). Bars before the holdout stay Binance, so the TP model's training rows (all < the holdout minus purge +
   embargo) and the dev margin are byte-identical in both arms; only the scored window changes venue. Rolling features
   in the first days of the holdout read a mixed lookback (stated). Symbols with no Bybit file stay Binance (listed).
3. ``ml_entry_tp_revision.py evidence-extend-only --structure-sl pivot=5`` (the record's own command) runs twice:
   CONTROL on the Binance cache, BYBIT on the Bybit cache. Arm F (SL-only structure stop + extend-only TP + 24h) is read
   from each run's evidence_extend_only.json.
4. Grade (thresholds are flags, set by the unit):
   INDETERMINATE if CONTROL arm F does not reproduce the record's expectancy_r_oos within --repro-tol, or BYBIT n <
   --n-floor, or a traded symbol has no Bybit file (the penalty would be partly unmeasured).
   PASS iff BYBIT arm F mean net R per decision > --bar; FAIL otherwise.
   penalty = BYBIT mean - CONTROL mean (reported; the per-symbol split too).
Writes ``<out>/verdict.json`` (script_run contract) and both runs' outputs under ``<out>/control`` and ``<out>/bybit``.

Research only (Tier 1). No config write, no record write: a pass or fail is evidence for the manager.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "scripts" / "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RECORD = REPO / "comms" / "strategy_evidence" / "ml_entry.json"


def splice(binance_pkl: Path, bybit_1h, out_pkl: Path, start: str) -> dict[str, Any]:
    """Binance bars before ``start`` + Bybit bars at/after it, in the cache schema (ts UTC, open..volume floats)."""
    import pandas as pd
    a = pd.read_pickle(binance_pkl)
    t0 = pd.Timestamp(start, tz="UTC")
    b = bybit_1h.rename(columns={"timestamp": "ts"})[["ts", "open", "high", "low", "close", "volume"]].copy()
    b["ts"] = pd.to_datetime(b["ts"], utc=True)
    for c in ("open", "high", "low", "close", "volume"):
        b[c] = b[c].astype(float)
    b = b[b.ts >= t0]
    keep = a[a.ts < t0]
    out = pd.concat([keep, b], ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    out_pkl.parent.mkdir(parents=True, exist_ok=True)
    out.to_pickle(out_pkl)
    return {"binance_rows_kept": len(keep), "bybit_rows": len(b),
            "binance_rows_replaced": int((a.ts >= t0).sum()),
            "bybit_first": str(b.ts.min()) if len(b) else None, "bybit_last": str(b.ts.max()) if len(b) else None}


def bybit_hourly(sym: str, data_dir: Path):
    import pandas as pd
    from m20_fleet_exit_sweep import resolve_data

    from scripts.ops.backtest_data_source import resample_open_stamped
    path, _proxy, resample = resolve_data(sym, "1h", data_dir)
    if not path:
        return None, None
    d = pd.read_csv(path)
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    d = d.dropna(subset=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp")
    if "volume" not in d.columns:
        d["volume"] = 0.0
    return resample_open_stamped(d, "1h" if resample else None), Path(path).name


def arm_f(run_dir: Path) -> dict[str, Any] | None:
    p = run_dir / "evidence_extend_only.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    f = d.get("extend_only_structure_sl") or {}
    return {"n": d.get("n"), "mean_net_r": f.get("mean_net_r"), "sum_net_r": f.get("sum_net_r"),
            "per_symbol": f.get("per_symbol"), "fixed_3atr_mean_net_r": (d.get("fixed_3atr") or {}).get("mean_net_r"),
            "population": d.get("population")}


def decide(control: dict | None, bybit: dict | None, *, record_exp: float | None, repro_tol: float,
           n_floor: int, bar: float, missing_traded: list[str]) -> dict[str, Any]:
    m: dict[str, Any] = {"control_arm_f": control, "bybit_arm_f": bybit, "record_expectancy_r_oos": record_exp,
                         "missing_traded_symbols": missing_traded}
    if control is None or bybit is None or control.get("mean_net_r") is None or bybit.get("mean_net_r") is None:
        return {"verdict": "not_applicable", "read_state": "producer_failed", "label": "run_missing", **m}
    m["penalty_r_per_decision"] = round(bybit["mean_net_r"] - control["mean_net_r"], 5)
    ok = record_exp is not None and abs(control["mean_net_r"] - record_exp) <= repro_tol
    m["control_reproduces_record"] = ok
    if not ok:
        return {"verdict": "indeterminate", "read_state": "measured", "label": "control_failed", **m}
    if missing_traded:
        return {"verdict": "indeterminate", "read_state": "measured", "label": "bybit_coverage_incomplete", **m}
    if (bybit.get("n") or 0) < n_floor:
        return {"verdict": "indeterminate", "read_state": "measured", "label": "underpowered", **m}
    if bybit["mean_net_r"] > bar:
        return {"verdict": "pass", "read_state": "measured", "label": "bybit_expectancy_positive", **m}
    return {"verdict": "fail", "read_state": "measured", "label": "bybit_expectancy_not_positive", **m}


def run(a: argparse.Namespace) -> dict[str, Any]:
    import ml_decision_entry as E
    out = Path(a.out)
    bn, by = Path(a.cache), Path(a.work) / "bybit_cache"
    syms = E.universe()
    E.fetch(bn, syms)
    traded = E.traded_symbols()
    if by.exists():
        shutil.rmtree(by)
    by.mkdir(parents=True)
    coverage = {}
    for s in syms:
        src = bn / f"{s}.pkl"
        h, name = bybit_hourly(s, Path(a.data_dir))
        if h is None:
            shutil.copy2(src, by / f"{s}.pkl")
            coverage[s] = {"venue": "binance (no trainer Bybit file)"}
        else:
            coverage[s] = {"venue": "bybit from holdout start", "source_file": name,
                           **splice(src, h, by / f"{s}.pkl", E.HOLDOUT_START)}
    missing = [s for s in traded if coverage.get(s, {}).get("venue", "").startswith("binance")]
    cmd = [sys.executable, str(REPO / "scripts" / "research" / "ml_entry_tp_revision.py"), "evidence-extend-only",
           "--structure-sl", a.structure_sl]
    runs = {}
    for tag, cache in (("control", bn), ("bybit", by)):
        d = out / tag
        p = subprocess.run(cmd + ["--cache", str(cache), "--out", str(d)], capture_output=True, text=True, cwd=str(REPO), check=False)
        runs[tag] = {"rc": p.returncode, "tail": (p.stderr or p.stdout)[-600:] if p.returncode else ""}
        # the record command writes its OWN verdict.json for its own unit; it is not this unit's verdict
        vj = d / "verdict.json"
        if vj.exists():
            vj.rename(d / "harness_verdict_5e04.json")
    rec = None
    try:
        rec = float(json.loads(RECORD.read_text())["expectancy_r_oos"])
    except (OSError, ValueError, KeyError, TypeError):
        rec = None
    v = decide(arm_f(out / "control"), arm_f(out / "bybit"), record_exp=rec, repro_tol=a.repro_tol,
               n_floor=a.n_floor, bar=a.bar, missing_traded=missing)
    n = (v.get("bybit_arm_f") or {}).get("n")
    pop = (f"ml_entry arm F (the live exit) on its Stage-0 held-out population ({E.HOLDOUT_START}..2026-09-30, traded "
           f"symbols {traded}), Bybit bars from the holdout start; net of the full cost stack the harness applies")
    return {"verdict": v.pop("verdict"), "read_state": v.pop("read_state"), "population": pop, "n": n,
            "measurement": {**v, "coverage": coverage, "runs": runs,
                            "thresholds": {"bar": a.bar, "n_floor": a.n_floor, "repro_tol": a.repro_tol}}}


def _self_test() -> int:
    import tempfile

    import pandas as pd
    fails = []

    def chk(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        ts = pd.date_range("2025-09-30 20:00", periods=8, freq="1h", tz="UTC")
        pd.DataFrame({"ts": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}).to_pickle(t / "a.pkl")
        b = pd.DataFrame({"timestamp": ts, "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 2.0})
        r = splice(t / "a.pkl", b, t / "o.pkl", "2025-10-01")
        o = pd.read_pickle(t / "o.pkl")
        chk("bars before the holdout stay Binance", (o[o.ts < pd.Timestamp("2025-10-01", tz="UTC")].close == 1.0).all())
        chk("bars from the holdout are Bybit", (o[o.ts >= pd.Timestamp("2025-10-01", tz="UTC")].close == 2.0).all())
        chk("row count and schema kept", len(o) == 8 and list(o.columns) == ["ts", "open", "high", "low", "close", "volume"]
            and r["binance_rows_replaced"] == 4)
    good = {"n": 907, "mean_net_r": 0.0371}
    kw = {"record_exp": 0.0371, "repro_tol": 0.005, "n_floor": 100, "bar": 0.0, "missing_traded": []}
    chk("positive Bybit -> pass", decide(good, {"n": 900, "mean_net_r": 0.01}, **kw)["verdict"] == "pass")
    chk("zero Bybit -> fail (strict > bar)", decide(good, {"n": 900, "mean_net_r": 0.0}, **kw)["verdict"] == "fail")
    chk("control off the record -> indeterminate",
        decide({"n": 907, "mean_net_r": 0.05}, {"n": 900, "mean_net_r": 0.01}, **kw)["label"] == "control_failed")
    chk("missing traded symbol -> indeterminate",
        decide(good, {"n": 900, "mean_net_r": 0.01}, **{**kw, "missing_traded": ["XRPUSDT"]})["verdict"] == "indeterminate")
    chk("n below floor -> indeterminate", decide(good, {"n": 50, "mean_net_r": 0.01}, **kw)["label"] == "underpowered")
    chk("missing run -> producer_failed", decide(None, good, **kw)["read_state"] == "producer_failed")
    chk("penalty reported", decide(good, {"n": 900, "mean_net_r": 0.0171}, **kw)["penalty_r_per_decision"] == -0.02)
    print("ml_entry_bybit_rescore self-test:", "OK" if not fails else f"FAILED {fails}")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cache", default="/tmp/ml_decision_klines", help="the Binance cache (filled if empty)")
    ap.add_argument("--work", default="/tmp/ml_entry_bybit_rescore")
    ap.add_argument("--data-dir", default="data", help="the trainer's resident Bybit files")
    ap.add_argument("--structure-sl", default="pivot=5")
    ap.add_argument("--bar", type=float)
    ap.add_argument("--n-floor", type=int)
    ap.add_argument("--repro-tol", type=float)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    miss = [f for f in ("bar", "n_floor", "repro_tol", "out") if getattr(a, f) is None]
    if miss:
        ap.error("required: " + ", ".join("--" + x.replace("_", "-") for x in miss))
    try:
        v = run(a)
    except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- recorded as producer_failed in verdict.json
        v = {"verdict": "not_applicable", "read_state": "producer_failed", "population": "ml_entry held-out population",
             "n": None, "note": f"{type(exc).__name__}: {exc}"}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(v, indent=1, default=str) + "\n")
    print(json.dumps({k: v.get(k) for k in ("verdict", "read_state", "n")}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
