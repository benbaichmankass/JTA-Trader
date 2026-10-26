#!/usr/bin/env python3
# wiring: imported by scripts/ops/soak_state.py (untouched-only soak count), scripts/research/r3_cost_fidelity.py
#         (untouched-only cost cells) and scripts/ops/touch_split.py (the report). Pure; reads no store.
"""The bybit_1 sandbox touch record (DESK-12-SANDBOX, design § 3.6).

A (package, account) trade leg is **touched** from its first applied stop amend onward: its exit is
then no longer the leg's own, so it must not count toward the leg's "1-2 clean trades" mechanical soak
and must not feed the leg's live-vs-backtest or cost-fidelity verdict.

NOT A NEW STORE. ``trades.notes.sl_amends`` is the canonical record: every apply path
(``scripts/ops/live_review_apply.py``, ``src/units/accounts/alpaca_amend.py``,
``scripts/ops/amend_position_sl.py``) appends one entry only AFTER the venue read-back matched, and no
other code writes the list. This module is a pure projection over a trade row's ``notes``:

    {order_package_id, account, intent_id, decision_id, applied_at, level_before, level_after,
     verdict, source, review_id, mandate}

``intent_id`` / ``decision_id`` are read from the entry when the desk apply path (DESK-4) writes them;
they are ``None`` for an LTR apply, never invented. ``source`` classifies who touched it.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from src.runtime.live_review_intent import PROVENANCE as LTR_SOURCE
from src.utils.json_notes import load_notes

DESK_SOURCES = ("claude_desk", "desk_intent")
MANUAL_SOURCE = "manual_amend_operator"


def classify_source(source: Any) -> str:
    s = str(source or "")
    if s == LTR_SOURCE:
        return "ltr_apply"
    if s in DESK_SOURCES:
        return "desk"
    if s == MANUAL_SOURCE:
        return "manual"
    return "other"


def touches(trade: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every applied amend on one trade row, oldest first. ``[]`` = untouched."""
    try:
        notes = load_notes(trade.get("notes"))
    except Exception:  # noqa: BLE001 — an unparseable notes blob is read as no record, see touch_read_state
        return []
    out: List[Dict[str, Any]] = []
    for a in (notes.get("sl_amends") if isinstance(notes, dict) else None) or []:
        if not isinstance(a, dict):
            continue
        out.append({
            "order_package_id": trade.get("order_package_id"),
            "account": trade.get("account_id"),
            "trade_id": trade.get("id"),
            "intent_id": a.get("intent_id"),
            "decision_id": a.get("decision_id"),
            "applied_at": a.get("at"),
            "level_before": a.get("from"),
            "level_after": a.get("to"),
            "verdict": "applied" if a.get("venue_after") is not None else "applied_venue_unread",
            "source": classify_source(a.get("source")),
            "review_id": a.get("review_id"),
            "mandate": a.get("mandate"),
        })
    return out


def is_touched(trade: Mapping[str, Any]) -> bool:
    return bool(touches(trade))


def split(trades: Iterable[Mapping[str, Any]]) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    """``(untouched, touched)`` — a partition: the two lists sum to the input."""
    untouched: List[Mapping[str, Any]] = []
    touched: List[Mapping[str, Any]] = []
    for t in trades:
        (touched if is_touched(t) else untouched).append(t)
    return untouched, touched
