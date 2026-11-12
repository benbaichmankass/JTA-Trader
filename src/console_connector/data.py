"""Payload builders for the console connector. Pure reads of the repo checkout; no writes.

Every payload carries ``as_of`` (when it was built), ``read_state`` (``read`` | ``stale`` |
``could_not_look``) and its ``population`` (what was scanned), so a failed read never comes
back as an empty list (canonical § "Collapsed states").

Sources, all PUBLIC repo files on the host's git checkout (``ict-git-sync`` keeps it at main):
  * checklist rows: ``docs/claude/work/checklist/`` via ``src.runtime.checklist_store``
  * pipeline items: ``docs/claude/work/pipeline/`` via ``scripts.ops.pipeline``
After the WORK-STORE S4 freeze both registers are read from the live work store (GET /api/bot/work/items,
see _load_checklist). The alert ledger is NOT read here until the
connector's sign-in (G1) is live; their sections report ``could_not_look`` with the reason.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROW_FIELDS = ("id", "title", "state", "owner", "lane", "tier", "due_by", "updated_at", "updated_by", "prs",
              "priority_rank", "roadmap", "week_lane", "writeback")
LIVE_STATES = ("in_flight", "blocked", "queued", "landed_unproven")


CLOSED_STATES = ("done", "dropped", "landed_unproven")


def week_start(now: datetime) -> datetime:
    """Start of the current planning week: the latest Wednesday 18:00Z at or before ``now``."""
    base = now.astimezone(timezone.utc).replace(hour=18, minute=0, second=0, microsecond=0)
    base -= timedelta(days=(base.weekday() - 2) % 7)  # Wednesday == 2
    return base - timedelta(days=7) if base > now else base


CLOSED_ROWS_CAP = 15
CLOSED_ROW_KEYS = ("id", "title", "state", "week_lane", "owner", "lane", "due_by", "updated_at",
                   "priority_rank", "roadmap")


def closed_this_week(items: list[dict], now: datetime, today: date) -> dict[str, Any]:
    """Rows closed (done / dropped / landed_unproven) this planning week by updated_at, with counts per
    week_lane and state. Additive: a separate block, never folded into the open sections."""
    start = week_start(now)
    rows, counts = [], {}
    for r in items:
        if r.get("state") not in CLOSED_STATES:
            continue
        age = _age_hours(r.get("updated_at"), now)
        if age is None or age < 0 or (now - timedelta(hours=age)) < start - timedelta(minutes=1):
            continue
        s = _slim(r, today, now)
        rows.append(s)
        lane = str(s.get("week_lane"))
        counts.setdefault(lane, {})
        counts[lane][s["state"]] = counts[lane].get(s["state"], 0) + 1
    rows.sort(key=lambda r: (r.get("week_lane") is None, str(r.get("week_lane")), r["state"], r["id"]))
    total = len(rows)
    # Size budget (console stuck on "Waiting", 2026-11-07: this block was 167 KB / 173 rows and made every work_rows
    # reply ~170 KB): counts stay complete; rows are capped, lane rows first, and slimmed.
    keep = [{k: r.get(k) for k in CLOSED_ROW_KEYS} for r in rows[:CLOSED_ROWS_CAP]]
    return {"read_state": "read",
            "week_start": _iso(start), "week_end": _iso(start + timedelta(days=7)),
            "population": {"rows_scanned": len(items), "closed_rows": total, "rows_returned": len(keep),
                           "rows_cap": CLOSED_ROWS_CAP, "rows_truncated": total > len(keep)},
            "counts_by_week_lane": counts, "rows": keep}


def week_lane_totals(items: list[dict]) -> dict[str, Any]:
    """Every week_lane row in the register (any state): total per lane and per lane x state, so the
    console can show done / landed_unproven against the full lane total."""
    out: dict[str, dict] = {}
    for r in items:
        lane = r.get("week_lane")
        if not lane:
            continue
        d = out.setdefault(str(lane), {"total": 0, "by_state": {}})
        d["total"] += 1
        st = str(r.get("state"))
        d["by_state"][st] = d["by_state"].get(st, 0) + 1
    return out


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


# ── the register after the WORK-STORE S4 freeze ─────────────────────────────────────────────
# Since S4 (#23962, 2026-11-06) the register lives in work_store.db on the trader VM, and the repo's
# row files are a FROZEN EXPORT. This host has no work_store.db, so checklist_store.load() here reads that
# 6-day-old export. When the header says frozen, read the live store through its open read route instead,
# mapped to rows by the repo's own lossless mapping (work_read.checklist_rows / pipeline_result).
WORK_ITEMS_URL = ((os.environ.get("CONSOLE_LIVE_BASE") or "https://ict-bot.duckdns.org").rstrip("/")
                  + "/api/bot/work/items")
STORE_TTL_S = 20.0
_PAGE = 1000


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, method="GET")
    tok = (os.environ.get("DASHBOARD_API_TOKEN") or "").strip()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=25) as resp:  # read-only GET
        return json.loads(resp.read().decode("utf-8"))


#: Injectable for tests: url -> parsed JSON.
STORE_FETCH: Callable[[str], Any] = _http_json


def _fresh(item: dict) -> dict:
    """The row's own updated_at/by live in ``extra`` and are refreshed only when a writer sets them; the
    store's item-level stamp moves on every write. Keep the newer one, so row ages are not days stale."""
    ex = item.get("extra")
    if isinstance(ex, dict) and str(item.get("updated_at") or "") > str(ex.get("updated_at") or ""):
        item = {**item, "extra": {**ex, "updated_at": item.get("updated_at"), "updated_by": item.get("updated_by")}}
    return item


