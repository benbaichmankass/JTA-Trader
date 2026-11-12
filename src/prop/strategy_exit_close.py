"""PROP-VM-STRATEGY-EXIT-CLOSE: a strategy's own exit CLOSES the prop position, as in the backtest.

Operator, 2026-11-12 ~11:40Z (chat, relayed by AM-TRADING), verbatim: *"Worry about getting the system to do what
it's fucking supposed to do ... Whatever we break whatever gate is there and throw it in the trash."* That answers
decisions-page x1 YES. MEASURED before this module (origin/main 1acc75e24 and later): when a prop leg's ORDER PACKAGE
closed on a strategy decision (sl / tp / trail / a close lever / a review close) the prop venue position stayed OPEN.
The VM trail only stepped its stop, a close lever only alerted, and the phone trail only logged the divergence
(breakout_2 pkg-a20ebe8b65ce4c44 closed ``sl`` at 11:32:17Z with the venue position still open).

What this module decides, and nothing else: :func:`is_strategy_exit` -- does a package ``close_reason`` mean the
STRATEGY exited (close the prop position), or is it bookkeeping (a reconciler / watchdog / netting / reset label that
says nothing about the trade)? Every non-empty reason not in :data:`BOOKKEEPING` is a strategy exit. The CLOSE itself
always goes through the account class's existing executor, one implementation each:

* VM accounts (tradeify_1, velotrade_1): ``vm_close.run_close_step`` treats such a ticket as a full-close request with
  the deterministic id ``pkgexit-<ticket_id>`` (:func:`vm_request_id`), so it is idempotent per package and ticket;
  the watched close re-reads the venue flat, and the reconcile journals the exit in ``prop_fills`` from venue history.
* phone accounts (breakout_2): :func:`plan_phone_exits` issues ONE ``phone_cancel.request_close`` per ticket (reason
  ``strategy_exit:<close_reason>``); the phone closes through the position sheet and reports, and its retry/backoff
  and red flag are ``phone_cancel``'s own.

Never a gate and never a halt: a close that fails is retried by its executor with ONE red flag after N failures.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: Package close reasons that are bookkeeping, not a trading decision (MEASURED from the writers in
#: src/runtime/order_monitor.py, src/core/coordinator.py and the reconcilers). Everything else that closes a package
#: is the strategy (or its reviewer) exiting the trade.
BOOKKEEPING = frozenset({
    "netting_attributed", "stuck_strategy_watchdog", "stuck_cascade_recovered", "reconciler_filled", "reconciler",
    "exit_coverage_no_strategy", "exchange_reset_flat", "account_reset", "shadow_no_execute", "prop_shadow_no_emit",
    "options_expiry_assignment", "orphaned", "rejected", "expired", "skipped", "superseded",
})
CLOSED_PKG = ("closed",)
REASON_PREFIX = "strategy_exit:"
VM_ID_PREFIX = "pkgexit-"


def is_strategy_exit(close_reason: Any) -> bool:
    r = str(close_reason or "").strip().lower()
    return bool(r) and r not in BOOKKEEPING


def package_exited(op_status: Any, close_reason: Any) -> bool:
    """The ticket's ORDER PACKAGE is closed on a strategy decision."""
    return str(op_status or "").strip().lower() in CLOSED_PKG and is_strategy_exit(close_reason)


def vm_request_id(ticket_id: Any) -> str:
    return f"{VM_ID_PREFIX}{ticket_id}"


def vm_synth_request(ticket: Any) -> Optional[dict]:
    """The full-close request a VM ticket implies when its package exited and it carries no explicit request."""
    if not isinstance(ticket, dict) or ticket.get("close_request") or not ticket.get("ticket_id"):
        return None
    if str(ticket.get("status") or "").lower() not in ("placed", "filled", "open", "closed"):
        return None
    if not package_exited(ticket.get("op_status"), ticket.get("close_reason")):
        return None
    return {"id": vm_request_id(ticket["ticket_id"]), "fraction": None, "source": "strategy_exit",
            "reason": f"{REASON_PREFIX}{ticket.get('close_reason')}", "synthetic": True}


def plan_phone_exits(account_id: str, *, now: Optional[datetime] = None,
                     send: Optional[Callable[..., Any]] = None) -> int:
    """Issue ONE phone close per filled ticket of ``account_id`` whose package exited. Returns requests issued.
    Idempotent: a ticket whose close slot already carries a strategy-exit request (any status) is never asked again,
    and ``request_close`` refuses while another request is outstanding."""
    from src.prop import phone_cancel, prop_journal
    from src.prop.phone_trail import _meta, _package_state, _send

    now = now or datetime.now(timezone.utc)
    issued = 0
    conn = prop_journal._connect(read_only=True)
    try:
        rows = conn.execute("SELECT ticket_id, order_package_id, meta FROM prop_tickets "
                            "WHERE account_id = ? AND status = 'filled'", (account_id,)).fetchall()
        todo = []
        for r in rows:
            m = _meta(r["meta"])
            if m.get("test") or m.get("origin") == "exec_test":
                continue
            c = m.get(phone_cancel.CLOSE_KEY) if isinstance(m.get(phone_cancel.CLOSE_KEY), dict) else {}
            if str(c.get("reason") or "").startswith(REASON_PREFIX):
                continue
            pk = _package_state(conn, r["order_package_id"])
            if pk and package_exited(pk.get("status"), pk.get("close_reason")):
                todo.append((r["ticket_id"], r["order_package_id"], pk))
    finally:
        conn.close()
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
