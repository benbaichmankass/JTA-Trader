#!/usr/bin/env python3
"""Live review ROWS MIRROR: ``live-review/rows`` -> main's ``reviews.jsonl`` (LTR-APPLY-AUTOFLOW (iv)).

Reviewers push rows straight to the protected append-only ``live-review/rows``
branch (``.claude/skills/live-trade-review/SKILL.md`` Step 6.3) so the apply can
run on a pinned commit with no main PR in the path. ``main`` must still carry
the full record. This script, run by ``.github/workflows/live-review-rows-mirror.yml``
on a main checkout, copies onto main:

* every row of the rows branch's ``comms/live_review/reviews.jsonl`` whose
  ``review_id`` main does not have and that passes the SAME rules
  ``scripts/ci/check_live_review_records.py`` applies (its ``row_problems`` /
  ``packet_blob_problems``, called, not copied), appended in the rows branch's order.
  A row that fails is skipped as ``schema: <message>`` and the rest still mirror: the
  rows branch is append-only, so one corrupt row must not strand every later one;
* the files those rows cite: ``comms/live_review/packets/<review_id>.json``
  (when the row carries ``packet_sha``) and its ``outcome_table_source``.

Rows come from BOTH the legacy ``reviews.jsonl`` and the per-row files
``comms/live_review/rows/<review_id>.json`` a reviewer creates since LTR-ROWS-SWAP-TRUNCATION
(2026-10-27; ``src/runtime/live_review_rows.py``). A per-row file lands on main as one compact
line in ``reviews.jsonl`` (main's one record). The legacy file is REFUSED, every row of it skipped
as ``shrunk: ...`` (exit 1), when a review_id that an earlier version of it on the branch carried
is gone at the tip (the 3f1546c2d truncation, 26 rows -> 4): nothing is mirrored from a shrunken
file. Per-row files still mirror. A per-row file that is not a row is skipped as ``schema: ...``.

Merged BY review_id, never by text concatenation: main's existing lines are
kept byte for byte and a review_id already on main is never re-added, so a
re-run is a no-op. A cited file that already exists on main with DIFFERENT
content is never overwritten: that row is skipped and reported (exit 1), the
rest still mirror.

Exit codes: 0 ok (``mirrored=N``, N may be 0; schema-refused rows are listed in ``skipped``
and logged, they are permanent on an append-only branch so they do not turn every later run red) ·
1 a row was skipped for a cited-file or id problem · 2 could not look.
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import check_live_review_records as rules  # noqa: E402
from src.runtime import live_review_rows as rows_lib  # noqa: E402
REVIEWS = "comms/live_review/reviews.jsonl"
#: how many earlier versions of the branch's legacy reviews.jsonl the shrink check compares against
HISTORY_DEPTH = 20
PACKETS = "comms/live_review/packets"


def git_show(ref: str, path: str, cwd: Path = ROOT) -> Optional[bytes]:
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=cwd, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def git_row_files(ref: str, cwd: Path = ROOT) -> Optional[List[str]]:
    """Paths of the per-row files at ``ref`` ([] when there are none); None when git cannot list."""
    r = subprocess.run(["git", "ls-tree", "--name-only", ref, "--", f"{rows_lib.ROWS_DIR}/"],
                       cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return [p for p in r.stdout.splitlines() if p.endswith(".json")]


def git_history(ref: str, path: str = REVIEWS, depth: int = HISTORY_DEPTH, cwd: Path = ROOT) -> Optional[List[bytes]]:
    """``path`` at each of the last ``depth`` commits on ``ref`` that changed it, excluding ``ref``'s own
    version; None when git cannot read the log (the caller then refuses the legacy file: could not check)."""
    r = subprocess.run(["git", "log", f"-{depth + 1}", "--format=%H", ref, "--", path],
                       cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = []
    for sha in r.stdout.split()[1:]:
        blob = git_show(sha, path, cwd)
        if blob is not None:
            out.append(blob)
    return out


def shrink_problem(tip_ids: set, history: Optional[List[bytes]]) -> Optional[str]:
    """Why the legacy file at the tip must not be read, or None. ``history`` = earlier versions."""
    if history is None:
        return f"shrunk: could not read the history of {REVIEWS} on the rows branch, so a shrink cannot be ruled out"
    before = set()
    for blob in history:
        before |= {r["review_id"] for r in rows_lib.parse_legacy(blob.decode(errors="replace"))[0]}
    lost = sorted(before - tip_ids)
    if lost:
        return (f"shrunk: {len(lost)} review_id(s) an earlier version of {REVIEWS} on the rows branch carried "
                f"are gone at the tip (first: {', '.join(lost[:3])}); restore the file on the branch")
    return None


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


def _branch_lines(read_rows: Callable[[str], Optional[bytes]], row_files: List[str],
                  history: Optional[List[bytes]], skipped: List[Dict[str, object]]
                  ) -> Optional[List[Tuple[Optional[str], str]]]:
    """(review_id, line) for every row on the branch: the legacy file's lines (unless it shrank),
    then the per-row files as compact lines, by (reviewed_at, review_id). None: nothing readable."""
    rows_raw = read_rows(REVIEWS)
    if rows_raw is None and not row_files:
        return None
    legacy = _ids(rows_raw.decode()) if rows_raw is not None else []
    file_rows = []
    for p in row_files:
        blob = read_rows(p)
        r, why = rows_lib.parse_row_file(p, blob.decode()) if blob is not None else (None, "unreadable")
        if r is None:
            # permanent on an append-only branch, like a schema refusal: visible, never a red run per hour
            skipped.append({"review_id": None, "why": f"schema: {p}: {why}"})
        else:
            file_rows.append(r)
    tip_ids = {rid for rid, _ in legacy if rid} | {r["review_id"] for r in file_rows}
    bad = shrink_problem(tip_ids, history) if rows_raw is not None else None
    if bad:
        skipped.append({"review_id": None, "why": bad})
        legacy = []
    have = {rid for rid, _ in legacy if rid}
    extra = [r for r in rows_lib.merge([], file_rows) if r["review_id"] not in have]
    return legacy + [(r["review_id"], json.dumps(r, separators=(",", ":"), ensure_ascii=False)) for r in extra]


def mirror(root: Path, read_rows: Callable[[str], Optional[bytes]],
           row_files: Optional[List[str]] = None, history: Optional[List[bytes]] = None,
           history_unreadable: bool = False) -> Dict[str, object]:
    """Apply the mirror to the checkout at ``root``. ``read_rows(path)`` reads the rows branch;
    ``row_files`` lists its per-row files; ``history`` = earlier versions of its legacy reviews.jsonl
    (``history_unreadable``: git could not read them, so the legacy file is refused)."""
    skipped: List[Dict[str, object]] = []
    branch = _branch_lines(read_rows, list(row_files or []),
                           None if history_unreadable else list(history or []), skipped)
    if branch is None:
        return {"state": "could_not_look", "reason": f"{REVIEWS} unreadable on the rows branch and no per-row files"}
    main_path = root / REVIEWS
    main_text = main_path.read_text() if main_path.exists() else ""
    have = {rid for rid, _ in _ids(main_text) if rid}
    new_lines, files = [], {}
    schema = json.loads(rules.SCHEMA.read_text())
    for rid, line in branch:
        if not rid:
            skipped.append({"review_id": None, "why": "row without a review_id / not JSON"})
            continue
        if rid in have:
            continue
        row = json.loads(line)
        bad = rules.row_problems(row, "reviews", schema) if isinstance(row, dict) else ["row is not an object"]
        if bad:
            skipped.append({"review_id": rid, "why": "schema: " + "; ".join(bad)})
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
        if not why and row.get("packet_sha"):
            pk = want.get(f"{PACKETS}/{rid}.json")
            bad = rules.packet_blob_problems(row, pk) if pk is not None else []
            if bad:
                skipped.append({"review_id": rid, "why": "schema: " + "; ".join(bad)})
                continue
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
    row_files = git_row_files(args.rows_ref)
    if row_files is None:
        res: Dict[str, object] = {"state": "could_not_look", "reason": f"cannot list {rows_lib.ROWS_DIR} on {args.rows_ref}"}
    else:
        hist = git_history(args.rows_ref)
        res = mirror(ROOT, lambda p: git_show(args.rows_ref, p), row_files, hist, history_unreadable=hist is None)
    print(json.dumps(res, indent=2))
    if res["state"] != "ok":
        return 2
    hard = [x for x in res["skipped"] if not str(x["why"]).startswith("schema: ")]
    for x in res["skipped"]:
        if x not in hard:
            print(f"::warning::rows-branch row {x['review_id']} refused by the schema, not mirrored: {x['why']}", file=sys.stderr)
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
