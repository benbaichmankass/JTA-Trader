#!/usr/bin/env python3
# wiring: manual-only - run by the manager's decisions-page refresh routine (a Claude trigger), which batch-writes the output to the artifact; no workflow consumes it
"""Builders for the manager's decisions page (claude.ai artifact; the twice-daily refresh routine writes them).

The page reads four collections from its artifact database. This script produces each one as JSON files ready for an
``ArtifactData`` batch write (``file_path`` entries), in the SAME shape the page already renders:

  workplan/p0..pN   {"gen", "seq", "total", "chunk"}  -- one JSON document split into 170 000-char chunks:
                    {"generated_at", "plan", "store_total", "rows": [...], "added": [...]}
  lanestatus/current {"json": "<string>"}            -- {"as_of", "note", "lanes": [{name, headline, moved_today,
                    working_now, stuck_or_waiting, next}]}
  rdreg/rp0..rpN    chunked like workplan            -- a slimmed comms/research/rd_registry.json
  plans/current     {"json": "<string>"}            -- {"generated_at", "plan_source", "plan_updated", "plan",
                    "frontier", "tracks"}

    python3 scripts/ops/decisions_page_build.py all --out /tmp/dp          # every collection
    python3 scripts/ops/decisions_page_build.py workplan --out /tmp/dp      # one collection

Every file lands at ``<out>/<collection>/<doc_id>.json``, and ``<out>/manifest.json`` lists them (collection, doc_id,
path) so the routine can batch-write and delete any extra p/rp docs left from a longer previous build.

PURE READS: the committed repo files plus the public ``/api/bot/work/items`` read (paged, 1000 per page). No secrets,
account ids or balances are copied: work-item fields are titles/notes/states the page already shows, and the
registry slim keeps names, stages, verdicts and counts only. Read failures are named in the output (``read_state``),
never rendered as an empty page.

Rebuilt 2026-11-15 (manager ask): the previous builders lived in a manager's scratchpad and were lost with that
container. Shapes mirror the collections as they stood at 2026-11-15T05:20Z (workplan gen 2026-11-14T17:11Z, rdreg gen
2026-11-12T22:53:10Z, plans gen 2026-11-14T17:11Z, lanestatus as_of 2026-11-14T17:12Z).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
CHUNK = 170_000
NOTE_TAIL = 420
ITEMS_URL = "https://ict-bot.duckdns.org/api/bot/work/items"
TRACKS = {"S": "AI-trader spine", "R": "Regime / when to trade", "X": "Exit and take-profit heads",
          "P": "Serve parity and producers", "D": "Data, labels, hygiene", "N": "New ideas / information classes",
          "F": "Frontier"}
FRONTIER_F_KEYS = ("family", "source", "why", "consumer", "baseline", "est_cost", "next_step", "p_pass")
LANES = (  # (display name, owner substrings that put a row in the lane)
    ("ML-PRIMARY (ML, standing)", ("AM-ML", "FRONTIER", "ML-PRIMARY")),
    ("AM-OPS (general)", ("AM-OPS",)),
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


# ── reads ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def fetch_items(url: str = ITEMS_URL, page: int = 1000, timeout: float = 60.0) -> Tuple[List[dict], str]:
    """Every work item, paged. Returns ``(items, read_state)``; a failed page is named, never an empty store."""
    items: List[dict] = []
    offset = 0
    total = None
    while True:
        try:
            with urllib.request.urlopen(f"{url}?limit={page}&offset={offset}", timeout=timeout) as r:  # noqa: S310
                doc = json.loads(r.read().decode())
        except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as read_state, the page never shows a silent empty store
            return items, f"could_not_look: {type(exc).__name__}: {exc}"[:200]
        got = doc.get("items") or []
        items += got
        total = doc.get("total", total)
        offset += len(got)
        if not got or (total is not None and offset >= total):
            return items, "read"


def _am(owner: Any) -> str:
    m = re.search(r"\bAM-[A-Z]+\b", str(owner or ""))
    return m.group(0) if m else str(owner or "")


def _row(it: Optional[dict]) -> Dict[str, Any]:
    it = it or {}
    note = str((it.get("extra") or {}).get("note") or it.get("note") or "")
    return {"state": it.get("state"), "title": it.get("title"), "owner": it.get("owner"),
            "updated_at": it.get("updated_at"), "prs": list(it.get("prs") or []),
            "terminal": it.get("terminal_reason"), "note": note[-NOTE_TAIL:]}


# ── workplan ──────────────────────────────────────────────────────────────────────────────────────────────────────
def latest_workplan(root: Path = REPO, pinned: Optional[Path] = None) -> Optional[Path]:
    """The weekly plan to read: ``pinned`` (``--plan``) when given, else the newest ``docs/plans/weekly/<week>/``.
    The choice is printed to stderr and recorded as the payload's ``plan`` field, so a fallback is never silent."""
    if pinned is not None:
        chosen: Optional[Path] = pinned
        how = "pinned (--plan)"
    else:
        # provenance: latest_workplan — newest weekly plan by ISO week directory name (YYYY-MM-DD sorts by date);
        # the path is printed below and written into the payload's "plan" field
        weeks = sorted(p for p in (root / "docs/plans/weekly").glob("*/WORKPLAN.md"))
        chosen, how = (weeks[-1] if weeks else None), f"newest of {len(weeks)} weekly plan(s)"
    print(f"decisions_page_build: workplan source = {chosen} ({how})", file=sys.stderr)
    return chosen


