"""Read-side normalisation of the Claude strategy-scores jsonl under ``comms/`` rows.

CJ-0 F4/F6 (docs/plans/ml-claude-distillation-DESIGN.md § 5). The score file is
append-only, so legacy quirks are fixed HERE, at read time, never in the file:

* ``author_kind`` is derived for rows written before the writers emitted it;
* out-of-vocabulary ``entry_quality`` values are mapped and flagged;
* a key graded more than once keeps the latest ``reviewed_at``.

Pure functions, no I/O: the ``claude_judgments`` family builder (CJ-2) is the
consumer.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# ``system-review`` rows used a vocabulary outside the rubric's.
ENTRY_QUALITY_VOCAB_MAP = {"good": "acceptable", "poor": "late"}


def derive_author_kind(row: dict) -> str:
    """``llm`` / ``rubric_script`` / ``human`` for a row, old or new.

    A row that states ``author_kind`` keeps it. Otherwise the rubric script's
    templated rationale (``...; entry=...; risk=...``) marks ``rubric_script``;
    anything else is free text from a review session, i.e. ``llm``.
    """
    stated = row.get("author_kind")
    if stated in ("llm", "rubric_script", "human"):
        return stated
    rationale = str(row.get("rationale") or "")
    if "entry=" in rationale and "risk=" in rationale:
        return "rubric_script"
    return "llm"


def normalise_row(row: dict) -> dict:
    """Copy of *row* with ``author_kind`` set and vocabulary mapped.

    ``vocab_mapped`` is True only when a value was changed.
    """
    out = dict(row)
    out["author_kind"] = derive_author_kind(row)
    eq = row.get("entry_quality")
    mapped = ENTRY_QUALITY_VOCAB_MAP.get(eq)
    out["vocab_mapped"] = mapped is not None
    if mapped is not None:
        out["entry_quality"] = mapped
    return out


def _dedupe_key(row: dict) -> tuple[Any, Any]:
    if row.get("keyed_on") == "linked_trade_id":
        return ("linked_trade_id", row.get("linked_trade_id"))
    return ("order_package_id", row.get("order_package_id"))


def dedupe_latest(rows: Iterable[dict]) -> list[dict]:
    """Latest ``reviewed_at`` per (key kind, key); rows without a key drop.

    Ties keep the later row in file order.
    """
    best: dict[tuple, dict] = {}
    for r in rows:
        k = _dedupe_key(r)
        if k[1] is None:
            continue
        cur = best.get(k)
        if cur is None or str(r.get("reviewed_at") or "") >= str(cur.get("reviewed_at") or ""):
            best[k] = r
    return list(best.values())
