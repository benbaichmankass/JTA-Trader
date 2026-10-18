"""Development test trades on the phone-executed prop accounts (mandate ``MD-EXEC-DEV-TEST-TRADES``).

Operator grant, 2026-10-18 (first in the manager session ~08:05Z, then stated directly in the lane's session
~09:35Z: *"I grant MD-EXEC-DEV-TEST-TRADES: the phone drill may open and close minimum-size test trades on
breakout_2 / tradeify_1 / velotrade_1 under the bounds you proposed, including the final Confirm."*). The grant and
its bounds are recorded in ``config/mandates.yaml`` under ``mandates:`` (the entry the operator merges is the
record; this module READS it and refuses when it is absent -- field beats comment).

What a test trade is: ONE real, minimum-size position on a phone-executed prop account, opened by the rehearsal
drill so the WHOLE operation -- entry with a protective stop, stop/target amend through the position sheet
INCLUDING the final Confirm, read-back from the venue, close -- runs on demand instead of waiting hours for a live
trail amend. It is execution plumbing, not a strategy: ``strategy = "exec_test"``, ``meta.origin = "exec_test"``,
ticket ids ``exec-test-...``, and every performance / soak / survival reader drops it (:func:`is_exec_test`).

The bounds (manager-set defaults; the operator changes them in the mandate entry, never here):
  * only accounts the mandate names AND that are phone_accounts; only that account's declared instruments;
  * minimum tradable size (the instrument's ``min_qty``, else its ``qty_step``);
  * a protective SL on the ticket at entry (the phone's order form sets it with the entry);
  * closed within the same drill: ``max_hold_min`` (30) -> ``meta.exec_test.close_by``;
  * at most ``max_per_account_per_day`` (6) tickets that reached the venue per account per UTC day;
  * never when the account's day loss is past ``day_loss_fraction_max`` (0.5) of its daily-DD switch limit, and never
    when that loss cannot be read (a null is "could not look", never 0);
  * never while a strategy position (or a pending strategy ticket) is open on the SAME symbol on that account.
Every bound is re-checked when the phone CLAIMS the ticket (``phone_executor.claim_next``), not only when it is
written, so a ticket written minutes earlier never trades past a bound that moved.
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

MANDATE_ID = "MD-EXEC-DEV-TEST-TRADES"
ORIGIN = "exec_test"
STRATEGY = "exec_test"
TICKET_PREFIX = "exec-test-"
VALID_MINUTES = 10
DEFAULT_BOUNDS: Dict[str, Any] = {
    "accounts": ["breakout_2", "tradeify_1", "velotrade_1"], "max_hold_min": 30, "max_per_account_per_day": 6,
    "day_loss_fraction_max": 0.5, "sl_pct": 1.0, "tp_pct": 2.0, "limit_offset_pct": 0.2,
}
# ticket statuses that never reached the venue: they do not count against the daily cap
_NOT_SENT = ("refused", "expired", "skipped", "superseded")
# a strategy ticket in one of these states means that symbol is, or is about to be, a strategy position
_STRATEGY_LIVE_STATES = ("emitted", "claimed", "placed", "filled", "open")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _meta(x: Any) -> Dict[str, Any]:
    m = x.get("meta") if isinstance(x, Mapping) and "meta" in x else x
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            return {}
    return m if isinstance(m, dict) else {}


def is_exec_test(row: Any) -> bool:
    """True for a prop TICKET row / dict (or its meta) written by this module."""
    if not isinstance(row, Mapping):
        return False
    if str(row.get("strategy") or "") == STRATEGY or str(row.get("ticket_id") or "").startswith(TICKET_PREFIX):
        return True
    return _meta(row).get("origin") == ORIGIN


def is_exec_test_fill(fill: Any) -> bool:
    """True for a prop FILL row that belongs to a test trade: linked by ticket id, or stamped in ``raw.origin``."""
    if not isinstance(fill, Mapping):
        return False
    if str(fill.get("ticket_id") or "").startswith(TICKET_PREFIX):
        return True
    raw = fill.get("raw")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    return isinstance(raw, dict) and (raw.get("origin") == ORIGIN
                                      or str(raw.get("ticket_id") or "").startswith(TICKET_PREFIX))


def exclude_exec_test(rows: Iterable[Mapping[str, Any]], *, fills: bool = False) -> List[Dict[str, Any]]:
    """The rows without test trades: what strategy performance, soak grading and survival stats are measured over."""
    pred = is_exec_test_fill if fills else is_exec_test
    return [dict(r) for r in rows if not pred(r)]


def mandate(root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The GRANTED entry (``mandates:`` only; a ``proposed:`` entry grants nothing), or None."""
    import yaml
    from src.utils.paths import repo_root
    p = Path(root or repo_root()) / "config" / "mandates.yaml"
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    for m in (doc.get("mandates") or []) if isinstance(doc, dict) else []:
        if isinstance(m, dict) and m.get("id") == MANDATE_ID and m.get("granted_by") and m.get("granted_at"):
            return m
    return None


