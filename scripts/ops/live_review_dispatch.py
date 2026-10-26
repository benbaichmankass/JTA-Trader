#!/usr/bin/env python3
"""Dispatch ONE committed live-review row to the per-account apply (LTR-APPLY-DISPATCH).

Why this exists
---------------
Lane LTR-JUDGEMENT-APPLY found on 2026-10-26 07:01Z that nothing ran
``scripts/ops/live_review_apply.py --apply``. ``config/live_trade_review.yaml``
read ``apply_mode: apply`` and ``MD-LIVE-TIGHTEN-SL`` was granted, but the only
system-action was ``live-review-dry-run``. So no reviewed ``tighten_sl`` could
reach a venue. The operator chose the fix by popup at about 07:12Z 2026-10-26,
verbatim: "Yes, top of the queue (Recommended)".

This is the bridge from a review row to that apply. It adds **no order path**:
every account still decides through its own ``RiskManager.approve_amend`` and
its own executor inside ``live_review_apply.py``. This file only decides
whether a row may be handed over at all.

1. **Resolve the row.** The row is read from the COMMITTED
   ``comms/live_review/reviews.jsonl`` at ``HEAD`` (``git show``), never from a
   working-tree edit. On the VM, ``HEAD`` is ``main`` as pulled by
   ``ict-git-sync``. A row that is not there yet is ``could_not_look``
   (exit 3): git-sync may lag by up to ~5 min, so re-dispatch.
2. **Re-check the mandate's package-level clauses** on the row itself. A failed
   clause is a refusal (exit 2) and nothing is sent:
   ``recommendation.action == tighten_sl``, a positive ``level``,
   ``mechanics.verdict == match``, ``disposition.route`` of ``recommended`` or
   ``auto_applied`` (an ``operator_ask`` row is never dispatched), the
   ``outcome_table_source`` committed at ``HEAD``, and the basis:

   * ``table``: the LTR-0 table's ``read_state`` is ``measured`` (n >= its
     floor), ``ev_delta_r >= -0.25`` (operator Q1) and ``worst_case_delta_r > 0``;
   * ``judgement`` (PR #20259, LTR-JUDGEMENT-APPLY): a
     ``judgement_confidence`` in [0, 1] and a non-empty ``reason``.
3. **Idempotent per review_id.** ``runtime_logs/live_review/dispatch_state.json``
   (VM-local) records each apply dispatch. A review_id whose earlier apply sent
   anything (an applied account, or exit 1 ``apply_failed``) is refused as a
   duplicate. One that sent nothing (exit 2 refused, or exit 3 could not look)
   may be retried; there is no halting. Within the apply, ``approve_amend``
   still allows at most one amend per package per closed bar, so two review
   ids on the same bar cannot double-amend either.
4. **Hand over.** It runs ``live_review_apply.py`` with PR #20259's interface:
   ``--package --new-sl --review-id --evidence --packet-sha --mandate
   MD-LIVE-TIGHTEN-SL --mechanics match --basis table|judgement`` plus
   ``--expected-cost-r/--worst-case-delta-r`` or ``--confidence/--reason``,
   and then ``--apply`` or ``--dry-run``. The apply script still owns
   ``apply_mode``, the granted-mandate check, every account gate, the venue
   read-back and the per-account pings. On a ``main`` without #20259 the
   unknown flags fail argparse and nothing is sent (fail closed).
5. **Report.** It prints one ``>>>`` line per account, with the verdict, the
   level, the executor result and the venue read-back. These come from the
   apply's own ``runtime_logs/live_review/applied.jsonl`` entry. A row-level
   refusal on a real-money or prop package sends ONE high-priority
   trade-update ping per review_id. The apply script pings every applied leg
   and every account refusal itself.

Never: a halt, a ``mode:`` or ``execution:`` write, a wider stop, a TP move, a
size change, a close.

Exit codes (the same as the apply's): 0 ok · 1 an apply did not verify · 2 refused · 3 could not look.

Usage (on the VM, via the ``live-review-apply`` system-action):
    python3 scripts/ops/live_review_dispatch.py --review-id LR-…            # dry run
    python3 scripts/ops/live_review_dispatch.py --review-id LR-… --apply
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_UNREADABLE = 0, 1, 2, 3
MANDATE_ID = "MD-LIVE-TIGHTEN-SL"
REVIEWS_PATH = "comms/live_review/reviews.jsonl"
APPLY_SCRIPT = "scripts/ops/live_review_apply.py"
DISPATCH_STATE = Path(_REPO_ROOT) / "runtime_logs" / "live_review" / "dispatch_state.json"
APPLIED_LOG = Path(_REPO_ROOT) / "runtime_logs" / "live_review" / "applied.jsonl"
#: Operator Q1: a table-backed tighten may cost at most 0.25 R of EV.
TABLE_EV_BOUND_R = -0.25
DISPATCHABLE_ROUTES = ("recommended", "auto_applied")
MONEY_CLASSES = ("real_money", "prop")


# --------------------------------------------------------------------------
# Seams (monkeypatched in tests)
# --------------------------------------------------------------------------

def _committed_text(path: str, ref: str = "HEAD") -> Optional[str]:
    """``path`` as committed at ``ref``; None when git cannot show it."""
    try:
        r = subprocess.run(["git", "-C", _REPO_ROOT, "show", f"{ref}:{path}"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _run_apply(argv: List[str]) -> int:
    """Run the apply script as its own process, so its output streams to this run's log."""
    try:
        return subprocess.run([sys.executable, os.path.join(_REPO_ROOT, APPLY_SCRIPT), *argv],
                              cwd=_REPO_ROOT).returncode
    except OSError as exc:
        print(f">>> live-review-apply: could not start {APPLY_SCRIPT}: {exc}")
        return EXIT_UNREADABLE


