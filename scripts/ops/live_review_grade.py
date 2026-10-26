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

CLAUDE-GRADE-LOOP additions (rules registered here, before any run reads them):
* HOLD vs CLOSE-AT-REVIEW. A ``hold`` call changes no path, so it has no delta against holding; what it
  rejected is closing. For a hold whose trade has CLOSED, ``delta_hold_r = net_r - state.open_r``
  (ESTIMATED, method ``hold_vs_close_at_mark_v1``). Stated bias: the close-now side is the gross mark at
  review and is charged NO cost, while ``net_r`` carries the full stack, so the delta UNDER-states every
  hold by about one round-trip cost -- conservative against the reviewer, never flattering.
* LTR-ALL-ACTIONS (MD-TRADE-DESK, operator 2026-10-26): every altering class in
  ``live_review_counterfactual.ALTERING`` -- tighten_sl, close, partial_close, move_tp / tp_revise, widen_sl,
  change_size, add_entry -- is priced hold-vs-action (``delta_r``), calibrated and given its own use rule; the
  operator adopted the use rules as written ("1", 2026-10-26, MD-LIVE-TIGHTEN-SL ``review_rule``).
* CALIBRATION BY ACTION CLASS (``calibration``): each altering class (success = ``delta_r > 0``) and hold (success =
  ``delta_hold_r > 0``), each stratified by ``evidence_source``, through ``claude_calibration.probability``
  (Brier, reference Brier, skill, over-confidence gap; verdict rules live there).
* BY BRIEF VERSION (``by_skill_sha``): every figure above split by the review's ``skill_sha`` (the blob sha
  of the contract the reviewer followed: live-trade-review SKILL.md for a repo reviewer -- MEASURED
  2026-10-26, recorded 76866a39 = SKILL.md at b21f6fb9 -- or REVIEWER-BRIEF.md for a repo-less one), so an
  amendment's effect is measurable. Versions are never pooled silently; ``unrecorded`` is its own bucket.
* USE RULES (``use_rules``), the generalised apply alarm, one per altering action class over its priced
  calls (applied and recommended-only pooled: either way ``delta_r`` measures the call):
  n < ``USE_MIN_N`` -> ``HOLD_SCOPE`` (INDETERMINATE); 95% CI of mean ``delta_r`` entirely < 0 ->
  ``PROPOSE_NARROW`` (the class goes recommend-only); entirely > 0 AND that class's calibration is not
  OVERCONFIDENT -> ``PROPOSE_WIDEN`` (a candidate for the next scope step); else ``HOLD_SCOPE``.
  Every verdict is a PROPOSAL for the operator (mandates are granted, never self-granted).
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

sys.path.insert(0, str(REPO / "scripts" / "ops"))
import claude_calibration as cal  # noqa: E402

Q1_MIN_DISCORDANT = 10
CAL_MIN_N = 10
ALARM_MIN_APPLIES = 20
USE_MIN_N = 20
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


def hold_vs_close(results: List[dict], reviews_by_id: Dict[str, dict]) -> Dict[str, float]:
    """review_id -> ``delta_hold_r`` (ESTIMATED) for every hold call whose trade has closed."""
    out: Dict[str, float] = {}
    for r in results:
        if r["action"] != "hold" or not r.get("outcome"):
            continue
        open_r = cf._num((reviews_by_id[r["review_id"]].get("state") or {}).get("open_r"))
        net_r = cf._num(r["outcome"].get("net_r"))
        if open_r is not None and net_r is not None:
            out[r["review_id"]] = round(net_r - open_r, 8)
    return out


def _cal_points(results: List[dict], reviews_by_id: Dict[str, dict], hold_d: Dict[str, float]) -> List[tuple]:
    """(action, evidence_source, skill_sha, confidence, success) for every graded call carrying a confidence."""
    pts = []
    for r in results:
        rv = reviews_by_id[r["review_id"]]
        rec = rv.get("recommendation") or {}
        conf = cf._num(rec.get("judgement_confidence"))
        if conf is None:
            continue
        if r["action"] in cf.ALTERING and r["state"] == "priced":   # every altering class (LTR-ALL-ACTIONS)
            d = r["outcome"]["delta_r"]
        elif r["action"] == "hold" and r["review_id"] in hold_d:
            d = hold_d[r["review_id"]]
        else:
            continue
        pts.append((r["action"], rec.get("evidence_source") or "unknown", rv.get("skill_sha"), conf,
                    1.0 if d > 0 else 0.0))
    return pts


def calibration_by_action(points: List[tuple]) -> Dict[str, Any]:
    strata: Dict[str, List[tuple]] = defaultdict(list)
    for act, src, _sha, c, y in points:
        strata[f"{act}/{src}"].append((c, y))
        strata[f"{act}/all"].append((c, y))
    return {k: cal.probability(v) for k, v in sorted(strata.items())}


