"""PHONE-ENTRY-CANCEL (operator 2026-11-09 ~08:20Z): withdraw ONE stale resting ENTRY order on a phone-executed account.

**Gates this adds or changes:** none. This is a narrow, server-issued capability (a new claim kind), not a switch: nothing
halts, no trade is blocked, and a cancel the phone cannot verify is simply not done (it retries with backoff, one red flag,
never stops).

Why. ``breakout_2`` runs only through the operator's phone app. The strategy exited ETH at 02:35Z and the ticket's
``valid_until`` (01:52Z) passed, but its limit sell still rested at the venue: exec.js ``DENY_WORDS`` / ``NOT_EDIT`` refused
every cancel (a session-authored deny-list, replaced by intent-bound clicks on 2026-11-09), the app had no supersede/cancel code, and the VM cancel path (``prop_executor.cancel_expired_resting``
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
the ticket becomes ``skipped``; ``placed`` (row still there after the attempt), ``ambiguous`` and ``refused`` (nothing
was clicked) -> retried with backoff, ONE red flag after :data:`FLAG_AFTER`.

``not_found`` (Open orders positively read, no matching row) means the order is GONE, not that it never FILLED
(PHONE-CANCEL-FILLED-AS-SKIPPED, 2026-11-12: breakout_2 ETH long ``prop-manual-c54b2229aa1c`` had filled into a position;
the 21:06Z cancel found no open order, the ticket went ``placed -> skipped``, the position left the risk book and its
stop-out went unrecorded). So ``not_found`` is resolved from evidence the server already holds, never straight to
``skipped`` (:func:`_position_verdict`):

1. the journal already has an open / closed fill on the ticket -> it filled (the ticket stays where that fill put it);
2. a clean venue Positions read shows the symbol + side, and no other open journal row accounts for it -> an ``open``
   fill is journaled on the ticket (venue entry and size, ``MEASURED``), the ticket becomes ``filled``, and
   ``phone_reconcile`` records its later close when it leaves the Positions list;
3. the bot's own candles traded THROUGH the limit between placement and the cancel -> an ``open`` fill is journaled in
   ``fill_inference``'s own format (``ESTIMATED``, entry = the limit), so that pass records its SL / TP close and a
   later venue read overrides it;
4. ``skipped`` only on positive evidence it never filled: the price never reached the limit, or a clean Positions read
   taken after the cancel looked is flat on that symbol + side while the price never traded through it;
5. anything else (no clean read, feed unreadable, only touched, flat read but price through) keeps the ticket
   ``placed`` -- still in the risk book -- with ONE alert, and the check re-runs on later :func:`plan_cancels` passes
   (every :data:`VERIFY_EVERY_S`) until one of 1-4 decides it.

**Gates this adds or changes (PHONE-CANCEL-FILLED-AS-SKIPPED):** none. ``not_found`` no longer closes a ticket without
evidence; nothing is blocked or halted.

CLOSE / REDUCE (operator 2026-11-09, "the system must be able to take whatever actions necessary"): the same channel
carries ``kind: close`` for a named ticket's open position (``request_close``; ``fraction`` < 1 = reduce). It is
requested by a decision point (``live_review_apply`` close / partial_close for phone accounts), claimed by an app that
declares ``"close"``, and reported ``kind: close_result`` as ``done`` / ``not_found`` / ``failed`` / ``ambiguous``.
``done`` and ``not_found`` end it; the rest back off with ONE flag after :data:`FLAG_AFTER`, never a stop. The phone
closes only through the position sheet's own Close position flow and re-reads Positions; a reduce needs the close
dialog's quantity input, which no capture has shown, so it captures that dialog and reports ``failed``.

The superseded reason only WITHDRAWS the stale order; releasing the newer suppressed ticket is the existing
``prop_supersede`` path and is not driven from here (filed on the checklist row).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Mapping, Optional

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
VERIFY_EVERY_S = 600             # an unverified not_found is re-checked at most this often (journal, venue read, price)
VENUE_LOOKBACK_S = 3 * 3600      # account_status snapshots scanned for the newest CLEAN Positions read
_BAR_S = 300
_TOUCH_TOL = 0.0005              # "never reached" needs every bar to stay this far (relative) clear of the limit
_bars_fn: Optional[Callable[..., Any]] = None   # tests inject; default fill_inference.default_bars


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
                if st == "not_found" and c.get("verify") == "pending":
                    nc = _parse(c.get("next_check_at"))
                    if nc is None or nc <= now:
                        try:
                            resolve_not_found(account_id, r["ticket_id"], now=now, send=send)
                        except Exception:  # noqa: BLE001  # allow-silent: logged; the ticket stays placed, next pass retries
                            logger.warning("phone_cancel: not_found re-check failed %s %s", account_id,
                                           r["ticket_id"], exc_info=True)
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
    """The phone's report of one claimed cancel. Only ``cancelled`` / ``not_found`` end the request: ``cancelled`` makes
    the ticket ``skipped``; ``not_found`` is resolved from evidence by :func:`resolve_not_found` (filled, skipped, or kept
    ``placed`` until it can tell). Anything else fails THAT attempt (backoff, then retried; ONE red flag after
    :data:`FLAG_AFTER`)."""
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
            if result == "not_found":
                c.update(verify="pending", looked_at=str(c.get("claimed_at") or now.isoformat()))
            if not _cas(conn, tid, r["meta"], {**m, KEY: c}):
                return {"ok": False, "kind": "cancel_result", "why": "lost a race"}
            if result == "not_found":
                conn.close()
                conn = None
                v = resolve_not_found(acct, tid, now=now, send=send, first=True)
                return {"ok": True, "kind": "cancel_result", "result": result, "verdict": v.get("verdict"),
                        "ticket_updated": v.get("ticket_updated", 0)}
            n = prop_journal.transition_ticket_status(tid, "skipped", from_statuses=("placed",), account_id=acct)
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
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------- not_found: did the order FILL? (PHONE-CANCEL-FILLED-AS-SKIPPED)
def _venue_read(account_id: str, now: datetime) -> tuple:
    """(positions, read_at) from the newest CLEAN Positions read in the last :data:`VENUE_LOOKBACK_S`, else (None, None).
    Only ``positions_state == "read"`` counts: "we could not look" is never "flat"."""
    import json as _json
    since = (now - timedelta(seconds=VENUE_LOOKBACK_S)).isoformat()
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        rows = conn.execute("SELECT reported_at, raw FROM prop_account_status WHERE account_id = ? AND reported_at >= ? "
                            "ORDER BY id DESC LIMIT 200", (account_id, since)).fetchall()
    finally:
        conn.close()
    for row in rows:
        try:
            raw = _json.loads(row["raw"] or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(raw, dict) and raw.get("positions_state") == "read" and isinstance(raw.get("positions"), list):
            at = _parse(row["reported_at"])
            if at is not None and at <= now + timedelta(minutes=5):
                return raw["positions"], at
    return None, None


def _placed_at(r: Any, m: Mapping[str, Any], fills: list) -> Optional[datetime]:
    """When the entry reached the venue: the ticket's placed fill (fill_inference's own rule), else the go-token
    redemption, else the phone claim, else the signal time."""
    from src.prop.fill_inference import _placed_at as fi_placed_at
    for f in fills:
        if str(f.get("status") or "").lower() == "placed":
            at = fi_placed_at(f)
            if at is not None:
                return at
    ph = m.get("phone") if isinstance(m.get("phone"), dict) else {}
    return (_parse((ph.get("go") or {}).get("used_at")) or _parse(ph.get("claimed_at"))
            or _parse(r["signal_time"]) or _parse(r["created_at"]))


def _price_path(symbol: str, side: str, limit: float, placed_at: datetime, looked_at: datetime) -> str:
    """``through`` (a bar opened after placement traded strictly through the limit: it filled), ``not_reached`` (every
    bar from the placement bar to the cancel stayed clear of the limit: it cannot have filled), ``touched`` (neither),
    or ``unread`` (feed empty / does not cover the window). Same feed and strictness as fill_inference."""
    from src.prop import fill_inference as fi
    fn = _bars_fn or fi.default_bars
    start = placed_at - timedelta(seconds=_BAR_S)
    bars = [b for b in (fn(symbol, start, looked_at) or []) if start < b[0] <= looked_at]
    if not bars or max(b[0] for b in bars) < looked_at - timedelta(seconds=2 * _BAR_S) \
            or min(b[0] for b in bars) > placed_at + timedelta(seconds=_BAR_S):
        return "unread"
    if any(b[0] >= placed_at and fi._through(side, limit, b[1], b[2]) for b in bars):
        return "through"
    tol = limit * _TOUCH_TOL
    clear = all((b[2] > limit + tol) if side == "long" else (b[1] < limit - tol) for b in bars)
    return "not_reached" if clear else "touched"


def _position_verdict(account_id: str, r: Any, m: Mapping[str, Any], looked_at: datetime,
                      now: datetime) -> Dict[str, Any]:
    """Decide what a not_found cancel means for ONE ticket. Pure read (no writes). See the module doc, steps 1-5."""
    from src.prop.prop_overview import split_fills
    tid = r["ticket_id"]
    sym = str(r["symbol"] or "").upper()
    side = {"buy": "long", "sell": "short"}.get(str(r["direction"] or "").lower(), str(r["direction"] or "").lower())
    fills = prop_journal.list_fills(account_id=account_id, limit=500)
    mine = [f for f in fills if str(f.get("ticket_id") or "") == tid]
    open_rows, closed_rows = split_fills(fills)
    if any(str(f.get("ticket_id") or "") == tid for f in open_rows + closed_rows):
        return {"verdict": "filled_journal", "basis": "the journal already has a fill on this ticket"}
    positions, read_at = _venue_read(account_id, now)
    venue_state = "not_read"
    if positions is not None and side in ("long", "short"):
        on_venue = next((p for p in positions if str(p.get("symbol") or "").upper() == sym
                         and p.get("direction") == side), None)
        if on_venue is None:
            venue_state = "flat"
        elif any(str(f.get("symbol") or "").upper() == sym and _entry_side(f.get("direction")) == _entry_side(side)
                 for f in open_rows if f.get("account_id") == account_id):
            venue_state = "other_row"   # another open journal row already accounts for that venue position
        else:
            return {"verdict": "filled_venue", "position": on_venue, "read_at": read_at.isoformat(),
                    "basis": f"clean Positions read at {read_at.isoformat()} shows {sym} {side}"}
    placed_at = _placed_at(r, m, mine)
    limit = _f(r["entry"])
    price = "unread"
    if placed_at is not None and limit and side in ("long", "short"):
        price = _price_path(sym, side, limit, placed_at, looked_at)
    flat_after = venue_state == "flat" and read_at is not None and read_at >= looked_at
    base = {"price_path": price, "placed_at": placed_at.isoformat() if placed_at else None,
            "venue_read_at": read_at.isoformat() if read_at else None,
            "venue": "flat_after_cancel" if flat_after else ("flat_before_cancel" if venue_state == "flat" else venue_state)}
    if price == "not_reached":
        return {**base, "verdict": "never_filled",
                "basis": f"{sym} candles never reached the {side} limit {limit:g} between placement and the cancel"}
    if price == "through" and not flat_after:
        return {**base, "verdict": "filled_estimated",
                "basis": f"{sym} candles traded through the {side} limit {limit:g} after placement; no clean Positions "
                         f"read contradicts it"}
    if flat_after and price in ("touched", "unread"):
        # flat AFTER the cancel looked, and the price never traded through the limit: it never filled
        return {**base, "verdict": "never_filled" if price == "touched" else "unverified",
                "basis": (f"clean Positions read at {read_at.isoformat()} (after the cancel) is flat on {sym} {side} "
                          f"and the price only touched the limit") if price == "touched" else
                         "flat Positions read after the cancel, but the price path is unreadable"}
    return {**base, "verdict": "unverified",
            "basis": ("flat Positions read after the cancel but the price traded through the limit (filled and "
                      "closed, or the feed disagrees with the venue)") if flat_after else
                     f"no clean Positions read after the cancel and the price path is '{price}'"}


def resolve_not_found(account_id: str, ticket_id: str, *, now: Optional[datetime] = None,
                      send: Optional[Callable[..., Any]] = None, first: bool = False) -> Dict[str, Any]:
    """Apply :func:`_position_verdict` to a ``not_found`` ticket. Writes: an ``open`` fill (venue / estimated) through
    ``ingest_report`` (which moves the ticket to ``filled``), or ``placed -> skipped`` on a never-filled verdict, or
    nothing (``unverified``: the ticket stays ``placed``; ONE alert on the first look). Idempotent."""
    from src.prop import fill_inference as fi
    from src.prop.prop_report import ingest_report
    from src.runtime.provenance import ESTIMATED, MEASURED
    now = now or _now()
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        r = conn.execute("SELECT * FROM prop_tickets WHERE ticket_id = ? AND account_id = ?",
                         (ticket_id, account_id)).fetchone()
    finally:
        conn.close()
    if r is None:
        return {"verdict": None, "why": "unknown ticket"}
    m = _meta(r["meta"])
    c = _load(m)
    if c.get("status") != "not_found" or c.get("verify") != "pending":
        return {"verdict": (c.get("position_check") or {}).get("verdict"), "why": "already resolved"}
    looked_at = _parse(c.get("looked_at")) or _parse(c.get("finished_at")) or now
    v = _position_verdict(account_id, r, m, looked_at, now)
    verdict = v["verdict"]
    venue_sym = (c.get("spec") or {}).get("venue_symbol") or r["symbol"]
    side = {"buy": "long", "sell": "short"}.get(str(r["direction"] or "").lower(), str(r["direction"] or "").lower())
    n = 0
    msg = None
    if str(r["status"] or "") != "placed" and verdict not in ("filled_journal",):
        verdict, v = "moved_on", {**v, "verdict": "moved_on", "basis": f"ticket is now {r['status']!r}"}
    if verdict == "filled_venue":
        p = v["position"]
        ingest_report({"kind": "fill", "status": "open", "account_id": account_id, "ticket_id": ticket_id,
                       "symbol": r["symbol"], "direction": side, "qty": _f(p.get("qty")) or _f(r["qty"]),
                       "entry_price": _f(p.get("entry")) or _f(r["entry"]), "sl": _f(r["sl"]), "tp": _f(r["tp"]),
                       "opened_at": v.get("read_at"), "source": "phone_cancel", "provenance": MEASURED,
                       "venue_position": p,
                       "reason": "filled: the stale-entry cancel found no open order and the terminal's Positions "
                                 "list shows the position (PHONE-CANCEL-FILLED-AS-SKIPPED)"})
        n = 1
        msg = (f"📱 phone {account_id}: [{ticket_id}] stale-entry cancel found no open order because it FILLED: "
               f"{r['symbol']} {side} is on the terminal's Positions list. Journaled OPEN (venue entry/size); the "
               f"ticket stays in the risk book and its close will be recorded.")
    elif verdict == "filled_estimated":
        limit = _f(r["entry"])
        ingest_report({"kind": "fill", "status": "open", "account_id": account_id, "ticket_id": ticket_id,
                       "external_order_id": fi._ext(ticket_id), "symbol": str(r["symbol"]).upper(), "direction": side,
                       "qty": _f(r["qty"]), "entry_price": limit, "sl": _f(r["sl"]), "tp": _f(r["tp"]),
                       "opened_at": v.get("placed_at"), "source": fi.SOURCE, "provenance": ESTIMATED, "inferred": True,
                       "reason": f"INFERRED fill (ESTIMATED, not a venue read): the stale-entry cancel found no open "
                                 f"order and {r['symbol']} candles traded through the {side} limit {limit:g} after "
                                 f"placement; entry is the limit price (PHONE-CANCEL-FILLED-AS-SKIPPED)"})
        n = 1
        msg = (f"📱 phone {account_id}: [{ticket_id}] stale-entry cancel found no open order, and the price traded "
               f"through the limit: journaled as FILLED (ESTIMATED, entry = limit). Kept in the risk book; its SL/TP close "
               f"is inferred from the candles until a Positions read measures it. CHECK the terminal for {venue_sym}.")
    elif verdict == "never_filled":
        n = prop_journal.transition_ticket_status(ticket_id, "skipped", from_statuses=("placed",), account_id=account_id)
        msg = (f"📱 phone {account_id}: [{ticket_id}] stale-entry cancel found no open order; it never filled "
               f"({v['basis']}). Ticket closed as skipped.")
    elif verdict == "unverified" and first:
        msg = (f"📱 phone {account_id}: [{ticket_id}] stale-entry cancel found NO matching open order, and the server "
               f"cannot yet tell whether it FILLED ({v['basis']}). Ticket KEPT as placed (in the risk book), re-checked "
               f"every {VERIFY_EVERY_S // 60} min. CHECK the terminal for a position on {venue_sym}.")
    # record the verdict on the cancel slot (CAS on the meta read above; a lost race re-checks next pass)
    c["position_check"] = {k: val for k, val in v.items() if k != "position"} | {"at": now.isoformat()}
    if verdict == "unverified":
        c["next_check_at"] = (now + timedelta(seconds=VERIFY_EVERY_S)).isoformat()
        c["checks"] = int(c.get("checks") or 0) + 1
    else:
        c["verify"] = "done"
    conn = prop_journal._connect()
    try:
        cur = conn.execute("SELECT meta FROM prop_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if cur is not None:
            m2 = _meta(cur["meta"])
            _cas(conn, ticket_id, cur["meta"], {**m2, KEY: {**_load(m2), **{k: c[k] for k in
                 ("position_check", "verify", "next_check_at", "checks") if k in c}}})
    finally:
        conn.close()
    if msg:
        _send(msg, send)
    logger.info("phone_cancel: not_found %s %s -> %s (%s)", account_id, ticket_id, verdict, v.get("basis"))
    return {"verdict": verdict, "basis": v.get("basis"), "ticket_updated": n}


# ---------------------------------------------------------------- close / reduce (the general action channel)
CLOSE_KEY = "phone_close"
CLOSE_RESULTS = ("done", "not_found", "failed", "ambiguous")
_CLOSE_TERMINAL = ("done", "not_found")


def request_close(account_id: str, ticket_id: str, *, fraction: Optional[float] = None, reason: str = "",
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """Issue ONE close (``fraction`` None / 1) or reduce (0 < fraction < 1) of the open position of a named ticket.
    One slot per ticket; a request already outstanding is not duplicated. Never touches the venue."""
    now = now or _now()
    f = None if fraction is None else _f(fraction)
    if f is not None and not 0 < f <= 1:
        return {"ok": False, "why": f"fraction {fraction!r} out of range (0, 1]"}
    action = "close" if f is None or f >= 1 else "reduce"
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        r = conn.execute("SELECT * FROM prop_tickets WHERE ticket_id = ? AND account_id = ?",
                         (ticket_id, account_id)).fetchone()
        if r is None:
            return {"ok": False, "why": "unknown ticket for this account"}
        m = _meta(r["meta"])
        if m.get("test") or m.get("origin") == "exec_test":
            return {"ok": False, "why": "test ticket"}
        if str(r["status"] or "") not in ("placed", "filled"):
            return {"ok": False, "why": f"ticket is {r['status']!r}: no position to act on"}
        c = dict(m.get(CLOSE_KEY) or {})
        if c.get("status") in ("emitted", "claimed"):
            return {"ok": False, "why": f"a {c.get('action')} request is already {c.get('status')}", "close_id": c.get("id")}
        from src.prop import phone_executor as pe
        venue = pe.venue_symbol(account_id, r["symbol"])
        side = str(r["direction"] or "").lower()
        if not venue or side not in ("long", "short"):
            return {"ok": False, "why": "venue symbol or side unreadable"}
        n = int(c.get("seq") or 0) + 1
        c = {"status": "emitted", "action": action, "id": f"{ticket_id}-x{n}", "seq": n, "attempts": 0, "reason": reason[:200],
             "spec": {"venue_symbol": venue, "side": side, "qty": _f(_venue_qty(account_id, r["symbol"], r["qty"])),
                      "fraction": f if action == "reduce" else None},
             "emitted_at": now.isoformat(), "valid_until": (now + timedelta(seconds=CANCEL_VALID_S)).isoformat(),
             "history": c.get("history") or []}
        if not _cas(conn, ticket_id, r["meta"], {**m, CLOSE_KEY: c}):
            return {"ok": False, "why": "lost a race"}
        return {"ok": True, "close_id": c["id"], "action": action}
    finally:
        conn.close()


def plan_closes(account_id: str, *, now: Optional[datetime] = None,
                send: Optional[Callable[..., Any]] = None) -> int:
    """Re-arm a close claim the phone never reported and a failed attempt after its backoff. Returns emitted count."""
    now = now or _now()
    emitted = 0
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        for r in conn.execute("SELECT * FROM prop_tickets WHERE account_id = ?", (account_id,)).fetchall():
            m = _meta(r["meta"])
            c = dict(m.get(CLOSE_KEY) or {})
            st = c.get("status")
            if st == "emitted":
                vu = _parse(c.get("valid_until"))
                if vu is not None and vu > now:
                    emitted += 1
                    continue
                st = "failed"
                c["next_try_at"] = None
            if st == "claimed":
                at = _parse(c.get("claimed_at"))
                if at is None or (now - at).total_seconds() < CLAIM_TIMEOUT_S:
                    continue
                n = int(c.get("attempts") or 0) + 1
                c.update(status="failed", attempts=n, last_result="unreported", next_try_at=(now + _backoff(n)).isoformat())
                _hist(c, {"at": now.isoformat(), "result": "unreported", "attempt": n})
                if _cas(conn, r["ticket_id"], r["meta"], {**m, CLOSE_KEY: c}) and n == FLAG_AFTER:
                    _send(f"📱 phone {account_id}: [{r['ticket_id']}] {c.get('action')} was claimed but never reported "
                          f"({n} attempts); the position may be unchanged. Retrying with backoff.", send)
                continue
            if st != "failed":
                continue
            nt = _parse(c.get("next_try_at"))
            if nt is not None and nt > now:
                continue
            n = int(c.get("seq") or 0) + 1
            c.update(status="emitted", id=f"{r['ticket_id']}-x{n}", seq=n, emitted_at=now.isoformat(),
                     valid_until=(now + timedelta(seconds=CANCEL_VALID_S)).isoformat())
            if _cas(conn, r["ticket_id"], r["meta"], {**m, CLOSE_KEY: c}):
                emitted += 1
    finally:
        conn.close()
    return emitted


def pending_closes(account_id: str, now: Optional[datetime] = None) -> int:
    now = now or _now()
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        rows = conn.execute("SELECT meta FROM prop_tickets WHERE account_id = ?", (account_id,)).fetchall()
    finally:
        conn.close()
    n = 0
    for r in rows:
        c = (_meta(r["meta"]).get(CLOSE_KEY) or {})
        vu = _parse(c.get("valid_until"))
        if c.get("status") == "emitted" and vu and vu > now:
            n += 1
    return n


def claim_close(device: Any, now: Optional[datetime] = None, *, accepts_reduce: bool = False,
                send: Optional[Callable[..., Any]] = None) -> Optional[Dict[str, Any]]:
    """Atomically claim the oldest emitted close/reduce for the device's account.

    A REDUCE is served only to an app that declares ``"reduce"`` in its claim (PHONE-CLOSE-CARDS, 2026-11-12): builds
    up to 1b.380 do not execute one -- their reduce branch clicks the armed Close position to MEASURE the dialog, then
    dismisses it and reports ``failed`` -- so serving them a reduce changes nothing at best and, on a venue whose Close
    is one tap, closes the WHOLE position while reporting failed. Such a reduce ends ``refused`` with ONE ping naming
    why (capability negotiation, the same pattern as ``amend`` / ``cancel`` / ``close``); a full close is unaffected."""
    from src.prop import phone_executor as pe
    now = now or _now()
    acct = device.account_id
    if pe.kill_switch(acct) == "off":
        return None
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        for r in conn.execute("SELECT * FROM prop_tickets WHERE account_id = ? ORDER BY created_at ASC", (acct,)).fetchall():
            m = _meta(r["meta"])
            c = dict(m.get(CLOSE_KEY) or {})
            vu = _parse(c.get("valid_until"))
            if c.get("status") != "emitted" or vu is None or vu <= now:
                continue
            if c.get("action") == "reduce" and not accepts_reduce:
                c.update(status="refused", finished_at=now.isoformat(), last_result="refused",
                         last_reason="app build does not execute a reduce (claim lacks 'reduce')")
                _hist(c, {"at": now.isoformat(), "result": "refused", "close_id": c.get("id"),
                          "reason": "app build does not execute a reduce"})
                if _cas(conn, r["ticket_id"], r["meta"], {**m, CLOSE_KEY: c}):
                    _send(f"📱 phone {acct}: [{r['ticket_id']}] reduce of {(c.get('spec') or {}).get('venue_symbol')} "
                          f"REFUSED, not executed: this phone app build does not execute a partial close. The position is "
                          f"unchanged.", send)
                continue
            c.update(status="claimed", claimed_at=now.isoformat(), device_id=device.device_id)
            if not _cas(conn, r["ticket_id"], r["meta"], {**m, CLOSE_KEY: c}):
                continue
            return {"kind": "close", "ticket_id": r["ticket_id"], "close_id": c["id"], "action": c.get("action"),
                    "reason": c.get("reason"), "symbol": r["symbol"], "spec": c.get("spec"),
                    "venue_symbol": (c.get("spec") or {}).get("venue_symbol"),
                    "submit": pe.submit_mode(acct, test=False), "claimed_at": now.isoformat()}
        return None
    finally:
        conn.close()


def record_close_result(device: Any, body: Mapping[str, Any], *, now: Optional[datetime] = None,
                        send: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """The phone's report of one claimed close/reduce: done / not_found end it; failed / ambiguous back off."""
    now = now or _now()
    acct = device.account_id
    tid, cid, result = str(body.get("ticket_id") or ""), str(body.get("close_id") or ""), str(body.get("result") or "")
    if result not in CLOSE_RESULTS:
        raise ValueError("close_result.result invalid")
    reason = str(body.get("reason") or "")[:300]
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        r = conn.execute("SELECT * FROM prop_tickets WHERE ticket_id = ? AND account_id = ?", (tid, acct)).fetchone()
        if r is None:
            return {"ok": False, "kind": "close_result", "why": "unknown ticket"}
        m = _meta(r["meta"])
        c = dict(m.get(CLOSE_KEY) or {})
        if c.get("id") != cid or c.get("status") != "claimed":
            return {"ok": False, "kind": "close_result", "why": "not the claimed close"}
        entry = {"at": now.isoformat(), "result": result, "reason": reason, "close_id": cid}
        what = c.get("action") or "close"
        sym = (c.get("spec") or {}).get("venue_symbol")
        if result in _CLOSE_TERMINAL:
            c.update(status=result, finished_at=now.isoformat(), last_result=result)
            _hist(c, entry)
            if not _cas(conn, tid, r["meta"], {**m, CLOSE_KEY: c}):
                return {"ok": False, "kind": "close_result", "why": "lost a race"}
            if result == "done":
                _send(f"📱 phone {acct}: [{tid}] {what} of {sym} DONE on the terminal (Positions re-read: {reason[:100]}).", send)
            else:
                _send(f"📱 phone {acct}: [{tid}] {what} found NO matching position on the terminal's Positions "
                      f"(already closed?). CHECK the terminal for {sym}.", send)
            return {"ok": True, "kind": "close_result", "result": result}
        n = int(c.get("attempts") or 0) + 1
        c.update(status="failed", attempts=n, last_result=result, last_reason=reason,
                 next_try_at=(now + _backoff(n)).isoformat())
        _hist(c, {**entry, "attempt": n})
        if not _cas(conn, tid, r["meta"], {**m, CLOSE_KEY: c}):
            return {"ok": False, "kind": "close_result", "why": "lost a race"}
        if n == FLAG_AFTER:
            _send(f"📱 phone {acct}: [{tid}] {what} of {sym} failed {n} times (last: {result}: {reason[:120]}); the "
                  f"position may be UNCHANGED. Retrying with backoff, nothing is stopped.", send)
        return {"ok": True, "kind": "close_result", "result": result, "attempt": n}
    finally:
        conn.close()
