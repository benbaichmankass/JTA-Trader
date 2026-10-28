#!/usr/bin/env python3
# wiring: .claude/skills/research-ops/SKILL.md (step 1, CHECKS) + .claude/skills/programme-review/SKILL.md (step 1, CHECKS)
"""The CHECKS layer for research-ops (4x/day) and the weekly programme review: one JSON packet of facts.

WHY (lane SKILL-DESIGN-RESEARCH, 2026-10-28; operator the same morning, paraphrased, binding): every
recurring review must keep a fixed format that guarantees the needed checks, AND leave the reasoning to
the session. This script is the first half. It computes, it never judges: no verdict, no ranking, no
recommendation. The session reads the packet and writes the ANALYSIS (the skill's second half) over it.
Shared pattern: docs/reference/llm-analyst-skill-design.md (lane ANALYTIC-SKILL-DESIGN).

What the packet holds, and why each block exists (each answers a failure MEASURED on the research-ops
records 2026-10-27T0925Z .. 2026-10-28T0300Z, see docs/research/research-ops-redesign-2026-10-28.md):

  pipeline          throughput + computed floor (queue_throughput; the same numbers the brief uses).
  runnable_by_track runnable units split TRADING / MODEL / INFRA (operator 2026-10-28: research is two
                    tracks). A track with 0 runnable is the headline, whatever the total says.
  results           every unit with a result row generated since --since: verdict, grader, track,
                    `verdict_on_unpowered` (a graded verdict whose rows say underpowered / insufficient_n) and
                    `power_label_uninformative` (a pass/fail whose only power label is `accruing`, see UNPOWERED).
  batches           graded units in the window grouped by authoring batch (RQ-YYYYMMDD-<h4>): n, pass, fail.
                    The multiple-testing denominator a PASS was chosen from.
  fails_without_next FAILs in the window that no queue unit or programme node names: a first test that
                    failed and nothing follows it (fail-is-not-dead, PLANNING.md s1).
  followups         every node / unit the last --records ops records said they filed, traced to now:
                    authored -> fired -> graded. "Filed" is not "ran".
  needs_review      the bucket, its owners, and its size across the last records (stagnation).
  ops_trend         per record: nodes drafted, triaged, results read, steps not run.
  stale             queued units never dispatched whose id date is older than --stale-days.
  graded_by_window  verdicts per track by grading.graded_at over 7d / 30d / lifetime (never one window alone).
  previous_calls    the top-level `calls` of the newest record of this kind (Layer 0 of the shared pattern grades them).

Read-only. Writes only --out (default stdout).
    python3 scripts/research/research_ops_checks.py --since 2026-10-27T21:10:00Z
    python3 scripts/research/research_ops_checks.py --since 7d --kind programme_review --out /tmp/checks.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OPS_DIR = Path("comms/research/ops")
REVIEW_DIR = Path("comms/research/programme_review")
#: Rows that say "cannot answer yet". NOT `accruing`: MEASURED 2026-10-28 over result rows generated since
#: 2026-10-21, 466 of 571 carry `accruing`, including 354 rule-scored FAILs and 50 PASSes, so it is a near-default
#: label, not a power read (scripts/ops/research_digest.py reached the same conclusion on 2026-10-11). The packet
#: counts it separately as `power_label_uninformative`; the real power check (realised n vs the unit's
#: `power.expected_n`) is not computed by any producer yet (row RESEARCH-POWER-CHECK).
UNPOWERED = {"underpowered", "insufficient_n"}
MODEL_PROGRAMMES = {"P2", "P6"}
TRADING_PROGRAMMES = {"P1", "P3", "P4", "P5", "P7"}
BATCH_RE = re.compile(r"^(RQ-\d{8}-[0-9a-f]{4})-\d+$")
RANGE_RE = re.compile(r"^(RQ-\d{8}-(?:[0-9a-f]{4}-)?)(\d+)\.\.(\d+)$")
ID_RE = re.compile(r"^(RQ-\d{8}-[0-9A-Za-z-]+|P\d+-[A-Za-z0-9-]+)$")
ID_DATE_RE = re.compile(r"^RQ-(\d{8})-")


def _ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def parse_since(s: str, now: datetime) -> datetime:
    m = re.fullmatch(r"(\d+)([hd])", s.strip())
    if m:
        n = int(m.group(1))
        return now - (timedelta(hours=n) if m.group(2) == "h" else timedelta(days=n))
    t = _ts(s)
    if t is None:
        raise SystemExit(f"--since: cannot parse {s!r} (ISO time, or Nh / Nd)")
    return t


def track(u: Dict[str, Any]) -> str:
    """TRADING (how to trade better) | MODEL (how to build a better AI trader model) | INFRA.
    Programme wins; else an ml_bakeoff block or the ml_health theme is MODEL; infra theme is INFRA."""
    prog = u.get("programme") or (u.get("programme_node") or {}).get("programme")
    if prog in MODEL_PROGRAMMES:
        return "MODEL"
    if prog in TRADING_PROGRAMMES:
        return "TRADING"
    if u.get("ml_bakeoff") or u.get("theme") == "ml_health":
        return "MODEL"
    if u.get("theme") == "infra":
        return "INFRA"
    return "TRADING"


def batch_of(uid: str) -> Optional[str]:
    m = BATCH_RE.match(uid)
    return m.group(1) if m else None


def _token(it: Any) -> str:
    """The id an ops-record list item names: a bare string ("RQ-... (note)", "RQ-...:"), or a dict
    carrying `unit` / `node` / `id` (records before 2026-10-27 used both shapes)."""
    if isinstance(it, dict):
        it = it.get("unit") or it.get("node") or it.get("id") or ""
    s = str(it).strip()
    return s.split()[0].rstrip(":,;.") if s else ""


def expand_ids(items: List[Any]) -> List[str]:
    """Ids named by a record list, ranges expanded; tokens that are not an RQ- or P<n>- id are dropped."""
    out: List[str] = []
    for it in items or []:
        s = _token(it)
        m = RANGE_RE.match(s)
        if m:
            w = len(m.group(2))
            out += [f"{m.group(1)}{i:0{w}d}" for i in range(int(m.group(2)), int(m.group(3)) + 1)]
        elif ID_RE.match(s):
            out.append(s)
    return out


def load_records(root: Path, d: Path, k: int) -> List[Dict[str, Any]]:
    recs = []
    for f in sorted((root / d).glob("*.json"))[-k:]:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            r = {"_unreadable": True}
        r["_file"] = str(f.relative_to(root))
        recs.append(r)
    return recs


def result_rows(root: Path, since: datetime) -> Dict[str, List[Dict[str, Any]]]:
    rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in (root / "research" / "results").glob("*/*.jsonl"):
        try:
            for ln in f.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                r = json.loads(ln)
                t = _ts(r.get("generated_at"))
                if t and t >= since:
                    rows[f.parent.name].append(r)
        except (OSError, ValueError):
            rows["_unreadable"].append({"file": str(f)})
    return rows


def build(root: Path, since: datetime, now: datetime, k: int, stale_days: int, kind: str) -> Dict[str, Any]:
    from scripts.research.queue_replenish import existing_units, runnable
    from scripts.research.queue_throughput import computed_floor, throughput

    units, bad = existing_units(root)
    t = throughput(root, now=now)
    run_ids = runnable(units, now=now)
    by_track = Counter(track(units[u]) for u in run_ids)

    # every text that could name a unit as its successor: queue files + programme trees
    texts: Dict[str, str] = {}
    for p in list((root / "research" / "queue").rglob("*.yaml")) + list((root / "research" / "programmes").glob("*.yaml")):
        try:
            texts[str(p.relative_to(root))] = p.read_text(encoding="utf-8")
        except OSError:
            pass

    rows = result_rows(root, since)
    results, batches = [], defaultdict(Counter)
    fails_without_next = []
    for uid in sorted(k_ for k_ in rows if k_ != "_unreadable"):
        u = units.get(uid, {})
        g = u.get("grading") or {}
        verdict = g.get("verdict")
        powers = sorted({str(r.get("power_state")) for r in rows[uid] if r.get("power_state")})
        item = {"unit": uid, "track": track(u), "programme": u.get("programme") or (u.get("programme_node") or {}).get("programme"),
                "theme": u.get("theme"), "verdict": verdict, "grader": g.get("grader") or ("session" if verdict else None),
                "needs_review": bool(g.get("needs_review")), "owner": g.get("owner"),
                "row_verdicts": dict(Counter(str(r.get("verdict")) for r in rows[uid])), "power_states": powers,
                "verdict_on_unpowered": bool(verdict in ("pass", "fail") and powers and set(powers) <= UNPOWERED),
                "power_label_uninformative": bool(verdict in ("pass", "fail") and powers == ["accruing"])}
        results.append(item)
        b = batch_of(uid)
        if b and verdict:
            batches[b][verdict] += 1
        if verdict == "fail":
            own = f"research/queue/{uid}.yaml"
            named = [p for p, s in texts.items() if uid in s and not p.endswith(f"{uid}.yaml") and p != own]
            if not named:
                fails_without_next.append({"unit": uid, "track": item["track"], "title": str(u.get("title", ""))[:140]})

    # follow-ups the last k ops records said they filed
    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    for p in (root / "research" / "programmes").glob("*.yaml"):
        try:
            import yaml
            for n in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("nodes") or []:
                nodes_by_id[str(n.get("id"))] = n
        except Exception:  # noqa: BLE001 -- an unreadable tree is reported below, never silent
            nodes_by_id[f"_unreadable:{p.name}"] = {}
    emitted = defaultdict(list)
    for uid, u in units.items():
        node = (u.get("programme_node") or {}).get("node")
        if node:
            emitted[node].append(uid)

    def unit_state(uid: str) -> str:
        u = units.get(uid)
        if not u:
            return "missing"
        if (u.get("grading") or {}).get("verdict"):
            return f"graded:{u['grading']['verdict']}"
        return "fired" if u.get("last_dispatched_at") else f"not_fired:{u.get('status')}"

    recs = load_records(root, OPS_DIR, k)
    followups = []
    for r in recs:
        named = expand_ids((r.get("authoring") or {}).get("nodes") or []) + expand_ids(r.get("units_authored") or [])
        filed_nodes = list(dict.fromkeys(n for n in named if not n.startswith("RQ-")))
        for nid in filed_nodes:
            n = nodes_by_id.get(nid)
            st = "node_missing" if n is None else ("needs_authoring" if "needs_authoring" in n else "authored")
            followups.append({"from": r["_file"], "kind": "node", "id": nid, "state": st,
                              "units": {e: unit_state(e) for e in emitted.get(nid, [])}})
        for uid in (u_ for u_ in expand_ids(r.get("units_authored") or []) if u_.startswith("RQ-")):
            followups.append({"from": r["_file"], "kind": "unit", "id": uid, "state": unit_state(uid)})
    fu_summary = Counter(f["state"] if f["kind"] == "unit" else
                         (f["state"] if not f["units"] else "emitted") for f in followups)

    nr = {uid: u for uid, u in units.items() if (u.get("grading") or {}).get("needs_review")}
    stale = []
    for uid, u in units.items():
        m = ID_DATE_RE.match(uid)
        if u.get("status") == "queued" and not u.get("last_dispatched_at") and m:
            born = datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
            if (now - born).days >= stale_days:
                stale.append({"unit": uid, "track": track(u), "age_days": (now - born).days})
    stale.sort(key=lambda x: -x["age_days"])

    # windows: lifetime / 30d / 7d by grading.graded_at (docs/reference/llm-analyst-skill-design.md s2: never the
    # since-last-run window alone)
    windows: Dict[str, Dict[str, Dict[str, int]]] = {}
    for label, days in (("7d", 7), ("30d", 30), ("lifetime", None)):
        cut = None if days is None else (now - timedelta(days=days)).date().isoformat()
        c: Dict[str, Counter] = defaultdict(Counter)
        for u in units.values():
            g = u.get("grading") or {}
            if g.get("verdict") and (cut is None or str(g.get("graded_at") or "") >= cut):
                c[track(u)][str(g["verdict"])] += 1
        windows[label] = {tr: dict(v) for tr, v in sorted(c.items())}

    prev = load_records(root, OPS_DIR if kind == "research_ops" else REVIEW_DIR, 1)
    graded = Counter(r["verdict"] for r in results if r["verdict"])
    return {
        "as_of": now.isoformat(), "since": since.isoformat(), "kind": kind,
        "population": f"research/queue/**/*.yaml ({len(units)} units, {len(bad)} unreadable); result rows with "
                      f"generated_at >= since ({sum(len(v) for k_, v in rows.items() if k_ != '_unreadable')} rows, "
                      f"{len(rows.get('_unreadable', []))} unreadable files); last {len(recs)} ops records",
        "pipeline": {**t, "floor": computed_floor(t.get("fired_24h"))},
        "runnable_by_track": {"TRADING": by_track.get("TRADING", 0), "MODEL": by_track.get("MODEL", 0),
                              "INFRA": by_track.get("INFRA", 0), "total": len(run_ids)},
        "results": {"units_with_rows": len(results), "graded": dict(graded),
                    "ungraded": sum(1 for r in results if not r["verdict"] and not (r["needs_review"] and r["owner"])),
                    "verdict_on_unpowered": [r["unit"] for r in results if r["verdict_on_unpowered"]],
                    "power_label_uninformative": sum(1 for r in results if r["power_label_uninformative"]),
                    "pass_rate": (round(graded.get("pass", 0) / sum(graded.values()), 3) if graded else None),
                    "by_track": {tr: dict(Counter(r["verdict"] for r in results if r["track"] == tr))
                                 for tr in ("TRADING", "MODEL", "INFRA")},
                    "units": results},
        "graded_by_window": windows,
        "batches": {b: {"n": sum(c.values()), **dict(c)} for b, c in sorted(batches.items()) if sum(c.values()) >= 3},
        "fails_without_next": fails_without_next,
        "followups": {"summary": dict(fu_summary), "items": followups},
        "needs_review": {"count": len(nr), "owners": dict(Counter(str((u.get("grading") or {}).get("owner")) for u in nr.values())),
                         "trend_from_records": [r.get("needs_review_left") for r in recs]},
        "ops_trend": [{"file": r["_file"], "nodes_drafted": (r.get("authoring") or {}).get("nodes_drafted"),
                       "needs_review_triaged": r.get("needs_review_triaged"),
                       "results_read": {x: (r.get("results_read") or {}).get(x) for x in ("pass", "fail", "indeterminate")},
                       "not_run": len(r.get("not_run") or [])} for r in recs],
        "stale": {"days": stale_days, "count": len(stale), "by_track": dict(Counter(s["track"] for s in stale)), "oldest": stale[:10]},
        "previous_calls": {"file": prev[0]["_file"] if prev else None,
                           "calls": ((prev[0].get("calls") or (prev[0].get("analysis") or {}).get("calls")) if prev else None)},
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default=None, help="ISO time or Nh/Nd; default = newest ops record's finished_at, else 24h")
    ap.add_argument("--records", type=int, default=4, help="how many recent ops records to trace follow-ups from")
    ap.add_argument("--stale-days", type=int, default=14)
    ap.add_argument("--kind", choices=["research_ops", "programme_review"], default="research_ops")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    root = Path(a.root)
    now = datetime.now(timezone.utc)
    since_s = a.since
    if since_s is None:
        last = load_records(root, OPS_DIR, 1)
        since_s = (last[0].get("finished_at") if last else None) or "24h"
    pkt = build(root, parse_since(since_s, now), now, a.records, a.stale_days, a.kind)
    s = json.dumps(pkt, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(s + "\n", encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