def by_skill_sha(reviews: List[dict], results: List[dict], hold_d: Dict[str, float], points: List[tuple]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    res_by_id = {r["review_id"]: r for r in results}
    for sha in sorted({rv.get("skill_sha") or "unrecorded" for rv in reviews}):
        rvs = [rv for rv in reviews if (rv.get("skill_sha") or "unrecorded") == sha]
        rs = [res_by_id[rv["review_id"]] for rv in rvs if rv["review_id"] in res_by_id]
        pr = [r["outcome"]["delta_r"] for r in rs if r["state"] == "priced" and r["action"] in cf.ALTERING]
        hd = [hold_d[r["review_id"]] for r in rs if r["review_id"] in hold_d]
        first = min(rv["reviewed_at"] for rv in rvs)
        out[sha] = {"n_reviews": len(rvs), "first_reviewed_at": first,
                    "altering_priced": _stats(pr), "hold_vs_close_graded": _stats(hd),
                    "calibration": cal.probability((c, y) for _a, _s, s, c, y in points if (s or "unrecorded") == sha)}
    return out


def _ci95(xs: List[float]) -> Optional[List[float]]:
    if len(xs) < 2:
        return None
    m, sd = statistics.fmean(xs), statistics.stdev(xs)
    half = _t95(len(xs) - 1) * sd / math.sqrt(len(xs))
    return [round(m - half, 4), round(m + half, 4)]


def use_rules(results: List[dict], cal_by_action: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for act in cf.ALTERING:
        xs = [r["outcome"]["delta_r"] for r in results if r["action"] == act and r["state"] == "priced"]
        ci = _ci95(xs)
        row: Dict[str, Any] = {**_stats(xs), "ci95": ci, "n_applied": sum(1 for r in results if r["action"] == act
                                                                           and r["state"] == "priced" and r["applied"])}
        verdict_cal = (cal_by_action.get(f"{act}/all") or {}).get("verdict", "")
        if len(xs) < USE_MIN_N or ci is None:
            row["verdict"] = f"HOLD_SCOPE (INDETERMINATE: n={len(xs)} < {USE_MIN_N})"
        elif ci[1] < 0:
            row["verdict"] = "PROPOSE_NARROW"
        elif ci[0] > 0 and verdict_cal != "OVERCONFIDENT":
            row["verdict"] = "PROPOSE_WIDEN"
        else:
            row["verdict"] = "HOLD_SCOPE"
        out[act] = row
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
    hold_d = hold_vs_close(results, by_id)
    pts = _cal_points(results, by_id, hold_d)
    cba = calibration_by_action(pts)
    return {
        "population": pop, "per_action_class": per_action, "q1_policy_comparison": q1_comparison(results, by_id),
        "hold_vs_close": {"method": "hold_vs_close_at_mark_v1", "provenance": "estimated",
                          "bias": "close-now side charged no cost: understates every hold by ~one round-trip cost",
                          **_stats(list(hold_d.values()))},
        "calibration": cba, "by_skill_sha": by_skill_sha(reviews, results, hold_d, pts),
        "use_rules": use_rules(results, cba),
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
    h = g["hold_vs_close"]
    L += [f"**Hold vs close-at-review** ({h['provenance']}, {h['method']}; {h['bias']}): n={h['n']}, mean dR {h['mean_dr']}, "
          f"hit {h['hit_rate']}.", ""]
    L.append("**Calibration by action class** (claude_calibration rules; success = the call beat its alternative):")
    if g["calibration"]:
        for k, c in g["calibration"].items():
            L.append(f"- {k}: n={c['n']}, Brier {c['brier']} vs ref {c['brier_ref']}, skill {c['skill']}, "
                     f"over-confidence gap {c['overconfidence_gap']} -> **{c['verdict']}**")
    else:
        L.append("- no graded call carries a `judgement_confidence` yet (n=0).")
    L += ["", "**By contract version** (`skill_sha`: SKILL.md / REVIEWER-BRIEF.md blob; never pooled):"]
    for sha, v in g["by_skill_sha"].items():
        L.append(f"- `{sha[:8]}` (from {v['first_reviewed_at'][:16]}): {v['n_reviews']} reviews, altering priced "
                 f"n={v['altering_priced']['n']} mean dR {v['altering_priced']['mean_dr']}, hold graded "
                 f"n={v['hold_vs_close_graded']['n']} mean {v['hold_vs_close_graded']['mean_dr']}, calibration "
                 f"{v['calibration']['verdict']}")
    L += ["", "**Use rules** (proposals only; the operator grants scope):"]
    for act, u in g["use_rules"].items():
        L.append(f"- {act}: n={u['n']} (applied {u['n_applied']}), mean dR {u['mean_dr']}, CI95 {u['ci95']} -> **{u['verdict']}**")
    L.append("")
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
