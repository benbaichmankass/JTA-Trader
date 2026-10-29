"""Directed trade actions: the fast path for an operator- or manager-DIRECTED trade update (TRADE-ACTION-FAST-PATH).

Operator, 2026-10-29 ~08:20Z, verbatim (checklist row TRADE-ACTION-FAST-PATH): "It looks like we also need a
fast track for trade updates - not really sure why these require a PR at all, but the action needs to be
immediate". MEASURED the same morning: the operator's ADA stop moves through the ``amend-position-sl``
system-action (#21186, #21193) took ~13 min each from issue to result, and a ``flatten-bybit-position``
(#21201) sat 25+ min queued behind 90 GitHub Actions runs.

The path, end to end (no PR, no Actions job):

1. ``scripts/ops/directed_action.py submit`` writes ONE record file, ``comms/directed_actions/<id>.json``, to
   the ``directed/actions`` branch with a plain git push (create-only; never a PR).
2. The live trader's watcher (``src/runtime/live_review_rows_watch.py``, its own ``directed-actions`` thread,
   every :data:`POLL_S` s) fetches that branch into ``refs/live-review/directed/actions`` and, when the tip
   moved, runs ``directed_action.py vm-pass --ref <tip>``.
3. ``vm-pass`` validates each new record (:func:`problems`), builds a ``LiveReviewIntent`` carrying
   ``directed_by`` + ``operator_quote`` (+ the account/trade scope) and hands it to
   ``scripts/ops/live_review_apply.run()`` -- the SAME executors as every live-review apply. Each account
   still decides through its OWN ``RiskManager.approve_amend`` / ``approve_action`` (mode, shadow, tighten-only
   + noise floor, the TP doctrine, both brackets, a widen's fresh-entry check), and every apply is read back
   from the venue. No new order path, no flag, no third gate.
4. One receipt per record (diag ``log_file?name=directed_actions``), one ping per record.

THE AUTHORITY. A directed record is the operator's own act (or the manager's, carrying the operator's words),
so it is NOT gated by the advice-only rule for reviewer recommendations (``live_review_rows.ADVICE_ONLY_ACTIONS``)
and needs no ``config/mandates.yaml`` grant. It MUST carry the operator's verbatim quote: a record without one is
refused (:data:`R_NO_QUOTE`), named, and nothing is sent.

Deliberate differences from a reviewer apply (each stated, each in a test):

* the reviewer's one-action-per-package-per-bar rate guard does not bind (the intent carries no ``bar_ts``): it
  exists to stop an automated reviewer churning; an operator who moves a stop twice in one bar means it;
* the scope may be ONE account, or one trade / prop ticket of that account: the other legs are not touched,
  and the shared package stop is never moved by a scoped record.

This module is pure (no I/O); the CLI and the VM pass live in ``scripts/ops/directed_action.py``.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA = "directed_action/v1"
BRANCH = "directed/actions"
RECORDS_DIR = "comms/directed_actions"
#: Directed actions and what each becomes in ``live_review_apply`` (``move_sl`` resolves per package to a
#: tighten or a widen, see :func:`resolve_action`).
ACTIONS = ("tighten_sl", "move_sl", "move_tp", "close", "partial_close")
NEEDS_LEVEL = ("tighten_sl", "move_sl", "move_tp")
#: The watcher's poll for the directed branch (its own thread; a rows dispatch never delays it).
POLL_S = 20
#: A record first seen more than this long after its ``created_at`` is refused ``stale_record``: a directed
#: action is meant NOW, and a late one (VM down, branch unreadable for a while) must be re-issued, not replayed.
STALE_S = 900
#: A could-not-look apply (exit 3) is retried on later passes this long, then ``expired`` with ONE flag.
RETRY_WINDOW_S = 600
ID_RE = re.compile(r"^DA-[0-9]{8}T[0-9]{6}Z-[a-z_]+-[0-9a-f]{6}$")

R_NO_QUOTE = "operator_quote_missing"
R_SCHEMA = "schema"
R_STALE = "stale_record"
R_SCOPE_EMPTY = "scope_matched_no_leg"


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def new_id(action: str, now: datetime, salt: str) -> str:
    return f"DA-{now.strftime('%Y%m%dT%H%M%SZ')}-{action}-{salt[:6]}"


def record_path(record_id: str) -> str:
    return f"{RECORDS_DIR}/{record_id}.json"


def scope_of(record: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """``{"account_id": ..., "trade_id": ...}`` (None = every). ``scope`` is ``"package"`` or an object."""
    sc = record.get("scope")
    if isinstance(sc, dict):
        tid = sc.get("trade_id")
        return {"account_id": sc.get("account_id") or None, "trade_id": None if tid in (None, "") else str(tid)}
    return {"account_id": None, "trade_id": None}


def problems(record: Any, *, path: Optional[str] = None) -> List[str]:
    """Every reason ``record`` may not be applied. Empty = valid. The missing operator quote is reported as
    :data:`R_NO_QUOTE` (first), so the refusal names it."""
    if not isinstance(record, dict):
        return [f"{R_SCHEMA}:not_an_object"]
    out: List[str] = []
    q = record.get("operator_quote")
    if not isinstance(q, str) or not q.strip():
        out.append(R_NO_QUOTE)
    if record.get("schema") != SCHEMA:
        out.append(f"{R_SCHEMA}:schema!={SCHEMA}")
    rid = record.get("id")
    if not isinstance(rid, str) or not ID_RE.match(rid):
        out.append(f"{R_SCHEMA}:id")
    elif path is not None and path != record_path(rid):
        out.append(f"{R_SCHEMA}:file_name_differs_from_id")
    by = record.get("directed_by")
    if not isinstance(by, str) or not by.strip():
        out.append(f"{R_SCHEMA}:directed_by")
    if _ts(record.get("created_at")) is None:
        out.append(f"{R_SCHEMA}:created_at")
    pkg = record.get("order_package_id")
    if not isinstance(pkg, str) or not pkg.startswith("pkg-"):
        out.append(f"{R_SCHEMA}:order_package_id")
    a = record.get("action")
    if a not in ACTIONS:
        out.append(f"{R_SCHEMA}:action_not_in:{','.join(ACTIONS)}")
    lvl = _num(record.get("level"))
    if a in NEEDS_LEVEL and (lvl is None or lvl <= 0):
        out.append(f"{R_SCHEMA}:level_required_for_{a}")
    if a not in NEEDS_LEVEL and record.get("level") is not None:
        out.append(f"{R_SCHEMA}:level_not_used_by_{a}")
    fr = _num(record.get("fraction"))
    if a == "partial_close" and (fr is None or not 0.0 < fr < 1.0):
        out.append(f"{R_SCHEMA}:fraction_in_(0,1)_required_for_partial_close")
    if a != "partial_close" and record.get("fraction") is not None:
        out.append(f"{R_SCHEMA}:fraction_not_used_by_{a}")
    if not isinstance(record.get("dry_run"), bool):
        out.append(f"{R_SCHEMA}:dry_run_must_be_true_or_false")
    sc = record.get("scope")
    if sc != "package":
        if not isinstance(sc, dict) or not isinstance(sc.get("account_id"), str) or not sc["account_id"].strip():
            out.append(f"{R_SCHEMA}:scope_is_package_or_an_account")
        elif set(sc) - {"account_id", "trade_id"}:
            out.append(f"{R_SCHEMA}:scope_keys:{','.join(sorted(set(sc) - {'account_id', 'trade_id'}))}")
    return out


def is_stale(record: Dict[str, Any], first_seen: datetime) -> bool:
    c = _ts(record.get("created_at"))
    return c is None or (first_seen - c).total_seconds() > STALE_S


def resolve_action(record: Dict[str, Any], package_sl: Optional[float], direction: str) -> Optional[str]:
    """The ``live_review_apply`` action: ``move_sl`` is a tighten when the level is tighter than the
    package stop, a widen when looser, else None (unchanged / unread). Every other action maps to itself."""
    a = record.get("action")
    if a != "move_sl":
        return a
    lvl, cur = _num(record.get("level")), _num(package_sl)
    if lvl is None or cur is None or abs(lvl - cur) <= max(abs(cur) * 1e-9, 1e-12):
        return None
    tighter = lvl > cur if direction == "long" else lvl < cur
    return "tighten_sl" if tighter else "widen_sl"


def precondition(intent: Any) -> Optional[str]:
    """The directed authority's own clause, checked by ``live_review_apply.run`` in place of a mandate's.
    None when it holds: a directing party and the operator's verbatim quote."""
    if not str(getattr(intent, "operator_quote", None) or "").strip():
        return f"directed:{R_NO_QUOTE}"
    if not str(getattr(intent, "directed_by", None) or "").strip():
        return "directed:directed_by_missing"
    return None


