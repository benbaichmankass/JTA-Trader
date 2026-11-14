"""Tier-1 read endpoint for the trading pipeline map (lane PIPELINE-MAP, 2026-11-14).

- ``GET /api/bot/work/pipeline-map`` -- the committed
  ``docs/reference/trading-pipeline-map.md`` as raw markdown (including its
  mermaid flow diagram) plus the commit and date that last changed it, so the
  dashboard's Work tab can render it and say how old it is.

File-backed from the repo tree on the VM (``ict-git-sync`` mirrors ``main``).
Read-only, no secrets, no DB. Best-effort: a missing file is HTTP 200 with
``read_state: "missing"`` and ``markdown: null``, never a 5xx; an unreadable git
history leaves ``last_commit`` null with its own read-state, and the file's
mtime is reported beside it, labelled as such.
"""
from __future__ import annotations

import datetime as _dt
import logging
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from src.utils.paths import repo_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/work", tags=["work"])

DOC_REL = "docs/reference/trading-pipeline-map.md"


def _last_commit(root: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%H%x1f%cI%x1f%s", "--", DOC_REL],
            capture_output=True, text=True, timeout=5, check=False,
        )
        out = proc.stdout.strip()
        if proc.returncode != 0 or not out:
            return {"read_state": "unreadable", "sha": None, "date": None, "subject": None}
        sha, date, subject = (out.split("\x1f") + [None, None])[:3]
        return {"read_state": "read", "sha": sha, "date": date, "subject": subject}
    except (OSError, subprocess.SubprocessError) as exc:  # git missing / timeout: a state, not a crash
        logger.warning("pipeline-map: git log failed: %s", exc)
        return {"read_state": "unreadable", "sha": None, "date": None, "subject": None}


@router.get("/pipeline-map")
def get_pipeline_map() -> dict[str, Any]:
    root = Path(repo_root())
    path = root / DOC_REL
    if not path.is_file():
        return {"path": DOC_REL, "read_state": "missing", "markdown": None,
                "last_commit": {"read_state": "not_read", "sha": None, "date": None, "subject": None},
                "file_mtime": None}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("pipeline-map: read failed: %s", exc)
        return {"path": DOC_REL, "read_state": "unreadable", "markdown": None,
                "last_commit": {"read_state": "not_read", "sha": None, "date": None, "subject": None},
                "file_mtime": None}
    mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime, tz=_dt.timezone.utc).isoformat()
    return {"path": DOC_REL, "read_state": "read", "markdown": text,
            "last_commit": _last_commit(root), "file_mtime": mtime}
