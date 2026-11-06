"""Alert ledger routes (row ``ALERT-LEDGER-TO-MANAGER``).

``GET  /api/bot/alerts?since=&kind=&channel=&limit=``  the one read (SPA / service token).
``POST /api/bot/alerts``  shell / workflow senders that curl Telegram directly record
                         what they sent; fail-closed ``DASHBOARD_API_TOKEN`` bearer
                         (the ``exec-js-signature`` pattern). A failed POST is ignored
                         by the sender, so this route can never gate a send.
The same read is mirrored at ``GET /api/diag/alerts`` (``DIAG_READ_TOKEN``) in
``routers/diag.py`` so ``diag_fetch.sh`` reads it.

Reply shape: ``read_state`` FIRST (``read | absent | could_not_look``), then the
rows, ``counts_by_kind``, ``newest_ts`` and the ``population``. A ledger that
cannot be read is ``could_not_look`` and an empty ``rows`` list under it means
"we did not look", never "0 alerts". Ledger: ``src/runtime/alerts_ledger.py``.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from src.runtime import alerts_ledger
from src.web.api.routers.prop import _require_write_token

router = APIRouter(prefix="/api/bot", tags=["alerts"])


def read_ledger(since: str | None, kind: str | None, channel: str | None, limit: int) -> dict[str, Any]:
    return alerts_ledger.read(since, kind, channel, limit=max(1, min(int(limit), 2000)))


@router.get("/alerts")
def get_alerts(since: str | None = None, kind: str | None = None,
               channel: str | None = None, limit: int = 500) -> dict[str, Any]:
    return read_ledger(since, kind, channel, limit)


@router.post("/alerts")
async def post_alert(request: Request,
                     authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Record one alert a non-Python sender delivered. Body:
    ``{kind, channel, body, priority?, dedup_key?, delivered?}``."""
    _require_write_token(authorization)
    try:
        doc = await request.json()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="body must be JSON") from exc
    if isinstance(doc, dict) and doc.get("route") == "ping":
        # WSD-S6A: a GitHub producer's pending-pings row, delivered exactly as the drain would.
        from src.runtime import ping_ingest
        try:
            return await asyncio.to_thread(ping_ingest.ingest, doc.get("entry"), doc.get("receipt"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — surfaced as 503 so the producer retries
            raise HTTPException(status_code=503, detail=f"ping ingest failed: {exc}") from exc
    if not isinstance(doc, dict) or not str(doc.get("body") or "").strip():
        raise HTTPException(status_code=400, detail="body is required")
    kind = str(doc.get("kind") or "").strip()
    if not kind or kind in alerts_ledger.SKIP_KINDS:
        raise HTTPException(status_code=400, detail="kind is required (replies are not ledgered)")
    ok = await asyncio.to_thread(
        alerts_ledger.append, kind, str(doc.get("channel") or "system"), str(doc["body"]),
        priority=doc.get("priority"), dedup_key=doc.get("dedup_key"),
        delivered=str(doc.get("delivered") or "unknown"))
    if not ok:
        raise HTTPException(status_code=503, detail="ledger append failed")
    return {"recorded": True}
