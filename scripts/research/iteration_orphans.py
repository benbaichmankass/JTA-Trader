#!/usr/bin/env python3
"""ITERATION ORPHANS: every unproven thing must have a LIVE research iteration (lane RESEARCH-ITERATE, 2026-11-01).

OPERATOR, 2026-11-01 ~12:59Z (verbatim): "first, these rules apply to MLs as well, not just strategies or live reviews. second, if
the data doesn't pass, it goes back into research for improvments and testing. THere is no other pipeline for underperforming
strategies/mls. I don' twant to keep finding strategies sitting arround on paper testing with no clear plan".

THE ONE LADDER: the edge is decided OFFLINE on evidence; mechanics are verified on paper in 1-2 trades (or are already proven); then
it goes live. Anything whose evidence does not pass goes BACK INTO RESEARCH: diagnose why it failed, form a hypothesis, register the
next variant with its rule pre-registered, test, read, repeat. Paper ("testing") is where an unproven thing keeps generating live
data WHILE its research loop runs -- never a parking place.

SUBJECTS (population, printed on every run):
  * strategy_leg -- every leg `scripts/ops/strategy_status.py` derives as `testing` (re-read from config every run). Its current
    Stage-0 verdict is read from `comms/strategy_evidence/<leg>.json` (`decision_rule.verdict`, `n_trades_oos`, `fidelity`).
  * ml_model / ltr_class -- the heads and live-review action classes named in `scripts/research/iteration_subjects.yaml`.

LIVE ITERATION. A subject is covered when at least one unit in `research/queue/*.yaml` (status `queued`) or
`research/queue/blocked/*.yaml` (status `blocked`, every `blocked_on` entry naming `clears_when`) carries an `iteration:` block:

    iteration:
      subject: <leg | ml id | ltr id>     # or a list
      subject_kind: strategy_leg | ml_model | ltr_class
      from_result: <the unit / record / rule whose result this iterates on>
      verdict_read: fail | indeterminate | pass_unconfirmed | pending
      diagnosis: <why it failed, from that result's own rows; >= 80 chars>
      hypothesis: <the cause this variant tests>
      attempt: <int, 1 = first iteration after the failed read>
      due_by: 'YYYY-MM-DD'                # when this iteration must have a read (or be re-dated with a reason)

A unit without the block may still be good research, but it is not an iteration of a subject: it does not cover it. `--legacy`
also lists, per orphan, the hand-authored queued units that NAME the subject (a migration aid, never coverage).

STATES. `covered` (a live iteration, due_by today or later) | `overdue` (only iterations past due_by: covered, flagged) |
`orphan` (none). A subject whose evidence record is missing is still a subject: the iteration it needs is the one that measures it.

Gates this adds or changes: none. Report-only; exit 0 on any finding (exit 2 only when it could not read the inputs at all).
Usage:
  python3 scripts/research/iteration_orphans.py            # table + counts per kind
  python3 scripts/research/iteration_orphans.py --json     # machine form (research-ops record `iteration` block)
  python3 scripts/research/iteration_orphans.py --legacy   # also list legacy units naming each orphan
  python3 scripts/research/iteration_orphans.py --self-test
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
SUBJECTS_REL = "scripts/research/iteration_subjects.yaml"
KINDS = ("strategy_leg", "ml_model", "ltr_class")
MIN_DIAGNOSIS = 80
#: template families whose units are generated re-runs, never an iteration authored from a diagnosis (for --legacy only)
_GENERATED = re.compile(r"^(roster-walkforward|m20-exit-lever|e35-bracket|prop-fit-|regime-|template:)")


def _load_yaml(p: Path) -> Any:
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:  # an unreadable unit is reported, never read as "no unit"
        print(f"iteration_orphans: could not read {p}: {exc}", file=sys.stderr)
        return None


def leg_subjects(root: Path) -> list[dict[str, Any]]:
    sys.path.insert(0, str(root / "scripts" / "ops"))
    import strategy_status as ss
    out = []
    for leg, row in ss.table(root).items():
        if row["status"] != ss.TESTING:
            continue
        ev = evidence_path(root, leg)
        rec: dict[str, Any] = {}
        if ev.is_file():
            try:
                rec = json.loads(ev.read_text(encoding="utf-8"))
            except (OSError, ValueError):  # unreadable record -> its own state, the leg stays a subject
                rec = {"coverage_state": "unreadable"}
        out.append({"id": leg, "kind": "strategy_leg", "books": row["books"], "verdict": leg_verdict(rec),
                    "basis": (f"{ev.relative_to(root)}: coverage {rec.get('coverage_state')}, "
                              f"n {rec.get('n_trades_oos')}, net R {rec.get('net_r_oos')}, fidelity {rec.get('fidelity')}, "
                              f"rule {(rec.get('decision_rule') or {}).get('verdict')}") if rec else
                             f"comms/strategy_evidence/{leg}.json absent (not measured: a statement about us, not the leg)"})
    return out


def evidence_path(root: Path, leg: str) -> Path:
    """`<leg>.json`, else the longest record stem the leg name extends (e4_oi_shock_1h -> e4_oi_shock.json)."""
    d = root / "comms" / "strategy_evidence"
    exact = d / f"{leg}.json"
    if exact.is_file():
        return exact
    # provenance: evidence_path — falls back only to a record whose stem the leg name extends (strategy_evidence names by strategy)
    stems = sorted((p for p in d.glob("*.json") if leg.startswith(p.stem + "_")), key=lambda p: -len(p.stem))
    return stems[0] if stems else exact


def leg_verdict(rec: dict[str, Any]) -> str:
    """fail | indeterminate | pass_unconfirmed, from the Stage-0 record's own fields (never a new rule)."""
    if not rec or rec.get("coverage_state") != "measured":
        return "indeterminate"
    v = (rec.get("decision_rule") or {}).get("verdict")
    if v == "fail":
        return "fail"
    n = rec.get("n_trades_oos") or 0
    if v == "pass" and n >= 30 and rec.get("fidelity") == "faithful":
        return "pass_unconfirmed"   # still needs its holdout confirmation (mandate_resolver R-HOLDOUT) to leave testing
    return "indeterminate"


