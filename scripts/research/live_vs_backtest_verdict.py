#!/usr/bin/env python3
"""research-queue adapter for live_vs_backtest.py: one leg -> ``<out>/verdict.json`` (Tier-1 tooling).

Runs the committed ``live_vs_backtest`` check for ONE leg on both books (realMoney / mirror) and writes the
research-result contract (``scripts/research/script_run.py::derive_record``). The grading below is fixed here
and in the queue units that call it, BEFORE any run:

  fail           BELOW_BACKTEST on the realMoney book with r_trades >= MIN_N  -> divergence confirmed; the unit's
                 rule files the cause-naming work (it never edits a roster or config)
  pass           CONSISTENT (or ABOVE_BACKTEST) on the realMoney book, r_trades >= MIN_N -> divergence not
                 established at this n
  indeterminate  anything else with a measured live side (INSUFFICIENT_N, NO_BACKTEST on a measured book)
  not_applicable the live payload could not be read (read_state no_data) -- "we could not look", never a verdict

No halting, no config writes; read-only GET of the same public route live_vs_backtest.py uses.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[2]
for _p in (str(HERE.parent), str(REPO / "scripts" / "ops"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import live_vs_backtest as lvb  # noqa: E402

MIN_N = lvb.MIN_N


def grade(rows: list) -> dict:
    """``rows`` = live_vs_backtest.run() output for one leg. Pure; tested."""
    real = [r for r in rows if r.get("book") == "realMoney"]
    if not real:
        return {"verdict": "not_applicable", "read_state": "no_data", "n": None,
                "note": "leg is not on a Stage-2 realMoney roster -- nothing to compare"}
    r = real[0]
    n = int(r.get("r_trades") or 0)
    v = r.get("verdict")
    base = {"n": n, "measurement": {"rows": rows}}
    if v == lvb.BELOW and n >= MIN_N:
        return {**base, "verdict": "fail", "read_state": "measured",
                "note": f"BELOW_BACKTEST on realMoney: live {r.get('live_r')}R over {n}, percentile {r.get('live_percentile')}"}
    if v in (lvb.CONSISTENT, lvb.ABOVE) and n >= MIN_N:
        return {**base, "verdict": "pass", "read_state": "measured", "note": f"{v} on realMoney over {n} trades"}
    if n >= 1 and v is not None:
        return {**base, "verdict": "indeterminate", "read_state": "measured", "note": f"{v} on realMoney (n={n})"}
    return {"verdict": "not_applicable", "read_state": "no_data", "n": None, "note": f"no measured live side: {v}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--url", default=lvb.DEFAULT_URL)
    ap.add_argument("--recent-json", type=pathlib.Path)
    ap.add_argument("--draws", type=int, default=lvb.DRAWS)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    pop = f"{a.leg}: live Stage-2 closed trades with an R basis vs bootstrap of its committed Stage-0 net_r"
    try:
        recent = (json.loads(a.recent_json.read_text(encoding="utf-8")) if a.recent_json else lvb._fetch(a.url))
        if recent.get("error") or any((recent.get(k) or {}).get("readState") != "ok" for k in ("realMoney", "mirror")):
            raise ValueError("route could not read both books")
        import r4_demotion_gate as g
        legs = [(acct, leg) for acct, leg in g.stage2_legs(REPO) if leg == a.leg]
        out = grade(lvb.run(recent, legs, draws=a.draws)) if legs else grade([])
    except (OSError, ValueError) as e:
        out = {"verdict": "not_applicable", "read_state": "no_data", "n": None, "note": f"could not look: {e}"}
    out["population"] = pop
    (a.out / "verdict.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("verdict", "read_state", "n", "note")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
