"""The REHEARSAL DRILL for the phone executor (PHONE-EXEC-OBSERVABLE-1018, piece 2; operator decision 2026-10-18).

What a drill is. A server-issued command that makes the phone run the FULL stop-amend flow on a real open
position -- Positions tab, row target and native touch, the sheet, [Position details], [n TP / n SL], the Stop row,
its pencil, the "Edit Stop loss" modal, ONLY the Trigger typed and read back -- up to the final Confirm, then CANCEL
the modal, re-read the stop unchanged and close the sheet. The app reports pass/fail PER STEP with a capture of
each step (``src.prop.phone_captures``). No order ever changes: the app never calls Confirm in a drill, the
denylist refuses every close / cancel-order control, and nothing is journaled as an amend.

Why it exists. Four APKs guessed one click each over three days; the operator's "done when" is *the drill passes
3 times in a row on the operator's phone, then the live amend runs on the same logic*. So the pass streak is also
THE GATE for the live pencil + Confirm: :func:`sheet_edit` answers True once :data:`PASSES_TO_ARM` consecutive drills
passed (or the operator pinned ``phone_accounts.<acct>.sheet_edit: true|false`` in ``config/prop_platforms.yaml``,
which wins either way). The claim config carries it to the app on every ticket; a failed drill after arming
drops the streak and the gate closes again until three more passes (the live amend then refuses before any click,
as it does today, and the refusal alert names the stop to set by hand).

State lives beside the other phone diag files (``<trade_journal.db dir>/phone_drill/<acct>/``): ``request.json``
(the ONE outstanding drill: requested -> claimed; removed on result or timeout) and ``history.jsonl`` (append-only
results, newest last). Requested by the ``phone-drill`` system-action (Tier 1: a file write, no order change) or
:func:`request_drill`; served on ``GET /phone/pending`` (``drill``), claimed atomically on ``POST /phone/drill/claim``,
reported on ``POST /phone/drill/result``; read on ``GET /api/diag/phone_drill``. One Telegram line per result.

A drill WITH A TEST TRADE (operator grant ``MD-EXEC-DEV-TEST-TRADES``, 2026-10-18; ``src.prop.exec_test_trades``).
``request_drill(..., test_trade="ETHUSDT")`` (system-action ``phone-drill`` with ``symbol:``) asks for the WHOLE
operation on a real, minimum-size position of our own: at CLAIM the server writes ONE exec-test ticket (every bound
checked then, and again when the phone claims the ticket), the app places it with its protective stop, runs the
stop-amend flow INCLUDING the final Confirm, reads the new stop back, CLOSES the position and reports; the server
journals the close as a fill linked to the ticket. A position the app reports open, or a claimed test drill that
never reports, is ONE alert naming the ticket -- the operator closes it by hand; nothing halts. Confirm and the
close are allowed to the app ONLY on the drill's own test ticket (``test_trade.confirm``), never on a strategy
position; a drill without a test trade keeps its no-Confirm, no-close contract above.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PASSES_TO_ARM = 3            # the operator's "done when": 3 consecutive passes arm the live pencil + Confirm
CLAIM_TIMEOUT_S = 10 * 60    # a claimed drill with no result: that attempt failed (unreported), the request clears
REQUEST_TTL_S = 24 * 3600    # an unclaimed request older than this expires (the phone was not around)
HISTORY_MAX = 200
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
STEP_RESULTS = ("pass", "fail", "unreported")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _dir(account_id: str) -> Path:
    from src.prop import prop_journal
    acct = re.sub(r"[^a-z0-9_]", "", str(account_id or ""))
    if not acct:
        raise ValueError("account_id invalid")
    return Path(prop_journal._db_path()).parent / "phone_drill" / acct


def _request_path(account_id: str) -> Path:
    return _dir(account_id) / "request.json"


def _history_path(account_id: str) -> Path:
    return _dir(account_id) / "history.jsonl"


def _scrub(s: Any, n: int = 160) -> str:
    s = re.sub(r"[^A-Za-z0-9 _.:/()=+&%#,;<>\[\]-]", "", str(s or ""))[:n]
    return re.sub(r"https?\S*|\S+@\S+|\d{6,}", "*", s)


def _read_request(account_id: str) -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(_request_path(account_id).read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write_request(account_id: str, req: Optional[Dict[str, Any]]) -> None:
    p = _request_path(account_id)
    if req is None:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(req))
    tmp.replace(p)


def _append_history(account_id: str, row: Dict[str, Any]) -> None:
    p = _history_path(account_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = history(account_id, limit=HISTORY_MAX - 1)
    rows.append(row)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows[-HISTORY_MAX:]))
    tmp.replace(p)


def history(account_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Results, oldest first (the last ``limit``)."""
    try:
        lines = _history_path(account_id).read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out[-max(1, int(limit)):]