def listed_subjects(root: Path) -> list[dict[str, Any]]:
    doc = _load_yaml(root / SUBJECTS_REL) or {}
    out = []
    for kind in ("ml_model", "ltr_class", "candidate"):
        for s in doc.get(kind) or []:
            if isinstance(s, dict) and s.get("id"):
                out.append({"id": s["id"], "kind": "strategy_leg" if kind == "candidate" else kind,
                            "verdict": s.get("verdict", "pending"),
                            "basis": s.get("basis", ""), "money": s.get("money")})
    return out


def _subjects_of(it: dict[str, Any]) -> list[str]:
    s = it.get("subject")
    return [str(x) for x in (s if isinstance(s, list) else [s]) if x]


def iteration_errors(it: Any) -> list[str]:
    if not isinstance(it, dict):
        return ["`iteration` is not a mapping"]
    errs = []
    if not _subjects_of(it):
        errs.append("no `subject`")
    if it.get("subject_kind") not in KINDS:
        errs.append(f"`subject_kind` not one of {KINDS}")
    for k in ("from_result", "due_by"):
        if not it.get(k):
            errs.append(f"no `{k}`")
    if not (it.get("search") or it.get("hypothesis")):   # `hypothesis` is the 2026-11-01 alias of `search`
        errs.append("no `search` (the lever space this iteration searches, and why the diagnosis points there)")
    if len(str(it.get("diagnosis") or "")) < MIN_DIAGNOSIS:
        errs.append(f"`diagnosis` shorter than {MIN_DIAGNOSIS} chars (a diagnosis says WHY, from the result's rows)")
    return errs


