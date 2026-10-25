"""Tighten the stop (and optionally move the target) of ONE open Alpaca trade,
with a venue read-back (AMEND-PARITY-ALL-ACCOUNTS).

Why this exists
---------------
Operator directive 2026-10-25: every live account must be able to update an
open position's SL/TP in real time, through the same per-account interface.
``AlpacaClient.modify_protective`` (the monitor trail's seam, via
``execute.modify_open_order``) PATCHes the resting legs, but it does not read
them back, does not refuse a looser stop, and cannot tell a partially filled
bracket from a filled one. Alpaca has a documented history of 2xx-accepting an
operation that never took effect: the alpaca_paper GLD OCO wedge
(``PI-20261002-APBY4NTV-0001``), where cancels were accepted and the stop sat
"held" ~$34 through the market. So an amend on a real-money Alpaca book is
only ``applied`` when the venue reads the new level back.

This module is the Alpaca executor the live-trade-review apply path
(``scripts/ops/live_review_apply.py``, LTR-6R, PR #20139) hands an approved
level to, in place of its ``no_amend_path`` refusal. Its result vocabulary is
that path's: ``applied`` / ``apply_failed`` / ``could_not_look`` /
``refused``, plus ``planned`` for a read-only dry run. Never collapsed:

* ``could_not_look`` — a read failed (orders, position, mark) or a leg is
  mid-replace. NOTHING was sent; retry next cycle.
* ``refused`` — we looked and will not send: no position, no stop leg of this
  trade's size, ambiguous legs, a partially filled bracket, a stop already
  through the market (the GLD wedge shape), a looser stop, or a stop that
  would trigger at once. The resting protection is unchanged.
* ``apply_failed`` — a PATCH was sent and the read-back does not show the
  level (or the read-back itself failed). The operator must hear about it.
* ``applied`` — sent, and the venue reads the new level on a resting leg.

What it never does: place an order, cancel an order, close a position, widen a
stop, or touch a leg that is not this trade's own (legs are scoped by the
trade's share count, exactly as ``modify_protective`` scopes them, and two
legs of the same size refuse rather than guess, because Alpaca leg ids are not
captured at entry).

Bracket / OCO semantics this relies on (Alpaca Trading API v2):

* the stop of a bracket or OCO rests as ``held`` (waiting on its OCO partner)
  and is returned only nested under its parent — ``_open_orders_for_symbol``
  already reads both the open and the filled parents' legs;
* ``PATCH /v2/orders/{id}`` REPLACES the order: the response is a NEW order
  (new ``id``, ``replaces`` = old id) and the old one goes ``replaced``. The
  read-back therefore looks for the returned id, and falls back to "a stop
  leg of this trade's size resting at the new level" when the response
  carries no id;
* a parent still ``partially_filled`` has legs sized to the ORDER, not to the
  shares held. Patching them is refused until the parent completes.

CLI (read-only, there is no ``--apply``)::

    python3 -m src.units.accounts.alpaca_amend --account alpaca_live
    python3 -m src.units.accounts.alpaca_amend --account alpaca_live \\
        --trade-id 123 --new-sl 101.25

It prints, for every open journal trade on the account, the OCO leg ids it
identified, the resting stop/target, and what a tighten WOULD send. It needs
the account's Alpaca keys, so it runs on the live VM.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

X_APPLIED = "applied"
X_APPLY_FAILED = "apply_failed"
X_COULD_NOT_LOOK = "could_not_look"
X_REFUSED = "refused"
X_PLANNED = "planned"
RESULTS = (X_APPLIED, X_APPLY_FAILED, X_COULD_NOT_LOOK, X_REFUSED, X_PLANNED)

#: Leg statuses that mean "a change is already in flight". Patching on top of
#: one races the venue, so it is could-not-look and retried next cycle.
_IN_FLIGHT = frozenset({"pending_replace", "pending_cancel", "pending_new"})

#: Read-back tolerance: Alpaca prices equities >= $1 to the cent.
_PRICE_TOL = 0.005
_QTY_EPS = 1e-9


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def round_tighter(direction: str, level: float) -> float:
    """Round *level* to Alpaca's price grid in the TIGHTENING direction.

    Cents at or above $1, four decimals below (Alpaca's sub-penny rule).
    A long's stop rounds UP and a short's DOWN, so rounding can never make the
    sent stop looser than the level the risk manager approved.
    """
    scale = 100 if level >= 1.0 else 10000
    raw = level * scale
    snapped = math.ceil(raw - 1e-6) if direction == "long" else math.floor(raw + 1e-6)
    return snapped / scale


def is_tighter(direction: str, new_sl: float, current: float) -> bool:
    return new_sl > current + 1e-9 if direction == "long" else new_sl < current - 1e-9


def through_market(direction: str, stop: float, mark: float) -> bool:
    """A long's stop at/above the mark (a short's at/below) should already
    have triggered. A resting stop in that state is the GLD wedge shape."""
    return stop >= mark if direction == "long" else stop <= mark


def _side(order: Dict[str, Any]) -> str:
    """``stop`` / ``target`` / ``""``, STOP FAMILY FIRST (a stop-limit's type
    contains "limit") — the same rule ``AlpacaClient._leg_protective_side``
    and ``protection_state`` follow."""
    otype = str(order.get("type") or order.get("order_type") or "").lower()
    if "stop" in otype or "trail" in otype:
        return "stop"
    if "limit" in otype:
        return "target"
    return ""


def _reducing_side(direction: str) -> str:
    return "sell" if direction == "long" else "buy"


def _partial_parent_leg_ids(client: Any, symbol: str) -> Optional[set]:
    """Ids of legs whose parent is still ``partially_filled``, or ``None`` when
    the open-orders read fails (could not look, never "none")."""
    env = client._request("GET", f"/v2/orders?status=open&nested=true&symbols={symbol}")
    if env.get("retCode") != 0:
        return None
    out: set = set()
    for parent in env.get("result") or []:
        if not isinstance(parent, dict):
            continue
        if str(parent.get("status") or "").lower() != "partially_filled":
            continue
        for leg in parent.get("legs") or []:
            if isinstance(leg, dict) and leg.get("id"):
                out.add(str(leg["id"]))
    return out


def read_trade_legs(client: Any, *, symbol: str, direction: str,
                    qty: float) -> Dict[str, Any]:
    """The venue's view of ONE trade's protection: its stop leg and target leg
    (scoped by share count), the position and the mark. ``read_state`` is
    ``resolved`` or ``read_failed``; a resolved read may still carry a
    ``refuse`` reason (we looked and the shape is unsafe to patch)."""
    sym = str(symbol).upper()
    out: Dict[str, Any] = {"read_state": "read_failed", "symbol": sym,
                           "direction": direction, "qty": qty,
                           "stop_leg": None, "target_leg": None,
                           "venue_sl": None, "venue_tp": None,
                           "mark": None, "position_qty": None, "refuse": None}
    pos = client.position_quote(sym)
    if pos.get("state") == "could_not_look":
        out["detail"] = "position read failed"
        return out
    legs = client._open_orders_for_symbol(sym)
    if legs is None:
        out["detail"] = "open orders read failed"
        return out
    partial = _partial_parent_leg_ids(client, sym)
    if partial is None:
        out["detail"] = "open parents read failed"
        return out
    out["read_state"] = "resolved"
    out["mark"] = pos.get("current_price")
    out["position_qty"] = pos.get("qty")
    if pos.get("state") == "flat":
        out["refuse"] = "no_position"
        return out
    if pos.get("side") != direction:
        out["refuse"] = f"position_side_{pos.get('side')}_not_{direction}"
        return out
    if (pos.get("qty") or 0.0) + _QTY_EPS < qty:
        out["refuse"] = f"position_qty_{pos.get('qty')}_below_trade_qty_{qty}"
        return out

    reducing = _reducing_side(direction)
    mine: Dict[str, List[Dict[str, Any]]] = {"stop": [], "target": []}
    for o in legs:
        if not isinstance(o, dict) or not o.get("id"):
            continue
        kind = _side(o)
        if not kind:
            continue
        if str(o.get("side") or "").lower() not in ("", reducing):
            continue  # an opening order on the same symbol is not protection
        lq = _f(o.get("qty"))
        if lq is None or lq <= 0 or abs(lq - qty) > _QTY_EPS:
            continue
        mine[kind].append(o)
    if len(mine["stop"]) > 1 or len(mine["target"]) > 1:
        out["refuse"] = (f"ambiguous_legs: {len(mine['stop'])} stop / "
                         f"{len(mine['target'])} target leg(s) of qty={qty}")
        return out
    stop = mine["stop"][0] if mine["stop"] else None
    target = mine["target"][0] if mine["target"] else None
    out["stop_leg"] = _leg_view(stop)
    out["target_leg"] = _leg_view(target)
    out["venue_sl"] = out["stop_leg"]["price"] if stop else None
    out["venue_tp"] = out["target_leg"]["price"] if target else None
    for leg in (stop, target):
        if leg is None:
            continue
        if str(leg.get("status") or "").lower() in _IN_FLIGHT:
            out["read_state"] = "read_failed"
            out["detail"] = f"leg {leg['id']} is {leg.get('status')} (change in flight)"
            return out
        if str(leg["id"]) in partial:
            out["refuse"] = f"parent_partially_filled (leg {leg['id']})"
            return out
    return out


def _leg_view(o: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if o is None:
        return None
    price = _f(o.get("stop_price")) if _side(o) == "stop" else _f(o.get("limit_price"))
    if _side(o) == "stop" and price is None:
        price = _f(o.get("limit_price"))
    return {"id": str(o["id"]), "status": o.get("status"),
            "type": o.get("type") or o.get("order_type"),
            "qty": _f(o.get("qty")), "price": price}


def _patch(client: Any, leg_id: str, field: str, price: float) -> Dict[str, Any]:
    wire = f"{price:.2f}" if price >= 1.0 else f"{price:.4f}"
    env = client._request("PATCH", f"/v2/orders/{leg_id}", {field: wire})
    res = env.get("result") if isinstance(env.get("result"), dict) else {}
    return {"ok": env.get("retCode") == 0, "retCode": env.get("retCode"),
            "retMsg": env.get("retMsg"), "new_id": str(res.get("id")) if res.get("id") else None,
            "replaces": res.get("replaces")}


def _verify(after: Dict[str, Any], kind: str, level: float, sent: Dict[str, Any],
            old_id: str) -> Optional[str]:
    """``None`` when the read-back shows *level* on this trade's *kind* leg,
    else the reason it does not."""
    if after.get("read_state") != "resolved":
        return "sent, but the venue read-back failed"
    leg = after.get("stop_leg" if kind == "stop" else "target_leg")
    if leg is None:
        return f"no {kind} leg of this trade's size rests after the PATCH"
    want_id = sent.get("new_id")
    if want_id and leg["id"] not in (want_id, old_id):
        return f"{kind} leg {leg['id']} rests, neither the old {old_id} nor the new {want_id}"
    if want_id and leg["id"] == old_id and want_id != old_id:
        return f"the old {kind} leg {old_id} still rests (PATCH accepted, not replaced)"
    if leg.get("price") is None or abs(leg["price"] - level) > _PRICE_TOL:
        return f"venue reads {kind} {leg.get('price')!r} after the amend, not {level}"
    return None


def tighten(client: Any, *, symbol: str, direction: str, qty: float,
            new_sl: Optional[float] = None, new_tp: Optional[float] = None,
            apply: bool = False) -> Dict[str, Any]:
    """Tighten this trade's stop to *new_sl* and/or move its target to
    *new_tp*. Dry (``planned``) unless *apply*. Never raises."""
    direction = str(direction or "").lower()
    if direction not in ("long", "short"):
        return {"result": X_REFUSED, "detail": f"bad direction {direction!r}"}
    try:
        qty = abs(float(qty))
    except (TypeError, ValueError):
        return {"result": X_REFUSED, "detail": f"bad qty {qty!r}"}
    if qty <= 0:
        return {"result": X_REFUSED, "detail": "qty must be positive (it scopes the legs)"}
    try:
        before = read_trade_legs(client, symbol=symbol, direction=direction, qty=qty)
    except Exception as exc:  # noqa: BLE001 — a raised read is could-not-look
        return {"result": X_COULD_NOT_LOOK, "detail": f"{type(exc).__name__}: {exc}"}
    out: Dict[str, Any] = {"before": before, "oco_leg_ids": {
        "stop": (before.get("stop_leg") or {}).get("id"),
        "target": (before.get("target_leg") or {}).get("id")}}
    if before["read_state"] != "resolved":
        return {**out, "result": X_COULD_NOT_LOOK, "detail": before.get("detail")}
    if before.get("refuse"):
        return {**out, "result": X_REFUSED, "detail": before["refuse"]}
    mark = before.get("mark")
    if mark is None:
        return {**out, "result": X_COULD_NOT_LOOK, "detail": "no mark published"}

    plan: List[Dict[str, Any]] = []
    if new_sl is not None:
        stop = before.get("stop_leg")
        if stop is None:
            return {**out, "result": X_REFUSED,
                    "detail": "no stop leg of this trade's size rests (naked: the re-arm path's job, not an amend)"}
        if stop.get("price") is None:
            return {**out, "result": X_COULD_NOT_LOOK, "detail": f"stop leg {stop['id']} has no readable price"}
        if through_market(direction, stop["price"], mark):
            return {**out, "result": X_REFUSED,
                    "detail": (f"venue_stop_through_market: stop {stop['price']} vs mark {mark} -- the "
                               "leg should already have triggered (wedged OCO shape, PI-20261002-APBY4NTV-0001)")}
        level = round_tighter(direction, float(new_sl))
        if not is_tighter(direction, level, stop["price"]):
            return {**out, "result": X_REFUSED,
                    "detail": f"already_at_or_tighter: resting stop {stop['price']} vs {level}"}
        if through_market(direction, level, mark):
            return {**out, "result": X_REFUSED,
                    "detail": f"would_trigger: {level} is through the mark {mark}"}
        plan.append({"kind": "stop", "leg_id": stop["id"], "field": "stop_price",
                     "from": stop["price"], "to": level})
    if new_tp is not None:
        target = before.get("target_leg")
        if target is None:
            return {**out, "result": X_REFUSED, "detail": "no target leg of this trade's size rests"}
        tp = round(float(new_tp), 2 if new_tp >= 1.0 else 4)
        if (direction == "long" and tp <= mark) or (direction == "short" and tp >= mark):
            return {**out, "result": X_REFUSED, "detail": f"target {tp} is not beyond the mark {mark}"}
        plan.append({"kind": "target", "leg_id": target["id"], "field": "limit_price",
                     "from": target.get("price"), "to": tp})
    if not plan:
        return {**out, "result": X_REFUSED, "detail": "nothing to amend (no new_sl and no new_tp)"}
    out["plan"] = plan
    if not apply:
        return {**out, "result": X_PLANNED, "detail": "dry run: nothing sent"}

    sent_all: List[Dict[str, Any]] = []
    for step in plan:
        try:
            sent = _patch(client, step["leg_id"], step["field"], step["to"])
        except Exception as exc:  # noqa: BLE001
            sent = {"ok": False, "retMsg": f"{type(exc).__name__}: {exc}"}
        sent_all.append({**step, **sent})
        out["sent"] = sent_all
        if not sent.get("ok"):
            return {**out, "result": X_APPLY_FAILED,
                    "detail": f"PATCH {step['kind']} leg {step['leg_id']} refused: {sent.get('retMsg')}"}
        try:
            after = read_trade_legs(client, symbol=symbol, direction=direction, qty=qty)
        except Exception as exc:  # noqa: BLE001
            after = {"read_state": "read_failed", "detail": str(exc)}
        out["after"] = after
        why = _verify(after, step["kind"], step["to"], sent, step["leg_id"])
        if why:
            return {**out, "result": X_APPLY_FAILED, "detail": why}
    after = out["after"]
    return {**out, "result": X_APPLIED, "venue_after": after.get("venue_sl"),
            "venue_tp_after": after.get("venue_tp"),
            "oco_leg_ids_after": {"stop": (after.get("stop_leg") or {}).get("id"),
                                  "target": (after.get("target_leg") or {}).get("id")}}


# ---------------------------------------------------------------------------
# The live-trade-review executor seam (LTR-6R) and its journal write-back
# ---------------------------------------------------------------------------

def exec_trade_leg(db: Any, trade: Dict[str, Any], level: float, *, source: str,
                   mandate: Optional[str] = None, review_id: Optional[str] = None,
                   evidence: Optional[str] = None, bar: Optional[str] = None,
                   client: Any = None) -> Dict[str, Any]:
    """Tighten ONE journal trade leg on its Alpaca account and, only after the
    venue reads the level back, write ``trades.stop_loss`` + ``notes.sl_amends``
    (provenance *source*) + ``notes.sl_floor``. The same write-back shape as
    ``live_review_apply._exec_bybit``, so the order monitor's floor check
    (``held_by_floor``) never trails this leg looser afterwards.

    The shared ``order_packages.sl`` is NOT moved here: the caller moves it
    only when every account's leg applied the same level."""
    direction = str(trade.get("direction") or "").lower()
    if client is None:
        from src.runtime.order_monitor import _build_account_client

        client, cfg = _build_account_client(trade.get("account_id"))
        if client is None or not cfg or str(cfg.get("exchange") or "").lower() != "alpaca":
            return {"result": X_COULD_NOT_LOOK,
                    "detail": f"no alpaca client for {trade.get('account_id')}"}
    res = tighten(client, symbol=str(trade.get("symbol") or ""), direction=direction,
                  qty=_f(trade.get("position_size")) or 0.0, new_sl=level, apply=True)
    if res.get("result") != X_APPLIED:
        return res
    from src.utils.json_notes import dump_capped

    now = datetime.now(timezone.utc).isoformat()
    raw = trade.get("notes")
    try:
        notes = json.loads(raw) if isinstance(raw, str) and raw else (dict(raw) if isinstance(raw, dict) else {})
    except (TypeError, ValueError):
        notes = {}
    if not isinstance(notes, dict):
        notes = {}
    sent_to = next((s["to"] for s in res.get("plan") or [] if s["kind"] == "stop"), level)
    amends = notes.get("sl_amends") if isinstance(notes.get("sl_amends"), list) else []
    amends.append({"source": source, "mandate": mandate, "review_id": review_id,
                   "evidence": evidence, "at": now, "bar": bar,
                   "from": _f(trade.get("stop_loss")), "to": sent_to,
                   "venue_before": (res.get("before") or {}).get("venue_sl"),
                   "venue_after": res.get("venue_after"),
                   "oco_leg_ids": res.get("oco_leg_ids_after")})
    notes["sl_amends"] = amends[-10:]
    notes["sl_floor"] = {"level": sent_to, "source": source, "review_id": review_id, "at": now}
    db.update_trade(int(trade["id"]), {"stop_loss": sent_to, "notes": dump_capped(notes, 2000)})
    return res


