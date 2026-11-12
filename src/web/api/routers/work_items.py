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
import re
from datetime import datetime, timezone
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


def accepted_work_store_tokens(now: float | None = None) -> list[str]:
    """Every value the work-store token check accepts right now (VM-CHANGE-LEDGER 4b, the rotation dual-accept).

    ``WORK_STORE_TOKEN`` always; ``WORK_STORE_TOKEN_PREV`` too while ``WORK_STORE_TOKEN_PREV_UNTIL`` (ISO-8601 UTC)
    is in the future, so a rotation never cuts off a holder of the old value mid-switch. A PREV with no parseable
    UNTIL is NOT accepted (an open-ended second token is not a rotation). Empty list = writes not configured.
    """
    import time as _time
    from datetime import datetime as _dt

    out = [t for t in [os.environ.get("WORK_STORE_TOKEN", "").strip()] if t]
    prev = os.environ.get("WORK_STORE_TOKEN_PREV", "").strip()
    until = os.environ.get("WORK_STORE_TOKEN_PREV_UNTIL", "").strip()
    if out and prev and until:
        try:
            exp = _dt.fromisoformat(until.replace("Z", "+00:00")).timestamp()
        except ValueError:
            exp = 0.0
        if (now if now is not None else _time.time()) < exp:
            out.append(prev)
    return out


def work_store_token_ok(presented: str) -> bool:
    """Constant-time match of ``presented`` against every accepted value."""
    p = (presented or "").strip()
    ok = False
    for t in accepted_work_store_tokens():
        ok = hmac.compare_digest(p, t) or ok
    return bool(p) and ok


def _require_work_store_token(authorization: str | None, x_work_store_token: str | None = None) -> None:
    """Fail-closed token gate (design G2), the ``_require_decision_write_token`` pattern.

    ``X-Work-Store-Token: <token>`` is the primary carrier. ``Authorization: Bearer <token>``
    is a DEPRECATED fallback kept while the environment secret moves to the new header.
    When the dedicated header is present it alone decides: a wrong value there is 401 even if
    ``Authorization`` would pass, so the two carriers can never disagree silently.
    """
    if not accepted_work_store_tokens():
        raise HTTPException(status_code=503, detail="work store is not configured to accept writes")
    if x_work_store_token is not None:
        if not x_work_store_token.strip():
            raise HTTPException(status_code=401, detail=f"empty {WORK_STORE_HEADER}")
        if not work_store_token_ok(x_work_store_token):
            raise HTTPException(status_code=401, detail="bad token")
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="missing authorization")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="bearer scheme required")
    if not work_store_token_ok(authorization[7:]):
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


def _week_lane(it: dict) -> str | None:
    ex = it.get("extra") if isinstance(it.get("extra"), dict) else {}
    v = ex.get("week_lane") if isinstance(ex, dict) else None
    return str(v) if v else None


_AM_RE = re.compile(r"^(AM-[A-Za-z0-9-]+)")


def _am_of(owner: Any) -> str:
    """The assistant manager an owner string belongs to (``AM-UI (session_...)`` -> ``AM-UI``); else ``other``."""
    m = _AM_RE.match(str(owner or "").strip())
    return m.group(1).upper() if m else "other"


def _matches(it: dict, *, owner_prefix: str | None, week_lane: str | None, q: str | None,
             note: dict | None) -> bool:
    if owner_prefix and not str(it.get("owner") or "").lower().startswith(owner_prefix.lower()):
        return False
    if week_lane and _week_lane(it) != week_lane:
        return False
    if q:
        hay = " ".join(str(x or "") for x in (it.get("id"), it.get("title"), it.get("summary"),
                                                (note or {}).get("note"))).lower()
        if q.lower() not in hay:
            return False
    return True


