#!/usr/bin/env python3
"""Operator-directed TIGHTENING of one live Bybit position's stop-loss.

Why this exists
---------------
AMEND-SL-ACTION (operator, 2026-10-24, popup "Build the action now"): there
was no sanctioned path to move a live Bybit stop by hand. Moving only the venue
stop is not enough, because the order monitor holds the stop in the JOURNAL and
every trail tick compares against that record — ``htf_pullback_trend_2h.monitor``
(and every trend/pullback trail) only proposes a new stop when
``candidate < open_pkg["sl"]`` for a short (``>`` for a long), and
``interpret_verdict`` is fed ``open_pkg.get("sl")``. So a venue-only change is
silently undone the next time the trail moves: the monitor amends the venue to
its own (looser) level. The record the monitor reads is
``order_packages.sl``; ``trades.stop_loss`` is what every operator surface
reads. This action moves the venue stop AND both journal fields together.

Because the trail only ever ratchets in the trade's favour relative to the
package stop, a tighter package stop is respected from then on: the trail stays
quiet until its own candidate is tighter still.

What it does
------------
1. Resolves the target trade row (``--trade-id``, or ``--symbol`` + ``--side``
   when exactly one open row matches), its account (must be Bybit and
   ``mode: live``) and its OPEN order package.
2. Reads every open leg of that package. One package fans out across N
   accounts (live + mirror) and they share ONE ``order_packages.sl``, so the
   amend goes to every leg — exactly what the monitor's own modify path does
   (``order_monitor._apply_update``). Amending one leg while moving the shared
   package stop would leave the siblings' venue stops diverged.
3. Reads the venue: the position (side, size, mark) and the resting stop of
   each live leg.
4. REFUSES (exit 2) — never guesses:
     * a LOOSER stop than the package stop, any leg's ``trades.stop_loss``, or
       any leg's resting venue stop (short: new_sl must be BELOW; long: ABOVE);
     * a stop on the wrong side of the mark (would trigger at once) unless
       ``--allow-immediate``;
     * a missing trade row, package, or venue position;
     * a non-live or non-Bybit account, or a non-Bybit leg in the package.
   Could not look (venue/journal unreadable) is exit 3, never folded into a
   refusal or a success.
5. DRY-RUN by default: prints the before state and the plan. ``--apply``
   amends through the EXISTING monitor seam
   (``order_monitor._send_modify_to_exchange`` → ``execute.modify_open_order``,
   which amends a tracked Partial leg in place) — no new order path.
6. Reads every live leg back from the venue. Only a leg whose venue stop now
   reads ``new_sl`` gets ``trades.stop_loss`` written (plus a provenance entry
   in ``trades.notes.sl_amends`` with source ``manual_amend_operator`` and the
   reason). ``order_packages.sl`` is written once the TARGET leg is confirmed —
   leaving it looser while the target venue stop is tighter is exactly the
   state the next trail would loosen. A sibling that did not confirm is
   reported (exit 1) and a re-run finishes it.
7. Idempotent: when the package, every leg's stop_loss and every live venue
   stop already read ``new_sl``, it reports ``already_applied`` and writes
   nothing.

Exit codes: 0 ok (preview / applied / already applied) · 1 amend failed or did
not verify · 2 refused by a guard · 3 could not look.

Usage (on the live VM, via the ``amend-position-sl`` system-action):
    python3 scripts/ops/amend_position_sl.py --account bybit_2 --trade-id 123 \
        --new-sl 0.2053 --reason "operator popup 2026-10-24"
    ... --apply
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

PROVENANCE = "manual_amend_operator"
_SL_TYPES = {"stoploss", "partialstoploss"}

EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_UNREADABLE = 0, 1, 2, 3


# --------------------------------------------------------------------------
# Seams (monkeypatched in tests)
# --------------------------------------------------------------------------

def _open_db():
    from src.runtime.order_monitor import _resolve_db

    return _resolve_db(None)


def _build_client(account_id: str):
    """``(client, cfg)`` exactly as the monitor builds them (cfg carries mode)."""
    from src.runtime.order_monitor import _build_account_client

    return _build_account_client(account_id)


def _send_modify(leg: dict[str, Any], **kwargs) -> dict[str, Any]:
    """The monitor's own exchange seam for an SL/TP modify."""
    from src.runtime.order_monitor import _send_modify_to_exchange

    return _send_modify_to_exchange(leg, **kwargs)


