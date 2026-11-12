"""PROP-BRACKET-APPLY: ask the system to set a VM-executed prop ticket's TP and/or SL, without the operator.

Operator, 2026-11-11 (relayed by the manager): *"it has to be able to do it on its own ... these are basic system
requirements."* Before this module the only prop apply was the live-review stop floor (``meta.sl_floor``); a TP
could be moved only by the trail's declared rule or by a human in the terminal.

DESIGN. No second venue client and no second login. A request is a write to the ticket's ``meta`` (the same place
the live-review stop floor lives); the account's own executor trail (``prop_trail.run_trail_step``) reads it on its
next cycle and applies it through its OWN amend code (``modify_bracket``, re-read, confirm, report), so every
existing guard binds it: the bounded rollout step, the venue-quote buffer, the retry backoff and the red flag.

* TP -> ``meta.tp_target``. Applied by ``prop_trail._tp_step``; it wins over any declared TP rule while it is set
  (``clear_tp`` removes it). Only an adapter that declares ``TP_AMEND_SUPPORTED`` can carry it: ``dxtrade_api``
  (velotrade_1) and, since CAP-TRADEIFY-TP-AMEND (2026-11-12), browser ``dxtrade`` (tradeify_1). Everything else is REFUSED here with the reason, never queued where it would sit unread.
* SL -> ``meta.sl_floor``, exactly what ``live_review_apply._exec_prop_vm`` writes. Tighten-only: a stop looser
  than the ticket's own is refused (both prop executors refuse a looser stop by construction).

The venue's confirmation is the executor's own ``amend`` report (``/api/bot/prop/fills`` ``amendments``); this
module reports ``queued`` and reads its own write back, never a venue state it did not read.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

PROVENANCE = "system_bracket_request"
_LIVE_STATUS = ("placed", "filled")

R_QUEUED, R_DRY, R_REFUSED, R_FAILED = "queued", "dry_run", "refused", "apply_failed"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x > 0 else None


def amend_capability(account_id: str, platforms_path: Optional[Path] = None) -> Dict[str, Any]:
    """What this account's executor can amend: ``{"tp": bool, "sl": bool, "why": str}``. Pure config read."""
    from src.prop.phone_executor import is_phone_account
    from src.prop.platform import load_platform_config

    try:
        if is_phone_account(account_id, platforms_path):
            return {"tp": False, "sl": False, "why": (
                f"{account_id} is a phone account: its amends go through the phone's one-slot channel "
                "(phone_trail.request_tp_amend / request_sl_tighten via live_review_apply), not a VM ticket pin")}
    except Exception:  # noqa: BLE001 -- an unreadable phone section falls through to the account lookup
        pass
    try:
        platform = str(load_platform_config(account_id, platforms_path).get("platform") or "")
    except Exception as exc:  # noqa: BLE001
        return {"tp": False, "sl": False, "why": f"{account_id} is not a VM-executed prop account ({exc})"}
    if platform == "dxtrade_api":
        return {"tp": True, "sl": True, "why": "dxtrade_api: the executor's trail amends TP and SL over REST"}
    if platform == "dxtrade":
        return {"tp": True, "sl": True, "why": (
            "browser dxtrade: the trail amends a TP as a TP-only rollout step and an SL as a tighten-only step "
            "(CAP-TRADEIFY-TP-AMEND, operator 2026-11-12)")}
    return {"tp": False, "sl": False, "why": f"platform {platform!r} has no executor amend path"}


def _refuse(why: str, **kw: Any) -> Dict[str, Any]:
    return {"result": R_REFUSED, "detail": why, **kw}


