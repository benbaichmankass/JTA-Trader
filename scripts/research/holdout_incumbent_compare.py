#!/usr/bin/env python3
# wiring: manual-only — a read of committed holdout runs a session RUNS before proposing a config change; no scheduled consumer.
"""Holdout: does the SELECTED arm beat the DECLARED arm on the same held-back span?

    python3 scripts/research/holdout_incumbent_compare.py comms/research/RQ-20261016-077e-0*/*/verdict.json

``exit_lever_ablation.py --grade holdout`` selects one arm on the discovery span and reads only
THAT arm once on the held-back span: PASS means "the selected arm is net-positive there". It never
reads the declared arm (A) on the same span, so a PASS can confirm a challenger that is WORSE than
the configuration already trading. Reading A there is not a second selection -- A is the incumbent,
fixed before the run -- so this comparison is what a config change has to clear.

Reads only committed artifacts (``verdict.json`` + ``arms/<arm>__trades.jsonl``), using the
verdict's own boundary: held-back trades are those ENTERED on/after it (the harness's rule). Prints
one row per run; ``--json`` for machine output. Edits nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _ts(s: str) -> datetime:
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def held_back(trades_path: Path, boundary: datetime) -> Dict[str, Any]:
    rows = [json.loads(x) for x in trades_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    ho = [r for r in rows if _ts(r["entry_time"]) >= boundary]
    net = round(sum(float(r["net_r"]) for r in ho), 4)
    return {"n": len(ho), "net_r": net, "expectancy_r": round(net / len(ho), 4) if ho else None}


def compare(verdict_path: Path, baseline: str = "A") -> Optional[Dict[str, Any]]:
    v = json.loads(verdict_path.read_text(encoding="utf-8"))
    g = (v.get("measurement") or {}).get("grade") or {}
    sel = g.get("selected")
    if not sel or not g.get("holdout"):
        return {"run": str(verdict_path), "leg": (v.get("measurement") or {}).get("leg"), "verdict": v.get("verdict"),
                "selected": sel, "state": "no_holdout_read"}
    b = _ts(g["plan"]["boundary"])
    arms = verdict_path.parent / "arms"
    s = held_back(arms / f"{sel}__trades.jsonl", b)
    a = held_back(arms / f"{baseline}__trades.jsonl", b)
    reported = g["holdout"]
    return {"run": str(verdict_path), "leg": v["measurement"].get("leg"), "verdict": v.get("verdict"),
            "selected": sel, "boundary": g["plan"]["boundary"], "selected_holdout": s, "baseline_holdout": a,
            "reproduces_verdict": s["n"] == reported.get("n") and abs(s["net_r"] - float(reported.get("net_r"))) < 1e-3,
            "selected_minus_baseline_r": round(s["net_r"] - a["net_r"], 4),
            "state": ("selected_beats_baseline" if s["net_r"] > a["net_r"] else "baseline_beats_selected")
            if sel != baseline else "baseline_selected"}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("verdicts", nargs="+", type=Path)
    ap.add_argument("--baseline", default="A")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = [compare(p, a.baseline) for p in a.verdicts]
    if a.json:
        print(json.dumps(out, indent=1))
        return 0
    for r in out:
        if r["state"] == "no_holdout_read":
            print(f"{r['leg']:<26} {r['verdict']:<14} selected={r['selected']}  (no holdout read)")
            continue
        s, b = r["selected_holdout"], r["baseline_holdout"]
        print(f"{r['leg']:<26} {r['verdict']:<14} {r['selected']}: n={s['n']} {s['net_r']:+.2f}R  vs  "
              f"{a.baseline}: n={b['n']} {b['net_r']:+.2f}R  -> {r['state']} ({r['selected_minus_baseline_r']:+.2f}R)"
              f"{'' if r['reproduces_verdict'] else '  [DOES NOT REPRODUCE verdict.holdout]'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
