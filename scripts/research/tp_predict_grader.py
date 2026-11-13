#!/usr/bin/env python3
# wiring: research/queue units (run.command) via research-script-run.yml -- the token-free runner
"""TP-PREDICT-GRADER · apply RULE-RQ1009-900-MFE-HEAD-VS-NAIVE-TP to ml2_bracket_train_eval output.

WHAT IT IS FOR
--------------
RQ-20261009-900 (TP doctrine, predict-head step 1) registered a rule on 2026-10-09,
before any run, for whether an entry-time MFE-quantile head beats four naive TP
baselines (B1 declared tp_r, B2 class-default tp_r, B3 train R-quantile, B4 the
leg's train %-of-entry quantile) on the six live legs, graded per stratum and never
pooled. `ml2_bracket_train_eval.py --outcome mfe_r` already computes every
per-quantile, per-baseline, null-gated sharpness state; nothing turned those into
the unit's verdict. This script is that grader. It

  1. runs the evaluator CLI once per split in {0.55, 0.65, 0.75}
     (`--outcome mfe_r --per-leg --per-stratum --control-trials 20 --no-dispersion
     --split <s> --out <out>/eval_split_<s>.json`) -- the evaluator's own output is
     KEPT next to the verdict, so the grade can be re-derived by hand;
  2. grades each stratum against the rule, clause by clause (below);
  3. writes `<out>/verdict.json` in the E5 shape script_run.py lands.

It grades the evaluator's fields; it fits nothing and predicts nothing itself.

THE RULE, CLAUSE BY CLAUSE, AND THE EVALUATOR FIELD EACH ONE READS
------------------------------------------------------------------
Quoted from research/queue/RQ-20261009-900.yaml `decision_rule.rule` (not edited):

* "beats ALL FOUR baselines (improvement above that baseline's null p95)" -- at one
  quantile, every `vs_B{1..4}_state == "beats_baseline_and_null"` in that
  quantile's `sharpness` row. The evaluator sets that state only when
  improvement > the quantile's shuffled-label `null_p95`; `baseline_unavailable`
  and every other state fail closed. Cross-checked against the evaluator's own
  `gate_state`; a disagreement is `producer_failed`, never silently resolved.
* "at >= 3 of the 5 quantiles" -- count of such rows over q in
  {0.5, 0.6, 0.7, 0.8, 0.9} >= 3. A result with any other quantile set is refused.
* "at EVERY split in {0.55, 0.65, 0.75}" -- the count above >= 3 in the stratum's
  `per_stratum[<S>]` result of all three runs. A split the evaluator could not
  grade (`insufficient_n` / `not_measured`) makes the stratum INDETERMINATE, not
  failed: the rule cannot be applied to a split with no grade.
* "neither of the stratum's two legs, graded alone, reverses the sign of the
  pooled improvement at >= 3 of 5 quantiles" -- `per_leg[<leg>]` is the leg graded
  alone (its own head, its own folds; that is what `--per-leg` computes). At
  quantile q the leg REVERSES if, for ANY of B1..B4, its `vs_Bk_improvement` and
  the stratum's `vs_Bk_improvement` at q are both non-zero and of opposite sign.
  Veto if a leg reverses at >= 3 quantiles, at ANY split. A leg whose alone-grade
  has no improvement figures (e.g. `insufficient_n`) leaves the veto UNMEASURED:
  if the stratum otherwise clears, it is INDETERMINATE, never SHARPER.
  ⚠️ Two readings were possible and the STRICTER (fail-closed) one is applied:
  "any baseline" rather than one chosen baseline, and "any split" rather than the
  0.65 headline only. Both are stated in verdict.json `measurement.interpretation`.
* "A head that beats B1-B3 but not B4 is NOT a pass" -- implied by "all four";
  a self-test case plants exactly that and requires not-SHARPER.
* "eval n >= 88" -- `per_stratum[<S>].population.n_eval` at split 0.65 (the
  power basis: "the chronologically last 35% ... default split 0.65"). n < 88 ->
  that stratum is INDETERMINATE whatever its clauses say (they are still reported).
* "control_trials >= 20" (statistic) -- passed as `--control-trials 20`; refused
  below 20. `trials_usable` per quantile is reported, not gated (the rule gates
  the configured trial count).
* MACE (statistic) -- reported per stratum and split; the rule does not gate on it.

VERDICT (E5 vocabulary, research/results/README.md)
  PASS            -> verdict `pass`: at least one stratum SHARPER with n >= 88.
                     MIXED (other strata not sharper) is reported per stratum.
  HONEST_NEGATIVE -> verdict `fail`: there is at least one stratum with n >= 88
                     and every such stratum FAILS.
  INDETERMINATE   -> verdict `indeterminate`: anything else (no stratum with
                     n >= 88, or an n >= 88 stratum that could not be graded).
  read_state `measured` when all three evaluator runs produced output;
  `no_data` when the corpus is missing or empty; `producer_failed` when an
  evaluator run broke or its output is malformed (verdict `not_applicable`,
  n null -- never a fabricated 0).

Tier-1 research tooling: reads a corpus, writes only under --out. No config, no
live path, no runtime caller.

Usage:
    python3 scripts/research/tp_predict_grader.py \\
        --corpus comms/research/RQ-20261014-736c-01/38738465656/ml2_live_leg_corpus.jsonl \\
        --out {out_dir} --unit RQ-20261009-900
    python3 scripts/research/tp_predict_grader.py --self-test
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
EVALUATOR = REPO / "scripts" / "research" / "ml2_bracket_train_eval.py"

RULE_ID = "RULE-RQ1009-900-MFE-HEAD-VS-NAIVE-TP"
RULE_REGISTERED_AT = "2026-10-09"
UNIT = "RQ-20261009-900"

SPLITS: Tuple[float, ...] = (0.55, 0.65, 0.75)
N_SPLIT = 0.65
QUANTILES: Tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9)
BASELINES: Tuple[str, ...] = ("B1", "B2", "B3", "B4")
MIN_QUANTILES = 3
EVAL_FLOOR = 88
MIN_CONTROL_TRIALS = 20
#: The CLOSED feature list of the unit's statistic. A result graded on any other
#: set is refused rather than graded.
FEATURES: Tuple[str, ...] = ("risk_frac", "is_long", "confidence", "hour_sin", "hour_cos",
                             "dow", "adx_at_entry", "regime_weight")
#: Strata and their legs, as registered in the unit's question (and carried by
#: ml2_live_leg_corpus.STRATA). The corpus' own leg->stratum map is checked
#: against this; a mismatch makes that stratum INDETERMINATE.
STRATA: Dict[str, Tuple[str, str]] = {
    "S1_bybit2_donchian_4h": ("trend_donchian_eth_4h", "trend_donchian_xrp_4h"),
    "S2_bybit2_pullback_2h": ("xrp_pullback_2h", "ada_pullback_2h"),
    "S3_prop_donchian_1h": ("trend_donchian_eth_prop", "trend_donchian_sol_prop"),
}

BEATS = "beats_baseline_and_null"  # == bracket_quantile.SHARP_BEATS_BASELINE
UNGRADED_VERDICTS = ("insufficient_n", "not_measured")

SHARPER, FAILS, INDETERMINATE = "SHARPER", "FAILS", "INDETERMINATE"


class MalformedResult(Exception):
    """The evaluator's output does not have the shape this grader reads."""