_BOUND_KEYS = {   # the entry's field names (as the manager recorded them, PR #18936) -> this module's
    "accounts": ("accounts",),
    "max_hold_min": ("max_hold_minutes", "max_hold_min"),
    "max_per_account_per_day": ("max_test_trades_per_account_per_utc_day", "max_per_account_per_day"),
    "day_loss_fraction_max": ("max_day_loss_fraction_of_daily_dd_switch_limit", "day_loss_fraction_max"),
    "sl_pct": ("sl_pct",), "tp_pct": ("tp_pct",), "limit_offset_pct": ("limit_offset_pct",),
}


def bounds(m: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The bounds as the mandate entry states them (field beats this module's defaults)."""
    b = dict(DEFAULT_BOUNDS)
    raw = (m or {}).get("bounds")
    if isinstance(raw, Mapping):
        for k, names in _BOUND_KEYS.items():
            for n in names:
                if raw.get(n) is not None:
                    b[k] = raw[n]
                    break
    return b


def _round_step(v: float, step: Optional[float], *, up: bool = False) -> float:
    if not step or step <= 0:
        return v
    n = round(v / step, 9)   # 2505 * 0.99 / 0.01 is 247994.9999…: snap the float before taking the floor
    return round((math.ceil(n) if up else math.floor(n)) * step, 10)


def count_today(account_id: str, now: Optional[datetime] = None) -> int:
    """Test tickets written today (UTC) for the account that reached, or may still reach, the venue."""
    from src.prop import prop_journal
    now = now or _now()
    day_start = now.strftime("%Y-%m-%dT00:00:00")
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        rows = conn.execute("SELECT status FROM prop_tickets WHERE account_id = ? AND strategy = ? "
                            "AND datetime(created_at) >= datetime(?)", (account_id, STRATEGY, day_start)).fetchall()
    finally:
        conn.close()
    return sum(1 for r in rows if str(r["status"] or "") not in _NOT_SENT)


def _strategy_position_on(account_id: str, symbol: str) -> Optional[str]:
    """The strategy ticket / open fill that makes ``symbol`` off-limits, as a short label; None when clear."""
    from src.prop import prop_journal
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        q = ",".join("?" * len(_STRATEGY_LIVE_STATES))
        for r in conn.execute("SELECT ticket_id, strategy, status, meta FROM prop_tickets WHERE account_id = ? AND symbol = ? "
                              f"AND status IN ({q})", (account_id, symbol, *_STRATEGY_LIVE_STATES)).fetchall():
            if not is_exec_test(dict(r)):
                return f"ticket {r['ticket_id']} ({r['strategy']}, {r['status']})"
        for r in conn.execute("SELECT id, ticket_id, raw FROM prop_fills WHERE account_id = ? AND symbol = ? AND status = 'open'",
                              (account_id, symbol)).fetchall():
            if not is_exec_test_fill(dict(r)):
                return f"open fill #{r['id']} ({r['ticket_id'] or 'unlinked'})"
    finally:
        conn.close()
    return None


def _day_loss(account_id: str, now: datetime) -> Dict[str, Any]:
    """``{loss_usd, limit_usd, fraction}`` off the account's daily-DD switch state; a None is "could not look"."""
    try:
        from src.prop import phone_executor as pe
        from src.units.accounts.daily_dd_switch import switch_for_account
        cfg = pe._account_block(account_id)
        st = switch_for_account(account_id, cfg).status()
        loss, limit = st.get("loss_usd"), st.get("limit_usd")
        frac = (float(loss) / float(limit)) if loss is not None and limit not in (None, 0) else None
        return {"loss_usd": loss, "limit_usd": limit, "fraction": frac, "day": st.get("day"), "tripped": st.get("tripped")}
    except Exception as exc:  # noqa: BLE001 — unreadable = could not look, which refuses below
        return {"loss_usd": None, "limit_usd": None, "fraction": None, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}


def check_bounds(account_id: str, symbol: str, *, now: Optional[datetime] = None, root: Optional[Path] = None,
                 skip_count_for: Optional[str] = None) -> Dict[str, Any]:
    """Every bound, every time. ``{"ok", "refusals": [...], "qty", "bounds", "count_today", "day_loss"}``.
    ``skip_count_for`` = a ticket id already counted (the claim-time re-check of a written ticket)."""
    from src.prop import phone_executor as pe
    now = now or _now()
    acct, sym = str(account_id or "").strip(), str(symbol or "").strip().upper()
    m = mandate(root)
    b = bounds(m)
    out: Dict[str, Any] = {"ok": False, "refusals": [], "qty": None, "bounds": b, "mandate": MANDATE_ID,
                           "count_today": None, "day_loss": None}
    if m is None:
        out["refusals"].append("mandate_not_granted: config/mandates.yaml carries no granted " + MANDATE_ID)
        return out
    if acct not in (b.get("accounts") or []):
        out["refusals"].append(f"account_not_in_mandate: {acct or '<empty>'}")
    if not pe.is_phone_account(acct):
        out["refusals"].append(f"not_a_phone_account: {acct or '<empty>'}")
    inst = (pe.phone_config(acct).get("instruments") or {}).get(sym) or {}
    if not inst:
        out["refusals"].append(f"symbol_not_declared: {sym or '<empty>'} is not in phone_accounts.{acct}.instruments")
    else:
        qty = inst.get("min_qty") or inst.get("qty_step")
        try:
            out["qty"] = float(qty) if qty and float(qty) > 0 else None
        except (TypeError, ValueError):
            out["qty"] = None
        if out["qty"] is None:
            out["refusals"].append(f"no_minimum_size: phone_accounts.{acct}.instruments.{sym} declares no min_qty / qty_step")
    if out["refusals"]:
        return out
    n = count_today(acct, now)
    if skip_count_for:
        n = max(n - 1, 0)
    out["count_today"] = n
    cap = int(b.get("max_per_account_per_day") or 0)
    if n >= cap:
        out["refusals"].append(f"daily_cap: {n} test tickets today already (cap {cap})")
    dl = _day_loss(acct, now)
    out["day_loss"] = dl
    frac_max = float(b.get("day_loss_fraction_max") or 0.5)
    if dl.get("fraction") is None:
        out["refusals"].append("day_loss_unreadable: the daily-DD switch has no readable loss/limit for today "
                               "(a null is not 0; never a test trade blind)")
    elif dl["fraction"] >= frac_max or dl.get("tripped"):
        out["refusals"].append(f"day_loss_past_bound: loss is {dl['fraction']:.0%} of the daily limit (bound {frac_max:.0%})"
                               + (" and the switch is tripped" if dl.get("tripped") else ""))
    pos = _strategy_position_on(acct, sym)
    if pos:
        out["refusals"].append(f"strategy_position_on_symbol: {pos}")
    out["ok"] = not out["refusals"]
    return out


def write_ticket(account_id: str, symbol: str, *, by: str, now: Optional[datetime] = None, root: Optional[Path] = None,
                 last: Optional[float] = None) -> Dict[str, Any]:
    """Write ONE test ticket (bounds checked). Long, marketable limit just above the last price so it fills at once,
    protective SL ``sl_pct`` below and a TP ``tp_pct`` above (test geometry, not a prediction: this is not a leg),
    minimum size, valid ``VALID_MINUTES``. Returns the verdict with ``ticket_id`` on success."""
    from src.prop import phone_executor as pe
    from src.prop import prop_journal
    now = now or _now()
    acct, sym = str(account_id or "").strip(), str(symbol or "").strip().upper()
    v = check_bounds(acct, sym, now=now, root=root)
    if not v["ok"]:
        return v
    inst = (pe.phone_config(acct).get("instruments") or {}).get(sym) or {}
    pstep = inst.get("price_step")
    ref = last if last is not None else pe._bybit_last(sym)
    if not ref or ref <= 0:
        v.update(ok=False, refusals=["no_reference_price"])
        return v
    b = v["bounds"]
    limit = _round_step(ref * (1 + float(b["limit_offset_pct"]) / 100), pstep, up=True)
    sl = _round_step(limit * (1 - float(b["sl_pct"]) / 100), pstep)
    tp = _round_step(limit * (1 + float(b["tp_pct"]) / 100), pstep, up=True)
    hold = int(b.get("max_hold_min") or 30)
    close_by = (now + timedelta(minutes=hold)).isoformat()
    tid = f"{TICKET_PREFIX}{uuid.uuid4().hex[:12]}"
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": acct, "strategy": STRATEGY, "symbol": sym, "direction": "long", "side": "buy",
        "entry": limit, "sl": sl, "tp": tp, "qty": v["qty"], "risk_usd": None, "signal_time": now.isoformat(),
        "valid_until": (now + timedelta(minutes=VALID_MINUTES)).isoformat(), "status": "emitted",
        "message": f"EXEC TEST TRADE ({MANDATE_ID}): minimum size, closed by the drill within {hold} min",
        "meta": {"origin": ORIGIN, "exec_test": {"mandate": MANDATE_ID, "by": str(by or "")[:80], "requested_at": now.isoformat(),
                                                 "max_hold_min": hold, "close_by": close_by, "reference_price": ref}},
    })
    logger.info("exec_test_trades: %s wrote %s for %s/%s qty=%s limit=%s sl=%s", by, tid, acct, sym, v["qty"], limit, sl)
    return {**v, "ticket_id": tid, "entry": limit, "sl": sl, "tp": tp, "close_by": close_by}


