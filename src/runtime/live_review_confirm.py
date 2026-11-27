"""Resolve every ``venue_unconfirmed`` live-review receipt (row LTR-PROP-RECEIPT-CONFIRM-WRITEBACK).

WHY. #29266 (LTR-PROP-CLOSE-FALSE-APPLIED) stopped the prop-VM and phone executors' queued ticket requests from reading
as a venue read-back: such an apply carries ``executor.venue_confirmed: false`` and is listed in
``disposition.venue_unconfirmed`` of its ``runtime_logs/live_review/applied.jsonl`` line. Nothing later recorded the
outcome, so the receipt stayed QUEUED for ever: a silent state. Motivating case: LR-20261115T1141Z tradeify_1 SOL close,
whose terminal still held the position at 12:48Z; the venue close came 204 min after the apply.

WHAT. One pass (the rows-watch thread, every ``POLL_S``) reads each unresolved (review_id, account_id) and resolves it
from the record the account's own executor writes back on THIS VM, keyed by the handle the apply recorded:

* phone amend (``executor.amend_id``): the ticket's ``meta.phone_trail.amend`` with that id -- ``amended`` confirmed;
  ``no_position`` / ``human_moved`` refused; anything else still pending (the phone backs off and retries);
* phone close / reduce (``executor.close_id``): the ticket's ``meta.phone_close`` with that id -- ``done`` confirmed,
  ``not_found`` refused (nothing to close); anything else pending;
* prop-VM close (``executor.close_id``, ``vm_close``): the ticket's newest ``prop_fills`` row closed at or after the
  apply (the executor's venue reconcile writes it; ``vm_close_done.json`` lives on the prop VM, not here);
* prop-VM / phone stop or target (``sl_floor`` / ``tp_target`` / an amend whose id was superseded): the open fill row's
  ``sl`` / ``tp`` at the requested level (the executor's ``amend`` report, ``prop_journal.amend_fill_levels``);
* a fill row that closed before any confirmation: ``closed_before_confirm`` (the position is gone; nothing to apply).

Each resolution is appended ONCE to ``runtime_logs/live_review/venue_confirmations.jsonl`` keyed by review_id +
account_id (outcome, evidence, latency). A request still pending after :data:`PENDING_FLAG_AFTER_S` gets ONE red flag
and stays watched: the executor keeps retrying (Prime Directive rule 7, no halting). An unreadable ticket or journal is
``could_not_look`` for that pass, retried, never folded into pending.

Gates this adds or changes: none -- a report, never a refusal; nothing here sends or blocks an order.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

CONFIRM_LOG = "venue_confirmations.jsonl"
STATE_FILE = "venue_confirm_state.json"
APPLIED_LOG = "applied.jsonl"
#: Measured over the 13 prop live-review applies 11-14..11-26: 9 confirmed within 5 min, 1 at 204 min, 2 on never-filled
#: tickets, 1 tighten without a venue level. 30 min flags the slow tail once without paging on the ordinary case.
PENDING_FLAG_AFTER_S = 1800
#: An apply older than this with no resolution is recorded ``expired_unresolved`` (one line) and no longer watched.
GIVE_UP_AFTER_S = 7 * 86400

CONFIRMED, REFUSED, APPLY_FAILED, PENDING = "confirmed", "refused", "apply_failed", "pending"
CLOSED_BEFORE, COULD_NOT_LOOK, EXPIRED = "closed_before_confirm", "could_not_look", "expired_unresolved"
#: A prop-VM PARTIAL close: its read-back (quantity dropped, both brackets resting) is the executor's own vm_close line on
#: the prop VM; nothing on this VM records the reduced size, so the receipt says so once instead of reading pending.
NO_READBACK_HERE = "no_readback_on_this_vm"
TERMINAL = (CONFIRMED, REFUSED, APPLY_FAILED, CLOSED_BEFORE, EXPIRED, NO_READBACK_HERE)

#: live_review_intent.TRADE_ACTIONS that take size off: a full close ends the fill row; the other two reduce it.
FULL_CLOSE, PARTIAL_ACTIONS = "close", ("partial_close", "change_size")


def _ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _meta(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        d = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _rows(path: Path) -> Iterable[Dict[str, Any]]:
    try:
        fh = path.open()
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                yield d


def unconfirmed(applied_rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One item per (review_id, account_id) an apply listed in ``disposition.venue_unconfirmed``."""
    out: List[Dict[str, Any]] = []
    for row in applied_rows:
        disp = row.get("disposition") or {}
        accts = set(disp.get("venue_unconfirmed") or [])
        if not accts or not row.get("review_id"):
            continue
        for a in row.get("accounts_applied") or []:
            if a.get("account_id") in accts:
                out.append({"review_id": row["review_id"], "account_id": a["account_id"],
                            "order_package_id": row.get("order_package_id"), "action": row.get("action"),
                            "applied_at": disp.get("applied_at") or row.get("at"), "level": a.get("level"),
                            "executor": dict(a.get("executor") or {})})
    return out


