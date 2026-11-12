"""CAP-PROP-VM-CLOSE: the system closes (or partly closes) a VM-executed prop position on its own.

Operator, 2026-11-12 (relayed by Manager Session 2026-11-11a): *"The system needs to be able to do that on its own.
I'm not doing it manually anymore. Enough is enough."* Before this module a tradeify_1 / velotrade_1 position could be
closed only by containment (a naked leg), the round-trip test, or the operator-dispatched ``close-position-live``
system-action. A live-review ``close`` / ``partial_close`` refused ``no_action_path`` on the ``prop_vm`` class.

DESIGN (the PROP-BRACKET-APPLY shape, ``src/prop/bracket_request.py``). No second venue client and no second login:

* :func:`request_close` writes ONE request on the ticket's ``meta.close_request`` (``{id, fraction, reason, source,
  at}``; ``fraction`` None = the whole position) and reads its own write back. Called by
  ``scripts/ops/live_review_apply.py`` after THIS account's ``RiskManager.approve_action`` approved the action.
* :func:`run_close_step` runs inside the account's own executor tick (``scripts/prop/prop_executor_tick.py``,
  BEFORE the trail step, so a position being closed is not amended first). For each pending request it finds the
  ticket's terminal position the same way the trail does (the open journal row for the symbol and side), then:

  - **close**: ``prop_executor._close_and_confirm`` -- the watched close the round trip and ``close-position-live``
    already use: ``adapter.flatten`` with the row's side / size / fill, re-read until the position is gone, no
    working order left for the symbol, the account re-read. The journal row is then closed by the executor's own
    reconcile from the VENUE's history (``_reconcile_journal``: exit price MEASURED, never estimated here).
  - **partial close**: ``adapter.reduce_position`` (only an adapter declaring ``PARTIAL_CLOSE_SUPPORTED``:
    ``dxtrade_api``, velotrade_1), then the read-back: the position's quantity dropped by the closed amount AND both
    brackets still rest at the venue at their prices (TP doctrine clause 3; MD-LTR-PROP-AUTO bound ``both_brackets``).
    Anything else is ``apply_failed``, alerted. The browser ``dxtrade`` adapter (tradeify_1) closes only the FULL
    size through its Close Position modal (lots-to-close is never edited, ``DXtradeAdapter.flatten``); a partial
    there is REFUSED at request time with that reason, never queued where it would sit unread.

  ``read_only`` / ``off`` executor modes act on nothing (read_only walks the close dry and leaves the request
  pending). Outcomes live in ``<state dir>/vm_close_done.json`` keyed by request id. NO HALTING: a full close that
  fails is retried every tick (``flatten`` re-checks the row's side / size / fill first, so a resend can only close
  the same position), alerted on its first failure and ONE red flag after :data:`RED_FLAG_AFTER`; a position already
  gone is ``closed``. A partial close is sent ONCE: a resend after an outcome nobody read could close twice, so a
  failed partial is ``apply_failed``, alerted, and the reviewer's next row is a new request.

A tighten stays where it was: ``meta.sl_floor``, applied tighten-only by the trail's bounded ``ModifyRollout`` step
(``live_review_apply._exec_prop_vm``). Nothing here moves a stop or a target.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

KEY = "close_request"
PROVENANCE = "system_close_request"
DONE_FILE = "vm_close_done.json"
#: Consecutive failed full-close ticks before ONE red flag (the close keeps retrying).
RED_FLAG_AFTER = 3
_LIVE_STATUS = ("placed", "filled")

R_QUEUED, R_DRY, R_REFUSED, R_FAILED = "queued", "dry_run", "refused", "apply_failed"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x > 0 else None


def _meta(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        m = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def close_request_from(meta: Any) -> Optional[Dict[str, Any]]:
    """The pending close request on a ticket's meta, or None (absent / unreadable)."""
    r = _meta(meta).get(KEY)
    return dict(r) if isinstance(r, dict) and r.get("id") else None


