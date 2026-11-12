#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py::w9-gate-reports (report mode, always exit 0; self-test in tests/test_report_w9_gates.py)
"""w9-gate-reports — FOUR candidate gates built as REPORTS that block nothing.

Operator decision 2026-11-12 (decisions page w9, "Build them as reports only (no gate)"; note: "I want a
break down of each one so that I can decide on each gate if its necessary or not").

Gates this adds or changes: none. This script NEVER exits 1: a finding is a line in a report, not a refusal;
an unreadable source is an explicit `read_state: could_not_look` on that check, still exit 0. Exit 2 is reserved
for a failed ``--self-test`` (a defect in this script's own controls, run by pytest, not by run_guards).

The four checks (one row each):
  ml-advisory-scope        ML-ADVISORY-SCOPE-GUARD    advisory_policy downsize / trend_vol cell / exit_head close on a
                                                      risk-bearing roster leg with no Gate-2 evidence record
  lever-consumer-parity    LEVER-LIVE-CONSUMER-PARITY every harness-tested exit-lever key, its live consumer or no_consumer
  prop-floor               PROP-GATE-RECOST-AND-FLOOR prop survival record vs the registered per-firm breach ceiling + EV
  active-mgmt-standard     RM-AM-STANDARD-GUARD       risk-bearing roster leg: (a) trail + activation R, (b) TP-doctrine
                                                      grade/baseline line, (c) coverage-matrix row

Populations are RE-PARSED on every run from config/accounts.yaml + config/strategies.yaml; no count is hard-coded.
"Risk-bearing" = ``account_class`` not ``paper`` (same predicate as roster-promotion-evidence-guard, fail closed).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REPO = Path(__file__).resolve().parents[2]
NON_RISK_CLASSES = frozenset({"paper"})
CHECKS = ("ml-advisory-scope", "lever-consumer-parity", "prop-floor", "active-mgmt-standard")
EVIDENCE_DIR = "comms/strategy_evidence"
SURVIVAL_DIR = "comms/prop_survival"
COVERAGE_JSON = "docs/research/exit-refinement-coverage.json"
PROP_N_FLOOR = 88          # the n floor RULE-V2 registers (research/queue/RQ-20261029-9a2c-01.yaml)
LEVER_RE = re.compile(r"^(trail|be_|tp_|stale|giveback|partial|exit_|breakeven|chandelier)")
# files that are NOT a live consumer of a lever key (the harness itself, the replay advisor, tests, this report)
NON_CONSUMER_PARTS = ("src/backtest/", "src/runtime/bracket_advisor.py")


# --------------------------------------------------------------------------- inputs
def _yaml(text: Optional[str]) -> Dict[str, Any]:
    d = yaml.safe_load(text) if text else None
    return d if isinstance(d, dict) else {}


def _git_show(sha: str, rel: str) -> Optional[str]:
    try:
        return subprocess.run(["git", "show", f"{sha}:{rel}"], cwd=REPO, capture_output=True, text=True,
                              check=True).stdout
    except Exception:  # noqa: BLE001 - report tool: absence is a read-state, not a crash
        return None


def _read(rel: str) -> Optional[str]:
    try:
        return (REPO / rel).read_text(encoding="utf-8")
    except OSError:
        return None


def risk_legs(accounts_text: Optional[str]) -> Dict[str, List[Dict[str, str]]]:
    """`{leg: [{account, class, mode}]}` over every risk-bearing account's `strategies:` roster."""
    out: Dict[str, List[Dict[str, str]]] = {}
    for acct, cfg in (_yaml(accounts_text).get("accounts") or {}).items():
        if not isinstance(cfg, dict):
            continue
        cls = None if cfg.get("account_class") is None else str(cfg["account_class"]).strip().lower()
        if cls in NON_RISK_CLASSES:
            continue
        for leg in cfg.get("strategies") or []:
            out.setdefault(str(leg), []).append({"account": str(acct), "class": str(cls),
                                                 "mode": str(cfg.get("mode"))})
    return out


