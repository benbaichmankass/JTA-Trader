"""Settle an ``intent_reduce`` leg's realised PnL from stored broker fills.

THE DEFECT (PERF-FU-REDUCE-PNL, measured 2026-10-11)
----------------------------------------------------
``apply_intent_reduce_partial_close`` (``src/units/accounts/execute.py``) books
an intent-layer reduce as a FIFO partial close of the parent rows and writes one
audit row (``exit_reason='intent_reduce_executed'``) with ``pnl`` NULL and
``notes.pnl_source='deferred_intent_reduce'``. Every reader of that marker
(``check_db_integrity`` INV-2c, ``provenance._absorbed_partial_pnl``,
``supersede_intent_reduce_phantom_pnl``) assumes *"the parent leg carries the
realised pnl"*. That holds only for a parent the reduce consumed FULLY (its row
closes with ``exit_reason='intent_reduce'`` and the local sweep prices it over
its whole size). A PARTIALLY consumed parent is **shrunk** — its
``position_size`` drops by ``consumed`` — so when it later closes, its pnl is
computed on the remaining units only. The reduced units' realised P&L lands on
**no row**: nothing ever settles it, because no settler exists. The 33 reduce
legs that did carry a ``pnl`` were the BL-20260711 phantoms (mark-priced,
``reconcile_status='superseded'``), not settlements.

Population (diag ``journal?table=trades``, all 6,572 rows, ids 1..6572):
114 reduce legs (bybit_1 97, bybit_2 9, bybit_portfolio 8); 81 pnl NULL; 33
superseded phantoms. 0 real settlements.

THE SETTLEMENT
--------------
For each PARTIALLY consumed allocation ``{parent_id, consumed, closed: false}``::

    pnl += compute_realized_pnl(entry = parent's ENTRY FILL vwap,
                                exit  = this reduce order's FILL vwap,
                                qty   = consumed,
                                direction = parent's direction) * contract value

net of the reduce order's fees pro-rated to the consumed share (the same
``close_fees_usd`` netting ``_sweep_local_pnl_for_unpriced`` applies to an
``exchange_fill`` exit). Fully consumed allocations are SKIPPED — their parent
row already books them, and booking them here would double count.

PROVENANCE: both prices must come from the exchange-fills store (venue fills,
joined by the venue order id). Then ``exit_price_source='exchange_fill'``
(MEASURED) and ``pnl_source='local_compute'`` (the arithmetic), exactly the
pair every other fills-priced row carries. Anything short of that REFUSES:
``pnl`` stays NULL, and the row is stamped ``reduce_settlement='unverified'``
with the reason. Nothing is estimated and nothing is fabricated.

This module is pure: it reads rows and fills it is handed and returns a plan.
The monitor sweep (``order_monitor._sweep_settle_intent_reduce_legs``) and the
backfill (``scripts/ops/backfill_intent_reduce_pnl.py``) both apply that plan.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from src.runtime.local_pnl import compute_realized_pnl, contract_value_usd_for

__all__ = [
    "SETTLED_BY",
    "SETTLED_STATE",
    "ABSORBED_STATE",
    "UNVERIFIED_STATE",
    "FILL_QTY_TOLERANCE",
    "Settlement",
    "is_settleable_reduce_leg",
    "plan_settlement",
    "apply_settlement",
    "fills_by_order_from_store",
    "FillsStoreUnavailable",
    "select_candidates",
]

#: ``notes.reduce_settled_by`` — who wrote the settlement.
SETTLED_BY = "reduce_leg_settlement"

#: ``notes.reduce_settlement`` values. A row carrying any of them has been
#: LOOKED at; one without has not.
SETTLED_STATE = "settled"            # pnl booked from two venue fills
ABSORBED_STATE = "absorbed_by_parent"  # every parent fully consumed: parent row books it
UNVERIFIED_STATE = "unverified"      # refused; pnl stays NULL, reason recorded

#: Relative tolerance between the reduce order's FILLED qty and the qty the
#: journal allocated to parents. Mirrors ``fills_pnl.QTY_TOLERANCE``. Beyond it
#: the journal shrank parents by units the venue never closed, so any figure
#: would price units that did not trade.
FILL_QTY_TOLERANCE = 0.05

_EPS = 1e-9


@dataclass
class Settlement:
    trade_id: int
    account_id: str
    symbol: str
    state: str
    reason: str = ""
    pnl: Optional[float] = None          # NET of the pro-rated reduce fees
    gross_pnl: Optional[float] = None
    fees_usd: Optional[float] = None
    pnl_percent: Optional[float] = None
    exit_price: Optional[float] = None   # the reduce order's fill vwap
    consumed_partial: float = 0.0
    consumed_full: float = 0.0
    parents: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _notes(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        out = json.loads(raw or "{}")
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _get(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _order_id(row: Any) -> Optional[str]:
    """The venue order id a journal row was placed under."""
    oid = _get(row, "broker_order_id")
    if oid:
        return str(oid)
    tid = _notes(_get(row, "notes")).get("trade_id")
    return str(tid) if tid else None


def is_settleable_reduce_leg(row: Any) -> bool:
    """A closed, non-backtest reduce AUDIT row with pnl NULL, not yet looked at."""
    if str(_get(row, "exit_reason") or "") != "intent_reduce_executed":
        return False
    if _get(row, "pnl") is not None:
        return False
    if str(_get(row, "status") or "") != "closed":
        return False
    if int(_get(row, "is_backtest") or 0):
        return False
    if str(_get(row, "reconcile_status") or "") == "superseded":
        return False
    return not _notes(_get(row, "notes")).get("reduce_settlement")


def _vwap(fills: Iterable[Mapping[str, Any]]) -> Optional[Dict[str, float]]:
    qty = px_qty = fee = 0.0
    for f in fills:
        q = _f(f.get("qty")) or 0.0
        p = _f(f.get("price")) or 0.0
        if q <= 0 or p <= 0:
            continue
        qty += q
        px_qty += p * q
        fee += _f(f.get("fee")) or 0.0
    if qty <= 0:
        return None
    return {"price": px_qty / qty, "qty": qty, "fee": fee}


def _ts(v: Any) -> Optional[float]:
    from datetime import datetime  # noqa: PLC0415

    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


#: A legacy reduce and the parent it fully consumed are written in the same
#: ``apply_intent_reduce_partial_close`` call, so their close stamps agree to
#: well under a second.
_LEGACY_SAME_CLOSE_S = 5.0


def _legacy_fully_consumed(row: Any, parent: Any, consumed: float) -> Optional[bool]:
    """Was a pre-``closed``-key allocation a FULL consumption of its parent?

    Allocations written before the ``closed`` key existed (81 of 104 on the
    live journal, 2026-10-11) say nothing about it, and reading the absence as
    "partial" double-counts: a fully consumed parent is closed with
    ``exit_reason='intent_reduce'`` at its full size and the local sweep books
    its pnl over those units (29 such allocations, e.g. reduce 4217 -> parent
    4162: 86,102.5 units already booked +998.79 on the parent). The legacy
    writer closed the parent IN THE SAME CALL without shrinking it, so all
    three hold: exit_reason ``intent_reduce``, size == consumed, and the same
    close time. ``None`` = parent row missing (caller refuses).
    """
    if parent is None:
        return None
    if str(_get(parent, "exit_reason") or "") != "intent_reduce":
        return False
    size = _f(_get(parent, "position_size")) or 0.0
    if abs(size - consumed) > 1e-6 * max(1.0, consumed):
        return False
    t_red = _ts(_get(row, "closed_at") or _get(row, "timestamp"))
    t_par = _ts(_get(parent, "closed_at"))
    if t_red is None or t_par is None:
        return True  # same size + intent_reduce close: the conservative call (books nothing)
    return abs(t_red - t_par) <= _LEGACY_SAME_CLOSE_S


def plan_settlement(
    row: Any,
    parents_by_id: Mapping[int, Any],
    fills_by_order: Mapping[str, List[Mapping[str, Any]]],
    *,
    contract_value: Optional[Callable[[str], float]] = None,
) -> Settlement:
    """What this reduce leg's pnl IS, from the fills — or why it cannot be said.

    Never raises on bad data; a malformed input is a refusal with a reason.
    """
    cvu_for = contract_value or contract_value_usd_for
    tid = int(_get(row, "id"))
    acct = str(_get(row, "account_id") or "")
    sym = str(_get(row, "symbol") or "")
    s = Settlement(trade_id=tid, account_id=acct, symbol=sym, state=UNVERIFIED_STATE)
    notes = _notes(_get(row, "notes"))

    allocs = notes.get("intent_reduce_allocations")
    if not isinstance(allocs, list):
        # The allocation list is the only record of WHICH parents (and how
        # much of each) the reduce closed. Without it there is no cost basis.
        s.reason = "no_allocations_in_notes"
        return s
    if not allocs:
        s.reason = "empty_allocations(no_parent_position)"
        return s

    partial, full = [], []
    for a in allocs:
        try:
            pid = int(a["parent_id"])
            consumed = float(a["consumed"])
        except (KeyError, TypeError, ValueError):
            s.reason = "malformed_allocation"
            return s
        if "closed" in a:
            is_full = bool(a["closed"])
        else:
            is_full = _legacy_fully_consumed(row, parents_by_id.get(pid), consumed)
            if is_full is None:
                s.reason = f"legacy_allocation_parent_{pid}_not_found"
                return s
        (full if is_full else partial).append((pid, consumed))
    s.consumed_full = sum(c for _, c in full)
    s.consumed_partial = sum(c for _, c in partial)

    oid = notes.get("trade_id") or _get(row, "broker_order_id")
    red = _vwap(fills_by_order.get(str(oid), ())) if oid else None
    if red is None:
        s.reason = "no_reduce_fill_in_store"
        return s
    s.exit_price = round(red["price"], 10)
    allocated = s.consumed_partial + s.consumed_full
    if allocated <= 0 or abs(red["qty"] - allocated) > FILL_QTY_TOLERANCE * allocated:
        s.reason = (f"fill_qty_mismatch(filled={red['qty']:g}, "
                    f"allocated={allocated:g})")
        return s

    if not partial:
        s.state = ABSORBED_STATE
        s.reason = "all_parents_fully_consumed"
        return s

    gross = 0.0
    notional = 0.0
    cvu = cvu_for(sym) or 1.0
    for pid, consumed in partial:
        parent = parents_by_id.get(pid)
        if parent is None:
            s.reason = f"parent_{pid}_not_found"
            return s
        poid = _order_id(parent)
        pent = _vwap(fills_by_order.get(poid, ())) if poid else None
        if pent is None:
            s.reason = f"no_entry_fill_for_parent_{pid}"
            return s
        leg = compute_realized_pnl(
            entry_price=pent["price"], exit_price=red["price"], qty=consumed,
            direction=_get(parent, "direction"), contract_value_usd=cvu,
        )
        if leg is None:
            s.reason = f"unpriceable_parent_{pid}"
            return s
        gross += leg
        notional += pent["price"] * consumed * cvu
        s.parents.append({"parent_id": pid, "consumed": consumed,
                          "entry_fill": round(pent["price"], 10),
                          "pnl": round(leg, 4)})

    fees = red["fee"] * (s.consumed_partial / red["qty"])
    s.gross_pnl = round(gross, 4)
    s.fees_usd = round(fees, 6)
    s.pnl = round(gross - fees, 4)
    s.pnl_percent = round(s.pnl / notional * 100, 4) if notional > 0 else None
    s.state = SETTLED_STATE
    s.reason = ("partial_allocations_only" if full else "all_allocations_partial")
    return s


def apply_settlement(db: Any, row: Any, s: Settlement, *, now_iso: str) -> Dict[str, Any]:
    """Write one plan through ``db.update_trade``. Returns the update dict.

    Never passes ``status`` (no close ping, no cost re-estimate): the row is
    already closed; this only fills in what its close could not know.
    """
    notes = _notes(_get(row, "notes"))
    notes["reduce_settlement"] = s.state
    notes["reduce_settlement_reason"] = s.reason
    notes["reduce_settled_by"] = SETTLED_BY
    notes["reduce_settled_at"] = now_iso
    updates: Dict[str, Any] = {}
    if s.state == SETTLED_STATE:
        notes["pnl_source"] = "local_compute"
        notes["exit_price_source"] = "exchange_fill"
        notes["close_fees_usd"] = s.fees_usd
        notes["pnl_net_of_close_fees"] = True
        notes["reduce_settlement_gross_pnl"] = s.gross_pnl
        notes["reduce_settlement_parents"] = s.parents
        updates.update({
            "pnl": s.pnl,
            "pnl_percent": s.pnl_percent,
            "exit_price": s.exit_price,
        })
    updates["notes"] = json.dumps(notes, ensure_ascii=False, default=str)
    db.update_trade(int(_get(row, "id")), updates)
    return updates


_CANDIDATE_SQL = (
    "SELECT * FROM trades "
    " WHERE exit_reason = 'intent_reduce_executed' "
    "   AND status = 'closed' "
    "   AND pnl IS NULL "
    "   AND COALESCE(is_backtest, 0) = 0 "
    "   AND COALESCE(reconcile_status, '') != 'superseded' "
    "   AND COALESCE(notes, '') NOT LIKE '%\"reduce_settlement\":%' "
)


def select_candidates(
    conn: Any, *, window_days: Optional[int] = None, limit: Optional[int] = None,
    ids: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """The unsettled reduce legs, their parent rows, and every order id needed.

    ``window_days`` keys on ``closed_at`` (the monitor sweep's bound); ``None``
    is the whole journal (the backfill). Returns ``{"rows", "parents_by_id",
    "order_ids"}``; rows are dicts.
    """
    conn.row_factory = sqlite3.Row
    sql = _CANDIDATE_SQL
    args: List[Any] = []
    if window_days is not None:
        sql += " AND datetime(COALESCE(closed_at, created_at)) >= datetime('now', ?) "
        args.append(f"-{int(window_days)} days")
    id_list = [int(i) for i in ids] if ids else []
    if id_list:
        sql += f" AND id IN ({','.join('?' * len(id_list))}) "
        args.extend(id_list)
    sql += " ORDER BY id ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    rows = [r for r in rows if is_settleable_reduce_leg(r)]
    pids = set()
    for r in rows:
        for a in _notes(r.get("notes")).get("intent_reduce_allocations") or ():
            try:
                pids.add(int(a["parent_id"]))
            except (KeyError, TypeError, ValueError):
                continue
    parents: Dict[int, Dict[str, Any]] = {}
    pl = sorted(pids)
    for i in range(0, len(pl), 500):
        chunk = pl[i:i + 500]
        for p in conn.execute(
            "SELECT id, direction, broker_order_id, notes, account_id, symbol, "
            "exit_reason, position_size, closed_at "
            f"FROM trades WHERE id IN ({','.join('?' * len(chunk))})", chunk,
        ).fetchall():
            parents[int(p["id"])] = dict(p)
    order_ids = {_notes(r.get("notes")).get("trade_id") for r in rows}
    order_ids |= {_order_id(p) for p in parents.values()}
    return {"rows": rows, "parents_by_id": parents,
            "order_ids": {o for o in order_ids if o}}


class FillsStoreUnavailable(RuntimeError):
    """The exchange-fills store could not be opened: we did NOT look.

    Distinct from "looked, no fill for this order" on purpose. Collapsing the
    two stamped rows ``unverified`` without reading the real store: the first
    VM dry-run (issue #17598, 2026-10-11) ran from a system-action shell with no
    DATA_DIR, resolved ``<repo>/runtime_state/`` (BL-20260717-FILLS-STORE-PATH-
    SPLIT), found "0 of 167" fills and planned 76 refusals that an apply would
    have written.
    """


def fills_by_order_from_store(
    order_ids: Iterable[str], *, conn_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Read the stored venue fills for *order_ids* (read-only, local SQLite).

    Raises :class:`FillsStoreUnavailable` when the store file does not exist
    (we could not look). ``{}`` means we looked and no order matched.
    """
    ids = sorted({str(o) for o in order_ids if o})
    if not ids:
        return {}
    if conn_factory is not None:
        conn = conn_factory()
    else:
        from src.runtime.exchange_fills_store import get_fills_db_path  # noqa: PLC0415

        path = get_fills_db_path()
        if not path.exists():
            raise FillsStoreUnavailable(f"exchange fills store absent at {path}")
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out: Dict[str, List[Dict[str, Any]]] = {}
    try:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = ("SELECT order_id, price, qty, fee FROM exchange_fills "
                 f"WHERE order_id IN ({','.join('?' * len(chunk))})")
            for oid, price, qty, fee in conn.execute(q, chunk).fetchall():
                out.setdefault(str(oid), []).append(
                    {"price": price, "qty": qty, "fee": fee})
    finally:
        conn.close()
    return out
