"""Plan (and with --apply, delete) STALE rotated log files under runtime_logs/.

Candidates are files that are (a) older than --days by mtime (so nothing is being written to them), (b) a
ROTATED or log-shaped artifact by name (``*.log``, ``*.log.*``, ``*.jsonl.gz``, ``*.jsonl.<date>``,
``*.<YYYY-MM-DD>.jsonl``), and (c) not on the never-touch list (databases, ``operator_actions/``,
``pending_claude_pings/``, anything with ``.db`` / ``.sqlite`` in the name). A live ``*.jsonl`` that is simply old
is NOT a candidate: a big live file needs its own writer-side cap, not a delete. Dry-run unless --apply.
The report prints the per-top-level-directory byte totals so the operator sees what the 11 GB is BEFORE any delete.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

NEVER_DIRS = {"operator_actions", "pending_claude_pings"}
NEVER_SUBSTR = (".db", ".sqlite", "-wal", "-shm")
ROTATED = (re.compile(r"\.log$"), re.compile(r"\.log\.[^/]+$"), re.compile(r"\.jsonl\.gz$"),
           re.compile(r"\.jsonl\.\d{4}-\d{2}-\d{2}"), re.compile(r"\.\d{4}-\d{2}-\d{2}\.jsonl"))


def _root() -> Path:
    from src.utils.paths import runtime_logs_dir
    return Path(runtime_logs_dir())


def is_candidate(rel: Path) -> bool:
    if rel.parts and rel.parts[0] in NEVER_DIRS:
        return False
    name = rel.name
    if any(s in name for s in NEVER_SUBSTR):
        return False
    return any(r.search(name) for r in ROTATED)


def plan(root: Path, days: int, now: Optional[float] = None) -> Tuple[List[Tuple[Path, int]], Dict[str, int]]:
    """([(path, bytes)] to delete, {top-level dir: total bytes}). Symlinks are never followed or deleted."""
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    victims: List[Tuple[Path, int]] = []
    totals: Dict[str, int] = {}
    for p in root.rglob("*"):
        try:
            if p.is_symlink() or not p.is_file():
                continue
            st = p.stat()
        except OSError:
            continue
        rel = p.relative_to(root)
        top = rel.parts[0] if len(rel.parts) > 1 else "(files at root)"
        totals[top] = totals.get(top, 0) + st.st_size
        if st.st_mtime < cutoff and is_candidate(rel):
            victims.append((p, st.st_size))
    return victims, totals


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", help="override (tests only)")
    a = ap.parse_args(argv)
    if a.days < 1:
        ap.error("--days must be >= 1")
    root = Path(a.root) if a.root else _root()
    victims, totals = plan(root, a.days)
    print(f"runtime_logs root: {root}")
    print("per top-level directory (bytes):")
    for k, v in sorted(totals.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {v:>14,}  {k}")
    freed = sum(b for _, b in victims)
    print(f"candidates older than {a.days}d: {len(victims)} file(s), {freed:,} bytes")
    for p, b in sorted(victims, key=lambda x: -x[1])[:40]:
        print(f"  DELETE {b:>14,}  {p.relative_to(root)}")
    if not a.apply:
        print("DRY-RUN: nothing deleted. Re-dispatch with apply: true.")
        return 0
    n = 0
    for p, _ in victims:
        try:
            p.unlink()
            n += 1
        except OSError as exc:
            print(f"  FAILED {p}: {exc}")
    print(f"APPLIED: deleted {n}/{len(victims)} file(s).")
    return 0 if n == len(victims) else 3


if __name__ == "__main__":
    sys.exit(main())
