"""``/api/bot/work/items`` -- the work store's API (WSD-S1-STORE-API, design § 2.3).

Writes (``POST``) are behind ``WORK_STORE_TOKEN`` (sent as ``X-Work-Store-Token``; Bearer is a deprecated fallback) -- a write-scoped token accepted by
these routes ONLY (never ``prop/report`` or ``decision``), fail-closed exactly like
``work._require_decision_write_token``: 503 when the token is unset on the VM, 401 when
missing / wrong scheme / wrong. Optimistic concurrency (G3): every write after create
carries ``If-Match: <version>``; a stale version is answered 409 with the current item.

Reads (``GET``) stay open ("Reading is never gated"). CORS is configured once in
``src/web/api/main.py`` and is not touched here.

S1 only: nothing reads this store as truth yet. The checklist row files and the pipeline
store stay canonical until S2 (importer + parity) and S4 (reader flip).
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from src.runtime import work_store as ws

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/work", tags=["work-items"])

_STORE: ws.WorkStore | None = None
_STORE_PATH: str | None = None


def _store() -> ws.WorkStore:
    """One WorkStore per resolved path (re-resolved, so tests can repoint WORK_STORE_DB)."""
    global _STORE, _STORE_PATH
    from src.utils.paths import work_store_db_path
    path = work_store_db_path()
    if _STORE is None or _STORE_PATH != path:
        _STORE, _STORE_PATH = ws.WorkStore(path), path
    return _STORE


#: The dedicated header the work-store token travels in (WSD-S1-PROXY-AUTH-COLLISION).
#: A cloud environment's proxy injects a saved network secret into EVERY request to the
#: host; carried in ``Authorization`` it overwrote every other bearer a session sends to
#: ict-bot.duckdns.org (DIAG_READ_TOKEN on /api/diag/*, measured 2026-11-05T06:43Z). In
#: its own header it touches nothing else.
WORK_STORE_HEADER = "X-Work-Store-Token"


def _require_work_store_token(authorization: str | None, x_work_store_token: str | None = None) -> None:
    """Fail-closed token gate (design G2), the ``_require_decision_write_token`` pattern.

    ``X-Work-Store-Token: <token>`` is the primary carrier. ``Authorization: Bearer <token>``
    is a DEPRECATED fallback kept while the environment secret moves to the new header.
    When the dedicated header is present it alone decides: a wrong value there is 401 even if
    ``Authorization`` would pass, so the two carriers can never disagree silently.
    """
    expected = os.environ.get("WORK_STORE_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="work store is not configured to accept writes")
    if x_work_store_token is not None:
        if not x_work_store_token.strip():
            raise HTTPException(status_code=401, detail=f"empty {WORK_STORE_HEADER}")
        if not hmac.compare_digest(x_work_store_token.strip().encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="bad token")
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="missing authorization")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="bearer scheme required")
    if not hmac.compare_digest(authorization[7:].strip().encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="bad token")


def _version(if_match: str | None) -> int | None:
    if if_match is None or not str(if_match).strip():
        return None
    raw = str(if_match).strip().removeprefix("W/").strip('"')
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="If-Match must be the integer item version") from None


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    return body


def _by(body: dict) -> str:
    by = body.pop("by", None)
    if not isinstance(by, str) or not by.strip():
        raise HTTPException(status_code=400, detail="`by` is required (who is writing)")
    return by.strip()


def _answer(fn, *, created: bool = False) -> JSONResponse:
    try:
        out = fn()
    except ws.ConflictError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc), "current": exc.current})
    except ws.WorkStoreError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    status = 201 if created and not out.get("replayed") else 200
    headers = {"ETag": str(out["item"]["version"])} if out.get("item") else {}
    return JSONResponse(status_code=status, content=out, headers=headers)


@router.post("/items")
async def create_item(request: Request, authorization: str | None = Header(default=None),
                   x_work_store_token: str | None = Header(default=None, alias=WORK_STORE_HEADER)):
    """Create one item. Body: ``{id, kind, title, ..., by, op_id?}``. 201, or 200 on a replayed op_id."""
    _require_work_store_token(authorization, x_work_store_token)
    body = await _body(request)
    by, op_id = _by(body), body.pop("op_id", None)
    return _answer(lambda: _store().create(body, by=by, op_id=op_id), created=True)


@router.post("/items/{item_id}/set")
async def set_item(item_id: str, request: Request, authorization: str | None = Header(default=None),
                   x_work_store_token: str | None = Header(default=None, alias=WORK_STORE_HEADER),
                   if_match: str | None = Header(default=None)):
    """Patch fields. Body: ``{fields: {...}, by, op_id?}``; ``If-Match: <version>`` required."""
    _require_work_store_token(authorization, x_work_store_token)
    body = await _body(request)
    by, op_id = _by(body), body.pop("op_id", None)
    fields = body.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise HTTPException(status_code=400, detail="`fields` must be a non-empty object")
    return _answer(lambda: _store().set(item_id, fields, by=by, op_id=op_id,
                                        expected_version=_version(if_match)))


@router.post("/items/{item_id}/note")
async def note_item(item_id: str, request: Request, authorization: str | None = Header(default=None),
                   x_work_store_token: str | None = Header(default=None, alias=WORK_STORE_HEADER),
                    if_match: str | None = Header(default=None)):
    """Append a note event. Body: ``{text, summary?, by, op_id?}``; ``If-Match`` required."""
    _require_work_store_token(authorization, x_work_store_token)
    body = await _body(request)
    by, op_id = _by(body), body.pop("op_id", None)
    return _answer(lambda: _store().note(item_id, body.get("text"), summary=body.get("summary"),
                                         by=by, op_id=op_id, expected_version=_version(if_match)))


@router.post("/items/{item_id}/close")
async def close_item(item_id: str, request: Request, authorization: str | None = Header(default=None),
                   x_work_store_token: str | None = Header(default=None, alias=WORK_STORE_HEADER),
                     if_match: str | None = Header(default=None)):
    """Close with a stated reason. Body: ``{state: done|dropped, reason, by, op_id?}``."""
    _require_work_store_token(authorization, x_work_store_token)
    body = await _body(request)
    by, op_id = _by(body), body.pop("op_id", None)
    return _answer(lambda: _store().close(item_id, state=body.get("state", "done"), reason=body.get("reason"),
                                          by=by, op_id=op_id, expected_version=_version(if_match)))


@router.get("/items")
def list_items(state: str | None = None, due: bool = False, parent: str | None = None,
               since: str | None = None, kind: str | None = None,
               limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    """Open read. ``due=1`` reads the ``due_now`` view. ``readState`` says whether we could look."""
    try:
        s = _store()
        items = s.list_items(state=state, due=due, parent=parent, since=since, kind=kind,
                             limit=limit, offset=offset)
        total = s.count_items()
    except Exception as exc:  # allow-silent: not silent -- logged with stack + 503 readState could_not_look, items null (never "0 items")
        logger.exception("work_items: list read failed")
        return JSONResponse(status_code=503, content={
            "readState": "could_not_look", "error": str(exc), "items": None, "total": None})
    return {"readState": "read", "items": items, "returned": len(items), "total": total,
            "canonical": False,
            "note": "S1: the checklist + pipeline files stay canonical until S2 parity and the S4 reader flip"}


@router.get("/items/{item_id}")
def get_item(item_id: str):
    item = _store().get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"no item {item_id!r}")
    return JSONResponse(content={"item": item}, headers={"ETag": str(item["version"])})


@router.get("/items/{item_id}/events")
def item_events(item_id: str):
    """The item's events plus the whole-chain verification (tamper evidence)."""
    s = _store()
    if s.get(item_id) is None:
        raise HTTPException(status_code=404, detail=f"no item {item_id!r}")
    return {"item_id": item_id, "events": s.events(item_id), "chain": s.verify_chain()}


@router.get("/parity")
def parity(hours: int = Query(default=48, ge=1, le=24 * 14)):
    """WSD-S2 shadow parity: the latest importer report and the window summary.

    Written by ``ict-work-store-import.timer`` (``scripts/ops/work_store_import.py --apply``)
    to ``runtime_logs/work_store_parity*.json*``. A missing log is ``readState: absent``, never
    a clean window."""
    import json as _json

    from scripts.ops import work_store_import as wsi
    try:
        lines = wsi.read_log()
        latest_path = wsi.log_dir() / wsi.LATEST_NAME
        latest = _json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.is_file() else None
    except Exception as exc:  # allow-silent: not silent -- logged with stack + 503 readState could_not_look
        logger.exception("work_items: parity read failed")
        return JSONResponse(status_code=503, content={"readState": "could_not_look", "error": str(exc)})
    if not lines:
        return {"readState": "absent", "latest": None, "window": None,
                "note": "no parity run recorded yet (ict-work-store-import.timer not fired here)"}
    return {"readState": "read", "latest": latest, "window": wsi.summarize(lines, hours=hours)}

