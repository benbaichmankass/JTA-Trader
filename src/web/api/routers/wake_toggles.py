"""Wake-notification toggles (console switches).

``GET  /api/bot/wake-toggles``  unauthenticated read (Tier 1, same as the other read routes): the posters on
GitHub runners and the console read it. ``read_state`` first; ``defaults`` = nobody has flipped anything yet.
``POST /api/bot/wake-toggles``  ``{key, on, by?}`` with EITHER the operator's SPA session (``Bearer ws_...``;
``by`` is then the session email, never the body's) OR the fail-closed ``DASHBOARD_API_TOKEN`` bearer (the
console MCP connector; the ``/api/bot/alerts`` / prop-report pattern). Anonymous or wrong token: 401, token
unset and no session: 503. Decision: 2026-11-09 operator UI redesign spec, UI-REDESIGN-2026-11 addendum 4 (the
Admin page's WAKE SWITCHES "view + flip, same backend as set_wake_toggle / GET+POST /api/bot/wake-toggles").
Every flip is logged with who/when/old/new (``runtime_state/wake_toggles_flips.jsonl``).

Gates this adds or changes: none -- decides only whether a session is woken. Logic: ``src/runtime/wake_toggles.py``.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from src.runtime import wake_toggles as wt
from src.web.api.auth import operator_session_or_none, session_actor
from src.web.api.routers.prop import _require_write_token

router = APIRouter(prefix="/api/bot", tags=["wake-toggles"])


def payload() -> dict[str, Any]:
    st = wt.read_local()
    t = st.get("toggles")
    rows = [{"key": k, "label": m["label"], "group": m["group"], "default": m["default"],
             "on": (None if t is None else t[k]), **((st.get("detail") or {}).get(k) or {})}
            for k, m in wt.TOGGLES.items()]
    return {"read_state": st["read_state"], "toggles": t, "rows": rows, "recent_flips": wt.recent_flips(),
            "population": f"{len(wt.TOGGLES)} wake switches (VM runtime state)",
            "note": "unreadable state => every poster posts (never silences by doubt)"}


@router.get("/wake-toggles")
def get_wake_toggles() -> dict[str, Any]:
    return payload()


@router.post("/wake-toggles")
async def post_wake_toggle(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    session = await operator_session_or_none(request)
    if session is None:
        _require_write_token(authorization)
    try:
        doc = await request.json()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="body must be JSON") from exc
    if not isinstance(doc, dict) or doc.get("key") not in wt.TOGGLES or not isinstance(doc.get("on"), bool):
        raise HTTPException(status_code=400, detail=f"body needs key in {sorted(wt.TOGGLES)} and boolean on")
    by = session_actor(session) if session is not None else str(doc.get("by") or "console")[:80]
    try:
        await asyncio.to_thread(wt.set_toggle, doc["key"], doc["on"], by)
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"state not writable: {type(exc).__name__}") from exc
    return payload()