def parse_workplan(text: str) -> List[Dict[str, Any]]:
    """Rows of WORKPLAN.md §3 (surge tables), §4 (throttle lists), §5 (standing) and §6 (landed_unproven)."""
    rows: List[Dict[str, Any]] = []
    section, am, slot = "", "", ""
    for line in text.splitlines():
        h2 = re.match(r"^## (\d+)\.", line)
        if h2:
            section, am, slot = h2.group(1), "", ""
            continue
        h3 = re.match(r"^### (AM-[A-Z]+)", line)
        if h3 and section == "3":
            am = h3.group(1)
            continue
        if section == "3":
            d = re.match(r"^\*\*(\d{4}-\d{2}-\d{2}|[0-9/-]+)\*\*\s*$", line.strip())
            if d:
                slot = d.group(1)
                continue
            m = re.match(r"^\|\s*(\d+)\s*\|\s*([A-Z0-9][A-Z0-9_.:-]+)\s*\|\s*([SML]?)\s*\|\s*(.*?)\s*\|\s*$", line)
            if m and am:
                rows.append({"id": m.group(2), "am": am, "slot": slot, "bucket": "surge", "n": m.group(1),
                             "size": m.group(3), "what": m.group(4)})
        elif section == "4":
            m = re.match(r"^\*\*(AM-[A-Z]+)\s*\(\d+\):\*\*\s*(.+)$", line.strip())
            if m:
                for n, rid in enumerate([x.strip() for x in m.group(2).split(",") if x.strip()], 1):
                    rows.append({"id": rid, "am": m.group(1), "slot": _throttle_slot(text),
                                 "bucket": "throttle", "n": str(n), "size": "", "what": ""})
        elif section == "5":
            for rid, who in re.findall(r"([A-Z0-9][A-Z0-9_.:-]{3,})\s*\((AM-[A-Z]+)\)", line):
                rows.append({"id": rid, "am": who, "slot": "standing", "bucket": "standing", "n": "", "size": "",
                             "what": ""})
        elif section == "6":
            m = re.match(r"^\|\s*([A-Z0-9][A-Z0-9_.:-]+)\s*\|\s*([A-Z]+)\s*\|\s*(.*?)\s*\|\s*$", line)
            if m and m.group(1) not in ("row",):
                rows.append({"id": m.group(1), "am": f"AM-{m.group(2)}", "slot": "observe",
                             "bucket": "landed_unproven", "n": "", "size": "", "what": m.group(3)})
    seen, out = set(), []
    for r in rows:  # first mention wins (a row listed twice keeps its surge slot)
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


def _throttle_slot(text: str) -> str:
    m = re.search(r"^## 4\. Throttle \(after the surge; due ([0-9/ -]+)", text, re.M)
    return m.group(1).replace(" ", "") if m else "throttle"


def build_workplan(items: List[dict], plan_path: Optional[Path], read_state: str) -> Dict[str, Any]:
    by_id = {i.get("id"): i for i in items}
    text = plan_path.read_text() if plan_path else ""
    rows = []
    for r in parse_workplan(text):
        it = by_id.get(r["id"])
        rr = {**r, **_row(it)}
        if not rr["what"]:
            rr["what"] = rr.get("title") or ""
        rows.append(rr)
    week = plan_path.parent.name if plan_path else ""
    planned = {r["id"] for r in rows}
    added = []
    for it in sorted(items, key=lambda i: str(i.get("created_at") or ""), reverse=True):
        if it.get("id") in planned or str(it.get("created_at") or "") < week or it.get("kind") not in (None, "build"):
            continue
        rw = _row(it)
        added.append({"id": it.get("id"), "am": _am(it.get("owner")) or rw["owner"], "slot": "added today",
                      "bucket": "added", "n": "", "size": "", "what": it.get("title") or "", "state": rw["state"],
                      "owner": rw["owner"], "updated_at": rw["updated_at"], "prs": rw["prs"], "note": rw["note"]})
    return {"generated_at": _now(), "plan": str(plan_path.relative_to(REPO)) if plan_path else None,
            "store_total": len(items), "read_state": read_state, "rows": rows, "added": added}