def _strategies(strategies_text: Optional[str]) -> Dict[str, Dict[str, Any]]:
    s = _yaml(strategies_text).get("strategies") or {}
    return {str(k): v for k, v in s.items() if isinstance(v, dict)}


def _result(check: str, row: str, rows: List[Dict[str, Any]], population: str, hits: int,
            read_state: str = "ok", **extra: Any) -> Dict[str, Any]:
    return {"check": check, "row": row, "read_state": read_state, "population": population,
            "n_checked": len(rows), "n_hits": hits, "rows": rows, **extra}


# --------------------------------------------------------------------------- 1. ML advisory scope
def _cells_for_leg(leg: str, regime: Dict[str, Any]) -> List[str]:
    """trend_vol cells whose strategy key is the leg or a name prefix of it (family match)."""
    found = []
    for trend, vols in (regime.get("trend_vol") or {}).items():
        for vol, strat in (vols or {}).items():
            for key, cell in (strat or {}).items():
                if leg == key or leg.startswith(str(key) + "_"):
                    found.append(f"{trend}/{vol}/{key}:{cell}")
    return found


def check_ml_advisory_scope(accounts_text, strategies_text, regime_text, evidence_exists=None) -> Dict[str, Any]:
    evidence_exists = evidence_exists or (lambda leg: (REPO / EVIDENCE_DIR / f"{leg}.json").exists())
    legs, strat, regime = risk_legs(accounts_text), _strategies(strategies_text), _yaml(regime_text)
    if not legs or not strat:
        return _result("ml-advisory-scope", "ML-ADVISORY-SCOPE-GUARD", [], "unreadable", 0, "could_not_look")
    rows, hits = [], 0
    for leg, accts in sorted(legs.items()):
        cfg = strat.get(leg)
        if cfg is None:
            rows.append({"leg": leg, "accounts": [a["account"] for a in accts], "read_state": "no_strategies_yaml_entry",
                         "effects": [], "hit": False})
            continue
        ap = cfg.get("advisory_policy")
        mode = (ap.get("mode") if isinstance(ap, dict) else ap) or "annotate(default)"
        effects = []
        if str(mode).lower() == "downsize":
            effects.append("advisory_policy.mode=downsize")
        if str(cfg.get("exit_head_action") or "").lower() == "close":
            effects.append("exit_head_action=close")
        effects += [f"trend_vol cell {c}" for c in _cells_for_leg(leg, regime)]
        has_ev = bool(evidence_exists(leg))
        hit = bool(effects) and not has_ev
        hits += hit
        rows.append({"leg": leg, "accounts": [a["account"] for a in accts], "advisory_mode": str(mode),
                     "exit_head_action": cfg.get("exit_head_action"), "effects": effects,
                     "gate2_evidence_record": has_ev, "hit": hit})
    return _result("ml-advisory-scope", "ML-ADVISORY-SCOPE-GUARD", rows,
                   "risk-bearing (non-paper) roster legs in config/accounts.yaml", hits,
                   cell_match="trend_vol cell key == leg or a `<key>_` name prefix of the leg (policy.py keys by strategy name)",
                   evidence_proxy=f"{EVIDENCE_DIR}/<leg>.json exists")


# --------------------------------------------------------------------------- 2. lever consumer parity
def _grep_files(globs: List[str]) -> Dict[str, str]:
    out = {}
    for g in globs:
        for p in sorted(REPO.glob(g)):
            if p.is_file() and "__pycache__" not in p.parts:
                try:
                    out[str(p.relative_to(REPO))] = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
    return out


