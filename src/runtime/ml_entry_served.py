"""The ONE served-ENTRY-model pointer (row ML-ENTRY-RETRAIN-CADENCE; Tier 2/3, held PR).

``ml/served/ENTRY_SERVED.json`` names the directory under ``ml/served/`` whose ``model.json`` the ``ml_entry`` leg serves
(``{"artifact_dir": "ml_decision_entry_v1", ...}``). A promoted candidate adds a NEW directory and repoints this file; the
old directory stays, so a revert is a one-line edit of the pointer. Absent or unusable pointer -> the original v1 directory,
with a WARNING (never a crash: the trader does not halt on a bad pointer, it serves what it served before).

Pure stdlib so the trader's strategy module, the live monitor and the research scripts can all import it.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SERVED_ROOT = Path(__file__).resolve().parents[2] / "ml" / "served"
POINTER = SERVED_ROOT / "ENTRY_SERVED.json"
DEFAULT_DIR = "ml_decision_entry_v1"
_DIR_RE = re.compile(r"^ml_decision_entry_v1(r[0-9]{8})?$")   # v1 or a dated revision of the v1 recipe; v2 is a different leg


def served_dir(pointer: Optional[Path] = None, root: Optional[Path] = None) -> str:
    pointer = pointer or POINTER
    root = root or SERVED_ROOT
    try:
        name = str(json.loads(pointer.read_text(encoding="utf-8"))["artifact_dir"])
        if not _DIR_RE.match(name):
            raise ValueError(f"artifact_dir {name!r} is not ml_decision_entry_v1[rYYYYMMDD]")
        if not (root / name / "model.json").is_file():
            raise FileNotFoundError(f"{name}/model.json missing")
        return name
    except FileNotFoundError as exc:
        if pointer.exists():
            logger.warning("ml_entry_served: pointer unusable (%s); serving %s", exc, DEFAULT_DIR)
        return DEFAULT_DIR
    except Exception as exc:  # noqa: BLE001  # allow-silent: logged; falls back to the previously served directory
        logger.warning("ml_entry_served: pointer unusable (%s: %s); serving %s", type(exc).__name__, exc, DEFAULT_DIR)
        return DEFAULT_DIR


def served_artifact(pointer: Optional[Path] = None, root: Optional[Path] = None) -> Path:
    return (root or SERVED_ROOT) / served_dir(pointer, root) / "model.json"
