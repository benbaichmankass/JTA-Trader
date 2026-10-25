#!/usr/bin/env python3
# wiring: manual-only — a per-leg diagnostic a session RUNS to re-evidence a leg on the bar it trades (DECISION-BAR-MATCH; origin.rerun of PI-20261022-LOWUPW43-0001); no scheduled consumer.
"""As-traded Stage 0: does the trade set a leg ACTUALLY trades clear Stage 0?

WHY (lane PERF-FOLLOWUP-2026W43, 2026-10-22). Two bybit_2 real-money legs
(xrp_pullback_2h, ada_pullback_2h) read BELOW_BACKTEST on live_vs_backtest.py
(2026-10-21 walk-through). The 10-18 per-trade join named the cause ENTRY: both
legs carry no ``decision_bar``, so live decides on the still-FORMING 2h bar
while their committed Stage-0 records score CLOSED bars
(PI-20260929-VOLSKIP-SIGNAL-0003, PI-20261015-10152047-0001). The 10-18 holdout
(RQ-20261018-2a10-01) asked "is closed better than forming?" and did not select
closed. It did not ask the question this script asks: **does the set the leg
trades -- the incumbent ``decision_bar`` arm -- have a Stage-0 edge on its own,
net of the full cost stack, across calendar folds and on the latest held-back
quarter?** That is the data half of VOLSKIP-0003's open decision ("does the
closed-bar record count as this leg's evidence while it trades the forming set").

WHAT IT DOES. Runs ``scripts/research/decision_bar_holdout.py`` unchanged (same
Binance 1m proxy, same config-exact arms, same cost stack) into
``<out>/holdout/``, then grades ONLY the incumbent arm of each leg
(``decision_bar`` absent => forming). ``--arms-dir`` skips the run and grades
existing ``<leg>__{A_closed,B_forming}__trades.jsonl`` files (tests; re-grades).

GRADE per leg (thresholds are the unit's, passed as flags):
  * n < --n-floor                               -> indeterminate
  * holdout = latest --holdout-frac of trades by entry time (>= --holdout-min);
    folds = --folds equal CALENDAR spans of the whole arm, binned by entry time.
  * PASS  iff net_r_total > 0 AND holdout net_r > 0 AND folds_positive >= --fold-majority
  * FAIL  iff net_r_total <= 0, OR (holdout net_r <= 0 AND folds_positive < --fold-majority)
  * MIXED otherwise.
Top-level verdict: ``fail`` if any leg FAILs, ``pass`` if every graded leg
PASSes, else ``indeterminate``. ``records`` fans out one row per leg.

Live side (measured, NOT graded): when ``--live`` is given, each leg's live
real-money total R is bootstrapped against the as-traded arm (the same
``live_vs_backtest.judge``), so the record states where live sits in the band
of what it trades. A failed fetch is recorded as ``not_measured``.

Edits no config, roster or record; places no order. A FAIL is a Tier-3 INPUT
(to VOLSKIP-0003 / the demotion mandate's own clauses), never a roster act.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))

ARM_FILE = {"closed": "A_closed", "forming": "B_forming"}


def _ts(v: Any) -> datetime:
    s = str(v).replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def incumbent_arm(leg: str, strategies_yaml: Path) -> str:
    import yaml
    doc = yaml.safe_load(strategies_yaml.read_text()) or {}
    block = (doc.get("strategies", doc) if isinstance(doc, dict) else {}).get(leg) or {}
    if not isinstance(block, dict):
        block = {}
    return "closed" if str(block.get("decision_bar") or "forming").lower() == "closed" else "forming"


def grade_arm(rows: list[dict[str, Any]], *, n_floor: int, folds: int, fold_majority: int,
              holdout_frac: float, holdout_min: int) -> dict[str, Any]:
    rows = sorted(rows, key=lambda r: _ts(r["entry_time"]))
    n = len(rows)
    net = round(sum(float(r["net_r"]) for r in rows), 4)
    out: dict[str, Any] = {"n": n, "net_r_total": net,
                           "mean_net_r": round(net / n, 4) if n else None}
    if n < n_floor:
        out.update(verdict="indeterminate", why=f"n {n} < n_floor {n_floor}")
        return out
    k = max(holdout_min, round(n * holdout_frac))
    hold = rows[n - k:]
    out["holdout"] = {"n": len(hold), "from": str(hold[0]["entry_time"]),
                      "net_r": round(sum(float(r["net_r"]) for r in hold), 4)}
    t0, t1 = _ts(rows[0]["entry_time"]), _ts(rows[-1]["entry_time"])
    span = (t1 - t0) / folds
    fold_r = [0.0] * folds
    fold_n = [0] * folds
    for r in rows:
        i = min(folds - 1, int((_ts(r["entry_time"]) - t0) / span)) if span.total_seconds() else 0
        fold_r[i] += float(r["net_r"])
        fold_n[i] += 1
    pos = sum(1 for x in fold_r if x > 0)
    out["folds"] = {"net_r": [round(x, 4) for x in fold_r], "n": fold_n, "positive": pos, "of": folds}
    if net > 0 and out["holdout"]["net_r"] > 0 and pos >= fold_majority:
        v = "pass"
    elif net <= 0 or (out["holdout"]["net_r"] <= 0 and pos < fold_majority):
        v = "fail"
    else:
        v = "mixed"
    out["verdict"] = v
    return out


def live_band(leg: str, xs: list[float], recent: dict[str, Any] | None) -> dict[str, Any]:
    if recent is None:
        return {"state": "not_measured", "why": "live fetch not requested or failed"}
    import live_vs_backtest as lvb
    row = lvb._leg_last(recent, "realMoney", leg)
    n = (row or {}).get("rTradeCount") or 0
    lr = (row or {}).get("totalR")
    if n < 1 or not isinstance(lr, (int, float)):
        return {"state": "not_measured", "why": "no real-money closed trade with an R basis"}
    return {"state": "measured", **lvb.judge(float(lr), xs, int(n))}


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.arms_dir:
        arms_dir = Path(args.arms_dir)
    else:
        hold = out_dir / "holdout"
        cmd = [sys.executable, str(REPO / "scripts/research/decision_bar_holdout.py"),
               "--klines-dir", str(out_dir / "klines"), "--out", str(hold),
               "--research-unit", args.research_unit or "as-traded-stage0"]
        if args.fetch:
            cmd.append("--fetch")
        if args.end:
            cmd += ["--end", args.end]
        for lg in args.leg:
            cmd += ["--leg", lg]
        subprocess.run(cmd, check=True, cwd=str(REPO))
        arms_dir = hold / "arms"
    recent = None
    if args.live:
        try:
            import live_vs_backtest as lvb
            recent = lvb._fetch(args.live_url)
        except (OSError, ValueError) as e:  # URLError is an OSError; bad JSON is a ValueError. Recorded as not_measured, never fabricated
            print(f"live fetch failed: {e!r}", file=sys.stderr)
    legs: dict[str, Any] = {}
    for leg in args.leg:
        arm = incumbent_arm(leg, Path(args.strategies))
        p = arms_dir / f"{leg}__{ARM_FILE[arm]}__trades.jsonl"
        if not p.exists():
            legs[leg] = {"arm": arm, "verdict": "indeterminate", "why": f"no arm file {p.name}"}
            continue
        rows = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
        g = grade_arm(rows, n_floor=args.n_floor, folds=args.folds, fold_majority=args.fold_majority,
                      holdout_frac=args.holdout_frac, holdout_min=args.holdout_min)
        g["arm"] = arm
        g["live_vs_as_traded"] = live_band(leg, [float(r["net_r"]) for r in rows], recent)
        legs[leg] = g
    vs = [g["verdict"] for g in legs.values()]
    graded = [v for v in vs if v != "indeterminate"]
    top = "fail" if "fail" in vs else "pass" if graded and all(v == "pass" for v in graded) else "indeterminate"
    pop = (f"{len(args.leg)} legs ({', '.join(args.leg)}): the incumbent decision_bar arm of "
           f"decision_bar_holdout.py (Binance 1m proxy, config-exact, full cost stack), window end "
           f"{args.end or 'unpinned'}")
    res = {
        "research_unit": args.research_unit, "verdict": top,
        "read_state": "measured" if graded else "insufficient_n",
        "population": pop, "n": sum(g.get("n", 0) for g in legs.values()),
        "measurement": {"legs": legs, "params": {
            "n_floor": args.n_floor, "folds": args.folds, "fold_majority": args.fold_majority,
            "holdout_frac": args.holdout_frac, "holdout_min": args.holdout_min}},
        "records": [{"leg": lg, "verdict": g["verdict"], "read_state": "measured"
                     if g["verdict"] != "indeterminate" else "insufficient_n",
                     "population": f"{lg} {g.get('arm')} arm, n={g.get('n')}", "n": g.get("n", 0),
                     "measurement": g} for lg, g in legs.items()],
        "note": "as-traded Stage 0 (incumbent decision_bar arm only); live band measured, not graded",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out_dir / "verdict.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arms-dir", default=None, help="grade existing arm files; skip the replay")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--end", default=None)
    ap.add_argument("--strategies", default=str(REPO / "config" / "strategies.yaml"))
    ap.add_argument("--n-floor", type=int, required=True)
    ap.add_argument("--folds", type=int, required=True)
    ap.add_argument("--fold-majority", type=int, required=True)
    ap.add_argument("--holdout-frac", type=float, required=True)
    ap.add_argument("--holdout-min", type=int, required=True)
    ap.add_argument("--live", action="store_true", help="bootstrap live real-money R vs the arm (measured, not graded)")
    ap.add_argument("--live-url", default="https://ict-bot.duckdns.org/api/bot/performance/recent?n=200")
    ap.add_argument("--research-unit", default=None)
    args = ap.parse_args(argv)
    res = run(args)
    print(json.dumps({lg: g["verdict"] for lg, g in res["measurement"]["legs"].items()}), res["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