def leg_in_scope(leg: Dict[str, Any], intent: Any) -> bool:
    """Whether ``leg`` (``live_review_apply.gather_legs``) is inside the intent's scope. An unreadable prop
    ticket read stays in (it is a could-not-look, never a silent skip)."""
    acct = getattr(intent, "target_account_id", None)
    if not acct:
        return True
    if leg.get("kind") == "prop_unreadable":
        return True
    if str(leg.get("account_id")) != str(acct):
        return False
    tid = getattr(intent, "target_trade_id", None)
    if not tid:
        return True
    row = leg.get("row") or {}
    key = row.get("id") if leg.get("kind") == "trade" else row.get("ticket_id")
    return str(key) == str(tid)


def summary_line(record: Dict[str, Any], accounts: List[Dict[str, Any]]) -> str:
    """One line per record for the ping: what was asked, and what each account did."""
    lvl = record.get("level")
    what = f"{record.get('action')}" + (f" {lvl:g}" if isinstance(lvl, (int, float)) else "") + (
        f" x{record.get('fraction'):g}" if isinstance(record.get("fraction"), (int, float)) else "")
    parts = []
    for a in accounts:
        ex = a.get("executor") or {}
        res = ex.get("result") or a.get("verdict")
        back = ex.get("venue_after")
        parts.append(f"{a.get('account_id')}: {res}" + (f" (venue {back})" if back is not None else "")
                     + ("" if a.get("executed") else f" [{a.get('reason')}]"))
    return f"directed {what} by {record.get('directed_by')} -> " + ("; ".join(parts) or "no leg")
