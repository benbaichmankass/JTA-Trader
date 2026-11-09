"""PHONE-ENTRY-CANCEL (operator 2026-11-09 ~08:20Z): withdraw ONE stale resting ENTRY order on a phone-executed account.

**Gates this adds or changes:** none. This is a narrow, server-issued capability (a new claim kind), not a switch: nothing
halts, no trade is blocked, and a cancel the phone cannot verify is simply not done (it retries with backoff, one red flag,
never stops).

Why. ``breakout_2`` runs only through the operator's phone app. The strategy exited ETH at 02:35Z and the ticket's
``valid_until`` (01:52Z) passed, but its limit sell still rested at the venue: exec.js ``DENY_WORDS`` / ``NOT_EDIT`` forbid
every cancel by design, the app had no supersede/cancel code, and the VM cancel path (``prop_executor.cancel_expired_resting``
/ ``_supersede_resting``, PROP-CANCEL-FIX) serves VM-executed accounts only.

What it is. One request per ticket, stored in ``prop_tickets.meta.phone_cancel`` (the same store and compare-and-set as the
phone trail). It is PLANNED by the server (:func:`plan_cancels`), CLAIMED by an app that declares ``"cancel"`` in
``accepts`` (:func:`claim_cancel`, after entries, before amends) and REPORTED (``kind: cancel_result``,
:func:`record_cancel_result`). It exists ONLY for a ticket that

* is ``placed`` (its entry order was submitted and nothing has filled it), is not a test / exec-test ticket, and
* is past ``valid_until``, OR its order package is CLOSED, OR a newer same-strategy ticket is waiting on it (superseded).

It is never a position, never an SL/TP leg and never an order the server did not issue: the request names one ticket's own
entry order (venue symbol, side, quantity, limit price). The phone matches the Open orders row by those four facts and
refuses anything but exactly one row; the click sequence is ``exec.js cancelOrderRow`` + ``MainActivity.executeCancel``.

Results (the phone's report): ``cancelled`` (row clicked, anchored confirm pressed, Open orders re-read, row gone) ->
the ticket becomes ``skipped``; ``not_found`` (Open orders positively read, no matching row: filled, cancelled by hand, or
never rested) -> ``skipped`` plus ONE alert to verify no position; ``placed`` (row still there after the attempt),
``ambiguous`` and ``refused`` (nothing was clicked) -> retried with backoff, ONE red flag after :data:`FLAG_AFTER`.

The superseded reason only WITHDRAWS the stale order; releasing the newer suppressed ticket is the existing
``prop_supersede`` path and is not driven from here (filed on the checklist row).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from src.prop import prop_journal
from src.prop.phone_trail import _cas, _f, _meta, _package_state, _parse, _price_step, _send, _venue_qty

logger = logging.getLogger(__name__)

KEY = "phone_cancel"
CANCEL_VALID_S = 6 * 3600        # an emitted request not claimed in time is re-planned (the reason is re-checked)
CLAIM_TIMEOUT_S = 180            # same watchdog as an entry / amend claim
FLAG_AFTER = 3                   # consecutive failed attempts on one ticket -> ONE red flag (never a stop)
BACKOFF_CAP_MIN = 360            # retry backoff after a failed attempt: 10, 20, 40 ... capped at 6 h
RESULTS = ("cancelled", "not_found", "ambiguous", "placed", "refused")
_TERMINAL = ("cancelled", "not_found")
_HISTORY_MAX = 12
_CLOSED_PKG = ("closed", "cancelled", "canceled", "expired", "skipped")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entry_side(direction: Any) -> Optional[str]:
    d = str(direction or "").lower()
    return {"long": "buy", "buy": "buy", "short": "sell", "sell": "sell"}.get(d)


def _reason(conn: Any, r: Any, m: Mapping[str, Any], now: datetime) -> Optional[str]:
    """Why this ticket's resting entry should be withdrawn, or None (every doubt is None: nothing is asked of the phone)."""
    if str(r["status"] or "") != "placed":
        return None
    if m.get("test") or m.get("origin") == "exec_test":
        return None
    vu = _parse(r["valid_until"])
    if vu is not None and vu <= now:
        return "expired"
    pk = _package_state(conn, r["order_package_id"])
    if pk and str(pk.get("status") or "").lower() in _CLOSED_PKG:
        return "package_closed"
    try:
        rows = conn.execute("SELECT meta FROM prop_tickets WHERE account_id = ? AND status = 'suppressed'",
                            (r["account_id"],)).fetchall()
    except Exception:  # noqa: BLE001  # allow-silent: could not look -> not superseded
        return None
    for x in rows:
        cand = _meta(x["meta"]).get("supersede")
        if isinstance(cand, dict) and cand.get("blocked_by") == r["ticket_id"]:
            cv = _parse(cand.get("valid_until"))
            if cv is not None and cv > now:
                return "superseded"
    return None