def _split_key(sp: float) -> str:
    return f"{sp:.2f}"


def _sign(v: Any) -> int:
    if v is None:
        return 0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return (f > 0) - (f < 0)


def _rows_by_q(res: Dict[str, Any], where: str) -> Dict[float, Dict[str, Any]]:
    rows = res.get("sharpness")
    if not isinstance(rows, list):
        raise MalformedResult(f"{where}: `sharpness` is not a list")
    out: Dict[float, Dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict) or "q" not in r:
            raise MalformedResult(f"{where}: a sharpness row has no `q`")
        out[round(float(r["q"]), 4)] = r
    return out


def beats_count(res: Dict[str, Any], where: str) -> Dict[str, Any]:
    """Quantiles at which the head beats ALL FOUR baselines above the null p95."""
    rows = _rows_by_q(res, where)
    if sorted(rows) != list(QUANTILES):
        raise MalformedResult(f"{where}: quantiles {sorted(rows)} != registered {list(QUANTILES)}")
    per_q = []
    count = 0
    for q in QUANTILES:
        r = rows[q]
        states = {b: r.get(f"vs_{b}_state") for b in BASELINES}
        if any(s is None for s in states.values()):
            raise MalformedResult(f"{where} q={q}: missing a vs_B*_state (not an R-basis result?)")
        all_four = all(s == BEATS for s in states.values())
        # The evaluator computes the same conjunction as `gate_state`. Two
        # computations of one clause that disagree mean neither is trusted.
        if (r.get("gate_state") == BEATS) != all_four:
            raise MalformedResult(f"{where} q={q}: gate_state {r.get('gate_state')!r} disagrees "
                                  f"with the per-baseline states {states}")
        count += int(all_four)
        per_q.append({"q": q, "beats_all_four": all_four, "states": states,
                      "improvements": {b: r.get(f"vs_{b}_improvement") for b in BASELINES},
                      "null_p95": r.get("null_p95")})
    return {"beats_all_four_count": count, "per_quantile": per_q}