def _level_match(have: Optional[float], want: Optional[float]) -> bool:
    if have is None or want is None:
        return False
    return abs(have - want) <= max(abs(want) * 1e-6, 1e-9)


def resolve(item: Mapping[str, Any], ticket: Optional[Mapping[str, Any]],
            fill: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The outcome for one item from its ticket row (``meta``) and the ticket's newest fill row. Pure."""
    if ticket is None:
        return {"outcome": COULD_NOT_LOOK, "evidence": "no prop ticket for this package on this account"}
    ex = item.get("executor") or {}
    m = _meta(ticket.get("meta"))
    applied = _ts(item.get("applied_at"))
    action = str(item.get("action") or "").lower()
    closed_at = _ts((fill or {}).get("closed_at"))
    fill_closed = bool(fill) and (str(fill.get("status") or "").lower() == "closed" or closed_at is not None)
    closed_after = fill_closed and (applied is None or closed_at is None or closed_at >= applied)

    amend_id, close_id = ex.get("amend_id"), ex.get("close_id")
    if close_id:
        pc = m.get("phone_close") or {}
        if pc.get("id") == close_id:
            st = str(pc.get("status") or "")
            if st == "done":
                return {"outcome": CONFIRMED, "evidence": f"phone close {close_id} reported done"}
            if st == "not_found":
                return {"outcome": REFUSED, "evidence": f"phone close {close_id}: not_found (nothing to close)"}
        if closed_after:
            return {"outcome": CONFIRMED, "evidence": f"fill row {fill.get('id')} closed at {fill.get('closed_at')}"}
        if action in PARTIAL_ACTIONS and not pc:
            return {"outcome": NO_READBACK_HERE, "evidence": f"prop-VM partial close {close_id}: its read-back is the "
                                                             f"executor's vm_close line on the prop VM"}
        return {"outcome": PENDING, "evidence": f"close {close_id}: fill row still open"}
    if amend_id:
        am = (m.get("phone_trail") or {}).get("amend") or {}
        if am.get("id") == amend_id:
            st = str(am.get("status") or "")
            if st == "amended":
                return {"outcome": CONFIRMED, "evidence": f"phone amend {amend_id} amended (sl_read={am.get('sl_read')})"}
            if st in ("no_position", "human_moved"):
                return {"outcome": REFUSED, "evidence": f"phone amend {amend_id}: {st}"}
    if action == FULL_CLOSE:
        if closed_after:
            return {"outcome": CONFIRMED, "evidence": f"fill row {fill.get('id')} closed at {fill.get('closed_at')}"}
        return {"outcome": PENDING, "evidence": "close requested: fill row still open"}
    # a stop / target request: the open fill row carries the level once the executor's amend report lands
    want_tp = _f(ex.get("tp")) if ex.get("tp") is not None else None
    want_sl = None if want_tp is not None else _f(ex.get("sl") if ex.get("sl") is not None else item.get("level"))
    if fill and not fill_closed:
        if want_tp is not None and _level_match(_f(fill.get("tp")), want_tp):
            return {"outcome": CONFIRMED, "evidence": f"fill row {fill.get('id')} tp={fill.get('tp')}"}
        have_sl, side = _f(fill.get("sl")), str(fill.get("direction") or "").lower()
        # a tighten is applied tighten-only by the trail, so the stop may sit AT or THROUGH the floor (never looser)
        through = have_sl is not None and want_sl is not None and action == "tighten_sl" and (
            (side in ("long", "buy") and have_sl >= want_sl) or (side in ("short", "sell") and have_sl <= want_sl))
        if want_sl is not None and (_level_match(have_sl, want_sl) or through):
            return {"outcome": CONFIRMED, "evidence": f"fill row {fill.get('id')} sl={fill.get('sl')} (asked {want_sl})"}
        return {"outcome": PENDING, "evidence": f"fill row {fill.get('id')} sl={fill.get('sl')} tp={fill.get('tp')}; "
                                               f"want sl={want_sl} tp={want_tp}"}
    if fill_closed:
        return {"outcome": CLOSED_BEFORE, "evidence": f"fill row {fill.get('id')} closed at {fill.get('closed_at')} "
                                                      f"before the level was confirmed"}
    return {"outcome": PENDING, "evidence": "no fill row yet (ticket not filled)"}


def _read_prop(item: Mapping[str, Any]) -> tuple:
    """(ticket, newest fill) for the item's package on its account, from the prop journal on this VM (``prop_tickets`` /
    ``prop_fills`` in the trade journal), opened READ-ONLY through the one path resolver. Not via ``src.prop.prop_journal``:
    importing it pulls the prop executor chain (vm_close -> prop_trail -> market_data -> exchange) into the trader's runtime
    import graph, which the layer contract refuses for this read."""
    import sqlite3

    from src.utils.paths import trade_journal_db_path

    conn = sqlite3.connect(f"file:{trade_journal_db_path()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    try:
        t = conn.execute("SELECT * FROM prop_tickets WHERE order_package_id = ? AND account_id = ? "
                         "ORDER BY created_at DESC LIMIT 1",
                         (item.get("order_package_id"), item.get("account_id"))).fetchone()
        if t is None:
            return None, None
        f = conn.execute("SELECT * FROM prop_fills WHERE ticket_id = ? ORDER BY id DESC LIMIT 1",
                         (t["ticket_id"],)).fetchone()
        return dict(t), (dict(f) if f is not None else None)
    finally:
        conn.close()


def _log_dir() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / "live_review"


def _alert(text: str) -> bool:
    """ONE operator flag on the alert channel (the rows-watch helper). Never raises."""
    from src.runtime.live_review_rows_watch import _alert as send
    return send(text)


def run_confirm_pass(*, now: Optional[datetime] = None, log_dir: Optional[Path] = None,
                     read: Callable[[Mapping[str, Any]], tuple] = _read_prop,
                     alert: Callable[[str], bool] = _alert) -> Dict[str, Any]:
    """Resolve every unresolved venue_unconfirmed item once. Returns counts by outcome (this pass)."""
    now = now or datetime.now(timezone.utc)
    d = Path(log_dir) if log_dir is not None else _log_dir()
    done = {(r.get("review_id"), r.get("account_id")) for r in _rows(d / CONFIRM_LOG)
            if r.get("outcome") in TERMINAL}
    try:
        state = json.loads((d / STATE_FILE).read_text())
    except (OSError, ValueError):
        state = {}
    flagged = dict(state.get("flagged") or {})
    counts: Dict[str, int] = {}
    for it in unconfirmed(_rows(d / APPLIED_LOG)):
        key = (it["review_id"], it["account_id"])
        if key in done:
            continue
        applied = _ts(it.get("applied_at"))
        age = (now - applied).total_seconds() if applied else None
        try:
            ticket, fill = read(it)
            res = resolve(it, ticket, fill)
        except Exception as exc:  # noqa: BLE001 — contained per item; retried next pass (no halting)
            res = {"outcome": COULD_NOT_LOOK, "evidence": f"{type(exc).__name__}: {str(exc)[:160]}"}
        if res["outcome"] == PENDING and age is not None and age > GIVE_UP_AFTER_S:
            res = {"outcome": EXPIRED, "evidence": res["evidence"] + f"; unresolved after {int(age)} s"}
        counts[res["outcome"]] = counts.get(res["outcome"], 0) + 1
        fkey = f"{it['review_id']}|{it['account_id']}"
        if res["outcome"] in TERMINAL:
            rec = {"at": now.isoformat(), "review_id": it["review_id"], "account_id": it["account_id"],
                   "order_package_id": it.get("order_package_id"), "action": it.get("action"),
                   "outcome": res["outcome"], "evidence": res["evidence"],
                   "latency_s": None if age is None else round(age, 1),
                   "handle": {k: it["executor"].get(k) for k in ("amend_id", "close_id") if it["executor"].get(k)},
                   "was_flagged": fkey in flagged}
            d.mkdir(parents=True, exist_ok=True)
            with (d / CONFIRM_LOG).open("a") as fh:
                fh.write(json.dumps(rec, default=str, separators=(",", ":")) + "\n")
            flagged.pop(fkey, None)
            if res["outcome"] in (APPLY_FAILED, CLOSED_BEFORE, EXPIRED) or rec["was_flagged"]:
                alert(f"live-review {it['review_id']} {it['account_id']} {it.get('action')}: venue {res['outcome']} "
                      f"-- {res['evidence']}")
        elif res["outcome"] == PENDING and age is not None and age > PENDING_FLAG_AFTER_S and fkey not in flagged:
            flagged[fkey] = now.isoformat()
            alert(f"live-review {it['review_id']} {it['account_id']} {it.get('action')}: still not confirmed at the "
                  f"venue after {int(age // 60)} min ({res['evidence']}); the executor keeps retrying")
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / STATE_FILE).write_text(json.dumps({"flagged": flagged, "at": now.isoformat()}, default=str))
    except OSError:
        logger.warning("venue-confirm: state not written", exc_info=True)
    return counts