def close_capability(account_id: str, platforms_path: Optional[Path] = None) -> Dict[str, Any]:
    """What this account's VM executor can close: ``{"close": bool, "partial": bool, "why": str}``. Config only."""
    from src.prop.phone_executor import is_phone_account
    from src.prop.platform import load_platform_config

    try:
        if is_phone_account(account_id, platforms_path):
            return {"close": False, "partial": False, "why": (
                f"{account_id} is a phone account: its close goes through phone_cancel.request_close, not the VM")}
    except Exception:  # noqa: BLE001 -- an unreadable phone section falls through to the account lookup
        pass
    try:
        platform = str(load_platform_config(account_id, platforms_path).get("platform") or "")
    except Exception as exc:  # noqa: BLE001
        return {"close": False, "partial": False, "why": f"{account_id} is not a VM-executed prop account ({exc})"}
    if platform == "dxtrade_api":
        return {"close": True, "partial": True, "why": (
            "dxtrade_api: close = one-instrument Bulk Close; partial = a CLOSE market order against the positionCode")}
    if platform == "dxtrade":
        return {"close": True, "partial": False, "why": (
            f"{account_id} is browser dxtrade: its Close Position modal closes the FULL size only (lots-to-close is "
            "never edited; a partial needs that field measured first)")}
    return {"close": False, "partial": False, "why": f"platform {platform!r} has no executor close path"}


def _refuse(why: str, **kw: Any) -> Dict[str, Any]:
    return {"result": R_REFUSED, "detail": why, **kw}