def check_lever_consumer_parity(strategies_text, harness_files=None, src_files=None) -> Dict[str, Any]:
    strat = _strategies(strategies_text)
    harness = harness_files if harness_files is not None else _grep_files(
        ["scripts/backtest_*.py", "src/backtest/*.py", "scripts/research/*exit*.py", "scripts/research/m20_*.py"])
    src = src_files if src_files is not None else _grep_files(["src/**/*.py"])
    keys: Dict[str, int] = {}
    for cfg in strat.values():
        for k in cfg:
            if LEVER_RE.match(str(k)):
                keys[k] = keys.get(k, 0) + 1
    # harness-only config keys: a lever the harness reads that no strategies.yaml leg declares (e.g. be_floor_r)
    harness_cfg = re.compile(r"""['"]((?:trail|be|giveback|stale)_[a-z0-9_]*(?:_r|_mult|_bars|_bps|_pctl|_frac))['"]""")
    for txt in harness.values():
        for k in harness_cfg.findall(txt):
            keys.setdefault(k, 0)
    if not keys or not src:
        return _result("lever-consumer-parity", "LEVER-LIVE-CONSUMER-PARITY", [], "unreadable", 0, "could_not_look")
    rows, hits = [], 0
    for k, n in sorted(keys.items()):
        tested_in = sorted(f for f, t in harness.items() if re.search(rf"['\"]{re.escape(k)}['\"]|\b{re.escape(k)}\b", t))
        consumers = sorted(f for f, t in src.items()
                           if not any(part in f for part in NON_CONSUMER_PARTS)
                           and re.search(rf"['\"]{re.escape(k)}['\"]", t))
        verdict = "consumer" if consumers else "no_consumer"
        hit = bool(tested_in) and not consumers
        hits += hit
        rows.append({"key": k, "declared_on_n_strategies": n, "harness_files": tested_in[:6],
                     "n_harness_files": len(tested_in), "live_consumers": consumers[:6],
                     "n_live_consumers": len(consumers), "verdict": verdict,
                     "harness_tested": bool(tested_in), "hit": hit})
    return _result("lever-consumer-parity", "LEVER-LIVE-CONSUMER-PARITY", rows,
                   "exit-lever-shaped keys declared in config/strategies.yaml (regex "
                   f"{LEVER_RE.pattern}) plus config-shaped lever keys the harness scripts read but no leg declares", hits,
                   consumer_rule="key as a quoted string in src/**/*.py outside src/backtest/ and bracket_advisor.py; "
                                 "a string match is NOT proof the value is read on the order path")


# --------------------------------------------------------------------------- 3. prop breach floor
def _ruleset_ceiling(ruleset: str) -> Optional[float]:
    d = _yaml(_read(f"config/prop_rulesets/{Path(ruleset).stem}.yaml"))
    try:
        fee = float(d["economics"]["account_fee_usd"]) if "economics" in d else float(_find(d, "account_fee_usd"))
        size = float(d["account_size_usd"])
        split = float(d["profit_split"])
        tgt = float(d["phases"]["evaluation"]["profit_target_pct"])
    except (KeyError, TypeError, ValueError):
        return None
    w = split * tgt * size
    return round(1 - 2 * fee / w, 3) if w > 0 else None


def _find(d: Any, key: str) -> Any:
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = _find(v, key)
            if r is not None:
                return r
    return None


def record_floor_problems(rec: Dict[str, Any], ceiling: Optional[float]) -> List[str]:
    """What the registered V2 rule would refuse on a record's headline numbers (n>=88, p_breach<c, EV>0)."""
    p = []
    n, pb, ev = rec.get("n_trades"), rec.get("p_breach"), rec.get("ev_net_usd")
    if not isinstance(n, int) or n < PROP_N_FLOOR:
        p.append(f"n_trades {n!r} < {PROP_N_FLOOR}")
    if ceiling is None:
        p.append("ceiling underivable from the ruleset (fee/size/split/target missing)")
    elif not isinstance(pb, (int, float)) or pb >= ceiling:
        p.append(f"p_breach {pb!r} >= ceiling {ceiling}")
    if not isinstance(ev, (int, float)) or ev <= 0:
        p.append(f"ev_net_usd {ev!r} <= 0")
    return p


