"""Live review ROWS WATCHER, VM side (LTR C1): a new rows-branch row -> the apply, no human hop.

Operator, 2026-10-26 ~11:40Z popup: "VM applies from rows branch". A reviewer
pushes its row to ``live-review/rows`` (skill Step 6.3 / REVIEWER-BRIEF.md);
this loop, inside the live trader, notices it and runs
``scripts/ops/live_review_dispatch.py --review-id <id> --ref <tip> --apply``
itself. That replaces the manager filing the ``live-review-apply``
system-action, which stays as the manual fallback.

NOTHING about the apply changes. The dispatcher still re-checks every mandate
clause on the row at the pinned commit, refuses a duplicate review_id through
``runtime_logs/live_review/dispatch_state.json``, and hands over to
``live_review_apply.py``, where each account decides through its own
``RiskManager.approve_amend`` and the venue is read back. This file only
decides WHEN to call it: once per new ``review_id`` whose recommendation is a
``tighten_sl`` on a dispatchable route (``hold``, ``operator_ask``,
``flag_mechanics`` and paper rows are logged ``not_dispatchable`` and never
sent, so they cannot trip the dispatcher's refusal ping).

Cadence: ``ensure_started()`` (called from ``record_position_telemetry``,
which only runs while packages are open) starts ONE daemon thread, once, in
the live trader only. It fetches the rows branch into
``refs/live-review/live-review/rows`` (the dispatcher's own namespace; the
working tree, ``origin/*`` and ict-git-sync are untouched) every
``POLL_S`` seconds. It never touches the exit loop.

First start: every review_id already on the branch is SEEDED as seen and never
dispatched, so a restart cannot replay old decisions. A dispatch that could not
look (exit 3) is retried on later passes for ``RETRY_WINDOW_S``; past that the
decision is stale and is logged ``expired``. There is no halting.

Receipts (diag ``log_file`` names):
* ``live_review_rows_watch`` -> ``runtime_logs/live_review/rows_watch.jsonl``:
  one line per new row: review_id, ref, verdict, exit, the per-account
  ``>>>`` lines (APPLIED / refused, executor, ``venue_after``) and the
  latencies ``reviewed_at -> seen_at -> done_at``.
* ``live_review_rows_watch_status`` -> ``rows_watch_status.json``: the last
  pass (fetch state, tip, counts), so "no new rows" and "could not fetch" are
  readable apart.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
ROWS_BRANCH = "live-review/rows"
LOCAL_REF = f"refs/live-review/{ROWS_BRANCH}"
REVIEWS_PATH = "comms/live_review/reviews.jsonl"
DISPATCH = ROOT / "scripts" / "ops" / "live_review_dispatch.py"
DISPATCHABLE_ROUTES = ("recommended", "auto_applied")
POLL_S = 45
RETRY_WINDOW_S = 3600
FETCH_TIMEOUT_S = 30
DISPATCH_TIMEOUT_S = 600

_started = False
_start_lock = threading.Lock()


def log_dir() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / "live_review"


def _is_live_trader() -> bool:
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    return getattr(spec, "name", None) == "src.main"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


Git = Callable[..., Tuple[int, str]]


def _git(*args: str, timeout: int = FETCH_TIMEOUT_S) -> Tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, type(exc).__name__
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).strip()


def _dispatch(review_id: str, ref: str) -> Dict[str, Any]:
    """Run the dispatcher with --apply at the pinned ref. Never raises."""
    try:
        r = subprocess.run([sys.executable, str(DISPATCH), "--review-id", review_id, "--ref", ref, "--apply"],
                           cwd=ROOT, capture_output=True, text=True, timeout=DISPATCH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"exit": 3, "verdict": "could_not_look", "detail": f"dispatcher did not run: {type(exc).__name__}",
                "lines": []}
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.startswith(">>>")]
    summary: Dict[str, Any] = {}
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("{"):
            try:
                summary = json.loads(ln)
            except ValueError:
                pass
    return {"exit": r.returncode, "verdict": summary.get("verdict"), "detail": summary.get("detail"),
            "lines": lines[-20:]}


def dispatchable(row: Dict[str, Any]) -> Optional[str]:
    """None when the row is an apply candidate; else why it is not (logged, never sent)."""
    rec = row.get("recommendation") or {}
    if rec.get("action") != "tighten_sl":
        return f"action_{rec.get('action')}"
    route = (row.get("disposition") or {}).get("route")
    if route not in DISPATCHABLE_ROUTES:
        return f"route_{route}"
    return None


def _rows(text: str) -> List[Dict[str, Any]]:
    out = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("review_id"):
            out.append(r)
    return out


def _load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write_json(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str) + "\n")
    os.replace(tmp, path)


def _append(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(doc, default=str, separators=(",", ":")) + "\n")


def run_pass(git: Git = _git, dispatch: Callable[[str, str], Dict[str, Any]] = _dispatch,
             now_fn: Callable[[], datetime] = _now, logs: Optional[Path] = None) -> Dict[str, Any]:
    """One fetch -> zero or more dispatches. Returns the status it wrote."""
    d = logs or log_dir()
    state_path, status_path, log_path = d / "rows_watch_state.json", d / "rows_watch_status.json", d / "rows_watch.jsonl"
    seen_at = now_fn()
    status: Dict[str, Any] = {"pass_at": seen_at.isoformat()}
    rc, out = git("fetch", "--quiet", "--no-write-fetch-head", "origin", f"+refs/heads/{ROWS_BRANCH}:{LOCAL_REF}")
    if rc != 0:
        status.update(fetch_state="could_not_fetch", detail=out[-200:])
        _write_json(status_path, status)
        return status
    rc, tip = git("rev-parse", LOCAL_REF)
    rc2, text = git("show", f"{tip}:{REVIEWS_PATH}") if rc == 0 else (1, "")
    if rc != 0 or rc2 != 0:
        status.update(fetch_state="could_not_read", detail=(tip if rc else text)[-200:])
        _write_json(status_path, status)
        return status
    rows = _rows(text)
    state = _load(state_path)
    status.update(fetch_state="fetched", tip=tip, rows=len(rows))
    if state is None:
        state = {"seeded_at": seen_at.isoformat(), "seeded_tip": tip,
                 "seen": sorted(r["review_id"] for r in rows), "pending": {}}
        _write_json(state_path, state)
        status.update(new=0, seeded=len(state["seen"]))
        _write_json(status_path, status)
        return status
    seen = set(state.get("seen") or [])
    pending: Dict[str, Any] = state.get("pending") or {}
    new = [r for r in rows if r["review_id"] not in seen]
    status["new"] = len(new)
    for row in new:
        rid = row["review_id"]
        first = _ts((pending.get(rid) or {}).get("first_seen_at")) or seen_at
        rec: Dict[str, Any] = {"review_id": rid, "order_package_id": row.get("order_package_id"),
                               "ref": tip, "reviewed_at": row.get("reviewed_at"),
                               "seen_at": first.isoformat()}
        why = dispatchable(row)
        if why:
            rec.update(verdict="not_dispatchable", detail=why)
        else:
            res = dispatch(rid, tip)
            done = now_fn()
            rec.update(exit=res.get("exit"), verdict=res.get("verdict"), detail=res.get("detail"),
                       lines=res.get("lines"), done_at=done.isoformat(),
                       seen_to_done_s=round((done - first).total_seconds(), 1))
            rv = _ts(row.get("reviewed_at"))
            if rv:
                rec["reviewed_to_done_s"] = round((done - rv).total_seconds(), 1)
            if res.get("exit") == 3:
                if (done - first).total_seconds() < RETRY_WINDOW_S:
                    att = int((pending.get(rid) or {}).get("attempts") or 0) + 1
                    pending[rid] = {"first_seen_at": first.isoformat(), "attempts": att}
                    if att == 1 or att % 10 == 0:
                        _append(log_path, dict(rec, retrying=True, attempts=att))
                    continue
                rec["verdict"] = "expired"
        pending.pop(rid, None)
        seen.add(rid)
        _append(log_path, rec)
    state.update(seen=sorted(seen), pending=pending)
    _write_json(state_path, state)
    _write_json(status_path, status)
    return status


def _loop() -> None:
    while True:
        try:
            run_pass()
        except Exception:  # noqa: BLE001 — contained; the next pass tries again (no halting)
            logger.warning("rows-watch: pass failed", exc_info=True)
        time.sleep(POLL_S)


def ensure_started(force: bool = False) -> bool:
    """Start the watcher thread once per process. Never blocks, never raises."""
    global _started
    try:
        if _started or not (force or _is_live_trader()):
            return False
        if not _start_lock.acquire(blocking=False):
            return False
        try:
            if _started:
                return False
            threading.Thread(target=_loop, name="ltr-rows-watch", daemon=True).start()
            _started = True
            return True
        finally:
            _start_lock.release()
    except Exception:  # noqa: BLE001
        return False
