"""Tier-1 read endpoint for the trading pipeline map (lane PIPELINE-MAP, 2026-11-14).

- ``GET /api/bot/work/pipeline-map`` -- the map BUILT LIVE by ``src/runtime/pipeline_map.py`` from
  the hand-written skeleton (``docs/reference/trading-pipeline-map.skeleton.md``) and the sources of
  truth: rosters, strategy status, evidence records, this API's own performance aggregate (called
  in-process, R only), served ML models, mandates, unit files, the TP-doctrine guard. Cached for
  ``CACHE_S`` seconds so the Work tab is current without rebuilding on every request.

Payload: ``{path, read_state, source, built_at, markdown, structured, live_state, last_commit, file_mtime}``.
``structured`` (v2) = ``{steps: [{id, n, name, technical[], trading[]}], loops: [{from, to, label}]}`` for the spine UI.
2026-11-15 (WORK-REORDER-ROUTE, additive + one value change): element ``id`` is unique across the payload
(``step-N/<old id>``); element ``state`` is filled where a real source exists (legs: status, accounts: mode,
models: stage, mandates: granted/auto-land, module/config: repo tree + trader import closure, service: unit
file) and stays null otherwise; each step gains ``technical_groups`` / ``trading_groups``
(``{id,label,kind,count,state_counts,element_ids}``); ``?grouped=true`` returns ``technical``/``trading``
with each multi-member group collapsed into one ``kind: "group"`` element.
``source`` is ``live`` (just built) or ``snapshot`` (the committed
``docs/reference/trading-pipeline-map.md``, served only when the live build fails, with the failure
in ``build_error``). ``last_commit`` is the skeleton's last commit -- when the hand-written part last
changed. Read-only, no secrets, no DB writes. Never a 5xx: a missing source is a stated read_state.
"""
from __future__ import annotations

import datetime as _dt
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from src.utils.paths import repo_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/work", tags=["work"])

SKELETON_REL = "docs/reference/trading-pipeline-map.skeleton.md"
DOC_REL = "docs/reference/trading-pipeline-map.md"
CACHE_S = 600

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "body": None}


def _last_commit(root: Path, rel: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%H%x1f%cI%x1f%s", "--", rel],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # git missing / timeout: a state, not a crash
        logger.warning("pipeline-map: git log failed: %s", exc)
        return {"read_state": "unreadable", "sha": None, "date": None, "subject": None}
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        return {"read_state": "unreadable", "sha": None, "date": None, "subject": None}
    sha, date, subject = (out.split("\x1f") + [None, None])[:3]
    return {"read_state": "read", "sha": sha, "date": date, "subject": subject}


def _live_performance() -> tuple[dict[str, Any] | None, str]:
    """This API's own /api/bot/performance?window=all, called in-process (no HTTP hop)."""
    try:
        from src.web.api.routers.performance import get_performance
        body = get_performance(window="all")
    except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- the read state names the failure and the live columns render "—"
        logger.warning("pipeline-map: performance read failed: %s", exc)
        return None, f"unreadable ({type(exc).__name__})"
    if not isinstance(body, dict) or body.get("error"):
        return None, "unreadable (performance route reported an error)"
    return body, "read"


def _mtime(path: Path) -> str | None:
    try:
        return _dt.datetime.fromtimestamp(path.stat().st_mtime, tz=_dt.timezone.utc).isoformat()
    except OSError:
        return None


def _build(root: Path) -> dict[str, Any]:
    base = {"path": DOC_REL, "skeleton": SKELETON_REL, "last_commit": _last_commit(root, SKELETON_REL),
            "built_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
    live, live_state = _live_performance()
    try:
        from src.runtime import pipeline_map
        md = pipeline_map.build(root, live=live, live_state=live_state)
        try:
            structured = pipeline_map.build_structured(root, live=live, live_state=live_state)
        except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- structured carries its error; markdown still serves
            logger.warning("pipeline-map: structured build failed: %s", exc)
            structured = {"steps": None, "loops": None, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        return {**base, "read_state": "read", "source": "live", "markdown": md, "live_state": live_state,
                "structured": structured,
                "file_mtime": _mtime(root / SKELETON_REL), "build_error": None}
    except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- falls back to the snapshot and reports build_error
        logger.warning("pipeline-map: live build failed, serving the snapshot: %s", exc)
        err = f"{type(exc).__name__}: {str(exc)[:200]}"
    snap = root / DOC_REL
    try:
        md = snap.read_text(encoding="utf-8")
        state = "read"
    except (OSError, UnicodeDecodeError):
        md, state = None, ("missing" if not snap.exists() else "unreadable")
    return {**base, "read_state": state, "source": "snapshot", "markdown": md, "live_state": live_state,
            "file_mtime": _mtime(snap), "build_error": err}


@router.get("/pipeline-map")
def get_pipeline_map(refresh: bool = False, grouped: bool = False) -> dict[str, Any]:
    """``grouped=true`` collapses each multi-member group of ``structured`` into one ``kind: "group"``
    element (same shape the deployed UI renders); the default payload is unchanged apart from the
    additive fields documented in the module docstring."""
    now = time.monotonic()
    with _lock:
        if not refresh and _cache["body"] is not None and now - _cache["at"] < CACHE_S:
            body, age = _cache["body"], round(now - _cache["at"])
        else:
            body, age = _build(Path(repo_root())), 0
            if body.get("source") == "live":
                _cache.update(at=now, body=body)
    if grouped and isinstance(body.get("structured"), dict) and body["structured"].get("steps"):
        from src.runtime import pipeline_map
        body = {**body, "structured": pipeline_map.collapse_groups(body["structured"])}
    return {**body, "cache_age_s": age}
