#!/usr/bin/env python3
"""shadowed-features-guard: a feature taken off the trade path must stay on the data path.

Rule: docs/CLAUDE-RULES-CANONICAL.md § "Off the trade path is not off the data path"
(operator, 2026-10-26). Registry: docs/reference/shadowed-features.yaml.

Fails when an entry
  * has no live owner (a checklist row that exists and is not done/dropped, or a research/queue unit),
  * has no named freshness check (`exists` + a path that exists, or `gap`/`could_not_verify` + a live gap_row),
  * has a decision other than shadowed|annotate (a dropped feature is not a registry entry),
  * lacks a data_artifact or re_entry_test.
Also fails if `execution: shadow` legs exist in config/strategies.yaml and no shadow_legs entry does.

Prints its population and denominator. Exit 0 pass, 1 findings, 2 could not look.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TERMINAL = {"done", "dropped"}
DECISIONS = {"shadowed", "annotate"}
FRESH_STATES = {"exists", "gap", "could_not_verify"}


def _row_state(repo: Path, row_id: str):
    p = repo / "docs/claude/work/checklist" / f"{row_id}.json"
    if not p.is_file():
        return None
    import json
    return json.loads(p.read_text()).get("state", "")


def _owner_live(repo: Path, owner: str) -> bool:
    state = _row_state(repo, owner)
    if state is not None:
        return state not in TERMINAL
    return any((repo / "research/queue" / sub / f"{owner}.yaml").is_file() for sub in ("", "blocked"))


def check(repo: Path) -> tuple[list[str], int, int]:
    reg = repo / "docs/reference/shadowed-features.yaml"
    if not reg.is_file():
        raise FileNotFoundError(reg)
    entries = (yaml.safe_load(reg.read_text()) or {}).get("entries") or {}
    problems: list[str] = []
    for name, e in entries.items():
        e = e or {}
        if e.get("decision") not in DECISIONS:
            problems.append(f"{name}: decision must be one of {sorted(DECISIONS)}, got {e.get('decision')!r}")
        for f in ("data_artifact", "re_entry_test"):
            if not e.get(f):
                problems.append(f"{name}: missing {f}")
        owner = e.get("owner")
        if not owner or not _owner_live(repo, str(owner)):
            problems.append(f"{name}: owner {owner!r} is not a live checklist row or research/queue unit")
        fc = e.get("freshness_check") or {}
        st = fc.get("state")
        if st not in FRESH_STATES:
            problems.append(f"{name}: freshness_check.state must be one of {sorted(FRESH_STATES)}, got {st!r}")
        elif st == "exists":
            if not fc.get("path") or not (repo / str(fc["path"])).exists():
                problems.append(f"{name}: freshness_check.path {fc.get('path')!r} does not exist")
        else:
            gap = fc.get("gap_row")
            gs = _row_state(repo, str(gap)) if gap else None
            if gs is None or gs in TERMINAL:
                problems.append(f"{name}: freshness_check {st} needs a live gap_row; {gap!r} is not one")
    strat = repo / "config/strategies.yaml"
    n_shadow = n_total = 0
    if strat.is_file():
        d = yaml.safe_load(strat.read_text()) or {}
        s = d.get("strategies", d)
        legs = {k: v for k, v in s.items() if isinstance(v, dict)}
        n_total = len(legs)
        n_shadow = sum(1 for v in legs.values() if v.get("execution") == "shadow")
    if n_shadow and "shadow_legs" not in entries:
        problems.append(f"{n_shadow} execution: shadow leg(s) exist but no shadow_legs entry")
    return problems, len(entries), n_shadow if n_total else -1


def _self_test() -> int:
    import json
    with tempfile.TemporaryDirectory() as t:
        repo = Path(t)
        (repo / "docs/reference").mkdir(parents=True)
        (repo / "docs/claude/work/checklist").mkdir(parents=True)
        (repo / "docs/claude/work/checklist/LIVE.json").write_text(json.dumps({"state": "queued"}))
        (repo / "docs/claude/work/checklist/DEAD.json").write_text(json.dumps({"state": "done"}))
        good = {"decision": "shadowed", "data_artifact": "x", "re_entry_test": "y", "owner": "LIVE",
                "freshness_check": {"state": "gap", "gap_row": "LIVE"}}
        bad = [dict(good, owner="DEAD"), dict(good, owner="NOPE"), dict(good, decision="dropped"),
               dict(good, freshness_check={"state": "gap", "gap_row": "DEAD"}),
               dict(good, freshness_check={"state": "exists", "path": "no/such"}),
               dict(good, freshness_check={}), {k: v for k, v in good.items() if k != "re_entry_test"}]
        reg = repo / "docs/reference/shadowed-features.yaml"
        reg.write_text(yaml.safe_dump({"entries": {"ok": good}}))
        if check(repo)[0]:
            print("self-test FAIL: clean registry reported problems", check(repo)[0])
            return 1
        for i, b in enumerate(bad):
            reg.write_text(yaml.safe_dump({"entries": {"bad": b}}))
            if not check(repo)[0]:
                print(f"self-test FAIL: planted break #{i} not caught")
                return 1
    print(f"self-test PASS: clean registry passes, {len(bad)} planted breaks all caught")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    try:
        problems, n, n_shadow = check(REPO)
    except Exception as exc:  # could not look is not a pass
        print(f"shadowed-features-guard: COULD NOT LOOK ({exc})")
        return 2
    shadow = "unmeasured" if n_shadow < 0 else f"{n_shadow} execution: shadow leg(s)"
    print(f"shadowed-features-guard: scanned {n} registry entr(y/ies); strategies.yaml has {shadow}")
    for p in problems:
        print(f"  FAIL {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
