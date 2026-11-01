#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py (--self-test) + .github/workflows/grading-freshness-alert.yml (daily, prints the table)
"""Is every grader's grade FRESH, and does it drive an action? (row GRADE-EVERYTHING-CONTINUOUSLY, 2026-11-01)

Reads docs/reference/grader-registry.yaml. ALERT-ONLY, like check_grading_freshness.py: the default prints a table and
GitHub ``::warning::`` annotations and ALWAYS exits 0; ``--strict`` exits 1 (stale / no grader) or 2 (could not look).
It grades nothing, gates nothing, blocks no PR and no trade. Gates this adds or changes: none.

Per grader one of: FRESH · STALE (store older than max_age_hours) · COULD_NOT_LOOK (store missing/unparseable: never
printed as fresh) · NO_GRADER (a decision class with no continuous grader: the gap, counted, not hidden). Each line also
says what the grade DRIVES; ``none`` is the feedback gap and names its owner.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "docs" / "reference" / "grader-registry.yaml"
FRESH, STALE, COULD_NOT_LOOK, NO_GRADER = "FRESH", "STALE", "COULD_NOT_LOOK", "NO_GRADER"


def _when(v) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def store_time(root: Path, store: dict) -> Optional[datetime]:
    path, kind, field = store.get("path"), store.get("kind"), store.get("field")
    p = root / str(path)
    if kind == "commit":
        out = subprocess.run(["git", "log", "-1", "--format=%cI", "--", str(path)], cwd=root, capture_output=True, text=True)
        return _when(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    if not p.is_file():
        return None
    try:
        if kind == "json_field":
            return _when(json.loads(p.read_text())[field])
        if kind == "jsonl_max":
            ts = []
            for ln in p.read_text().splitlines():
                try:
                    t = _when(json.loads(ln).get(field))
                except ValueError:
                    continue
                if t:
                    ts.append(t)
            return max(ts) if ts else None
    except (ValueError, KeyError, TypeError, OSError):
        return None
    return None


def classify(root: Path, g: dict, now: datetime) -> tuple[str, str]:
    if g.get("status") != "scheduled" or not g.get("store"):
        return NO_GRADER, "no continuous grader for this decision class"
    t = store_time(root, g["store"])
    if t is None:
        return COULD_NOT_LOOK, f"{g['store'].get('path')}: missing or no parseable {g['store'].get('field') or 'commit'}"
    age_h = (now - t).total_seconds() / 3600
    lim = float(g["store"]["max_age_hours"])
    return (FRESH if age_h <= lim else STALE), f"newest grade {age_h:.1f}h old (limit {lim:g}h)"


def run(root: Path = REPO, registry: Path = REGISTRY, now: Optional[datetime] = None) -> tuple[list[dict], dict]:
    now = now or datetime.now(timezone.utc)
    graders = yaml.safe_load(registry.read_text())["graders"]
    rows = []
    for g in graders:
        state, detail = classify(root, g, now)
        rows.append({"id": g["id"], "decision": g["decision"], "state": state, "detail": detail,
                     "drives_action": g.get("drives_action"), "gap_owner": g.get("gap_owner")})
    counts = {s: sum(r["state"] == s for r in rows) for s in (FRESH, STALE, COULD_NOT_LOOK, NO_GRADER)}
    counts["drives_no_action"] = sum(str(r["drives_action"]).startswith("none") for r in rows)
    return rows, counts


def self_test() -> int:
    import tempfile
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "fresh.json").write_text(json.dumps({"at": "2026-11-01T11:00:00Z"}))
        (root / "old.json").write_text(json.dumps({"at": "2026-10-01T00:00:00Z"}))
        (root / "bad.json").write_text("not json")
        (root / "s.jsonl").write_text('{"at":"2026-10-01T00:00:00Z"}\n{"at":"2026-11-01T10:00:00Z"}\n')
        mk = lambda p, k="json_field": {"status": "scheduled", "store": {"path": p, "kind": k, "field": "at", "max_age_hours": 6}}
        cases = [(mk("fresh.json"), FRESH), (mk("old.json"), STALE), (mk("bad.json"), COULD_NOT_LOOK),
                 (mk("missing.json"), COULD_NOT_LOOK), (mk("s.jsonl", "jsonl_max"), FRESH),
                 ({"status": "not_scheduled", "store": None}, NO_GRADER)]
        bad = [(i, classify(root, g, now)[0], want) for i, (g, want) in enumerate(cases) if classify(root, g, now)[0] != want]
    if bad:
        print("grader-freshness self-test FAILED:", bad)
        return 1
    print("grader-freshness: self-test OK — every planted state classified (stale, unparseable and missing are never FRESH)")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in a:
        return self_test()
    rows, counts = run()
    print(f"grader-freshness: {len(rows)} grader/decision classes · {counts}")
    for r in rows:
        print(f"  {r['state']:<14} {r['id']:<28} {r['detail']} | drives: {r['drives_action']}"
              + (f" | gap owner: {r['gap_owner']}" if r["gap_owner"] and str(r["drives_action"]).startswith("none") else ""))
        if r["state"] != FRESH:
            print(f"::warning::grader {r['id']} is {r['state']}: {r['detail']}")
    if "--strict" in a:
        if counts[COULD_NOT_LOOK]:
            return 2
        return 1 if counts[STALE] or counts[NO_GRADER] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
