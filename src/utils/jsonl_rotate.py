"""Writer-side size-based rotation for append-only ``runtime_logs/*.jsonl`` files.

VM-DISK-GROWTH-20261102: ``signal_audit.jsonl`` (1.5 GB) and
``position_read_state_soak.jsonl`` (343 MB) had no cap. ``cap_runtime_logs.py``
deliberately never deletes a live ``*.jsonl`` ("a big live file needs its own
writer-side cap"); this is that cap.

When the live file reaches ``max_bytes`` it is renamed (atomic) to
``<name>.<YYYY-MM-DDTHHMMSSZ>`` and a background thread gzips it to
``<name>.<stamp>.gz`` (tmp + rename, then the plain copy is removed). The names
match ``cap_runtime_logs.ROTATED`` (``\\.jsonl\\.\\d{4}-\\d{2}-\\d{2}``), so
``cap-vm-logs target=runtime_logs`` prunes old rotations by age.

MUST NEVER RAISE: rotation is best-effort and sits on the tick path; the append
itself always happens. The live path is re-created by the append, so readers of
the live file see a short file, never a missing one for more than an instant.
"""
from __future__ import annotations

import gzip
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List

ENV_MAX_MB = "JSONL_ROTATE_MAX_MB"


def _max_bytes(default_mb: int) -> int:
    try:
        mb = float(os.environ.get(ENV_MAX_MB, "") or default_mb)
    except ValueError:
        mb = default_mb
    return int(max(mb, 0.001) * 1024 * 1024)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _gzip_file(src: Path) -> None:
    dst = Path(str(src) + ".gz")
    tmp = Path(str(dst) + ".tmp")
    try:
        with src.open("rb") as fi, gzip.open(tmp, "wb", compresslevel=3) as fo:
            shutil.copyfileobj(fi, fo, 1024 * 1024)
        os.replace(tmp, dst)
        src.unlink()
    except Exception:  # noqa: BLE001 - leave the plain rotated copy; cap-vm-logs still ages it out
        try:
            tmp.unlink()
        except OSError:
            pass


def rotate_if_needed(path: Path, default_mb: int, *, background: bool = True) -> bool:
    """Rotate ``path`` if it is >= the cap. Returns True if it rotated. Never raises."""
    try:
        if path.stat().st_size < _max_bytes(default_mb):
            return False
        rotated = path.with_name(f"{path.name}.{_stamp()}")
        # Same-second collision (plain OR already-gzipped): skip -- the live file just grows a
        # little past the cap; renaming over it would let a later gzip overwrite rows.
        if rotated.exists() or Path(str(rotated) + ".gz").exists():
            return False
        os.rename(path, rotated)  # atomic; a racing process loses with FileNotFoundError
    except Exception:  # noqa: BLE001
        return False
    try:
        if background:
            threading.Thread(target=_gzip_file, args=(rotated,), daemon=True).start()
        else:
            _gzip_file(rotated)
    except Exception:  # noqa: BLE001
        pass
    return True


def append_line(path: Path, line: str, default_mb: int) -> None:
    """Append ``line`` (already newline-terminated) to ``path``, rotating first if over the cap."""
    rotate_if_needed(path, default_mb)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def rotated_siblings(path: Path) -> List[Path]:
    """Rotated files of ``path`` (``.gz`` and not-yet-gzipped), oldest first, excluding ``*.tmp``."""
    out = [p for p in path.parent.glob(path.name + ".*")
           if not p.name.endswith(".tmp") and p.is_file()]
    names = {p.name for p in out}
    # While gzip is finishing both exist: the .gz is complete (it is renamed in last), keep only it.
    out = [p for p in out if p.name.endswith(".gz") or p.name + ".gz" not in names]
    return sorted(out, key=lambda p: p.name.removesuffix(".gz"))


def open_rotated(p: Path):
    """Binary line-iterable handle for a rotated file (gz or plain)."""
    return gzip.open(p, "rb") if p.name.endswith(".gz") else p.open("rb")
