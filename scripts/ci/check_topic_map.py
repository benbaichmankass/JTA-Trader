#!/usr/bin/env python3
"""topic-map-guard (WORK-TOPIC-TAXONOMY): docs/roadmap/topics.yaml maps EVERY milestone in
docs/roadmap/milestones.yaml (and nothing else), and every topic it uses is declared in its `topics` list.

Why: the Work page groups rows by a topic computed from their roadmap ref. A milestone added without a topic
would silently send its rows to "Unmapped"; a stale entry would name a goal that no longer exists.
Exit 0 = OK, 1 = a violation (each printed). ``--self-test`` plants each defect and checks it is caught.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

REPO = Path(__file__).resolve().parents[2]


def problems(milestones: Any, topics: Dict[str, Any]) -> List[str]:
    ms = milestones.get("milestones", milestones) if isinstance(milestones, dict) else milestones
    ids = {str(x["id"]) for x in (ms or []) if isinstance(x, dict) and x.get("id")}
    mapped = topics.get("milestones") or {}
    declared = list(topics.get("topics") or [])
    out: List[str] = []
    if not ids:
        out.append("milestones.yaml: no milestone ids read (could not look is not a pass)")
    for i in sorted(ids - set(mapped)):
        out.append(f"milestone {i} has no topic in docs/roadmap/topics.yaml")
    for i in sorted(set(mapped) - ids):
        out.append(f"topics.yaml maps {i}, which is not a milestone in docs/roadmap/milestones.yaml")
    for i, v in sorted(mapped.items()):
        t = (v or {}).get("topic") if isinstance(v, dict) else None
        if not t:
            out.append(f"topics.yaml: {i} has no topic")
        elif t not in declared:
            out.append(f"topics.yaml: {i} uses topic {t!r}, not in the declared `topics` list")
    if not topics.get("unmapped_topic"):
        out.append("topics.yaml: no `unmapped_topic` (rows without a roadmap ref need a visible bucket)")
    return out


def _self_test() -> int:
    ms = {"milestones": [{"id": "A"}, {"id": "B"}]}
    good = {"unmapped_topic": "Unmapped", "topics": ["X"], "milestones": {"A": {"topic": "X"}, "B": {"topic": "X"}}}
    cases = [(good, 0), ({**good, "milestones": {"A": {"topic": "X"}}}, 1),
             ({**good, "milestones": {**good["milestones"], "C": {"topic": "X"}}}, 1),
             ({**good, "milestones": {"A": {"topic": "Y"}, "B": {"topic": "X"}}}, 1),
             ({k: v for k, v in good.items() if k != "unmapped_topic"}, 1)]
    ok = all((len(problems(ms, t)) > 0) == bool(bad) for t, bad in cases) and problems({"milestones": []}, good)
    print("topic-map-guard self-test:", "OK" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    try:
        ms = yaml.safe_load((REPO / "docs/roadmap/milestones.yaml").read_text())
        tp = yaml.safe_load((REPO / "docs/roadmap/topics.yaml").read_text()) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"topic-map-guard: could not read the maps: {exc}")
        return 1
    bad = problems(ms, tp)
    for b in bad:
        print(f"::error::topic-map-guard: {b}")
    if not bad:
        print(f"topic-map-guard: OK — {len(tp.get('milestones') or {})} milestones mapped to "
              f"{len(tp.get('topics') or [])} topics")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
