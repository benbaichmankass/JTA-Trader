#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py (prop-roster-gate-guard)
"""prop-roster-gate-guard — a prop leg clears EVERYTHING a real-money leg clears, PLUS prop survival.

OPERATOR DECISION, 2026-10-15 (chat, verbatim choice "Yes, 1, 2 and 3a"; principle:
"if anything, the prop accounts should have a higher bar to clear because of the DD limits"):
the prop gate is a SUPERSET of the real-money bar, never a lower one. The 2026-08-27 correction
said "the prop gate is NOT a lower bar"; this guard is the mechanical half of making it formally
a superset. The bar for a leg reaching a prop roster:

  1. everything a real-money leg clears — Stage 0 net of the FULL cost stack (enforced by
     ``roster-promotion-evidence-guard``, which already treats ``prop`` as risk-bearing; this
     guard does NOT duplicate it) and Gate 2 criteria;
  2. a Stage-1 soak: the leg is on a Stage-1 roster (``soak_state.STAGE1_ACCOUNTS``) at HEAD
     OR carries a Stage-1 soak contract in ``docs/claude/work/SOAKS.json``; AND
     AMENDMENT (operator 2026-10-15): Stage-1 soak evidence may ALSO come from LIVE PROP trading —
     a contract ``sources`` entry of kind ``prop_live`` (``n_needed`` <= 2 and its mechanical
     ``checklist``) counts. REDEFINED the same day (operator: "a soak is a mechanical verification ...
     nothing needs to soak for more than one or two trades"): the soak PASSES on 1-2 clean trades
     (signal, size/side, real SL+TP resting at the venue, management, journaled exit, fill recorded);
     realized cost and live_vs_backtest are ONGOING MONITORING, not soak exit criteria. Grading:
     ``scripts/ops/soak_state.py::grade_prop_signal``. A PASS feeds MD-PROMOTE-S1-S2 (bybit_2 +
     bybit_portfolio together, human merge) and the evidence record must carry a PORTFOLIO OVERLAP
     check. Nothing is promoted by this guard.
  3. a prop survival-gate record: ``comms/prop_survival/<leg>.json`` — see ``record_problems``
     for the fields (the EV/survival run under the firm's ruleset, a rule registered before the
     run, verdict pass).

DIFF-SCOPED, ROSTER-MEMBERSHIP KEYED — same polarity as ``check_roster_promotion_evidence.py``:
it compares the PARSED ``strategies:`` roster of every ``account_class: prop`` account at the fork
point against HEAD (plus an account moving INTO the prop class while carrying legs), so editing the
list cannot walk around it. DEMOTION IS FREE: a removal produces nothing, ever.

GRANDFATHERED, BY NAME, WITH A DUE DATE (not silently): ``GRANDFATHERED`` below. The two legs that
reached prop rosters before this rule — ``trend_donchian_eth_prop`` and ``trend_donchian_sol_prop`` —
are exempt from clauses 2 and 3 until their ``due`` date (row ``PROP-GATE-PARITY``; the dates were
the end dates of the retired ACCRUAL soak contracts and are kept as the exemption's lapse dates — the
mechanical soak that replaced them on 2026-10-15 has no end date). After ``due`` the exemption LAPSES: an add of that leg to
another prop account is refused like any other, and the whole-tree check prints a loud lapse notice
(a notice, not a failure — a CI-wide red on a calendar date is the desensitised alarm this repo
refuses; the dated checklist row + soak state carry the actual alarm). An entry may only be removed,
never added, without the operator's say — adding one is a roster-gate change.

Exit: 0 clean · 1 refused · 2 could not check.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
from _git_base import READ, UNREADABLE, read_at, resolve_base  # noqa: E402
import check_roster_promotion_evidence as rpe  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    print("prop-roster-gate: COULD NOT MEASURE — pyyaml is not installed", file=sys.stderr)
    sys.exit(2)

REPO = Path(__file__).resolve().parents[2]
ACCOUNTS_REL = "config/accounts.yaml"
SOAKS_REL = "docs/claude/work/SOAKS.json"
SURVIVAL_DIR_REL = "comms/prop_survival"
MACHINE_PREFIX = "PROP_ROSTER_GATE"
PROP_CLASS = "prop"
#: Mirrors ``scripts/ops/soak_state.py::STAGE1_ACCOUNTS`` (asserted equal in --self-test).
STAGE1_ACCOUNTS = ("bybit_1", "alpaca_paper")

#: leg -> (due date for its soak, citation). The ONLY exemption. See the module docstring.
GRANDFATHERED: Dict[str, Dict[str, str]] = {
    "trend_donchian_eth_prop": {
        "due": "2026-11-07",  # was SOAK-stage1-bybit_1-trend_donchian_eth_prop's (retired) end_date
        "decision": "operator 2026-10-15 'Yes, 1, 2 and 3a' (row PROP-GATE-PARITY)",
    },
    "trend_donchian_sol_prop": {
        "due": "2026-12-11",  # was SOAK-stage1-bybit_1-trend_donchian_sol_prop's (retired) end_date
        "decision": "operator 2026-10-15 'Yes, 1, 2 and 3a' (row PROP-GATE-PARITY)",
    },
}


def prop_adds(base_accounts: Optional[str], head_accounts: Optional[str]) -> List[Dict[str, str]]:
    """Legs this diff puts on a ``prop``-class roster. Removals return nothing."""
    base, head = rpe.rosters(base_accounts), rpe.rosters(head_accounts)
    found: List[Dict[str, str]] = []
    for acct, cur in sorted(head.items()):
        if cur["class"] != PROP_CLASS:
            continue
        prev = base.get(acct)
        was_prop = prev is not None and prev["class"] == PROP_CLASS
        known = set(prev["legs"]) if was_prop else set()
        for leg in cur["legs"]:
            if leg not in known:
                found.append({"account": acct, "leg": leg,
                              "why": "account moved into the prop class" if prev and not was_prop
                              else f"added to {acct}"})
    return found


def on_stage1_roster(leg: str, head_accounts: Optional[str]) -> Optional[str]:
    r = rpe.rosters(head_accounts)
    for a in STAGE1_ACCOUNTS:
        if leg in (r.get(a) or {}).get("legs", []):
            return a
    return None


def has_stage1_contract(leg: str, soaks: Sequence[Dict[str, Any]]) -> Optional[str]:
    for c in soaks:
        if c.get("leg") == leg and c.get("kind") == "stage1" and c.get("account") in STAGE1_ACCOUNTS:
            return str(c.get("id"))
    return None


def has_prop_live_soak(leg: str, soaks: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Operator amendment 2026-10-15: Stage-1 soak evidence may ALSO come from LIVE PROP trading.

    A contract for the leg carrying a ``sources`` entry of kind ``prop_live`` with a mechanical
    definition of done (``n_needed`` 1 or 2 and a ``checklist``) counts as a soak record. It is
    evidence for promotion decisions only. A source with no n_needed, or one above 2 (the retired
    accrual shape), does not count.
    """
    for c in soaks:
        if c.get("leg") != leg:
            continue
        for s in c.get("sources") or []:
            n = s.get("n_needed") if isinstance(s, dict) else None
            if (isinstance(s, dict) and s.get("kind") == "prop_live" and isinstance(n, int)
                    and not isinstance(n, bool) and 1 <= n <= 2 and s.get("checklist")):
                return str(c.get("id"))
    return None