def _ping(row: Dict[str, Any], line: str) -> None:
    """ONE not-dispatched alert. Kind ``trade-update``: ``execution_diagnostics``
    routes it to the TRADES channel through ``src.runtime.telegram_channels``."""
    try:
        from src.runtime.execution_diagnostics import enqueue_trade_update

        enqueue_trade_update(symbol=str(row.get("symbol") or row.get("leg") or "?"),
                             account=",".join(row.get("accounts") or []) or None,
                             strategy=row.get("leg"), priority="high",
                             changes=[f"⚠️ live-review apply NOT dispatched: {line}",
                                      f"review {row.get('review_id')} · mandate {MANDATE_ID}"])
    except Exception as exc:  # noqa: BLE001 — a ping failure never blocks the record
        print(f">>> live-review-apply: refusal ping failed: {exc}")


def _load_state() -> Dict[str, Any]:
    try:
        return json.loads(DISPATCH_STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(st: Dict[str, Any]) -> None:
    try:
        DISPATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DISPATCH_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1, default=str))
        tmp.replace(DISPATCH_STATE)
    except OSError as exc:
        print(f">>> live-review-apply: dispatch state write failed: {exc}")


def _applied_entry(review_id: str, since: str) -> Optional[Dict[str, Any]]:
    """The apply's own writeback for ``review_id`` written at or after ``since``."""
    try:
        lines = APPLIED_LOG.read_text().splitlines()
    except OSError:
        return None
    for ln in reversed(lines):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("review_id") == review_id and str(e.get("at") or "") >= since:
            return e
    return None


# --------------------------------------------------------------------------
# Pure checks
# --------------------------------------------------------------------------