def reversal_count(leg_res: Dict[str, Any], stratum_res: Dict[str, Any],
                   where: str) -> Optional[Dict[str, Any]]:
    """Quantiles at which the leg graded alone reverses the pooled improvement's sign
    against ANY baseline. None when the leg has no improvement figures to compare."""
    if leg_res.get("verdict") in UNGRADED_VERDICTS or not leg_res.get("sharpness"):
        return None
    lrows = _rows_by_q(leg_res, where)
    srows = _rows_by_q(stratum_res, where)
    per_q = []
    count = 0
    comparable_any = False
    for q in QUANTILES:
        lr, sr = lrows.get(q), srows.get(q)
        if lr is None or sr is None:
            raise MalformedResult(f"{where}: quantile {q} missing from the leg or stratum result")
        rev = []
        for b in BASELINES:
            ls, ss = _sign(lr.get(f"vs_{b}_improvement")), _sign(sr.get(f"vs_{b}_improvement"))
            if ls and ss:
                comparable_any = True
                if ls != ss:
                    rev.append(b)
        count += int(bool(rev))
        per_q.append({"q": q, "reversed_vs": rev})
    if not comparable_any:
        return None
    return {"reversal_count": count, "per_quantile": per_q}


def grade_stratum(stratum: str, by_split: Dict[str, Dict[str, Any]],
                  leg_map: Dict[str, str]) -> Dict[str, Any]:
    """Apply the rule to one stratum. ``by_split[<"0.55">]`` is that split's full
    evaluator payload ({"per_stratum": ..., "per_leg": ...})."""
    legs = STRATA[stratum]
    out: Dict[str, Any] = {"stratum": stratum, "legs": list(legs), "splits": {}, "reasons": []}
    found_legs = sorted(lg for lg, s in leg_map.items() if s == stratum)
    if found_legs != sorted(legs):
        out.update(status=INDETERMINATE, n_eval=None,
                   reasons=[f"corpus legs for {stratum} are {found_legs}, registered {sorted(legs)}"])
        return out

    head = by_split[_split_key(N_SPLIT)]["per_stratum"].get(stratum)
    n_eval = None
    if isinstance(head, dict):
        n_eval = (head.get("population") or {}).get("n_eval")
    out["n_eval"] = n_eval
    out["n_eval_split"] = N_SPLIT

    all_graded, all_beat = True, True
    veto, veto_unmeasured = False, False
    for sp in SPLITS:
        k = _split_key(sp)
        res = by_split[k]["per_stratum"].get(stratum)
        cell: Dict[str, Any] = {}
        out["splits"][k] = cell
        if not isinstance(res, dict) or res.get("verdict") in UNGRADED_VERDICTS or not res.get("sharpness"):
            cell["graded"] = False
            cell["evaluator_verdict"] = res.get("verdict") if isinstance(res, dict) else "absent"
            all_graded = False
            continue
        feats = (res.get("population") or {}).get("features")
        if list(feats or []) != list(FEATURES):
            raise MalformedResult(f"{stratum} split {k}: features {feats} != the closed list {list(FEATURES)}")
        bc = beats_count(res, f"{stratum} split {k}")
        cell.update(graded=True, evaluator_verdict=res.get("verdict"), mace=res.get("mace"),
                    n_eval=(res.get("population") or {}).get("n_eval"),
                    control_trials_usable={str(q): (c or {}).get("trials_usable") for q, c in
                                           ((res.get("control") or {}).get("per_quantile") or {}).items()},
                    **bc, beats_at_min_quantiles=bc["beats_all_four_count"] >= MIN_QUANTILES)
        if bc["beats_all_four_count"] < MIN_QUANTILES:
            all_beat = False
        cell["legs"] = {}
        for lg in legs:
            lres = by_split[k]["per_leg"].get(lg)
            rc = reversal_count(lres, res, f"{lg} split {k}") if isinstance(lres, dict) else None
            if rc is None:
                veto_unmeasured = True
                cell["legs"][lg] = {"measured": False,
                                    "evaluator_verdict": lres.get("verdict") if isinstance(lres, dict) else "absent"}
            else:
                v = rc["reversal_count"] >= MIN_QUANTILES
                veto = veto or v
                cell["legs"][lg] = {"measured": True, "vetoes": v,
                                    "n_eval": (lres.get("population") or {}).get("n_eval"), **rc}

    out["clauses"] = {"every_split_graded": all_graded,
                      "beats_all_four_at_3of5_every_split": all_graded and all_beat,
                      "leg_reversal_veto": veto, "leg_reversal_veto_unmeasured": veto_unmeasured}
    reasons = out["reasons"]
    if all_graded and not all_beat:
        sharper_state = FAILS
        reasons.append("does not beat all four baselines above the null p95 at >= 3 of 5 quantiles at every split")
    elif all_graded and veto:
        sharper_state = FAILS
        reasons.append("a leg graded alone reverses the pooled improvement's sign at >= 3 of 5 quantiles")
    elif not all_graded:
        sharper_state = INDETERMINATE
        reasons.append("at least one split could not be graded by the evaluator")
    elif veto_unmeasured:
        sharper_state = INDETERMINATE
        reasons.append("clears the baseline clause but a leg's alone-grade has no improvement figures, "
                       "so the leg-reversal veto could not be measured")
    else:
        sharper_state = SHARPER
    out["sharper_clauses"] = sharper_state
    if n_eval is None or n_eval < EVAL_FLOOR:
        out["status"] = INDETERMINATE
        reasons.insert(0, f"eval n {n_eval} < {EVAL_FLOOR} at split {N_SPLIT} (rule: INDETERMINATE)")
    else:
        out["status"] = sharper_state
    return out