def check_prop_floor(accounts_text, survival: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    accts = _yaml(accounts_text).get("accounts") or {}
    if survival is None:
        survival = {}
        for p in sorted((REPO / SURVIVAL_DIR).glob("*.json")):
            try:
                survival[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                survival[p.stem] = {"_unreadable": True}
    rows, hits = [], 0
    for acct, cfg in sorted(accts.items()):
        if not isinstance(cfg, dict) or str(cfg.get("account_class")).lower() != "prop":
            continue
        ruleset = cfg.get("backtest_ruleset")
        ceiling = _ruleset_ceiling(str(ruleset)) if ruleset else None
        for leg in cfg.get("strategies") or []:
            rec = survival.get(str(leg))
            exempt = bool(rec and isinstance(rec.get("operator_exception"), dict)
                          and rec["operator_exception"].get("kind") == "baseline"
                          and acct in (rec["operator_exception"].get("accounts") or []))
            if rec is None or rec.get("_unreadable"):
                rows.append({"account": acct, "leg": leg, "ruleset": ruleset, "record": "missing" if rec is None else "unreadable",
                             "problems": ["no readable record"], "operator_baseline_exempt": False, "hit": True})
                hits += 1
                continue
            cell = (rec.get("accounts") or {}).get(acct) or (rec.get("per_firm") or {}).get(acct) or {}
            # the per-account cell (median + worst seed) is the registered rule's unit; fall back to the headline
            view = {"n_trades": rec.get("n_trades"),
                    "p_breach": cell.get("p_breach", cell.get("p_breach_eval_worst", rec.get("p_breach"))),
                    "ev_net_usd": cell.get("ev_net_usd_worst", cell.get("ev_net_usd_worst_seed",
                                          cell.get("ev_net_usd_median", rec.get("ev_net_usd")))),
                    "edge_ci95_lower_r": cell.get("edge_ci95_lower")}
            probs = record_floor_problems(view, ceiling)
            dr = rec.get("decision_rule") if isinstance(rec.get("decision_rule"), dict) else {}
            hit = bool(probs)
            hits += hit
            rows.append({"account": acct, "leg": leg, "ruleset": ruleset, "ceiling": ceiling,
                         "record_verdict": dr.get("verdict"), "rule_id": dr.get("id"), "view": view,
                         "from_per_account_cell": bool(cell), "problems": probs,
                         "operator_baseline_exempt": exempt, "hit": hit,
                         "hit_without_exemption": hit and not exempt})
    return _result("prop-floor", "PROP-GATE-RECOST-AND-FLOOR", rows,
                   "(prop account, leg) routings on every class=prop account in config/accounts.yaml", hits,
                   note="ceiling c = 1 - 2F/W per firm (RQ-20261029-9a2c-01); the record's p_breach is the seed-max "
                        "lifetime field unless a per-account cell exists, so the headline view over-reads breach")


# --------------------------------------------------------------------------- 4. active-management standard
def _trail_state(cfg: Dict[str, Any]) -> Dict[str, Any]:
    has_trail = any(cfg.get(k) for k in ("trail_mult", "trail_atr_mult"))
    act = {k: cfg.get(k) for k in ("trail_decay_arm_r", "be_at_r") if isinstance(cfg.get(k), (int, float))}
    return {"trail_declared": has_trail, "activation_r": act or None,
            "activation": "explicit" if act else ("implicit_from_entry" if has_trail else "none")}


def _coverage_rows() -> List[Dict[str, Any]]:
    try:
        return json.loads(_read(COVERAGE_JSON) or "{}").get("rows") or []
    except ValueError:
        return []


def _tp_failures(accounts_text) -> Dict[str, List[str]]:
    """leg -> TP-doctrine fails on its risk-bearing routings, via the existing guard's scan (read-only)."""
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "scripts" / "ci"))
    import check_tp_doctrine as tp  # noqa: WPS433
    base = tp.BASELINE_2026_10_06
    out: Dict[str, List[str]] = {}
    for r in tp.scan():
        if r.account_class in ("paper", "mirror", "unknown"):
            continue
        state = "baseline_line" if r.key in base else ("compliant" if not r.fails else "uncovered_fail")
        out.setdefault(r.leg, []).append(f"{r.account}:{state}")
    return out


