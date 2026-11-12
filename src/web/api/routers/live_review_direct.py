"""Direct submit of a live-review row to the VM (TRADE-ACTION-DIRECT-PATH phase 2). No git, PR or Actions hop.

Operator, 2026-11-12 ~00:00Z (row TRADE-ACTION-DIRECT-PATH): "when the review makes a decision that is approved by
a mandate, then that decision needs to be implemented on the account immediately, not through the repo." Design:
docs/design/trade-action-direct-path-2026-11.md § 2.3.

``POST /api/bot/live-review/rows``: the body is ONE review row (the same JSON a reviewer writes to
``comms/live_review/rows/<review_id>.json`` on ``live-review/rows``). It is written create-only to
``runtime_logs/live_review/direct/comms/live_review/rows/<review_id>.json``. The live trader's ``ltr-direct-rows``
thread (``live_review_rows_watch.run_direct_pass``, every 2 s) then runs it through the SAME ``process_row`` as a
branch row: a mandate-covered row is dispatched (``live_review_dispatch.py --local-root``: every mandate clause,
per-account RiskManager, both brackets, read-back); a row that needs the operator gets the phase-1 Telegram
Approve/Reject ask. This route decides nothing about the trade itself.

``GET /api/bot/live-review/rows/{review_id}``: the watcher's receipt for that row (``pending`` until handled).

Auth: the work-store service token (``X-Work-Store-Token``, which the env proxy injects on every session request
to this host; ``Authorization: Bearer`` as the deprecated fallback), checked fail-closed (503 unset, 401 wrong).
GATES: none added. The route is a transport; the trade checks are unchanged downstream.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.runtime import live_review_rows as rows_lib
from src.web.api.routers.work_items import WORK_STORE_HEADER, _require_work_store_token

router = APIRouter()

ROW_ID_RE = re.compile(r"^LR-[0-9]{8}T[0-9]{4}Z-pkg-[0-9a-f]{16}$")
MAX_BODY_BYTES = 256 * 1024
_REQUIRED = ("order_package_id", "recommendation", "disposition", "mechanics", "reviewed_at")


def _direct_root() -> Path:
    from src.runtime.live_review_rows_watch import direct_root
    return direct_root()


def _logs() -> Path:
    from src.runtime.live_review_rows_watch import log_dir
    return log_dir()


def validate_row(row: Any) -> Optional[str]:
    """None when the row may be queued; else why not. Shape only: every trade rule is checked downstream."""
    if not isinstance(row, dict):
        return "body must be one JSON object (a review row)"
    rid = row.get("review_id")
    if not isinstance(rid, str) or not ROW_ID_RE.match(rid):
        return "review_id must look like LR-YYYYMMDDTHHMMZ-pkg-<16 hex>"
    missing = [k for k in _REQUIRED if row.get(k) in (None, "")]
    if missing:
        return f"missing: {', '.join(missing)}"
    if not isinstance(row.get("recommendation"), dict) or not row["recommendation"].get("action"):
        return "recommendation.action is required"
    if not isinstance(row.get("disposition"), dict) or "route" not in row["disposition"]:
        return "disposition.route is required"
    if not str(row.get("order_package_id")).startswith("pkg-") or not rid.endswith(str(row["order_package_id"])):
        return "order_package_id must be the package named in the review_id"
    return None


def _already_seen(rid: str, logs: Path) -> bool:
    for name in ("rows_watch_state.json", "direct_rows_state.json"):
        try:
            if rid in (json.loads((logs / name).read_text()).get("seen") or []):
                return True
        except (OSError, ValueError):
            continue
    return False


@router.post("/api/bot/live-review/rows", status_code=201)
async def submit_row(request: Request, authorization: Optional[str] = Header(default=None),
                     x_work_store_token: Optional[str] = Header(default=None, alias=WORK_STORE_HEADER)) -> Any:
    _require_work_store_token(authorization, x_work_store_token)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=f"row larger than {MAX_BODY_BYTES} bytes")
    try:
        row = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="body is not JSON")
    why = validate_row(row)
    if why:
        raise HTTPException(status_code=400, detail=why)
    rid = row["review_id"]
    if _already_seen(rid, _logs()):
        raise HTTPException(status_code=409, detail=f"{rid} was already handled (a new review is a new decision)")
    dest = _direct_root() / rows_lib.row_path(rid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(row, indent=1, sort_keys=True) + "\n").encode()
    try:
        fd = os.open(str(dest) + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.link(str(dest) + ".tmp", dest)            # create-only: fails if the row already exists
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"{rid} was already submitted")
    finally:
        try:
            os.unlink(str(dest) + ".tmp")
        except OSError:
            pass
    return {"state": "accepted", "review_id": rid, "receipt": f"/api/bot/live-review/rows/{rid}",
            "note": "the live trader picks it up within ~2 s; the receipt says what it did"}


@router.get("/api/bot/live-review/rows/{review_id}")
def row_receipt(review_id: str) -> Any:
    if not ROW_ID_RE.match(review_id):
        raise HTTPException(status_code=400, detail="bad review_id")
    submitted = (_direct_root() / rows_lib.row_path(review_id)).exists()
    found: Dict[str, Any] = {}
    try:
        lines = (_logs() / "rows_watch.jsonl").read_text().splitlines()[-5000:]
        read_state = "read"
    except FileNotFoundError:
        lines, read_state = [], "absent"
    except OSError:
        return JSONResponse(status_code=503, content={"readState": "could_not_look", "receipt": None})
    for ln in lines:
        if review_id in ln:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("review_id") == review_id:
                found = r                                  # the newest line wins (retry lines precede the final)
    state = "handled" if found and not found.get("retrying") and not found.get("deferred") else (
        "pending" if submitted or found else "unknown")
    return {"readState": read_state, "review_id": review_id, "submitted_direct": submitted, "state": state,
            "receipt": found or None}


# ─────────────────────────── TRADE-ACTION-DIRECT-PATH phase 1b: the SPA console's Approve (second surface)
# The SAME state machine as the Telegram button (src/runtime/trade_approvals.decide): whichever surface decides
# first wins; the other reads ``already_<state>``. Behind the operator's SPA session (require_session, the
# default-deny dependency), never a service token: only the signed-in operator may execute an approval.

from fastapi import Depends  # noqa: E402

from src.web.api.auth import require_session  # noqa: E402


@router.get("/api/bot/trade-approvals")
def list_trade_approvals(state: Optional[str] = None, _session: dict = Depends(require_session)) -> Any:
    from src.runtime import trade_approvals
    store = trade_approvals.read_pending()
    asks = sorted((store.get("asks") or {}).values(), key=lambda a: str(a.get("created_at")), reverse=True)
    if state:
        asks = [a for a in asks if a.get("state") == state]
    return {"readState": "read", "count": len(asks), "asks": asks[:200]}


@router.post("/api/bot/trade-approvals/{token}")
async def decide_trade_approval(token: str, request: Request, session: dict = Depends(require_session)) -> Any:
    from src.runtime import trade_approvals
    if not re.fullmatch(r"[0-9a-f]{10}", token):
        raise HTTPException(status_code=400, detail="bad token")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body is not JSON")
    choice = (body or {}).get("choice") if isinstance(body, dict) else None
    if choice not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="choice must be approve or reject")
    res = trade_approvals.decide(token, choice, authorised=True, source="spa")
    code = {"approved": 200, "rejected": 200, "unknown": 404, "expired": 410}.get(res["outcome"], 409)
    return JSONResponse(status_code=code, content=res)