def record_problems(rec: Optional[Dict[str, Any]], leg: str) -> List[str]:
    """Why ``comms/prop_survival/<leg>.json`` is not a prop survival-gate record. Empty = admissible.

    Fail closed: every field is required; a PR body is not a record.
      leg, harness (str), ruleset (str — the firm ruleset graded under), ev_net_usd (number),
      p_breach (number in [0,1]), n_trades (int >= 1), and decision_rule{id, registered_at,
      verdict == "pass"} — the rule registered BEFORE the run, passing.
    """
    if rec is None:
        return [f"no committed record at {SURVIVAL_DIR_REL}/{leg}.json"]
    p: List[str] = []
    if rec.get("leg") != leg:
        p.append(f"`leg` is {rec.get('leg')!r}, not {leg!r}")
    for k in ("harness", "ruleset"):
        if not str(rec.get(k) or "").strip():
            p.append(f"missing `{k}`")
    ev = rec.get("ev_net_usd")
    if isinstance(ev, bool) or not isinstance(ev, (int, float)):
        p.append("`ev_net_usd` is not a number")
    pb = rec.get("p_breach")
    if isinstance(pb, bool) or not isinstance(pb, (int, float)) or not 0 <= pb <= 1:
        p.append("`p_breach` is not a number in [0,1]")
    n = rec.get("n_trades")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        p.append("`n_trades` is not a stated integer >= 1")
    dr = rec.get("decision_rule")
    if not isinstance(dr, dict):
        p.append("missing `decision_rule` (the rule registered BEFORE the run)")
    else:
        if not str(dr.get("id") or "").strip() or not str(dr.get("registered_at") or "").strip():
            p.append("decision_rule needs `id` and `registered_at`")
        if dr.get("verdict") != "pass":
            p.append(f"decision_rule.verdict is {dr.get('verdict')!r}, not 'pass'")
    return p