def grade(by_split: Dict[str, Dict[str, Any]], leg_map: Dict[str, str]) -> Dict[str, Any]:
    """Grade every stratum and assign the unit verdict. Raises MalformedResult."""
    for sp in SPLITS:
        p = by_split.get(_split_key(sp))
        if not isinstance(p, dict) or not isinstance(p.get("per_stratum"), dict) \
                or not isinstance(p.get("per_leg"), dict):
            raise MalformedResult(f"split {sp}: evaluator output lacks per_stratum / per_leg")
    strata = {s: grade_stratum(s, by_split, leg_map) for s in STRATA}
    powered = {s: g for s, g in strata.items() if g.get("n_eval") is not None and g["n_eval"] >= EVAL_FLOOR}
    passed = sorted(s for s, g in powered.items() if g["status"] == SHARPER)
    if passed:
        label, verdict = "PASS", "pass"
    elif powered and all(g["status"] == FAILS for g in powered.values()):
        label, verdict = "HONEST_NEGATIVE", "fail"
    else:
        label, verdict = "INDETERMINATE", "indeterminate"
    statuses = {s: g["status"] for s, g in strata.items()}
    return {"rule_outcome": label, "verdict": verdict, "strata_passed": passed,
            "mixed": bool(passed) and any(v != SHARPER for v in statuses.values()),
            "stratum_status": statuses, "per_stratum": strata,
            "n": sum(int(g["n_eval"]) for g in strata.values() if g.get("n_eval") is not None)}


# ── I/O ──────────────────────────────────────────────────────────────────────

def read_leg_map(corpus: Path) -> Tuple[Dict[str, str], int]:
    """leg -> stratum as the corpus rows carry it, and the row count. Reads only
    those two columns' worth of meaning; no outcome is inspected here."""
    leg_map: Dict[str, str] = {}
    n = 0
    with corpus.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(r, dict):
                continue
            n += 1
            lg, st = r.get("leg"), r.get("stratum")
            if lg is not None and st is not None:
                if leg_map.get(str(lg), str(st)) != str(st):
                    leg_map[str(lg)] = "AMBIGUOUS"
                else:
                    leg_map[str(lg)] = str(st)
    return leg_map, n


