#!/usr/bin/env python3
# wiring: research-script-run.yml via research/queue/RQ-20261009-900.yaml (run.commands) -- the registered grader of that
# unit. Tier-1, observe-only: reads a committed backtest corpus, writes verdict.json; no config, no order path.
"""TP-PREDICT-GRADER: apply RULE-RQ1009-900-MFE-HEAD-VS-NAIVE-TP to ml2_bracket_train_eval output.

The rule is quoted from research/queue/RQ-20261009-900.yaml (registered 2026-10-09, registered_before_run: true) and
is NOT edited here:

    A stratum is SHARPER IF the head beats ALL FOUR baselines (improvement above that baseline's null p95) at >= 3 of
    the 5 quantiles, at EVERY split in {0.55, 0.65, 0.75}, AND neither of the stratum's two legs, graded alone,
    reverses the sign of the pooled improvement at >= 3 of 5 quantiles.
    PASS IF at least one stratum is SHARPER and its eval n >= 88. HONEST_NEGATIVE IF every stratum with eval n >= 88
    fails. INDETERMINATE for a stratum with eval n < 88. A head that beats B1-B3 but not B4 is NOT a pass.
    MIXED (some strata SHARPER, some not) is reported per stratum and is not averaged.

How each clause is computed (every choice below is a reading of the text, stated so it can be checked):

* "beats ALL FOUR ... above that baseline's null p95" is `ml2_bracket_train_eval.evaluate(outcome="mfe_r")`'s
  per-quantile `gate_state == beats_baseline_and_null`: every one of B1..B4 graded `beats_baseline_and_null` against
  that quantile's shuffled-label null p95 (control_trials >= 20, enforced). An unavailable baseline fails closed.
* Quantiles are the five registered ones (0.5 .. 0.9); splits are 0.55 / 0.65 / 0.75; strata are the corpus `stratum`
  column, each evaluated on its own rows only (never pooled across strata).
* "eval n" is the stratum's n_eval at split 0.65, the split the unit's power basis sizes (last 35%: 88 floor).
* The per-leg sign check: each leg is evaluated ALONE (its own chronological split, own train-fold baselines) at
  EVERY split. At a split, a leg "reverses the sign of the pooled improvement" when, for some baseline Bk, the sign of
  the leg's improvement vs Bk is opposite to the stratum's improvement vs Bk at >= 3 of the 5 quantiles (both
  non-null and non-zero). A leg that reverses at any split fails the stratum. A leg the evaluator could not grade
  (insufficient_n) leaves the check UNMEASURED, which makes a stratum that otherwise cleared the sharp clause
  INDETERMINATE -- never SHARPER, and never HONEST_NEGATIVE on a check that was not run.
* Verdict words map to the result contract: PASS -> pass, HONEST_NEGATIVE -> fail, INDETERMINATE -> indeterminate
  (the rule's own word is kept in `rule_verdict`). Per-stratum states are in `measurement.strata`, never averaged.
* MACE (calibration) is reported per stratum and split; the rule does not gate on it.

Prediction quality only: a PASS says the head's MFE forecast is sharper, not that it makes money (that is step 2,
RQ-20261009-901).

Usage:
    python3 scripts/research/tp_predict_grader.py --corpus <ml2_live_leg_corpus.jsonl> --out <dir>
    python3 scripts/research/tp_predict_grader.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RULE_ID = "RULE-RQ1009-900-MFE-HEAD-VS-NAIVE-TP"
RULE_REGISTERED_AT = "2026-10-09"
SPLITS = (0.55, 0.65, 0.75)
HEADLINE_SPLIT = 0.65
QUANTILES = (0.5, 0.6, 0.7, 0.8, 0.9)
BASELINES = ("B1", "B2", "B3", "B4")
MIN_SHARP_QUANTILES = 3          # ">= 3 of the 5 quantiles"
MIN_REVERSED_QUANTILES = 3       # "reverses the sign ... at >= 3 of 5 quantiles"
EVAL_N_FLOOR = 88                # "eval n >= 88" (power basis: (1.96+0.8416)^2 / 0.30^2 = 87.2 -> 88)
MIN_CONTROL_TRIALS = 20          # "control_trials >= 20"
SHARP = "beats_baseline_and_null"

Evaluator = Callable[..., Dict[str, Any]]


def _default_evaluator() -> Evaluator:
    from ml2_bracket_train_eval import evaluate  # noqa: WPS433 (heavy import kept off the selftest path)
    return evaluate


def _sharp_count(res: Dict[str, Any]) -> int:
    return sum(1 for s in res.get("sharpness") or [] if s.get("gate_state") == SHARP)


def _improvements(res: Dict[str, Any]) -> Dict[str, Dict[float, Optional[float]]]:
    """{baseline: {q: improvement or None}} from one evaluate() result."""
    out: Dict[str, Dict[float, Optional[float]]] = {b: {} for b in BASELINES}
    for s in res.get("sharpness") or []:
        q = round(float(s.get("q")), 4)
        for b in BASELINES:
            v = s.get(f"vs_{b}_improvement")
            out[b][q] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return out


def _sign(v: Optional[float]) -> int:
    return 0 if v is None or v == 0 else (1 if v > 0 else -1)


def leg_sign_check(stratum_res: Dict[str, Any], leg_res: Dict[str, Any]) -> Dict[str, Any]:
    """One leg vs its stratum at ONE split. state: ok | reverses | unmeasured."""
    if not leg_res.get("sharpness"):
        return {"state": "unmeasured", "why": f"leg evaluate verdict {leg_res.get('verdict')!r} "
                f"(n_eval {(leg_res.get('population') or {}).get('n_eval')})"}
    pooled, leg = _improvements(stratum_res), _improvements(leg_res)
    reversed_by_b: Dict[str, int] = {}
    for b in BASELINES:
        reversed_by_b[b] = sum(1 for q in QUANTILES
                               if _sign(pooled[b].get(q)) * _sign(leg[b].get(round(q, 4))) == -1)
    worst = max(reversed_by_b.values()) if reversed_by_b else 0
    return {"state": "reverses" if worst >= MIN_REVERSED_QUANTILES else "ok",
            "reversed_quantiles_by_baseline": reversed_by_b}


def _summary(res: Dict[str, Any]) -> Dict[str, Any]:
    pop = res.get("population") or {}
    return {"verdict_evaluator": res.get("verdict"), "n_train": pop.get("n_train"), "n_eval": pop.get("n_eval"),
            "usable": pop.get("usable"), "sharp_vs_all_four": _sharp_count(res), "mace": res.get("mace"),
            "gate_state_by_q": {str(s.get("q")): s.get("gate_state") for s in res.get("sharpness") or []},
            "improvement_by_baseline": {b: {str(q): v for q, v in d.items()}
                                        for b, d in _improvements(res).items()}}


def grade_stratum(name: str, rows: Sequence[Dict[str, Any]], ev: Evaluator, *, control_trials: int,
                  seed: int) -> Dict[str, Any]:
    kw = dict(outcome="mfe_r", quantiles=QUANTILES, control_trials=control_trials, seed=seed)
    legs = sorted({str(r.get("leg")) for r in rows})
    by_split: Dict[str, Any] = {}
    leg_checks: Dict[str, Dict[str, Any]] = {lg: {} for lg in legs}
    for sp in SPLITS:
        res = ev(list(rows), split=sp, **kw)
        by_split[str(sp)] = _summary(res)
        for lg in legs:
            lres = ev([r for r in rows if str(r.get("leg")) == lg], split=sp, **kw)
            leg_checks[lg][str(sp)] = leg_sign_check(res, lres)
    n_eval = by_split[str(HEADLINE_SPLIT)]["n_eval"]
    sharp_every_split = all((by_split[str(sp)]["sharp_vs_all_four"] or 0) >= MIN_SHARP_QUANTILES for sp in SPLITS)
    states = [c["state"] for lg in legs for c in leg_checks[lg].values()]
    if not isinstance(n_eval, int) or n_eval < EVAL_N_FLOOR:
        state, why = "indeterminate", f"eval n {n_eval} < {EVAL_N_FLOOR} at split {HEADLINE_SPLIT}"
    elif not sharp_every_split:
        state, why = "not_sharper", ("head does not beat all four baselines above the null at >= 3 of 5 quantiles at "
                                     "every split: " + ", ".join(f"{sp}: {by_split[str(sp)]['sharp_vs_all_four']}/5"
                                                                 for sp in SPLITS))
    elif "reverses" in states:
        state, why = "not_sharper", "a leg graded alone reverses the pooled improvement's sign at >= 3 of 5 quantiles"
    elif "unmeasured" in states:
        state, why = "indeterminate", "sharp clause met, but the per-leg sign check could not be graded for every leg"
    else:
        state, why = "sharper", f"beats all four at >= 3/5 quantiles at every split; no leg reverses; eval n {n_eval}"
    return {"stratum": name, "legs": legs, "state": state, "why": why, "eval_n": n_eval,
            "sharp_every_split": sharp_every_split, "by_split": by_split, "leg_sign_check": leg_checks}


def grade(rows: Sequence[Dict[str, Any]], *, evaluator: Optional[Evaluator] = None, control_trials: int = 20,
          seed: int = 0) -> Dict[str, Any]:
    """The run's verdict.json (dict) for RULE-RQ1009-900 over a corpus's rows."""
    if control_trials < MIN_CONTROL_TRIALS:
        raise ValueError(f"control_trials {control_trials} < {MIN_CONTROL_TRIALS}: the rule registers >= 20")
    ev = evaluator or _default_evaluator()
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if r.get("stratum"):
            groups.setdefault(str(r["stratum"]), []).append(r)
    if not groups:
        return {"verdict": "not_applicable", "read_state": "no_data", "n": None,
                "population": "RQ-20261009-900: corpus carries no stratum-labelled rows -- nothing graded",
                "note": "no strata in corpus", "rule_verdict": None}
    strata = [grade_stratum(s, groups[s], ev, control_trials=control_trials, seed=seed) for s in sorted(groups)]
    powered = [s for s in strata if isinstance(s["eval_n"], int) and s["eval_n"] >= EVAL_N_FLOOR]
    if any(s["state"] == "sharper" for s in strata):
        rule_verdict, verdict = "PASS", "pass"
    elif powered and all(s["state"] == "not_sharper" for s in powered):
        rule_verdict, verdict = "HONEST_NEGATIVE", "fail"
    else:
        rule_verdict, verdict = "INDETERMINATE", "indeterminate"
    mixed = len({s["state"] for s in strata}) > 1
    n_eval = sum(s["eval_n"] for s in strata if isinstance(s["eval_n"], int))
    return {
        "verdict": verdict, "read_state": "measured", "rule_verdict": rule_verdict,
        "n": n_eval,
        "population": (f"RQ-20261009-900: {len(strata)} strata graded separately, never pooled "
                       f"({', '.join(f'{s['stratum']} eval n {s['eval_n']}' for s in strata)} at split {HEADLINE_SPLIT}); "
                       f"n = summed eval rows at the headline split; outcome mfe_r, 5 quantiles x 3 splits, B1-B4 "
                       f"each gated by the shuffled-label null p95 (control_trials {control_trials})"),
        "note": (f"{RULE_ID}: {rule_verdict}" + (" (MIXED, reported per stratum)" if mixed else "") + " | "
                 + "; ".join(f"{s['stratum']}={s['state']} ({s['why']})" for s in strata)
                 + " | prediction quality only, NOT evidence of P&L (step 2 is RQ-20261009-901)"),
        "measurement": {"rule_id": RULE_ID, "rule_registered_at": RULE_REGISTERED_AT, "rule_verdict": rule_verdict,
                        "mixed": mixed, "splits": list(SPLITS), "quantiles": list(QUANTILES),
                        "eval_n_floor": EVAL_N_FLOOR, "control_trials": control_trials, "seed": seed,
                        "strata_passing": [s["stratum"] for s in strata if s["state"] == "sharper"],
                        "strata": strata},
    }


# ── selftest: planted evaluator outputs, so every branch of the rule is exercised without the SGD fits ──────────────
def _fake_res(n_eval: int, sharp_qs: int, impr: float = 0.1) -> Dict[str, Any]:
    sh = []
    for i, q in enumerate(QUANTILES):
        s = {"q": q, "gate_state": SHARP if i < sharp_qs else "not_all_four"}
        for b in BASELINES:
            s[f"vs_{b}_improvement"] = impr
        sh.append(s)
    return {"verdict": "x", "population": {"n_eval": n_eval, "n_train": n_eval * 2, "usable": n_eval * 3},
            "sharpness": sh if n_eval >= 30 else [], "mace": 0.03}


def _planted(spec: Dict[str, Dict[str, Any]]) -> Evaluator:
    """spec[stratum] = {"n": eval n, "sharp": k, "legs": {leg: (n_eval, improvement sign)}}"""
    def ev(rows, *, split, **_kw):
        st, legs = str(rows[0]["stratum"]), {str(r["leg"]) for r in rows}
        sp = spec[st]
        if len(legs) == 1:
            ln, sign = sp["legs"][next(iter(legs))]
            return _fake_res(ln, 0, 0.1 * sign)
        k = sp["sharp"][split] if isinstance(sp["sharp"], dict) else sp["sharp"]
        return _fake_res(sp["n"], k)
    return ev


def _rows(spec: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"stratum": s, "leg": lg} for s, sp in spec.items() for lg in sp["legs"]]


def selftest() -> int:
    ok = True

    def case(label: str, spec: Dict[str, Dict[str, Any]], want: str, want_states: Dict[str, str]) -> None:
        nonlocal ok
        v = grade(_rows(spec), evaluator=_planted(spec))
        got = {s["stratum"]: s["state"] for s in v["measurement"]["strata"]}
        good = v["rule_verdict"] == want and got == want_states
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: {v['rule_verdict']} {got}")

    up = {"a": (60, 1), "b": (60, 1)}
    case("one stratum sharper -> PASS", {"S1": {"n": 120, "sharp": 4, "legs": up}}, "PASS", {"S1": "sharper"})
    case("3/5 at two splits, 2/5 at one -> not sharper -> HONEST_NEGATIVE",
         {"S1": {"n": 120, "sharp": {0.55: 3, 0.65: 3, 0.75: 2}, "legs": up}}, "HONEST_NEGATIVE", {"S1": "not_sharper"})
    case("a leg reverses the sign -> not sharper",
         {"S1": {"n": 120, "sharp": 5, "legs": {"a": (60, 1), "b": (60, -1)}}}, "HONEST_NEGATIVE", {"S1": "not_sharper"})
    case("eval n 74 < 88 -> INDETERMINATE even when sharp",
         {"S1": {"n": 74, "sharp": 5, "legs": up}}, "INDETERMINATE", {"S1": "indeterminate"})
    case("leg too thin to grade alone -> INDETERMINATE, never PASS",
         {"S1": {"n": 120, "sharp": 5, "legs": {"a": (60, 1), "b": (20, 1)}}}, "INDETERMINATE", {"S1": "indeterminate"})
    case("leg too thin but sharp clause fails -> still not sharper",
         {"S1": {"n": 120, "sharp": 1, "legs": {"a": (60, 1), "b": (20, 1)}}}, "HONEST_NEGATIVE", {"S1": "not_sharper"})
    case("MIXED: S1 n-short, S2 sharper -> PASS on S2 only",
         {"S1": {"n": 74, "sharp": 5, "legs": up}, "S2": {"n": 200, "sharp": 3, "legs": up}},
         "PASS", {"S1": "indeterminate", "S2": "sharper"})
    case("powered strata all fail, one underpowered -> HONEST_NEGATIVE",
         {"S1": {"n": 74, "sharp": 5, "legs": up}, "S2": {"n": 200, "sharp": 0, "legs": up}},
         "HONEST_NEGATIVE", {"S1": "indeterminate", "S2": "not_sharper"})
    try:
        grade([{"stratum": "S", "leg": "a"}], evaluator=_planted({}), control_trials=5)
        ok = False
        print("  FAIL  control_trials < 20 must be refused")
    except ValueError:
        print("  PASS  control_trials < 20 refused")
    print("tp_predict_grader self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus")
    ap.add_argument("--out", help="directory: verdict.json + tp_predict_grader.json are written here")
    ap.add_argument("--control-trials", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.corpus or not a.out:
        ap.error("--corpus and --out are required (or --selftest)")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        rows = [json.loads(ln) for ln in Path(a.corpus).read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, ValueError) as exc:
        v: Dict[str, Any] = {"verdict": "not_applicable", "read_state": "producer_failed", "n": None,
                             "population": f"RQ-20261009-900: corpus {a.corpus} unreadable -- NOT GRADED",
                             "note": f"producer_failed: {type(exc).__name__}: {exc}"}
    else:
        v = grade(rows, control_trials=a.control_trials, seed=a.seed)
    v["data_inputs"] = [a.corpus]
    (out / "tp_predict_grader.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    slim = {k: v[k] for k in ("verdict", "read_state", "population", "n", "note", "data_inputs") if k in v}
    if "measurement" in v:
        slim["measurement"] = v["measurement"]
    (out / "verdict.json").write_text(json.dumps(slim, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": v["verdict"], "rule_verdict": v.get("rule_verdict"), "n": v["n"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