# ── lane status ───────────────────────────────────────────────────────────────────────────────────────────────────
def _status_word(it: dict) -> str:
    s = it.get("state")
    return {"done": "observed", "landed_unproven": "merged/deployed, NOT observed", "in_flight": "in flight",
            "blocked": "blocked", "queued": "queued"}.get(s, str(s))


def build_lanestatus(items: List[dict], read_state: str, today: Optional[str] = None) -> Dict[str, Any]:
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lanes = []
    for name, keys in LANES:
        mine = [i for i in items if any(k in str(i.get("owner") or "") for k in keys)]
        moved = [i for i in mine if str(i.get("updated_at") or "").startswith(today)
                 and i.get("state") in ("done", "landed_unproven")]
        working = [i for i in mine if i.get("state") == "in_flight"]
        stuck = [i for i in mine if i.get("state") == "blocked"]
        nxt = sorted((i for i in mine if i.get("state") == "queued"),
                     key=lambda i: (i.get("priority_rank") if i.get("priority_rank") is not None else 99,
                                    str(i.get("due_at") or "9999")))

        def line(i: dict) -> str:
            prs = ", ".join(f"#{p}" for p in (i.get("prs") or []))
            return f"{i.get('id')}: {_status_word(i)}{' (' + prs + ')' if prs else ''}: {str(i.get('title') or '')[:140]}"

        n_obs = sum(1 for i in moved if i.get("state") == "done")
        lanes.append({
            "name": name,
            "headline": (f"{len(moved)} moved today ({n_obs} observed, {len(moved) - n_obs} merged but not yet "
                         f"observed); {len(working)} in flight; {len(stuck)} blocked."),
            "moved_today": [line(i) for i in moved][:12],
            "working_now": [line(i) for i in working][:10],
            "stuck_or_waiting": [line(i) for i in stuck][:8],
            "next": [line(i) for i in nxt][:6],
        })
    return {"as_of": _now(), "read_state": read_state,
            "note": ("Two lanes: ML-PRIMARY (ML, standing) and AM-OPS (general: ops, trading, devops). PIPELINE-MAP "
                     "finished and was archived 2026-11-15 02:00Z. 'observed' = done with a live observation; "
                     "'merged/deployed, NOT observed' = landed_unproven. Built from the work store by "
                     "scripts/ops/decisions_page_build.py."),
            "lanes": lanes}


# ── R&D registry (slim) ───────────────────────────────────────────────────────────────────────────────────────────
def _cut(v: Any, n: int) -> Any:
    """The old slim's text cap: longer than ``n`` keeps n-1 chars plus an ellipsis."""
    return v[: n - 1] + "\u2026" if isinstance(v, str) and len(v) > n else v


def _slim_idea(i: dict) -> Dict[str, Any]:
    lr = i.get("latest_result") or None
    s0 = i.get("stage0_evidence") or None
    ev = None
    if s0 and s0.get("coverage_state") == "measured":
        ev = {"r": s0.get("expectancy_r_oos"), "n": s0.get("n_trades_oos"),
              "f": (f"{s0.get('folds_positive')}/{s0.get('folds')}" if s0.get("folds") is not None else None)}
    links = i.get("links") or {}
    prog = i.get("programme")
    if isinstance(prog, list):
        prog = ", ".join(str(x) for x in prog)
    last = i.get("last_activity")
    return {"id": i.get("id"), "name": _cut(i.get("name"), 160), "track": i.get("track"), "kind": i.get("kind"),
            "prog": prog or "", "stage": i.get("stage"), "why": _cut(i.get("stage_reason"), 260),
            "next": _cut(i.get("next_step"), 260) or "", "c": i.get("counts"),
            "lr": ({"u": lr.get("unit"), "v": lr.get("verdict"), "d": str(lr.get("date") or "")[:10],
                    "n": lr.get("n"), "t": _cut(lr.get("title"), 200)} if lr else None),
            "books": i.get("books") or None, "last": str(last)[:16] if last else None,
            "link": next(iter(links.values()), None) if isinstance(links, dict) else None,
            "open": list(i.get("open_units") or [])[:4], "ev": ev}


def build_rdreg(path: Path = REPO / "comms/research/rd_registry.json") -> Dict[str, Any]:
    try:
        full = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001  # allow-silent: named in read_state, never an empty registry
        return {"generated_at": None, "read_state": f"could_not_look: {exc}"[:200], "stages": [], "summary": None,
                "changed": None, "rules": [], "ideas": []}
    summ = full.get("summary") or {}
    ch = summ.get("changed_last_7d") or {}
    return {"generated_at": full.get("generated_at"), "stages": full.get("stages") or [],
            "summary": {k: summ.get(k) for k in ("ideas", "per_track", "per_stage_per_track")},
            "changed": {"basis": ch.get("basis"), "count": ch.get("count"), "items": list(ch.get("items") or [])[:40]},
            "rules": full.get("stage_rules") or [],
            "ideas": [_slim_idea(i) for i in full.get("ideas") or []]}


