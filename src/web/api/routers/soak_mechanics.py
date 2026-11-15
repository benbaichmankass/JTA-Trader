"""GET /api/bot/soak/mechanics: per-leg ``mechanics_proven`` for the console Ladder tab (row UI-CONSOLE-ARTIFACT C2).

Tier 1, read-only. Soak state is computed LIVE on this VM by ``scripts/ops/soak_state.soak_states()`` from the
contracts (docs/claude/work/SOAKS.json) plus the trade journal, and is never written to the repo. The console
connector runs on the trainer, which has no journal, so this route evaluates ``soak_state.mechanics_proven()``
HERE, where its inputs exist, and the connector reads the result. Nothing is re-implemented: the decision is the
same function MD-PROMOTE-S1-S2 reads (OPERATING-PLAN § 2, operator 2026-11-01 PROMOTION-NO-SOAK).

Collapsed states: when the journal cannot be read every soak row reads ``unknown``, and then a "not proven" would be
a fabricated negative. So the response says ``read_state: could_not_look`` with ``legs: null``, never ``false``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/soak", tags=["soak"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_mechanics(ss: Any = None, status: Any = None) -> dict[str, Any]:
    """``ss`` = scripts.ops.soak_state, ``status`` = scripts.ops.strategy_status (injectable for tests)."""
    if ss is None:
        from scripts.ops import soak_state as ss  # noqa: PLC0415 - heavy, only on request
    if status is None:
        from scripts.ops import strategy_status as status  # noqa: PLC0415
    base: dict[str, Any] = {
        "as_of": _now(),
        "provenance": {"measure": "MEASURED",
                       "source": ["docs/claude/work/SOAKS.json", "trade journal (soak_state.soak_states)",
                                  "config/mechanics_paths.yaml"],
                       "decision": "scripts/ops/soak_state.py::mechanics_proven"},
    }
    try:
        states = ss.soak_states()
    except Exception as exc:  # noqa: BLE001  # allow-silent: reported as could_not_look with the reason, never as unproven
        logger.warning("soak/mechanics: soak_states failed", exc_info=True)
        return {**base, "read_state": "could_not_look", "reason": f"soak_states failed: {type(exc).__name__}: {exc}",
                "legs": None, "population": {"soaks": None, "legs": None}}
    rows = [r for r in states if isinstance(r, dict)]
    by_state: dict[str, int] = {}
    for r in rows:
        by_state[str(r.get("state"))] = by_state.get(str(r.get("state")), 0) + 1
    if rows and all(r.get("state") == "unknown" for r in rows):
        reason = next((r.get("reason") for r in rows if r.get("reason")), "every soak reads unknown")
        return {**base, "read_state": "could_not_look", "reason": f"journal not readable: {reason}", "legs": None,
                "population": {"soaks": len(rows), "by_state": by_state, "legs": None}}
    try:
        registry = ss.load_mechanics_paths()
        accounts, _strategies = status.load()
        exch = {str(k): str(v.get("exchange")) for k, v in (accounts or {}).items() if isinstance(v, dict) and v.get("exchange")}
        legs_all = sorted(set(status.table())
                          | set(registry) | {str(r.get("leg")) for r in rows if r.get("leg")})
    except Exception as exc:  # noqa: BLE001  # allow-silent: reported as could_not_look with the reason
        logger.warning("soak/mechanics: roster/registry read failed", exc_info=True)
        return {**base, "read_state": "could_not_look", "reason": f"roster/registry read failed: {type(exc).__name__}: {exc}",
                "legs": None, "population": {"soaks": len(rows), "by_state": by_state, "legs": None}}
    legs: dict[str, Any] = {}
    for leg in legs_all:
        m = ss.mechanics_proven(leg, rows, legs=registry, exchange_of_account=exch)
        e = registry.get(leg) or {}
        proven: bool | None = bool(m.get("proven"))
        reason = m.get("reason")
        own_unknown = next((r for r in rows if r.get("leg") == leg and r.get("state") == "unknown"), None)
        if not proven and own_unknown is not None:
            # Its own soak could not be graded (journal unreadable for it): "not proven" would be a fabricated
            # negative, so it is null with the reason (collapsed-states rule).
            proven, reason = None, f"own soak {own_unknown.get('id')} reads unknown: {own_unknown.get('reason') or 'no reason given'}"
        legs[leg] = {"proven": proven, "basis": m.get("basis"), "path": m.get("path") or e.get("path"),
                     "delta": e.get("delta"), "reason": reason}
    return {**base, "read_state": "read", "legs": legs,
            "population": {"soaks": len(rows), "by_state": by_state, "legs": len(legs),
                           "proven": sum(1 for v in legs.values() if v["proven"] is True),
                           "not_proven": sum(1 for v in legs.values() if v["proven"] is False),
                           "unknown": sum(1 for v in legs.values() if v["proven"] is None),
                           "registered_paths": len(registry)}}


@router.get("/mechanics")
def get_soak_mechanics() -> dict[str, Any]:
    """Sync handler (FastAPI threadpool): soak_states opens the journal read-only."""
    return build_mechanics()
