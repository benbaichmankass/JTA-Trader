#!/usr/bin/env python3
# wiring: called by .github/workflows/desk-decisions-mirror.yml after the mirror (a failure is a warning, never a stop).
"""DESK-14 -- the feed-gap alert path for the desk's use of outside information.

Operator rule (2026-10-27, binding): every use of outside information by the desk (web search, open-source
context beyond the packet) is logged point-in-time, flows INTO the ML training corpus, and raises a feed-gap
alert naming the data feed we lack. This module is the alert half. It reads

* ``comms/desk/decisions.jsonl``  -- ``external_context.items[]`` on each desk row (the desk wake, written by
  ``.claude/skills/trading-desk/desk_write.py``), and
* ``comms/live_review/short_hold/feed_gaps.jsonl`` -- the short-hold lane's feed-gap lines, when present on
  this checkout (the lane writes them to ``live-review/rows``; mirroring them to main is a follow-up),

and writes ``comms/desk/feed_gaps.jsonl`` (one line per (decision, feed_gap), idempotent on ``gap_key``). For each
feed-gap NAME seen for the first time it files ONE item in the follow-through pipeline
(``scripts/ops/pipeline.py``; it reaches the operator's brief section 0 once due). That is the existing route; no
new gate, no halt (Prime Directive rule 7): a failure to read or file is printed and the run exits 0.

``--report`` prints the gaps ranked by how often they were decisive. Exit: 0 ok.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline

DECISIONS = Path("comms/desk/decisions.jsonl")
SHORT_HOLD_GAPS = Path("comms/live_review/short_hold/feed_gaps.jsonl")
STORE = Path("comms/desk/feed_gaps.jsonl")
REF_PREFIX = "desk-feed-gap:"
SESSION_REF = "desk-feed-gaps"


def _rows(path: Path) -> list[dict]:
    out = []
    if path.is_file():
        for ln in path.read_text().splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and "_meta" not in r:
                out.append(r)
    return out


def collect(decisions: Path = DECISIONS, short_hold: Path = SHORT_HOLD_GAPS) -> list[dict]:
    """Every feed-gap occurrence, as rows with a stable ``gap_key``."""
    out = []
    for d in _rows(decisions):
        for it in (d.get("external_context") or {}).get("items") or []:
            name = it.get("feed_gap")
            if not name:
                continue
            out.append({"gap_key": f"{d.get('decision_id')}:{name}", "origin": "desk", "decision_id": d.get("decision_id"),
                        "decided_at": d.get("judged_at"), "retrieved_at": it.get("retrieved_at"), "feed_gap": name,
                        "gap_class": it.get("gap_class"), "source": it.get("source"), "influence": it.get("influence"),
                        "why_packet_insufficient": it.get("why_packet_insufficient")})
    for g in _rows(short_hold):
        name = g.get("feed_gap")
        if not name:
            continue
        out.append({"gap_key": f"{g.get('review_id')}:{name}", "origin": "short_hold", "decision_id": g.get("review_id"),
                    "decided_at": g.get("decided_at"), "retrieved_at": None, "feed_gap": name,
                    "gap_class": g.get("gap_class"), "source": g.get("source"), "influence": g.get("influence"),
                    "why_packet_insufficient": g.get("why_packet_insufficient")})
    return out


def known_gap_names(store_dir: Path = pipeline.STORE) -> set[str]:
    """Feed-gap names that already have a pipeline item, in ANY state: a killed gap was decided, not forgotten."""
    names = set()
    for item in pipeline.read_log(store_dir).items.values():
        ref = (item.get("origin") or {}).get("ref") or ""
        if ref.startswith(REF_PREFIX):
            names.add(ref[len(REF_PREFIX):])
    return names


def summarize(rows: list[dict]) -> dict[str, dict]:
    by: dict[str, dict] = defaultdict(lambda: {"n": 0, "decisive": 0, "class": None, "first": None, "last": None, "sources": set()})
    for r in rows:
        g = by[r["feed_gap"]]
        g["n"] += 1
        g["decisive"] += r.get("influence") == "decisive"
        g["class"] = g["class"] or r.get("gap_class")
        t = r.get("decided_at") or ""
        g["first"] = min(filter(None, [g["first"], t]), default=None)
        g["last"] = max(filter(None, [g["last"], t]), default=None)
        g["sources"].add(r.get("source"))
    return by


def new_item(name: str, s: dict, *, today: date, store_dir: Path) -> dict:
    return {
        "id": pipeline.mint_id(SESSION_REF, today=today, store=store_dir),
        "what": (f"Desk feed gap '{name}' ({s['class']}): the desk needed outside information the scan packet lacks "
                 f"({s['n']} use(s), {s['decisive']} decisive; first seen {s['first']}; sources {sorted(x for x in s['sources'] if x)}). "
                 f"Decide: wire a feed into the packet (then the desk stops searching for it), or kill with a reason. "
                 f"Detail: comms/desk/feed_gaps.jsonl."),
        "origin": {"kind": "audit", "ref": REF_PREFIX + name, "rerun": "python3 scripts/ops/desk_feed_gaps.py --report"},
        "due_when": {"kind": "date", "due_date": (today + timedelta(days=3)).isoformat()},
        "next_action": "dispatch_lane", "state": "queued",
    }


def run(decisions: Path = DECISIONS, short_hold: Path = SHORT_HOLD_GAPS, store: Path = STORE, *,
        file_pipeline: bool = False, today: date | None = None, pipeline_dir: Path = pipeline.STORE) -> dict:
    today = today or date.today()
    rows = collect(decisions, short_hold)
    have = {r.get("gap_key") for r in _rows(store)}
    fresh = [r for r in rows if r["gap_key"] not in have]
    if fresh:
        store.parent.mkdir(parents=True, exist_ok=True)
        with open(store, "a", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r, sort_keys=True) + "\n" for r in fresh)
    stats = summarize(_rows(store))
    filed, errors = [], []
    if file_pipeline:
        known = known_gap_names(pipeline_dir)
        for name in sorted(set(stats) - known):
            try:
                filed.append(pipeline.append(new_item(name, stats[name], today=today, store_dir=pipeline_dir),
                                             pipeline_dir, intent="new")["id"])
            except pipeline.PipelineError as exc:  # a refused filing is reported, never a stop
                errors.append(f"{name}: {exc}")
    return {"occurrences": len(rows), "new_lines": len(fresh), "gap_names": sorted(stats), "filed": filed, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--file-pipeline", action="store_true", help="file one pipeline item per NEW feed-gap name")
    ap.add_argument("--report", action="store_true", help="print the gaps ranked by decisive uses; write nothing")
    a = ap.parse_args(argv)
    if a.report:
        stats = summarize(collect())
        for name, s in sorted(stats.items(), key=lambda kv: (-kv[1]["decisive"], -kv[1]["n"], kv[0])):
            print(f"{name}\tclass={s['class']}\tuses={s['n']}\tdecisive={s['decisive']}\tlast={s['last']}")
        if not stats:
            print("no feed gaps recorded (no desk row has external_context.items[])")
        return 0
    try:
        print(json.dumps(run(file_pipeline=a.file_pipeline), indent=1))
    except (OSError, pipeline.PipelineError) as exc:
        print(f"::warning::desk_feed_gaps could not run: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
