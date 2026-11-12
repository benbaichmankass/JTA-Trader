"""Gate registry routes (lane GATE-REGISTRY, operator 2026-11-12).

    GET  /api/bot/gates                  filters: category, decision, state, real_money, decided_since
    GET  /api/bot/gates/{gate_id}        one row + its decision history
    POST /api/bot/gates/{gate_id}/decision   body {decision: keep|remove|report_only|undecided, note}

Gates this adds or changes: **none.** The GETs read ``gate_registry`` (``src/runtime/gate_registry.py``); the POST
records the operator's decision, which is an instruction to Claude and changes no code by itself. The POST sits
behind the operator's SPA session (``require_session``), exactly like ``POST /api/bot/trade-approvals/{token}``.
The GETs sit behind the site gate with no special-casing. Additive only (CORS unchanged: GET/POST).

Refresh: a read re-runs :func:`gate_registry.refresh_if_stale` (HEAD moved — i.e. a deploy / git-sync — or the last
refresh is older than an hour); once any gates route has been hit since boot, a daemon loop also refreshes every
30 min so drift alerts go out without a reader.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from src.runtime import gate_registry
from src.web.api.auth import require_session

logger = logging.getLogger(__name__)

router = APIRouter()

GATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
BG_INTERVAL_S = 30 * 60

_bg_lock = threading.Lock()
_bg_started = False


def _bg_loop() -> None:
    while True:
        time.sleep(BG_INTERVAL_S)
        try:
            gate_registry.refresh_if_stale()
        except Exception as exc:  # noqa: BLE001  # allow-silent: logged at ERROR; the loop must survive and the next pass retries
            logger.error("gate_registry background refresh failed: %s", exc)


def _ensure_bg() -> None:
    global _bg_started
    with _bg_lock:
        if not _bg_started:
            threading.Thread(target=_bg_loop, name="gate-registry-refresh", daemon=True).start()
            _bg_started = True


def _as_of() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _refresh_and(fn):
    """Refresh if stale, then run ``fn(conn)``. Returns ``(result, refresh_error)``."""
    refresh_error = None
    try:
        gate_registry.refresh_if_stale()
    except Exception as exc:  # noqa: BLE001  # allow-silent: logged at ERROR and returned as refresh.read_state=failed + error
        refresh_error = f"refresh failed: {exc}"
        logger.error("gate_registry: %s", refresh_error)
    conn = gate_registry.connect()
    try:
        return fn(conn), gate_registry.last_refresh(conn), refresh_error
    finally:
        conn.close()


@router.get("/api/bot/gates")
async def list_gates(category: str | None = None, decision: str | None = None,
                     state: str | None = None, real_money: str | None = None,
                     decided_since: str | None = None) -> Any:
    _ensure_bg()
    if decision and decision not in gate_registry.DECISIONS:
        raise HTTPException(status_code=400, detail=f"decision must be one of {list(gate_registry.DECISIONS)}")
    if state and state not in gate_registry.STATE_FILTERS:
        raise HTTPException(status_code=400, detail=f"state must be one of {list(gate_registry.STATE_FILTERS)}")
    if real_money not in (None, "", "true", "false"):
        raise HTTPException(status_code=400, detail="real_money must be true or false")
    try:
        result, refresh, refresh_error = await run_in_threadpool(
            _refresh_and, lambda c: gate_registry.list_gates(
                c, category=category, decision=decision, state=state, real_money=real_money,
                decided_since=decided_since))
    except Exception as exc:  # noqa: BLE001  # allow-silent: logged at ERROR; 503 readState=unreadable, gates=null (never an empty list)
        logger.error("gate_registry read failed: %s", exc)
        return JSONResponse(status_code=503, content={
            "readState": "unreadable", "as_of": _as_of(), "error": str(exc)[:300],
            "population": {"total": None, "returned": None,
                           "description": "gate_registry could not be read"},
            "counts": None, "refresh": None, "gates": None})
    refresh = dict(refresh or {})
    if refresh_error:
        refresh.update(read_state="failed", error=refresh_error)
    return {"readState": "read", "as_of": _as_of(), **result,
            "refresh": refresh or {"at": None, "head_sha": None, "read_state": "never", "error": None},
            "filters": {"category": category, "decision": decision, "state": state,
                        "real_money": real_money, "decided_since": decided_since}}


@router.get("/api/bot/gates/{gate_id}")
async def get_gate(gate_id: str) -> Any:
    _ensure_bg()
    if not GATE_ID_RE.match(gate_id):
        raise HTTPException(status_code=400, detail="bad gate id")
    try:
        found, refresh, refresh_error = await run_in_threadpool(_refresh_and, lambda c: gate_registry.get_gate(c, gate_id))
    except Exception as exc:  # noqa: BLE001  # allow-silent: 503 readState=unreadable with the error, never a 200
        logger.error("gate_registry read failed: %s", exc)
        return JSONResponse(status_code=503, content={"readState": "unreadable", "as_of": _as_of(),
                                                      "error": str(exc)[:300], "gate": None, "history": None})
    if found is None:
        raise HTTPException(status_code=404, detail=f"no gate '{gate_id}' in the registry")
    return {"readState": "read", "as_of": _as_of(), **found,
            "population": {"description": "one gate_registry row and every gate_decision_log entry for it",
                           "history_count": len(found["history"])},
            "refresh": refresh, "refresh_error": refresh_error}


@router.post("/api/bot/gates/{gate_id}/decision")
async def post_gate_decision(gate_id: str, request: Request, _session: dict = Depends(require_session)) -> Any:  # noqa: B008
    """Record the operator's decision on one gate. It changes no code; Claude implements it."""
    if not GATE_ID_RE.match(gate_id):
        raise HTTPException(status_code=400, detail="bad gate id")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body is not JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    decision = body.get("decision")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise HTTPException(status_code=400, detail="note must be a string")
    # The session is the operator's (require_session checks ALLOWED_EMAIL); the address itself is not echoed.
    who = "operator"

    def _write():
        conn = gate_registry.connect()
        try:
            rec = gate_registry.record_decision(conn, gate_id, str(decision or ""), note, who, source="spa")
            return rec, gate_registry.get_gate(conn, gate_id)
        finally:
            conn.close()

    try:
        rec, found = await run_in_threadpool(_write)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no gate '{gate_id}' in the registry")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    msg = (f"Recorded: {gate_id} → {rec['decision']} at {rec['decided_at']}. This is an instruction to Claude; "
           f"no code changed. Implementation state: {found['gate']['implementation_state']}.")
    return {"ok": True, "message": msg, "recorded": rec, "gate": found["gate"]}