def _spec(account_id: str, r: Any) -> Optional[Dict[str, Any]]:
    """The four facts the phone matches the Open orders row by, from the ticket. None when any is unreadable."""
    from src.prop import phone_executor as pe
    venue = pe.venue_symbol(account_id, r["symbol"])
    side = _entry_side(r["direction"])
    qty = _f(_venue_qty(account_id, r["symbol"], r["qty"]))
    price = _f(r["entry"])
    if not venue or side is None or not qty or qty <= 0 or not price or price <= 0:
        return None
    return {"venue_symbol": venue, "side": side, "qty": qty, "price": price,
            "price_step": _price_step(account_id, r["symbol"])}


def _load(m: Mapping[str, Any]) -> Dict[str, Any]:
    c = m.get(KEY)
    return dict(c) if isinstance(c, dict) else {}


def _hist(c: Dict[str, Any], entry: Mapping[str, Any]) -> None:
    c["history"] = (list(c.get("history") or []) + [dict(entry)])[-_HISTORY_MAX:]


def _backoff(n: int) -> timedelta:
    return timedelta(minutes=min(10 * (2 ** max(n - 1, 0)), BACKOFF_CAP_MIN))


def plan_cancels(account_id: str, *, now: Optional[datetime] = None,
                 send: Optional[Callable[..., Any]] = None) -> int:
    """Publish (emit) the cancel request for every eligible ticket, and re-arm a claim the phone never reported.
    Idempotent. Returns how many requests are now ``emitted``. Never touches the venue."""
    now = now or _now()
    emitted = 0
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        rows = conn.execute("SELECT * FROM prop_tickets WHERE account_id = ? AND status = 'placed' "
                            "ORDER BY created_at ASC", (account_id,)).fetchall()
        for r in rows:
            m = _meta(r["meta"])
            c = _load(m)
            st = c.get("status")
            if st in _TERMINAL:
                continue
            if st == "claimed":
                at = _parse(c.get("claimed_at"))
                if at is None or (now - at).total_seconds() < CLAIM_TIMEOUT_S:
                    continue
                # the phone never reported: that attempt failed (a click may or may not have happened; the next
                # attempt matches the rows afresh, so a row that is gone reads not_found and nothing is repeated)
                n = int(c.get("attempts") or 0) + 1
                c.update(status="failed", attempts=n, next_try_at=(now + _backoff(n)).isoformat(),
                         last_result="unreported")
                _hist(c, {"at": now.isoformat(), "result": "unreported", "attempt": n})
                if not _cas(conn, r["ticket_id"], r["meta"], {**m, KEY: c}):
                    continue
                if n == FLAG_AFTER:
                    _send(f"📱 phone {account_id}: [{r['ticket_id']}] stale-entry cancel was claimed but never "
                          f"reported ({n} attempts); the order may STILL BE RESTING. Retrying with backoff.", send)
                continue
            reason = _reason(conn, r, m, now)
            if reason is None:
                if st == "emitted":   # no longer eligible (e.g. a late fill was journaled): withdraw the request
                    c["status"] = "withdrawn"
                    _cas(conn, r["ticket_id"], r["meta"], {**m, KEY: c})
                continue
            nt = _parse(c.get("next_try_at"))
            if st == "failed" and nt is not None and nt > now:
                continue
            if st == "emitted":
                vu = _parse(c.get("valid_until"))
                if vu is not None and vu > now:
                    emitted += 1
                    continue
            spec = _spec(account_id, r)
            if spec is None:
                continue
            c.update(status="emitted", id=f"{r['ticket_id']}-c{int(c.get('attempts') or 0) + 1}", reason=reason, spec=spec,
                     emitted_at=now.isoformat(), valid_until=(now + timedelta(seconds=CANCEL_VALID_S)).isoformat())
            if _cas(conn, r["ticket_id"], r["meta"], {**m, KEY: c}):
                emitted += 1
    finally:
        conn.close()
    return emitted


def pending_cancels(account_id: str, now: Optional[datetime] = None) -> int:
    """Read-only: emitted, still-valid requests the next cancel-capable claim would find."""
    now = now or _now()
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        rows = conn.execute("SELECT meta FROM prop_tickets WHERE account_id = ? AND status = 'placed'", (account_id,)).fetchall()
    finally:
        conn.close()
    n = 0
    for r in rows:
        c = _load(_meta(r["meta"]))
        vu = _parse(c.get("valid_until"))
        if c.get("status") == "emitted" and vu and vu > now:
            n += 1
    return n