def overdue(account_id: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Test tickets that reached the venue and are past ``close_by`` without a closed fill: the drill did not close them.
    The caller alerts ONCE per ticket (``meta.exec_test.overdue_alerted``) -- never a halt, never an auto-close here."""
    from src.prop import prop_journal
    now = now or _now()
    conn = prop_journal._connect()
    try:
        prop_journal.ensure_tables(conn)
        rows = [prop_journal._ticket_row(r) for r in conn.execute(
            "SELECT * FROM prop_tickets WHERE account_id = ? AND strategy = ? AND status IN ('placed', 'filled', 'open')",
            (account_id, STRATEGY)).fetchall()]
        out = []
        for t in rows:
            cb = ((t.get("meta") or {}).get("exec_test") or {}).get("close_by")
            try:
                due = datetime.fromisoformat(str(cb).replace("Z", "+00:00")) if cb else None
            except ValueError:
                due = None
            if due is None or due > now:
                continue
            closed = conn.execute("SELECT 1 FROM prop_fills WHERE ticket_id = ? AND status = 'closed' LIMIT 1",
                                  (t["ticket_id"],)).fetchone()
            if not closed:
                out.append(t)
        return out
    finally:
        conn.close()


__all__ = ["MANDATE_ID", "ORIGIN", "STRATEGY", "TICKET_PREFIX", "is_exec_test", "is_exec_test_fill", "exclude_exec_test",
           "mandate", "bounds", "check_bounds", "write_ticket", "count_today", "overdue"]