class RemoteWorkStore:
    """The slice of ``WorkStore`` that work_read's mappers use (``list_items``), over GET /api/bot/work/items."""

    def list_items(self, *, kind: str | None = None, due: bool = False, limit: int = 10 ** 7, **_: Any) -> list[dict]:
        out: list[dict] = []
        offset = 0
        while len(out) < limit:
            q = {"limit": _PAGE, "offset": offset}
            if kind:
                q["kind"] = kind
            if due:
                q["due"] = 1
            doc = STORE_FETCH(WORK_ITEMS_URL + "?" + urllib.parse.urlencode(q))
            page = doc.get("items") if isinstance(doc, dict) else None
            if page is None or doc.get("readState") == "could_not_look":
                raise RuntimeError(f"work store read failed: {(doc or {}).get('error') if isinstance(doc, dict) else doc}")
            out.extend(_fresh(i) for i in page)
            if len(page) < _PAGE:
                break
            offset += _PAGE
        return out[:limit]


_STORE_CACHE: TTLCache | None = None


def register_source(repo: Path) -> str:
    """``work_store`` when the register is frozen into the store (S4), else ``files``."""
    from src.runtime import work_read
    return "work_store" if work_read.frozen(repo) and work_read.local_store() is None else "files"


def _load_checklist(repo: Path) -> dict:
    from src.runtime import checklist_store as cs
    if register_source(repo) != "work_store":
        return cs.load(repo=repo)

    def build() -> dict:
        from src.runtime import work_read
        head = json.loads((repo / work_read.CHECKLIST_STORE / work_read.HEADER).read_text(encoding="utf-8"))
        return {**head, "items": work_read.checklist_rows(RemoteWorkStore()), "_source": "work_store"}
    return _store_cache().get("checklist", STORE_TTL_S, build)


def load_pipeline(repo: Path):
    """``pipeline.LoadResult`` from the live store after the freeze, else from the files."""
    from scripts.ops import pipeline as pl
    if register_source(repo) != "work_store":
        return pl.read_log(repo / pl.STORE)

    def build():
        from src.runtime import work_read
        return work_read.pipeline_result(RemoteWorkStore())
    return _store_cache().get("pipeline", STORE_TTL_S, build)


def _store_cache() -> TTLCache:
    global _STORE_CACHE
    if _STORE_CACHE is None:
        _STORE_CACHE = TTLCache()
    return _STORE_CACHE


def register_provenance(repo: Path) -> dict[str, Any]:
    prov = git_provenance(repo)
    src = register_source(repo)
    prov["register_source"] = src
    if src == "work_store":
        prov["register_url"] = WORK_ITEMS_URL
    return prov


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
                            "provenance": register_provenance(repo)}
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
            "sections": {k: v[offset:offset + limit] for k, v in sections.items()},
            "closed_this_week": closed_this_week(items, now, today),
            "week_lane_totals": week_lane_totals(items)}


def inbox(repo: Path, limit: int = 25, today: date | None = None) -> dict[str, Any]:
    """The Inbox tab: decisions waiting on the operator (checklist edges + pipeline asks) and alerts."""
    now = _now()
    today = today or now.date()
    out: dict[str, Any] = {"as_of": _iso(now), "provenance": register_provenance(repo), "sections": {}}

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
        res = load_pipeline(repo)
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