def live_units(root: Path) -> list[dict[str, Any]]:
    out = []
    for f in sorted(glob.glob(str(root / "research/queue/*.yaml")) + glob.glob(str(root / "research/queue/blocked/*.yaml"))):
        d = _load_yaml(Path(f))
        if not isinstance(d, dict):
            continue
        st = d.get("status")
        blocked_dir = "/blocked/" in f
        if st == "queued" and not blocked_dir:
            live = True
        elif st == "blocked" and blocked_dir:
            bo = d.get("blocked_on") or []
            live = bool(bo) and all(isinstance(b, dict) and b.get("clears_when") for b in bo)
        else:
            live = False
        out.append({"id": d.get("id"), "path": str(Path(f).relative_to(root)), "status": st, "live": live,
                    "run": d.get("run") or {}, "grading": d.get("grading") or {},
                    "iteration": d.get("iteration"), "text": Path(f).read_text(encoding="utf-8"),
                    "generated": (d.get("generated") or {}).get("family") if isinstance(d.get("generated"), dict) else None})
    return out


# ── lever coverage (operator 2026-11-01): which lever families each subject has had tested, and which remain ──────────
#: config key / harness flag prefix -> strategy lever family (policy.lever_families.strategy_leg). Normalised: no dashes, '_'.
_LEVER_PREFIX = [
    ("off_cells", "regime_gating"), ("vol_spec", "regime_gating"), ("regime", "regime_gating"),
    ("adx_", "filter"), ("vol_skip", "filter"), ("htf_", "filter"), ("cooldown", "filter"),
    ("session", "session"), ("skip_hours", "session"),
    ("side_filter", "direction"), ("long_only", "direction"),
    ("timeframe", "timeframe"), ("symbol", "symbol_set"),
    ("entry_mode", "sizing_vs_cost"), ("fee_", "sizing_vs_cost"), ("slippage", "sizing_vs_cost"), ("maker_", "sizing_vs_cost"),
    ("taker_", "sizing_vs_cost"), ("risk_", "sizing_vs_cost"), ("sizing", "sizing_vs_cost"), ("funding", "sizing_vs_cost"),
    ("tp_", "exit"), ("trail_", "exit"), ("stale_exit", "exit"), ("giveback", "exit"), ("timeout", "exit"), ("bank_", "exit"),
    ("atr_stop", "exit"), ("atr_sl_buffer", "exit"), ("be_", "exit"), ("exit_", "exit"), ("partial", "exit"),
    ("trend_lookback", "entry"), ("pullback", "entry"), ("donchian", "entry"), ("min_confidence", "entry"),
    ("confirm_bars", "entry"), ("displacement", "entry"), ("min_displacement", "entry"), ("sweep", "entry"),
    ("swing_lookback", "entry"), ("min_fvg", "entry"), ("mitigation", "entry"), ("pierce", "entry"), ("range_lookback", "entry"),
    ("min_touches", "entry"), ("third_frac", "entry"), ("fvg_search", "entry"), ("min_width", "entry"), ("max_width", "entry"),
    ("touch_tol", "entry"), ("bb_", "entry"), ("kc_", "entry"), ("oi_", "entry"),
]
#: generated template families -> lever family (they carry no per-arm keys we can read)
_GEN_LEVER = [("m20-exit-lever", "exit"), ("e35-bracket", "exit"), ("prop-fit", "sizing_vs_cost")]


def _lever_of(token: str) -> str | None:
    key = token.lstrip("-").split("=", 1)[0].replace("-", "_").lower()
    for pre, fam in _LEVER_PREFIX:
        if key.startswith(pre):
            return fam
    return None


def unit_levers(u: dict[str, Any]) -> set:
    """Lever families a unit varies: explicit `iteration.levers`, else read from its `--arm` specs / --symbol / template family."""
    it = u.get("iteration") if isinstance(u.get("iteration"), dict) else {}
    if it.get("levers"):
        return {str(x) for x in it["levers"]}
    fams: set = set()
    cmd = [str(x) for x in ((u.get("run") or {}).get("command") or [])]
    for i, tok in enumerate(cmd):
        if tok == "--arm" and i + 1 < len(cmd):
            body = cmd[i + 1].partition("=")[2]
            for t in (x.strip() for x in body.split(";")):
                if t and (f := _lever_of(t)):
                    fams.add(f)
        elif tok == "--symbol":
            fams.add("symbol_set")
    for pre, fam in _GEN_LEVER:
        if u.get("generated") and str(u["generated"]).startswith(pre):
            fams.add(fam)
    return fams