@router.get("/items")
def list_items(state: str | None = None, due: bool = False, parent: str | None = None,
               since: str | None = None, kind: str | None = None,
               limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0),
               owner_prefix: str | None = None, week_lane: str | None = None, q: str | None = None,
               counts: bool = False, latest_note: bool = False):
    """Open read. ``due=1`` reads the ``due_now`` view. ``readState`` says whether we could look.

    UI-WQ-WEEK-ROUTES (Work queue "This week" tab): ``state=open`` (every non-terminal state),
    ``owner_prefix`` (e.g. ``AM-UI``), ``week_lane`` (from ``extra.week_lane``), ``q`` (id / title /
    summary / latest note, case-insensitive), ``counts=1`` (owner x state over the WHOLE filtered set,
    before paging) and ``latest_note=1`` (each returned item carries its newest note event)."""
    open_state = state == "open"
    if state and not open_state and state not in ws.ITEM_STATES:
        raise HTTPException(status_code=400, detail=f"state must be 'open' or one of {list(ws.ITEM_STATES)}")
    extended = open_state or owner_prefix or week_lane or q or counts
    try:
        s = _store()
        total = s.count_items()
        if not extended:
            items = s.list_items(state=state, due=due, parent=parent, since=since, kind=kind,
                                 limit=limit, offset=offset)
            matched = None
            count_block = None
        else:
            pool = s.list_items(state=None if open_state else state, due=due, parent=parent, since=since,
                                kind=kind, limit=max(total, 1), offset=0)
            if open_state:
                pool = [it for it in pool if it.get("state") not in ws.TERMINAL]
            notes = s.latest_notes([it["id"] for it in pool]) if q else {}
            hits = [it for it in pool if _matches(it, owner_prefix=owner_prefix, week_lane=week_lane, q=q,
                                                    note=notes.get(it["id"]))]
            matched = len(hits)
            count_block = None
            if counts:
                by: dict[str, dict[str, int]] = {}
                for it in hits:
                    row = by.setdefault(_am_of(it.get("owner")), {})
                    row[it["state"]] = row.get(it["state"], 0) + 1
                count_block = {"by_owner_state": by, "basis": "owner grouped to its AM-* prefix, else 'other'",
                               "matched": matched}
            items = hits[offset:offset + limit]
        if latest_note:
            got = s.latest_notes([it["id"] for it in items])
            for it in items:
                it["latest_note"] = got.get(it["id"])
    except Exception as exc:  # allow-silent: not silent -- logged with stack + 503 readState could_not_look, items null (never "0 items")
        logger.exception("work_items: list read failed")
        return JSONResponse(status_code=503, content={
            "readState": "could_not_look", "error": str(exc), "items": None, "total": None})
    out = {"readState": "read", "items": items, "returned": len(items), "total": total,
           "canonical": False,
           "note": "S1: the checklist + pipeline files stay canonical until S2 parity and the S4 reader flip"}
    if matched is not None:
        out["matched"] = matched
    if count_block is not None:
        out["counts"] = count_block
    return out


@router.get("/lanes")
def lanes(next_n: int = Query(default=5, ge=1, le=50), list_cap: int = Query(default=25, ge=1, le=200)):
    """Per-AM lane cards for the Work queue "This week" tab (UI-WQ-WEEK-ROUTES).

    For each assistant manager (owner grouped by its ``AM-*`` prefix; the rest under ``other``):
    ``moved_today`` (a state change since 00:00Z, from the event log), ``working_now`` (``in_flight``),
    ``stuck`` (``blocked``, or open with ``blocked_on`` set) and ``next`` (queued, by ``priority_rank``
    then ``due_at``). Each list is ``{read_state, count, items[{id, title, state, updated_at}]}``;
    ``count`` is the full count, ``items`` capped at ``list_cap`` (``next`` at ``next_n``).
    ``week_lanes`` reuses ``work_read.week_lane_totals`` (the console's function). ``headline`` is null with
    ``headline_read_state: absent`` until the AM writes one (prose, never derived here)."""
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = midnight.isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        s = _store()
        items = s.list_items(limit=max(s.count_items(), 1))
        moves = s.state_moves_since(since)
    except Exception as exc:  # allow-silent: not silent -- logged + 503 read_state could_not_look, lanes null (never an empty board)
        logger.exception("work_items: lanes read failed")
        return JSONResponse(status_code=503, content={
            "read_state": "could_not_look", "error": str(exc), "lanes": None, "week_lanes": None})
    by_id = {it["id"]: it for it in items}

    def slim(it: dict) -> dict:
        return {"id": it["id"], "title": it.get("title"), "state": it.get("state"), "updated_at": it.get("updated_at")}

    def block(rows: list[dict], cap: int) -> dict:
        return {"read_state": "read", "count": len(rows), "items": [slim(r) for r in rows[:cap]]}

    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(_am_of(it.get("owner")), []).append(it)
    out_lanes = []
    for am in sorted(groups, key=lambda k: (k == "other", k)):
        rows = groups[am]
        open_rows = [r for r in rows if r.get("state") not in ws.TERMINAL]
        moved = sorted((r for r in rows if r["id"] in moves), key=lambda r: moves[r["id"]], reverse=True)
        working = [r for r in open_rows if r.get("state") == "in_flight"]
        stuck = [r for r in open_rows if r.get("state") == "blocked" or (r.get("blocked_on") and r.get("state") != "in_flight")]
        queued = sorted((r for r in open_rows if r.get("state") == "queued"),
                        key=lambda r: (r.get("priority_rank") is None, r.get("priority_rank") or 0,
                                       r.get("due_at") is None, r.get("due_at") or ""))
        out_lanes.append({"am": am, "open": len(open_rows), "headline": None, "headline_read_state": "absent",
                          "moved_today": block(moved, list_cap), "working_now": block(working, list_cap),
                          "stuck": block(stuck, list_cap), "next": block(queued, next_n)})
    from src.runtime.work_read import week_lane_totals
    wl = week_lane_totals([{"week_lane": _week_lane(it), "state": it.get("state")} for it in items])
    return {"read_state": "read", "as_of": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "moved_since": since, "lanes": out_lanes, "week_lanes": wl,
            "population": {"items": len(items), "lanes": len(out_lanes), "moved_today": len(moves),
                           "moved_today_unknown_items": sum(1 for i in moves if i not in by_id)},
            "provenance": {"measure": "MEASURED", "source": "work_store items + events (hash-chained)",
                           "grouping": "owner -> AM-* prefix, else 'other'"}}


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

