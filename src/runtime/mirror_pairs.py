"""Stage-2 mirror pairs: a mirror places a package ONLY when its primary did.

CLAUDE.md § "The promotion ladder": Stage 2 is one stage — the real-money
account and its paper mirror carry the IDENTICAL roster and take the IDENTICAL
trades. Roster equality is enforced in ``tests/test_paper_portfolio_accounts.py``;
trade equality was not enforced anywhere at dispatch time.

**The incident (MIRROR-QTY-DIVERGE, 2026-10-09T06:02Z).** ``xrp_pullback_2h``
short, package ``pkg-63b56da53bfe4d64``. Both accounts already held the
``trend_donchian_xrp_4h`` short, so intent mode dispatched a top-up DELTA to
each: bybit_2 57.4 − 56.9 = **0.5 XRP** (~$0.70), bybit_portfolio
17428.1 − 17267.2 = **160.9 XRP** — the same 303.6× ratio as every other leg.
The venue refused bybit_2's 0.5 (ErrCode 110094, min order value 5 USDT); the
mirror's 160.9 filled. When the donchian stop fired the mirror was left holding
a short the real-money account never had. Measured over 2026-07-16 → 2026-10-12
(the mirror's whole life): 9 packages filled on bybit_portfolio while bybit_2
did not place (8 × ErrCode 110007 on BTCUSDT, 1 × 110094 on XRPUSDT).

**The rule here.** A mirror follows its primary's OUTCOME for the same package
in the same dispatch call: primary placed → mirror dispatches normally; primary
did not place (any reason — venue reject, sub-min delta, risk refusal, netting
guard) → mirror skips with a named reason. The reverse (primary placed, mirror
failed) cannot be undone from here; it is reported as an ERROR-level alert so
the divergence is never silent.

``MIRROR_PAIRS`` is derived from ``strategy_monocle.STAGE2_PAIRS``; that every
``paper_role: portfolio`` account appears in it is pinned by
``tests/test_mirror_pairs.py``.

Complements, does not replace: the monocle gate (PAIR-COUPLED, one open
package per pair) decides whether the pair may open at all;
``scripts/ops/check_mirror_orphans.py`` flags an orphan within a day. Neither
sees the per-account VENUE outcome of a dispatch, which is where this
divergence was born.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from src.runtime.strategy_monocle import STAGE2_PAIRS

#: mirror account -> its real-money primary. DERIVED from the one src-side
#: pairing constant (``strategy_monocle.STAGE2_PAIRS``, itself tied to
#: ``mandate_resolver.MIRROR_OF`` and the mirror-equality tests by
#: ``tests/test_monocle_gate_per_account.py``) — not a second list.
MIRROR_PAIRS: Dict[str, str] = {mirror: live for live, mirror in STAGE2_PAIRS}

#: Follow verdicts. Never collapsed: each is a different log/alert path.
FOLLOW = "follow"                  # primary placed -> dispatch the mirror
SKIP = "skip"                      # primary did not place -> mirror skips
UNOBSERVED = "unobserved"          # primary absent from this call -> dispatch + WARN
NOT_A_MIRROR = "not_a_mirror"


def primary_of(account_name: str) -> Optional[str]:
    return MIRROR_PAIRS.get(str(account_name))


def order_primaries_first(accounts: Iterable[Any], name_of: Callable[[Any], str]) -> List[Any]:
    """Stable reorder so every mirror dispatches AFTER its primary.

    Config order is otherwise preserved. Needed because ``alpaca_portfolio`` is
    declared above ``alpaca_live`` in ``config/accounts.yaml``.
    """
    accts = list(accounts)
    names = [str(name_of(a)) for a in accts]
    mirrors = [a for a, n in zip(accts, names) if MIRROR_PAIRS.get(n) in names]
    out = [a for a in accts if not any(a is m for m in mirrors)]
    for m in mirrors:
        p = MIRROR_PAIRS[str(name_of(m))]
        idx = next(i for i, a in enumerate(out) if str(name_of(a)) == p)
        # insert after the primary and after any mirror already placed there
        j = idx + 1
        while j < len(out) and MIRROR_PAIRS.get(str(name_of(out[j]))) == p:
            j += 1
        out.insert(j, m)
    return out


def follow_decision(
    mirror: str,
    results: Iterable[Mapping[str, Any]],
    excluded_by_account: Mapping[str, str],
) -> Tuple[str, Optional[str]]:
    """``(verdict, reason)`` for dispatching *mirror* given this call's state.

    ``results`` are the per-account result rows already produced in this call;
    a row with a truthy ``trade_id`` means the primary placed.
    """
    primary = MIRROR_PAIRS.get(str(mirror))
    if primary is None:
        return NOT_A_MIRROR, None
    row = None
    for r in results:
        if r.get("name") == primary:
            row = r
    if row is not None:
        if row.get("trade_id"):
            return FOLLOW, None
        return SKIP, f"mirror_primary_not_placed:{primary}:{row.get('error')}"
    if primary in excluded_by_account:
        return SKIP, (
            f"mirror_primary_not_dispatched:{primary}:"
            f"{excluded_by_account[primary]}"
        )
    return UNOBSERVED, f"mirror_primary_unobserved:{primary}"


def divergences(results: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Pairs in one call where the PRIMARY placed and the MIRROR did not.

    The direction ``follow_decision`` cannot prevent — the live order is
    already on the venue. Each returned row must be alerted.
    """
    rows = list(results)
    placed = {r.get("name"): r for r in rows}
    out: List[Dict[str, Any]] = []
    for mirror, primary in MIRROR_PAIRS.items():
        p, m = placed.get(primary), placed.get(mirror)
        if p is None or m is None:
            continue
        if p.get("trade_id") and not m.get("trade_id"):
            out.append({
                "primary": primary, "mirror": mirror,
                "primary_trade_id": p.get("trade_id"),
                "mirror_error": m.get("error"),
            })
    return out
