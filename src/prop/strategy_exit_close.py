"""PROP-VM-STRATEGY-EXIT-CLOSE: a strategy's own exit CLOSES the prop position, as in the backtest.

Operator, 2026-11-12 ~11:40Z (chat, relayed by AM-TRADING), verbatim: *"Worry about getting the system to do what
it's fucking supposed to do ... Whatever we break whatever gate is there and throw it in the trash."* That answers
decisions-page x1 YES. MEASURED before this module (origin/main 1acc75e24 and later): when a prop leg's ORDER PACKAGE
closed on a strategy decision (sl / tp / trail / a close lever / a review close) the prop venue position stayed OPEN.
The VM trail only stepped its stop, a close lever only alerted, and the phone trail only logged the divergence
(breakout_2 pkg-a20ebe8b65ce4c44 closed ``sl`` at 11:32:17Z with the venue position still open).

What this module decides, and nothing else: the ticket's ORDER PACKAGE is ``closed`` (:func:`package_exited`), so the
prop position is closed too -- whatever the close reason (operator 2026-11-12 ~11:45Z, binding: "no more gates that I
don't explicitly give you permission for"; no reason filter was asked for, so none is applied). The CLOSE itself
always goes through the account class's existing executor, one implementation each:

* VM accounts (tradeify_1, velotrade_1): ``vm_close.run_close_step`` treats such a ticket as a full-close request with
  the deterministic id ``pkgexit-<ticket_id>`` (:func:`vm_request_id`), so it is idempotent per package and ticket;
  the watched close re-reads the venue flat, and the reconcile journals the exit in ``prop_fills`` from venue history.
* phone accounts (breakout_2): :func:`plan_phone_exits` would issue ONE ``phone_cancel.request_close`` per ticket.
  It is INERT -- nothing calls it -- since breakout_2 was breached and put ON ICE (operator ~11:56Z, AM-TRADING
  12:39Z: no phone-app work). Wire it at phone_executor's two ``"close" in accepts`` sites when work row
  PHONE-EXECUTOR-ICE lifts.

Never a gate and never a halt: a close that fails is retried by its executor with ONE red flag after N failures.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

CLOSED_PKG = ("closed",)
REASON_PREFIX = "strategy_exit:"
VM_ID_PREFIX = "pkgexit-"


def package_exited(op_status: Any, close_reason: Any = None) -> bool:
    """The ticket's ORDER PACKAGE is closed (any reason; ``close_reason`` is carried for the alert only)."""
    return str(op_status or "").strip().lower() in CLOSED_PKG


#: Ticket statuses that own venue quantity (a resting or unsent entry owns none).
_OWNS_QTY = ("filled", "open")
SHARED_KEY = "strategy_exit_close"


def sharers(tickets: Any, ticket: Any) -> list:
    """ATTRIBUTION (AM-TRADING 2026-11-12, "correctness, not a gate"): the OTHER tickets on the same account, symbol and
    direction whose order package is still OPEN and which own venue quantity. One package's exit must never close
    their share of a netted venue position."""
    sym, d, tid = str(ticket.get("symbol") or "").upper(), str(ticket.get("direction") or "").lower(), ticket.get(
        "ticket_id")
    out = []
    for o in tickets or ():
        if not isinstance(o, dict) or o.get("ticket_id") == tid:
            continue
        if (str(o.get("symbol") or "").upper() == sym and str(o.get("direction") or "").lower() == d
                and str(o.get("status") or "").lower() in _OWNS_QTY
                and str(o.get("op_status") or "").lower() not in CLOSED_PKG):
            out.append(str(o.get("ticket_id")))
    return out


def vm_request_id(ticket_id: Any) -> str:
    return f"{VM_ID_PREFIX}{ticket_id}"