def claim_cancel(device: Any, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Atomically claim the oldest emitted request for the device's account. The reason is re-checked AT CLAIM."""
    from src.prop import phone_executor as pe
    now = now or _now()
    acct = device.account_id
    if pe.kill_switch(acct) == "off":
        return None
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        rows = conn.execute("SELECT * FROM prop_tickets WHERE account_id = ? AND status = 'placed' "
                            "ORDER BY created_at ASC", (acct,)).fetchall()
        for r in rows:
            m = _meta(r["meta"])
            c = _load(m)
            vu = _parse(c.get("valid_until"))
            if c.get("status") != "emitted" or vu is None or vu <= now:
                continue
            reason = _reason(conn, r, m, now)
            if reason is None:
                continue
            c.update(status="claimed", claimed_at=now.isoformat(), device_id=device.device_id, reason=reason)
            if not _cas(conn, r["ticket_id"], r["meta"], {**m, KEY: c}):
                continue  # lost the race: never act on it
            return {"kind": "cancel", "ticket_id": r["ticket_id"], "cancel_id": c["id"], "reason": reason,
                    "symbol": r["symbol"], "spec": c.get("spec"), "venue_symbol": (c.get("spec") or {}).get("venue_symbol"),
                    "submit": pe.submit_mode(acct, test=False), "claimed_at": now.isoformat()}
        return None
    finally:
        conn.close()


def record_cancel_result(device: Any, body: Mapping[str, Any], *, now: Optional[datetime] = None,
                         send: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """The phone's report of one claimed cancel. Only ``cancelled`` / ``not_found`` end the request (the ticket becomes
    ``skipped``); anything else fails THAT attempt (backoff, then retried; ONE red flag after :data:`FLAG_AFTER`)."""
    now = now or _now()
    acct = device.account_id
    tid = str(body.get("ticket_id") or "")
    cid = str(body.get("cancel_id") or "")
    result = str(body.get("result") or "")
    if result not in RESULTS:
        raise ValueError("cancel_result.result invalid")
    reason = str(body.get("reason") or "")[:300]
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        r = conn.execute("SELECT * FROM prop_tickets WHERE ticket_id = ? AND account_id = ?", (tid, acct)).fetchone()
        if r is None:
            return {"ok": False, "kind": "cancel_result", "why": "unknown ticket"}
        m = _meta(r["meta"])
        c = _load(m)
        if c.get("id") != cid or c.get("status") != "claimed":
            return {"ok": False, "kind": "cancel_result", "why": "not the claimed cancel"}
        live = str(body.get("submit") or "live") == "live"
        entry = {"at": now.isoformat(), "result": result, "reason": reason, "cancel_id": cid}
        if result in _TERMINAL:
            c.update(status=result, finished_at=now.isoformat(), last_result=result)
            _hist(c, entry)
            if not _cas(conn, tid, r["meta"], {**m, KEY: c}):
                return {"ok": False, "kind": "cancel_result", "why": "lost a race"}
            n = prop_journal.transition_ticket_status(tid, "skipped", from_statuses=("placed",), account_id=acct)
            if result == "not_found":
                _send(f"📱 phone {acct}: [{tid}] stale-entry cancel found NO matching order on the terminal's Open "
                      f"orders (filled, cancelled by hand, or never rested). Ticket closed as skipped; CHECK the "
                      f"terminal for a position on {(c.get('spec') or {}).get('venue_symbol')}.", send)
            else:
                _send(f"📱 phone {acct}: [{tid}] stale entry order ({c.get('reason')}) CANCELLED on the terminal "
                      f"(row clicked, anchored confirm pressed, Open orders re-read: gone).", send)
            return {"ok": True, "kind": "cancel_result", "result": result, "ticket_updated": n}
        n = int(c.get("attempts") or 0) + 1
        c.update(status="failed", attempts=n, last_result=result, last_reason=reason,
                 next_try_at=(now + _backoff(n)).isoformat())
        _hist(c, {**entry, "attempt": n})
        if not _cas(conn, tid, r["meta"], {**m, KEY: c}):
            return {"ok": False, "kind": "cancel_result", "why": "lost a race"}
        if n == FLAG_AFTER and live:
            _send(f"📱 phone {acct}: [{tid}] stale-entry cancel failed {n} times (last: {result}: {reason[:120]}); the "
                  f"order may STILL BE RESTING. Retrying with backoff, nothing is stopped.", send)
        return {"ok": True, "kind": "cancel_result", "result": result, "attempt": n}
    finally:
        conn.close()
