"""The work-store token's rotation, VM side (VM-CHANGE-LEDGER 4b; runbook docs/runbooks/ops-token-rotation.md).

Lives under ``src/web/`` because the credential is the web API's alone (``scripts/ops/sync_vm_secrets.sh::
WEB_API_ONLY_KEYS``): the ops runner calls :func:`stage` through the ``stage-token-rotation`` action, and the dual
accept is ``routers/work_items.accepted_work_store_tokens``. Gates this adds: none.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

#: How long the previous token stays accepted after staging.
TOKEN_PREV_WINDOW_H = 72
STAGED_KEYS = ("WORK_STORE_TOKEN_PREV", "WORK_STORE_TOKEN_PREV_UNTIL")


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()[:8] if v else "-"


def _upsert_env(text: str, key: str, value: str) -> str:
    lines, done = text.splitlines(), False
    for i, ln in enumerate(lines):
        if ln.startswith(f"{key}="):
            lines[i], done = f"{key}={value}", True
    if not done:
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def stage(env_path: Path, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Copy WORK_STORE_TOKEN to WORK_STORE_TOKEN_PREV with an expiry, in place (mode kept). Prints fingerprints,
    never values. The new token then arrives as WORK_STORE_TOKEN by the sync-vm-secrets workflow."""
    now = now or _now()
    text = env_path.read_text()
    cur = None
    for ln in text.splitlines():
        if ln.startswith("WORK_STORE_TOKEN="):
            cur = ln.split("=", 1)[1].strip().strip('"').strip("'")
    if not cur:
        return {"exit": 2, "detail": f"refused: no WORK_STORE_TOKEN in {env_path.name}; nothing to stage"}
    until = _iso(now + timedelta(hours=TOKEN_PREV_WINDOW_H))
    new = _upsert_env(_upsert_env(text, "WORK_STORE_TOKEN_PREV", cur), "WORK_STORE_TOKEN_PREV_UNTIL", until)
    mode = env_path.stat().st_mode & 0o777
    backup = env_path.with_name(f"{env_path.name}.bak.{now.strftime('%Y%m%dT%H%M%SZ')}")
    backup.write_text(text)
    os.chmod(backup, mode)
    tmp = env_path.with_name(f".{env_path.name}.{os.getpid()}.tmp")
    tmp.write_text(new)
    os.chmod(tmp, mode)
    os.replace(tmp, env_path)
    return {"exit": 0, "prev_fingerprint": _fingerprint(cur), "prev_until": until, "backup": backup.name,
            "detail": f"WORK_STORE_TOKEN_PREV staged (fp {_fingerprint(cur)}), accepted until {until}"}