# ── plans ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def build_plans(items: List[dict], root: Path = REPO) -> Dict[str, Any]:
    import yaml

    by_id = {i.get("id"): i for i in items}
    src = root / "docs/plans/ml-dev-plan.yaml"
    if not src.exists():
        src = root / "docs/plans/ml-plan-items.yaml"
    doc = yaml.safe_load(src.read_text()) or {}
    plan = []
    for ln in doc.get("lines") or doc.get("items") or []:
        ref = ln.get("row") or ln.get("ref") or ln.get("id")
        it = by_id.get(ref) or {}
        plan.append({"id": ln.get("id"), "track": ln.get("track"), "family": ln.get("family"),
                     "title": ln.get("subject") or ln.get("title"), "plan_state": ln.get("state"),
                     "ref": ref, "ref_state": it.get("state"), "close": ln.get("close") or "",
                     "steps": ln.get("steps"), "next": ln.get("next"), "owner": ln.get("owner"),
                     "updated": it.get("updated_at"), "tier": it.get("tier")})
    frontier = []
    for it in sorted((i for i in items if str(i.get("id") or "").startswith("FRONTIER-Q-")), key=lambda i: i["id"]):
        ex = it.get("extra") or {}
        fr = ex.get("frontier") or {}
        frontier.append({"id": it["id"], "title": it.get("title"), "state": fr.get("state") or "idea",
                         "store_state": it.get("state"), "owner": it.get("owner"), "updated": it.get("updated_at"),
                         "note": str(ex.get("note") or "")[:NOTE_TAIL],
                         "f": {k: fr.get(k) for k in FRONTIER_F_KEYS}})
    return {"generated_at": _now(), "plan_source": str(src.relative_to(root)), "plan_updated": str(doc.get("updated")),
            "plan": plan, "frontier": frontier, "tracks": TRACKS}


# ── output ────────────────────────────────────────────────────────────────────────────────────────────────────────
def chunk_docs(payload: Dict[str, Any], prefix: str, gen: str) -> List[Tuple[str, Dict[str, Any]]]:
    s = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    parts = [s[i:i + CHUNK] for i in range(0, len(s), CHUNK)] or [""]
    return [(f"{prefix}{n}", {"gen": gen, "seq": n, "total": len(parts), "chunk": p}) for n, p in enumerate(parts)]


def write_out(out: Path, collection: str, docs: Iterable[Tuple[str, Dict[str, Any]]], manifest: List[dict]) -> None:
    d = out / collection
    d.mkdir(parents=True, exist_ok=True)
    for doc_id, data in docs:
        p = d / f"{doc_id}.json"
        p.write_text(json.dumps(data, ensure_ascii=False))
        manifest.append({"collection": collection, "doc_id": doc_id, "path": str(p)})


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=("all", "workplan", "lanestatus", "rdreg", "plans"))
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--items-json", type=Path, help="read work items from this file instead of the API (tests)")
    ap.add_argument("--plan", type=Path, help="pin the WORKPLAN.md to read (default: the newest weekly plan, printed)")
    a = ap.parse_args(argv)
    if a.items_json:
        items, rs = json.loads(a.items_json.read_text()), "read (file)"
    else:
        items, rs = fetch_items()
    manifest: List[dict] = []
    if a.what in ("all", "workplan"):
        wp = build_workplan(items, latest_workplan(pinned=a.plan), rs)
        write_out(a.out, "workplan", chunk_docs(wp, "p", wp["generated_at"]), manifest)
    if a.what in ("all", "lanestatus"):
        write_out(a.out, "lanestatus", [("current", {"json": json.dumps(build_lanestatus(items, rs))})], manifest)
    if a.what in ("all", "rdreg"):
        rd = build_rdreg()
        write_out(a.out, "rdreg", chunk_docs(rd, "rp", str(rd.get("generated_at"))), manifest)
    if a.what in ("all", "plans"):
        write_out(a.out, "plans", [("current", {"json": json.dumps(build_plans(items))})], manifest)
    (a.out / "manifest.json").write_text(json.dumps({"built_at": _now(), "items_read_state": rs,
                                                     "store_total": len(items), "docs": manifest}, indent=1))
    print(json.dumps({"items_read_state": rs, "store_total": len(items),
                      "docs": [f"{m['collection']}/{m['doc_id']}" for m in manifest]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
