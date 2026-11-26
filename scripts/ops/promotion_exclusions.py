#!/usr/bin/env python3
# wiring: library - imported by scripts/research/live_bar.py and scripts/ops/scoreboard.py (no entry point of its own).
"""Trades the operator excluded from every promotion/demotion read (comms/promotion_exclusions.yaml).

Operator decision 2026-11-25 (W48 planning Q3), verbatim: "Exclude it from every promotion/demotion read, keep it visible and
labelled (Recommended)". ``split`` returns (kept, excluded); callers MUST report the excluded list beside their verdict, never
drop it silently. Gates this adds or changes: none (a population filter on reads).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO / "comms" / "promotion_exclusions.yaml"


def load(path: Path | None = None) -> List[Dict[str, Any]]:
    """The exclusion entries. A missing file is an empty list; an unparseable one raises (a broken filter must not read as 'none')."""
    p = path or DEFAULT_PATH
    if not p.exists():
        return []
    import yaml
    doc = yaml.safe_load(p.read_text()) or {}
    return [dict(e) for e in (doc.get("exclusions") or [])]


def _key(e: Mapping[str, Any]) -> Tuple[str, str]:
    return (str(e.get("trade_id")), str(e.get("account_id") or ""))


def is_excluded(trade: Mapping[str, Any], entries: Iterable[Mapping[str, Any]]) -> Dict[str, Any] | None:
    """The matching entry, or None. Matches on trade id, and on account when the entry names one and the row carries one."""
    tid = str(trade.get("id"))
    acct = str(trade.get("account_id") or "")
    for e in entries:
        k_id, k_acct = _key(e)
        if k_id == tid and (not k_acct or not acct or k_acct == acct):
            return dict(e)
    return None


def split(trades: Iterable[Mapping[str, Any]], entries: Iterable[Mapping[str, Any]] | None = None
          ) -> Tuple[List[Mapping[str, Any]], List[Dict[str, Any]]]:
    """(kept trades, labelled excluded list). ``entries`` defaults to the committed file."""
    ents = list(load() if entries is None else entries)
    kept: List[Mapping[str, Any]] = []
    out: List[Dict[str, Any]] = []
    for t in trades:
        hit = is_excluded(t, ents) if ents else None
        if hit is None:
            kept.append(t)
        else:
            out.append({"trade_id": t.get("id"), "account_id": t.get("account_id"), "strategy": t.get("strategy_name"),
                        "pnl": t.get("pnl"), "provenance": hit.get("provenance"), "reason": hit.get("reason"),
                        "decided": hit.get("decided")})
    return kept, out
