#!/usr/bin/env python3
"""Live review ROWS MIRROR: ``live-review/rows`` -> main's ``reviews.jsonl`` (LTR-APPLY-AUTOFLOW (iv)).

Reviewers push rows straight to the protected append-only ``live-review/rows``
branch (``.claude/skills/live-trade-review/SKILL.md`` Step 6.3) so the apply can
run on a pinned commit with no main PR in the path. ``main`` must still carry
the full record. This script, run by ``.github/workflows/live-review-rows-mirror.yml``
on a main checkout, copies onto main:

* every row of the rows branch's ``comms/live_review/reviews.jsonl`` whose
  ``review_id`` main does not have, appended in the rows branch's order;
* the files those rows cite: ``comms/live_review/packets/<review_id>.json``
  (when the row carries ``packet_sha``) and its ``outcome_table_source``.

Merged BY review_id, never by text concatenation: main's existing lines are
kept byte for byte and a review_id already on main is never re-added, so a
re-run is a no-op. A cited file that already exists on main with DIFFERENT
content is never overwritten: that row is skipped and reported (exit 1), the
rest still mirror.

Exit codes: 0 ok (``mirrored=N``, N may be 0) · 1 a row was skipped · 2 could not look.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
REVIEWS = "comms/live_review/reviews.jsonl"
PACKETS = "comms/live_review/packets"


def git_show(ref: str, path: str, cwd: Path = ROOT) -> Optional[bytes]:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=cwd, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def _ids(text: str) -> List[Tuple[Optional[str], str]]:
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rid = json.loads(line).get("review_id")
        except (ValueError, AttributeError):
            rid = None
        out.append((rid, line))
    return out


def cited(line: str) -> List[str]:
    row = json.loads(line)
    paths = []
    if row.get("packet_sha"):
        paths.append(f"{PACKETS}/{row.get('review_id')}.json")
    src = row.get("outcome_table_source")
    if isinstance(src, str) and src.startswith("comms/live_review/") and ".." not in src:
        paths.append(src)
    return paths


def mirror(root: Path, read_rows: Callable[[str], Optional[bytes]]) -> Dict[str, object]:
    """Apply the mirror to the checkout at ``root``. ``read_rows(path)`` reads the rows branch."""
    rows_raw = read_rows(REVIEWS)
    if rows_raw is None:
        return {"state": "could_not_look", "reason": f"{REVIEWS} unreadable on the rows branch"}
    main_path = root / REVIEWS
    main_text = main_path.read_text() if main_path.exists() else ""
    have = {rid for rid, _ in _ids(main_text) if rid}
    new_lines, files, skipped = [], {}, []
    for rid, line in _ids(rows_raw.decode()):
        if not rid:
            skipped.append({"review_id": None, "why": "row without a review_id / not JSON"})
            continue
        if rid in have:
            continue
        want: Dict[str, bytes] = {}
        why = None
        for p in cited(line):
            blob = read_rows(p)
            if blob is None:
                why = f"cited file {p} missing on the rows branch"
                break
            dest = root / p
            if dest.exists() and dest.read_bytes() != blob:
                why = f"cited file {p} differs on main; not overwritten"
                break
            want[p] = blob
        if why:
            skipped.append({"review_id": rid, "why": why})
            continue
        have.add(rid)
        new_lines.append(line)
        files.update(want)
    if new_lines:
        for p, blob in files.items():
            (root / p).parent.mkdir(parents=True, exist_ok=True)
            (root / p).write_bytes(blob)
        sep = "" if (not main_text or main_text.endswith("\n")) else "\n"
        main_path.parent.mkdir(parents=True, exist_ok=True)
        main_path.write_text(main_text + sep + "\n".join(new_lines) + "\n")
    return {"state": "ok", "mirrored": len(new_lines), "files": sorted(files),
            "review_ids": [json.loads(x)["review_id"] for x in new_lines], "skipped": skipped}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows-ref", default="origin/live-review/rows")
    args = ap.parse_args(argv)
    res = mirror(ROOT, lambda p: git_show(args.rows_ref, p))
    print(json.dumps(res, indent=2))
    if res["state"] != "ok":
        return 2
    return 1 if res["skipped"] else 0


if __name__ == "__main__":
    sys.exit(main())
