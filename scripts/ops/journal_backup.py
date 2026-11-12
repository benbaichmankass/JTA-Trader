"""Shared pre-APPLY journal backup with per-prefix retention (HEALTH-20261112-JOURNAL-BAK-RETENTION).

Thirteen Tier-2 writeback helpers (prop_report_close/open/skip, prop_ticket_expire/reissue,
prop_fix_mislinked_close, repair_prop_fill_direction, reconcile_orphan_history, backfill_intent_reduce_pnl,
backfill_own_fill_exits, supersede_*) copy the WHOLE
trade_journal.db (~2.7 GB on 2026-11-12) to ``<db>.bak-<tag>-<stamp>`` before every APPLY, and
nothing pruned at the writer. That is how the live VM's root disk regrew from 35.6 % free (11-04)
to 24 % free (11-11) after the previous manual prune.

``take_backup`` keeps the file name each helper always wrote, and after the new copy is
written and closed it deletes the OLDER backups of the SAME tag, keeping the newest
``KEEP_PER_PREFIX`` (counting the one just taken).

Why ``KEEP_PER_PREFIX = 1``: the copy taken before an apply is the rollback for THAT apply.
Older pre-apply states are covered by the off-VM daily backup (journal-offvm-backup.yml:
versioned private bucket, integrity + restore test on every run), so a second on-VM copy at
~2.7 GB each buys little against a disk with ~15 GB free (11-12), where a burst of applies
across several tags at N=2 could fill the disk the live trader writes to.

Safety order:
  * the new backup is written FIRST; pruning runs only after it succeeded, so a failed
    backup never removes the previous one;
  * only files matching ``<db basename>.bak-<tag>-<stamp>`` exactly (stamp = epoch digits or
    ``YYYYMMDDTHHMMSSZ``) in the DB's own directory are candidates, so a tag never matches
    another tag that shares its prefix, and the live DB / -wal / -shm can never match;
  * a prune failure is printed and swallowed (no-halt): the apply proceeds, the scheduled
    prune in journal-offvm-backup.yml catches it next day.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional

KEEP_PER_PREFIX = 1

_STAMP_RE = r"(?:\d+|\d{8}T\d{6}Z)"


def _stamp(style: str) -> str:
    if style == "epoch":
        return str(int(time.time()))
    if style == "iso":
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raise ValueError(f"unknown stamp style {style!r}")


def _infix(tag: str, tag_first: bool) -> str:
    # Two historical spellings, both matched by prune_db_backups.sh: <db>.bak-<tag>-<stamp>
    # (most helpers) and <db>.<tag>-bak-<stamp> (reconcile_orphan_history.py).
    return f".{tag}-bak-" if tag_first else f".bak-{tag}-"


def backup_path(db_path: str, tag: str, stamp_style: str = "epoch", *, tag_first: bool = False) -> str:
    return f"{db_path}{_infix(tag, tag_first)}{_stamp(stamp_style)}"


def _copy_online(db_path: str, dest: str, *, read_only: bool) -> None:
    uri = f"file:{db_path}?mode=ro" if read_only else db_path
    src = sqlite3.connect(uri, uri=read_only)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def same_tag_backups(db_path: str, tag: str, *, tag_first: bool = False) -> List[str]:
    """Existing backups of exactly this tag, newest first (mtime, then name)."""
    d = os.path.dirname(os.path.abspath(db_path))
    base = os.path.basename(db_path)
    pat = re.compile(rf"^{re.escape(base + _infix(tag, tag_first))}{_STAMP_RE}$")
    live = {base, f"{base}-wal", f"{base}-shm"}
    out = []
    for name in os.listdir(d):
        if name in live or not pat.match(name):
            continue
        p = os.path.join(d, name)
        if os.path.isfile(p) and not os.path.islink(p):
            out.append(p)
    out.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
    return out


def prune_tag(db_path: str, tag: str, *, keep: int = KEEP_PER_PREFIX,
              protect: Optional[str] = None, tag_first: bool = False) -> List[str]:
    """Delete same-tag backups beyond the newest ``keep``; never ``protect``. Returns deleted paths."""
    keep = max(1, int(keep))
    found = same_tag_backups(db_path, tag, tag_first=tag_first)
    if protect:
        prot = os.path.abspath(protect)
        found = [prot] + [p for p in found if os.path.abspath(p) != prot]
    deleted = []
    for p in found[keep:]:
        try:
            os.remove(p)
            deleted.append(p)
        except OSError as e:  # no-halt: report, never fail the apply
            print(f"journal_backup: could not prune {p}: {e}", file=sys.stderr)
    return deleted


def take_backup(db_path: str, tag: str, *, method: str = "online", stamp_style: str = "epoch",
                read_only: bool = True, keep: int = KEEP_PER_PREFIX, tag_first: bool = False) -> str:
    """Back up ``db_path`` to ``<db>.bak-<tag>-<stamp>`` then prune older same-tag copies.

    ``method``: ``online`` (sqlite backup API; consistent under a live writer) or ``copy``
    (shutil.copy2, kept for the helpers that always used it). Returns the new backup path.
    Raises if the backup itself fails (the caller must not apply without one).
    """
    dest = backup_path(db_path, tag, stamp_style, tag_first=tag_first)
    if method == "online":
        _copy_online(db_path, dest, read_only=read_only)
    elif method == "copy":
        shutil.copy2(db_path, dest)
    else:
        raise ValueError(f"unknown backup method {method!r}")
    try:
        deleted = prune_tag(db_path, tag, keep=keep, protect=dest, tag_first=tag_first)
    except Exception as e:  # noqa: BLE001 - no-halt: the backup exists, the apply may proceed
        print(f"journal_backup: prune of tag {tag!r} failed: {e}", file=sys.stderr)
        deleted = []
    for p in deleted:
        print(f"journal_backup: pruned older {tag} backup {os.path.basename(p)}", file=sys.stderr)
    return dest
