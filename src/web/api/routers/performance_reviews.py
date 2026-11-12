"""Performance-review list + fetch-one (UI-SPA-BACKEND-ROUTES, 2026-11-12).

Backs the Performance page's "list of performance reviews, openable"
(UI-REDESIGN-2026-11, operator 2026-11-09). NOT ``/strategy-reviews``.

- ``GET /api/bot/performance/reviews[?kind=&limit=]`` -- newest first.
- ``GET /api/bot/performance/reviews/{review_id}``    -- one review's content.

Sources, file-backed from the repo tree the VM's ``ict-git-sync`` mirrors
(read-only, no DB, no secrets):

* ``comms/reviews/performance-review-*.json``  -> ``kind: performance_review``
* ``docs/reviews/*weekly-walkthrough*.md``     -> ``kind: weekly_walkthrough``
  (``...-perf.md`` -> ``weekly_walkthrough_perf``, ``...-ml.md`` ->
  ``weekly_walkthrough_ml``)

``review_id`` is the file stem and is resolved by LISTING the two directories
and matching -- never by joining the caller's string onto a path -- so there
is no traversal surface. A stamp is the review's own ``reviewed_at`` where the
file carries one (``stamp_basis: reviewed_at``), else the date in its
filename (``filename_date``); a stamp is never invented.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.utils.paths import repo_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot/performance/reviews", tags=["performance-reviews"])

MAX_BYTES = 2_000_000
_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_KINDS = ("performance_review", "weekly_walkthrough",
          "weekly_walkthrough_perf", "weekly_walkthrough_ml")


def _sources() -> List[Dict[str, Any]]:
    root = Path(repo_root())
    return [
        {"source": "comms/reviews", "dir": root / "comms" / "reviews",
         "glob": "performance-review-*.json"},
        {"source": "docs/reviews", "dir": root / "docs" / "reviews",
         "glob": "*weekly-walkthrough*.md"},
    ]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _kind_for(path: Path) -> str:
    if path.suffix == ".json":
        return "performance_review"
    if path.stem.endswith("-perf"):
        return "weekly_walkthrough_perf"
    if path.stem.endswith("-ml"):
        return "weekly_walkthrough_ml"
    return "weekly_walkthrough"


def _entry(path: Path, rel: str) -> Optional[Dict[str, Any]]:
    """Index row for *path*, or None when the file cannot be read at all."""
    kind = _kind_for(path)
    stamp: Optional[datetime] = None
    basis = None
    title: Optional[str] = None
    summary: Optional[str] = None
    window_start = window_end = None
    try:
        size = path.stat().st_size
        if size > MAX_BYTES:
            return None
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("performance_reviews: unreadable %s: %s", path, exc)
        return None
    if path.suffix == ".json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict):
            stamp = _parse_ts(doc.get("reviewed_at"))
            basis = "reviewed_at" if stamp else None
            window_start = doc.get("window_start")
            window_end = doc.get("window_end")
            oa = doc.get("overall_assessment")
            if isinstance(oa, str) and oa.strip():
                summary = oa.strip()[:240]
        title = f"Performance review {path.stem.split('performance-review-')[-1]}"
    else:
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    if stamp is None:
        m = _DATE_PREFIX.match(path.stem)
        if m is None:
            m = re.search(r"(\d{4})(\d{2})(\d{2})", path.stem)
            date = "-".join(m.groups()) if m else None
        else:
            date = m.group(1)
        stamp = _parse_ts(date) if date else None
        basis = "filename_date" if stamp else None
    return {
        "id": path.stem,
        "kind": kind,
        "stamp": _iso(stamp) if stamp else None,
        "stamp_basis": basis,
        "title": title or path.stem,
        "summary": summary,
        "window_start": window_start if isinstance(window_start, str) else None,
        "window_end": window_end if isinstance(window_end, str) else None,
        "format": "json" if path.suffix == ".json" else "markdown",
        "path": rel,
        "_sort": stamp or datetime.min.replace(tzinfo=timezone.utc),
        "_file": path,
    }


def _index() -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    srcs: List[Dict[str, Any]] = []
    unreadable = 0
    for s in _sources():
        d: Path = s["dir"]
        if not d.is_dir():
            srcs.append({"source": s["source"], "read_state": "absent", "count": None})
            continue
        n = 0
        try:
            files = sorted(d.glob(s["glob"]))
        except OSError as exc:
            logger.warning("performance_reviews: cannot list %s: %s", d, exc)
            srcs.append({"source": s["source"], "read_state": "unreadable", "count": None})
            continue
        for f in files:
            if not f.is_file():
                continue
            e = _entry(f, f"{s['source']}/{f.name}")
            if e is None:
                unreadable += 1
                continue
            entries.append(e)
            n += 1
        srcs.append({"source": s["source"], "read_state": "read", "count": n})
    entries.sort(key=lambda e: (e["_sort"], e["id"]), reverse=True)
    states = {s["read_state"] for s in srcs}
    if states == {"read"} and not unreadable:
        read_state = "read"
    elif "read" in states:
        read_state = "partial"
    else:
        read_state = "could_not_look"
    return {"entries": entries, "sources": srcs, "read_state": read_state,
            "unreadable_files": unreadable}


def _public(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in e.items() if not k.startswith("_")}


@router.get("")
def list_reviews(
    kind: Optional[str] = Query(None, max_length=40),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """``{as_of, read_state, sources[], unreadable_files, total, count, reviews[]}``.

    ``read_state`` is ``read`` (every source listed), ``partial`` (one source
    absent/unreadable, or a file skipped) or ``could_not_look`` (none read) --
    an empty ``reviews`` with ``read`` means "we looked and there are none".
    Unknown ``kind`` is 400.
    """
    if kind is not None and kind not in _KINDS:
        raise HTTPException(status_code=400,
                            detail=f"unknown kind {kind!r}; valid: {list(_KINDS)}")
    idx = _index()
    rows = [e for e in idx["entries"] if kind is None or e["kind"] == kind]
    return {
        "as_of": _iso(datetime.now(timezone.utc)),
        "read_state": idx["read_state"],
        "sources": idx["sources"],
        "unreadable_files": idx["unreadable_files"],
        "kind": kind,
        "total": len(rows),
        "count": len(rows[:limit]),
        "reviews": [_public(e) for e in rows[:limit]],
    }


@router.get("/{review_id}")
def get_review(review_id: str) -> Dict[str, Any]:
    """One review: its index row plus ``content_text`` (markdown) or
    ``content_json`` (parsed JSON review); the other is ``null``."""
    idx = _index()
    entry = next((e for e in idx["entries"] if e["id"] == review_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail={
            "error": "review_not_found", "review_id": review_id[:128],
            "read_state": idx["read_state"]})
    path: Path = entry["_file"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("performance_reviews: read failed %s: %s", path, exc)
        raise HTTPException(status_code=503, detail={
            "error": "review_unreadable", "review_id": review_id[:128]}) from None
    content_json: Any = None
    content_text: Optional[str] = text
    if entry["format"] == "json":
        try:
            content_json = json.loads(text)
            content_text = None
        except json.JSONDecodeError:
            pass  # served as text: the bytes are the truth
    return {
        "as_of": _iso(datetime.now(timezone.utc)),
        "review": _public(entry),
        "content_text": content_text,
        "content_json": content_json,
    }