def consecutive_passes(account_id: str) -> int:
    """Passes at the END of the history (a fail or an unreported drill resets the streak)."""
    n = 0
    for r in reversed(history(account_id, limit=HISTORY_MAX)):
        if r.get("result") == "pass":
            n += 1
        else:
            break
    return n


def sheet_edit(account_id: str) -> Dict[str, Any]:
    """The live pencil + Confirm gate the claim config carries to the app. ``{"enabled", "source", "passes"}``:
    an explicit ``phone_accounts.<acct>.sheet_edit`` (true/false) in ``config/prop_platforms.yaml`` wins; else
    ``auto`` = at least :data:`PASSES_TO_ARM` consecutive drill passes."""
    from src.prop.phone_executor import phone_config
    cfg = phone_config(account_id)
    passes = consecutive_passes(account_id)
    pin = cfg.get("sheet_edit")
    if isinstance(pin, bool):
        return {"enabled": pin, "source": "config", "passes": passes}
    return {"enabled": passes >= PASSES_TO_ARM, "source": "drills", "passes": passes, "needed": PASSES_TO_ARM}


def expire(account_id: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Watchdog: a claimed drill past :data:`CLAIM_TIMEOUT_S` with no result is recorded ``unreported`` (the streak
    resets); an unclaimed request past :data:`REQUEST_TTL_S` is dropped. Returns the history row written, if any."""
    now = now or _now()
    req = _read_request(account_id)
    if not req:
        return None
    if req.get("status") == "claimed":
        at = _parse(req.get("claimed_at"))
        if at and (now - at).total_seconds() > CLAIM_TIMEOUT_S:
            row = {"id": req.get("id"), "result": "unreported", "at": now.isoformat(), "requested_by": req.get("by"),
                   "claimed_at": req.get("claimed_at"), "why": "claimed and never reported (app died or the page hung)"}
            tt = req.get("test_trade") if isinstance(req.get("test_trade"), dict) else None
            if tt and tt.get("ticket_id"):
                # the test position may be open with nobody reporting it: ONE alert, the operator checks; no halt.
                # A ticket still emitted (never claimed) is expired so the normal poll never opens it later.
                try:
                    from src.prop import prop_journal
                    t = prop_journal.get_ticket(tt["ticket_id"]) or {}
                    _retire_unplaced(tt["ticket_id"], str(t.get("status") or ""))
                except Exception:  # noqa: BLE001  # allow-silent: logged in _retire_unplaced / validity expires it
                    pass
                row["test_trade"] = {**tt, "state": "unreported"}
                _send(f"📱 drill {account_id}: ⚠️ {req.get('id')} claimed with test ticket {tt['ticket_id']} and never reported. "
                      f"CHECK the terminal and close {tt.get('symbol')} long {tt.get('qty')} by hand if it is open "
                      f"(close_by {tt.get('close_by')}).", None)
            _append_history(account_id, row)
            _write_request(account_id, None)
            return row
        return None
    at = _parse(req.get("requested_at"))
    if at and (now - at).total_seconds() > REQUEST_TTL_S:
        _write_request(account_id, None)
    return None


def request_drill(account_id: str, *, by: str = "manual", note: str = "", now: Optional[datetime] = None,
                  test_trade: Optional[str] = None) -> Dict[str, Any]:
    """Ask for ONE drill. Idempotent while one is outstanding (the existing request is returned). ``test_trade`` =
    a symbol: the drill opens, amends (with Confirm) and closes a minimum-size test position of our own; every bound
    of MD-EXEC-DEV-TEST-TRADES is checked here (a refusal writes nothing) and again when the ticket is written at
    claim and when the phone claims the ticket."""
    from src.prop.phone_executor import is_phone_account
    now = now or _now()
    if not is_phone_account(account_id):
        raise ValueError(f"{account_id or '<empty>'} is not a phone_accounts entry in config/prop_platforms.yaml")
    expire(account_id, now=now)
    cur = _read_request(account_id)
    if cur:
        return {"ok": True, "existing": True, "drill": cur}
    req = {"id": f"drill-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}", "status": "requested",
           "requested_at": now.isoformat(), "by": _scrub(by, 80), "note": _scrub(note, 160)}
    if test_trade:
        from src.prop import exec_test_trades
        sym = str(test_trade).strip().upper()
        v = exec_test_trades.check_bounds(account_id, sym, now=now)
        if not v["ok"]:
            raise ValueError("test trade refused: " + "; ".join(v["refusals"]))
        req["test_trade"] = {"symbol": sym, "qty": v["qty"]}
    _write_request(account_id, req)
    logger.info("phone_drill: requested %s for %s by %s", req["id"], account_id, req["by"])
    return {"ok": True, "existing": False, "drill": req}


def pending(account_id: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """What ``GET /phone/pending`` tells the app: ``{"id": ...}`` for an unclaimed request, else None."""
    now = now or _now()
    expire(account_id, now=now)
    req = _read_request(account_id)
    if req and req.get("status") == "requested":
        return {"id": req["id"], "requested_at": req.get("requested_at")}
    return None


def _position_context(account_id: str) -> Dict[str, Any]:
    """The open position the server expects the drill to find, from the newest placed/filled phone ticket and its
    trail state (symbol, venue symbol, direction, qty, the resting stop the server believes, the price step). Empty
    when the journal holds none: the app then rehearses the one position the sheet shows."""
    from src.prop import phone_trail, prop_journal
    from src.prop.phone_executor import phone_config, venue_symbol
    out: Dict[str, Any] = {}
    try:
        rows = [t for st in ("placed", "filled") for t in prop_journal.list_tickets(account_id=account_id, status=st, limit=20)]
    except Exception:  # noqa: BLE001  # allow-silent: no context is a legal drill (the sheet decides)
        logger.warning("phone_drill: position context read failed", exc_info=True)
        return out
    rows = [t for t in rows if not (t.get("meta") or {}).get("test")]
    if not rows:
        return out
    rows.sort(key=lambda t: str(t.get("created_at") or ""))
    t = rows[-1]
    sym = str(t.get("symbol") or "").upper()
    inst = (phone_config(account_id).get("instruments") or {}).get(sym) or {}
    m = t.get("meta") if isinstance(t.get("meta"), dict) else {}
    tr = (m.get(phone_trail.KEY) or {}) if isinstance(m, dict) else {}
    step = inst.get("price_step")
    sl, _tp = phone_trail._levels(t, tr, phone_trail._f(step))
    out = {"ticket_id": t.get("ticket_id"), "symbol": sym, "venue_symbol": venue_symbol(account_id, sym),
           "direction": t.get("direction"), "qty": t.get("qty"), "resting_sl": sl, "price_step": step}
    return {k: v for k, v in out.items() if v is not None}


def claim(device: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """``POST /phone/drill/claim``: the outstanding request becomes claimed by this device (one attempt per request;
    a second claim answers ``drill: null``)."""
    now = now or _now()
    acct = device.account_id
    expire(acct, now=now)
    req = _read_request(acct)
    if not req or req.get("status") != "requested":
        return {"ok": True, "drill": None}
    tt = req.get("test_trade") if isinstance(req.get("test_trade"), dict) else None
    if tt and not tt.get("ticket_id"):
        # MD-EXEC-DEV-TEST-TRADES: the test ticket is written NOW, bounds re-checked; a refusal is a failed drill
        from src.prop import exec_test_trades
        try:
            v = exec_test_trades.write_ticket(acct, str(tt.get("symbol") or ""), by=f"drill {req['id']}", now=now)
        except Exception as exc:  # noqa: BLE001 — a writer fault is a refusal, never an unserved claim
            v = {"ok": False, "refusals": [f"{type(exc).__name__}: {str(exc)[:80]}"]}
        if not v.get("ok"):
            why = _scrub("; ".join(v.get("refusals") or []), 160)
            row = {"id": req["id"], "result": "fail", "at": now.isoformat(), "requested_by": req.get("by"),
                   "device_id": device.device_id, "run_id": None, "captures": None,
                   "steps": [{"step": "test_trade_bounds", "ok": False, "why": why}], "failed_steps": ["test_trade_bounds"],
                   "test_trade": {"symbol": tt.get("symbol"), "ticket_id": None, "state": "refused"}}
            _append_history(acct, row)
            _write_request(acct, None)
            _send(f"📱 drill {acct}: FAIL ❌ {req['id']} — test trade refused before any ticket: {why}", None)
            logger.warning("phone_drill: %s test trade refused: %s", req["id"], why)
            return {"ok": True, "drill": None, "refused": v.get("refusals")}
        tt.update(ticket_id=v["ticket_id"], entry=v["entry"], sl=v["sl"], tp=v["tp"], qty=v["qty"], close_by=v["close_by"])
        req["test_trade"] = tt
    req.update(status="claimed", claimed_at=now.isoformat(), device_id=device.device_id)
    _write_request(acct, req)
    if tt:
        from src.prop.phone_executor import phone_config, venue_symbol
        sym = str(tt.get("symbol") or "")
        inst = (phone_config(acct).get("instruments") or {}).get(sym) or {}
        ctx = {"ticket_id": tt.get("ticket_id"), "symbol": sym, "venue_symbol": venue_symbol(acct, sym), "direction": "long",
               "qty": tt.get("qty"), "resting_sl": tt.get("sl"), "price_step": inst.get("price_step"),
               "test_trade": {**tt, "venue_symbol": venue_symbol(acct, sym), "direction": "long",
                              "price_step": inst.get("price_step"), "confirm": True}}
        ctx = {k: v for k, v in ctx.items() if v is not None}
    else:
        ctx = _position_context(acct)
    logger.info("phone_drill: %s claimed by %s (%s)%s", req["id"], device.device_id, acct,
                f" test trade {tt.get('ticket_id')}" if tt else "")
    return {"ok": True, "drill": {"id": req["id"], "requested_at": req.get("requested_at"), "note": req.get("note"), **ctx}}


def _capture_link(account_id: str, run_id: str) -> str:
    from src.prop.phone_captures import capture_link
    return capture_link(account_id, run_id)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _send(msg: str, send: Any) -> None:
    try:
        if send is None:
            from src.runtime.notify import send_telegram_direct
            send = send_telegram_direct
        send(msg, parse_mode=None)
    except Exception:  # noqa: BLE001  # allow-silent: logged; the record is written either way
        logger.warning("phone_drill: ping failed", exc_info=True)


def _test_trade_outcome(account_id: str, tt_req: Dict[str, Any], tt_in: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """What became of the drill's test trade, from the app's report: ``closed`` journals the close as a fill linked to
    the ticket (``prop_report.ingest_report``); a placed position the app could not close is ``OPEN_UNCLOSED`` (the
    caller alerts; the operator closes it by hand); nothing placed is ``not_placed`` with the ticket's own status."""
    from src.prop import prop_journal
    tid = str(tt_req.get("ticket_id") or "")
    out: Dict[str, Any] = {"ticket_id": tid or None, "symbol": tt_req.get("symbol"), "placed": tt_in.get("placed") is True,
                           "closed": tt_in.get("closed") is True, "amended_sl": _f(tt_in.get("amended_sl")),
                           "exit_price": _f(tt_in.get("exit_price")), "state": "not_written"}
    if not tid:
        return out
    if str(tt_in.get("ticket_id") or "") not in ("", tid):
        out["state"] = "ticket_mismatch"
        return out
    t = prop_journal.get_ticket(tid) or {}
    st = str(t.get("status") or "")
    if out["closed"]:
        try:
            from src.prop.prop_report import ingest_report
            ingest_report({"kind": "fill", "account_id": account_id, "ticket_id": tid, "symbol": tt_req.get("symbol"),
                           "direction": "long", "qty": tt_req.get("qty"),
                           "entry_price": _f(tt_in.get("entry_price")) or tt_req.get("entry"), "exit_price": out["exit_price"],
                           "sl": out["amended_sl"] or tt_req.get("sl"), "tp": tt_req.get("tp"), "status": "closed",
                           "closed_at": now.isoformat(), "reason": "exec_test drill close (MD-EXEC-DEV-TEST-TRADES)",
                           "source": "phone_drill", "origin": "exec_test"})
            out["state"] = "closed"
        except Exception as exc:  # noqa: BLE001 — the close happened on the venue; say the journal missed it
            logger.warning("phone_drill: test trade close not journaled: %s", exc)
            out["state"] = f"closed_unjournaled: {type(exc).__name__}"
    elif out["placed"] or st in ("placed", "filled", "open"):
        out["state"] = "OPEN_UNCLOSED"
    else:
        out["state"] = f"not_placed ({st or 'no ticket'})"
        _retire_unplaced(tid, st)
    return out


def _retire_unplaced(ticket_id: str, status: str) -> None:
    """A test ticket the drill never placed must not be picked up later by the normal entry poll (it would open a
    position nobody closes): an ``emitted`` one is expired now. ``refused`` / ``expired`` / ``skipped`` stay as they are."""
    if status != "emitted":
        return
    try:
        from src.prop import prop_journal
        prop_journal.set_ticket_status(ticket_id, "expired")
    except Exception:  # noqa: BLE001  # allow-silent: logged; the 10-min validity expires it anyway
        logger.warning("phone_drill: could not expire unplaced test ticket %s", ticket_id, exc_info=True)


def record_result(device: Any, body: Dict[str, Any], *, now: Optional[datetime] = None, send=None) -> Dict[str, Any]:
    """``POST /phone/drill/result``: the app's per-step report for the claimed drill. Appends to the history, clears
    the request, pings ONE Telegram line (pass/fail, failed steps, the capture link, the gate's new state)."""
    now = now or _now()
    acct = device.account_id
    did = str(body.get("drill_id") or "")
    if not _ID_RE.match(did):
        raise ValueError("drill_id invalid")
    req = _read_request(acct)
    if not req or req.get("id") != did or req.get("status") != "claimed":
        return {"ok": False, "why": "drill is not the claimed one"}
    if str(req.get("device_id") or "") != str(device.device_id):
        return {"ok": False, "why": "drill was claimed by another device"}
    passed = body.get("pass") is True
    steps_in = body.get("steps") if isinstance(body.get("steps"), list) else []
    steps = []
    for s in steps_in[:60]:
        if not isinstance(s, dict):
            continue
        ok = s.get("ok")
        steps.append({"step": re.sub(r"[^a-z0-9_]", "", str(s.get("step") or ""))[:40], "ok": ok if isinstance(ok, bool) else None,
                      "why": _scrub(s.get("why"), 160)})
    run_id = str(body.get("run_id") or "")
    run_id = run_id if _ID_RE.match(run_id) else ""
    row = {"id": did, "result": "pass" if passed else "fail", "at": now.isoformat(), "requested_by": req.get("by"),
           "claimed_at": req.get("claimed_at"), "device_id": device.device_id, "run_id": run_id or None,
           "captures": int(body.get("captures") or 0) if isinstance(body.get("captures"), int) else None,
           "app_version": _scrub(body.get("app_version"), 24), "exec_js": _scrub(body.get("exec_js"), 24),
           "steps": steps, "failed_steps": [s["step"] for s in steps if s["ok"] is False]}
    tt_req = req.get("test_trade") if isinstance(req.get("test_trade"), dict) else None
    tt_line = ""
    if tt_req:
        tt_in = body.get("test_trade") if isinstance(body.get("test_trade"), dict) else {}
        row["test_trade"] = _test_trade_outcome(acct, tt_req, tt_in, now)
        state = row["test_trade"]["state"]
        tt_line = f" Test trade {row['test_trade']['ticket_id'] or '(none)'}: {state}."
        if state == "OPEN_UNCLOSED":
            tt_line += (f" ⚠️ CLOSE IT BY HAND on the terminal: {tt_req.get('symbol')} long {tt_req.get('qty')}"
                        f" (close_by {tt_req.get('close_by')}).")
    _append_history(acct, row)
    _write_request(acct, None)
    gate = sheet_edit(acct)
    link = _capture_link(acct, run_id)
    msg = (f"📱 drill {acct}: {'PASS ✅' if passed else 'FAIL ❌'} {did} — {len(steps)} steps"
           + (f", failed: {', '.join(row['failed_steps'])[:120]}" if row["failed_steps"] else "")
           + f". Consecutive passes {gate['passes']}"
           + (f"/{gate.get('needed')}" if gate.get("source") == "drills" else "")
           + f"; live sheet edit {'ARMED' if gate['enabled'] else 'off'} ({gate['source']})."
           + tt_line
           + (f" Captures: {link}" if link else ""))
    _send(msg, send)
    logger.info("phone_drill: %s %s for %s (passes %s)", did, row["result"], acct, gate["passes"])
    return {"ok": True, "result": row["result"], "passes": gate["passes"], "sheet_edit": gate,
            **({"test_trade": row["test_trade"]} if tt_req else {})}


def status(account_id: str, limit: int = 20) -> Dict[str, Any]:
    """The read surface (``GET /api/diag/phone_drill``): pending request, the gate, recent results newest first."""
    expire(account_id)
    hist = history(account_id, limit=limit)
    try:
        from src.prop import exec_test_trades
        overdue = [t["ticket_id"] for t in exec_test_trades.overdue(account_id)]
    except Exception:  # noqa: BLE001  # allow-silent: a read surface; the list is best effort and says so (null)
        overdue = None
    return {"account_id": account_id, "pending": _read_request(account_id), "sheet_edit": sheet_edit(account_id),
            "passes_to_arm": PASSES_TO_ARM, "results": list(reversed(hist)), "present": bool(hist) or _read_request(account_id) is not None,
            "test_trades_overdue": overdue}


def main(argv: Optional[list] = None) -> int:
    """CLI (the ``phone-drill`` system-action): ``--request --account <acct> [--source who] [--note text]``."""
    import argparse
    ap = argparse.ArgumentParser(description="request one phone rehearsal drill")
    ap.add_argument("--request", action="store_true")
    ap.add_argument("--account", required=True)
    ap.add_argument("--source", default="phone-drill")
    ap.add_argument("--note", default="")
    ap.add_argument("--test-trade", default="", metavar="SYMBOL",
                    help="open, amend (Confirm) and close a minimum-size test position on this symbol (MD-EXEC-DEV-TEST-TRADES)")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    if a.status:
        print(json.dumps(status(a.account)))
        return 0
    if a.request:
        try:
            print(json.dumps(request_drill(a.account, by=a.source, note=a.note, test_trade=a.test_trade or None)))
            return 0
        except ValueError as exc:
            print(json.dumps({"ok": False, "refused": str(exc)}))
            return 1
    ap.print_help()
    return 2


__all__ = ["request_drill", "pending", "claim", "record_result", "status", "sheet_edit", "consecutive_passes",
           "history", "expire", "PASSES_TO_ARM", "CLAIM_TIMEOUT_S"]