def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def find_row(text: Optional[str], review_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """(row, detail). The LAST row with this id wins (the file is append-only)."""
    if text is None:
        return None, f"{REVIEWS_PATH} is not readable at HEAD"
    found = None
    for ln in text.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("review_id") == review_id:
            found = r
    if found is None:
        return None, (f"{review_id} is not in the committed {REVIEWS_PATH} at HEAD "
                      f"(not landed on main yet, or git-sync has not pulled it; re-dispatch)")
    return found, "ok"


def check_row(row: Dict[str, Any], evidence_text: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(plan, refusal). ``plan`` holds the apply arguments; ``refusal`` names the
    first mandate clause the row fails. Pure: ``evidence_text`` is the committed
    outcome table (None = not committed at HEAD)."""
    rec = row.get("recommendation") or {}
    if rec.get("action") != "tighten_sl":
        return None, f"not_tighten_sl:{rec.get('action')}"
    level = _num(rec.get("level"))
    if level is None or level <= 0:
        return None, "level_missing"
    pkg = row.get("order_package_id")
    if not pkg:
        return None, "order_package_id_missing"
    mech = (row.get("mechanics") or {}).get("verdict")
    if mech != "match":
        return None, f"mechanics_{mech or 'unstated'}"
    route = (row.get("disposition") or {}).get("route")
    if route not in DISPATCHABLE_ROUTES:
        return None, f"route_{route or 'unstated'}"
    evidence = row.get("outcome_table_source")
    if not evidence or evidence_text is None:
        return None, "evidence_not_committed"
    plan: Dict[str, Any] = {"package": pkg, "new_sl": level, "review_id": row.get("review_id"),
                            "evidence": evidence, "packet_sha": row.get("packet_sha")}
    basis, src = rec.get("basis"), rec.get("evidence_source")
    if basis == "judgement" or src == "judgement":
        if basis != "judgement" or src not in (None, "judgement"):
            return None, "basis_evidence_source_disagree"
        c = _num(rec.get("judgement_confidence"))
        if c is None or not 0.0 <= c <= 1.0:
            return None, "judgement_confidence_missing"
        reason = str(rec.get("reason") or "").strip()
        if not reason:
            return None, "judgement_reason_missing"
        plan.update(basis="judgement", confidence=c, reason=reason)
        return plan, None
    if basis in ("insufficient_n", "default_hold", "record_only", "mechanics", "operator_ask"):
        return None, f"basis_{basis}"
    try:
        table = json.loads(evidence_text)
    except ValueError:
        return None, "evidence_unparseable"
    if (table or {}).get("read_state") != "measured":
        return None, f"table_not_measured:{(table or {}).get('read_state')}"
    ev, worst = _num(rec.get("ev_delta_r")), _num(rec.get("worst_case_delta_r"))
    if ev is None or ev < TABLE_EV_BOUND_R:
        return None, "table_ev_outside_bound"
    if worst is None or worst <= 0:
        return None, "table_worst_case_not_improved"
    plan.update(basis="table", expected_cost_r=ev, worst_case_delta_r=worst)
    return plan, None


def apply_argv(plan: Dict[str, Any], *, apply: bool) -> List[str]:
    """PR #20259's ``live_review_apply.py`` interface, built from a checked plan."""
    argv = ["--package", plan["package"], "--new-sl", repr(plan["new_sl"]),
            "--review-id", plan["review_id"], "--evidence", plan["evidence"],
            "--mandate", MANDATE_ID, "--mechanics", "match", "--basis", plan["basis"]]
    if plan.get("packet_sha"):
        argv += ["--packet-sha", plan["packet_sha"]]
    if plan["basis"] == "table":
        argv += ["--expected-cost-r", repr(plan["expected_cost_r"]),
                 "--worst-case-delta-r", repr(plan["worst_case_delta_r"])]
    else:
        argv += ["--confidence", repr(plan["confidence"]), "--reason", plan["reason"]]
    argv.append("--apply" if apply else "--dry-run")
    return argv


def is_money_row(row: Dict[str, Any]) -> bool:
    return any(str(a.get("account_class") or "").lower() in MONEY_CLASSES
               for a in (row.get("account_reads") or []) if isinstance(a, dict))


def summarize(entry: Optional[Dict[str, Any]]) -> List[str]:
    """One line per account from the apply's writeback: verdict, level, executor, venue read-back."""
    if not entry:
        return [">>> no applied.jsonl entry for this run (dry run, or the apply refused before any account)"]
    applied = {a.get("account_id"): a for a in (entry.get("accounts_applied") or [])}
    out = []
    for r in entry.get("account_reads") or []:
        aid = r.get("account_id")
        a = applied.get(aid) or {}
        ex = a.get("executor") or {}
        out.append(f">>> {aid} [{r.get('account_class')}]: "
                   f"{'APPLIED' if aid in applied else r.get('read')} level={a.get('level')} "
                   f"executor={ex.get('result')} venue_after={ex.get('venue_after', ex.get('sl'))} "
                   f"— {r.get('evidence')}")
    out.append(f">>> disposition {json.dumps(entry.get('disposition'), default=str)}")
    return out


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

def dispatch(review_id: str, *, apply: bool, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One dispatch. Returns the summary printed by :func:`main` (with ``exit``)."""
    started = datetime.now(timezone.utc).isoformat()
    persist = state is None
    st = state if state is not None else _load_state()
    out: Dict[str, Any] = {"review_id": review_id, "apply": apply, "at": started}
    row, detail = find_row(_committed_text(REVIEWS_PATH), review_id)
    if row is None:
        out.update(verdict="could_not_look", detail=detail, exit=EXIT_UNREADABLE)
        return out
    prev = (st.get("dispatched") or {}).get(review_id)
    if apply and prev and prev.get("sent"):
        out.update(verdict="refused", detail=f"duplicate_review_id: already dispatched at {prev.get('at')} "
                                             f"(exit {prev.get('exit')}); a new review row is a new decision",
                   exit=EXIT_REFUSED)
        return out
    evidence = row.get("outcome_table_source")
    plan, refusal = check_row(row, _committed_text(evidence) if evidence else None)
    if refusal:
        out.update(verdict="refused", detail=f"mandate_precondition:{refusal}", exit=EXIT_REFUSED)
        alerted = st.setdefault("alerted", {})
        if apply and is_money_row(row) and not alerted.get(review_id):
            alerted[review_id] = started
            _ping(row, f"{review_id}: {refusal}")
        if persist and apply:
            _save_state(st)
        return out
    argv = apply_argv(plan, apply=apply)
    out["apply_argv"] = argv
    print(f">>> live-review-apply: {review_id} -> {APPLY_SCRIPT} {' '.join(argv)}")
    rc = _run_apply(argv)
    entry = _applied_entry(review_id, started) if apply else None
    sent = bool(entry and entry.get("applied")) or rc == EXIT_FAILED
    out.update(verdict="dispatched", apply_exit=rc, exit=rc, accounts=summarize(entry),
               writeback=entry)
    if apply:
        st.setdefault("dispatched", {})[review_id] = {"at": started, "exit": rc, "sent": sent,
                                                      "package": plan["package"], "level": plan["new_sl"]}
        if persist:
            _save_state(st)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--review-id", required=True, help="the committed review row's review_id (LR-…)")
    ap.add_argument("--apply", action="store_true", help="execute; without it the apply runs --dry-run")
    a = ap.parse_args(argv)
    res = dispatch(a.review_id, apply=a.apply)
    for line in res.get("accounts") or []:
        print(line)
    print(json.dumps({k: v for k, v in res.items() if k not in ("accounts", "writeback")}, default=str))
    print(f">>> live-review-apply {a.review_id}: {res['verdict']} (exit {res['exit']})"
          f"{' — ' + res['detail'] if res.get('detail') else ''}")
    return int(res["exit"])


if __name__ == "__main__":
    sys.exit(main())
