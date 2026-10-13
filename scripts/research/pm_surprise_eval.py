#!/usr/bin/env python3
# wiring: research/queue/RQ-20261009-903.yaml (run.command via research-script-run-trainer.yml) — TRAINER-side, needs the off-repo Kalshi backfill.
"""RQ-20261009-903 (PM-SURPRISE-EVAL, WEPE gate G2) — the measurement, applied to its PRE-REGISTERED rule.

Reads the trainer-resident Kalshi backfill, builds PM-expected / PM-surprise per release
(``scripts/macro/pm_surprise.py``), joins to the committed consensus by EXACT release date, and runs the
paired IC comparison (``scripts/macro/econ_event_study.py::paired_ic_comparison``):

    IC(PM-surprise, fwd return) - IC(consensus-surprise, fwd return)   at the SAME releases, per horizon

Writes ``<out>/scorecard.json`` (aggregates + per-release DERIVED surprises, no quotes), ``<out>/paired.jsonl``
(the per-release derived records ``econ_event_study.py --pm-surprise`` reads) and ``<out>/verdict.json``
(the ``script_run.py`` contract). Third-party data stays on the trainer; only these derived files are committed.

THE RULE (RULE-RQ1009-903-PM-SURPRISE-VS-CONSENSUS, registered 2026-10-09 before any run, UNCHANGED —
``grade()`` below is that text, mechanically):
  * population: releases with BOTH a PM quote within 6 h before the release AND a resolved consensus;
  * ELIGIBLE only when paired n >= 49 pooled (at both registered horizons);
  * PASS  — paired IC difference at horizons 3 AND 5 is > 0, bootstrap interval excludes 0, and the sign holds
            on both date halves;
  * FAIL  — the difference is <= 0, or its interval spans zero, at n >= 49;
  * below n = 49 — UNDERPOWERED (verdict ``indeterminate``), never a pass, never a fail.
Where the rule is silent this script says so in the note instead of choosing a side.

Implementation choices the rule leaves open (all echoed in the scorecard ``definitions``): the difference is
SIGNED as written (IC_pm - IC_consensus; |IC| difference is reported beside it, ungraded); pooling across kinds
uses within-kind percentile ranks of each surprise (units differ: pp / thousands of jobs / bps); the forward
return is ES=F close-to-close (no traded proxy, so there is no cost to net).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0] / "macro"))
import econ_event_study as ees  # noqa: E402
import pm_snapshot_collect as pmc  # noqa: E402
import pm_surprise as pms  # noqa: E402

RULE_ID = "RULE-RQ1009-903-PM-SURPRISE-VS-CONSENSUS"
REGISTERED_HORIZONS = (3, 5)
HORIZONS = [1, 3, 5, 10, 21]
N_FLOOR = 49
WITHIN_HOURS = 6.0
DEFAULT_SNAPSHOTS = [
    "comms/macro/econ_calendar_snapshots.jsonl",
    "comms/macro/econ_calendar_snapshots_backfill.jsonl",
    "comms/macro/econ_calendar_snapshots_survey_backfill.jsonl",
]
DEFINITIONS = {
    "pm_expected": "last usable two-sided yes bid/ask mid per strike with candle_end_utc <= close_time; "
                   "usable = 0<=bid<=ask<=1, spread<=%.2f" % pms.MAX_SPREAD,
    "pm_surprise": "realized - pm_expected (realized = calendar actual; FOMC = calendar change in bps)",
    "consensus_surprise": "realized - calendar consensus (FOMC: consensus level - prior, in bps)",
    "join": "exact: UTC date of the Kalshi close_time == calendar scheduled_for",
    "graded_population": "last PM quote within %.0f h before close_time" % WITHIN_HOURS,
    "pooling": "within-kind percentile rank of each surprise; forward return raw",
    "difference": "signed IC_pm - IC_consensus, as written in the rule; abs_ic_diff reported ungraded",
    "bootstrap": "percentile, 2000 resamples of paired releases, seed 20261012+horizon, 95%",
    "return": "ES=F close-to-close forward return, trading-day horizons, right-censored dropped",
}


def grade(pooled: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply the registered rule to the pooled rows (one per horizon). Returns ``{verdict, note, n}``."""
    reg = {r["horizon_days"]: r for r in pooled if r["horizon_days"] in REGISTERED_HORIZONS}
    if set(reg) != set(REGISTERED_HORIZONS):
        return {"verdict": "indeterminate", "n": None, "note": "registered horizons missing from the study"}
    n = min(r["n_paired"] for r in reg.values())
    if n < N_FLOOR:
        return {"verdict": "indeterminate", "n": n,
                "note": f"UNDERPOWERED: paired n={n} < {N_FLOOR} at the registered horizons (3, 5). Not a pass, not a fail."}
    fail, ok, why = False, True, []
    for h in REGISTERED_HORIZONS:
        r = reg[h]
        d, lo, hi, halves = r["diff"], r["boot_lo"], r["boot_hi"], r["half_diffs"]
        if d is None or lo is None or hi is None:
            return {"verdict": "indeterminate", "n": n, "note": f"h={h}: difference or interval undefined"}
        if d <= 0 or (lo <= 0 <= hi):
            fail = True
            why.append(f"h={h}: diff={d:+.4f} CI[{lo:+.4f},{hi:+.4f}] " + ("diff<=0" if d <= 0 else "interval spans 0"))
        elif len(halves) != 2 or any(x is None or x <= 0 for x in halves):
            ok = False
            why.append(f"h={h}: diff={d:+.4f} CI[{lo:+.4f},{hi:+.4f}] excludes 0 but halves={halves} do not both agree")
        else:
            why.append(f"h={h}: diff={d:+.4f} CI[{lo:+.4f},{hi:+.4f}] halves={halves}")
    if fail:
        return {"verdict": "fail", "n": n, "note": "FAIL (rule: diff<=0 or interval spans zero at n>=49). " + "; ".join(why)}
    if ok:
        return {"verdict": "pass", "n": n, "note": "PASS (G2 clause 2 met; record, no config). " + "; ".join(why)}
    return {"verdict": "indeterminate", "n": n,
            "note": "RULE SILENT: diff>0 with interval excluding 0 but the date-half sign condition failed — neither "
                    "PASS nor FAIL is written for this case. " + "; ".join(why)}


