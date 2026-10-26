#!/usr/bin/env python3
# wiring: called by .github/workflows/desk-scan-packet.yml (publish) and
# .github/workflows/desk-decisions-mirror.yml (mirror).
"""DESK-6-SHADOW-PILOT -- the two data hops of the ``desk/decisions`` branch.

The desk loop (``.claude/skills/trading-desk/SKILL.md`` § 1) keeps its live record on the
protected append-only ``desk/decisions`` branch, the ``live-review/rows`` pattern (LTR-APPLY-AUTOFLOW):

* ``publish`` -- stage ONE builder-made scan packet for that branch: the packet, compact, at
  ``comms/desk/packets/<packet_id>.json``, and the pointer ``comms/desk/latest_scan.json``
  (``packet_id``, ``packet_sha``, ``path``, ``built_at``, ``info_cutoff_at``) that a repo-less desk
  wake reads first. The packet is re-validated with desk-records-guard's ``packet_problems`` and
  its sha is the guard's ``packet_sha`` (canonical JSON), so the pointer and every row that cites
  it agree with what CI checks on ``main``.
* ``mirror`` -- copy onto a ``main`` checkout every row of the branch's
  ``comms/desk/decisions.jsonl`` whose ``decision_id`` main lacks, appended in branch order, plus
  the packet each row cites. Merged BY decision_id, never text concat: main's lines are kept byte
  for byte, a re-run is a no-op, and a cited packet that already exists on main with DIFFERENT
  content is never overwritten (that row is skipped and reported). Packets no row cites stay on
  the branch, so main carries only packets that were judged.

Exit: 0 ok · 1 a row was skipped / a packet refused · 2 could not look.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import check_desk_records as cdr  # noqa: E402

DECISIONS = "comms/desk/decisions.jsonl"
PACKETS = "comms/desk/packets"
POINTER = "comms/desk/latest_scan.json"


def git_show(ref: str, path: str, cwd: Path = ROOT) -> Optional[bytes]:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=cwd, capture_output=True)
    return r.stdout if r.returncode == 0 else None


# ----------------------------------------------------------------------------- publish

def publish(packet: dict, stage: Path) -> Dict[str, object]:
    problems = cdr.packet_problems(packet, json.loads(cdr.PACKET_SCHEMA.read_text()))
    meta = packet.get("meta") or {}
    if problems or meta.get("packet_kind") != "scan" or meta.get("mode") != "live":
        return {"state": "refused", "problems": problems or ["publish takes a live scan packet only"]}
    pid = meta["packet_id"]
    rel = f"{PACKETS}/{pid}.json"
    (stage / PACKETS).mkdir(parents=True, exist_ok=True)
    (stage / rel).write_text(json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n")
    pointer = {"packet_id": pid, "packet_sha": cdr.packet_sha(packet), "path": rel,
               "built_at": meta["built_at"], "info_cutoff_at": meta["info_cutoff_at"]}
    (stage / POINTER).write_text(json.dumps(pointer, indent=1, sort_keys=True) + "\n")
    return {"state": "ok", **pointer}


# ----------------------------------------------------------------------------- mirror

def _ids(text: str) -> List[Tuple[Optional[str], str]]:
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rid = json.loads(line).get("decision_id")
        except (ValueError, AttributeError):
            rid = None
        out.append((rid, line))
    return out


def mirror(root: Path, read_branch: Callable[[str], Optional[bytes]]) -> Dict[str, object]:
    """Apply the mirror to the checkout at ``root``; ``read_branch(path)`` reads desk/decisions."""
    raw = read_branch(DECISIONS)
    if raw is None:
        return {"state": "could_not_look", "reason": f"{DECISIONS} unreadable on desk/decisions"}
    main_path = root / DECISIONS
    main_text = main_path.read_text() if main_path.exists() else ""
    have = {rid for rid, _ in _ids(main_text) if rid}
    new_lines, files, skipped = [], {}, []
    for rid, line in _ids(raw.decode()):
        if not rid:
            skipped.append({"decision_id": None, "why": "row without a decision_id / not JSON"})
            continue
        if rid in have:
            continue
        pid = json.loads(line).get("packet_id")
        p = f"{PACKETS}/{pid}.json"
        blob = read_branch(p) if isinstance(pid, str) and "/" not in pid and ".." not in pid else None
        if blob is None:
            skipped.append({"decision_id": rid, "why": f"cited packet {p} missing on desk/decisions"})
            continue
        dest = root / p
        if dest.exists() and dest.read_bytes() != blob:
            skipped.append({"decision_id": rid, "why": f"cited packet {p} differs on main; not overwritten"})
            continue
        have.add(rid)
        new_lines.append(line)
        files[p] = blob
    if new_lines:
        for p, blob in files.items():
            (root / p).parent.mkdir(parents=True, exist_ok=True)
            (root / p).write_bytes(blob)
        sep = "" if (not main_text or main_text.endswith("\n")) else "\n"
        main_path.parent.mkdir(parents=True, exist_ok=True)
        main_path.write_text(main_text + sep + "\n".join(new_lines) + "\n")
    return {"state": "ok", "mirrored": len(new_lines), "files": sorted(files),
            "decision_ids": [json.loads(x)["decision_id"] for x in new_lines], "skipped": skipped}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("publish")
    p1.add_argument("--packet", type=Path, required=True)
    p1.add_argument("--stage", type=Path, required=True)
    p2 = sub.add_parser("mirror")
    p2.add_argument("--ref", default="origin/desk/decisions")
    a = ap.parse_args(argv)
    if a.cmd == "publish":
        try:
            pk = json.loads(a.packet.read_text())
        except (OSError, ValueError) as exc:
            print(json.dumps({"state": "could_not_look", "reason": str(exc)}))
            return 2
        res = publish(pk, a.stage)
        print(json.dumps(res, indent=2))
        return 0 if res["state"] == "ok" else 1
    res = mirror(ROOT, lambda p: git_show(a.ref, p))
    print(json.dumps(res, indent=2))
    if res["state"] != "ok":
        return 2
    return 1 if res["skipped"] else 0


if __name__ == "__main__":
    sys.exit(main())
