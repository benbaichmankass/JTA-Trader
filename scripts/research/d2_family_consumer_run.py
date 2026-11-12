#!/usr/bin/env python3
"""Trainer-side driver for the D2 family consumer test (unit RQ-20261112-bcd2-01).

Per leg: resolve the live params (regime_debt_matrix), fetch candles, run the classified harness (--emit-trades, full cost stack),
tag EVERY trade with (regime, vol_regime) via regime_tag_emitted --emit-tagged --vol-labels (no --only filter), then pool the legs
through regime_gate_family_consumer.py. A leg whose symbol has no labels file is reported inert and excluded, never graded.

    python scripts/research/d2_family_consumer_run.py --out DIR \
        --leg trend_donchian_sol_prop=DIR/SOLUSDT_labels.jsonl --leg trend_donchian_eth_prop=DIR/ETHUSDT_labels.jsonl ...
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regime_debt_matrix as rdm  # type: ignore

REPO = rdm.REPO


def tag_leg(strategy: str, labels: str, workdir: str, days: int) -> dict:
    cfg = rdm.resolve_strategy(strategy)
    out: dict = {"strategy": strategy}
    if cfg is None:
        return {**out, "error": "not declared in strategies.yaml"}
    harness = rdm.classify(cfg)
    sym = (cfg.get("symbols") or [None])[0]
    tf = cfg.get("timeframe")
    if harness is None or not sym or not tf:
        return {**out, "error": "unclassifiable"}
    feed = rdm.resolve_feed(sym, tf)
    csv = os.path.join(workdir, f"{strategy}__data.csv")
    emit = os.path.join(workdir, f"{strategy}__trades.jsonl")
    jout = os.path.join(workdir, f"{strategy}__bt.json")
    tagged = os.path.join(workdir, f"{strategy}__tagged.jsonl")
    rdm._fetch_csv(feed, days, csv)
    argv, faithful, omitted = rdm.build_harness_cmd(strategy, cfg, harness, csv, feed["resample"], emit, jout)
    subprocess.run(argv, check=True, cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    subprocess.run([sys.executable, os.path.join(REPO, "scripts/research/regime_tag_emitted.py"),
                    "--trades", emit, "--data", csv, "--resample", feed["resample"], "--label", strategy,
                    "--emit-tagged", tagged, "--vol-labels", labels, "--json"],
                   check=True, cwd=REPO, capture_output=True)
    return {**out, "symbol": sym, "timeframe": tf, "harness": harness,
            "fidelity": "faithful" if faithful else "approximate", "omitted_levers": sorted(omitted), "tagged": tagged}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--leg", action="append", required=True, help="STRATEGY=labels.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--since", default="2026-07-01")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    legs, report = {}, []
    for spec in a.leg:
        name, labels = spec.split("=", 1)
        if not os.path.exists(labels) or os.path.getsize(labels) == 0:
            report.append({"strategy": name, "error": "no vol labels for the symbol (no advisory head): inert, excluded"})
            continue
        try:
            r = tag_leg(name, labels, a.out, a.days)
        except Exception as e:  # noqa: BLE001  one leg failing never hides the others
            r = {"strategy": name, "error": f"{type(e).__name__}: {str(e)[-300:]}"}
        report.append(r)
        if r.get("tagged"):
            legs[name] = r["tagged"]
    print(json.dumps({"legs": report}, indent=1))
    if not legs:
        print("NO LEGS GRADABLE", file=sys.stderr)
        return 0
    base = [sys.executable, os.path.join(REPO, "scripts/research/regime_gate_family_consumer.py")]
    for l in legs.items():
        base += ["--leg", f"{l[0]}={l[1]}"]
    for tag, extra in (("PRIMARY", []), ("SINCE", ["--since", a.since])):
        print(f"=== GRADE {tag}")
        subprocess.run(base + extra, cwd=REPO, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
