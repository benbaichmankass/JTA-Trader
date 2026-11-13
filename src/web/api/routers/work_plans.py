"""Work queue 'Plans' tab (UI-WQ-PLANS-ROUTES; design docs/design/ui-redesign-2026-11-reconciliation.md § Tab 5).

- ``GET /api/bot/ml/plan`` — **Tier 1, read.** The ML development plan joined to the live work store:
  ``items`` (``docs/plans/ml-plan-items.yaml``, each with its carrying ``ref`` and that ref's live ``ref_state``)
  and ``dev_plan`` (``docs/plans/ml-dev-plan.yaml`` through ``scripts/ops/ml_dev_plan.py``'s own analysis — the
  reader that file names as "what the operator's Plans page renders"; nothing is re-derived here).
- ``POST /api/bot/work/plan-edits`` — **Tier 2, operator write** behind ``require_session``. Files one operator add
  or edit as a work-store item of ``kind: observation`` under the item it targets (or the plan root for an add),
  carrying ``extra.plan_edit = {section, item_id, kind, text, status: "new", reply: null}``. The manager relays it by
  setting ``owner``; the owner closes it with ``terminal_reason: applied`` or ``declined: <why>``. Read back with
  ``GET /api/bot/work/items?kind=observation&parent=<parent>``.

The frontier sub-queue needs no route: its ``FRONTIER-Q-*`` items are children of ``FRONTIER-RESEARCH`` (parent
backfilled 2026-11-12), so ``GET /api/bot/work/items?parent=FRONTIER-RESEARCH`` selects them; their
``why``/``baseline``/``family``/``est_cost`` live in ``extra.frontier``.

Gates this adds or changes: none.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from src.utils.paths import repo_root
from src.web.api.auth import require_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["work-plans"])

_CACHE_TTL_S = 30.0
_cache: tuple[float, dict[str, Any]] | None = None

#: Where an ADD lands when it names no item: the section's root row.
PLAN_ROOTS = {"frontier": "FRONTIER-RESEARCH", "ml_plan": "ML-DEV-PLAN"}
EDIT_KINDS = ("add", "edit")
MAX_TEXT_CHARS = 4000
CLOSED_REF = {"done", "dropped", "killed", "retired", "archived"}


def _as_of() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _store():
    """The live WorkStore, or None when its file does not exist (never created from a read)."""
    from src.runtime import work_read

    return work_read.local_store()


def _item_ref_state(ref: str, rowmap: dict[str, dict] | None, repo: Path, mdp) -> tuple[str | None, str]:
    """``(ref_state, ref_kind)`` for one plan item's ref. ``ref_state`` None = unresolved or not looked at."""
    if ref.startswith("recurring:"):
        ok = (repo / ".claude/skills" / ref.split(":", 1)[1] / "SKILL.md").exists()
        return ("recurring" if ok else None), "skill"
    if ref.startswith("RQ-"):
        u = mdp.unit_state(ref, repo)
        return (u["status"] if u else None), "unit"
    if rowmap is None:
        return None, "row"
    r = rowmap.get(ref)
    return (r.get("state") if r else None), "row"


def build_plan() -> dict[str, Any]:
    """The whole payload. Raises only when the plan files themselves cannot be read."""
    from scripts.ops import ml_dev_plan as mdp

    repo = Path(repo_root())
    items_doc = yaml.safe_load((repo / "docs/plans/ml-plan-items.yaml").read_text(encoding="utf-8")) or {}
    dev = mdp.load(repo / "docs/plans/ml-dev-plan.yaml")

    rows_state, rows_error, rowmap = "read", None, None
    try:
        store = _store()
        if store is None:
            rows_state = "absent"
        else:
            rowmap = {r["id"]: r for r in store.list_items(limit=10 ** 7) if r.get("id")}
    except Exception as exc:  # noqa: BLE001  # allow-silent: published as rows_read_state unreadable + error; ref states go null, never "orphan".
        rows_state, rows_error = "unreadable", f"{type(exc).__name__}: {exc}"[:300]

    items: list[dict[str, Any]] = []
    by_track: dict[str, int] = {}
    for it in items_doc.get("items") or []:
        ref = str(it.get("ref") or "")
        ref_state, ref_kind = _item_ref_state(ref, rowmap, repo, mdp)
        looked = ref_kind != "row" or rowmap is not None
        flags: list[str] = []
        if looked:
            if ref_state is None:
                flags.append("ORPHAN")
            elif it.get("state") == "open" and ref_state in CLOSED_REF:
                flags.append("CLOSED-OPEN")
            elif it.get("state") == "done" and ref_state not in CLOSED_REF | {"recurring"}:
                flags.append("OPEN-DONE")
        track = str(it.get("track") or "?")
        by_track[track] = by_track.get(track, 0) + 1
        items.append({
            "id": it.get("id"), "track": track, "title": it.get("title"), "plan_state": it.get("state"),
            "family": it.get("family"), "tier": it.get("tier"), "closes_when": it.get("close"),
            "ref": ref or None, "ref_kind": ref_kind, "ref_state": ref_state,
            # "row we could not read" is not "no such row": null + this read state, never an ORPHAN flag.
            "ref_read_state": "read" if looked else rows_state,
            "flags": flags,
        })

    # The dev plan, through its own reader. When the store could not be read the line flags would read every
    # row as an orphan, so they are withheld (null) rather than published wrong.
    lines = mdp.analyse(dev, rowmap or {}, mdp.plan_item_ids(repo / "docs/plans/ml-plan-items.yaml"), repo)
    if rowmap is None:
        for ln in lines:
            ln["flags"] = None
            ln["row_state"] = None
    dev_plan = mdp.render_json(dev, lines, "read" if rowmap is not None else rows_state)

    return {
        "read_state": "read" if rowmap is not None else "partial",
        "as_of": _as_of(),
        "rows_read_state": rows_state,
        "rows_error": rows_error,
        "items": items,
        "dev_plan": dev_plan,
        "population": {
            "items": len(items), "items_by_track": by_track, "dev_plan_lines": len(dev.get("lines") or []),
            "description": "every item in docs/plans/ml-plan-items.yaml and every line in docs/plans/ml-dev-plan.yaml "
                           "on the VM working tree, joined to the work store's rows",
        },
        "sources": {"items": "docs/plans/ml-plan-items.yaml", "dev_plan": "docs/plans/ml-dev-plan.yaml",
                    "reader": "scripts/ops/ml_dev_plan.py"},
        "frontier": {"route": "/api/bot/work/items?parent=FRONTIER-RESEARCH",
                     "fields": "extra.frontier (why, baseline, family, est_cost, consumer, next_step, ...)"},
    }


