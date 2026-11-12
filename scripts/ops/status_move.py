"""What happens to OPEN positions when a leg changes book: the status-move read (row STATUS-MOVE-OPEN-POSITIONS).

The rule is stated ONCE in docs/plans/OPERATING-PLAN-2026-09-21.md § 2 "Open positions on a book move". This module
is its runtime read. It classifies every open position against the CURRENT rosters, so a status change that moved
the roster but left a position behind shows up as a named row instead of an anonymous extra copy of a trade.

Operator, 2026-10-29 (ADA trade 6734 left on bybit_1 after #21038 promoted ada_pullback_2h): *"There shouldn't be
three versions of this trade. There should be at most two."* Operator, 2026-11-12 (planning page p3): *"We already
said that things get promoted to real money based on backtesting, shadow on paper is only for something that is
demoted and in iteration, not a step on the way to real money"*.

Verdicts, one per open position:

    on_book          the leg is on this account's roster now. Nothing to do.
    not_judged       a prop / options / other account the status model does not judge (strategy_status.py docstring).
    close_duplicate  a PROMOTED leg's position still on general paper while the same trade is open on its real-money
                     book or mirror: the third version. The paper copy is closed (the money and mirror copies are the
                     record). Closing it loses no data: the mirror carries the same trade.
    close_netted     close_duplicate, but another open position shares this account + symbol. A whole-symbol flatten
                     (the flatten-* system-actions) would also close that neighbour, so this needs a per-row close.
    run_out          off its roster, and the SOLE remaining copy on that side of the books: a promoted leg's paper
                     position with no money/mirror sibling, a DEMOTED leg's money + mirror positions (keep open, block
                     new: they keep their SL/TP and the exit monitor, E21), or a retired leg's position. It runs to its
                     own exit. A status change is not a market signal, so it does not choose an exit time.
    unexplained      off its roster with no status change that explains it (e.g. moved between two paper books). Report.

Versions: a "trade" is (leg, symbol, side) across the books the status model judges. More than two open copies of one
trade is a breach of the operator's rule, whatever the verdicts say.

Sibling matching. With ``order_package_id`` on the row (the journal ``trades`` table) the match is exact: MEASURED.
``/api/bot/positions`` does not carry the package id, so the CLI falls back to leg + symbol + side, labelled ESTIMATED.
A fallback match can pair two separate trades of one leg; it never invents a sibling across legs or symbols.

Pure functions, stdlib only (plus strategy_status for the book definitions). No broker, no DB, no order path.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

ON_BOOK = "on_book"
NOT_JUDGED = "not_judged"
CLOSE_DUPLICATE = "close_duplicate"
CLOSE_NETTED = "close_netted"
RUN_OUT = "run_out"
UNEXPLAINED = "unexplained"
VERDICTS = (ON_BOOK, NOT_JUDGED, CLOSE_DUPLICATE, CLOSE_NETTED, RUN_OUT, UNEXPLAINED)

GENERAL_PAPER = ("bybit_1", "alpaca_paper", "ib_paper")
REAL_MONEY_MIRROR: dict[str, str | None] = {
    "bybit_2": "bybit_portfolio", "alpaca_live": "alpaca_portfolio", "ib_live": None,
}
MIRRORS = tuple(m for m in REAL_MONEY_MIRROR.values() if m)
JUDGED = GENERAL_PAPER + tuple(REAL_MONEY_MIRROR) + MIRRORS

MEASURED, ESTIMATED = "MEASURED", "ESTIMATED"


def _norm(p: dict[str, Any]) -> dict[str, Any]:
    """Accept a journal ``trades`` row or an ``/api/bot/positions`` row."""
    return {
        "id": str(p.get("id")),
        "account": p.get("account") or p.get("account_id"),
        "leg": p.get("strategy") or p.get("pattern") or p.get("strategy_name"),
        "symbol": p.get("symbol"),
        "side": str(p.get("side") or p.get("direction") or "").lower().replace("long", "buy").replace("short", "sell"),
        "package": p.get("order_package_id"),
    }


def _books(leg: str, rosters: dict[str, list[str]]) -> list[str]:
    return [a for a in JUDGED if leg in rosters.get(a, [])]


def classify(positions: Iterable[dict[str, Any]], rosters: dict[str, list[str]],
             retired: Iterable[str] = ()) -> dict[str, Any]:
    """Classify open positions. ``rosters`` is account -> legs (config/accounts.yaml); ``retired`` the retired legs."""
    rows = [_norm(p) for p in positions]
    retired = set(retired)
    by_trade: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    by_acct_sym: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["account"] in JUDGED:
            by_trade[(r["leg"], r["symbol"], r["side"])].append(r)
        by_acct_sym[(r["account"], r["symbol"])].append(r)

    out: list[dict[str, Any]] = []
    for r in rows:
        acct, leg = r["account"], r["leg"]
        v: dict[str, Any] = dict(r)
        if acct not in JUDGED:
            v.update(verdict=NOT_JUDGED, why="account outside the status model (prop / options / other)")
        elif leg in rosters.get(acct, []):
            v.update(verdict=ON_BOOK, why="leg on this account's roster")
        elif leg in retired:
            v.update(verdict=RUN_OUT, why="leg retired by record; position runs to its own exit (E21)")
        else:
            books = _books(leg, rosters)
            production = any(b in REAL_MONEY_MIRROR for b in books)
            if acct in GENERAL_PAPER and production:
                money_side = set(books) - set(GENERAL_PAPER)
                sibs = [s for s in by_trade[(leg, r["symbol"], r["side"])]
                        if s["account"] in money_side and s["id"] != r["id"]]
                if r["package"]:
                    sibs = [s for s in sibs if s["package"] == r["package"]]
                    prov = MEASURED
                else:
                    prov = ESTIMATED
                if sibs:
                    neighbours = [n["id"] for n in by_acct_sym[(acct, r["symbol"])] if n["id"] != r["id"]]
                    v.update(verdict=CLOSE_NETTED if neighbours else CLOSE_DUPLICATE,
                             why=f"promoted leg; same trade open on {sorted({s['account'] for s in sibs})}",
                             siblings=sorted(s["id"] for s in sibs), match=prov, neighbours=neighbours)
                else:
                    v.update(verdict=RUN_OUT, match=prov,
                             why="promoted leg; no money/mirror sibling, so this is the sole copy and runs out")
            elif acct not in GENERAL_PAPER and not production and books:
                v.update(verdict=RUN_OUT,
                         why="demoted leg; money/mirror position keeps SL/TP and runs out (keep open, block new)")
            else:
                v.update(verdict=UNEXPLAINED, why=f"off roster; leg's books now {books or '—'}")
        out.append(v)

    versions: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["account"] in JUDGED:  # exact by package when the row carries one, else leg + symbol + side
            versions[("pkg", r["package"]) if r["package"] else (r["leg"], r["symbol"], r["side"])].append(r)
    breaches = [{"trade": list(k), "copies": sorted(x["account"] for x in g), "ids": sorted(x["id"] for x in g),
                 "match": MEASURED if k[0] == "pkg" else ESTIMATED}
                for k, g in versions.items() if len(g) > 2]
    counts = {k: sum(1 for o in out if o["verdict"] == k) for k in VERDICTS}
    return {"population": len(out), "counts": counts, "positions": out, "version_breaches": breaches}