def _names_subject(u: dict[str, Any], sid: str) -> bool:
    it = u.get("iteration") if isinstance(u.get("iteration"), dict) else {}
    if sid in _subjects_of(it):
        return True
    cmd = [str(x) for x in ((u.get("run") or {}).get("command") or [])]
    return any(cmd[i] == "--leg" and i + 1 < len(cmd) and cmd[i + 1] == sid for i in range(len(cmd)))


#: lever-map `levers_tested[].family` is free text (RESEARCH-EDGE hand-seeded it); the policy has nine strategy families. An entry may
#: carry an explicit `lever_family:` (wins); otherwise the first keyword that matches picks the policy family. Order matters.
_FAMILY_ALIASES = [
    ("regime", "regime_gating"), ("time-of-day", "session"), ("session", "session"),
    ("side", "direction"), ("short", "direction"), ("direction", "direction"), ("long-only", "direction"),
    ("universe", "symbol_set"), ("symbol", "symbol_set"), ("breadth", "symbol_set"), ("instrument", "symbol_set"),
    ("rebalance", "timeframe"), ("timeframe", "timeframe"),
    ("cost", "sizing_vs_cost"), ("risk scale", "sizing_vs_cost"), ("weighting", "sizing_vs_cost"), ("order type", "sizing_vs_cost"),
    ("trade frequency", "sizing_vs_cost"), ("sizing", "sizing_vs_cost"),
    ("target", "exit"), ("stop", "exit"), ("exit", "exit"), ("hold", "exit"),
    ("gate", "filter"), ("threshold", "filter"), ("filter", "filter"),
]


def policy_family(text: str, explicit: str | None = None) -> str:
    if explicit:
        return str(explicit)
    t = str(text).lower()
    for kw, fam in _FAMILY_ALIASES:
        if kw in t:
            return fam
    return "entry"          # signal / formation / forecast horizon, bracket mode, entry distance: how the entry is chosen


