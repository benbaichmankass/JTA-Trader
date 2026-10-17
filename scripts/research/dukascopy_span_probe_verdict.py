#!/usr/bin/env python3
# wiring: research/queue/RQ-20261017-ae17-50.yaml (research-script-run.yml; dukascopy-python is installed there)
"""Dukascopy depth probe as a queue unit: does the feed reach back to ~2006 for every adjudicated equity/index instrument?

Runs ``dukascopy_span_probe.run`` (the same probe the manual dukascopy-span-probe.yml uses) at daily
resolution with anchors out to 7300 d, and writes ``<out>/verdict.json`` for scripts/research/script_run.py.
Not a market measurement: it answers whether a second candle source is needed for the 1d ETF legs
(yfinance has served Stage-0 history back to 2006; Dukascopy is the candidate fallback).

Rule (registered in the unit): PASS iff every probed instrument is a clean ``measured`` claim whose deepest
anchor with bars is >= TARGET_DAYS; FAIL iff every anchor answered (no error / unknown) and at least one
instrument's deepest anchor is < TARGET_DAYS; INDETERMINATE (read_state measured) otherwise -- a
lower-bound or errored read is "we did not look", never a depth.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dukascopy_span_probe as probe

TARGET_DAYS = 7300   # ~2006-10 from 2026-10


def grade(by_instrument: list, target: int = TARGET_DAYS) -> dict:
    deep = [b for b in by_instrument if b["depth_claim"] == "measured" and (b["earliest_bars_anchor"] or 0) >= target]
    shallow = [b["instrument"] for b in by_instrument
               if b["depth_claim"] == "measured" and (b["earliest_bars_anchor"] or 0) < target]
    unclear = [b["instrument"] for b in by_instrument if b["depth_claim"] != "measured"]
    if not by_instrument:
        verdict = "not_applicable"
    elif not shallow and not unclear:
        verdict = "pass"
    elif shallow and not unclear:
        verdict = "fail"
    else:
        verdict = "indeterminate"
    return {"verdict": verdict, "reach_target": len(deep), "shallow": shallow, "unclear": unclear}


def _self_test() -> int:
    def mk(i, claim, e):
        return {"instrument": i, "depth_claim": claim, "earliest_bars_anchor": e}

    assert grade([mk("a", "measured", 7300), mk("b", "measured", 7300)])["verdict"] == "pass"
    assert grade([mk("a", "measured", 7300), mk("b", "measured", 3650)])["verdict"] == "fail"
    assert grade([mk("a", "measured", 3650), mk("b", "lower_bound_some_anchors_errored", 3650)])["verdict"] == "indeterminate"
    assert grade([])["verdict"] == "not_applicable"
    print("dukascopy_span_probe_verdict self-test OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--anchors", default="1830,3650,5475,7300")
    ap.add_argument("--window-days", type=int, default=10)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    anchors = tuple(int(x) for x in a.anchors.split(",") if x.strip())
    out = probe.run(anchors, a.interval, a.window_days)
    g = grade(out["by_instrument"])
    n = len(out["by_instrument"])
    verdict = {"verdict": g["verdict"], "read_state": "measured" if n else "no_data",
               "population": f"{n} adjudicated Dukascopy instrument(s) x {len(anchors)} look-back anchors ({a.interval}, {a.window_days} d windows)",
               "n": n, "measurement": {**g, "target_days": TARGET_DAYS, "anchors_days": list(anchors),
                                       "by_instrument": out["by_instrument"], "refused_symbols": out["refused_symbols"]},
               "note": "data-source depth only; says nothing about any strategy. Proxies keep their `relation`: a proxy's span is not the real instrument's."}
    p = Path(a.out)
    p.mkdir(parents=True, exist_ok=True)
    (p / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print(probe.render(out))
    print(json.dumps({k: verdict[k] for k in ("verdict", "read_state", "population", "n")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
