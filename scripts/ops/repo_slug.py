# wiring: manual-only - this is a LIBRARY (imported by manager_view / session_reaper); it has no schedule of its own.
"""This repository's name, for string compares (RENAME-SLUG-FUNCTIONAL-AUDIT).

CLAUDE.md § Repo identity: "Tooling reads the repo slug from GITHUB_REPOSITORY / git remote, never a literal". After the
2026-10-28 rename (Metis-Insights -> JTA-Trader) every literal that is MATCHED AS A STRING (a permission pattern, an
equality compare, a prefix) silently stopped matching; redirects only cover URLs and API calls. This module is the one
place that knows the name.

* :func:`current_name`: ``GITHUB_REPOSITORY`` (runner), else the ``origin`` remote, else ``JTA-Trader``.
* :func:`is_this_repo`: True for the current name AND every historical name in :data:`HISTORICAL_NAMES`,
  case-insensitively, because register rows written before a rename still carry the old name (``Metis-Insights#10654``).
A future rename adds its old name to HISTORICAL_NAMES; nothing else here changes.
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

FALLBACK = "JTA-Trader"
HISTORICAL_NAMES = ("Metis-Insights", "ict-trading-bot")


def _from_remote() -> Optional[str]:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=5,
                             cwd=str(Path(__file__).resolve().parents[2])).stdout.strip()
    except Exception:  # noqa: BLE001 -- no git: fall back
        return None
    name = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    name = name[:-4] if name.lower().endswith(".git") else name
    return name or None


@lru_cache(maxsize=1)
def current_name() -> str:
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" in env:
        return env.split("/", 1)[1]
    remote = _from_remote()
    # A session's proxy remote can be a lower-cased local path; prefer the canonical spelling when it is ours.
    if remote and remote.lower() == FALLBACK.lower():
        return FALLBACK
    return remote or FALLBACK


def is_this_repo(name: Optional[str]) -> bool:
    if not name:
        return False
    n = str(name).strip().split("/")[-1].lower().removesuffix(".git")
    return n in {current_name().lower(), FALLBACK.lower(), *(h.lower() for h in HISTORICAL_NAMES)}


__all__ = ["current_name", "is_this_repo", "HISTORICAL_NAMES", "FALLBACK"]
