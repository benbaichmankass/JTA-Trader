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
decides WHEN to call it: once per new ``review_id`` whose recommendation is
(LTR-ALL-ACTIONS, mandate ``MD-TRADE-DESK``, 2026-10-26) one of the trade actions -- close, partial_close, move_tp, widen_sl, change_size,
add_entry -- on a dispatchable route, on ANY account class, paper included
(operator 2026-10-26: "All accounts now", "Real-money, prop and paper at once").
``hold``, ``operator_ask`` / ``none`` routes and ``flag_mechanics`` are logged
``not_dispatchable`` and never sent, so they cannot trip the dispatcher's
refusal ping. A class in ``rows_lib.ADVICE_ONLY_ACTIONS`` is ADVICE ONLY: on any route it is
logged ``advice_only`` and never sent (tighten_sl: operator 2026-10-28 ~20:35Z, "Advice-only
tightens (Recommended)"; every in-trade class: operator 2026-10-28 ~21:07Z, "Advice-only until
tested"). A class graduates by leaving that tuple, citing its passed test. ONE exception, per package:
an active ``kind: ltr_auto_apply`` entry in config/mandates.yaml that scopes the row's
order_package_id and action (``src/runtime/ltr_auto_mandate.py``; MD-LTR-ADA-AUTO, operator
2026-10-29 "VM applies it directly") makes that row a candidate; the receipt carries
``auto_mandate``, and the apply enforces that entry's bounds.

Cadence: ``ensure_started()`` (called from ``record_position_telemetry``,
which only runs while packages are open) starts ONE daemon thread, once, in
the live trader only. It fetches the rows branch into
``refs/live-review/live-review/rows`` (the dispatcher's own namespace; the
working tree, ``origin/*`` and ict-git-sync are untouched) every
``POLL_S`` seconds. It never touches the exit loop.

Rows (LTR-ROWS-SWAP-TRUNCATION, 2026-10-27): a reviewer creates ONE file,
``comms/live_review/rows/<review_id>.json``; the legacy ``reviews.jsonl`` is still read, so
nothing already written is lost (``src/runtime/live_review_rows.py``). A tip on which a
review_id this watcher already saw is gone, or on which the row count fell below the last
accepted tip's, is REFUSED: nothing is dispatched from it, ``fetch_state`` reads
``refused_shrunk``, ONE alert goes out per incident, and the next pass looks again (the fix
is to restore the file on the branch). No halting: the loop keeps polling.

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

DESK-4-INTAKE (2026-10-26): the same loop also fetches ``desk/decisions`` into
``refs/live-review/desk/decisions`` and, when its tip moved (or the last intake
could not look), runs ``scripts/ops/desk_intake.py --ref <tip> --apply`` as a
subprocess. That script validates each new desk decision row (schema v2) and
hands an in-trade action to ``live_review_apply.run()``; a ``propose_entry`` is
refused, named, while ``MD-TRADE-DESK``'s entry_generation is blocked. Its
receipts: ``desk_intake`` (``runtime_logs/desk/intake.jsonl``),
``desk_intake_status`` and ``desk_watch_status`` (this loop's fetch state).
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
from typing import Any, Callable, Dict, Optional, Tuple

from src.runtime import live_review_rows as rows_lib
from src.runtime import ltr_auto_mandate

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
ROWS_BRANCH = "live-review/rows"
LOCAL_REF = f"refs/live-review/{ROWS_BRANCH}"
REVIEWS_PATH = rows_lib.REVIEWS_PATH
DISPATCH = ROOT / "scripts" / "ops" / "live_review_dispatch.py"
DISPATCHABLE_ROUTES = ("recommended", "auto_applied")
POLL_S = 45
RETRY_WINDOW_S = 3600
FETCH_TIMEOUT_S = 30
DISPATCH_TIMEOUT_S = 600
DESK_BRANCH = "desk/decisions"
DESK_LOCAL_REF = f"refs/live-review/{DESK_BRANCH}"
DESK_INTAKE = ROOT / "scripts" / "ops" / "desk_intake.py"

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


#: tighten_sl plus the trade-desk actions (LTR-ALL-ACTIONS); every one is re-checked by the dispatcher.
#: rows_lib.ADVICE_ONLY_ACTIONS (every in-trade class until it graduates, operator 2026-10-28) is checked FIRST and is never sent.
DISPATCHABLE_ACTIONS = ("tighten_sl", "close", "partial_close", "move_tp", "widen_sl", "change_size", "add_entry")


def dispatchable(row: Dict[str, Any],
                 auto: Callable[[Dict[str, Any]], Optional[str]] = ltr_auto_mandate.exception_for) -> Optional[str]:
    """None when the row is an apply candidate; else why it is not (logged, never sent).
    An advice-only class returns rows_lib.ADVICE_ONLY_VERDICT on every route: recorded as advice, never executed,
    UNLESS an active per-package auto mandate (``ltr_auto_mandate``, read from config/mandates.yaml) scopes this
    row's order_package_id and action (MD-LTR-ADA-AUTO, operator 2026-10-29): then it is a candidate like any other."""
    rec = row.get("recommendation") or {}
    if rec.get("action") in rows_lib.ADVICE_ONLY_ACTIONS and not auto(row):
        return rows_lib.ADVICE_ONLY_VERDICT
    if rec.get("action") not in DISPATCHABLE_ACTIONS:
        return f"action_{rec.get('action')}"
    route = (row.get("disposition") or {}).get("route")
    if route not in DISPATCHABLE_ROUTES:
        return f"route_{route}"
    return None


def _alert(text: str) -> bool:
    """ONE operator flag on the alert channel. Never raises."""
    try:
        from src.runtime import telegram_channels
        return bool(telegram_channels.send("alert", text))
    except Exception:  # noqa: BLE001
        logger.warning("rows-watch: alert send failed", exc_info=True)
        return False


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
             now_fn: Callable[[], datetime] = _now, logs: Optional[Path] = None,
             alert: Callable[[str], bool] = _alert) -> Dict[str, Any]:
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
    read = rows_lib.read_at(tip, git) if rc == 0 else {"state": "could_not_read", "detail": tip}
    if read["state"] != "ok":
        status.update(fetch_state="could_not_read", detail=str(read.get("detail"))[-200:])
        _write_json(status_path, status)
        return status
    rows = read["rows"]
    state = _load(state_path)
    status.update(fetch_state="fetched", tip=tip, rows=len(rows), legacy_rows=read["legacy_rows"],
                  file_rows=read["file_rows"], bad_lines=read["bad_lines"], bad_files=len(read["bad_files"]))
    if state is None:
        state = {"seeded_at": seen_at.isoformat(), "seeded_tip": tip,
                 "seen": sorted(r["review_id"] for r in rows), "pending": {}, "tip_rows": len(rows)}
        _write_json(state_path, state)
        status.update(new=0, seeded=len(state["seen"]))
        _write_json(status_path, status)
        return status
    seen = set(state.get("seen") or [])
    lost = rows_lib.lost_ids(seen, rows)
    prev_rows = state.get("tip_rows")
    if lost or (isinstance(prev_rows, int) and len(rows) < prev_rows):
        # Never act on a shrunken file: refuse this tip, flag once, look again next pass (no halting).
        detail = (f"rows branch shrank at {tip[:12]}: {len(rows)} rows < {prev_rows} at the last accepted tip"
                  f"; {len(lost)} already-seen review_id(s) gone (first: {', '.join(lost[:3]) or '-'})"
                  f"; {read['bad_lines']} unparseable line(s)")
        status.update(fetch_state="refused_shrunk", detail=detail, lost=len(lost), new=0)
        flag = state.get("shrink_alerted") or {}
        if not flag:
            sent = alert(f"⚠️ live-review rows watcher REFUSED {ROWS_BRANCH} tip {tip[:12]}: {detail}. "
                         f"Nothing is applied from it. Restore {REVIEWS_PATH} on the branch "
                         f"(the 2026-10-27 truncation repair, fb2640ef8, is the pattern).")
            flag = {"at": seen_at.isoformat(), "sent": sent}
        if flag.get("tip") != tip:  # one receipt line per refused tip, not one per 45 s pass
            _append(log_path, {"verdict": "refused_shrunk", "ref": tip, "seen_at": seen_at.isoformat(),
                               "detail": detail, "lost": lost[:20]})
            state["shrink_alerted"] = dict(flag, tip=tip)
            _write_json(state_path, state)
        _write_json(status_path, status)
        return status
    if state.pop("shrink_alerted", None):
        status["shrink_cleared"] = True
    pending: Dict[str, Any] = state.get("pending") or {}
    new = [r for r in rows if r["review_id"] not in seen]
    status["new"] = len(new)
    for row in new:
        rid = row["review_id"]
        first = _ts((pending.get(rid) or {}).get("first_seen_at")) or seen_at
        rec: Dict[str, Any] = {"review_id": rid, "order_package_id": row.get("order_package_id"),
                               "ref": tip, "reviewed_at": row.get("reviewed_at"),
                               "seen_at": first.isoformat()}
        _proof(lambda fp: fp.record_row(row, at=first))
        why = dispatchable(row)
        auto_id = ltr_auto_mandate.exception_for(row) if why is None else None
        if auto_id:
            rec["auto_mandate"] = auto_id
        if why == rows_lib.ADVICE_ONLY_VERDICT:
            rec.update(verdict=why, detail=f"advice only: {(row.get('recommendation') or {}).get('action')} "
                                           f"level {(row.get('recommendation') or {}).get('level')} not executed")
        elif why:
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
            if res.get("exit") in (0, 1, 2) and res.get("verdict") == "dispatched":
                _proof(lambda fp: fp.record("S4_pickup", at=done, review_id=rid, leg=row.get("leg"),
                                            accounts=list(row.get("accounts") or [])))
                entry = _applied_entry(d / "applied.jsonl", rid)
                _proof(lambda fp: fp.record_writeback(row, entry, at=_ts((entry or {}).get("at")) or done))
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
    state.update(seen=sorted(seen), pending=pending, tip_rows=len(rows))
    _write_json(state_path, state)
    _write_json(status_path, status)
    return status


def _proof(fn: Callable[[Any], Any]) -> None:
    """LTR first-proof pings (best-effort; src/runtime/ltr_first_proof.py)."""
    try:
        from src.runtime import ltr_first_proof
        fn(ltr_first_proof)
    except Exception:  # noqa: BLE001
        logger.debug("rows-watch: first-proof ping failed", exc_info=True)


def _applied_entry(path: Path, review_id: str) -> Optional[Dict[str, Any]]:
    """The apply's newest applied.jsonl writeback for ``review_id``."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    for ln in reversed(lines[-500:]):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("review_id") == review_id:
            return e
    return None


def _desk_intake(tip: str) -> Dict[str, Any]:
    """Run the desk intake at the pinned tip with --apply. Never raises."""
    try:
        r = subprocess.run([sys.executable, str(DESK_INTAKE), "--ref", tip, "--apply"],
                           cwd=ROOT, capture_output=True, text=True, timeout=DISPATCH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"exit": 3, "detail": f"desk intake did not run: {type(exc).__name__}"}
    summary: Dict[str, Any] = {}
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("{"):
            try:
                summary = json.loads(ln)
            except ValueError:
                pass
    return {"exit": r.returncode, "new": summary.get("new"), "detail": summary.get("detail")
            or (r.stderr or "").strip()[-200:] or None}


def run_desk_pass(git: Git = _git, intake: Callable[[str], Dict[str, Any]] = _desk_intake,
                  now_fn: Callable[[], datetime] = _now, logs: Optional[Path] = None) -> Dict[str, Any]:
    """One fetch of desk/decisions -> the desk intake, only when the tip moved or the last intake
    could not look (exit 3: a row is pending a retry). Dedupe and retries live in the intake."""
    d = logs or log_dir()
    status_path = d / "desk_watch_status.json"
    prev = _load(status_path) or {}
    status: Dict[str, Any] = {"pass_at": now_fn().isoformat()}
    rc, out = git("fetch", "--quiet", "--no-write-fetch-head", "origin", f"+refs/heads/{DESK_BRANCH}:{DESK_LOCAL_REF}")
    if rc != 0:
        status.update(fetch_state="could_not_fetch", detail=out[-200:], tip=prev.get("tip"),
                      intake_exit=prev.get("intake_exit"))
        _write_json(status_path, status)
        return status
    rc, tip = git("rev-parse", DESK_LOCAL_REF)
    if rc != 0:
        status.update(fetch_state="could_not_read", detail=tip[-200:])
        _write_json(status_path, status)
        return status
    status.update(fetch_state="fetched", tip=tip)
    if tip == prev.get("tip") and prev.get("intake_exit") in (0, 1, 2):
        status.update(intake="unchanged", intake_exit=prev.get("intake_exit"))
    else:
        res = intake(tip)
        status.update(intake="ran", intake_exit=res.get("exit"), new=res.get("new"), detail=res.get("detail"))
    _write_json(status_path, status)
    return status


def _loop() -> None:
    _proof(lambda fp: fp.ensure_seeded())
    while True:
        for one in (run_pass, run_desk_pass):
            try:
                one()
            except Exception:  # noqa: BLE001 — contained; the next pass tries again (no halting)
                logger.warning("rows-watch: %s failed", one.__name__, exc_info=True)
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
