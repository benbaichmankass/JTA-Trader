"""The daily-DD switch's one-time operator override (DD-SWITCH-OVERRIDE).

Operator decision 2026-11-12 (m7, docs/plans/thursday-planning-2026-11-12-answers.md):
"Build the one-time override button and fix the day-start reading first".

``GET  /api/bot/accounts/{account}/daily-dd-switch``           the switch status for one account
                                                               (same shape as ``/api/bot/config``
                                                               ``accounts[].daily_dd_switch``) plus
                                                               today's override record.
``POST /api/bot/accounts/{account}/daily-dd-switch/override``  body ``{"reason": "<text>"}`` (optional).
                                                               Clears TODAY's trip for that ONE account
                                                               for the rest of its trading day; at most
                                                               once per account per day.

Responses (POST): 200 ``{"outcome": "overridden", "override": {...}, "status": {...}}``;
409 ``already_overridden`` / ``not_tripped``; 400 ``not_armed``; 404 unknown or retired account;
503 the journal could not be written (nothing overridden).

Auth: the operator's SPA session (``require_session``, the trade-approvals pattern) -- the override is
the operator's act; ``by`` is the session's email claim.

Gates this adds or changes: none. The switch stays a per-trade ``RiskManager`` refusal (keep open, block
new); the override only lifts that refusal for the rest of the day it was used on. Not a mode flip.
Logic: ``src/units/accounts/daily_dd_switch.py`` (``DailyDDSwitch.override``).
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.web.api.auth import require_session

router = APIRouter(prefix="/api/bot", tags=["daily-dd-switch"])

_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_ACCOUNTS_YAML: Optional[Path] = None   # test seam; None = the loader's default path

_CODES = {"overridden": 200, "already_overridden": 409, "not_tripped": 409, "not_armed": 400}


def _switch(account: str):
    if not _ACCOUNT_RE.match(account or ""):
        raise HTTPException(status_code=400, detail="bad account id")
    from src.config.accounts_loader import load_accounts_dict
    from src.units.accounts.daily_dd_switch import switch_for_account
    errors: list = []
    accounts = load_accounts_dict(_ACCOUNTS_YAML, errors=errors)
    if not accounts:
        raise HTTPException(status_code=503, detail="accounts config unreadable")
    cfg = accounts.get(account)
    if not isinstance(cfg, dict) or cfg.get("retired") is True:
        raise HTTPException(status_code=404, detail=f"unknown account {account}")
    return switch_for_account(account, cfg)


@router.get("/accounts/{account}/daily-dd-switch")
def get_dd_switch(account: str) -> Dict[str, Any]:
    sw = _switch(account)
    return {"account": account, "status": sw.status()}


@router.post("/accounts/{account}/daily-dd-switch/override")
async def post_dd_switch_override(account: str, request: Request,
                                  session: dict = Depends(require_session)) -> Any:
    sw = _switch(account)
    reason = ""
    raw = await request.body()
    if raw.strip():
        try:
            doc = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="body must be JSON") from exc
        if not isinstance(doc, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        reason = str(doc.get("reason") or "")[:500]
    by = str((session or {}).get("email") or (session or {}).get("sub") or "operator-session")
    try:
        outcome, payload = await asyncio.to_thread(sw.override, by=by, reason=reason)
    except OSError as exc:
        raise HTTPException(status_code=503,
                            detail=f"override journal not writable: {type(exc).__name__}") from exc
    return JSONResponse(status_code=_CODES.get(outcome, 409),
                        content={"account": account, "outcome": outcome, **payload})
