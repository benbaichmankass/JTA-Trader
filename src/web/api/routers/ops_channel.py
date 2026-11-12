"""``/api/bot/ops/*`` -- the direct ops channel (MANAGER-VM-DIRECT-OPS; design § 2.3 of
docs/design/trade-action-direct-path-2026-11.md).

* ``POST /api/bot/ops/actions`` ``{"action", "params", "session", "reason", "operator_quote"?}`` ->
  ``{"job_id", "tier", "state", ...}``. 202 for a queued or awaiting job.
* ``GET /api/bot/ops/jobs/{job_id}`` -> the journaled job (state, exit, stdout tail, ``read_state``).

Auth: the work store's credential, ``X-Work-Store-Token`` (the env proxy injects it on every request a session
makes to this host; WSD-S1-PROXY-AUTH-COLLISION). Checked fail-closed on BOTH routes by
``work_items._require_work_store_token`` (503 when unset on the VM, 401 when missing or wrong): a job record carries
script output, so the read is not left open. No new secret. The token authenticates the environment; the tier rules
in ``src/runtime/ops_actions.py`` decide what it may do. This router never runs an action: it writes a job file and
the ``ict-ops-runner`` unit runs it out of process.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.runtime import ops_actions as ops
from src.web.api.routers.work_items import WORK_STORE_HEADER, _require_work_store_token

router = APIRouter(prefix="/api/bot/ops", tags=["ops-channel"])


def _err(exc: ops.OpsError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail)


@router.post("/actions")
async def submit_action(request: Request, authorization: str | None = Header(default=None),
                        x_work_store_token: str | None = Header(default=None, alias=WORK_STORE_HEADER)):
    _require_work_store_token(authorization, x_work_store_token)
    try:
        body: Any = await request.json()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    try:
        job = ops.submit(body)
    except ops.OpsError as exc:
        raise _err(exc) from None
    return JSONResponse(status_code=202, content=job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None),
            x_work_store_token: str | None = Header(default=None, alias=WORK_STORE_HEADER)):
    _require_work_store_token(authorization, x_work_store_token)
    try:
        return ops.read_job(job_id)
    except ops.OpsError as exc:
        raise _err(exc) from None