def load_record(leg: str, survival_dir: Path) -> Optional[Dict[str, Any]]:
    p = survival_dir / f"{leg}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"_bad": True}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"_bad": True}


def grandfather_active(leg: str, today: date) -> Optional[Dict[str, str]]:
    g = GRANDFATHERED.get(leg)
    if g and today <= date.fromisoformat(g["due"]):
        return g
    return None


def grade(found: Sequence[Dict[str, str]], head_accounts: Optional[str], soaks: Sequence[Dict[str, Any]],
          survival_dir: Path, today: date) -> List[str]:
    out: List[str] = []
    for f in found:
        leg, acct = f["leg"], f["account"]
        if grandfather_active(leg, today):
            continue
        miss: List[str] = []
        if not (on_stage1_roster(leg, head_accounts) or has_stage1_contract(leg, soaks)
                or has_prop_live_soak(leg, soaks)):
            miss.append(f"no Stage-1 soak: {leg} is on neither {'/'.join(STAGE1_ACCOUNTS)} roster "
                        f"nor carries a SOAK-stage1-<acct>-{leg} contract (or a `prop_live` source) "
                        f"in {SOAKS_REL}")
        miss += [f"prop survival gate: {m}" for m in record_problems(load_record(leg, survival_dir), leg)]
        if miss:
            lapsed = " (grandfather LAPSED " + GRANDFATHERED[leg]["due"] + ")" if leg in GRANDFATHERED else ""
            out.append(f"{acct}/{leg} [{f['why']}]{lapsed}\n      - " + "\n      - ".join(miss))
    return out


def lapse_notices(head_accounts: Optional[str], today: date) -> List[str]:
    """Whole-tree NOTICES (never failures): a lapsed grandfather still on a prop roster."""
    r = rpe.rosters(head_accounts)
    out = []
    for leg, g in sorted(GRANDFATHERED.items()):
        if today > date.fromisoformat(g["due"]):
            on = [a for a, c in r.items() if c["class"] == PROP_CLASS and leg in c["legs"]]
            if on:
                out.append(f"grandfather for {leg} LAPSED {g['due']} and it is still on {', '.join(on)} — "
                           f"read SOAK-stage1-bybit_1-{leg}; PASS => file the survival record, "
                           f"FAIL => propose pulling it (data-backed Tier-3). Row PROP-GATE-PARITY.")
    return out


def _read(base_ref: str, rel: str):
    state, text = read_at(base_ref, rel, repo=REPO)
    if state == UNREADABLE:
        raise RuntimeError(f"base ref {base_ref!r} is unreadable — nothing was checked")
    path = REPO / rel
    head = path.read_text(encoding="utf-8") if path.is_file() else None
    return (text if state == READ else None), head


