"""Post-only maker entry at the touch, with a 5-minute fallback to the Market entry (DESK-MAKER-FILLS probe b).

Why this exists
---------------
Every Bybit entry this system has ever placed is a Market order (1,411 measured fills, all taker, 5.5 bps a
side; row COST-STACK-BYBIT-TAKER-FEE). The registered replay RQ-20261027-a3f1-01 (PASS at its threshold,
docs/research/desk-maker-fills-2026-10-27.md) measured that a post-only limit at the near touch, crossed as
taker after 5 minutes if unfilled, beats the Market entry by +2.03 bps per entry on Bybit's own trade prints.
Two things the replay cannot see decide whether that survives: whether the Bybit DEMO venue matches a resting
order like mainnet does, and the real maker fee. This module is the probe that measures both, on the
``claude_desk`` leg on a demo/paper Bybit account only.

What it decides
---------------
* :func:`resolve_entry_order` -- ``post_only_touch`` ONLY when the leg declares
  ``entry_order: post_only_touch`` in ``config/strategies.yaml`` AND the account is Bybit, derivatives
  (linear/inverse), ``demo`` true AND ``account_class == "paper"``, AND the order opens (not reduce-only).
  Anything else is ``market`` (today's path, byte-for-byte). A real-money account can never receive it, whatever
  the leg says. The field is a declared per-leg value (``market`` | ``post_only_touch``), not a default-off flag.
* :func:`apply_post_only` -- turns the entry kwargs into ``orderType: Limit``, ``timeInForce: PostOnly`` at the
  near touch (Buy at ``bid1Price``, Sell at ``ask1Price``); the attached ``stopLoss`` / ``takeProfit`` (and the
  Partial-mode fields) are kept. The Market kwargs it replaces are kept verbatim as the fallback.
* :func:`sweep_maker_entries` -- runs in the monitor's reconciliation tick, BEFORE the forward reconciler, over
  journal rows whose ``notes.maker_probe.state`` is ``resting`` (a row closed while its limit rests has the
  limit cancelled, so a late fill cannot open an untracked position):
    - filled (fully) -> records ``is_maker`` / ``exec_fee`` / ``fee_rate`` from the venue's executions;
    - post-only reject (terminal, zero fill) -> sends the stored Market kwargs at once;
    - still resting after ``FALLBACK_SECONDS`` with zero fill -> cancel, then the Market kwargs;
    - partially filled after ``FALLBACK_SECONDS`` -> cancel the remainder and shrink ``position_size`` to the
      filled qty (no top-up: the position is smaller than sized, never larger).
  A fallback re-points ``notes.trade_id`` to the Market order id, so the reconciler follows the order that holds
  the position (otherwise it would orphan the row as a terminal zero-fill).

ROLLBACK: delete ``entry_order: post_only_touch`` from the ``claude_desk`` block in ``config/strategies.yaml``
(the leg falls back to ``market``). Rows already resting are still resolved by the sweep.
"""
from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

MARKET = "market"
POST_ONLY_TOUCH = "post_only_touch"
ENTRY_ORDERS = (MARKET, POST_ONLY_TOUCH)
FALLBACK_SECONDS = 300          # registered with the replay: W = 5 min
NOTES_KEY = "maker_probe"
PROBE_VERSION = 1

_LIVE = frozenset({"new", "partiallyfilled", "untriggered", "active", "created"})


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def leg_entry_order(strategy: Optional[str], *, cfg_loader: Optional[Callable[[str], dict]] = None) -> str:
    """The leg's declared ``entry_order``; ``market`` when absent, unknown, or the leg cannot be read."""
    if not strategy:
        return MARKET
    try:
        if cfg_loader is None:
            from src.strategy_registry import _strategy_cfg as cfg_loader  # noqa: N813
        cfg = cfg_loader(str(strategy)) or {}
    except Exception:  # noqa: BLE001 -- an unreadable leg config keeps today's Market path
        return MARKET
    val = str(cfg.get("entry_order") or MARKET).strip().lower()
    if val not in ENTRY_ORDERS:
        logger.warning("maker_entry: leg %s declares unknown entry_order %r; using market", strategy, val)
        return MARKET
    return val


def resolve_entry_order(order: Dict[str, Any], account_cfg: Dict[str, Any], category: str,
                        *, cfg_loader: Optional[Callable[[str], dict]] = None) -> Tuple[str, str]:
    """(entry_order, reason). ``post_only_touch`` only on a demo/paper Bybit derivatives OPEN for a declaring leg."""
    if order.get("reduce_only"):
        return MARKET, "reduce_only"
    if str(account_cfg.get("exchange") or "bybit").lower() != "bybit":
        return MARKET, "not_bybit"
    if category not in ("linear", "inverse"):
        return MARKET, "not_derivatives"
    if leg_entry_order(order.get("strategy"), cfg_loader=cfg_loader) != POST_ONLY_TOUCH:
        return MARKET, "leg_market"
    # The real-money fence. account_class defaults to real_money in the coordinator's cfg, so a missing
    # field refuses; `demo` must be explicitly true.
    if str(account_cfg.get("account_class") or "real_money").lower() != "paper":
        return MARKET, "not_paper_account"
    if not _truthy(account_cfg.get("demo")):
        return MARKET, "not_demo_account"
    return POST_ONLY_TOUCH, "leg_post_only_touch"