# ---------------------------------------------------------------------------
# Read-only dry run over the positions open now
# ---------------------------------------------------------------------------

def dry_run(account_id: str, *, trade_id: Optional[int] = None,
            new_sl: Optional[float] = None, db: Any = None, client: Any = None) -> List[Dict[str, Any]]:
    """What a tighten WOULD send, per open journal trade on *account_id*.
    Without *new_sl* it reports the identified legs and the journal-vs-venue
    stop for each trade. Sends nothing."""
    if db is None:
        from src.units.db.database import Database
        from src.utils.paths import trade_journal_db_path

        db = Database(db_path=trade_journal_db_path())
    if client is None:
        from src.runtime.order_monitor import _build_account_client

        client, _cfg = _build_account_client(account_id)
    rows = db.get_trades(filters={"account_id": account_id, "status": "open", "is_backtest": 0}) or []
    out: List[Dict[str, Any]] = []
    for t in rows:
        if trade_id is not None and int(t.get("id")) != int(trade_id):
            continue
        rec: Dict[str, Any] = {"trade_id": t.get("id"), "symbol": t.get("symbol"),
                               "direction": t.get("direction"), "qty": t.get("position_size"),
                               "journal_sl": t.get("stop_loss"), "journal_tp": t.get("take_profit")}
        if client is None:
            rec.update(result=X_COULD_NOT_LOOK, detail="no alpaca client (missing creds?)")
        else:
            res = tighten(client, symbol=str(t.get("symbol") or ""),
                          direction=str(t.get("direction") or ""),
                          qty=_f(t.get("position_size")) or 0.0,
                          new_sl=new_sl, apply=False)
            if new_sl is None and res.get("result") == X_REFUSED and "nothing to amend" in str(res.get("detail")):
                res["result"], res["detail"] = "read_only", "legs identified; no new_sl given"
            rec.update(res)
        out.append(rec)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--account", required=True)
    ap.add_argument("--trade-id", type=int)
    ap.add_argument("--new-sl", type=float)
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="always on: this CLI never sends an order")
    args = ap.parse_args(argv)
    rows = dry_run(args.account, trade_id=args.trade_id, new_sl=args.new_sl)
    print(json.dumps(rows, indent=1, default=str))
    return 3 if any(r.get("result") == X_COULD_NOT_LOOK for r in rows) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
