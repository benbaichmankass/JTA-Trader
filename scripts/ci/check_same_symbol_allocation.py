#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py (same-symbol-allocation-guard)
"""same-symbol-allocation-guard — legs sharing one (account, symbol) need a KNOWN allocation, not a name tiebreak.

OPERATOR, 2026-10-15 (verbatim, re-scope ~20:25Z): "We can have different strategies working with netted positions as
long as we know how much of that position belongs to each strategy, and each piece of that position has its own
brackets ... We don't need to collapse it, we just need to make sure we know how to allocate between the trades
correctly. And it should be based on those other things, not just backtesting."

SHARING IS NOT THE FAILURE. A one-way venue holds one net position per symbol and the election
(``src/runtime/intents.py::_election_sort_key``) falls through confidence-tie -> declared priority -> 3d PnL ->
timestamp -> strategy NAME. The failure is a shared slot whose split nobody has recorded.

WHAT IT CHECKS (whole tree, at HEAD): every (account, symbol) with >= 2 legs on the account's ``strategies:`` roster,
where a leg's symbols are ``config/strategies.yaml::<leg>.symbols``. Roster membership is the key, not ``execution:``
(a ``shadow`` leg is elected too). A group PASSES if ONE of:

  (a) its ACCOUNT has slice support — ``SLICE_SUPPORT_ACCOUNTS`` below. EMPTY today: lane NETTED-SLICES owns the
      per-strategy slice + per-slice bracket build and its config shape is not on main yet. When it lands, that lane
      (or a follow-up) fills this from the real config field; do NOT guess a shape here; or
  (b) a committed allocation-weights record in ``comms/same_symbol_allocation/*.json`` covers it: ``kind`` ==
      ``allocation_weights``, ``covers`` lists ``{account, symbol}`` for the group, ``legs`` equal to the group's legs,
      ``weights`` a number per leg summing to ~1, and ``inputs`` naming the existing allocator factors used
      (``src/runtime/allocator_ev.py`` / ``allocator_corr.py`` / ``allocator_soak.py`` / ``conviction_*``) — backtest
      quality (``same_symbol_head_to_head.py`` output) is ONE such input, not the whole basis.

GRANDFATHERED, BY NAME, WITH A DUE DATE: ``GRANDFATHERED`` below — today's pairs, each with the unit that produces its
backtest-quality input and a due date. Exemption is the exact (account, symbol) AND exact leg set. After ``due`` it
LAPSES: the whole-tree run prints a NOTICE (not a failure — a calendar-date red is the desensitised alarm this repo
refuses; checklist row SAME-SYMBOL-ALLOCATION carries the alarm). Entries may be removed, never added, without the
operator's say.

Exit: 0 clean · 1 refused · 2 could not check.
"""
from __future__ import annotations

import argparse
import json
import sys
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
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
ACCOUNTS_REL = "config/accounts.yaml"
STRATEGIES_REL = "config/strategies.yaml"
RECORDS_REL = "comms/same_symbol_allocation"
MACHINE_PREFIX = "SAME_SYMBOL_ALLOCATION"

Key = Tuple[str, str]  # (account, symbol)

