"""An ML leg's traded symbols come from its PER-SYMBOL PASS RECORD, not from account config (row ML-ENTRY-ALL-ACCOUNTS; Tier 3).

Operator 2026-11-04 ~19:06Z, verbatim: "There's no per symbol configuration. There's only per strategy configuration. Specific
strategies trade one symbol usually, but the MLs trade whatever is whatever they're set to trade. They don't have their roster is
internal to the ML, and it's based on what tests have passed versus which ones have not." Popup answers ~19:08Z: "Per-symbol passes
(Recommended)", "Per-symbol tests (Recommended)"; ~19:18Z the bar: "Shrunk >= 0, n >= 100 (Recommended)".

THE RECORD: ``comms/ml_universe/<leg>.json`` -- written by the per-symbol units (RQ-20261101-a24c-01 for the Bybit perps,
RQ-20261104-a41f-01 for Alpaca), never by hand::

    {"schema": "ml_universe/1", "leg": "ml_entry", "rule_id": "...", "generated_at": "...",
     "symbols": {"<SYMBOL>": {"verdict": "pass" | "fail" | "indeterminate", "n": int, "shrunk_mean_net_r": float,
                              "venues": ["bybit", ...], "unit": "RQ-...", "result": "research/results/..."}}}

THE RULE (one function, :func:`apply`), for one account whose venue is ``venue``:

* no record (file absent / unreadable / wrong leg): the configured set, UNCHANGED -- no widening by default;
* ``fail``: removed (a fail removes it, re-evaluated monthly by the unit);
* ``pass`` and the record lists the account's venue: added (the record's ``venues`` is the unit's run-time venue listing);
* ``indeterminate`` (n < 100) or ``pass`` on a venue it does not list: unchanged -- in if configured, out if not.

Today no record exists for any leg, so every account's set is byte-identical to before this module.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
RECORD_DIR = REPO / "comms" / "ml_universe"
SCHEMA = "ml_universe/1"
VERDICTS = ("pass", "fail", "indeterminate")
_CACHE: Dict[str, Any] = {}


def record_path(leg: str, base: Optional[Path] = None) -> Path:
    return (base or RECORD_DIR) / f"{leg}.json"


def load(leg: Optional[str], base: Optional[Path] = None) -> Optional[Dict[str, Dict[str, Any]]]:
    """``{symbol: entry}`` from the leg's record, or ``None`` (no record / unreadable / malformed: never raises).
    Cached on (path, mtime)."""
    if not leg:
        return None
    p = record_path(str(leg), base)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    hit = _CACHE.get(str(p))
    if hit and hit[0] == mt:
        return hit[1]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if doc.get("schema") != SCHEMA or str(doc.get("leg")) != str(leg) or not isinstance(doc.get("symbols"), dict):
            raise ValueError("schema/leg mismatch")
        syms = {str(s): dict(e) for s, e in doc["symbols"].items()
                if isinstance(e, dict) and e.get("verdict") in VERDICTS}
    except Exception as exc:  # noqa: BLE001 -- a bad record must never change what trades: fall back to config
        logger.warning("ml_universe: record %s unreadable (%s); configured set kept", p, exc)
        syms = None
    _CACHE[str(p)] = (mt, syms)
    return syms


def account_venue(account_id: Optional[str]) -> Optional[str]:
    if not account_id:
        return None
    try:
        from src.config.accounts_loader import load_accounts_dict
        acct = (load_accounts_dict() or {}).get(str(account_id)) or {}
        v = acct.get("exchange")
        return str(v).lower() if v else None
    except Exception:  # noqa: BLE001
        return None


def apply(configured: List[str], record: Optional[Dict[str, Dict[str, Any]]], venue: Optional[str]) -> List[str]:
    """The traded set for one account. ``record=None`` returns ``configured`` unchanged (same list order)."""
    if record is None:
        return list(configured)
    out = [s for s in configured if (record.get(s) or {}).get("verdict") != "fail"]
    if venue:
        for s, e in record.items():
            if e.get("verdict") == "pass" and venue in [str(v).lower() for v in (e.get("venues") or [])] \
                    and s not in out:
                out.append(s)
    return out


def passed_symbols(record: Optional[Dict[str, Dict[str, Any]]]) -> List[str]:
    return [s for s, e in (record or {}).items() if e.get("verdict") == "pass"]
