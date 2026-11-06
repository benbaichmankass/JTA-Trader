"""Ping ingest: the VM-side half of WSD-S6A (GitHub producers POST instead of committing).

A GitHub producer used to append a row to ``docs/claude/pending-pings.jsonl`` and commit it to
``main``; ``scripts/notify_on_pull.py`` drained it on the next git-sync. Now the producer sends
the SAME row to ``POST /api/bot/alerts`` (``route: "ping"``) and this module does what the drain
did, with the SAME functions, so delivery is identical:

* dedupe on the row's sha256 in ``runtime_logs/pending_pings_delivered.txt`` (the drain's own
  ledger, so a client retry or a straggler committed row never double-sends);
* render with ``notify_on_pull._render_event_body``;
* TELEGRAM-TRIM: ``_digest_suppressed`` -> ``telegram_policy.record_suppressed`` (recorded in the
  alert ledger, not sent), else ``send_ping.enqueue(target="claude")``;
* the delivered hash is written only AFTER the enqueue/record succeeded.

A receipt (``kind=work_digest_receipt``) is appended to the alert ledger when supplied; it replaces
the committed ``docs/claude/work/WORK-DIGEST.json`` as the digest's interval gate.

Gates this adds or changes: none. Any failure raises so the HTTP route answers 503 and the
producer retries, then falls back to the legacy commit path (nothing is dropped, nothing halts).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

RECEIPT_KIND = "work_digest_receipt"


def _canonical(entry: Dict[str, Any]) -> str:
    # The exact line a producer would have committed (json.dumps default separators).
    return json.dumps(entry, ensure_ascii=False)


def ingest(entry: Dict[str, Any], receipt: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Deliver one pending-pings row. Raises on delivery failure (caller -> 503)."""
    from scripts import notify_on_pull as npl  # noqa: PLC0415 — the drain's own renderer/policy
    from src.runtime import alerts_ledger, telegram_policy  # noqa: PLC0415

    if not isinstance(entry, dict) or not entry:
        raise ValueError("entry must be a non-empty object")
    raw = _canonical(entry)
    h = npl._line_hash(raw)
    status = "duplicate"
    if h not in npl._load_delivered_hashes(npl.DELIVERED_HASHES):
        event = str(entry.get("event") or "ping")
        priority = str(entry.get("priority") or npl.EVENT_DEFAULT_PRIORITY.get(event, "normal"))
        body = npl._render_event_body(event, entry)
        if npl._digest_suppressed(event):
            if not telegram_policy.record_suppressed(
                    "manager_update", body, reason="recurring_off", channel="manager",
                    source="alerts-post"):
                raise RuntimeError("suppressed-ledger record failed")
            status = "suppressed_by_policy"
        else:
            import sys  # noqa: PLC0415
            sys.path.insert(0, str(npl.REPO_ROOT / "scripts"))
            from send_ping import enqueue  # noqa: PLC0415
            enqueue(body, priority=priority, target=str(entry.get("target") or "claude"))
            status = "enqueued"
        npl._record_delivered_hash(npl.DELIVERED_HASHES, h)
    receipt_recorded = None
    if receipt:
        receipt_recorded = alerts_ledger.append(
            RECEIPT_KIND, "system", json.dumps(receipt, sort_keys=True), priority="normal",
            dedup_key=f"{RECEIPT_KIND}:{receipt.get('window_head', '')}", delivered="unknown")
        if not receipt_recorded:
            raise RuntimeError("receipt ledger append failed")
    return {"recorded": True, "ping": status, "hash": h[:12], "receipt": receipt_recorded}
