#!/usr/bin/env python3
# wiring: manual-only — LTR-CLASS-GRADE one-shot per-class verdict over the whole live-review record; re-run by hand or by a later grading lane. No timer.
"""Grade every live-review action class from the record we already have (lane LTR-CLASS-GRADE, 2026-11-01).

    python3 scripts/research/ltr_class_grade.py --out comms/research/ltr_class_grade/verdict.json

Pre-registration: comms/research/ltr_class_grade/PREREGISTRATION.md (committed before this ran).

POPULATION: ``comms/live_review/reviews.jsonl`` on origin/main UNION origin/live-review/rows, de-duplicated by
review_id. Packages / trades from the VM journal (scripts/ops/diag_fetch.sh), candles from the bot API.

PRICING: scripts/research/live_review_counterfactual.py::price_all, unchanged except the candle-coverage guard
landed with this lane. ``hold`` has no path change, so it is priced as the decision it was: HOLD vs the one
alternative every hold rejected, CLOSE at the review-bar open, using the same paired replay net of the same cost
stack (delta = -(close - hold)). Positive = holding beat closing.

STATS: mean delta R; CI95 by a call-level percentile bootstrap AND a package-cluster bootstrap (10,000 draws, seed
20261101); calibration verdict from scripts/ops/live_review_grade.py; per ISO week / month; per account / leg.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

import live_review_counterfactual as cf  # noqa: E402
import live_review_grade as lrg  # noqa: E402

from functools import lru_cache  # noqa: E402

#: one fetch per (symbol, interval) for the whole run, so every pass prices against the SAME bars
candles = lru_cache(maxsize=None)(cf.fetch_candles_live)

CLASSES = ("close", "partial_close", "tighten_sl", "move_tp", "widen_sl", "hold")
SEED, DRAWS, MIN_N = 20261101, 10_000, 20


def _git_rows(ref: str) -> List[dict]:
    p = subprocess.run(["git", "show", f"{ref}:comms/live_review/reviews.jsonl"], capture_output=True, text=True, cwd=REPO)
    if p.returncode != 0:
        print(f"ltr_class_grade: {ref} unreadable: {p.stderr.strip()[:200]}", file=sys.stderr)
        return []
    return [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip() and not ln.startswith('{"_meta"')]


def load_reviews(refs: List[str]) -> Dict[str, Any]:
    by_id: Dict[str, dict] = {}
    per_ref = {}
    for ref in refs:
        rows = _git_rows(ref)
        per_ref[ref] = len(rows)
        for r in rows:
            by_id.setdefault(r["review_id"], r)
    return {"rows": sorted(by_id.values(), key=lambda r: r["reviewed_at"]), "per_ref": per_ref}


def load_journal() -> Dict[str, Any]:
    pk = cf.fetch_diag("journal?table=order_packages&limit=1000")
    pk = pk.get("rows", pk) if isinstance(pk, dict) else pk
    trades: Dict[int, dict] = {}
    off = 0
    while True:
        page = cf.fetch_diag(f"journal?table=trades&limit=1000&offset={off}")
        page = page.get("rows", page) if isinstance(page, dict) else page
        trades.update({int(t["id"]): t for t in page})
        if len(page) < 1000:
            break
        off += 1000
    return {"packages": {p["order_package_id"]: p for p in pk}, "trades": trades}


def boot_ci(xs: List[float], rng: random.Random) -> Optional[List[float]]:
    if len(xs) < 2:
        return None
    n = len(xs)
    ms = sorted(statistics.fmean(rng.choice(xs) for _ in range(n)) for _ in range(DRAWS))
    return [round(ms[int(0.025 * DRAWS)], 4), round(ms[int(0.975 * DRAWS) - 1], 4)]


def cluster_ci(pairs: List[tuple], rng: random.Random) -> Optional[List[float]]:
    """pairs = (cluster_key, x). Resample clusters, mean over all calls in the drawn clusters."""
    groups: Dict[str, List[float]] = defaultdict(list)
    for k, x in pairs:
        groups[k].append(x)
    keys = list(groups)
    if len(keys) < 2:
        return None
    ms = []
    for _ in range(DRAWS):
        xs = [x for k in (rng.choice(keys) for _ in keys) for x in groups[k]]
        ms.append(statistics.fmean(xs))
    ms.sort()
    return [round(ms[int(0.025 * DRAWS)], 4), round(ms[int(0.975 * DRAWS) - 1], 4)]


def _week(ts: str) -> str:
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _summ(xs: List[float]) -> Dict[str, Any]:
    if not xs:
        return {"n": 0, "mean_dr": None, "sum_dr": None}
    return {"n": len(xs), "mean_dr": round(statistics.fmean(xs), 4), "sum_dr": round(sum(xs), 4),
            "hit_rate": round(sum(1 for x in xs if x > 0) / len(xs), 3)}


def verdict(n: int, mean: Optional[float], ci: Optional[List[float]], cci: Optional[List[float]], cal: str,
            regime: Dict[str, Any]) -> Dict[str, str]:
    if n < MIN_N or mean is None or ci is None:
        return {"verdict": "INDETERMINATE", "why": f"P1 fails: n={n} priced < {MIN_N}"}
    if mean <= 0 or ci[1] < 0 or (cci and cci[1] < 0):
        return {"verdict": "FAIL", "why": f"mean {mean} / CI95 {ci} / cluster CI95 {cci}"}
    fails = []
    if ci[0] <= 0:
        fails.append(f"P3 CI95 {ci} not > 0")
    if cal == "OVERCONFIDENT":
        fails.append("P4 calibration OVERCONFIDENT")
    if not regime.get("p5_pass"):
        fails.append(f"P5 regime: {regime.get('p5_why')}")
    if not cci or cci[0] <= 0:
        fails.append(f"P6 cluster CI95 {cci} not > 0")
    return {"verdict": "PASS", "why": "P1-P6 hold"} if not fails else {"verdict": "INDETERMINATE", "why": "; ".join(fails)}


def regime(rows: List[dict]) -> Dict[str, Any]:
    wk: Dict[str, List[float]] = defaultdict(list)
    mo: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        wk[_week(r["reviewed_at"])].append(r["delta_r"])
        mo[r["reviewed_at"][:7]].append(r["delta_r"])
    out: Dict[str, Any] = {"by_week": {k: _summ(v) for k, v in sorted(wk.items())},
                           "by_month": {k: _summ(v) for k, v in sorted(mo.items())}}
    if not rows:
        out.update(p5_pass=False, p5_why="no priced calls")
        return out
    best = max(wk, key=lambda k: sum(wk[k]))
    rest = [x for k, v in wk.items() if k != best for x in v]
    m_rest = statistics.fmean(rest) if rest else None
    big = [k for k, v in wk.items() if len(v) >= 3]
    pos = [k for k in big if statistics.fmean(wk[k]) > 0]
    ok = m_rest is not None and m_rest > 0 and big and len(pos) * 2 > len(big)
    out.update(best_week=best, mean_without_best_week=None if m_rest is None else round(m_rest, 4),
               weeks_with_ge3=len(big), weeks_positive=len(pos), p5_pass=bool(ok),
               p5_why=f"mean w/o best week {best} = {None if m_rest is None else round(m_rest, 4)}; "
                      f"{len(pos)}/{len(big)} weeks (n>=3) positive")
    return out


def realised_anchored(reviews: List[dict], packages: Dict[str, dict], trades: Dict[int, dict]) -> Dict[str, Any]:
    """close / hold calls NOT applied, priced as close-at-review-open (net) minus the REALISED net R."""
    captured: List[Optional[float]] = []
    orig_tad, orig_fid = cf.trade_action_delta, cf._fidelity

    def tad(action, rec, **kw):                       # capture close_net, keep the harness's own arithmetic
        captured.append(kw.get("close_net"))
        return orig_tad(action, rec, **kw)

    cf.trade_action_delta = tad
    cf._fidelity = lambda h, r: "replay_matches_realised" if h is not None else "unvalidated"
    out: Dict[str, List[tuple]] = defaultdict(list)
    try:
        for rv in reviews:
            act = (rv.get("recommendation") or {}).get("action")
            if rv.get("applied"):
                continue
            as_close = dict(rv, recommendation=dict(rv.get("recommendation") or {}, action="close"))
            captured.clear()
            r = cf.price_all([as_close], packages, trades, candles)[0]
            if r["state"] != "priced" or not captured or captured[-1] is None or r["outcome"]["applied"]:
                continue
            d = captured[-1] - r["outcome"]["net_r"]
            out[act].append((rv["order_package_id"], -d if act == "hold" else d))
    finally:
        cf.trade_action_delta, cf._fidelity = orig_tad, orig_fid
    rng = random.Random(SEED + 1)
    return {c: {**_summ([x for _, x in v]), "n_packages": len({k for k, _ in v}),
                "ci95_call_bootstrap": boot_ci([x for _, x in v], rng),
                "ci95_package_cluster_bootstrap": cluster_ci(v, rng)} for c, v in out.items()}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refs", default="origin/main,origin/live-review/rows")
    ap.add_argument("--out", default=str(REPO / "comms/research/ltr_class_grade/verdict.json"))
    ap.add_argument("--priced-out", default=None, help="optional per-call jsonl (review_id, class, delta, state)")
    a = ap.parse_args(argv)
    rng = random.Random(SEED)

    src = load_reviews(a.refs.split(","))
    reviews = src["rows"]
    j = load_journal()
    packages, trades = j["packages"], j["trades"]
    res = cf.price_all(reviews, packages, trades, candles)
    by_id = {r["review_id"]: r for r in reviews}

    # hold priced as hold-vs-close (paired replay, net of cost)
    holds = [dict(r, recommendation=dict(r.get("recommendation") or {}, action="close"))
             for r in reviews if (r.get("recommendation") or {}).get("action") == "hold"]
    hres = {h["review_id"]: h for h in cf.price_all(holds, packages, trades, candles)}

    calls: List[dict] = []
    for r in res:
        rv = by_id[r["review_id"]]
        act = (rv.get("recommendation") or {}).get("action")
        if act == "hold":
            h = hres[r["review_id"]]
            state, reason = h["state"], h.get("reason")
            d = -h["outcome"]["delta_r"] if state == "priced" else None
            applied = False
        else:
            state, reason = r["state"], r.get("reason")
            d = r["outcome"]["delta_r"] if state == "priced" else None
            applied = bool((r.get("outcome") or {}).get("applied"))
        calls.append({"review_id": r["review_id"], "class": act, "state": state, "reason": reason, "delta_r": d,
                      "applied": applied, "reviewed_at": rv["reviewed_at"], "package": rv["order_package_id"],
                      "leg": rv.get("leg"), "accounts": rv.get("accounts") or [],
                      "basis": (rv.get("recommendation") or {}).get("evidence_source"),
                      "confidence": (rv.get("recommendation") or {}).get("judgement_confidence"),
                      "fidelity": (r.get("outcome") or (hres.get(r["review_id"]) or {}).get("outcome") or {}).get("replay_fidelity")})

    # SENSITIVITY (reported, never a pass clause): the harness refuses a not-applied call whose hold replay misses
    # the realised exit by > 0.15 R (replay_mismatch), which may select. Re-price close / hold ANCHORED ON THE
    # REALISED EXIT instead (delta = close-at-review-open net - realised net), which needs no hold replay at all.
    sens = realised_anchored([r for r in reviews if (r.get("recommendation") or {}).get("action") in ("close", "hold")],
                             packages, trades)

    cba = lrg.grade(reviews, res)["calibration"]
    classes: Dict[str, Any] = {}
    for c in sorted(set(CLASSES) | {x["class"] for x in calls}, key=lambda k: (k not in CLASSES, k)):
        cs = [x for x in calls if x["class"] == c]
        pr = [x for x in cs if x["state"] == "priced"]
        xs = [x["delta_r"] for x in pr]
        reasons = Counter(x["reason"] for x in cs if x["state"] != "priced")
        ci = boot_ci(xs, rng)
        cci = cluster_ci([(x["package"], x["delta_r"]) for x in pr], rng)
        cal = (cba.get(f"{c}/all") or {}).get("verdict", "n/a") if c != "hold" else "n/a (hold priced vs close here)"
        reg = regime(pr)
        by_acct: Dict[str, List[float]] = defaultdict(list)
        by_leg: Dict[str, List[float]] = defaultdict(list)
        for x in pr:
            for acc in x["accounts"]:
                by_acct[acc].append(x["delta_r"])
            by_leg[x["leg"] or "?"].append(x["delta_r"])
        row = {"n_calls": len(cs), "n_priced": len(pr), "n_packages_priced": len({x["package"] for x in pr}),
               "share_unpriced": round(1 - len(pr) / len(cs), 3) if cs else None,
               "unpriced_reasons": dict(reasons), **_summ(xs), "ci95_call_bootstrap": ci,
               "ci95_package_cluster_bootstrap": cci, "calibration_verdict": cal,
               "applied": _summ([x["delta_r"] for x in pr if x["applied"]]),
               "recommended_only": _summ([x["delta_r"] for x in pr if not x["applied"]]),
               "replay_fidelity": dict(Counter(x["fidelity"] for x in pr)),
               "by_account": {k: _summ(v) for k, v in sorted(by_acct.items())},
               "by_leg": {k: _summ(v) for k, v in sorted(by_leg.items())},
               "regime": reg}
        row.update(verdict(len(pr), row["mean_dr"], ci, cci, cal, reg))
        classes[c] = row

    out = {"schema": "ltr_class_grade/v1", "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "preregistration": "comms/research/ltr_class_grade/PREREGISTRATION.md",
           "harness": "scripts/research/live_review_counterfactual.py::price_all (paired_replay_v1 / replay_v1), net of cost_legs",
           "population": {"refs": src["per_ref"], "n_reviews_union": len(reviews),
                          "first": reviews[0]["reviewed_at"] if reviews else None,
                          "last": reviews[-1]["reviewed_at"] if reviews else None,
                          "by_action": dict(Counter((r.get("recommendation") or {}).get("action") for r in reviews)),
                          "n_packages_journal": len(packages), "n_trades_journal": len(trades)},
           "classes": classes,
           "sensitivity_realised_anchored_not_applied": sens}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=False) + "\n")
    if a.priced_out:
        with open(a.priced_out, "w") as f:
            for x in calls:
                f.write(json.dumps({k: x[k] for k in ("review_id", "class", "state", "reason", "delta_r", "applied",
                                                       "reviewed_at", "package", "leg", "fidelity")}) + "\n")
    for c, row in classes.items():
        print(f"{c:14s} n_calls={row['n_calls']:4d} priced={row['n_priced']:4d} mean={row['mean_dr']} "
              f"ci={row['ci95_call_bootstrap']} cluster={row['ci95_package_cluster_bootstrap']} -> {row['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
