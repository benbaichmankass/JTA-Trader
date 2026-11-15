#!/usr/bin/env python3
"""Trainer-side driver for the D2 family consumer test (unit RQ-20261112-bcd2-01).

Per leg: resolve the live params (regime_debt_matrix), fetch candles, run the classified harness (--emit-trades, full cost stack),
tag EVERY trade with (regime, vol_regime) via regime_tag_emitted --emit-tagged --vol-labels (no --only filter), then pool the legs
through regime_gate_family_consumer.py. A leg whose symbol has no labels file is reported inert and excluded, never graded.

    python scripts/research/d2_family_consumer_run.py --out DIR \
        --leg trend_donchian_sol_prop=DIR/SOLUSDT_labels.jsonl --leg trend_donchian_eth_prop=DIR/ETHUSDT_labels.jsonl ...

Opt-in, default OFF (without them the run is unchanged):
  --cells-per-leg   pass-through to regime_gate_family_consumer.py: each leg is gated by its OWN trend_vol cells.
  --verdict-json P  also write a script_run verdict.json applying the KEEP-TEST rule (unit RQ-20261113-b819-01):
                    PRIMARY dropped < 25 -> indeterminate; PRIMARY fail -> fail; PRIMARY pass -> SINCE must also have
                    dropped >= 25 and added_r > 0 (pass), dropped < 25 (indeterminate), else fail. The PRIMARY window
                    includes the cells' authoring history, so a PRIMARY pass alone never keeps a cell.
"""
# wiring: manual-only - run through the trainer-vm-diag issue relay by the research unit that names it (RQ-20261112-bcd2-01), not by a workflow or caller
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regime_debt_matrix as rdm  # type: ignore  # noqa: E402

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


MIN_SINCE_DROPPED = 25  # = regime_gate_family_consumer.MIN_DROPPED; the out-of-sample slice's own power floor


def keep_test_verdict(primary: dict, since: dict) -> tuple[str, str]:
    """The KEEP-TEST rule (registered in RQ-20261113-b819-01 before any run). Returns (verdict, reason)."""
    pv = primary.get("verdict")
    if pv in ("indeterminate_underpowered", "no_trades"):
        return "indeterminate", f"primary {pv}"
    if pv != "pass":
        return "fail", "primary fail (added_r <= 0, fold_wins < 4 or control_p > 0.05) on a window biased toward the cells"
    if int(since.get("dropped_n") or 0) < MIN_SINCE_DROPPED:
        return "indeterminate", f"primary pass but since-slice dropped_n {since.get('dropped_n')} < {MIN_SINCE_DROPPED}"
    if float(since.get("added_r") or 0.0) > 0:
        return "pass", "primary pass and since-slice added_r > 0"
    return "fail", "primary pass but since-slice added_r <= 0 (the cells did not hold after authoring)"


def _selftest() -> None:
    P = {"verdict": "pass", "dropped_n": 200, "added_r": 10.0}
    assert keep_test_verdict({"verdict": "indeterminate_underpowered"}, {})[0] == "indeterminate"
    assert keep_test_verdict({"verdict": "fail"}, {"dropped_n": 99, "added_r": 5})[0] == "fail"
    assert keep_test_verdict(P, {"dropped_n": 24, "added_r": 5})[0] == "indeterminate"
    assert keep_test_verdict(P, {"dropped_n": 25, "added_r": 0.1})[0] == "pass"
    assert keep_test_verdict(P, {"dropped_n": 40, "added_r": 0.0})[0] == "fail"
    print("self-test ok")


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        _selftest()
        return 0
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--leg", action="append", required=True, help="STRATEGY=labels.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--since", default="2026-07-01")
    ap.add_argument("--cells-per-leg", action="store_true", help="opt-in: each leg gated by its own trend_vol cells")
    ap.add_argument("--verdict-json", default=None, help="opt-in: write a verdict.json under the KEEP-TEST rule")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    legs, report, failed = {}, [], False
    for spec in a.leg:
        name, labels = spec.split("=", 1)
        if not os.path.exists(labels) or os.path.getsize(labels) == 0:
            report.append({"strategy": name, "error": "no vol labels for the symbol (no advisory head): inert, excluded"})
            continue
        try:
            r = tag_leg(name, labels, a.out, a.days)
        except (subprocess.CalledProcessError, OSError, KeyError, ValueError) as e:
            # one leg failing never hides the others: the error is written into the report and the exit says so
            r = {"strategy": name, "error": f"{type(e).__name__}: {str(e)[-300:]}"}
            failed = True
        report.append(r)
        if r.get("tagged"):
            legs[name] = r["tagged"]
    print(json.dumps({"legs": report}, indent=1))
    if not legs:
        print("NO LEGS GRADABLE", file=sys.stderr)
        return 1
    base = [sys.executable, os.path.join(REPO, "scripts/research/regime_gate_family_consumer.py")]
    for leg_name, leg_file in legs.items():
        base += ["--leg", f"{leg_name}={leg_file}"]
    if a.cells_per_leg:
        base += ["--cells-per-leg"]
    grades: dict = {}
    for tag, extra in (("PRIMARY", []), ("SINCE", ["--since", a.since])):
        print(f"=== GRADE {tag}")
        if a.verdict_json:
            proc = subprocess.run(base + extra, cwd=REPO, check=True, capture_output=True, text=True)
            print(proc.stdout)
            grades[tag] = json.loads(proc.stdout)
        else:
            subprocess.run(base + extra, cwd=REPO, check=True)
    if a.verdict_json:
        verdict, reason = keep_test_verdict(grades["PRIMARY"], grades["SINCE"])
        graded = [r for r in report if r.get("tagged")]
        rec = {
            "verdict": verdict,
            "read_state": "producer_failed" if failed else "measured",
            "n": grades["PRIMARY"].get("trades_total"),
            "population": ("harness trades of " + ", ".join(f"{r['strategy']} ({r['symbol']} {r['timeframe']}, "
                                                             f"{r['fidelity']})" for r in graded)
                           + f", {a.days}d Binance-vision candles, full cost stack, tagged by replayed vol labels"),
            "measurement": {"primary": grades["PRIMARY"], "since": grades["SINCE"], "since_date": a.since,
                            "legs": report, "rule_reason": reason, "min_since_dropped": MIN_SINCE_DROPPED},
            "note": reason,
        }
        with open(a.verdict_json, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=1)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