#: "account/SYMBOL" -> exemption. The ONLY one. ``unit`` is the research unit whose landing closes it.
GRANDFATHERED: Dict[str, Dict[str, Any]] = {
    "bybit_1/ETHUSDT": {"legs": ["trend_donchian_eth_4h", "trend_donchian_eth_prop"],
                        "unit": "RQ-20261015-1631-01", "due": "2026-10-29"},
    # 2026-10-22 OPERATOR-DECISIONS-1022: bybit_1 runs the soak alias trend_donchian_xrp_adx25 (an exact copy
    # of trend_donchian_xrp_4h plus the declared ADX trail) in place of the incumbent: SAME pair, SAME unit and
    # due date, one leg renamed. bybit_2 / bybit_portfolio keep the incumbent (entries below).
    "bybit_1/XRPUSDT": {"legs": ["trend_donchian_xrp_adx25", "xrp_pullback_2h"],
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


#: Legs that never SHARE a symbol's position on an account without slice support: the coordinator refuses the second
#: arrival per package, journalled (``src/units/strategies/claude_desk.py::exclusive_hold_refusal``, called from
#: ``Coordinator.multi_account_execute``; DESK-PAPER-ACCOUNTS 2026-10-27). Such a leg is not part of a shared slot, so it
#: is left out of the group. ``self_test`` pins the coordinator call: delete the refusal and this guard goes red.
EXCLUSIVE_HOLD_LEGS: frozenset = frozenset({"claude_desk"})
COORDINATOR_REL = "src/core/coordinator.py"


def groups(accounts_text: str, strategies_text: str) -> Dict[Key, List[str]]:
    """(account, symbol) -> sorted legs, only where >= 2 legs share the key. A leg's symbols on an account are its
    per-account scope when it declares ``account_symbols`` (``src.config.symbol_sets.leg_symbols``)."""
    from src.config.symbol_sets import leg_symbols

    acc = (yaml.safe_load(accounts_text) or {}).get("accounts") or {}
    strat = (yaml.safe_load(strategies_text) or {}).get("strategies") or {}
    out: Dict[Key, List[str]] = defaultdict(list)
    for name, a in acc.items():
        for leg in (a or {}).get("strategies") or []:
            if not isinstance(leg, str):
                continue
            if leg in EXCLUSIVE_HOLD_LEGS and name not in SLICE_SUPPORT_ACCOUNTS:
                continue
            for sym in leg_symbols(strat.get(leg), name):
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


#: Accounts whose per-strategy slices + per-slice brackets are live (lane NETTED-SLICES). Empty until that config lands.
#: bybit_1 declares `position_model: slices` in config/accounts.yaml (NETTED-SLICES soak, operator 2026-10-15) and the runtime implements it
#: (src/runtime/positions.py POSITION_MODEL_KEY / admit_slice; weights from config/slice_allocation.yaml). Listed here because the
#: roster-add of ict_scalp_eth_15m / ict_scalp_xrp_15m (DESK-8-SHORT-HOLD-S0) otherwise fails this guard on the XRP and ETH leg sets.
#: bybit_2 / bybit_portfolio do NOT declare it and stay graded. ROLLBACK: empty this set (and restore the self-test assertion below).
SLICE_SUPPORT_ACCOUNTS: frozenset = frozenset({"bybit_1"})

_ALLOCATOR_FACTORS = ("allocator_ev", "allocator_corr", "allocator_soak", "conviction")


def record_covers(rec: Dict[str, Any], key: Key, legs: List[str]) -> bool:
    w = rec.get("weights")
    if not (rec.get("kind") == "allocation_weights" and isinstance(w, dict) and sorted(w) == legs):
        return False
    try:
        if abs(sum(float(v) for v in w.values()) - 1.0) > 1e-6 or any(float(v) < 0 for v in w.values()):
            return False
    except (TypeError, ValueError):
        return False
    inputs = " ".join(str(i) for i in rec.get("inputs") or [])
    return (sorted(rec.get("legs") or []) == legs
            and any(f in inputs for f in _ALLOCATOR_FACTORS)
            and any(c.get("account") == key[0] and c.get("symbol") == key[1] for c in rec.get("covers") or []))


def grandfather_active(key: Key, legs: List[str], today: date) -> Optional[Dict[str, Any]]:
    g = GRANDFATHERED.get(f"{key[0]}/{key[1]}")
    if g and sorted(g["legs"]) == legs and today <= date.fromisoformat(g["due"]):
        return g
    return None


def grade(grp: Dict[Key, List[str]], records: List[Dict[str, Any]], today: date) -> List[str]:
    out: List[str] = []
    for key, legs in grp.items():
        if key[0] in SLICE_SUPPORT_ACCOUNTS:
            continue
        if any(record_covers(r, key, legs) for r in records):
            continue
        if grandfather_active(key, legs, today):
            continue
        g = GRANDFATHERED.get(f"{key[0]}/{key[1]}")
        why = ""
        if g and sorted(g["legs"]) == legs:
            why = f" (grandfather for {key[0]}/{key[1]} LAPSED {g['due']}; unit {g['unit']})"
        elif g:
            why = f" (grandfather names legs {g['legs']}, roster has {legs} — exemption is by exact leg set)"
        out.append(f"{key[0]} / {key[1]}: legs {legs} share one net position and the election falls through "
                   f"confidence-tie -> name; the account has no slice support and {RECORDS_REL}/ has no "
                   f"allocation-weights record for it{why}")
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
    global SLICE_SUPPORT_ACCOUNTS
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
    g = groups(acct({"acc": ["a", "b", "c"]}), strat)
    check("pair detected, singletons ignored", g, {("acc", "X"): ["a", "b"]})
    check("one leg per symbol -> nothing", groups(acct({"acc": ["a", "c"]}), strat), {})
    check("same leg twice is not a pair", groups(acct({"acc": ["a", "a"]}), strat), {})
    check("per-account keys", sorted(groups(acct({"p": ["a", "b"], "q": ["a", "b"]}), strat)), [("p", "X"), ("q", "X")])
    check("unknown leg ignored", groups(acct({"acc": ["a", "zzz"]}), strat), {})
    # sharing alone fails; coverage clears it
    check("uncovered pair refused", len(grade(g, [], today)), 1)
    rec = {"kind": "allocation_weights", "legs": ["a", "b"], "weights": {"a": 0.6, "b": 0.4},
           "inputs": ["src/runtime/allocator_ev.py EV_R", "head_to_head RQ-x"],
           "covers": [{"account": "acc", "symbol": "X"}]}
    check("weights record passes", grade(g, [rec], today), [])
    check("weights not summing to 1 refused", len(grade(g, [dict(rec, weights={"a": 0.6, "b": 0.6})], today)), 1)
    check("negative weight refused", len(grade(g, [dict(rec, weights={"a": 1.5, "b": -0.5})], today)), 1)
    check("weights missing a leg refused", len(grade(g, [dict(rec, weights={"a": 1.0})], today)), 1)
    check("wrong kind refused", len(grade(g, [dict(rec, kind="winner")], today)), 1)
    check("backtest-only basis (no allocator factor) refused", len(grade(g, [dict(rec, inputs=["head_to_head only"])], today)), 1)
    check("other account refused", len(grade(g, [dict(rec, covers=[{"account": "zz", "symbol": "X"}])], today)), 1)
    check("other symbol refused", len(grade(g, [dict(rec, covers=[{"account": "acc", "symbol": "Y"}])], today)), 1)
    g3 = groups(acct({"acc": ["a", "b", "d"]}), strat)
    check("third leg voids a 2-leg record", len(grade(g3, [rec], today)), 1)
    # slice support
    saved = SLICE_SUPPORT_ACCOUNTS
    SLICE_SUPPORT_ACCOUNTS = frozenset({"acc"})
    check("slice-supported account passes", grade(g, [], today), [])
    check("slice support is per account", len(grade({("other", "X"): ["a", "b"]}, [], today)), 1)
    SLICE_SUPPORT_ACCOUNTS = saved
    check("slice support lists only accounts declaring position_model: slices", SLICE_SUPPORT_ACCOUNTS, frozenset({"bybit_1"}))
    # grandfather (real table, real keys): graded as if the account had no slice support, since the table predates it
    SLICE_SUPPORT_ACCOUNTS = frozenset()
    gk = ("bybit_1", "XRPUSDT")
    legs = sorted(GRANDFATHERED["bybit_1/XRPUSDT"]["legs"])
    grp = {gk: legs}
    check("grandfathered before due", grade(grp, [], today), [])
    due = date.fromisoformat(GRANDFATHERED["bybit_1/XRPUSDT"]["due"])
    late = date.fromordinal(due.toordinal() + 1)
    r = grade(grp, [], late)
    check("grandfather lapses after due", len(r) == 1 and "LAPSED" in r[0], True)
    check("lapse notice", len(lapse_notices(grp, late)), 1)
    check("no lapse notice before due", lapse_notices(grp, today), [])
    check("exemption is by exact leg set (third leg)", len(grade({gk: legs + ["zz"]}, [], today)), 1)
    check("exemption is by exact key (other account)", len(grade({("bybit_9", "XRPUSDT"): legs}, [], today)), 1)
    check("every grandfather has a unit and a due", all(x.get("unit") and x.get("due") for x in GRANDFATHERED.values()), True)
    SLICE_SUPPORT_ACCOUNTS = saved
    # exclusive-hold legs (DESK-PAPER-ACCOUNTS): out of the group on a non-slice account, in it on a slice account,
    # per-account scope honoured, and the runtime refusal that justifies leaving them out is really called.
    sx = yaml.safe_dump({"strategies": {"a": {"symbols": ["X"]}, "claude_desk": {
        "symbols": ["X", "Y"], "account_symbols": {"acc": ["X"], "bybit_1": ["X"], "other": ["Y"]}}}})
    check("exclusive leg left out on a non-slice account", groups(acct({"acc": ["a", "claude_desk"]}), sx), {})
    check("exclusive leg counted on a slice account",
          groups(acct({"bybit_1": ["a", "claude_desk"]}), sx), {("bybit_1", "X"): ["a", "claude_desk"]})
    check("per-account scope: the leg's other symbols are not on this account",
          groups(acct({"other": ["a", "claude_desk"]}), sx), {})
    coord = (REPO / COORDINATOR_REL).read_text(encoding="utf-8")
    check("the coordinator calls the exclusive-hold refusal", "exclusive_hold_refusal(" in coord, True)
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
    except (OSError, ValueError, yaml.YAMLError, SyntaxError) as exc:
        print(f"same-symbol-allocation: COULD NOT MEASURE — {exc}", file=sys.stderr)
        return 2
    if args.list:
        for (a, s), legs in grp.items():
            print(f"{a}\t{s}\t{', '.join(legs)}")
        return 0
    for n in lapse_notices(grp, today):
        print(f"same-symbol-allocation: NOTICE — {n}")
    findings = grade(grp, load_records(REPO / RECORDS_REL), today)
    if not findings:
        print(f"same-symbol-allocation: clean ({len(grp)} same-symbol group(s) over "
              f"{ACCOUNTS_REL} x {STRATEGIES_REL}; each evidenced or grandfathered with a due date)")
        return 0
    print("🚨 SAME-SYMBOL ALLOCATION: two rostered legs share one net position with no recorded allocation "
          "(operator 2026-10-15: know how much of the position belongs to each strategy; do not let the name decide).", file=sys.stderr)
    print(f"   Needs: slice support for the account (SLICE_SUPPORT_ACCOUNTS, lane NETTED-SLICES) OR an allocation-weights record in "
          f"{RECORDS_REL}/ citing the existing allocator factors. Removing a leg from the roster needs nothing.\n", file=sys.stderr)
    for f in findings:
        print(f"  - {f}", file=sys.stderr)
        print(f"{MACHINE_PREFIX}\t{f.splitlines()[0]}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