def vm_synth_request(ticket: Any, all_tickets: Any = ()) -> Optional[dict]:
    """The close request a VM ticket implies when its package exited and it carries no explicit request. When other
    open packages share the venue position, the request carries ``shared_with`` and this ticket's own ``own_qty``:
    the executor then REDUCES by that qty (or, without a partial close, alerts for the call) -- never a flatten."""
    if not isinstance(ticket, dict) or ticket.get("close_request") or not ticket.get("ticket_id"):
        return None
    if not package_exited(ticket.get("op_status"), ticket.get("close_reason")):
        return None
    req = {"id": vm_request_id(ticket["ticket_id"]), "fraction": None, "source": "strategy_exit",
           "reason": f"{REASON_PREFIX}{ticket.get('close_reason')}", "synthetic": True}
    others = sharers(all_tickets, ticket)
    if others:
        req.update(shared_with=others, own_qty=ticket.get("qty"))
    return req


def plan_phone_exits(account_id: str, *, now: Optional[datetime] = None,
                     send: Optional[Callable[..., Any]] = None) -> int:
    """Issue ONE phone close per filled ticket of ``account_id`` whose package exited. Returns requests issued.
    Idempotent: a ticket whose close slot already carries a strategy-exit request (any status) is never asked again,
    and ``request_close`` refuses while another request is outstanding."""
    from src.prop import phone_cancel, prop_journal
    from src.prop.phone_trail import _cas, _meta, _package_state, _send

    now = now or datetime.now(timezone.utc)
    issued = 0
    conn = prop_journal._connect(read_only=True)
    try:
        rows = conn.execute("SELECT ticket_id, order_package_id, symbol, direction, meta FROM prop_tickets "
                            "WHERE account_id = ? AND status = 'filled'", (account_id,)).fetchall()
        view = []
        for r in rows:
            pk = _package_state(conn, r["order_package_id"]) or {}
            view.append({"ticket_id": r["ticket_id"], "symbol": r["symbol"], "direction": r["direction"],
                         "status": "filled", "op_status": pk.get("status"), "_pk": pk, "_row": r})
        todo, shared = [], []
        for v in view:
            r, pk = v["_row"], v["_pk"]
            m = _meta(r["meta"])
            if m.get("test") or m.get("origin") == "exec_test":
                continue
            c = m.get(phone_cancel.CLOSE_KEY) if isinstance(m.get(phone_cancel.CLOSE_KEY), dict) else {}
            if str(c.get("reason") or "").startswith(REASON_PREFIX):
                continue
            if not (pk and package_exited(pk.get("status"), pk.get("close_reason"))):
                continue
            others = sharers(view, v)
            if others:
                # ATTRIBUTION: the phone has no reduce (refused at claim since #25227), so a close here would also
                # close the other open package(s)' share. ONE alert asks for the call; nothing is closed.
                if not (m.get(SHARED_KEY) or {}).get("alerted"):
                    shared.append((r, m, pk, others))
                continue
            todo.append((r["ticket_id"], r["order_package_id"], pk))
    finally:
        conn.close()
    for r, m, pk, others in shared:
        w = prop_journal._connect()
        try:
            ok = _cas(w, r["ticket_id"], r["meta"], {**m, SHARED_KEY: {"alerted": now.isoformat(), "shared_with": others}})
        finally:
            w.close()
        if ok:
            _send(f"📱 phone {account_id}: [{r['ticket_id']}] strategy exited ({pk.get('close_reason')}, package "
                  f"{r['order_package_id']} closed) but the venue position is SHARED with open ticket(s) {others} on "
                  f"{r['symbol']} {r['direction']}. The phone cannot reduce, so NOTHING was closed: your call "
                  "(close all, or leave it for the other package)", send)
    for tid, opid, pk in todo:
        res = phone_cancel.request_close(account_id, tid, reason=f"{REASON_PREFIX}{pk.get('close_reason')} {opid}",
                                         now=now)
        if res.get("ok"):
            issued += 1
            _send(f"📱 phone {account_id}: [{tid}] strategy exited ({pk.get('close_reason')}, package {opid} closed "
                  f"{pk.get('updated_at')}) with the position still open: close request {res.get('close_id')} issued "
                  "to the phone", send)
        else:
            logger.info("strategy_exit_close: %s %s not requested: %s", account_id, tid, res.get("why"))
    return issued