def map_families(doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """policy family -> {"at_power": bool, "tests": [labels]} from a lever map's hand-schema `levers_tested`."""
    out: dict[str, dict[str, Any]] = {}
    for lt in (doc or {}).get("levers_tested") or []:
        if not isinstance(lt, dict) or not lt.get("family"):
            continue
        fam = policy_family(lt["family"], lt.get("lever_family"))
        c = out.setdefault(fam, {"at_power": False, "tests": []})
        c["at_power"] = c["at_power"] or bool(lt.get("tested_at_power"))
        c["tests"].append(str(lt["family"]))
    return out


def read_map(root: Path, sid: str) -> dict[str, Any] | None:
    p = root / "research" / "levers" / f"{sid}.yaml"
    d = _load_yaml(p) if p.is_file() else None
    return d if isinstance(d, dict) else None


def lever_coverage(subjects: list[dict[str, Any]], units: list[dict[str, Any]], policy: dict[str, Any],
                   root: Path | None = None) -> dict[str, Any]:
    """Per subject: each lever family of its kind -> tested (a graded pass/fail), indeterminate_only, live, or untested.

    'tested' here means a graded verdict exists; whether it was at ADEQUATE power and full cost is the family-review
    record's job (scripts/research/family_retirement_guard.py). This view shows progress, it decides nothing."""
    fams_by_kind = policy.get("lever_families") or {}
    out = {}
    for s in subjects:
        fams = list(fams_by_kind.get(s["kind"]) or [])
        cell: dict[str, dict[str, list]] = {f: {"graded": [], "indeterminate": [], "live": []} for f in fams}
        for u in units:
            if not _names_subject(u, s["id"]):
                continue
            v = str((u.get("grading") or {}).get("verdict") or "").lower()
            for f in unit_levers(u):
                c = cell.setdefault(f, {"graded": [], "indeterminate": [], "live": []})
                if u["live"]:
                    c["live"].append(u["id"])
                elif v in ("pass", "fail"):
                    c["graded"].append(f"{u['id']}:{v}")
                elif u.get("status") == "done":
                    c["indeterminate"].append(u["id"])
        # the subject's lever map (research/levers/<id>.yaml `levers_tested`) is the other source: a family the map records as tested
        # counts; at_power False reads "underpowered" (tried, not closed -- it stays in `remaining`).
        mapped = map_families(read_map(root, s["id"])) if root is not None else {}
        for f, m in mapped.items():
            cell.setdefault(f, {"graded": [], "indeterminate": [], "live": []})
            cell[f]["map"] = m
        state = {f: ("tested" if c["graded"] or (c.get("map") or {}).get("at_power") else "live" if c["live"] else
                     "underpowered" if c.get("map") else
                     "indeterminate_only" if c["indeterminate"] else "untested") for f, c in cell.items()}
        out[s["id"]] = {"kind": s["kind"], "state": state, "detail": cell,
                        "remaining": [f for f in fams if state.get(f) != "tested"]}
    return out


def classify(subjects: list[dict[str, Any]], units: list[dict[str, Any]], today: dt.date,
             legacy: bool = False) -> list[dict[str, Any]]:
    rows = []
    for s in subjects:
        cov, bad = [], []
        for u in units:
            it = u["iteration"]
            if not u["live"] or not isinstance(it, dict) or s["id"] not in _subjects_of(it):
                continue
            errs = iteration_errors(it)
            if errs:
                bad.append({"unit": u["id"], "errors": errs})
                continue
            try:
                due = dt.date.fromisoformat(str(it["due_by"])[:10])
            except ValueError:
                bad.append({"unit": u["id"], "errors": ["`due_by` is not YYYY-MM-DD"]})
                continue
            cov.append({"unit": u["id"], "status": u["status"], "due_by": str(due), "overdue": due < today,
                        "attempt": it.get("attempt")})
        state = "orphan" if not cov else ("overdue" if all(c["overdue"] for c in cov) else "covered")
        row = {**s, "state": state, "iterations": cov, "malformed": bad}
        if legacy and state == "orphan":
            pat = re.compile(r"\b" + re.escape(s["id"]) + r"\b")
            row["legacy_naming"] = [u["id"] for u in units if u["live"] and not u["iteration"]
                                    and not (u["generated"] and _GENERATED.match(u["generated"]))
                                    and pat.search(u["text"])]
        rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        k = out.setdefault(r["kind"], {"subjects": 0, "covered": 0, "overdue": 0, "orphan": 0})
        k["subjects"] += 1
        k[r["state"]] += 1
    return out


def run(root: Path, today: dt.date | None = None, legacy: bool = False) -> dict[str, Any]:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    subjects = leg_subjects(root) + listed_subjects(root)
    units = live_units(root)
    rows = classify(subjects, units, today, legacy=legacy)
    policy = _load_yaml(root / "scripts/research/family_retirement_policy.yaml") or {}
    return {"as_of": str(today), "population": "testing legs (strategy_status.py) + " + SUBJECTS_REL,
            "counts": summarize(rows), "rows": rows, "lever_coverage": lever_coverage(subjects, units, policy, root)}


def _self_test() -> int:
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + label)
        ok = ok and cond

    today = dt.date(2026, 11, 1)
    good = {"subject": "leg_a", "subject_kind": "strategy_leg", "from_result": "RQ-x", "hypothesis": "h",
            "diagnosis": "d" * 90, "due_by": "2026-11-05", "attempt": 1}
    subj = [{"id": "leg_a", "kind": "strategy_leg", "verdict": "fail"},
            {"id": "leg_b", "kind": "strategy_leg", "verdict": "fail"}]
    units = [{"id": "U1", "live": True, "status": "queued", "iteration": good, "text": "leg_a", "generated": None},
             {"id": "U2", "live": True, "status": "queued", "iteration": None, "text": "leg_b", "generated": None},
             {"id": "U3", "live": False, "status": "done", "iteration": {**good, "subject": "leg_b"}, "text": "", "generated": None}]
    rows = {r["id"]: r for r in classify(subj, units, today, legacy=True)}
    check("a valid live iteration covers its subject", rows["leg_a"]["state"] == "covered")
    check("a unit merely NAMING a subject does not cover it", rows["leg_b"]["state"] == "orphan")
    check("a done unit's iteration block does not cover", rows["leg_b"]["iterations"] == [])
    check("--legacy lists the naming unit as a migration aid", rows["leg_b"]["legacy_naming"] == ["U2"])
    short = {**good, "diagnosis": "too short"}
    r2 = classify(subj[:1], [{**units[0], "iteration": short}], today)[0]
    check("a diagnosis under 80 chars is malformed, not coverage", r2["state"] == "orphan" and r2["malformed"])
    late = {**good, "due_by": "2026-10-01"}
    check("only past-due iterations read overdue", classify(subj[:1], [{**units[0], "iteration": late}], today)[0]["state"] == "overdue")
    check("verdict: measured + rule fail -> fail", leg_verdict({"coverage_state": "measured", "decision_rule": {"verdict": "fail"}}) == "fail")
    check("verdict: pass but n < 30 -> indeterminate",
          leg_verdict({"coverage_state": "measured", "decision_rule": {"verdict": "pass"}, "n_trades_oos": 8, "fidelity": "faithful"}) == "indeterminate")
    check("verdict: no record -> indeterminate (never pass)", leg_verdict({}) == "indeterminate")
    u_arm = {"id": "U9", "live": False, "status": "done", "grading": {"verdict": "fail"}, "iteration": None, "generated": None,
             "run": {"command": ["python3", "x.py", "--leg", "leg_a", "--arm", "A=", "--arm", "AD=adx_min=25;tp_r=3",
                                 "--arm", "H4=--htf-rule=4h"]}}
    check("arms map to lever families (adx/htf -> filter, tp_r -> exit)", unit_levers(u_arm) == {"filter", "exit"})
    cov = lever_coverage(subj[:1], [u_arm], {"lever_families": {"strategy_leg": ["entry", "exit", "filter"]}})["leg_a"]
    check("coverage: graded families read tested, others remain", cov["state"] == {"entry": "untested", "exit": "tested",
                                                                                   "filter": "tested"} and cov["remaining"] == ["entry"])
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--legacy", action="store_true")
    ap.add_argument("--levers", action="store_true", help="per subject: lever families tested / live / remaining")
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    try:
        res = run(Path(a.root), legacy=a.legacy)
    except (OSError, ValueError, KeyError, ImportError, yaml.YAMLError) as exc:  # could not look: say so, never zero orphans
        print(f"iteration_orphans: COULD NOT MEASURE -- {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=1, default=str))
        return 0
    for r in res["rows"]:
        its = ",".join(f"{c['unit']}{'(OVERDUE)' if c['overdue'] else ''}" for c in r["iterations"]) or "—"
        extra = f"  legacy-naming: {len(r.get('legacy_naming') or [])}" if "legacy_naming" in r else ""
        mal = f"  MALFORMED: {','.join(m['unit'] for m in r['malformed'])}" if r["malformed"] else ""
        print(f"{r['state']:<8} {r['kind']:<13} {r['id']:<28} verdict={r['verdict']:<17} {its}{extra}{mal}")
    if a.levers:
        print("\nLEVER COVERAGE (T tested=graded pass/fail or map-recorded at power, L live, u tried-underpowered (map), i indeterminate only, . untested; power/cost adequacy is the review record's call)")
        sym = {"tested": "T", "live": "L", "underpowered": "u", "indeterminate_only": "i", "untested": "."}
        for sid, c in res["lever_coverage"].items():
            cells = " ".join(f"{f}={sym.get(st, '?')}" for f, st in c["state"].items())
            print(f"  {sid:<28} {cells}")
    print(f"population: {res['population']} as of {res['as_of']}")
    for k, c in res["counts"].items():
        print(f"  {k}: {c['subjects']} subjects -- covered {c['covered']}, overdue {c['overdue']}, ORPHAN {c['orphan']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
