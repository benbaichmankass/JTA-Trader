"""Payload builders for the console connector. Pure reads of the repo checkout; no writes.

Every payload carries ``as_of`` (when it was built), ``read_state`` (``read`` | ``stale`` |
``could_not_look``) and its ``population`` (what was scanned), so a failed read never comes
back as an empty list (canonical § "Collapsed states").

Sources, all PUBLIC repo files on the host's git checkout (``ict-git-sync`` keeps it at main):
  * checklist rows: ``docs/claude/work/checklist/`` via ``src.runtime.checklist_store``
  * pipeline items: ``docs/claude/work/pipeline/`` via ``scripts.ops.pipeline``
Live-VM sources (alert ledger, work store ``/api/bot/work/items``) are NOT read here until the
connector's sign-in (G1) is live; their sections report ``could_not_look`` with the reason.
"""
from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROW_FIELDS = ("id", "title", "state", "owner", "lane", "tier", "due_by", "updated_at", "updated_by", "prs",
              "priority_rank", "roadmap", "week_lane", "writeback")
LIVE_STATES = ("in_flight", "blocked", "queued", "landed_unproven")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _age_hours(stamp: Any, now: datetime) -> float | None:
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((now - dt).total_seconds() / 3600.0, 1)


def _options(src: Any) -> list[str] | None:
    """Choice labels the source row/item carries (``options`` or ``choices``), else None (rendered as a dash)."""
    if not isinstance(src, dict):
        return None
    for key in ("options", "choices"):
        raw = src.get(key)
        if isinstance(raw, list) and raw:
            out = []
            for o in raw:
                lab = o.get("label") if isinstance(o, dict) else o
                if isinstance(lab, str) and lab.strip():
                    out.append(lab.strip())
            if out:
                return out
    return None


def git_provenance(repo: Path) -> dict[str, Any]:
    """The commit the checkout is at, so the console can show how fresh the register is."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%H %cI"],
                             capture_output=True, text=True, timeout=5, check=True).stdout.split()
        return {"commit": out[0][:12], "committed_at": out[1]}
    except Exception as exc:  # noqa: BLE001  # allow-silent: provenance is reported as unknown with the error, never dropped
        return {"commit": None, "committed_at": None, "error": str(exc)[:200]}


class TTLCache:
    """One shared cache for every viewer: each key is rebuilt at most once per TTL (budget G2)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, Any]] = {}
        self.builds = 0

    def get(self, key: str, ttl_s: float, build: Callable[[], Any]) -> Any:
        with self._lock:
            hit = self._entries.get(key)
            if hit and self._clock() - hit[0] < ttl_s:
                return hit[1]
        value = build()
        with self._lock:
            self._entries[key] = (self._clock(), value)
            self.builds += 1
        return value


def _load_checklist(repo: Path) -> dict:
    from src.runtime import checklist_store as cs
    return cs.load(repo=repo)


def _slim(row: dict, today: date, now: datetime) -> dict:
    from src.runtime import checklist_store as cs
    out = {k: row.get(k) for k in ROW_FIELDS}
    due = cs.effective_due(row)
    out["due_by"] = due.isoformat() if due else None
    out["overdue"] = bool(cs.is_overdue(row, today))
    out["age_hours"] = _age_hours(row.get("updated_at"), now)
    blocked = row.get("blocked_on") if isinstance(row.get("blocked_on"), list) else []
    out["blocked_on"] = [{"kind": e.get("kind"), "ref": e.get("ref"), "what": e.get("what")}
                         for e in blocked if isinstance(e, dict)]
    note = row.get("note")
    out["note_tail"] = note[-240:] if isinstance(note, str) and note else None
    return out