def _tick_size(client, cfg: dict[str, Any], symbol: str) -> float | None:
    try:
        from src.units.accounts.execute import _bybit_category
        from src.units.accounts.precision import get_tick_size

        tick = get_tick_size(client, symbol, _bybit_category(cfg))
        return float(tick) if tick else None
    except Exception:  # noqa: BLE001
        return None


def _get_package(db, pkg_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        conn.row_factory = __import__("sqlite3").Row
        row = conn.execute(
            "SELECT * FROM order_packages WHERE order_package_id = ?",
            (pkg_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _venue_state(client, cfg: dict[str, Any], symbol: str, direction: str,
                 sl_order_id: str | None) -> dict[str, Any]:
    """The venue's view of one leg. ``read_state`` is never collapsed:
    ``resolved`` (looked; ``position`` may be None = flat on that side) or
    ``read_failed`` (we could not look)."""
    out: dict[str, Any] = {"read_state": "read_failed", "position": None,
                           "mark": None, "venue_sl": None, "sl_source": None}
    try:
        from src.units.accounts.execute import _bybit_category

        category = _bybit_category(cfg)
        want_side = "Buy" if direction == "long" else "Sell"
        resp = client.get_positions(category=category, symbol=symbol)
        rows = ((resp or {}).get("result") or {}).get("list")
        if rows is None:
            return out
        pos = None
        for r in rows:
            try:
                size = float(r.get("size") or 0)
            except (TypeError, ValueError):
                size = 0.0
            if size > 0 and str(r.get("side")) == want_side:
                pos = r
                break
        oresp = client.get_open_orders(category=category, symbol=symbol,
                                       orderFilter="StopOrder")
        orders = ((oresp or {}).get("result") or {}).get("list")
        if orders is None:
            return out
        sl_legs = [o for o in orders
                   if str(o.get("stopOrderType", "")).lower() in _SL_TYPES]
        out["read_state"] = "resolved"
        if pos is None:
            return out
        out["position"] = {"side": pos.get("side"), "size": pos.get("size")}
        out["mark"] = _f(pos.get("markPrice"))
        if sl_order_id:
            hit = [o for o in sl_legs if str(o.get("orderId")) == str(sl_order_id)]
            if hit:
                out["venue_sl"] = _f(hit[0].get("triggerPrice"))
                out["sl_source"] = f"tracked_leg:{sl_order_id}"
            return out
        pos_sl = _f(pos.get("stopLoss"))
        if pos_sl:
            out["venue_sl"], out["sl_source"] = pos_sl, "position_stopLoss"
        elif len(sl_legs) == 1:
            out["venue_sl"] = _f(sl_legs[0].get("triggerPrice"))
            out["sl_source"] = f"sole_sl_leg:{sl_legs[0].get('orderId')}"
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


def _ping(leg: dict[str, Any], new_sl: float, n_legs: int) -> None:
    try:
        from src.runtime.execution_diagnostics import enqueue_trade_update

        changes = [f"SL → {new_sl:g} ({PROVENANCE})"]
        if n_legs > 1:
            changes.append(f"({n_legs} legs)")
        enqueue_trade_update(symbol=leg.get("symbol") or "?",
                             account=leg.get("account_id"),
                             strategy=leg.get("strategy_name") or leg.get("setup_type"),
                             changes=changes)
    except Exception as exc:  # noqa: BLE001 — the amend already landed
        print(f">>> amend-position-sl: trade-update ping failed (amend stands): {exc}")


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x != 0 else None


def is_looser(direction: str, new_sl: float, current: float, tol: float) -> bool:
    """True when ``new_sl`` moves the stop AWAY from price relative to
    ``current`` by more than ``tol``. Short: higher is looser; long: lower."""
    if direction == "short":
        return new_sl > current + tol
    return new_sl < current - tol


def same_level(a: float | None, b: float | None, tol: float) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def would_trigger(direction: str, new_sl: float, mark: float) -> bool:
    """A short's stop at/below the mark, or a long's at/above it, fires at once."""
    return new_sl <= mark if direction == "short" else new_sl >= mark


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

def amend(account_id: str, *, new_sl: float, reason: str,
          trade_id: int | None = None, symbol: str | None = None,
          side: str | None = None, apply: bool = False,
          allow_immediate: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"account_id": account_id, "new_sl": new_sl,
                           "apply": apply, "action": None, "ok": False,
                           "exit": EXIT_REFUSED, "detail": None,
                           "before": {}, "after": {}}

    def _done(action: str, code: int, detail: str) -> dict[str, Any]:
        out.update(action=action, exit=code, ok=code == EXIT_OK, detail=detail)
        return out

    if new_sl is None or not math.isfinite(new_sl) or new_sl <= 0:
        return _done("refuse_bad_input", EXIT_REFUSED, f"new_sl {new_sl!r} must be a positive number")
    if not (reason or "").strip():
        return _done("refuse_bad_input", EXIT_REFUSED, "reason is required (it is the provenance record)")
    if trade_id is None and not (symbol and side):
        return _done("refuse_bad_input", EXIT_REFUSED, "give trade_id, or symbol + side")
    if side is not None and side.lower() not in ("long", "short"):
        return _done("refuse_bad_input", EXIT_REFUSED, f"side must be long or short (got {side!r})")

    client, cfg = _build_client(account_id)
    if not cfg:
        return _done("refuse_no_account", EXIT_REFUSED, f"account {account_id!r} not found in accounts.yaml")
    if str(cfg.get("exchange") or "").lower() != "bybit":
        return _done("refuse_not_bybit", EXIT_REFUSED, f"account {account_id!r} is exchange={cfg.get('exchange')!r}, not Bybit")
    if cfg.get("mode") != "live":
        return _done("refuse_not_live", EXIT_REFUSED, f"account {account_id!r} is mode={cfg.get('mode')!r}, not live")
    if client is None:
        return _done("unreadable_no_client", EXIT_UNREADABLE, f"no exchange client for {account_id!r} (missing creds?)")

    # ---- journal ----------------------------------------------------------
    try:
        db = _open_db()
        if trade_id is not None:
            rows = db.get_trades(filters={"id": int(trade_id)})
        else:
            rows = [r for r in db.get_trades(filters={
                "account_id": account_id, "symbol": symbol.upper(), "status": "open"})
                if str(r.get("direction") or "").lower() == side.lower()]
    except Exception as exc:  # noqa: BLE001
        return _done("unreadable_journal", EXIT_UNREADABLE, f"journal read failed: {exc}")
    rows = [r for r in rows if not r.get("is_backtest")]
    if not rows:
        return _done("refuse_no_trade", EXIT_REFUSED, "no matching trade row")
    if len(rows) > 1:
        return _done("refuse_ambiguous", EXIT_REFUSED,
                     f"{len(rows)} open rows match — pass trade_id: ids={[r.get('id') for r in rows]}")
    trade = rows[0]
    if trade.get("account_id") != account_id:
        return _done("refuse_wrong_account", EXIT_REFUSED,
                     f"trade {trade.get('id')} belongs to {trade.get('account_id')!r}, not {account_id!r}")
    if trade.get("status") != "open":
        return _done("refuse_not_open", EXIT_REFUSED, f"trade {trade.get('id')} is status={trade.get('status')!r}")
    direction = str(trade.get("direction") or "").lower()
    if direction not in ("long", "short"):
        return _done("refuse_bad_direction", EXIT_REFUSED, f"trade {trade.get('id')} direction={direction!r}")
    sym = str(trade.get("symbol") or "").upper()
    out.update(trade_id=trade.get("id"), symbol=sym, direction=direction)

    pkg_id = trade.get("order_package_id")
    try:
        pkg = _get_package(db, pkg_id) if pkg_id else None
        legs = [r for r in db.get_trades(filters={"order_package_id": pkg_id, "status": "open"})
                if not r.get("is_backtest")] if pkg_id else []
    except Exception as exc:  # noqa: BLE001
        return _done("unreadable_journal", EXIT_UNREADABLE, f"package read failed: {exc}")
    if not pkg:
        return _done("refuse_no_package", EXIT_REFUSED,
                     f"trade {trade.get('id')} has no order package ({pkg_id!r}) — the monitor holds no stop to keep in sync")
    if pkg.get("status") != "open":
        return _done("refuse_package_not_open", EXIT_REFUSED, f"package {pkg_id} is status={pkg.get('status')!r}")
    if not any(str(r.get("id")) == str(trade.get("id")) for r in legs):
        legs.insert(0, trade)
    legs.sort(key=lambda r: str(r.get("id")) != str(trade.get("id")))  # target first

    tick = _tick_size(client, cfg, sym)
    tol = (tick / 2.0) if tick else max(abs(new_sl) * 1e-6, 1e-9)
    pkg_sl = _f(pkg.get("sl"))
    out["before"]["package"] = {"order_package_id": pkg_id, "sl": pkg_sl}
    if pkg_sl is None:
        return _done("unreadable_package_sl", EXIT_UNREADABLE, f"package {pkg_id} sl={pkg.get('sl')!r} unreadable")
    if is_looser(direction, new_sl, pkg_sl, tol):
        return _done("refuse_looser", EXIT_REFUSED,
                     f"new_sl {new_sl:g} is LOOSER than the journal stop {pkg_sl:g} for a {direction} "
                     f"(a {direction} stop may only move {'down' if direction == 'short' else 'up'})")

    # ---- venue ------------------------------------------------------------
    leg_states: list[dict[str, Any]] = []
    for leg in legs:
        aid = leg.get("account_id")
        if aid == account_id:
            lc, lcfg = client, cfg
        else:
            lc, lcfg = _build_client(aid)
        if not lcfg or str(lcfg.get("exchange") or "").lower() != "bybit":
            return _done("refuse_non_bybit_leg", EXIT_REFUSED,
                         f"package leg {leg.get('id')} is on {aid!r} (not Bybit) — out of scope")
        live = lcfg.get("mode") == "live"
        st: dict[str, Any] = {"trade_id": leg.get("id"), "account_id": aid, "live": live,
                              "stop_loss": _f(leg.get("stop_loss")), "leg": leg}
        if is_looser(direction, new_sl, st["stop_loss"] or new_sl, tol):
            return _done("refuse_looser", EXIT_REFUSED,
                         f"new_sl {new_sl:g} is LOOSER than trade {leg.get('id')}'s stop_loss {st['stop_loss']:g}")
        if live:
            if lc is None:
                return _done("unreadable_no_client", EXIT_UNREADABLE, f"no exchange client for leg account {aid!r}")
            vs = _venue_state(lc, lcfg, sym, direction, leg.get("sl_order_id"))
            st.update(venue=vs)
            if vs["read_state"] != "resolved":
                return _done("unreadable_venue", EXIT_UNREADABLE,
                             f"could not read the venue for {aid}/{sym}: {vs.get('error') or 'no data'}")
            if vs["position"] is None:
                return _done("refuse_no_position", EXIT_REFUSED,
                             f"no open {direction} position on {aid}/{sym} for trade {leg.get('id')}")
            if vs["venue_sl"] is None:
                return _done("unreadable_venue_sl", EXIT_UNREADABLE,
                             f"cannot identify the resting stop on {aid}/{sym} (sl_order_id={leg.get('sl_order_id')!r})")
            if is_looser(direction, new_sl, vs["venue_sl"], tol):
                return _done("refuse_looser", EXIT_REFUSED,
                             f"new_sl {new_sl:g} is LOOSER than the resting venue stop {vs['venue_sl']:g} on {aid}")
        leg_states.append(st)

    out["before"]["legs"] = [{k: v for k, v in s.items() if k != "leg"} for s in leg_states]
    mark = (leg_states[0].get("venue") or {}).get("mark")
    if mark is None:
        return _done("unreadable_mark", EXIT_UNREADABLE, f"no mark price for {account_id}/{sym}")
    out["before"]["mark"] = mark
    if would_trigger(direction, new_sl, mark) and not allow_immediate:
        return _done("refuse_wrong_side", EXIT_REFUSED,
                     f"new_sl {new_sl:g} is on the wrong side of mark {mark:g} for a {direction} — it would "
                     f"trigger immediately (pass allow_immediate: true to do it anyway)")

    need_venue = [s for s in leg_states if s["live"] and not same_level(s["venue"]["venue_sl"], new_sl, tol)]
    need_db = [s for s in leg_states if not same_level(s["stop_loss"], new_sl, tol)]
    pkg_needs = not same_level(pkg_sl, new_sl, tol)
    out["plan"] = {"venue_amend_trade_ids": [s["trade_id"] for s in need_venue],
                   "journal_trade_ids": [s["trade_id"] for s in need_db],
                   "package_sl": pkg_needs}
    if not need_venue and not need_db and not pkg_needs:
        out["after"] = out["before"]
        return _done("already_applied", EXIT_OK, f"every leg, the package and the venue already read {new_sl:g}")
    if not apply:
        return _done("dry_run", EXIT_OK, "preview only — set apply: true to amend")

    # ---- apply ------------------------------------------------------------
    results: dict[str, Any] = {}
    for s in need_venue:
        leg = s["leg"]
        try:
            qty = float(leg.get("position_size")) if leg.get("position_size") is not None else None
        except (TypeError, ValueError):
            qty = None
        results[str(s["trade_id"])] = _send_modify(
            leg, sl=new_sl, side=direction, qty=qty,
            cur_sl=pkg_sl, cur_tp=_f(pkg.get("tp")))
    out["amend_results"] = results

    now = datetime.now(timezone.utc).isoformat()
    confirmed: list[Any] = []
    unconfirmed: list[str] = []
    after_legs = []
    for s in leg_states:
        leg = s["leg"]
        rec: dict[str, Any] = {"trade_id": s["trade_id"], "account_id": s["account_id"]}
        if s["live"]:
            lc, lcfg = (client, cfg) if s["account_id"] == account_id else _build_client(s["account_id"])
            vs = _venue_state(lc, lcfg, sym, direction, leg.get("sl_order_id"))
            rec["venue_sl"] = vs.get("venue_sl")
            ok = vs["read_state"] == "resolved" and same_level(vs.get("venue_sl"), new_sl, tol)
        else:
            ok = True  # dry-run account: no venue stop, the journal is the stop
        if not ok:
            unconfirmed.append(f"{s['trade_id']}/{s['account_id']}: venue reads {rec.get('venue_sl')!r}")
            after_legs.append({**rec, "stop_loss": s["stop_loss"]})
            continue
        confirmed.append(s["trade_id"])
        if not same_level(s["stop_loss"], new_sl, tol):
            from src.utils.json_notes import dump_capped, load_notes

            notes = load_notes(leg.get("notes"))
            amends = notes.get("sl_amends") if isinstance(notes.get("sl_amends"), list) else []
            amends.append({"source": PROVENANCE, "reason": reason, "at": now,
                           "from": s["stop_loss"], "to": new_sl,
                           "venue_before": (s.get("venue") or {}).get("venue_sl"),
                           "venue_after": rec.get("venue_sl")})
            notes["sl_amends"] = amends[-10:]
            db.update_trade(int(s["trade_id"]), {"stop_loss": new_sl,
                                                 "notes": dump_capped(notes, 2000)})
        after_legs.append({**rec, "stop_loss": new_sl})

    target_ok = str(leg_states[0]["trade_id"]) in {str(c) for c in confirmed}
    if target_ok and pkg_needs:
        db.update_order_package(pkg_id, {"sl": new_sl})
    out["after"] = {"package": {"order_package_id": pkg_id,
                                "sl": new_sl if target_ok else pkg_sl},
                    "legs": after_legs}
    if not target_ok:
        return _done("amend_failed", EXIT_FAILED,
                     "target leg did not verify at the venue — journal left UNCHANGED: " + "; ".join(unconfirmed))
    _ping(leg_states[0]["leg"], new_sl, len(confirmed))
    if unconfirmed:
        return _done("partial", EXIT_FAILED,
                     "target leg + package moved; sibling leg(s) did not verify — re-run to finish: "
                     + "; ".join(unconfirmed))
    return _done("applied", EXIT_OK, f"stop moved to {new_sl:g} on {len(confirmed)} leg(s); journal + package written")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--account", required=True)
    ap.add_argument("--trade-id", type=int)
    ap.add_argument("--symbol")
    ap.add_argument("--side", choices=["long", "short"])
    ap.add_argument("--new-sl", type=float, required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-immediate", action="store_true")
    a = ap.parse_args(argv)
    res = amend(a.account, new_sl=a.new_sl, reason=a.reason, trade_id=a.trade_id,
                symbol=a.symbol, side=a.side, apply=a.apply,
                allow_immediate=a.allow_immediate)
    print(json.dumps(res, indent=2, default=str))
    print(f">>> amend-position-sl: {res['action']} — {res['detail']}")
    return int(res["exit"])


if __name__ == "__main__":
    sys.exit(main())