def touch_price(client: Any, category: str, symbol: str, side: str) -> Optional[float]:
    """The near touch: best bid for a Buy, best ask for a Sell. ``None`` when the ticker cannot be read."""
    try:
        t = client.get_tickers(category=category, symbol=symbol) or {}
        row = ((t.get("result") or {}).get("list") or [{}])[0]
        px = float(row.get("bid1Price" if side == "Buy" else "ask1Price") or 0)
        return px if px > 0 else None
    except Exception as exc:  # noqa: BLE001 -- no touch means no probe, never a broken entry
        logger.warning("maker_entry: touch read failed for %s: %s", symbol, exc)
        return None


def apply_post_only(kwargs: Dict[str, Any], price_str: str) -> Dict[str, Any]:
    """Mutate the Market entry kwargs into a post-only limit; return the Market kwargs it replaced."""
    fallback = copy.deepcopy(kwargs)
    kwargs["orderType"] = "Limit"
    kwargs["price"] = price_str
    kwargs["timeInForce"] = "PostOnly"
    return fallback


def probe_notes(*, limit_price: float, touch: float, fallback_kwargs: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """The journal's ``notes.maker_probe`` block for a newly resting entry."""
    return {NOTES_KEY: {
        "version": PROBE_VERSION, "state": "resting", "entry_order": POST_ONLY_TOUCH, "reason": reason,
        "limit_price": limit_price, "touch": touch,
        "placed_at": datetime.now(timezone.utc).isoformat(), "fallback_after_s": FALLBACK_SECONDS,
        "fallback_kwargs": fallback_kwargs,
    }}


def _parse_ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _executions(client: Any, category: str, symbol: str, order_id: str) -> Dict[str, Any]:
    """isMaker / execFee / feeRate summed over the order's executions; ``{"fee_read": "unread"}`` on failure."""
    try:
        r = client.get_executions(category=category, symbol=symbol, orderId=str(order_id)) or {}
        rows = (r.get("result") or {}).get("list") or []
    except Exception as exc:  # noqa: BLE001
        return {"fee_read": "unread", "fee_read_error": str(exc)[:160]}
    if not rows:
        return {"fee_read": "no_executions"}
    fee = sum(float(x.get("execFee") or 0) for x in rows)
    rates = sorted({str(x.get("feeRate")) for x in rows if x.get("feeRate") is not None})
    makers = {_truthy(x.get("isMaker")) for x in rows}
    return {"fee_read": "read", "exec_fee": fee, "fee_rates": rates,
            "is_maker": (makers.pop() if len(makers) == 1 else "mixed"), "n_executions": len(rows)}


def _place_fallback(client: Any, fb: Dict[str, Any]) -> Tuple[Optional[str], str]:
    try:
        resp = client.place_order(**fb) or {}
    except Exception as exc:  # noqa: BLE001
        return None, f"raised: {str(exc)[:160]}"
    if resp.get("retCode") not in (0, "0", None):
        return None, f"retCode={resp.get('retCode')} {resp.get('retMsg') or ''}".strip()
    oid = (resp.get("result") or {}).get("orderId")
    return (str(oid), "placed") if oid else (None, "no orderId")


def resolve_row(row: Dict[str, Any], notes: Dict[str, Any], *, client: Any, cfg: Dict[str, Any],
                order_status: Callable[[Dict[str, Any], str], Optional[Dict[str, Any]]],
                category: str, now: datetime) -> Optional[Dict[str, Any]]:
    """The ``update_trade`` dict that resolves one resting row this tick, or ``None`` to leave it."""
    probe = notes.get(NOTES_KEY) or {}
    tid = str(notes.get("trade_id") or "")
    if not tid or client is None:
        return None
    st = order_status(cfg, tid)
    if st is None:
        return None                                  # could not look: retry next tick
    status = str(st.get("status") or "").lower()
    filled = float(st.get("filled_qty") or 0.0)
    placed = _parse_ts(probe.get("placed_at")) or _parse_ts(row.get("created_at"))
    age = (now - placed).total_seconds() if placed else 0.0
    symbol = str(row.get("symbol") or "")
    stamp = now.isoformat()

    if str(row.get("status") or "open") != "open":
        # The journal row was closed (e.g. by the exit loop) while the limit still rested: cancel it so a
        # late fill cannot open a position no row tracks. A fill that already happened is left to the
        # reverse reconciler (adopt/alert) and recorded loudly here.
        if status in _LIVE:
            try:
                client.cancel_order(category=category, symbol=symbol, orderId=tid)
            except Exception as exc:  # noqa: BLE001
                logger.warning("maker_entry: cancel of %s on a closed row failed: %s (retry)", tid, exc)
                return None
            probe.update(state="cancelled_row_not_open", resolved_at=stamp)
        else:
            probe.update(state="row_not_open_order_terminal", resolved_at=stamp, filled_qty=filled)
            if filled > 0:
                logger.error("maker_entry: %s %s limit %s filled after its row closed (qty %s)",
                             row.get("account_id"), symbol, tid, filled)
        notes[NOTES_KEY] = probe
        return {"notes": json.dumps(notes)}
    if status not in _LIVE and filled > 0:           # filled (or partially filled then cancelled by the venue)
        probe.update(state="filled_maker", resolved_at=stamp, filled_qty=filled,
                     **_executions(client, category, symbol, tid))
        notes[NOTES_KEY] = probe
        upd: Dict[str, Any] = {"notes": json.dumps(notes)}
        if filled < float(row.get("position_size") or 0) - 1e-12:
            upd["position_size"] = filled
        return upd
    if status in _LIVE and age < FALLBACK_SECONDS:
        return None                                  # still inside the window
    if status in _LIVE:                              # window expired: cancel what rests
        try:
            client.cancel_order(category=category, symbol=symbol, orderId=tid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("maker_entry: cancel of %s failed: %s (retry next tick)", tid, exc)
            return None
        st = order_status(cfg, tid) or {}
        filled = float(st.get("filled_qty") or 0.0)
        if filled > 0:                               # partly (or fully) filled before the cancel landed
            probe.update(state="partial_maker_remainder_cancelled", resolved_at=stamp, filled_qty=filled,
                         **_executions(client, category, symbol, tid))
            notes[NOTES_KEY] = probe
            return {"notes": json.dumps(notes), "position_size": filled}
        why = "window_expired"
    else:
        why = "post_only_reject_or_cancelled"        # terminal, zero fill
    fb = probe.get("fallback_kwargs") or {}
    new_id, outcome = _place_fallback(client, fb)
    probe.update(resolved_at=stamp, fallback_reason=why, limit_order_id=tid, fallback_outcome=outcome)
    if new_id is None:
        probe["state"] = "fallback_failed"           # the reconciler then orphans the zero-fill row: no position
        notes[NOTES_KEY] = probe
        logger.error("maker_entry: Market fallback for %s %s failed: %s", row.get("account_id"), symbol, outcome)
        return {"notes": json.dumps(notes)}
    probe.update(state="fallback_market", market_order_id=new_id)
    notes[NOTES_KEY] = probe
    notes["trade_id"] = new_id                       # the reconciler follows the order holding the position
    return {"notes": json.dumps(notes)}


def sweep_maker_entries(db: Any, *, build_client: Callable[[str], Tuple[Any, Optional[Dict[str, Any]]]],
                        order_status: Callable[[Dict[str, Any], str], Optional[Dict[str, Any]]],
                        now: Optional[datetime] = None) -> Dict[str, int]:
    """Resolve every open row whose maker probe is still resting. Best-effort; never raises."""
    summary = {"resting": 0, "resolved": 0, "errors": 0}
    now = now or datetime.now(timezone.utc)
    try:
        conn = db.connect()
        try:
            conn.row_factory = __import__("sqlite3").Row
            rows = [dict(r) for r in conn.execute(
                "SELECT id, account_id, symbol, notes, created_at, position_size, status FROM trades "
                "WHERE COALESCE(is_backtest,0)=0 AND notes LIKE ?",
                ('%"maker_probe"%',)).fetchall()]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("maker_entry: open-row read failed: %s", exc)
        summary["errors"] += 1
        return summary
    from src.units.accounts.execute import _bybit_category
    clients: Dict[str, Tuple[Any, Optional[Dict[str, Any]]]] = {}
    for row in rows:
        try:
            notes = json.loads(row.get("notes") or "{}")
            if (notes.get(NOTES_KEY) or {}).get("state") != "resting":
                continue
            summary["resting"] += 1
            aid = str(row.get("account_id") or "")
            if aid not in clients:
                clients[aid] = build_client(aid)
            client, cfg = clients[aid]
            if cfg is None:
                continue
            upd = resolve_row(row, notes, client=client, cfg=cfg, order_status=order_status,
                              category=_bybit_category(cfg), now=now)
            if upd:
                db.update_trade(row["id"], upd)
                summary["resolved"] += 1
        except Exception as exc:  # noqa: BLE001 -- one bad row never stops the sweep
            logger.warning("maker_entry: row %s failed: %s", row.get("id"), exc)
            summary["errors"] += 1
    return summary
