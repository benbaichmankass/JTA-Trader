"""An ML leg's traded symbols come from its POPULATION PASS RECORD, not from account config (row ML-ENTRY-ALL-ACCOUNTS; Tier 3).

Operator 2026-11-04 ~19:06Z, verbatim: "There's no per symbol configuration. There's only per strategy configuration. Specific
strategies trade one symbol usually, but the MLs trade whatever is whatever they're set to trade. They don't have their roster is
internal to the ML, and it's based on what tests have passed versus which ones have not." Popup ~19:33Z, verbatim: "Group-level
(Recommended)" (replacing the ~19:08Z / ~19:18Z per-symbol answers); context ~19:25Z, verbatim: "Maybe it shouldn't be gated at a per
symbol basis, but rather it should be kept more general ... I didn't mean to make the rules stricter than they had and the ML had been
designed for."

THE RECORD: ``comms/ml_universe/<leg>.json`` -- written by the pooled units (RQ-20261101-a24c-01 for the Bybit perps, RQ-20261104-a41f-01
for Alpaca), never by hand::

    {"schema": "ml_universe/1", "leg": "ml_entry",
     "populations": [{"unit": "RQ-...", "rule_id": "...", "verdict": "pass" | "fail" | "indeterminate", "result": "research/results/...",
                      "symbols": {"<SYMBOL>": {"venues": ["bybit", ...]}}}]}

``symbols`` is the tested population AFTER the unit's pre-registered cost / liquidity filter; ``venues`` is the venue listing the unit read
at run time.

THE RULE (one function, :func:`apply`), for one account whose venue is ``venue``:

* no record (file absent / unreadable / wrong leg): the configured set, UNCHANGED;
* every population whose verdict is ``pass`` ADDS its symbols that list the account's venue;
* a ``fail`` / ``indeterminate`` population adds nothing and removes nothing (group-level: a failed widening keeps the set it had).

The rule only ever ADDS ("not stricter than ... the ML had been designed for"). Today no record exists for any leg, so every account's
set is byte-identical to before this module.

ADD-ONLY BY DESIGN (Manager Session 2026-11-04a decision ~20:22Z, on canonical docs/CLAUDE-RULES-CANONICAL.md § "An account configures
strategies, never symbols", #22914): this resolver never shrinks a set, so a bad or partial record cannot take symbols off a real-money
account. Rule point 5 (a TESTING ML on the demo/paper floor trades its pending test's population) is met by a separate, explicit Tier-3
config PR with the per-symbol diff in its body, never by this resolver removing symbols -- e.g. ml_entry on alpaca_paper and
ml_entry_v2 on bybit_1.
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


def load(leg: Optional[str], base: Optional[Path] = None) -> Optional[List[Dict[str, Any]]]:
    """The leg's populations (each with a valid verdict), or ``None`` (no record / unreadable / malformed: never raises).
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
        if doc.get("schema") != SCHEMA or str(doc.get("leg")) != str(leg) or not isinstance(doc.get("populations"), list):
            raise ValueError("schema/leg mismatch")
        pops = [dict(x) for x in doc["populations"]
                if isinstance(x, dict) and x.get("verdict") in VERDICTS and isinstance(x.get("symbols"), dict)]
    except Exception as exc:  # noqa: BLE001 -- a bad record must never change what trades: fall back to config
        logger.warning("ml_universe: record %s unreadable (%s); configured set kept", p, exc)
        pops = None
    _CACHE[str(p)] = (mt, pops)
    return pops


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


def passed_symbols(record: Optional[List[Dict[str, Any]]], venue: Optional[str] = None) -> List[str]:
    """Symbols of every PASSED population, in record order; with ``venue``, only those that list it."""
    out: List[str] = []
    for pop in record or []:
        if pop.get("verdict") != "pass":
            continue
        for s, e in pop["symbols"].items():
            venues = [str(v).lower() for v in ((e or {}).get("venues") or [])] if isinstance(e, dict) else []
            if (venue is None or venue in venues) and s not in out:
                out.append(str(s))
    return out


def apply(configured: List[str], record: Optional[List[Dict[str, Any]]], venue: Optional[str]) -> List[str]:
    """The traded set for one account: ``configured`` plus every passed population's symbols on ``venue``. Never removes;
    ``record=None`` returns ``configured`` unchanged (same list order)."""
    out = list(configured)
    if record is None or not venue:
        return out
    for s in passed_symbols(record, venue):
        if s not in out:
            out.append(s)
    return out


def write_population(leg: str, population: Dict[str, Any], base: Optional[Path] = None,
                     seed_from: Optional[Path] = None) -> Path:
    """Upsert one pooled unit's population into ``<base>/<leg>.json`` (the only writer; units call it, nobody edits by hand).

    A population with the same ``unit`` replaces the earlier one; others are kept. ``seed_from`` (a directory) supplies the existing
    populations when ``base`` has no file yet, so a research runner writing to its output dir carries the committed record forward.
    Validates before writing (a bad population raises, nothing is written). Atomic (tmp + replace)."""
    for k in ("unit", "rule_id", "verdict", "result", "symbols"):
        if k not in population:
            raise ValueError(f"population missing {k!r}")
    if population["verdict"] not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {population['verdict']!r}")
    if not isinstance(population["symbols"], dict) or any(
            not isinstance(e, dict) or not isinstance(e.get("venues"), list) or not e["venues"]
            for e in population["symbols"].values()):
        raise ValueError("symbols must map SYMBOL -> {'venues': [non-empty list]}")
    dest = record_path(leg, base)
    existing: List[Dict[str, Any]] = []
    # base=None writes to RECORD_DIR, so the existing populations are read from RECORD_DIR too: before 2026-11-12 the
    # default call skipped the read and a second unit's write erased the first unit's populations (lane ML-ENTRY-POPULATION-TEST).
    for src in (base or RECORD_DIR, seed_from):
        if src is None:
            continue
        if record_path(leg, src).exists():
            doc = json.loads(record_path(leg, src).read_text(encoding="utf-8"))
            if doc.get("schema") != SCHEMA or str(doc.get("leg")) != str(leg):
                raise ValueError(f"existing record {record_path(leg, src)} has a different schema/leg")
            existing = [dict(x) for x in doc.get("populations", [])]
            break
    pops = [x for x in existing if x.get("unit") != population["unit"]] + [dict(population)]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, "leg": str(leg), "populations": pops}, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, dest)
    _CACHE.pop(str(dest), None)
    return dest
