#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py (same-symbol-allocation-guard)
"""same-symbol-allocation-guard — two ROSTERED legs on one (account, symbol) need a measured allocation.

OPERATOR, 2026-10-15 (verbatim): "If we're running the same strategy and symbol on 2 different timeframes,
than we need to make sure that we know how to allocate the trades properly (and not, say alphabetically), or
we need to choose the better one based on testing on run with that one".

THE MECHANICAL FACT (MEASURED by the manager): a one-way venue holds ONE net position per symbol, so when
two rostered legs on the same account signal on the same symbol the election
(``src/runtime/intents.py::_election_sort_key``) picks one: -confidence (about 50% exact ties), then declared
priority, then 3-day realized PnL, then timestamp, then the strategy NAME. No backtest-quality term exists, so
a tie is decided alphabetically. This guard makes that a thing you cannot add silently.

WHAT IT CHECKS (whole tree, at HEAD): every (account, symbol) with >= 2 legs on the account's ``strategies:``
roster, where a leg's symbols are ``config/strategies.yaml::<leg>.symbols``. Roster membership is the key, not
``execution:`` — a ``shadow`` leg is elected too (it suppresses live legs for the tick), so it counts.
A group PASSES if ONE of:

  (a) a committed head-to-head record in ``comms/same_symbol_allocation/*.json`` covers it: ``verdict`` ==
      ``pass``, a ``winner``, ``harness`` naming ``backtest_system``, ``covers`` listing ``{account, symbol}``
      for the group, and ``legs`` equal to the group's legs. Produced by
      ``scripts/research/same_symbol_head_to_head.py`` (unit ``head_to_head`` block); or
  (b) EVERY leg of the group has a DISTINCT, NON-ZERO entry in ``DEFAULT_PRIORITIES`` AND ``intents.py``
      carries a ``# same-symbol-evidence: <account>/<SYMBOL> <path>`` line whose path exists (the record the
      ordering cites). A non-zero priority with no cited record fails — a number is not a measurement.

GRANDFATHERED, BY NAME, WITH A DUE DATE: ``GRANDFATHERED`` below — today's pairs, each with the research unit
whose landing is expected by ``due``. The exemption is the exact (account, symbol) AND exact leg set, so a
third leg, or a different pair, on the same key is refused. After ``due`` it LAPSES: the whole-tree run prints
a loud NOTICE (not a failure — a calendar-date red is the desensitised alarm this repo refuses; the
checklist row SAME-SYMBOL-ALLOCATION and the unit carry the alarm), and the key is graded like any other
only if the entry is REMOVED. Entries may be removed, never added, without the operator's say.

Exit: 0 clean · 1 refused · 2 could not check.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    print("same-symbol-allocation: COULD NOT MEASURE — pyyaml is not installed", file=sys.stderr)
    sys.exit(2)

REPO = Path(__file__).resolve().parents[2]
ACCOUNTS_REL = "config/accounts.yaml"
STRATEGIES_REL = "config/strategies.yaml"
INTENTS_REL = "src/runtime/intents.py"
RECORDS_REL = "comms/same_symbol_allocation"
MACHINE_PREFIX = "SAME_SYMBOL_ALLOCATION"

Key = Tuple[str, str]  # (account, symbol)

#: "account/SYMBOL" -> exemption. The ONLY one. ``unit`` is the research unit whose landing closes it.
GRANDFATHERED: Dict[str, Dict[str, Any]] = {
    "bybit_1/ETHUSDT": {"legs": ["trend_donchian_eth_4h", "trend_donchian_eth_prop"],
                        "unit": "RQ-20261015-1631-01", "due": "2026-10-29"},
    "bybit_1/XRPUSDT": {"legs": ["trend_donchian_xrp_4h", "xrp_pullback_2h"],
                        "unit": "RQ-20261015-1631-02", "due": "2026-10-29"},
    "bybit_2/XRPUSDT": {"legs": ["trend_donchian_xrp_4h", "xrp_pullback_2h"],
                        "unit": "RQ-20261015-1631-02", "due": "2026-10-29"},
    "bybit_portfolio/XRPUSDT": {"legs": ["trend_donchian_xrp_4h", "xrp_pullback_2h"],
                                "unit": "RQ-20261015-1631-02", "due": "2026-10-29"},
    # Blocked units: the harness cannot run these legs yet (see each unit's blocked_on). Dated for the unblock + a run.
    "ib_paper/MGC": {"legs": ["ict_scalp_mgc_15m", "mgc_pullback_1d", "mgc_trend_1h"],
                     "unit": "RQ-20261015-1631-03", "due": "2026-11-30"},
    "alpaca_paper/SLV": {"legs": ["slv_pullback_1d", "slv_trend_1h"],
                         "unit": "RQ-20261015-1631-04", "due": "2026-11-30"},
    "alpaca_options_paper/SLV": {"legs": ["slv_pullback_1d", "slv_trend_1h"],
                                 "unit": "RQ-20261015-1631-04", "due": "2026-11-30"},
    # OWNED BY ANOTHER LANE (PROMOTE-PROP-LEGS puts trend_donchian_eth_prop on bybit_2 beside trend_donchian_eth_4h).
    # No unit here by instruction; its verdict is that lane's, via RQ-20261015-1631-01's pair measurement or its own.
    "bybit_2/ETHUSDT": {"legs": ["trend_donchian_eth_4h", "trend_donchian_eth_prop"],
                        "unit": "RQ-20261015-1631-01 (owner: lane PROMOTE-PROP-LEGS)", "due": "2026-10-29"},
}


def groups(accounts_text: str, strategies_text: str) -> Dict[Key, List[str]]:
    """(account, symbol) -> sorted legs, only where >= 2 legs share the key."""
    acc = (yaml.safe_load(accounts_text) or {}).get("accounts") or {}
    strat = (yaml.safe_load(strategies_text) or {}).get("strategies") or {}
    out: Dict[Key, List[str]] = defaultdict(list)
    for name, a in acc.items():
        for leg in (a or {}).get("strategies") or []:
            if not isinstance(leg, str):
                continue
            for sym in (strat.get(leg) or {}).get("symbols") or []:
                out[(name, str(sym))].append(leg)
    return {k: sorted(set(v)) for k, v in sorted(out.items()) if len(set(v)) >= 2}


def load_records(rec_dir: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if rec_dir.is_dir():
        for p in sorted(rec_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                out.append({"_unreadable": p.name})
    return out


def record_covers(rec: Dict[str, Any], key: Key, legs: List[str]) -> bool:
    return (rec.get("verdict") == "pass" and bool(rec.get("winner"))
            and "backtest_system" in str(rec.get("harness", ""))
            and sorted(rec.get("legs") or []) == legs
            and any(c.get("account") == key[0] and c.get("symbol") == key[1] for c in rec.get("covers") or []))


def priorities(intents_text: str) -> Dict[str, int]:
    for node in ast.walk(ast.parse(intents_text)):
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if "DEFAULT_PRIORITIES" in targets and getattr(node, "value", None) is not None:
            try:
                return {str(k): int(v) for k, v in ast.literal_eval(node.value).items()}
            except (ValueError, TypeError):
                return {}
    return {}


def priority_citation_ok(intents_text: str, key: Key, legs: List[str], repo: Path) -> bool:
    prio = priorities(intents_text)
    vals = [prio.get(leg, 0) for leg in legs]
    if any(v == 0 for v in vals) or len(set(vals)) != len(vals):
        return False
    pat = re.compile(r"#\s*same-symbol-evidence:\s*" + re.escape(f"{key[0]}/{key[1]}") + r"\s+(\S+)")
    return any((repo / m.group(1)).exists() for m in pat.finditer(intents_text))


def grandfather_active(key: Key, legs: List[str], today: date) -> Optional[Dict[str, Any]]:
    g = GRANDFATHERED.get(f"{key[0]}/{key[1]}")
    if g and sorted(g["legs"]) == legs and today <= date.fromisoformat(g["due"]):
        return g
    return None


def grade(grp: Dict[Key, List[str]], records: List[Dict[str, Any]], intents_text: str, repo: Path,
          today: date) -> List[str]:
    out: List[str] = []
    for key, legs in grp.items():
        if any(record_covers(r, key, legs) for r in records):
            continue
        if priority_citation_ok(intents_text, key, legs, repo):
            continue
        if grandfather_active(key, legs, today):
            continue
        g = GRANDFATHERED.get(f"{key[0]}/{key[1]}")
        why = ""
        if g and sorted(g["legs"]) == legs:
            why = f" (grandfather for {key[0]}/{key[1]} LAPSED {g['due']}; unit {g['unit']})"
        elif g:
            why = f" (grandfather names legs {g['legs']}, roster has {legs} — exemption is by exact leg set)"
        out.append(f"{key[0]} / {key[1]}: legs {legs} share one position slot and the election is "
                   f"confidence-tie -> name; no head-to-head record in {RECORDS_REL}/ and no distinct non-zero "
                   f"DEFAULT_PRIORITIES ordering citing one{why}")
    return out


def lapse_notices(grp: Dict[Key, List[str]], today: date) -> List[str]:
    out = []
    for ks, g in sorted(GRANDFATHERED.items()):
        a, s = ks.split("/", 1)
        if grp.get((a, s)) == sorted(g["legs"]) and today > date.fromisoformat(g["due"]):
            out.append(f"grandfather for {ks} LAPSED {g['due']} and the pair is still rostered — unit {g['unit']} "
                       f"should have landed; the next PR touching it is graded like any other")
    return out


def self_test() -> int:
    ok = True

    def check(name: str, got: Any, want: Any) -> None:
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: got {got!r}, want {want!r}")

    strat = yaml.safe_dump({"strategies": {"a": {"symbols": ["X"]}, "b": {"symbols": ["X"]}, "c": {"symbols": ["Y"]},
                                           "d": {"symbols": ["X"]}}})

    def acct(roster: Dict[str, List[str]]) -> str:
        return yaml.safe_dump({"accounts": {n: {"strategies": r} for n, r in roster.items()}})

    today = date(2026, 10, 15)
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "comms").mkdir()
        # --- detection
        g = groups(acct({"acc": ["a", "b", "c"]}), strat)
        check("pair detected, singletons ignored", g, {("acc", "X"): ["a", "b"]})
        check("one leg per symbol -> nothing", groups(acct({"acc": ["a", "c"]}), strat), {})
        check("same leg twice is not a pair", groups(acct({"acc": ["a", "a"]}), strat), {})
        check("per-account keys", sorted(groups(acct({"p": ["a", "b"], "q": ["a", "b"]}), strat)),
              [("p", "X"), ("q", "X")])
        check("unknown leg ignored", groups(acct({"acc": ["a", "zzz"]}), strat), {})
        # --- refusal and (a)
        key = ("acc", "X")
        check("unevidenced pair refused", len(grade(g, [], "DEFAULT_PRIORITIES = {}", repo, today)), 1)
        good = {"verdict": "pass", "winner": "solo:a", "harness": "scripts/backtest_system.py",
                "legs": ["a", "b"], "covers": [{"account": "acc", "symbol": "X"}]}
        check("(a) record passes", grade(g, [good], "", repo, today), [])
        check("(a) verdict indeterminate refused", len(grade(g, [dict(good, verdict="indeterminate")], "", repo, today)), 1)
        check("(a) no winner refused", len(grade(g, [dict(good, winner=None)], "", repo, today)), 1)
        check("(a) wrong harness refused", len(grade(g, [dict(good, harness="vibes")], "", repo, today)), 1)
        check("(a) other account refused", len(grade(g, [dict(good, covers=[{"account": "zz", "symbol": "X"}])], "", repo, today)), 1)
        check("(a) different leg set refused", len(grade(g, [dict(good, legs=["a", "b", "d"])], "", repo, today)), 1)
        g3 = groups(acct({"acc": ["a", "b", "d"]}), strat)
        check("third leg voids a 2-leg record", len(grade(g3, [good], "", repo, today)), 1)
        # --- (b) priorities
        (repo / "comms" / "h2h.json").write_text("{}")
        cite = "# same-symbol-evidence: acc/X comms/h2h.json\n"
        src = lambda p: "DEFAULT_PRIORITIES = " + json.dumps(p) + "\n"  # noqa: E731
        check("(b) distinct non-zero + citation passes", grade(g, [], src({"a": 10, "b": 20}) + cite, repo, today), [])
        check("(b) citation to a missing file refused",
              len(grade(g, [], src({"a": 10, "b": 20}) + "# same-symbol-evidence: acc/X comms/nope.json\n", repo, today)), 1)
        check("(b) no citation refused", len(grade(g, [], src({"a": 10, "b": 20}), repo, today)), 1)
        check("(b) a zero priority refused", len(grade(g, [], src({"a": 10, "b": 0}) + cite, repo, today)), 1)
        check("(b) equal priorities refused", len(grade(g, [], src({"a": 10, "b": 10}) + cite, repo, today)), 1)
        check("(b) missing leg counts as 0", len(grade(g, [], src({"a": 10}) + cite, repo, today)), 1)
        check("(b) citation for another key refused",
              len(grade(g, [], src({"a": 10, "b": 20}) + "# same-symbol-evidence: acc/Y comms/h2h.json\n", repo, today)), 1)
    # --- grandfather (real table, real keys)
    gk = ("bybit_1", "XRPUSDT")
    legs = sorted(GRANDFATHERED["bybit_1/XRPUSDT"]["legs"])
    grp = {gk: legs}
    check("grandfathered before due", grade(grp, [], "", REPO, today), [])
    due = date.fromisoformat(GRANDFATHERED["bybit_1/XRPUSDT"]["due"])
    r = grade(grp, [], "", REPO, date.fromordinal(due.toordinal() + 1))
    check("grandfather lapses after due", len(r) == 1 and "LAPSED" in r[0], True)
    check("lapse notice", len(lapse_notices(grp, date.fromordinal(due.toordinal() + 1))), 1)
    check("no lapse notice before due", lapse_notices(grp, today), [])
    check("exemption is by exact leg set (third leg)", len(grade({gk: legs + ["zz"]}, [], "", REPO, today)), 1)
    check("exemption is by exact key (other account)", len(grade({("bybit_9", "XRPUSDT"): legs}, [], "", REPO, today)), 1)
    check("every grandfather has a unit and a due", all(g.get("unit") and g.get("due") for g in GRANDFATHERED.values()), True)
    print("self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--today", default=None, help="ISO date override (tests)")
    ap.add_argument("--list", action="store_true", help="print the inventory and exit")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    today = date.fromisoformat(args.today) if args.today else date.today()
    try:
        grp = groups((REPO / ACCOUNTS_REL).read_text(encoding="utf-8"),
                     (REPO / STRATEGIES_REL).read_text(encoding="utf-8"))
        intents = (REPO / INTENTS_REL).read_text(encoding="utf-8")
    except (OSError, ValueError, yaml.YAMLError, SyntaxError) as exc:
        print(f"same-symbol-allocation: COULD NOT MEASURE — {exc}", file=sys.stderr)
        return 2
    if args.list:
        for (a, s), legs in grp.items():
            print(f"{a}\t{s}\t{', '.join(legs)}")
        return 0
    for n in lapse_notices(grp, today):
        print(f"same-symbol-allocation: NOTICE — {n}")
    findings = grade(grp, load_records(REPO / RECORDS_REL), intents, REPO, today)
    if not findings:
        print(f"same-symbol-allocation: clean ({len(grp)} same-symbol group(s) over "
              f"{ACCOUNTS_REL} x {STRATEGIES_REL}; each evidenced or grandfathered with a due date)")
        return 0
    print("🚨 SAME-SYMBOL ALLOCATION: two rostered legs share one (account, symbol) slot with no measured allocation "
          "(operator 2026-10-15: not alphabetically — measure it, or pick the better one).", file=sys.stderr)
    print(f"   Needs: a head-to-head record in {RECORDS_REL}/ (scripts/research/same_symbol_head_to_head.py) OR distinct "
          "non-zero DEFAULT_PRIORITIES citing one. Removing a leg from the roster needs nothing.\n", file=sys.stderr)
    for f in findings:
        print(f"  - {f}", file=sys.stderr)
        print(f"{MACHINE_PREFIX}\t{f.splitlines()[0]}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