def work_rows(repo: Path, view: str = "all", limit: int = 25, today: date | None = None,
              offset: int = 0) -> dict[str, Any]:
    """Checklist rows for the Work tab: due (overdue, live), in_flight, blocked, queued (with a due date) and
    open_other (queued without a due date, landed_unproven). Rows carry week_lane, roadmap and writeback."""
    now = _now()
    today = today or now.date()
    base: dict[str, Any] = {"as_of": _iso(now), "source": "checklist", "view": view,
                            "provenance": git_provenance(repo)}
    try:
        data = _load_checklist(repo)
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look with the error
        return {**base, "read_state": "could_not_look", "error": str(exc)[:300],
                "population": {"rows_scanned": None}, "sections": {}}
    items = [r for r in data.get("items", []) if isinstance(r, dict)]
    slim = [_slim(r, today, now) for r in items]
    live = [r for r in slim if r["state"] in LIVE_STATES]
    sections = {
        "due": sorted([r for r in live if r["overdue"]], key=lambda r: (r["due_by"] or "", r["id"])),
        "in_flight": sorted([r for r in live if r["state"] == "in_flight"],
                            key=lambda r: -(r["age_hours"] or 0)),
        "blocked": sorted([r for r in live if r["state"] == "blocked"], key=lambda r: r["id"]),
        "queued": sorted([r for r in live if r["state"] == "queued" and r["due_by"] and not r["overdue"]],
                         key=lambda r: (r["due_by"], r.get("priority_rank") or 9999, r["id"])),
        # every other live row, so the console Roadmap card is complete: queued WITHOUT a due date, and
        # landed_unproven (neither is in due / in_flight / blocked / queued above)
        "open_other": sorted([r for r in live if r["state"] not in ("in_flight", "blocked") and not r["overdue"]
                              and not (r["state"] == "queued" and r["due_by"])], key=lambda r: r["id"]),
    }
    if view != "all":
        if view not in sections:
            return {**base, "read_state": "read", "error": f"unknown view {view!r}; use all|"
                    + "|".join(sections), "population": {"rows_scanned": len(items)}, "sections": {}}
        sections = {view: sections[view]}
    offset = max(0, int(offset or 0))
    counts = {k: len(v) for k, v in sections.items()}
    truncated = {k: len(v) > offset + limit for k, v in sections.items()}
    # next_offset per section: where the next page starts, or None when the section is complete
    next_offset = {k: (offset + limit if len(v) > offset + limit else None) for k, v in sections.items()}
    return {**base, "read_state": "read",
            "population": {"rows_scanned": len(items), "live_rows": len(live), "limit_per_section": limit,
                           "offset": offset, "counts": counts, "truncated": truncated,
                           "next_offset": next_offset},
            "sections": {k: v[offset:offset + limit] for k, v in sections.items()}}


def inbox(repo: Path, limit: int = 25, today: date | None = None) -> dict[str, Any]:
    """The Inbox tab: decisions waiting on the operator (checklist edges + pipeline asks) and alerts."""
    now = _now()
    today = today or now.date()
    out: dict[str, Any] = {"as_of": _iso(now), "provenance": git_provenance(repo), "sections": {}}

    # 1. checklist rows blocked on an operator decision
    try:
        data = _load_checklist(repo)
        rows = [r for r in data.get("items", []) if isinstance(r, dict)]
        edges = []
        for r in rows:
            if r.get("state") in ("done", "dropped"):
                continue
            for e in r.get("blocked_on") or []:
                if isinstance(e, dict) and e.get("kind") == "operator_decision":
                    edges.append({"source": "checklist", "id": r.get("id"), "title": r.get("title"),
                                  "state": r.get("state"), "ref": e.get("ref"), "what": e.get("what"),
                                  "due_by": r.get("due_by"), "age_hours": _age_hours(r.get("updated_at"), now),
                                  "options": _options(e) or _options(r)})
        out["sections"]["decisions_checklist"] = {"read_state": "read", "population": {"rows_scanned": len(rows)},
                                                  "count": len(edges), "items": edges[:limit]}
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the error
        out["sections"]["decisions_checklist"] = {"read_state": "could_not_look", "error": str(exc)[:300],
                                                  "population": {"rows_scanned": None}, "count": None, "items": []}

    # 2. pipeline items that declare next_action: ask_operator
    try:
        from scripts.ops import pipeline as pl
        res = pl.read_log(repo / pl.STORE)
        asks = []
        for item in res.items.values():
            if item.get("next_action") != "ask_operator" or item.get("state") in pl.TERMINAL_STATES:
                continue
            due_when = item.get("due_when") or {}
            try:
                due = bool(pl.is_due(item, today))
            except Exception:  # noqa: BLE001  # allow-silent: due unknown is reported as None
                due = None
            asks.append({"source": "pipeline", "id": item.get("id"), "title": item.get("what"),
                         "state": item.get("state"), "routed_to": item.get("routed_to"),
                         "clears_when": due_when.get("clears_when"), "due": due,
                         "options": _options(item)})
        asks.sort(key=lambda a: (a["due"] is not True, str(a["id"])))
        out["sections"]["asks_pipeline"] = {
            "read_state": "read" if res.healthy else "stale",
            "population": {"items_scanned": len(res.items), "unreadable": len(res.unreadable)},
            "count": len(asks), "items": asks[:limit]}
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the error
        out["sections"]["asks_pipeline"] = {"read_state": "could_not_look", "error": str(exc)[:300],
                                            "population": {"items_scanned": None}, "count": None, "items": []}

    # 3. alerts: live-VM alert ledger, not read until connector sign-in (G1) is live
    out["sections"]["alerts"] = {"read_state": "could_not_look", "count": None, "items": [],
                                 "population": {"rows_scanned": None},
                                 "reason": "alert ledger is on the live VM; served once the connector's sign-in (G1) is live"}
    return out


def work_items() -> dict[str, Any]:
    """Work-store items (WORK-STORE S1, /api/bot/work/items). Not built yet: say so, never return []."""
    return {"as_of": _iso(_now()), "read_state": "could_not_look", "count": None, "items": [],
            "population": {"rows_scanned": None},
            "reason": "the work store route /api/bot/work/items (WORK-STORE S1) is not live yet; "
                      "the Work tab reads checklist rows (work_rows) meanwhile"}