def check_active_mgmt_standard(accounts_text, strategies_text, coverage_rows=None, tp_states=None) -> Dict[str, Any]:
    legs, strat = risk_legs(accounts_text), _strategies(strategies_text)
    if not legs or not strat:
        return _result("active-mgmt-standard", "RM-AM-STANDARD-GUARD", [], "unreadable", 0, "could_not_look")
    cov = coverage_rows if coverage_rows is not None else _coverage_rows()
    try:
        tps = tp_states if tp_states is not None else _tp_failures(accounts_text)
        tp_read = "ok"
    except Exception as e:  # noqa: BLE001
        tps, tp_read = {}, f"could_not_look({type(e).__name__})"
    rows, hits = [], 0
    for leg, accts in sorted(legs.items()):
        cfg = strat.get(leg, {})
        tr = _trail_state(cfg)
        syms = [str(s).upper() for s in (cfg.get("symbols") or [])]
        tf = str(cfg.get("timeframe") or "")
        matched = [r for r in cov if (leg == r.get("strategy") or leg.startswith(str(r.get("strategy")) + "_"))
                   and (not syms or str(r.get("symbol", "")).upper() in syms) and (not tf or r.get("tf") == tf)]
        tp_list = tps.get(leg, [])
        tp_bad = [s for s in tp_list if s.endswith("uncovered_fail")]
        gaps = []
        if not tr["trail_declared"]:
            gaps.append("a:no_trail")
        elif tr["activation"] != "explicit":
            gaps.append("a:activation_implicit")     # soft: a chandelier trails from entry; no separate arm R
        if tp_read == "ok" and (not tp_list or tp_bad):
            gaps.append("b:tp_uncovered" if tp_list else "b:no_tp_grade")
        if not matched:
            gaps.append("c:no_coverage_row")
        hard = [g for g in gaps if g != "a:activation_implicit"]
        hit = bool(hard)
        hits += hit
        rows.append({"leg": leg, "accounts": [a["account"] for a in accts], **tr,
                     "tp_doctrine": tp_list, "coverage_rows": len(matched), "gaps": gaps, "hit": hit})
    return _result("active-mgmt-standard", "RM-AM-STANDARD-GUARD", rows,
                   "risk-bearing (non-paper) roster legs in config/accounts.yaml", hits,
                   tp_read_state=tp_read,
                   coverage_match="matrix row strategy == leg or a `<strategy>_` prefix of it, symbol in the leg's symbols, tf equal",
                   note="activation_implicit is reported but is not a hit: a chandelier trail has no separate arm R")