def run_evaluator(corpus: Path, out_dir: Path, sp: float, control_trials: int,
                  log: List[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    dest = out_dir / f"eval_split_{_split_key(sp)}.json"
    argv = [sys.executable, str(EVALUATOR), "--corpus", str(corpus), "--outcome", "mfe_r",
            "--per-leg", "--per-stratum", "--split", str(sp), "--control-trials", str(control_trials),
            "--no-dispersion", "--out", str(dest)]
    log.append(" ".join(argv[1:]))
    proc = subprocess.run(argv, capture_output=True, text=True)
    (out_dir / f"eval_split_{_split_key(sp)}.log").write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr,
                                                              encoding="utf-8")
    if proc.returncode != 0:
        return None, f"evaluator exit {proc.returncode} at split {sp} (log eval_split_{_split_key(sp)}.log)"
    try:
        return json.loads(dest.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"evaluator output unreadable at split {sp}: {type(exc).__name__}: {exc}"


def _record(unit: Optional[str], corpus_rel: str, read_state: str, verdict: str, n: Optional[int],
            pop_desc: str, note: str, measurement: Dict[str, Any]) -> Dict[str, Any]:
    return {"schema_version": 1, "research_unit": unit, "read_state": read_state, "verdict": verdict,
            "n": n, "population": {"n": n, "description": pop_desc}, "note": note,
            "decision_rule": {"id": RULE_ID, "registered_at": RULE_REGISTERED_AT,
                              "registered_before_run": True},
            "measurement": measurement, "data_inputs": [corpus_rel],
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "produced_by": {"tool": "python3 scripts/research/tp_predict_grader.py",
                            "evaluator": "scripts/research/ml2_bracket_train_eval.py"}}


INTERPRETATION = {
    "beats": "per quantile, every vs_B{1..4}_state == beats_baseline_and_null (improvement > that "
             "quantile's shuffled-label null_p95); cross-checked against gate_state",
    "quantiles": "count over q in {0.5,0.6,0.7,0.8,0.9} >= 3, at each of splits 0.55/0.65/0.75",
    "leg_reversal": "per_leg[<leg>] (leg graded alone: its own head and folds). At q a leg reverses if, for "
                    "ANY baseline, its vs_Bk_improvement and the stratum's are non-zero with opposite sign; "
                    "veto at >= 3 of 5 quantiles at ANY split. STRICTER of two readings (any baseline, any "
                    "split), chosen fail-closed. Leg with no improvement figures -> veto unmeasured -> "
                    "INDETERMINATE if the stratum otherwise clears",
    "n_floor": "per_stratum[<S>].population.n_eval at split 0.65 >= 88, else INDETERMINATE",
    "verdict": "PASS->pass if >=1 stratum SHARPER with n>=88; HONEST_NEGATIVE->fail if >=1 stratum has "
               "n>=88 and every such stratum FAILS; else INDETERMINATE->indeterminate",
    "not_graded": "MACE is reported, not gated (the rule does not gate on it); the evaluator's pooled-all "
                  "headline is in eval_split_*.json but pools strata and is NOT graded",
}


def run(corpus: Path, out_dir: Path, unit: Optional[str], control_trials: int) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        corpus_rel = corpus.resolve().relative_to(REPO).as_posix()
    except ValueError:
        corpus_rel = corpus.as_posix()
    if control_trials < MIN_CONTROL_TRIALS:
        raise SystemExit(f"--control-trials {control_trials} < {MIN_CONTROL_TRIALS} (the rule's floor)")
    base_m: Dict[str, Any] = {"splits": list(SPLITS), "quantiles": list(QUANTILES),
                              "control_trials": control_trials, "eval_floor": EVAL_FLOOR,
                              "features": list(FEATURES), "interpretation": INTERPRETATION}
    if not corpus.is_file():
        return _record(unit, corpus_rel, "no_data", "not_applicable", None,
                       f"{UNIT}: corpus {corpus_rel} does not exist -- could not look",
                       "no_data: corpus file missing", base_m)
    leg_map, n_rows = read_leg_map(corpus)
    if n_rows == 0:
        return _record(unit, corpus_rel, "no_data", "not_applicable", None,
                       f"{UNIT}: corpus {corpus_rel} has no rows", "no_data: empty corpus", base_m)
    log: List[str] = []
    by_split: Dict[str, Dict[str, Any]] = {}
    for sp in SPLITS:
        payload, err = run_evaluator(corpus, out_dir, sp, control_trials, log)
        if err:
            base_m["commands"] = log
            return _record(unit, corpus_rel, "producer_failed", "not_applicable", None,
                           f"{UNIT}: evaluator failed -- NOT GRADED", "producer_failed: " + err, base_m)
        by_split[_split_key(sp)] = payload  # type: ignore[assignment]
    base_m["commands"] = log
    base_m["corpus_rows"] = n_rows
    base_m["corpus_leg_map"] = leg_map
    try:
        g = grade(by_split, leg_map)
    except MalformedResult as exc:
        return _record(unit, corpus_rel, "producer_failed", "not_applicable", None,
                       f"{UNIT}: evaluator output malformed -- NOT GRADED",
                       f"producer_failed: {exc}", base_m)
    base_m.update(g)
    st = ", ".join(f"{s} {v} (n_eval {g['per_stratum'][s].get('n_eval')})"
                   for s, v in g["stratum_status"].items())
    pop = (f"{n_rows} corpus rows ({corpus_rel}), 6 registered legs in 3 strata graded separately, never "
           f"pooled; n = sum of per-stratum eval trades at split {N_SPLIT} (chronological last "
           f"{int(round((1 - N_SPLIT) * 100))}%); splits {list(SPLITS)}, quantiles {list(QUANTILES)}, "
           f"control_trials {control_trials}")
    note = (f"{g['rule_outcome']}: {st}." + (f" Passed: {g['strata_passed']}." if g["strata_passed"] else "")
            + (" MIXED -- reported per stratum, not averaged." if g["mixed"] else "")
            + " Forecast sharpness only -- NOT net P&L (that is RQ-20261009-901).")
    return _record(unit, corpus_rel, "measured", g["verdict"], g["n"], pop, note, base_m)


# ── self-test ────────────────────────────────────────────────────────────────

def _mk_res(n_eval: int, beats: List[bool], *, imp: float = 0.2, b4_beats: Optional[List[bool]] = None,
            imp_sign: Optional[List[int]] = None, verdict: str = "calibrated_and_sharper") -> Dict[str, Any]:
    """A synthetic evaluator result: ``beats[i]`` = head beats ALL FOUR at QUANTILES[i];
    ``b4_beats`` overrides B4 alone; ``imp_sign[i]`` sets every improvement's sign at q_i."""
    if verdict in UNGRADED_VERDICTS:
        return {"verdict": verdict, "sharpness": [], "mace": None,
                "population": {"n_eval": n_eval, "features": list(FEATURES)}}
    rows = []
    for i, q in enumerate(QUANTILES):
        sgn = (imp_sign[i] if imp_sign else 1)
        r: Dict[str, Any] = {"q": q, "null_p95": 0.05}
        for b in BASELINES:
            ok = beats[i]
            if b == "B4" and b4_beats is not None:
                ok = b4_beats[i]
            r[f"vs_{b}_state"] = BEATS if ok else "beats_baseline_within_null"
            r[f"vs_{b}_improvement"] = sgn * (imp if ok else 0.01)
        r["gate_state"] = BEATS if all(r[f"vs_{b}_state"] == BEATS for b in BASELINES) else "not_all_four"
        rows.append(r)
    return {"verdict": verdict, "sharpness": rows, "mace": 0.03,
            "population": {"n_eval": n_eval, "features": list(FEATURES)},
            "control": {"per_quantile": {str(q): {"trials_usable": 20} for q in QUANTILES}}}


ALL = [True] * 5
NONE = [False] * 5
THREE = [True, True, True, False, False]
TWO = [True, True, False, False, False]


def _payloads(spec: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """spec[stratum] = {"n": int, "beats": {split: list} | list, "legs": {leg: res-kwargs} , ...}."""
    out: Dict[str, Dict[str, Any]] = {}
    for sp in SPLITS:
        k = _split_key(sp)
        ps, pl = {}, {}
        for s, legs in STRATA.items():
            sd = spec.get(s, {"n": 200, "beats": NONE})
            beats = sd["beats"][k] if isinstance(sd["beats"], dict) else sd["beats"]
            n = sd["n"] if sp == N_SPLIT else int(sd["n"] * (1 - sp) / (1 - N_SPLIT))
            ps[s] = _mk_res(n, beats, b4_beats=sd.get("b4"))
            for lg in legs:
                kw = dict((sd.get("legs") or {}).get(lg, {}))
                pl[lg] = _mk_res(n // 2, kw.pop("beats", beats), **kw)
        out[k] = {"per_stratum": ps, "per_leg": pl}
    return out


LEG_MAP = {lg: s for s, legs in STRATA.items() for lg in legs}


def self_test() -> int:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"[self-test] {'ok  ' if cond else 'FAIL'} {name}")
        ok = ok and cond

    S1, S2, S3 = list(STRATA)
    # 1. PASS (and MIXED): S2 sharper at every split with n >= 88; S1 sharper but n 74; S3 fails.
    g = grade(_payloads({S1: {"n": 74, "beats": ALL}, S2: {"n": 150, "beats": ALL},
                         S3: {"n": 400, "beats": TWO}}), LEG_MAP)
    check("PASS: one powered stratum SHARPER -> verdict pass", g["verdict"] == "pass" and g["strata_passed"] == [S2])
    check("PASS is MIXED and reported per stratum", g["mixed"] and g["stratum_status"][S3] == FAILS)
    check("INDETERMINATE: n 74 < 88 never passes, even when every clause clears",
          g["stratum_status"][S1] == INDETERMINATE and g["per_stratum"][S1]["sharper_clauses"] == SHARPER)
    # 2. HONEST_NEGATIVE: every powered stratum fails; S1 under the floor.
    g = grade(_payloads({S1: {"n": 74, "beats": ALL}, S2: {"n": 150, "beats": TWO},
                         S3: {"n": 400, "beats": NONE}}), LEG_MAP)
    check("HONEST_NEGATIVE: every n>=88 stratum fails -> verdict fail",
          g["verdict"] == "fail" and g["rule_outcome"] == "HONEST_NEGATIVE")
    # 3. INDETERMINATE overall: no stratum reaches n >= 88.
    g = grade(_payloads({S1: {"n": 74, "beats": ALL}, S2: {"n": 80, "beats": ALL},
                         S3: {"n": 60, "beats": ALL}}), LEG_MAP)
    check("INDETERMINATE: no stratum with n >= 88 -> verdict indeterminate", g["verdict"] == "indeterminate")
    # 4. B4 confound: beats B1..B3 everywhere, never B4 -> not a pass.
    g = grade(_payloads({S2: {"n": 150, "beats": ALL, "b4": NONE}, S3: {"n": 400, "beats": NONE}}), LEG_MAP)
    check("B1-B3 but not B4 is NOT a pass (volatility confound)",
          g["stratum_status"][S2] == FAILS and g["verdict"] == "fail")
    # 5. every split: 3 of 5 at 0.55 and 0.65, 2 of 5 at 0.75 -> not sharper.
    g = grade(_payloads({S2: {"n": 150, "beats": {"0.55": THREE, "0.65": ALL, "0.75": TWO}},
                         S3: {"n": 400, "beats": NONE}}), LEG_MAP)
    check("every-split requirement: one split at 2 of 5 -> FAILS", g["stratum_status"][S2] == FAILS)
    g = grade(_payloads({S2: {"n": 150, "beats": THREE}, S3: {"n": 400, "beats": NONE}}), LEG_MAP)
    check("boundary: exactly 3 of 5 at every split -> SHARPER", g["stratum_status"][S2] == SHARPER)
    # 6. leg-reversal veto.
    rev3 = {"imp_sign": [-1, -1, -1, 1, 1]}
    rev2 = {"imp_sign": [-1, -1, 1, 1, 1]}
    g = grade(_payloads({S2: {"n": 150, "beats": ALL, "legs": {"ada_pullback_2h": rev3}},
                         S3: {"n": 400, "beats": NONE}}), LEG_MAP)
    check("leg veto: a leg reversing the sign at 3 of 5 quantiles -> FAILS",
          g["stratum_status"][S2] == FAILS and g["per_stratum"][S2]["clauses"]["leg_reversal_veto"])
    g = grade(_payloads({S2: {"n": 150, "beats": ALL, "legs": {"ada_pullback_2h": rev2}},
                         S3: {"n": 400, "beats": NONE}}), LEG_MAP)
    check("leg veto boundary: reversal at 2 of 5 does not veto", g["stratum_status"][S2] == SHARPER)
    g = grade(_payloads({S2: {"n": 150, "beats": ALL,
                              "legs": {"xrp_pullback_2h": {"verdict": "insufficient_n"}}},
                         S3: {"n": 400, "beats": NONE}}), LEG_MAP)
    check("leg veto UNMEASURED (leg insufficient_n) + clears -> INDETERMINATE, not pass",
          g["stratum_status"][S2] == INDETERMINATE and g["verdict"] == "indeterminate")
    g = grade(_payloads({S2: {"n": 150, "beats": TWO,
                              "legs": {"xrp_pullback_2h": {"verdict": "insufficient_n"}}},
                         S3: {"n": 400, "beats": NONE}}), LEG_MAP)
    check("veto unmeasured but baseline clause fails -> FAILS (honest negative stands)",
          g["stratum_status"][S2] == FAILS and g["verdict"] == "fail")
    # 7. malformed output is refused, never graded.
    p = _payloads({S2: {"n": 150, "beats": ALL}})
    p["0.65"]["per_stratum"][S2]["sharpness"][0]["gate_state"] = "not_all_four"
    try:
        grade(p, LEG_MAP)
        check("gate_state disagreeing with per-baseline states is refused", False)
    except MalformedResult:
        check("gate_state disagreeing with per-baseline states is refused", True)
    p = _payloads({S2: {"n": 150, "beats": ALL}})
    p["0.75"]["per_stratum"][S2]["population"]["features"] = list(FEATURES[:6])
    try:
        grade(p, LEG_MAP)
        check("a result on a feature set other than the closed eight is refused", False)
    except MalformedResult:
        check("a result on a feature set other than the closed eight is refused", True)
    bad_map = dict(LEG_MAP, ada_pullback_2h=S3)
    g = grade(_payloads({S2: {"n": 150, "beats": ALL}}), bad_map)
    check("corpus leg->stratum map differing from the registered one -> INDETERMINATE",
          g["stratum_status"][S2] == INDETERMINATE)
    # 8. read_state paths, through run().
    with tempfile.TemporaryDirectory() as td:
        rec = run(Path(td) / "absent.jsonl", Path(td) / "o1", "RQ-X", 20)
        check("missing corpus -> no_data / not_applicable / n null",
              rec["read_state"] == "no_data" and rec["verdict"] == "not_applicable" and rec["n"] is None)
        empty = Path(td) / "empty.jsonl"
        empty.write_text("")
        rec = run(empty, Path(td) / "o2", "RQ-X", 20)
        check("empty corpus -> no_data", rec["read_state"] == "no_data" and rec["n"] is None)
        junk = Path(td) / "junk.jsonl"
        junk.write_text(json.dumps({"leg": "x", "stratum": "y"}) + "\n")
        global EVALUATOR
        real = EVALUATOR
        EVALUATOR = Path(td) / "broken_eval.py"
        EVALUATOR.write_text("import sys; sys.exit(3)\n")
        try:
            rec = run(junk, Path(td) / "o3", "RQ-X", 20)
        finally:
            EVALUATOR = real
        check("evaluator exiting non-zero -> producer_failed / not_applicable / n null",
              rec["read_state"] == "producer_failed" and rec["verdict"] == "not_applicable"
              and rec["n"] is None and "exit 3" in rec["note"])
        check("E5 shape: required keys present",
              all(k in rec for k in ("schema_version", "research_unit", "read_state", "verdict", "n",
                                     "population", "note", "decision_rule", "measurement", "data_inputs"))
              and rec["decision_rule"] == {"id": RULE_ID, "registered_at": RULE_REGISTERED_AT,
                                           "registered_before_run": True})
    print("[self-test]", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", help="ml2_live_leg_corpus.jsonl (RQ-20261014-736c-01's landed corpus)")
    ap.add_argument("--out", help="output directory; verdict.json + eval_split_*.json land here")
    ap.add_argument("--unit", default=UNIT)
    ap.add_argument("--control-trials", type=int, default=MIN_CONTROL_TRIALS)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.corpus or not args.out:
        ap.error("--corpus and --out are required (or --self-test)")
    out_dir = Path(args.out)
    rec = run(Path(args.corpus), out_dir, args.unit, args.control_trials)
    (out_dir / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"verdict: {rec['verdict']} (read_state {rec['read_state']}) -- {rec['note']}")
    print(f"wrote {out_dir / 'verdict.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