def request_close(ticket_id: str, *, account_id: str, fraction: Optional[float] = None, source: str = PROVENANCE,
                  reason: str = "", review_id: Optional[str] = None, apply: bool = False,
                  platforms_path: Optional[Path] = None) -> Dict[str, Any]:
    """Validate, and (``apply``) write one close request on a live VM prop ticket. Dry by default."""
    from src.prop import prop_journal
    from src.prop.phone_trail import _cas

    if fraction is not None:
        fr = _f(fraction)
        if fr is None or not 0 < fr < 1:
            return _refuse(f"partial fraction must be in (0, 1), got {fraction!r}")
        fraction = fr
    cap = close_capability(account_id, platforms_path)
    if not cap["close"]:
        return _refuse(f"{account_id} cannot close: {cap['why']}", capability=cap)
    if fraction is not None and not cap["partial"]:
        return _refuse(f"{account_id} cannot partly close: {cap['why']}", capability=cap)
    tk = prop_journal.get_ticket(ticket_id)
    if tk is None:
        return _refuse(f"ticket {ticket_id!r} not readable in the prop journal")
    if str(tk.get("account_id")) != account_id:
        return _refuse(f"ticket {ticket_id} belongs to {tk.get('account_id')!r}, not {account_id!r}")
    if str(tk.get("status")) not in _LIVE_STATUS:
        return _refuse(f"ticket is {tk.get('status')!r}, not placed/filled")
    req = {"id": f"vmc-{uuid.uuid4().hex[:12]}", "fraction": fraction, "source": source, "reason": reason,
           "review_id": review_id, "at": datetime.now(timezone.utc).isoformat()}
    plan = {"ticket_id": ticket_id, "account_id": account_id, "fraction": fraction,
            "executor_applies": "on its next tick, through its own watched close (confirmed by re-read)"}
    if not apply:
        return {"result": R_DRY, "detail": "dry run: nothing written", **plan}
    conn = prop_journal._connect()
    try:
        r = conn.execute("SELECT meta, status FROM prop_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if r is None or r["status"] not in _LIVE_STATUS:
            return _refuse("ticket changed state before the write")
        m = _meta(r["meta"])
        m[KEY] = req
        if not _cas(conn, ticket_id, r["meta"], m):
            return {"result": R_FAILED, "detail": "ticket meta changed under the write (one writer wins); retry", **plan}
    finally:
        conn.close()
    back = close_request_from((prop_journal.get_ticket(ticket_id) or {}).get("meta"))
    if not back or back.get("id") != req["id"]:
        return {"result": R_FAILED, "detail": f"ticket close_request reads {back!r} after the write", **plan}
    return {"result": R_QUEUED, "close_id": req["id"],
            "detail": "close request recorded on the ticket; the executor closes it next tick", **plan}


# ── the executor side ────────────────────────────────────────────────────


def _load_done(state_dir: Path) -> Dict[str, Any]:
    try:
        d = json.loads((Path(state_dir) / DONE_FILE).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_done(state_dir: Path, done: Mapping[str, Any]) -> None:
    p = Path(state_dir) / DONE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    keep = dict(sorted(done.items(), key=lambda kv: str((kv[1] or {}).get("at") or ""))[-500:])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(keep, indent=1, default=str))
    tmp.replace(p)


def _same(a: Optional[float], b: Optional[float], step: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max((step or 0.0) / 2.0, 1e-9 * max(abs(a), abs(b), 1.0))


def confirm_partial(adapter: Any, page: Any, before: Any, closed_qty: float, venue: str,
                    qty_step: Optional[float], price_step: Optional[float],
                    reads: int, sleep: Callable[[float], None]) -> tuple:
    """Read the venue back after a partial close: (ok, why, after-position facts). OK only when the position's
    quantity is the old one minus ``closed_qty`` AND its SL and TP both still rest at their pre-close prices."""
    want = float(before.quantity) - float(closed_qty)
    last: Dict[str, Any] = {}
    for _ in range(max(1, reads)):
        sleep(2.0)
        try:
            rows = [p for p in adapter.read_positions(page) if p.symbol.upper() == venue and p.side == before.side]
        except Exception as exc:  # noqa: BLE001
            last = {"read_error": type(exc).__name__}
            continue
        if not rows:
            return False, "position GONE after a partial close (closed in full?)", {"positions": 0}
        p = rows[0]
        last = {"quantity": p.quantity, "stop_loss": p.stop_loss, "take_profit": p.take_profit}
        if not _same(_f(p.quantity), want, qty_step):
            continue
        missing = [k for k, v in (("SL", p.stop_loss), ("TP", p.take_profit)) if v is None]
        if missing:
            return False, f"quantity reduced but {'/'.join(missing)} not resting at the venue (both brackets " \
                          f"required)", last
        if not (_same(p.stop_loss, before.stop_loss, price_step) and _same(p.take_profit, before.take_profit,
                                                                            price_step)):
            return False, (f"brackets moved by the partial close (SL {before.stop_loss}->{p.stop_loss}, "
                           f"TP {before.take_profit}->{p.take_profit})"), last
        return True, "", last
    return False, f"quantity not {want} after {reads} re-reads", last


def round_down(x: float, step: Optional[float]) -> float:
    if not step:
        return x
    import math
    return math.floor(x / step + 1e-9) * step


def run_close_step(*, adapter: Any, page: Any, api: Any, cfg: Any, mode: str, state_dir: Path, res: Any,
                   sleep: Callable[[float], None], reads: int = 10) -> Any:
    """One pass over this account's pending close requests. Never raises past one ticket."""
    from src.prop import prop_executor as pe

    if mode not in ("live", "read_only"):
        return res
    live = mode == "live"
    try:
        tickets = [t for t in api.all_tickets(cfg.account_id) if t.get(KEY)]
    except Exception as exc:  # noqa: BLE001
        res.alerts.append(f"close: ticket read failed ({type(exc).__name__}); no close this tick")
        return res
    if not tickets:
        return res
    done = _load_done(state_dir)
    final = ("closed", "reduced", "refused", "apply_failed")
    pending = [t for t in tickets if (t.get(KEY) or {}).get("id")
               and (done.get(t[KEY]["id"]) or {}).get("result") not in final]
    if not pending:
        return res
    try:
        positions = adapter.read_positions(page)
        journal = api.open_fills(cfg.account_id)
    except Exception as exc:  # noqa: BLE001
        res.alerts.append(f"close: venue/journal read failed ({type(exc).__name__}); {len(pending)} close request(s)"
                          " retried next tick")
        return res
    by_tid = {str(j.get("ticket_id")): j for j in journal if j.get("ticket_id")}
    for t in pending:
        tid, req = str(t.get("ticket_id")), dict(t[KEY])
        rid, frac = req["id"], _f(req.get("fraction"))
        outcome: Dict[str, Any] = {"ticket_id": tid, "fraction": frac, "at": datetime.now(timezone.utc).isoformat(),
                                   "review_id": req.get("review_id")}
        try:
            j = by_tid.get(tid)
            bot_sym = str((j or {}).get("symbol") or t.get("symbol") or "").upper()
            sym_cfg = cfg.symbols.get(bot_sym) or {}
            venue = str(sym_cfg.get("venue") or "").upper()
            side = pe._dir((j or {}).get("direction") or t.get("direction"))
            mine = [p for p in positions if venue and p.symbol.upper() == venue and p.side == side]
            prev = done.get(rid) or {}
            if j is None and frac is None and int(prev.get("attempts") or 0) > 0:
                outcome.update(result="closed", why="journal row closed since the last attempt (venue flat)")
            elif j is None:
                outcome.update(result="refused", why="no open journal row for the ticket (not filled, or closed)")
            elif frac is None and not mine and int(prev.get("attempts") or 0) > 0:
                outcome.update(result="closed", why="position gone since the last attempt (venue flat)")
            elif len(mine) != 1:
                outcome.update(result="refused", why=f"{len(mine)} {venue or bot_sym} {side} positions (need 1)")
            elif frac is None:
                pos = mine[0]
                if not live:
                    r = adapter.flatten(page, venue, arm=False, side=pos.side, quantity=pos.quantity,
                                        entry_price=pos.entry_price)
                    res.log("vm_close_dry", ticket_id=tid, close_id=rid, result=r)
                    continue   # read_only: the request stays pending
                ok, _unreal, why = pe._close_and_confirm(res, adapter, page, venue, pos.side, pos, reads, sleep, tid)
                n = int(prev.get("attempts") or 0) + 1
                outcome.update(result="closed" if ok else "retrying", why=why or "flat, no orphan order", attempts=n)
            else:
                pos = mine[0]
                step = _f(sym_cfg.get("lot_step"))
                qty = round_down(float(pos.quantity or 0) * frac, step)
                min_q = _f(sym_cfg.get("min_lots")) or step or 0.0
                rest = float(pos.quantity or 0) - qty
                if not getattr(adapter, "PARTIAL_CLOSE_SUPPORTED", False):
                    outcome.update(result="refused", why=f"{type(adapter).__name__} has no partial close")
                elif qty < min_q or rest < min_q:
                    outcome.update(result="refused", why=(f"partial {qty} of {pos.quantity} leaves a side below the "
                                                          f"venue minimum {min_q}"))
                else:
                    r = adapter.reduce_position(page, pos, qty, arm=live, client_id=rid)
                    res.log("vm_partial_close" if live else "vm_partial_close_dry", ticket_id=tid, close_id=rid,
                            qty=qty, result=r)
                    if not live:
                        continue
                    if not r.get("ok"):
                        outcome.update(result="apply_failed", why=f"reduce not accepted: {r.get('why')}")
                    else:
                        ok, why, after = confirm_partial(adapter, page, pos, qty, venue, step,
                                                         _f(sym_cfg.get("price_step")), reads, sleep)
                        outcome.update(result="reduced" if ok else "apply_failed", qty_closed=qty,
                                       why=why or "quantity reduced; SL and TP still resting", after=after)
        except Exception as exc:  # noqa: BLE001 -- one ticket's failure never stops the others
            outcome.update(result="apply_failed", why=f"{type(exc).__name__}: {str(exc)[:200]}")
        done[rid] = outcome
        res.log("vm_close", close_id=rid, **outcome)
        if outcome["result"] == "retrying":
            n = outcome["attempts"]
            if n == 1:
                res.alerts.append(f"{tid}: system close request {rid} not confirmed ({outcome['why']}); the position "
                                  "keeps its bracket and the close retries every tick")
            elif n == RED_FLAG_AFTER:
                res.alerts.append(f"RED FLAG {tid}: system close request {rid} failed {n} ticks in a row "
                                  f"({outcome['why']}); still retrying")
        elif outcome["result"] in ("closed", "reduced"):
            res.alerts.append(f"{tid}: system {'close' if frac is None else f'partial close ({frac:g})'} applied and "
                              f"read back ({outcome['why']}); request {rid}")
        else:
            res.alerts.append(f"{tid}: system close request {rid} NOT applied -- {outcome['result']}: "
                              f"{outcome.get('why')}")
    if live:
        try:
            _save_done(state_dir, done)
        except OSError as exc:
            res.alerts.append(f"close: done-state write failed ({type(exc).__name__}); a request may repeat")
    return res