@router.get("/api/bot/ml/plan")
async def get_ml_plan() -> Any:
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < _CACHE_TTL_S:
        return _cache[1]
    try:
        payload = await run_in_threadpool(build_plan)
    except Exception as exc:  # noqa: BLE001  # allow-silent: logged at ERROR; 503 read_state unreadable with items/dev_plan null (never empty lists).
        logger.error("ml plan read failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=503, content={
            "read_state": "unreadable", "as_of": _as_of(), "error": str(exc)[:300],
            "items": None, "dev_plan": None, "population": None})
    _cache = (now, payload)
    return payload


def _edit_item(body: dict[str, Any], today: str) -> dict[str, Any]:
    """Validate the body and build the store item (raises HTTPException 400)."""
    section = body.get("section")
    if section not in PLAN_ROOTS:
        raise HTTPException(status_code=400, detail=f"section must be one of {sorted(PLAN_ROOTS)}")
    kind = body.get("kind")
    if kind not in EDIT_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {list(EDIT_KINDS)}")
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    text = text.strip()
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=400, detail=f"text exceeds {MAX_TEXT_CHARS} characters")
    item_id = body.get("item_id")
    if item_id is not None and (not isinstance(item_id, str) or not item_id.strip()):
        raise HTTPException(status_code=400, detail="item_id must be a non-empty string")
    item_id = item_id.strip() if isinstance(item_id, str) else None
    if kind == "edit" and not item_id:
        raise HTTPException(status_code=400, detail="an edit names the item_id it changes")
    parent = item_id or PLAN_ROOTS[section]
    summary = text if len(text) <= 120 else text[:117] + "..."
    return {
        "id": f"PLAN-EDIT-{today.replace('-', '')}-{uuid.uuid4().hex[:6].upper()}",
        "kind": "observation",
        "state": "queued",
        "parent_id": parent,
        "title": f"Operator plan {kind} ({section}){' on ' + item_id if item_id else ''}: {summary}",
        "owner": "manager",
        "next_action": "dispatch_lane",
        "origin": {"kind": "operator", "ref": "SPA Plans tab (POST /api/bot/work/plan-edits)",
                   "rerun": f"GET /api/bot/work/items?kind=observation&parent={parent}"},
        "due_rule": {"kind": "observation",
                     "clears_when": "the owner closes it: terminal_reason 'applied' or 'declined: <why>'"},
        "extra": {"plan_edit": {"section": section, "item_id": item_id, "kind": kind, "text": text,
                                "status": "new", "reply": None}},
    }


@router.post("/api/bot/work/plan-edits")
async def post_plan_edit(request: Request, _session: dict = Depends(require_session)) -> Any:  # noqa: B008
    """File one operator add/edit. **Tier 2.** 200 with the item; 400 bad body; 404 unknown target item;
    503 when the work store is absent or the write did not persist."""
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body is not JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    item = _edit_item(body, datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    def _write():
        from src.runtime import work_store as ws

        store = _store()
        if store is None:
            raise FileNotFoundError("work store is absent on this host")
        if store.get(item["parent_id"]) is None:
            return None
        try:
            # The shared session actor ("operator-spa"): never the email (manager 2026-11-13).
            from src.web.api.auth import SESSION_ACTOR
            return store.create(item, by=SESSION_ACTOR)["item"]
        except ws.WorkStoreValidationError as exc:
            raise ValueError(str(exc)) from exc

    try:
        created = await run_in_threadpool(_write)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from None
    except Exception as exc:  # noqa: BLE001  # allow-silent: logged at ERROR and returned as 503 — an edit the operator thinks landed and did not is refused loudly.
        logger.error("plan edit did not persist: %s", exc)
        raise HTTPException(status_code=503, detail=f"plan edit did not persist: {str(exc)[:200]}") from None
    if created is None:
        raise HTTPException(status_code=404, detail=f"no work item '{item['parent_id']}' to attach this to")
    return {"accepted": True, "status": "new", "item": created,
            "read_back": f"/api/bot/work/items?kind=observation&parent={item['parent_id']}"}
