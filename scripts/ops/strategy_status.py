#!/usr/bin/env python3
"""The three strategy statuses, DERIVED from config — never declared (operator, 2026-10-28).

Operator, verbatim (relayed by the manager, decision "Adopt; build it this week"):
  "strategies have 3 statuses - in testing (live on general paper), in production (live on real
   money and paper portfolio), and inactive (if several rounds of research had proven it's not
   worth pursuing)."

    testing     on a GENERAL PAPER roster (bybit_1 / alpaca_paper / ib_paper) = ladder Stage 1.
    production  on a REAL-MONEY roster (bybit_2 / alpaca_live / ib_live) and its paper-portfolio
                mirror, and on NO general paper roster = ladder Stage 2.
    inactive    retired by record: ``enabled: false`` in config/strategies.yaml (the existing
                retirement-record marker, ``mandate_resolver._retired_by_record``); on no roster.

WHY DERIVED. A ``status:`` field would be a third execution gate (CLAUDE.md § "The two execution
gates": there is no third gate) and a second copy of a fact the rosters already hold, free to drift
from them. The status is read off roster membership + the retirement marker, so it cannot disagree
with what trades. The invariant that keeps the books clean is enforced by
``scripts/ci/check_strategy_status.py`` (strategy-status-guard).

Prop rosters (``account_class: prop``) and ``alpaca_options_paper`` are NOT a status: a leg's
status is decided by the general-paper / real-money books alone. Where prop legs belong is an open
operator question (OPERATING-PLAN § 2 "Three strategy statuses").

Usage: python3 scripts/ops/strategy_status.py   # prints every leg's status and its books
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

REPO = Path(__file__).resolve().parents[2]
ACCOUNTS_REL = "config/accounts.yaml"
STRATEGIES_REL = "config/strategies.yaml"

#: Stage 1 — the general paper accounts (``mandate_resolver.DEMO_FLOOR_ACCOUNTS``; asserted equal in tests).
GENERAL_PAPER = ("bybit_1", "alpaca_paper", "ib_paper")
#: Stage 2 — real money -> its paper-portfolio mirror (``mandate_resolver.MIRROR_OF``). ib_live has none.
REAL_MONEY_MIRROR: Dict[str, Optional[str]] = {
    "bybit_2": "bybit_portfolio", "alpaca_live": "alpaca_portfolio", "ib_live": None,
}
#: The one sanctioned mirror divergence (tests/test_paper_portfolio_accounts.py::_ALPACA_PROXY_STRATEGIES).
MIRROR_CARVE_OUT = {"alpaca_portfolio": frozenset({"splg_trend_long_1d", "iaum_pullback_1d"})}

TESTING, PRODUCTION, INACTIVE = "testing", "production", "inactive"


def _yaml(root: Path, rel: str) -> Dict[str, Any]:
    p = root / rel
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.is_file() else {}


def rosters(accounts: Dict[str, Any]) -> Dict[str, list]:
    return {a: list((cfg or {}).get("strategies") or []) for a, cfg in accounts.items()
            if isinstance(cfg, dict)}


def retired(strategies: Dict[str, Any], leg: str) -> bool:
    cfg = strategies.get(leg)
    return isinstance(cfg, dict) and cfg.get("enabled") is False


def status_of(leg: str, ros: Dict[str, list], strategies: Dict[str, Any]) -> str:
    if retired(strategies, leg):
        return INACTIVE
    if any(leg in ros.get(a, []) for a in REAL_MONEY_MIRROR):
        return PRODUCTION
    return TESTING


def load(root: Path = REPO) -> tuple:
    accounts = _yaml(root, ACCOUNTS_REL).get("accounts") or {}
    strategies = _yaml(root, STRATEGIES_REL).get("strategies") or {}
    return accounts, strategies


def table(root: Path = REPO) -> Dict[str, Dict[str, Any]]:
    accounts, strategies = load(root)
    ros = rosters(accounts)
    return {leg: {"status": status_of(leg, ros, strategies),
                  "books": sorted(a for a, legs in ros.items() if leg in legs)}
            for leg in sorted(strategies) if isinstance(strategies.get(leg), dict)}


def main() -> int:
    t = table()
    if not t:
        print("strategy_status: COULD NOT MEASURE — config/strategies.yaml empty or unreadable", file=sys.stderr)
        return 2
    counts: Dict[str, int] = {}
    for leg, row in t.items():
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        print(f"{row['status']:<10} {leg:<28} {', '.join(row['books']) or '—'}")
    print(f"population: {len(t)} legs in {STRATEGIES_REL} — " +
          ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
