#!/usr/bin/env python3
# wiring: manual-only — the "Live review" section generator for /performance-review (LTR-5); the skill runs it each review, /perf-followup Track 2 reads its --json. No timer.
"""Grade the live-trade-review calls: the "Live review" section of /performance-review.

    python3 scripts/ops/live_review_grade.py --live              # markdown section, priced from the VM journal + candles
    python3 scripts/ops/live_review_grade.py --live --json       # machine form (perf-followup Track 2 reads this)
    python3 scripts/ops/live_review_grade.py --live --since 2026-10-19

Projects over the canonical records (``comms/live_review/reviews.jsonl`` joined to the journal on
``order_package_id`` / ``trade_id``) through ``scripts/research/live_review_counterfactual.py``; it keeps
no store of its own. Every figure carries its population.

THE Q1 COMPARISON (live 0.25 R policy vs the shadow 0.5 R policy, operator Q1 2026-10-25). The rule is
registered here, BEFORE any run reads it:
* a tighten_sl review is IN the comparison only when BOTH ``apply_policy.within_bound`` and
  ``shadow_policy.within_bound`` were decided at review time (a table-backed cost; a judgement call has neither);
* policy A (0.25 R) takes the tighten iff its flag is true, else holds; policy B (0.5 R) likewise;
* the paired difference per review is ``dR_B - dR_A`` where dR is the priced ``delta_r`` if the policy took the
  tighten, else 0. Only DISCORDANT reviews (A holds, B tightens) are non-zero;
* the verdict is ``B_better`` / ``A_better`` only when ``n_discordant >= Q1_MIN_DISCORDANT`` AND the two-sided 95%
  interval of the mean paired difference excludes 0; otherwise ``INDETERMINATE`` with the reason.

CALIBRATION. For priced tighten_sl calls carrying ``judgement_confidence`` (the probability the call beats
holding): success = ``delta_r > 0``; Brier score and a reliability table by confidence bucket, stratified by
``evidence_source``. Below ``CAL_MIN_N`` priced calls the stratum reads INDETERMINATE.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import live_review_counterfactual as cf  # noqa: E402

Q1_MIN_DISCORDANT = 10
CAL_MIN_N = 10
ALARM_MIN_APPLIES = 20
BUCKETS = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0001))
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
        20: 2.086, 25: 2.060, 30: 2.042}


def _t95(df: int) -> float:
    if df <= 0:
        return math.inf
    ks = sorted(_T95)
    for k in ks:
        if df <= k:
            return _T95[k]
    return 1.96


def _stats(xs: List[float]) -> Dict[str, Any]:
    if not xs:
        return {"n": 0, "mean_dr": None, "worst_dr": None, "hit_rate": None}
    return {"n": len(xs), "mean_dr": round(statistics.fmean(xs), 4), "worst_dr": round(min(xs), 4),
            "hit_rate": round(sum(1 for x in xs if x > 0) / len(xs), 3)}


def q1_comparison(results: List[dict], reviews_by_id: Dict[str, dict]) -> Dict[str, Any]:
    tight = [r for r in results if r["action"] == "tighten_sl"]
    priced = [r for r in tight if r["state"] == "priced"]
    rows = []
    undefined = 0
    for r in priced:
        rv = reviews_by_id[r["review_id"]]
        a, b = (rv.get("apply_policy") or {}).get("within_bound"), (rv.get("shadow_policy") or {}).get("within_bound")
        if a is None or b is None:
            undefined += 1
            continue
        d = r["outcome"]["delta_r"]
        rows.append((a, b, d))
    diffs = [((d if b else 0.0) - (d if a else 0.0)) for a, b, d in rows]
    disc = [x for (a, b, _), x in zip(rows, diffs) if a != b]
    out: Dict[str, Any] = {
        "population": {"tighten_reviews": len(tight), "priced": len(priced), "policy_undefined_judgement_or_thin": undefined,
                       "in_comparison": len(rows), "concordant": len(rows) - len(disc), "discordant": len(disc)},
        "rule": f"B_better/A_better only if discordant >= {Q1_MIN_DISCORDANT} and the 95% interval of the mean paired dR (0.5R policy - 0.25R policy) excludes 0",
        "mean_paired_dr": round(statistics.fmean(diffs), 4) if diffs else None,
    }
    if len(disc) >= Q1_MIN_DISCORDANT:
        m, sd = statistics.fmean(disc), statistics.stdev(disc)
        half = _t95(len(disc) - 1) * sd / math.sqrt(len(disc))
        out["discordant_mean_dr"], out["ci95"] = round(m, 4), [round(m - half, 4), round(m + half, 4)]
        out["verdict"] = "INDETERMINATE" if (m - half) <= 0 <= (m + half) else ("B_better" if m > 0 else "A_better")
        if out["verdict"] == "INDETERMINATE":
            out["verdict_reason"] = "interval includes 0"
    else:
        out["verdict"] = "INDETERMINATE"
        out["verdict_reason"] = f"{len(disc)} discordant priced review(s) < {Q1_MIN_DISCORDANT}"
    return out


def calibration(results: List[dict], reviews_by_id: Dict[str, dict]) -> Dict[str, Any]:
    strata: Dict[str, List[tuple]] = defaultdict(list)
    for r in results:
        if r["action"] != "tighten_sl" or r["state"] != "priced":
            continue
        rec = reviews_by_id[r["review_id"]].get("recommendation") or {}
        conf = rec.get("judgement_confidence")
        if conf is None:
            continue
        strata[rec.get("evidence_source") or "unknown"].append((float(conf), 1.0 if r["outcome"]["delta_r"] > 0 else 0.0))
    out = {}
    for src, pts in sorted(strata.items()):
        row: Dict[str, Any] = {"n": len(pts), "brier": round(statistics.fmean((c - y) ** 2 for c, y in pts), 4),
                               "reliability": []}
        for lo, hi in BUCKETS:
            b = [(c, y) for c, y in pts if lo <= c < hi]
            if b:
                row["reliability"].append({"bucket": f"[{lo:.1f},{min(hi, 1.0):.1f}]", "n": len(b),
                                           "mean_confidence": round(statistics.fmean(c for c, _ in b), 3),
                                           "realised_hit_rate": round(statistics.fmean(y for _, y in b), 3)})
        if len(pts) < CAL_MIN_N:
            row["verdict"] = f"INDETERMINATE (n={len(pts)} < {CAL_MIN_N})"
        out[src] = row
    return out


def grade(reviews: List[dict], results: List[dict]) -> Dict[str, Any]:
    by_id = {r["review_id"]: r for r in reviews}
    pop = {"n_reviews": len(reviews), "n_packages": len({r["order_package_id"] for r in reviews}),
           "by_action_basis": dict(Counter(f'{(r.get("recommendation") or {}).get("action")}/{(r.get("recommendation") or {}).get("basis")}' for r in reviews))}
    priced = [r for r in results if r["state"] == "priced"]
    cnp = [r for r in results if r["state"] == "could_not_price"]
    nac = [r for r in results if r["state"] == "not_a_call"]
    altering = [r for r in results if r["action"] in cf.ALTERING]
    pop.update({
        "n_altering_calls": len(altering),
        "n_priced": sum(1 for r in priced if r["action"] in cf.ALTERING),
        "n_could_not_price": len(cnp),
        "could_not_price_reasons": dict(Counter(r["reason"] for r in cnp)),
        "n_not_a_call": len(nac),
        "not_a_call_note": "hold / no_recommendation / flag_mechanics change no path: delta_r = 0 by construction, not measured; they are graded only when the trade closes (outcome row, cf_method no_path_change)",
        "n_no_path_change_outcomes_ready": sum(1 for r in nac if r.get("outcome")),
    })
    per_action: Dict[str, Any] = {}
    for act in sorted({r["action"] for r in priced if r["action"] in cf.ALTERING}):
        rs = [r for r in priced if r["action"] == act]
        per_action[act] = {"applied": _stats([r["outcome"]["delta_r"] for r in rs if r["applied"]]),
                           "recommended_only": _stats([r["outcome"]["delta_r"] for r in rs if not r["applied"]])}
    applied = [r["outcome"]["delta_r"] for r in priced if r["applied"] and r["action"] in cf.ALTERING]
    alarm = {"applied_priced": len(applied), "net_delta_r": round(sum(applied), 4) if applied else None,
             "proposes_recommend_mode": len(applied) >= ALARM_MIN_APPLIES and sum(applied) < 0,
             "rule": f"net dR < 0 over >= {ALARM_MIN_APPLIES} priced applies => next review proposes apply_mode: recommend (a proposal, never a flip)"}
    fid = Counter(r["outcome"]["replay_fidelity"] for r in priced if r.get("outcome"))
    open_replays = [{"review_id": r["review_id"], "leg": r["leg"], "to_date": r["to_date"]} for r in cnp if r.get("to_date")]
    return {
        "population": pop, "per_action_class": per_action, "q1_policy_comparison": q1_comparison(results, by_id),
        "calibration_by_evidence_source": calibration(results, by_id), "applied_alarm": alarm,
        "replay_fidelity": dict(fid),
        "touched_packages": sorted({r["order_package_id"] for r in results if r["applied"]}),
        "touched_note": "live-vs-backtest verdicts must split these (a mandate-tightened exit is not the exit Stage 0 validated)",
        "open_trade_replays_to_date": open_replays,
    }


def render(g: Dict[str, Any], window: str) -> str:
    p, q, al = g["population"], g["q1_policy_comparison"], g["applied_alarm"]
    L = [f"## Live review ({window})", "",
         f"**Population:** {p['n_reviews']} reviews on {p['n_packages']} packages. {p['n_altering_calls']} altering call(s) "
         f"(tighten_sl / tp_revise / close): **{p['n_priced']} priced**, **{p['n_could_not_price']} could not price** "
         f"{p['could_not_price_reasons'] or '{}'}. {p['n_not_a_call']} review(s) changed no path "
         f"(hold / no_recommendation / flag_mechanics; {p['n_no_path_change_outcomes_ready']} with a closed trade to grade).",
         f"By action/basis: {p['by_action_basis']}", ""]
    if g["per_action_class"]:
        L += ["| action | book | n | mean dR | worst dR | hit |", "|---|---|---|---|---|---|"]
        for act, d in g["per_action_class"].items():
            for k, lab in (("applied", "applied"), ("recommended_only", "recommended only")):
                s = d[k]
                L.append(f"| {act} | {lab} | {s['n']} | {s['mean_dr']} | {s['worst_dr']} | {s['hit_rate']} |")
        L.append("")
    else:
        L += ["No altering call has been priced yet, so there is no per-action table. (n=0, not zero R.)", ""]
    pp = q["population"]
    L += [f"**Q1: live 0.25 R policy vs shadow 0.5 R policy.** {pp['tighten_reviews']} tighten review(s), {pp['priced']} priced, "
          f"{pp['policy_undefined_judgement_or_thin']} with no ex-ante policy flag (judgement or thin cell), "
          f"{pp['in_comparison']} in the paired comparison ({pp['discordant']} discordant). "
          f"Mean paired dR {q['mean_paired_dr']}. **Verdict: {q['verdict']}**"
          + (f" ({q['verdict_reason']})" if q.get("verdict_reason") else "") + f". Rule: {q['rule']}.", ""]
    if g["calibration_by_evidence_source"]:
        L.append("**Calibration of `judgement_confidence`** (success = dR > 0):")
        for src, c in g["calibration_by_evidence_source"].items():
            L.append(f"- {src}: n={c['n']}, Brier {c['brier']}" + (f", {c['verdict']}" if c.get("verdict") else "")
                     + f", reliability {c['reliability']}")
        L.append("")
    else:
        L += ["**Calibration:** no priced tighten call carries a `judgement_confidence` yet (n=0).", ""]
    L += [f"**Applied-action alarm:** {al['applied_priced']} priced apply(ies), net dR {al['net_delta_r']}; "
          f"proposes recommend mode: {al['proposes_recommend_mode']}. Replay fidelity: {g['replay_fidelity'] or 'n/a'}.",
          f"**Touched packages** ({len(g['touched_packages'])}): split these from untouched ones in every live-vs-backtest verdict."]
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--reviews", default=str(cf.REVIEWS))
    ap.add_argument("--since", help="ISO date: only reviews at/after it")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-outcomes", action="store_true", help="append computed rows for closed trades to outcomes.jsonl")
    a = ap.parse_args(argv)
    if not a.live:
        ap.error("--live is the only wired source; tests call grade() directly")
    reviews = cf.read_jsonl(Path(a.reviews))
    if a.since:
        reviews = [r for r in reviews if r["reviewed_at"] >= a.since]
    packages, trades = cf.load_live_sources(reviews)
    results = cf.price_all(reviews, packages, trades, cf.fetch_candles_live)
    if a.write_outcomes:
        print(f"outcomes appended: {cf.append_outcomes(results)}", file=sys.stderr)
    g = grade(reviews, results)
    window = f"since {a.since}" if a.since else "all reviews on main"
    print(json.dumps(g, indent=1, default=str) if a.json else render(g, window))
    return 0


if __name__ == "__main__":
    sys.exit(main())