def self_test() -> int:
    ok = True

    def check(label: str, got: Any, want: Any) -> None:
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  [{'ok' if good else 'FAIL'}] {label}" + ("" if good else f"  got={got!r} want={want!r}"))

    def acc(prop_legs: List[str], paper_legs: List[str], prop_class: str = "prop") -> str:
        return yaml.safe_dump({"accounts": {
            "bybit_1": {"account_class": "paper", "strategies": paper_legs},
            "p1": {"account_class": prop_class, "strategies": prop_legs}}})

    try:
        import soak_state
        check("STAGE1_ACCOUNTS mirrors soak_state", STAGE1_ACCOUNTS, tuple(soak_state.STAGE1_ACCOUNTS))
    except ImportError:  # pragma: no cover
        pass
    today = date(2026, 10, 15)
    good = {"leg": "x", "harness": "run_ev_montecarlo", "ruleset": "breakout_turbo_1step", "ev_net_usd": 100.0,
            "p_breach": 0.2, "n_trades": 50,
            "decision_rule": {"id": "R", "registered_at": "2026-10-01", "verdict": "pass"}}
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "x.json").write_text(json.dumps(good))
        base = acc(["old"], [])
        # new leg, no soak, no record -> refused on both
        f = prop_adds(base, acc(["old", "x"], []))
        r = grade(f, acc(["old", "x"], []), [], d, today)
        check("no soak -> refused (soak clause)", len(r) == 1 and "no Stage-1 soak" in r[0], True)
        # on bybit_1 + record -> clean
        h = acc(["old", "x"], ["x"])
        check("soak roster + record -> clean", grade(prop_adds(base, h), h, [], d, today), [])
        # soak ok, record absent -> refused on survival only
        h = acc(["old", "y"], ["y"])
        r = grade(prop_adds(base, h), h, [], d, today)
        check("no survival record -> refused", len(r) == 1 and "prop survival gate" in r[0]
              and "no Stage-1 soak" not in r[0], True)
        # contract (not roster) satisfies the soak clause
        h = acc(["old", "x"], [])
        c = [{"leg": "x", "kind": "stage1", "account": "bybit_1", "id": "SOAK-stage1-bybit_1-x"}]
        check("contract alone satisfies soak clause", grade(prop_adds(base, h), h, c, d, today), [])
        # amendment: a prop_live source on a contract also satisfies the soak clause
        pl = [{"leg": "x", "id": "S", "sources": [{"kind": "prop_live", "n_needed": 2,
                                                  "checklist": ["signal_fired"]}]}]
        h2 = acc(["old", "x"], [])
        check("prop_live source satisfies soak clause", grade(prop_adds(base, h2), h2, pl, d, today), [])
        pl[0]["sources"][0]["n_needed"] = 10
        check("a retired accrual-shaped prop_live source (n_needed 10) does not",
              len(grade(prop_adds(base, h2), h2, pl, d, today)), 1)
        pl[0]["sources"][0].update(n_needed=2, checklist=[])
        check("prop_live source without a checklist does not", len(grade(prop_adds(base, h2), h2, pl, d, today)), 1)
        # bad record (verdict fail) refused
        (d / "x.json").write_text(json.dumps(dict(good, decision_rule={"id": "R", "registered_at": "z",
                                                                       "verdict": "fail"})))
        check("verdict fail -> refused", len(grade(prop_adds(base, h), h, c, d, today)), 1)
        # demotion is free
        check("removal -> nothing", prop_adds(acc(["old", "x"], []), acc(["old"], [])), [])
        # class flip into prop arms every leg
        check("class flip detected",
              [x["leg"] for x in prop_adds(acc(["a"], [], "paper"), acc(["a"], [], "prop"))], ["a"])
        # grandfather: exempt before due, lapsed after
        g = "trend_donchian_eth_prop"
        h = acc(["old", g], [])
        check("grandfathered before due", grade(prop_adds(base, h), h, [], d, today), [])
        r = grade(prop_adds(base, h), h, [], d, date(2026, 11, 8))
        check("grandfather lapses after due", len(r) == 1 and "LAPSED" in r[0], True)
        check("lapse notice (whole tree)", len(lapse_notices(h, date(2026, 11, 8))), 1)
        check("no lapse notice before due", lapse_notices(h, today), [])
        # a leg named like a grandfathered one is NOT exempt (exact name)
        h = acc(["old", g + "_2"], [])
        check("exemption is by exact name", len(grade(prop_adds(base, h), h, [], d, today)), 1)
    print("self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--today", default=None, help="ISO date override (tests)")
    args = ap.parse_args(argv)
    # NOTICE only (no stash, no exit-code change): this guard grades a COMMIT RANGE, so a dirty tree
    # is a verdict about a different tree. Same shared notice as the other diff-scoped guards.
    import _dirty_tree  # noqa: PLC0415 — the path shim is at module level
    _dirty_tree.warn()
    if args.self_test:
        return self_test()
    today = date.fromisoformat(args.today) if args.today else date.today()
    base_ref, _ = resolve_base(args.base, repo=REPO)
    try:
        base_acc, head_acc = _read(base_ref, ACCOUNTS_REL)
        soaks = json.loads((REPO / SOAKS_REL).read_text(encoding="utf-8")).get("soaks") or []
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"prop-roster-gate: COULD NOT MEASURE — {exc}", file=sys.stderr)
        return 2
    for n in lapse_notices(head_acc, today):
        print(f"prop-roster-gate: NOTICE — {n}")
    found = prop_adds(base_acc, head_acc)
    if not found:
        print("prop-roster-gate: clean (this diff adds no leg to a prop roster)")
        return 0
    findings = grade(found, head_acc, soaks, REPO / SURVIVAL_DIR_REL, today)
    if not findings:
        print(f"prop-roster-gate: clean ({len(found)} prop roster add(s), each soaked/grandfathered "
              f"and carrying a survival record)")
        return 0
    print("🚨 PROP ROSTER GATE: a leg reaches a PROP roster without clearing the superset bar "
          "(operator 2026-10-15: prop clears everything real-money clears, PLUS prop DD survival).",
          file=sys.stderr)
    print("   Needs: a Stage-1 soak (bybit_1/alpaca_paper roster or a SOAK-stage1 contract) AND "
          f"{SURVIVAL_DIR_REL}/<leg>.json. Demotion needs nothing.\n", file=sys.stderr)
    for f in findings:
        print(f"  - {f}", file=sys.stderr)
        print(f"{MACHINE_PREFIX}\t{f.splitlines()[0]}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
