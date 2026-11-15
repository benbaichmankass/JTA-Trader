"""Readers for the decision sources a trade chart marks (UI-REDESIGN-2026-11 addendum 5).

* LTR review rows: main's ``comms/live_review/reviews.jsonl`` + per-row files on the ``live-review/rows`` branch
  (the local ref the rows watcher fetches) + rows submitted directly to the VM
  (``runtime_logs/live_review/direct/comms/live_review/rows/*.json``), deduped by ``review_id``.
* Directed-action receipts: ``runtime_logs/directed_actions/receipts.jsonl`` (one line per record).

Each returns ``{"state": read|absent|could_not_look, "rows": [...]}``; ``could_not_look`` is never folded into an
empty list that would read as "no decisions". Local reads only (no network on a request path).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _jsonl(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"state": "absent", "rows": []}
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError as exc:
        return {"state": "could_not_look", "rows": [], "reason": str(exc)}
    return {"state": "read", "rows": rows}


def load_reviews() -> Dict[str, Any]:
    try:
        from src.runtime import live_review_due as due
        main = due.read_reviews()
        if main.get("state") == "unreadable":
            return {"state": "could_not_look", "rows": [], "reason": main.get("error")}
        rows = list(main.get("rows") or [])
        branch = due.read_branch_rows()
        if branch.get("state") == "read":
            rows = due.merge_branch_rows(rows, branch.get("rows") or [])
        have = {r.get("review_id") for r in rows}
        try:
            from src.runtime import live_review_rows as rows_lib
            from src.runtime import live_review_rows_watch as watch
            d = Path(watch.direct_root()) / rows_lib.ROWS_DIR
            for p in sorted(d.glob("*.json")) if d.is_dir() else []:
                try:
                    r = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(r, dict) and r.get("review_id") and r["review_id"] not in have:
                    rows.append(r)
                    have.add(r["review_id"])
        except Exception:  # noqa: BLE001  # allow-silent: direct rows are a supplement; main + branch stand
            logger.warning("trade decision sources: direct rows unreadable", exc_info=True)
        # the branch ref is where fresh rows live; when it is unreadable, rows may be missing -> could_not_look
        state = "read" if branch.get("state") == "read" else "could_not_look"
        return {"state": state, "rows": rows, "branch_state": branch.get("state")}
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look, never an empty "no reviews"
        logger.warning("trade decision sources: reviews unreadable", exc_info=True)
        return {"state": "could_not_look", "rows": [], "reason": f"{type(exc).__name__}: {exc}"}


def load_receipts() -> Dict[str, Any]:
    try:
        from src.utils.paths import repo_root
        return _jsonl(os.path.join(repo_root(), "runtime_logs", "directed_actions", "receipts.jsonl"))
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
        return {"state": "could_not_look", "rows": [], "reason": f"{type(exc).__name__}: {exc}"}