def request_bracket(ticket_id: str, *, account_id: str, tp: Optional[float] = None, sl: Optional[float] = None,
                    clear_tp: bool = False, source: str = PROVENANCE, reason: str = "", apply: bool = False,
                    platforms_path: Optional[Path] = None) -> Dict[str, Any]:
    """Validate, and (``apply``) write one request on a live prop ticket. Dry by default: nothing is written."""
    from src.prop import prop_journal
    from src.prop.phone_trail import _cas, _meta
    from src.runtime.live_review_intent import TP_TARGET_KEY, sl_floor_from, tp_target_from

    tp, sl = _f(tp), _f(sl)
    if clear_tp and tp is not None:
        return _refuse("clear_tp and tp are mutually exclusive")
    if tp is None and sl is None and not clear_tp:
        return _refuse("nothing to do: give tp and/or sl (or clear_tp)")
    cap = amend_capability(account_id, platforms_path)
    if (tp is not None or clear_tp) and not cap["tp"]:
        return _refuse(f"{account_id} cannot amend a TP: {cap['why']}", capability=cap)
    if sl is not None and not cap["sl"]:
        return _refuse(f"{account_id} cannot amend an SL: {cap['why']}", capability=cap)
    tk = prop_journal.get_ticket(ticket_id)
    if tk is None:
        return _refuse(f"ticket {ticket_id!r} not readable in the prop journal")
    if str(tk.get("account_id")) != account_id:
        return _refuse(f"ticket {ticket_id} belongs to {tk.get('account_id')!r}, not {account_id!r}")
    if str(tk.get("status")) not in _LIVE_STATUS:
        return _refuse(f"ticket is {tk.get('status')!r}, not placed/filled")
    direction, entry, t_sl = str(tk.get("direction") or ""), _f(tk.get("entry")), _f(tk.get("sl"))
    if direction not in ("long", "short") or entry is None:
        return _refuse("ticket has no readable direction/entry")
    if tp is not None and not (tp > entry if direction == "long" else tp < entry):
        return _refuse(f"TP {tp} is not on the profit side of the {direction} entry {entry}")
    if sl is not None and t_sl is not None and (sl < t_sl if direction == "long" else sl > t_sl):
        return _refuse(f"SL {sl} is looser than the ticket's {t_sl}: a prop executor never loosens a stop")
    now = datetime.now(timezone.utc).isoformat()
    stamp = {"source": source, "reason": reason, "at": now}

    def _apply_to(meta: Dict[str, Any]) -> Dict[str, Any]:
        if tp is not None:
            meta[TP_TARGET_KEY] = {"level": tp, **stamp}
        if clear_tp:
            meta.pop(TP_TARGET_KEY, None)
        if sl is not None:
            meta["sl_floor"] = {"level": sl, **stamp}
        return meta

    plan = {"ticket_id": ticket_id, "account_id": account_id, "tp": tp, "sl": sl, "clear_tp": clear_tp,
            "executor_applies": "on its next cycle, through its own amend code (confirmed by the executor's report)"}
    if not apply:
        return {"result": R_DRY, "detail": "dry run: nothing written", **plan}
    conn = prop_journal._connect()
    try:
        r = conn.execute("SELECT meta, status FROM prop_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if r is None or r["status"] not in _LIVE_STATUS:
            return _refuse("ticket changed state before the write")
        if not _cas(conn, ticket_id, r["meta"], _apply_to(_meta(r["meta"]))):
            return {"result": R_FAILED, "detail": "ticket meta changed under the write (one writer wins); retry", **plan}
    finally:
        conn.close()
    back = prop_journal.get_ticket(ticket_id) or {}
    bm = back.get("meta")
    got_tp, got_sl = tp_target_from(bm), sl_floor_from(bm)
    if tp is not None and (got_tp is None or abs(got_tp - tp) > max(tp * 1e-9, 1e-12)):
        return {"result": R_FAILED, "detail": f"ticket tp_target reads {got_tp!r} after the write", **plan}
    if clear_tp and got_tp is not None:
        return {"result": R_FAILED, "detail": f"ticket tp_target still reads {got_tp!r} after clear", **plan}
    if sl is not None and (got_sl is None or abs(got_sl - sl) > max(sl * 1e-9, 1e-12)):
        return {"result": R_FAILED, "detail": f"ticket sl_floor reads {got_sl!r} after the write", **plan}
    return {"result": R_QUEUED, "detail": "request recorded on the ticket; the executor applies it next cycle", **plan}
