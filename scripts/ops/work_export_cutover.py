"""The work-store export's CUTOVER for old debt (row AM-OPS-9 / STORE-EXPORT-BACKFILL-258).

Gates this adds or changes: none added; narrows roadmap-map, soak-contract and claim-basis to skip rows
whose store updated_at <= export_base_at (pre-cutover debt, tracked on STORE-EXPORT-BACKFILL-258).

Since the WSD-S4 freeze the checklist row files and pipeline record files are an EXPORT of the work
store (``scripts/ops/work.py export --to-files``). The export runs the same row checks the three
guards use on each changed row/record and holds a failing one back -- EXCEPT a row/record whose
store ``updated_at`` is <= ``export_base_at`` (a key in ``docs/claude/work/checklist/_header.json``):
that is debt from before the export ran, it lands, and the guards skip it in their diff-scoped checks.

The row files do not carry the store's ``updated_at`` (a store-native row or an observation's record
has no such key, and adding one would break "the files equal the store"), so the export writes a
side file, ``docs/claude/work/EXPORT-STAMPS.json``: for every file the LAST export wrote, its store
``updated_at`` and the sha256 of the bytes written. A guard treats a changed file as exempt only
when its stamp is <= ``export_base_at`` AND the file's current bytes still hash to the stamp -- so a
hand edit to an exported file is never exempt. No stamp, no ``export_base_at`` -> nothing is exempt
(the guards behave exactly as before).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

HEADER_REL = "docs/claude/work/checklist/_header.json"
STAMPS_REL = "docs/claude/work/EXPORT-STAMPS.json"
KEY = "export_base_at"


def _ts(v) -> datetime | None:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        return datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def base_at(root) -> str | None:
    """``export_base_at`` from the register header under ``root``; None when absent/unreadable."""
    try:
        v = json.loads((Path(root) / HEADER_REL).read_text(encoding="utf-8")).get(KEY)
    except (OSError, ValueError, AttributeError):
        return None
    return v if _ts(v) is not None else None


def is_pre_cutover(updated_at, base) -> bool:
    """The store ``updated_at`` is at or before the cutover (both parseable ISO timestamps)."""
    u, b = _ts(updated_at), _ts(base)
    return u is not None and b is not None and u <= b


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_stamps(root) -> dict:
    try:
        d = json.loads((Path(root) / STAMPS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = d.get("files") if isinstance(d, dict) else None
    return files if isinstance(files, dict) else {}


def exempt_paths(root) -> set[str]:
    """Repo-relative paths of exported files the guards skip: stamp <= export_base_at and the file's
    bytes are still the bytes the export wrote."""
    root = Path(root)
    base = base_at(root)
    if base is None:
        return set()
    out = set()
    for rel, st in load_stamps(root).items():
        if not isinstance(st, dict) or not is_pre_cutover(st.get("updated_at"), base):
            continue
        try:
            if sha((root / rel).read_bytes()) == st.get("sha256"):
                out.add(rel)
        except OSError:
            continue
    return out
