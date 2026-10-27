#!/usr/bin/env python3
"""Re-arm BOTH brackets (stop + take-profit, one OCA group) on a FULLY NAKED IB
position — the IB sibling of ``rearm-alpaca-protective``'s row mode.

Why this exists
---------------
Operator rule, 2026-10-26 (verbatim): *"every trade always must have BOTH
brackets ... Claude can move the brackets, but nothing is supposed to remove
brackets"*. The same day ``ib_paper``/MGC sat short 12 with **no stop and no
take-profit** (fresh ``/api/diag/ib_open_orders`` read: only MHG legs on the
account), and no sanctioned action could place a stop on it:

* ``attach-ib-target`` only JOINS a target to an existing stop's OCA group —
  there was no stop to join;
* ``flatten-ib-position`` closes the position, it does not protect it;
* the trader's own sweep (``order_monitor._check_broker_naked_ib_positions``)
  refused because journal row 6673 says ``position_size=14`` while the broker
  holds 12, and its foreign-target check read ``0 + 14 > 12`` as "a second
  target could open a reverse position".

The mechanism
-------------
``IBClient.place_protective`` with ``oca_key=<row id>``: a STP and a LMT in ONE
OCA group ``oca-protect-t<row>`` (ocaType=1, GTC), the reverse side of the
position. Its pre-cancel is scoped to that group name and this script refuses
unless NOTHING rests on the symbol, so the pre-cancel has nothing to touch.

Levels come from the journal (``trades.stop_loss`` / ``trades.take_profit_1``)
— never from the caller. Qty is the LIVE broker size (clamped DOWN to whole
contracts and never above the journal row), so neither leg can fill past flat.

Refusals (nothing is placed)
---------------------------
* any order — protective or not — resting on the symbol (this is for a FULLY
  naked position only; a partial book is the sweep's / ``attach-ib-target``'s);
* more than one OPEN journal row for (account, symbol), or ``--row`` not that row;
* journal SL or TP missing (a target is never invented; that is Tier-3);
* broker flat, broker side != journal direction, or broker size > journal size;
* the contract ``place_protective`` would resolve differs from the position's;
* levels that do not straddle the current mark (a BUY STP below a short's mark
  would fire at once). An unreadable mark refuses unless
  ``--allow-unverified-mark`` is passed — and that is echoed in the output;
* any could-not-look read (account, journal, positions, orders).

Verification: re-reads the account-wide order book on a fresh read client and
requires exactly one STP and one LMT on the symbol, in group
``oca-protect-t<row>``, at the journal levels (to the tick), for the qty.

DRY-RUN by default. Never raises; every outcome is JSON. Exit codes:
0 ok/dry-run · 1 place failed · 2 could not look · 3 placed but unverified ·
4 refused.

Usage (on the live VM, via the ``rearm-ib-protective`` system-action):
    python3 scripts/ops/rearm_ib_protective.py --account ib_paper --symbol MGC --row 6673
    python3 scripts/ops/rearm_ib_protective.py --account ib_paper --symbol MGC --row 6673 --apply
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Statuses that mean the order is no longer working at the venue. A fresh
# reqAllOpenOrders should not return them, but a row that does is not resting.
_TERMINAL = {"cancelled", "apicancelled", "filled", "inactive"}


def _is_stop(order_type: Optional[str]) -> bool:
    t = str(order_type or "").upper()
    return "TRAIL" in t or t.startswith("STP")


def _is_target(order_type: Optional[str]) -> bool:
    t = str(order_type or "").upper()
    return not _is_stop(t) and ("LMT" in t or t == "LIMIT")


def _resting(rows: List[Dict[str, Any]], sym: str) -> List[Dict[str, Any]]:
    return [
        r for r in rows
        if str(r.get("symbol") or "").upper() == sym
        and str(r.get("status") or "").replace(" ", "").lower() not in _TERMINAL
    ]


def _load_account(account_id: str) -> Optional[Dict[str, Any]]:
    from src.units.ui.data_loaders import list_accounts

    for acc in list_accounts() or []:
        if (acc or {}).get("account_id") == account_id or (acc or {}).get("name") == account_id:
            return acc
    return None


def _ib_ops_client_id() -> int:
    """Process-unique OPS clientId (9900-range): never the trader's execution
    ids (496/497/498) nor the 9000-9899 read band — see attach_ib_target.py
    ``_ib_ops_client_id`` for the Error 326 history behind this rule."""
    return 9900 + (os.getpid() % 90)


def _open_rows(account_id: str, symbol: str) -> Optional[List[Dict[str, Any]]]:
    """Every OPEN live journal row for (account, symbol root). Read-only."""
    import sqlite3

    from src.utils.paths import trade_journal_db_path

    try:
        conn = sqlite3.connect(f"file:{trade_journal_db_path()}?mode=ro", uri=True)
    except Exception:  # noqa: BLE001
        return None
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, symbol, direction, position_size, stop_loss, "
            "take_profit_1 FROM trades WHERE status='open' AND account_id=? "
            "AND COALESCE(is_backtest,0)=0 AND UPPER(symbol) LIKE ?",
            (account_id, f"{symbol.upper()}%"),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        return None
    finally:
        conn.close()


def _broker_read(cfg: Dict[str, Any], sym: str) -> Dict[str, Any]:
    """One fresh READ client: positions, open orders, resolved contract, mark.

    Each field is three-state: a value, or ``None`` with a ``*_error`` saying we
    could not look. A brand-new process has no accumulated ib_insync order
    cache, so this order read does not carry the stale-cancelled rows the
    long-lived diag route can (BL-20260826-DIAG-IB-OPEN-ORDERS-SERVES-A-STALE-
    MONOTONIC-ORDER-VIEW applies to a long-lived client, not to this one).
    """
    from src.units.accounts.clients import ib_read_client_for

    out: Dict[str, Any] = {"positions": None, "orders": None,
                           "contract_local_symbol": None, "mark": None}
    client = ib_read_client_for(cfg)
    if client is None:
        out["error"] = "could not build an IB read client"
        return out
    try:
        ib = client.connect()
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"connect failed: {type(exc).__name__}: {exc}"
        return out
    try:
        pos = []
        for p in client._req_positions_snapshot(ib) or []:
            c = getattr(p, "contract", None)
            if str(getattr(c, "symbol", "") or "").upper() != sym:
                continue
            pos.append({"local_symbol": str(getattr(c, "localSymbol", "") or ""),
                        "con_id": getattr(c, "conId", None),
                        "position": float(getattr(p, "position", 0) or 0.0)})
        out["positions"] = pos
    except Exception as exc:  # noqa: BLE001
        out["positions_error"] = f"{type(exc).__name__}: {exc}"
    try:
        out["orders"] = client.list_open_orders()
    except Exception as exc:  # noqa: BLE001
        out["orders_error"] = f"{type(exc).__name__}: {exc}"
    contract = None
    try:
        contract = client._build_contract(sym)
        out["contract_local_symbol"] = str(getattr(contract, "localSymbol", "") or "")
        out["contract_con_id"] = getattr(contract, "conId", None)
    except Exception as exc:  # noqa: BLE001
        out["contract_error"] = f"{type(exc).__name__}: {exc}"
    if contract is not None:
        try:
            # 4 = delayed-frozen: live when subscribed, else delayed/last close.
            ib.reqMarketDataType(4)
            tickers = ib.reqTickers(contract)
            t = tickers[0] if tickers else None
            for cand in ((t.marketPrice() if t is not None else None),
                         getattr(t, "last", None), getattr(t, "close", None)):
                try:
                    v = float(cand)
                except (TypeError, ValueError):
                    continue
                if v > 0 and math.isfinite(v):
                    out["mark"] = v
                    break
        except Exception as exc:  # noqa: BLE001
            out["mark_error"] = f"{type(exc).__name__}: {exc}"
    try:
        client.disconnect()
    except Exception:  # noqa: BLE001
        pass
    return out


def _place(cfg: Dict[str, Any], *, account_id: str, symbol: str, direction: str,
           qty: float, sl: float, tp: float, row_id: int) -> Dict[str, Any]:
    from src.units.accounts.clients import ib_client_for

    client = ib_client_for(cfg, client_id=_ib_ops_client_id(), readonly=False)
    if client is None:
        return {"retCode": 1, "retMsg": "could not build an IB client"}
    try:
        return client.place_protective({
            "symbol": symbol, "direction": direction, "qty": qty,
            "sl": sl, "tp": tp, "oca_key": str(row_id), "account_id": account_id,
        })
    except Exception as exc:  # noqa: BLE001
        return {"retCode": 1, "retMsg": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _tick(sym: str) -> float:
    try:
        from src.core.profile_loader import tick_size_for

        t = float(tick_size_for(sym) or 0.0)
        return t if t > 0 else 1e-6
    except Exception:  # noqa: BLE001
        return 1e-6


def _verify(rows: List[Dict[str, Any]], sym: str, *, group: str, qty: float,
            sl: float, tp: float, tick: float) -> Dict[str, Any]:
    mine = _resting(rows, sym)
    stops = [r for r in mine if _is_stop(r.get("order_type"))]
    targets = [r for r in mine if _is_target(r.get("order_type"))]

    def _ok(r: Dict[str, Any], px_key: str, want: float) -> bool:
        try:
            return (str(r.get("oca_group") or "") == group
                    and abs(float(r.get("total_quantity") or 0) - qty) < 1e-9
                    and abs(float(r.get(px_key) or 0) - want) <= tick + 1e-9)
        except (TypeError, ValueError):
            return False

    good = (len(mine) == 2 and len(stops) == 1 and len(targets) == 1
            and _ok(stops[0], "aux_price", sl) and _ok(targets[0], "lmt_price", tp))
    return {"verified": good, "orders_on_symbol": mine}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--account", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--row", type=int, required=True,
                    help="the open journal trade id the bracket belongs to")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-unverified-mark", action="store_true")
    args = ap.parse_args(argv)

    sym = args.symbol.upper()
    out: Dict[str, Any] = {"account": args.account, "symbol": sym, "row": args.row,
                           "apply": bool(args.apply),
                           "allow_unverified_mark": bool(args.allow_unverified_mark)}

    def _emit(code: int, **kw: Any) -> int:
        out.update(kw)
        print(json.dumps(out, indent=2, default=str))
        return code

    cfg = _load_account(args.account)
    if cfg is None:
        return _emit(2, state="could_not_look", error=f"unknown account {args.account!r}")
    if str(cfg.get("exchange", "")).lower() not in ("interactive_brokers", "ib"):
        return _emit(4, state="refused", blocker="not an IB account")

    rows = _open_rows(args.account, sym)
    if rows is None:
        return _emit(2, state="could_not_look", error="journal read failed")
    out["open_rows"] = [r.get("id") for r in rows]
    if len(rows) != 1 or int(rows[0]["id"]) != args.row:
        return _emit(4, state="refused", blocker=(
            f"expected exactly one OPEN journal row for {args.account}/{sym} and "
            f"it to be row {args.row}; found {out['open_rows']}. Several rows on a "
            "netted contract need per-row sizing this action does not do."))
    trade = rows[0]
    direction = str(trade.get("direction") or "").lower()
    try:
        sl = float(trade.get("stop_loss") or 0)
        tp = float(trade.get("take_profit_1") or 0)
        journal_qty = float(trade.get("position_size") or 0)
    except (TypeError, ValueError):
        return _emit(4, state="refused", blocker="unreadable journal levels/size")
    out.update(direction=direction, journal_sl=sl, journal_tp=tp, journal_qty=journal_qty)
    if direction not in ("long", "short"):
        return _emit(4, state="refused", blocker=f"journal direction {direction!r}")
    if sl <= 0 or tp <= 0:
        return _emit(4, state="refused", blocker=(
            "journal SL or TP missing — both brackets are required and a level is "
            "never invented here"))

    br = _broker_read(cfg, sym)
    out["broker"] = {k: v for k, v in br.items() if k != "orders"}
    if br.get("positions") is None or br.get("orders") is None:
        return _emit(2, state="could_not_look", error=(
            "position or order read failed — NOT evidence the position is naked"))
    resting = _resting(br["orders"], sym)
    out["resting_on_symbol"] = resting
    if resting:
        return _emit(4, state="refused", blocker=(
            f"{len(resting)} order(s) already resting on {sym}; this action is for "
            "a FULLY naked position only (nothing to cancel, nothing to join)"))
    if len(br["positions"]) != 1:
        return _emit(4, state="refused", blocker=(
            f"expected one {sym} position, found {len(br['positions'])}"))
    p = br["positions"][0]
    signed = p["position"]
    if signed == 0:
        return _emit(4, state="refused", blocker="broker reads flat")
    if (signed > 0) != (direction == "long"):
        return _emit(4, state="refused", blocker=(
            f"broker side ({'long' if signed > 0 else 'short'}) != journal {direction}"))
    size = float(math.floor(abs(signed)))
    if size < 1:
        return _emit(4, state="refused", blocker=f"broker size {abs(signed)} < 1 contract")
    if size > journal_qty + 1e-9:
        return _emit(4, state="refused", blocker=(
            f"broker size {size} > journal position_size {journal_qty} — the excess "
            "is untracked; not stamping this row's geometry over it"))
    out["qty"] = size
    if size != journal_qty:
        out["size_note"] = (f"journal says {journal_qty}, broker holds {size}; both "
                            "legs are sized to the BROKER qty so neither fills past flat")
    want_ls = p.get("local_symbol") or ""
    got_ls = br.get("contract_local_symbol") or ""
    if not want_ls or not got_ls or want_ls != got_ls:
        return _emit(4, state="refused", blocker=(
            f"position contract {want_ls!r} != the contract place_protective would "
            f"resolve {got_ls!r} — a bracket on another month protects nothing"))

    mark = br.get("mark")
    if mark is None:
        if not args.allow_unverified_mark:
            return _emit(4, state="refused", blocker=(
                "could not read a mark to check the levels straddle price; pass "
                "allow_unverified_mark: true only after checking it another way"))
        out["mark_check"] = "SKIPPED (allow_unverified_mark)"
    else:
        straddles = (sl > mark > tp) if direction == "short" else (sl < mark < tp)
        out["mark_check"] = "straddles" if straddles else "DOES_NOT_STRADDLE"
        if not straddles:
            return _emit(4, state="refused", blocker=(
                f"levels sl={sl} tp={tp} do not straddle mark {mark} for a "
                f"{direction} — a leg would fill on arrival"))

    group = f"oca-protect-t{args.row}"
    out["oca_group"] = group
    if not args.apply:
        rev = "BUY" if direction == "short" else "SELL"
        return _emit(0, state="ready", action="dry_run", would=(
            f"place {rev} STP {size} @ {sl} + {rev} LMT {size} @ {tp} in OCA "
            f"{group!r} (GTC) on {got_ls}"))

    resp = _place(cfg, account_id=args.account, symbol=sym, direction=direction,
                  qty=size, sl=sl, tp=tp, row_id=args.row)
    out["place_response"] = resp
    if resp.get("retCode") != 0:
        return _emit(1, state="place_failed", action="place_failed")

    tick = _tick(sym)
    ver: Dict[str, Any] = {}
    for _ in range(5):
        time.sleep(2.0)
        after = _broker_read(cfg, sym)
        if after.get("orders") is None:
            ver = {"verified": None, "error": after.get("orders_error") or after.get("error")}
            continue
        ver = _verify(after["orders"], sym, group=group, qty=size, sl=sl, tp=tp, tick=tick)
        if ver["verified"]:
            break
    out["verify"] = ver
    if ver.get("verified"):
        return _emit(0, state="rearmed", action="placed",
                     verify_state="both_legs_resting")
    if ver.get("verified") is None:
        return _emit(3, state="placed_unconfirmed", action="placed",
                     verify_state="could_not_look",
                     note="accepted is not confirmed; re-run the dry-run before retrying")
    return _emit(3, state="placed_unverified", action="placed",
                 verify_state="legs_not_as_expected",
                 note=("the place was accepted but the re-read does not show exactly "
                       "one STP + one LMT at the journal levels — inspect before "
                       "any retry (a retry reuses the same OCA group)"))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
