#!/usr/bin/env python3
# wiring: scripts/ops/work_digest_now.py (the MANAGER update, ict-work-digest.timer)
"""WORK section of the manager update — what was DONE, VERIFIED, BLOCKED, what
is COMING UP and what DIDN'T WORK, each line ``row id — one-line why``.

Operator, 2026-10-11 (checklist row ``TELEGRAM-CHANNELS``, close paraphrase):
the WORK section must carry the same level of detail as the Research queue
section — brief enough to stay relevant, informative enough to be useful.

POPULATION. The checklist store (``src/runtime/checklist_store.load`` — every
row, its ``state``), the follow-through pipeline (``scripts/ops/pipeline.load``
— every item's ``state`` + ``terminal_reason``) and ``git log`` of the checkout
this runs in (the VM clone, synced from ``main`` every ~5 min) for merged PRs
and reverts.

BUCKETS map 1:1 onto the checklist's own declared state meanings
(``states`` in the header), so nothing here re-defines a state:

* ✅ SHIPPED      a row moved to ``landed_unproven`` (merged; effect NOT yet observed)
* 🔬 VERIFIED     a row moved to ``done`` (merged AND its effect observed), or a
                 pipeline item closed ``done``
* ⛔ BLOCKED      every row in ``blocked`` now (🆕 = newly blocked), with ``blocked_on``
* ❌ DIDN'T WORK  rows moved to ``dropped``, pipeline items ``killed`` (with
                 their ``terminal_reason``), and ``Revert`` commits
* ⏭ COMING UP    rows ``in_flight`` now, then ``queued`` (most recently touched first)

CURSOR (``runtime_logs/work_section_cursor.json``) holds the previous snapshot;
"new" is the diff, advanced only after the update was enqueued (``commit``).
With NO cursor the section says so and reports a fixed 24h window using each
row's ``updated_at``. A source that cannot be read says *could not look* — never
"nothing new". Missing fields render "—".
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CURSOR = REPO_ROOT / "runtime_logs" / "work_section_cursor.json"
FIRST_RUN_WINDOW_H = 24
MAX_PER_BUCKET = 8
#: SHIPPED / VERIFIED are history, rendered LAST and capped tighter: Telegram's
#: 4096-char trim drops the TAIL, and on 2026-10-11 it cut a Blocked item
#: because ten Shipped/Verified lines sat ahead of it (TELEGRAM-CHANNELS-3).
MAX_PER_BUCKET_HISTORY = 5
_WHY = 100

SHIPPED, VERIFIED, BLOCKED, FAILED, UPCOMING = (
    "shipped", "verified", "blocked", "didnt_work", "coming_up")


def _dash(v: Any) -> str:
    return "—" if v in (None, "", []) else str(v)


def _short(text: Any, n: int = _WHY) -> str:
    t = " ".join(str(text or "").split())
    return (t[: n - 1] + "…") if len(t) > n else (t or "—")


def _last_note(note: Any) -> str:
    """The most recent ``[stamp …] text`` fragment of a row note, header dropped."""
    s = str(note or "")
    i = s.rfind("[")
    frag = s[i:] if i >= 0 else s
    frag = re.sub(r"^\[[^\]]*\]\s*", "", frag)
    return _short(frag or s)


def _obs(o: Any) -> Optional[str]:
    """A row's observed OUTCOME as one line, or ``None``. A dict's ``what`` is
    the check that WOULD close the row, not what was seen, so it is not an
    outcome (the VERIFIED line then falls back to the row's last note)."""
    if isinstance(o, dict):
        o = o.get("observed") or o.get("result")
    return _short(o) if o else None


def _parse_ts(v: Any) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return t if (t is None or t.tzinfo) else t.replace(tzinfo=timezone.utc)


def snapshot(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Read the checklist + pipeline. Never raises; failures are STATED."""
    rows: dict[str, dict] = {}
    checklist_state = "read"
    try:
        sys.path.insert(0, str(root))
        from src.runtime import checklist_store  # noqa: PLC0415

        for r in checklist_store.load().get("items") or []:
            rows[str(r.get("id"))] = {
                "state": _dash(r.get("state")), "title": _short(r.get("title")),
                "blocked_on": [str(x) for x in (r.get("blocked_on") or [])],
                "why": _last_note(r.get("note")),
                "observation": _obs(r.get("observation")),
                "updated_at": r.get("updated_at")}
    except Exception as exc:  # noqa: BLE001 — stated, not hidden
        checklist_state = f"unreadable ({type(exc).__name__})"
    items: dict[str, dict] = {}
    pipeline_state = "read"
    try:
        from scripts.ops import pipeline  # noqa: PLC0415

        res = pipeline.load()
        its = res.items.values() if isinstance(res.items, dict) else res.items
        for it in its:
            items[str(it.get("id"))] = {
                "state": _dash(it.get("state")),
                "reason": _short(it.get("terminal_reason") or it.get("what"))}
    except Exception as exc:  # noqa: BLE001
        pipeline_state = f"unreadable ({type(exc).__name__})"
    return {"rows": rows, "items": items, "checklist_state": checklist_state,
            "pipeline_state": pipeline_state}


def read_cursor(path: Path = CURSOR) -> Optional[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and "rows" in d and "items" in d else None
    except (OSError, ValueError):
        return None


def commit(snap: dict, path: Path = CURSOR, now: Optional[datetime] = None) -> None:
    """Advance the cursor. Call ONLY after the update was enqueued. A source
    that was not read keeps its previous cursor (never diffed against empty)."""
    prev = read_cursor(path) or {}
    payload = {"at": (now or datetime.now(timezone.utc)).isoformat(),
               "rows": {k: v["state"] for k, v in snap["rows"].items()}
               if snap["checklist_state"] == "read" else prev.get("rows", {}),
               "items": {k: v["state"] for k, v in snap["items"].items()}
               if snap["pipeline_state"] == "read" else prev.get("items", {})}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"work-section: WARNING could not write cursor: {exc}")


def git_window(since: datetime, root: Path = REPO_ROOT) -> dict[str, Any]:
    """Merged-PR count + revert subjects since *since*. ``None`` = could not look."""
    try:
        out = subprocess.run(
            ["git", "log", f"--since={since.isoformat()}", "--format=%s", "HEAD"],
            cwd=root, capture_output=True, text=True, check=True, timeout=30).stdout
    except (subprocess.SubprocessError, OSError):
        return {"merged_prs": None, "reverts": None}
    subs = out.splitlines()
    prs = {m.group(1) for s in subs if (m := re.search(r"\(#(\d+)\)\s*$", s))}
    reverts = [_short(s, 90) for s in subs if s.startswith("Revert")]
    return {"merged_prs": len(prs), "reverts": reverts}


def build(prev: Optional[dict] = None, now: Optional[datetime] = None,
          snap: Optional[dict] = None, git: Optional[dict] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    snap = snap if snap is not None else snapshot()
    since = _parse_ts((prev or {}).get("at")) or now - timedelta(hours=FIRST_RUN_WINDOW_H)
    git = git if git is not None else git_window(since)
    b: dict[str, list[str]] = {k: [] for k in (SHIPPED, VERIFIED, BLOCKED, FAILED, UPCOMING)}
    prow = (prev or {}).get("rows") or {}
    pitem = (prev or {}).get("items") or {}

    def moved(rid: str, r: dict, to: str) -> bool:
        if r["state"] != to:
            return False
        if prev is not None:
            return prow.get(rid) not in (None, to) or (rid not in prow and bool(prow))
        t = _parse_ts(r.get("updated_at"))
        return bool(t and t >= since)

    for rid, r in sorted(snap["rows"].items()):
        if moved(rid, r, "landed_unproven"):
            b[SHIPPED].append(f"{rid} — {r['title']}")
        if moved(rid, r, "done"):
            b[VERIFIED].append(f"{rid} — {r.get('observation') or r['why']}")
        if moved(rid, r, "dropped"):
            b[FAILED].append(f"{rid} (dropped) — {r['why']}")
        if r["state"] == "blocked":
            new = "🆕 " if (prev is not None and prow.get(rid) != "blocked") else ""
            on = ", ".join(r["blocked_on"]) if r["blocked_on"] else r["why"]
            b[BLOCKED].append(f"{new}{rid} — on {_dash(on)}")
    if prev is not None and pitem and snap["pipeline_state"] == "read":
        for iid, it in sorted(snap["items"].items()):
            was = pitem.get(iid)
            if it["state"] == was:
                continue
            if it["state"] == "done":
                b[VERIFIED].append(f"{iid} (pipeline) — {it['reason']}")
            elif it["state"] == "killed":
                b[FAILED].append(f"{iid} (killed) — {it['reason']}")
    for s in git.get("reverts") or []:
        b[FAILED].append(f"revert — {s}")
    live = [(rid, r) for rid, r in snap["rows"].items() if r["state"] == "in_flight"]
    queued = sorted(((rid, r) for rid, r in snap["rows"].items() if r["state"] == "queued"),
                    key=lambda x: str(x[1].get("updated_at") or ""), reverse=True)
    b[UPCOMING] += [f"▶ {rid} — {r['title']}" for rid, r in sorted(live)]
    b[UPCOMING] += [f"· {rid} — {r['title']}" for rid, r in queued]
    states: dict[str, int] = {}
    for r in snap["rows"].values():
        states[r["state"]] = states.get(r["state"], 0) + 1
    return {"mode": "since_last_update" if prev is not None else "first_run_window",
            "since": since.isoformat(), "buckets": b, "states": states,
            "checklist_state": snap["checklist_state"],
            "pipeline_state": snap["pipeline_state"], "git": git, "snapshot": snap}


#: Render order: what needs attention first (Blocked, Didn't work), then what
#: is in flight / next, then the history (Shipped, Verified).
_LABELS = ((BLOCKED, "⛔ BLOCKED now"),
           (FAILED, "❌ DIDN'T WORK — dropped / killed / reverted"),
           (UPCOMING, "⏭ IN FLIGHT / NEXT — ▶ in flight, · queued"),
           (SHIPPED, "✅ SHIPPED — merged, effect not yet observed"),
           (VERIFIED, "🔬 VERIFIED / PASSED — outcome observed"))
_CAPS = {SHIPPED: MAX_PER_BUCKET_HISTORY, VERIFIED: MAX_PER_BUCKET_HISTORY}


def headline(d: dict) -> str:
    if d["checklist_state"] != "read":
        return "🛠 work: ⚠️ checklist NOT READ — could not look"
    b = d["buckets"]
    n_live = sum(1 for x in b[UPCOMING] if x.startswith("▶"))
    return (f"🛠 work: {len(b[SHIPPED])} shipped · {len(b[VERIFIED])} verified · "
            f"{len(b[FAILED])} didn't work · {len(b[BLOCKED])} blocked · {n_live} in flight")


def render_body(d: dict) -> str:
    L: list[str] = []
    if d["mode"] == "first_run_window":
        L.append(f"No prior cursor — showing rows touched in the last {FIRST_RUN_WINDOW_H}h "
                 "(fixed window). Pipeline transitions start next update.")
    else:
        L.append(f"New since the last update ({_dash(d['since'])[:16]}Z).")
    for src in ("checklist_state", "pipeline_state"):
        if d[src] != "read":
            L.append(f"⚠️ {src.split('_')[0]} {d[src]} — we could not look; NOT 'nothing new'.")
    for key, label in _LABELS:
        items = d["buckets"][key]
        if not items:
            L.append(f"{label}: none")
            continue
        L.append(f"{label} ({len(items)}):")
        cap = _CAPS.get(key, MAX_PER_BUCKET)
        L += [f"  {x}" for x in items[:cap]]
        if len(items) > cap:
            L.append(f"  … +{len(items) - cap} more")
    g = d["git"]
    L.append(f"Merged PRs in window: {_dash(g.get('merged_prs'))}"
             + ("" if g.get("reverts") is not None else " (git log could not run)"))
    st = d["states"]
    L.append("Checklist now: " + (" · ".join(f"{k} {v}" for k, v in sorted(st.items())) or "—")
             + f" (of {sum(st.values())} rows)")
    return "\n".join(L)
