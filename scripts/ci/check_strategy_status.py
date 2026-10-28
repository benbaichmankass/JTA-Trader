#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py (strategy-status-guard)
"""strategy-status-guard — every leg is on exactly ONE of {general paper} or {real money + mirror}.

Operator, 2026-10-28 (decision "Adopt; build it this week", relayed by the manager): three statuses —
testing (general paper), production (real money + the paper-portfolio mirror, NOT general paper),
inactive (retired by record). Status derivation: ``scripts/ops/strategy_status.py``. Rule:
``docs/plans/OPERATING-PLAN-2026-09-21.md`` § 2 "Three strategy statuses".

WHY A NEW GUARD. CI is asymmetric (CLAUDE.md § "The two execution gates"): nothing guards a leg being
REMOVED from a roster, and nothing guards a leg sitting on two books at once. Promotion now MOVES a leg
(off general paper, onto real money + mirror) and demotion moves it back, so both directions need a
check, keyed on ROSTER MEMBERSHIP (not the ``mode`` / ``execution`` fields, which a roster edit walks
around). WHOLE TREE, not diff-scoped: the books are the population.

REFUSES (exit 1):
  R-DUAL-BOOK      a production leg (on bybit_2 / alpaca_live / ib_live) that is also on a general paper
                   roster (bybit_1 / alpaca_paper / ib_paper) — the duplicate trade this model removes.
  R-NO-MIRROR      a production leg its real-money account's mirror does not carry (minus the declared
                   affordability carve-out), or a real-money account with legs and no mirror (ib_live).
  R-INACTIVE-ROSTERED  a leg retired by record (``enabled: false``) still on ANY roster.
  R-UNHOMED        a non-retired leg on neither book (it trades nowhere and is not retired) — unless it
                   is named in UNHOMED below with its reason and owning row. A demotion that drops a leg
                   instead of moving it back to general paper lands here.
Prop rosters and ``alpaca_options_paper`` are reported, not judged: a leg's status is set by the two
books alone (where prop legs belong is an open operator question).

Exit: 0 clean · 1 refused · 2 could not check.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "ops"))
try:
    import strategy_status as st  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(f"strategy-status: COULD NOT MEASURE — {exc}", file=sys.stderr)
    sys.exit(2)

#: Non-retired legs on no book, BY NAME, each with why and the row that owns the decision. Adding a
#: name here is a roster decision, not a test edit. Measured 2026-10-28 on main (strategy_status.py).
UNHOMED: Dict[str, str] = {
    leg: ("cut from alpaca_paper 2026-10-05 by MD-S1-CUT-ON-STAGE0-FAIL (PR #16548), before the "
          "2026-10-27 demo-floor rule; never restored and never retired. Testing (back on alpaca_paper) "
          "or inactive (enabled: false) is an operator question — row STRATEGY-STATUS-MODEL")
    for leg in ("gld_pullback_1h", "spy_pullback_1h", "qqq_pullback_1h", "tlt_pullback_1h")
}


def findings(accounts: Dict[str, Any], strategies: Dict[str, Any]) -> List[str]:
    ros = st.rosters(accounts)
    out: List[str] = []
    for real, mirror in st.REAL_MONEY_MIRROR.items():
        legs = ros.get(real, [])
        if legs and mirror is None:
            out.append(f"R-NO-MIRROR {real} carries {legs} and has no paper-portfolio mirror account")
        for leg in legs:
            dual = [a for a in st.GENERAL_PAPER if leg in ros.get(a, [])]
            if dual:
                out.append(f"R-DUAL-BOOK {leg} is production ({real}) and also on general paper {dual}: "
                           f"remove it from {dual} (promotion MOVES a leg; OPERATING-PLAN § 2)")
            if mirror and leg not in ros.get(mirror, []) and leg not in st.MIRROR_CARVE_OUT.get(mirror, ()):
                out.append(f"R-NO-MIRROR {leg} is on {real} but not on its mirror {mirror}")
    on_book = {leg for a in (*st.GENERAL_PAPER, *st.REAL_MONEY_MIRROR) for leg in ros.get(a, [])}
    for leg in sorted(strategies):
        if not isinstance(strategies.get(leg), dict):
            continue
        if st.retired(strategies, leg):
            where = sorted(a for a, legs in ros.items() if leg in legs)
            if where:
                out.append(f"R-INACTIVE-ROSTERED {leg} is retired by record (enabled: false) but on {where}")
        elif leg not in on_book and leg not in UNHOMED:
            out.append(f"R-UNHOMED {leg} is not retired and is on neither general paper "
                       f"{list(st.GENERAL_PAPER)} nor real money {list(st.REAL_MONEY_MIRROR)}: put it back "
                       "on its general paper account, or retire it by record (enabled: false)")
    return out


def self_test() -> int:
    ok = True

    def ck(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")

    strat = {"a": {}, "p": {}, "r": {"enabled": False}, "iaum_pullback_1d": {}}
    clean = {"bybit_1": {"strategies": ["a"]}, "bybit_2": {"strategies": ["p"]},
             "bybit_portfolio": {"strategies": ["p"]}, "alpaca_live": {"strategies": ["iaum_pullback_1d"]},
             "alpaca_portfolio": {"strategies": []}}
    ck("a clean tree passes (positive control)", findings(clean, strat) == [])
    dual = {**clean, "bybit_1": {"strategies": ["a", "p"]}}
    ck("a production leg left on general paper is refused (R-DUAL-BOOK)",
       any(f.startswith("R-DUAL-BOOK p") for f in findings(dual, strat)))
    nomir = {**clean, "bybit_portfolio": {"strategies": []}}
    ck("a production leg its mirror lacks is refused (R-NO-MIRROR)",
       any(f.startswith("R-NO-MIRROR p") for f in findings(nomir, strat)))
    ck("the declared affordability carve-out is not a missing mirror",
       not any("iaum" in f for f in findings(clean, strat)))
    ib = {**clean, "ib_live": {"strategies": ["a"]}}
    ck("a real-money account with no mirror account is refused", any("ib_live" in f for f in findings(ib, strat)))
    ret = {**clean, "bybit_1": {"strategies": ["a", "r"]}}
    ck("a retired leg on a roster is refused (R-INACTIVE-ROSTERED)",
       any(f.startswith("R-INACTIVE-ROSTERED r") for f in findings(ret, strat)))
    drop = {**clean, "bybit_1": {"strategies": []}}
    ck("a non-retired leg dropped from every book is refused (R-UNHOMED)",
       any(f.startswith("R-UNHOMED a") for f in findings(drop, strat)))
    ck("a named UNHOMED leg is not refused",
       findings(clean, {**strat, "gld_pullback_1h": {}}) == [])
    ck("prop rosters are not judged", findings({**clean, "breakout_2": {"strategies": ["a", "p"]}}, strat) == [])
    print(f"strategy-status self-test: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    accounts, strategies = st.load(REPO)
    if not accounts or not strategies:
        print("strategy-status: COULD NOT MEASURE — config/accounts.yaml or config/strategies.yaml "
              "empty or unreadable", file=sys.stderr)
        return 2
    t = st.table(REPO)
    counts: Dict[str, int] = {}
    for row in t.values():
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"strategy-status: population {len(t)} legs in {st.STRATEGIES_REL} — "
          + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
          + f"; {len(UNHOMED)} named UNHOMED")
    out = findings(accounts, strategies)
    for f in out:
        print(f"  REFUSED {f}")
    print(f"strategy-status: {'REFUSED' if out else 'OK'} ({len(out)} finding(s))")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