def run(backfill_dir: Path, snapshots: List[str], panel: List, horizons: List[int], n_boot: int = 2000) -> Dict[str, Any]:
    pm: List[Dict[str, Any]] = []
    series_stats: Dict[str, Any] = {}
    for series in pms.KIND_SPEC:
        path = backfill_dir / f"{series}.jsonl"
        recs = pms.build_series(series, pms.read_jsonl(path)) if path.exists() else []
        pm.extend(recs)
        series_stats[series] = {"events": len(recs), "skipped": sum(1 for r in recs if r.get("skipped")),
                                "skip_reasons": _count(r["reason"] for r in recs if r.get("skipped"))}
    cal = {k["kind"]: ees.load_resolved_events_multi(snapshots, k["kind"]) for k in pms.KIND_SPEC.values()}
    paired_all, diag_all = pms.join_pm_to_calendar(pm, cal)
    paired, diag = pms.join_pm_to_calendar(pm, cal, max_stale_hours=WITHIN_HOURS)

    def study(rows: List[Dict[str, Any]], group: bool) -> List[Dict[str, Any]]:
        return ees.paired_ic_comparison(rows, panel, horizons=horizons, n_boot=n_boot,
                                        group_key="kind" if group else None)

    per_kind = {k: study([p for p in paired if p["kind"] == k], False) for k in sorted({p["kind"] for p in paired})}
    return {
        "series": series_stats, "calendar_resolved": {k: len(v) for k, v in cal.items()},
        "join_graded": diag, "join_all_last_quote": diag_all,
        "pooled": study(paired, True), "per_kind": per_kind,
        "sensitivity_all_last_quote_pooled": study(paired_all, True),
        "paired": paired,
    }


def _count(it) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backfill-dir", type=Path, default=None, help="default <data_dir>/pm_backfill/kalshi")
    ap.add_argument("--snapshots", nargs="*", default=DEFAULT_SNAPSHOTS)
    ap.add_argument("--symbol", default="ES=F")
    ap.add_argument("--candles-dir", default=None, help="per-symbol daily CSVs (tests); default: off-VM live fetch")
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument("--n-boot", type=int, default=2000)
    a = ap.parse_args(argv)

    bdir = a.backfill_dir or (pmc.data_dir() / "pm_backfill" / "kalshi")
    a.out.mkdir(parents=True, exist_ok=True)
    if a.candles_dir is None:
        # This command is TRAINER-side by declaration (header), i.e. an off-live-VM host, but the unit's argv cannot
        # carry env (script_run._INTERPRETERS) and research-script-run-trainer.yml does not set it: without this the
        # fetch guard raised in 0.3 s (run 38258786887, exit 1). setdefault: an operator-set value still wins.
        os.environ.setdefault("ICT_OFFVM_BUILD_HOST", "1")
    panel = ees._resolve_panel(a.symbol, a.candles_dir)
    if not panel:
        v = {"verdict": "indeterminate", "read_state": "no_data", "n": None,
             "population": f"{RULE_ID}: no {a.symbol} price bars fetched — nothing measured",
             "note": "price panel empty (yfinance/Stooq unreachable from this host?)"}
        (a.out / "verdict.json").write_text(json.dumps(v, indent=2) + "\n")
        print(v["note"], file=sys.stderr)
        return 0
    res = run(bdir, a.snapshots, panel, HORIZONS, a.n_boot)
    paired = res.pop("paired")
    g = grade(res["pooled"])
    scorecard = {"rule_id": RULE_ID, "definitions": DEFINITIONS, "symbol": a.symbol, "price_bars": len(panel),
                 "horizons": HORIZONS, "registered_horizons": list(REGISTERED_HORIZONS), "n_floor": N_FLOOR,
                 "grade": g, **res}
    (a.out / "scorecard.json").write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n")
    with (a.out / "paired.jsonl").open("w", encoding="utf-8") as fh:
        for p in paired:
            fh.write(json.dumps(p, sort_keys=True) + "\n")
    jg = res["join_graded"]
    verdict = {
        "verdict": g["verdict"], "read_state": "measured", "n": g["n"],
        "population": (f"releases with a Kalshi quote <= {WITHIN_HOURS:.0f} h before close AND a resolved consensus, "
                       f"exact-date join; paired={jg['paired']} of {jg['pm_events']} PM events (CPI mom / NFP / FOMC); "
                       f"horizons {HORIZONS}, {a.symbol}"),
        "note": g["note"],
        "measurement": {"pooled": res["pooled"], "join_graded": jg, "per_kind_n": {
            k: {r["horizon_days"]: r["n_paired"] for r in v} for k, v in res["per_kind"].items()}},
    }
    (a.out / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"grade": g, "join_graded": jg}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