# --------------------------------------------------------------------------- history (cheap: yaml at past commits)
def _commits(paths: List[str], n: int) -> List[str]:
    try:
        out = subprocess.run(["git", "log", f"-{n}", "--format=%H", "--", *paths], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
        return [x for x in out.split() if x]
    except Exception:  # noqa: BLE001
        return []


def history(check: str, n: int) -> Dict[str, Any]:
    """Re-run a yaml-only check at each of the last `n` commits that touched its inputs."""
    if check not in ("ml-advisory-scope", "active-mgmt-standard", "prop-floor"):
        return {"read_state": "not_attempted", "why": "reads src/ or repo-wide state; history costs a checkout per commit"}
    paths = ["config/accounts.yaml", "config/strategies.yaml"] + (
        ["config/regime_policy.yaml"] if check == "ml-advisory-scope" else [])
    shas = _commits(paths, n)
    series = []
    for sha in shas:
        a, s = _git_show(sha, "config/accounts.yaml"), _git_show(sha, "config/strategies.yaml")
        if check == "ml-advisory-scope":
            r = check_ml_advisory_scope(a, s, _git_show(sha, "config/regime_policy.yaml"), evidence_exists=lambda leg, sha=sha: _git_show(sha, f"{EVIDENCE_DIR}/{leg}.json") is not None)
        elif check == "active-mgmt-standard":
            r = check_active_mgmt_standard(a, s, coverage_rows=json.loads(_git_show(sha, COVERAGE_JSON) or "{}").get("rows") or [],
                                           tp_states={})   # tp axis not replayed historically; a/c only
            for row in r["rows"]:
                row["gaps"] = [g for g in row["gaps"] if not g.startswith("b:")]
                row["hit"] = any(g != "a:activation_implicit" for g in row["gaps"])
            r["n_hits"] = sum(row["hit"] for row in r["rows"])
        else:
            surv = {}
            for p in (REPO / SURVIVAL_DIR).glob("*.json"):
                t = _git_show(sha, f"{SURVIVAL_DIR}/{p.name}")
                if t:
                    try:
                        surv[p.stem] = json.loads(t)
                    except ValueError:
                        pass
            r = check_prop_floor(a, surv)
        series.append({"commit": sha[:9], "n_checked": r["n_checked"], "n_hits": r["n_hits"],
                       "hit_keys": [x.get("leg") or x.get("key") for x in r["rows"] if x.get("hit")]})
    ever = sorted({k for s in series for k in s["hit_keys"] if k})
    return {"read_state": "ok" if series else "could_not_look",
            "population": f"last {len(series)} commits touching {', '.join(paths)} (survival records read at HEAD's file set)"
                          if check == "prop-floor" else f"last {len(series)} commits touching {', '.join(paths)}",
            "commits_with_any_hit": sum(1 for s in series if s["n_hits"]), "ever_hit": ever, "series": series[:40]}


# --------------------------------------------------------------------------- driver
def run(check: str, with_history: int = 0) -> Dict[str, Any]:
    a, s, rg = _read("config/accounts.yaml"), _read("config/strategies.yaml"), _read("config/regime_policy.yaml")
    try:
        if check == "ml-advisory-scope":
            r = check_ml_advisory_scope(a, s, rg)
        elif check == "lever-consumer-parity":
            r = check_lever_consumer_parity(s)
        elif check == "prop-floor":
            r = check_prop_floor(a)
        else:
            r = check_active_mgmt_standard(a, s)
    except Exception as e:  # noqa: BLE001 - a report never crashes CI
        r = _result(check, "?", [], f"error {type(e).__name__}: {e}", 0, "could_not_look")
    if with_history:
        r["history"] = history(check, with_history)
    return r


def render(r: Dict[str, Any]) -> str:
    lines = [f"== {r['check']} ({r['row']})  read_state={r['read_state']}  hits {r['n_hits']}/{r['n_checked']}",
             f"   population: {r['population']}"]
    for row in r["rows"]:
        if row.get("hit"):
            lines.append("   HIT  " + json.dumps({k: v for k, v in row.items() if k not in ("hit", "harness_files")})[:300])
    if r.get("history"):
        h = r["history"]
        lines.append(f"   history: {h.get('read_state')} {h.get('population', h.get('why', ''))} "
                     f"commits_with_any_hit={h.get('commits_with_any_hit')} ever_hit={h.get('ever_hit')}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- self-test (positive + negative controls)
def _self_test() -> int:
    bad: List[str] = []

    def expect(name: str, cond: bool) -> None:
        if not cond:
            bad.append(name)

    acc = ("accounts:\n  rm:\n    account_class: real_money\n    mode: live\n    strategies: [leg_a, leg_b]\n"
           "  pp:\n    account_class: paper\n    mode: live\n    strategies: [leg_paper]\n")
    strat = ("strategies:\n  leg_a:\n    advisory_policy: {mode: downsize}\n    trail_mult: 3\n    symbols: [AAAUSDT]\n    timeframe: 1h\n"
             "    tp_r: 50\n    be_at_r: 1.0\n"
             "  leg_b:\n    exit_head_action: annotate\n    tp_r: 3\n"
             "  leg_paper:\n    advisory_policy: {mode: downsize}\n")
    reg = "trend_vol:\n  chop:\n    calm:\n      leg_b: { long: off }\n"
    # 1 -- positive: leg_a downsize without evidence is a hit; leg_b cell family-match is a hit; negative: paper leg ignored,
    # evidence record suppresses; annotate without a cell is not a hit.
    r = check_ml_advisory_scope(acc, strat, reg, evidence_exists=lambda leg: False)
    hits = {x["leg"] for x in r["rows"] if x["hit"]}
    expect("1+ downsize hit", "leg_a" in hits)
    expect("1+ cell hit", "leg_b" in hits)
    expect("1- paper not in population", r["n_checked"] == 2)
    expect("1- evidence suppresses", check_ml_advisory_scope(acc, strat, reg, evidence_exists=lambda leg: True)["n_hits"] == 0)
    expect("1- annotate/no cell not a hit", check_ml_advisory_scope(acc, strat, "", evidence_exists=lambda leg: False)["n_hits"] == 1)
    expect("1- unreadable is could_not_look", check_ml_advisory_scope("", "", "")["read_state"] == "could_not_look")
    # 2 -- positive: tested in harness, no src consumer; negative: consumer present, and not harness-tested.
    s2 = "strategies:\n  x: {trail_mult: 1, be_floor_r: 2, stale_exit_bars: 3}\n"
    harness = {"scripts/backtest_trend.py": "p['trail_mult']; p['be_floor_r']"}
    src = {"src/units/a.py": "cfg.get('trail_mult')", "src/runtime/bracket_advisor.py": "'be_floor_r'"}
    rows = {x["key"]: x for x in check_lever_consumer_parity(s2, harness, src)["rows"]}
    expect("2+ no_consumer hit", rows["be_floor_r"]["hit"] and rows["be_floor_r"]["verdict"] == "no_consumer")
    expect("2- consumer ok", not rows["trail_mult"]["hit"] and rows["trail_mult"]["verdict"] == "consumer")
    expect("2- untested key not a hit", not rows["stale_exit_bars"]["hit"])
    # 3 -- planted 0.934 record vs 0.889 ceiling flags; a 0.464 record does not; n floor; EV floor.
    expect("3+ 0.934 flagged", bool(record_floor_problems({"n_trades": 517, "p_breach": 0.934, "ev_net_usd": 75}, 0.889)))
    expect("3 ceiling derives", _ruleset_ceiling("prop_rulesets/breakout_turbo_1step.yaml") == 0.889)
    expect("3- 0.464 clean", not record_floor_problems({"n_trades": 132, "p_breach": 0.464, "ev_net_usd": 64}, 0.889))
    expect("3+ n floor", bool(record_floor_problems({"n_trades": 51, "p_breach": 0.1, "ev_net_usd": 1}, 0.889)))
    expect("3+ EV floor", bool(record_floor_problems({"n_trades": 200, "p_breach": 0.1, "ev_net_usd": -1}, 0.889)))
    # 4 -- no trail / no coverage row hit; full leg clean; activation_implicit soft.
    acc4 = "accounts:\n  rm:\n    account_class: real_money\n    mode: live\n    strategies: [leg_a, leg_b]\n"
    cov = [{"strategy": "leg", "symbol": "AAAUSDT", "tf": "1h"}]
    strat = strat.replace("  leg_b:\n", "  leg_b:\n    symbols: [ZZZUSDT]\n")
    r4 = {x["leg"]: x for x in check_active_mgmt_standard(acc4, strat, coverage_rows=cov,
                                                           tp_states={"leg_a": ["rm:compliant"], "leg_b": ["rm:uncovered_fail"]})["rows"]}
    expect("4- complete leg clean", not r4["leg_a"]["hit"])
    expect("4+ leg_b gaps", r4["leg_b"]["hit"] and {"a:no_trail", "b:tp_uncovered", "c:no_coverage_row"} <= set(r4["leg_b"]["gaps"]))
    for b in bad:
        print(f"SELF-TEST FAIL: {b}")
    print(f"w9-gate-reports self-test: {'FAIL' if bad else 'ok'} ({len(bad)} failing control(s))")
    return 2 if bad else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--check", choices=CHECKS + ("all",), default="all")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--history", type=int, default=0, metavar="N", help="also replay yaml-only checks over the last N commits")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    results = [run(c, args.history) for c in (CHECKS if args.check == "all" else (args.check,))]
    print(json.dumps(results, indent=1) if args.json else "\n".join(render(r) for r in results))
    return 0          # a report: NEVER exit 1


if __name__ == "__main__":
    sys.exit(main())
