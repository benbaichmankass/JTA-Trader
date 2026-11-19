"""Post-only maker TIME-STOP exit at the mid, with a 1-minute market fallback (D9-MAKER-EXIT-BUILD).

Why this exists
---------------
``ml_entry``'s 24 h time stop (``max_hold``, ``claude_desk.max_hold_verdict``) has always been closed with a
reduce-only Market order (``execute.close_open_position``). Two registered replays passed for working that close
post-only at the mid with a 1-minute market fallback:

* RQ-20261118-04a5-05 (run 44400344151): +0.0060 R per time-stop exit, deflated CI [+0.0034, +0.0087],
  n 2,786 on 53 symbols, fill rate 0.754;
* RQ-20261118-e8a1-01 (run 44422089383, fresh window): +0.0066 R per exit, CI [+0.0059, +0.0073], n 16,764 on
  60 symbols, fill 82.8%.

What the harness assumed, and the price this module rests at
------------------------------------------------------------
``scripts/research/ml_entry_maker_replay.py::delta_f`` models the book at T as a ONE-TICK spread around ``p``,
the close of the minute ending at T (bid = p - tick/2, ask = p + tick/2), and the ``mid`` arm rests AT ``p``:
an on-grid price (a traded price), one half-tick inside the modelled touch. A fill needs a 1m print one tick
THROUGH the resting price inside (T, T+1m]; otherwise the market at T+1m.

A real book cannot rest half a tick inside a one-tick spread. The closest realisable reading of "rest at the mid"
is the venue mid ``(bid1 + ask1) / 2`` rounded to the tick on the PASSIVE side (a Sell rounds UP, a Buy rounds
DOWN), so the order can never cross and be refused by post-only:

* spread > 1 tick -> the order rests inside the spread (the harness's "inside the touch" case);
* spread == 1 tick -> the passive rounding lands on the near touch (the ask for a Sell). That is where the
  harness's ``p`` sits whenever the last trade printed on our side of the book.

The live demo exits measure the realised fill rate against the harness's 0.754 / 0.828 (``notes.maker_exit``
records bid, ask, tick and the limit). That comparison is the parity check.

The fence (staging, PR 1)
-------------------------
:func:`resolve_exit_order` returns ``post_only_mid`` ONLY when all of these hold:

* the close reason is the time stop (``max_hold``; protective reasons are never worked passively);
* the leg declares ``time_stop_exit_order: post_only_mid`` in ``config/strategies.yaml``;
* the account is Bybit derivatives (linear/inverse) and not ``mode: dry_run``;
* the account is on the DEMO FLOOR: ``account_class == "paper"``, ``demo`` true, and not a Stage-2 portfolio
  mirror (``paper_role: portfolio`` mirrors real money and moves with it in PR 2).

Anything else returns ``market``, which is today's path byte for byte. The field is a declared per-leg value
(``market`` | ``post_only_mid``) in the pattern of ``maker_entry.entry_order``. It is not a default-off flag.
PR 2, after 1-2 clean demo exits, is a one-line widening of :func:`account_admitted`.

The state machine (``notes.maker_exit``)
----------------------------------------
The exit pass owns it (:func:`exit_step`, called from ``order_monitor._apply_update`` once per pass while the
time stop keeps firing). The venue SL/TP stay resting throughout, so the position is never unprotected:

* no block -> place a reduce-only post-only Limit at the passive mid; ``resting``. A place refusal (retCode,
  post-only reject at the door, no ticker) -> ``place_failed`` and the Market close goes out in the SAME pass.
* ``resting`` and fully filled -> ``filled_maker``; the caller closes the journal row at the limit's own fill
  price (no Market order is sent) and cancels the row's tracked SL/TP legs, as ``close_open_position`` does.
* ``resting`` and live inside 60 s -> wait (the pass sends nothing for this leg).
* ``resting`` and live after 60 s -> cancel, re-read the fill, then the Market close for the REMAINDER only
  (position - filled); the exit price is the qty-weighted blend.
* ``resting`` and terminal with zero fill (a post-only reject after placement, or the venue cancelled it) ->
  the Market close at once, UNLESS the position is already flat on the venue: then a stop or TP filled during
  the window. The block becomes ``released_venue_flat`` and the forward reconciler closes the row on the stop's
  own price (a Market close there would be refused with "position is zero" and recorded as ``max_hold``).
* status unreadable -> wait, up to :data:`UNREAD_GIVE_UP_S`; then cancel blind and send the Market close.

The reconciliation tick (:func:`sweep_maker_exits`, BEFORE the forward reconciler) handles the rest:

* a row that closed while its limit still rests (a stop, a desk close) -> cancel the limit;
* a row still ``resting`` past :data:`ABANDON_S` (the exit pass stopped visiting it, e.g. monitor-blind) ->
  cancel the limit, ``abandoned``, and the ordinary paths own the row again.

:func:`reconciler_defers` keeps the forward reconciler off a ``resting`` row, bounded by :data:`ABANDON_S`.
Without it, a full maker fill would be closed as ``reconciler_filled`` and lose its ``max_hold`` label.

ROLLBACK: delete ``time_stop_exit_order: post_only_mid`` from ``ml_entry`` in ``config/strategies.yaml`` (the
leg returns to the taker Market exit). Rows already resting are still resolved by the exit pass and the sweep.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

MARKET = "market"
POST_ONLY_MID = "post_only_mid"
EXIT_ORDERS = (MARKET, POST_ONLY_MID)
LEG_FIELD = "time_stop_exit_order"
TIME_STOP_REASONS = frozenset({"max_hold"})
FALLBACK_SECONDS = 60          # registered with the replay: --exit-w-min 1
UNREAD_GIVE_UP_S = 300         # status unreadable this long -> cancel blind, Market close
ABANDON_S = 600                # a resting block nobody resolved: the sweep cancels it, ordinary paths own the row
NOTES_KEY = "maker_exit"
VERSION = 1

_LIVE = frozenset({"new", "partiallyfilled", "untriggered", "active", "created"})
_EPS = 1e-12

# Exit-pass actions (:class:`Step.action`).
A_MARKET = "market"            # today's path: the Market close for the full row
A_PLACED = "placed"            # a limit was placed this pass; send nothing else for this leg
A_WAIT = "wait"                # resting inside the window, or could not look: send nothing
A_MAKER_FILLED = "maker_filled"
A_FALLBACK = "fallback"        # the Market close for ``qty`` (the unfilled remainder)
A_VENUE_FLAT = "venue_flat"    # a stop/TP flattened it during the window: the reconciler owns the close


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def decode_notes(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        d = json.loads(raw or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def block_of(raw_notes: Any) -> Dict[str, Any]:
    b = decode_notes(raw_notes).get(NOTES_KEY)
    return b if isinstance(b, dict) else {}


# --- the fence ------------------------------------------------------------------------------------------------

_LEG_CACHE: Dict[str, Any] = {"mtime": None, "legs": {}}


def full_leg_cfg(strategy: str, *, path: Optional[str] = None) -> Dict[str, Any]:
    """The leg's WHOLE block from ``config/strategies.yaml`` (mtime-cached); ``{}`` when absent or unreadable.

    Deliberately NOT ``src.strategy_registry._strategy_cfg``: that returns only name / service / model /
    signal_prefixes / execution, so a leg field read through it is always absent (it is why
    ``maker_entry.leg_entry_order`` reads ``market`` for a leg that declares ``post_only_touch``)."""
    from pathlib import Path
    p = Path(path) if path else Path(__file__).resolve().parents[3] / "config" / "strategies.yaml"
    try:
        mtime = p.stat().st_mtime
        if path is None and _LEG_CACHE["mtime"] == mtime:
            legs = _LEG_CACHE["legs"]
        else:
            import yaml
            doc = yaml.safe_load(p.read_text()) or {}
            raw = doc.get("strategies") or {}
            legs = {str(k): v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}
            if path is None:
                _LEG_CACHE.update(mtime=mtime, legs=legs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("maker_exit: strategies.yaml read failed: %s", exc)
        legs = _LEG_CACHE["legs"]
    return dict(legs.get(str(strategy)) or {})


def leg_exit_order(strategy: Optional[str], *, cfg_loader: Optional[Callable[[str], dict]] = None) -> str:
    """The leg's declared ``time_stop_exit_order``; ``market`` when absent, unknown, or unreadable."""
    if not strategy:
        return MARKET
    try:
        cfg = (cfg_loader or full_leg_cfg)(str(strategy)) or {}
    except Exception:  # noqa: BLE001 -- an unreadable leg config keeps today's Market path
        return MARKET
    val = str(cfg.get(LEG_FIELD) or MARKET).strip().lower()
    if val not in EXIT_ORDERS:
        logger.warning("maker_exit: leg %s declares unknown %s %r; using market", strategy, LEG_FIELD, val)
        return MARKET
    return val


_FENCE_KEYS = ("account_class", "demo", "paper_role")


def _declared_account(account_id: Optional[str], *, path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The account's own block in ``config/accounts.yaml`` (via the canonical loader); ``None`` when unreadable."""
    if not account_id:
        return None
    try:
        from src.config.accounts_loader import load_accounts_dict
        errors: list = []
        accs = load_accounts_dict(path, errors=errors) if path else load_accounts_dict(errors=errors)
        if errors and not accs:
            return None
        blk = (accs or {}).get(str(account_id))
        return blk if isinstance(blk, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("maker_exit: accounts.yaml read failed for %s: %s", account_id, exc)
        return None


def fence_view(account_cfg: Dict[str, Any], *, accounts_path: Optional[str] = None) -> Dict[str, Any]:
    """``account_cfg`` with the fence fields filled from ``config/accounts.yaml`` where the runtime cfg omits them.

    The monitor's ``_build_account_client`` cfg carries ``demo`` but not ``account_class`` / ``paper_role``; the
    YAML is their source of truth. A field neither carries stays absent, and the fence then refuses."""
    view = dict(account_cfg or {})
    if all(k in view for k in _FENCE_KEYS):
        return view
    declared = _declared_account(view.get("account_id"), path=accounts_path)
    if declared is None:
        view["_fence_read"] = "unreadable"
        return view
    for k in _FENCE_KEYS:
        if k not in view and k in declared:
            view[k] = declared[k]
    return view


def account_admitted(account_cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """The staging fence: the demo floor only (PR 1). PR 2 widens THIS function to the real-money accounts.

    ``account_class`` defaults to real money when missing, and ``demo`` must be explicitly true, so a missing
    field refuses. A Stage-2 portfolio mirror (``paper_role: portfolio``) is excluded: it must execute exactly as
    its real-money twin does, so it moves with the widening."""
    if account_cfg.get("_fence_read") == "unreadable":
        return False, "account_unreadable"
    if str(account_cfg.get("account_class") or "real_money").lower() != "paper":
        return False, "not_paper_account"
    if not _truthy(account_cfg.get("demo")):
        return False, "not_demo_account"
    if str(account_cfg.get("paper_role") or "").lower() == "portfolio":
        return False, "portfolio_mirror"
    return True, "demo_floor"


def resolve_exit_order(strategy: Optional[str], reason: Optional[str], account_cfg: Optional[Dict[str, Any]],
                       *, cfg_loader: Optional[Callable[[str], dict]] = None,
                       accounts_path: Optional[str] = None) -> Tuple[str, str]:
    """(exit_order, why). ``post_only_mid`` only for a declaring leg's time stop on a fenced-in Bybit account."""
    cfg = account_cfg or {}
    if str(reason or "") not in TIME_STOP_REASONS:
        return MARKET, "not_time_stop"
    if str(cfg.get("exchange") or "").lower() != "bybit":
        return MARKET, "not_bybit"
    if str(cfg.get("mode") or "live").lower() in ("dry_run", "dry", "dry-run"):
        return MARKET, "dry_run"
    try:
        from src.units.accounts.execute import _bybit_category
        category = _bybit_category(cfg)
    except Exception:  # noqa: BLE001
        return MARKET, "category_unreadable"
    if category not in ("linear", "inverse"):
        return MARKET, "not_derivatives"
    if leg_exit_order(strategy, cfg_loader=cfg_loader) != POST_ONLY_MID:
        return MARKET, "leg_market"
    ok, why = account_admitted(fence_view(cfg, accounts_path=accounts_path))
    if not ok:
        return MARKET, why
    return POST_ONLY_MID, "leg_post_only_mid"


# --- pricing --------------------------------------------------------------------------------------------------

def passive_mid(bid: float, ask: float, tick: Decimal, close_side: str) -> Optional[Decimal]:
    """The venue mid rounded to ``tick`` AWAY from the aggressive side: a Sell rounds up, a Buy rounds down.

    One-tick spread -> the near touch (ask for a Sell, bid for a Buy). Wider -> inside the spread. ``None`` on a
    locked/crossed or unreadable book (no passive price exists)."""
    try:
        b, a = Decimal(str(bid)), Decimal(str(ask))
    except Exception:  # noqa: BLE001
        return None
    if b <= 0 or a <= 0 or a <= b or tick <= 0:
        return None
    mid = (b + a) / 2
    rounding = ROUND_CEILING if close_side == "Sell" else ROUND_FLOOR
    px = ((mid / tick).to_integral_value(rounding=rounding) * tick).quantize(tick)
    if close_side == "Sell" and px <= b:
        return None
    if close_side == "Buy" and px >= a:
        return None
    return px


def _book(client: Any, category: str, symbol: str) -> Tuple[Optional[float], Optional[float]]:
    try:
        t = client.get_tickers(category=category, symbol=symbol) or {}
        row = ((t.get("result") or {}).get("list") or [{}])[0]
        bid, ask = float(row.get("bid1Price") or 0), float(row.get("ask1Price") or 0)
        return (bid, ask) if bid > 0 and ask > 0 else (None, None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("maker_exit: ticker read failed for %s: %s", symbol, exc)
        return None, None


# --- venue actions --------------------------------------------------------------------------------------------

def place_resting_exit(client: Any, account_cfg: Dict[str, Any], *, symbol: str, direction: str, qty: float,
                       now: Optional[datetime] = None) -> Dict[str, Any]:
    """Place the reduce-only post-only Limit; return the ``notes.maker_exit`` block (``resting`` or ``place_failed``).

    The kwargs mirror ``close_open_position``'s Bybit branch (category, symbol, close side, snapped qty,
    ``reduceOnly``, ``positionIdx``) with ``orderType: Limit``, ``timeInForce: PostOnly`` and the price."""
    from src.runtime import bybit_position_mode
    from src.units.accounts.execute import _bybit_category
    from src.units.accounts.precision import get_tick_size
    from src.units.accounts.qty_legalize import snap_artifact_qty

    stamp = (now or _now()).isoformat()
    close_side = "Sell" if str(direction).lower() == "long" else "Buy"
    block: Dict[str, Any] = {"v": VERSION, "state": "place_failed", "side": close_side, "placed_at": stamp,
                             "fallback_after_s": FALLBACK_SECONDS}
    try:
        category = _bybit_category(account_cfg)
        bid, ask = _book(client, category, symbol)
        if bid is None:
            block["why"] = "no_ticker"
            return block
        tick = get_tick_size(client, symbol, category)
        px = passive_mid(bid, ask, tick, close_side)
        block.update(bid=bid, ask=ask, tick=str(tick))
        if px is None:
            block["why"] = "no_passive_price"
            return block
        _q, qty_str, _state = snap_artifact_qty(qty, account_cfg=account_cfg, symbol=symbol, client=client)
        kwargs = {"category": category, "symbol": symbol, "side": close_side, "orderType": "Limit",
                  "qty": qty_str, "price": str(px), "timeInForce": "PostOnly", "reduceOnly": True}
        bybit_position_mode.apply_position_idx(kwargs, account_cfg.get("account_id"), symbol, direction)
        resp = client.place_order(**kwargs) or {}
    except Exception as exc:  # noqa: BLE001 -- a failed post is a Market close, never a broken exit
        block["why"] = f"raised: {str(exc)[:120]}"
        return block
    if resp.get("retCode") not in (0, "0", None):
        block["why"] = f"retCode={resp.get('retCode')} {str(resp.get('retMsg') or '')[:80]}".strip()
        return block
    oid = (resp.get("result") or {}).get("orderId")
    if not oid:
        block["why"] = "no orderId"
        return block
    block.update(state="resting", limit_order_id=str(oid), limit_price=float(px), qty=float(qty))
    return block


def cancel_limit(client: Any, category: str, symbol: str, order_id: str) -> bool:
    """Cancel the resting limit. True when the venue accepted the cancel or the order is already terminal."""
    try:
        r = client.cancel_order(category=category, symbol=symbol, orderId=str(order_id)) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("maker_exit: cancel of %s raised: %s", order_id, exc)
        return False
    code = r.get("retCode")
    # 110001 = order does not exist / already filled or cancelled: terminal, the re-read decides.
    return code in (0, "0", None, 110001, "110001")


def cancel_own_legs(client: Any, category: str, symbol: str, *leg_ids: Optional[str]) -> None:
    """Cancel the row's tracked Partial-tpsl legs after a maker fill flattened it (``close_open_position`` does
    the same after a Market close). Best effort: a leg that already fired or was cancelled is fine."""
    for leg_id in leg_ids:
        if not leg_id:
            continue
        try:
            r = client.cancel_order(category=category, symbol=symbol, orderId=str(leg_id)) or {}
            logger.info("maker_exit: post-fill leg cancel %s %s -> retCode=%s", symbol, leg_id, r.get("retCode"))
        except Exception as exc:  # noqa: BLE001
            logger.info("maker_exit: post-fill leg cancel %s %s raised: %s", symbol, leg_id, exc)


def _executions(client: Any, category: str, symbol: str, order_id: str) -> Dict[str, Any]:
    from src.units.accounts.maker_entry import _executions as _ex
    out = _ex(client, category, symbol, order_id)
    return {k: out[k] for k in ("fee_read", "exec_fee", "is_maker") if k in out}


# --- the exit pass --------------------------------------------------------------------------------------------

@dataclass
class Step:
    action: str
    why: str = ""
    block: Optional[Dict[str, Any]] = None      # the new notes.maker_exit block to persist (None = unchanged)
    qty: Optional[float] = None                 # A_FALLBACK: the Market qty (the unfilled remainder)
    filled_qty: float = 0.0
    filled_avg: Optional[float] = None
    order_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def ex_result(self) -> Dict[str, Any]:
        """A_MAKER_FILLED: the result shape the close path expects from ``_send_close_to_exchange``."""
        return {"ok": True, "exchange_response": None, "exchange_order_id": self.order_id, "error": None,
                "maker_exit": True}


def blended_exit_price(filled_qty: float, filled_avg: Optional[float], market_qty: float,
                       market_avg: Optional[float]) -> Optional[float]:
    """Qty-weighted exit price of the maker part and the Market remainder; None when a part is unpriced."""
    if filled_qty <= 0:
        return market_avg
    if filled_avg is None or market_avg is None or market_qty < 0:
        return None
    tot = filled_qty + market_qty
    return (filled_qty * filled_avg + market_qty * market_avg) / tot if tot > 0 else None


def exit_step(row: Dict[str, Any], reason: Optional[str], *, strategy: Optional[str], client: Any,
              cfg: Optional[Dict[str, Any]],
              order_status: Callable[[Dict[str, Any], str], Optional[Dict[str, Any]]],
              position_open: Callable[[Dict[str, Any], str, str], Optional[bool]],
              now: Optional[datetime] = None,
              cfg_loader: Optional[Callable[[str], dict]] = None) -> Step:
    """What the exit pass does for this leg's close this pass. Never raises (any error -> ``market``, today's path)."""
    now = now or _now()
    try:
        return _exit_step(row, reason, strategy=strategy, client=client, cfg=cfg or {}, order_status=order_status,
                          position_open=position_open, now=now, cfg_loader=cfg_loader)
    except Exception as exc:  # noqa: BLE001
        logger.warning("maker_exit: exit_step failed for trade %s: %s -- Market close", row.get("id"), exc)
        return Step(A_MARKET, why=f"error: {str(exc)[:120]}")


def _exit_step(row, reason, *, strategy, client, cfg, order_status, position_open, now, cfg_loader) -> Step:
    blk = block_of(row.get("notes"))
    size = float(row.get("position_size") or 0.0)
    symbol = str(row.get("symbol") or "")
    direction = str(row.get("direction") or "").lower()
    state = blk.get("state")

    if not blk:
        choice, why = resolve_exit_order(strategy, reason, cfg, cfg_loader=cfg_loader)
        if choice != POST_ONLY_MID or client is None or size <= 0:
            return Step(A_MARKET, why=why if choice != POST_ONLY_MID else "no_client_or_size")
        new = place_resting_exit(client, cfg, symbol=symbol, direction=direction, qty=size, now=now)
        if new.get("state") == "resting":
            return Step(A_PLACED, why="placed", block=new, order_id=new.get("limit_order_id"))
        return Step(A_MARKET, why=f"place_failed: {new.get('why')}", block=new)

    from src.units.accounts.execute import _bybit_category
    category = _bybit_category(cfg) if cfg else "linear"
    stamp = now.isoformat()

    if state == "fallback_market":
        rem = max(size - float(blk.get("filled_qty") or 0.0), 0.0)
        return Step(A_FALLBACK, why="fallback_retry", qty=rem, filled_qty=float(blk.get("filled_qty") or 0.0),
                    filled_avg=blk.get("filled_avg"))
    if state == "released_venue_flat":
        rel = _parse_ts(blk.get("resolved_at"))
        if rel is not None and (now - rel).total_seconds() < ABANDON_S:
            return Step(A_VENUE_FLAT, why="awaiting_reconciler")
        return Step(A_MARKET, why="released_stale")
    if state != "resting":
        return Step(A_MARKET, why=f"state_{state}")

    tid = str(blk.get("limit_order_id") or "")
    placed = _parse_ts(blk.get("placed_at"))
    age = (now - placed).total_seconds() if placed else FALLBACK_SECONDS
    if client is None or not cfg or not tid:
        return Step(A_WAIT, why="no_client") if age < UNREAD_GIVE_UP_S else Step(A_MARKET, why="no_client_stale")

    st = order_status(cfg, tid)
    if st is None:
        if age < UNREAD_GIVE_UP_S and str(reason or "") in TIME_STOP_REASONS:
            return Step(A_WAIT, why="status_unreadable")
        cancel_limit(client, category, symbol, tid)
        b = dict(blk, state="fallback_market", fallback_reason="status_unreadable", resolved_at=stamp)
        return Step(A_FALLBACK, why="status_unreadable", block=b, qty=size)

    status = str(st.get("status") or "").lower()
    filled = float(st.get("filled_qty") or 0.0)
    avg = float(st.get("avg_price") or 0.0) or None

    # A PROTECTIVE close (any reason but the time stop) arriving while the maker limit rests never waits out the
    # window: the limit is cancelled now and the remainder goes at Market in this pass.
    urgent = str(reason or "") not in TIME_STOP_REASONS
    if status in _LIVE and filled < size - _EPS and age < FALLBACK_SECONDS and not urgent:
        return Step(A_WAIT, why="resting")
    if status in _LIVE and filled < size - _EPS:          # window expired (or urgent): cancel, then re-read
        if not cancel_limit(client, category, symbol, tid):
            return Step(A_WAIT, why="cancel_failed")
        st = order_status(cfg, tid) or st
        status = str(st.get("status") or "").lower()
        filled = float(st.get("filled_qty") or filled)
        avg = float(st.get("avg_price") or 0.0) or avg
        why = "protective_close" if urgent else "window_expired"
    else:
        why = "post_only_reject_or_venue_cancel" if filled <= _EPS else "terminal_partial"

    if filled >= size - _EPS:
        b = dict(blk, state="filled_maker", filled_qty=filled, filled_avg=avg, resolved_at=stamp,
                 **_executions(client, category, symbol, tid))
        return Step(A_MAKER_FILLED, why="filled", block=b, filled_qty=filled, filled_avg=avg, order_id=tid)

    # A Market remainder is due. First: is the position still there? A stop/TP that filled during the window
    # flattened it; a Market close would then be refused ("position is zero") and recorded as max_hold.
    alive = position_open(cfg, symbol, direction)
    if alive is None:
        if age < UNREAD_GIVE_UP_S and not urgent:
            return Step(A_WAIT, why="position_unreadable")
    elif alive is False:
        b = dict(blk, state="released_venue_flat", filled_qty=filled, filled_avg=avg, resolved_at=stamp,
                 release_reason=why)
        return Step(A_VENUE_FLAT, why="venue_flat", block=b)
    rem = max(size - filled, 0.0)
    b = dict(blk, state="fallback_market", fallback_reason=why, filled_qty=filled, filled_avg=avg,
             resolved_at=stamp)
    if filled > 0:
        b.update(_executions(client, category, symbol, tid))
    return Step(A_FALLBACK, why=why, block=b, qty=rem, filled_qty=filled, filled_avg=avg)


# --- the reconciliation tick ----------------------------------------------------------------------------------

def reconciler_defers(raw_notes: Any, now: Optional[datetime] = None) -> bool:
    """True while a maker exit RESTS on this row (bounded by :data:`ABANDON_S`): the exit pass owns its close."""
    blk = block_of(raw_notes)
    if blk.get("state") != "resting":
        return False
    placed = _parse_ts(blk.get("placed_at"))
    if placed is None:
        return False
    return ((now or _now()) - placed).total_seconds() < ABANDON_S


def sweep_maker_exits(db: Any, *, build_client: Callable[[str], Tuple[Any, Optional[Dict[str, Any]]]],
                      order_status: Callable[[Dict[str, Any], str], Optional[Dict[str, Any]]],
                      now: Optional[datetime] = None) -> Dict[str, int]:
    """Cancel limits left resting on CLOSED rows, and abandon blocks nobody resolved within :data:`ABANDON_S`.

    Selects only rows whose notes carry ``"maker_exit"``. Best effort; never raises."""
    summary = {"resting": 0, "resolved": 0, "errors": 0}
    now = now or _now()
    try:
        conn = db.connect()
        try:
            conn.row_factory = __import__("sqlite3").Row
            rows = [dict(r) for r in conn.execute(
                "SELECT id, account_id, symbol, notes, status FROM trades "
                "WHERE COALESCE(is_backtest,0)=0 AND notes LIKE ?", ('%"maker_exit"%',)).fetchall()]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("maker_exit: row read failed: %s", exc)
        summary["errors"] += 1
        return summary
    from src.units.accounts.execute import _bybit_category
    clients: Dict[str, Tuple[Any, Optional[Dict[str, Any]]]] = {}
    for row in rows:
        try:
            notes = decode_notes(row.get("notes"))
            blk = notes.get(NOTES_KEY) or {}
            if blk.get("state") != "resting":
                continue
            summary["resting"] += 1
            row_open = str(row.get("status") or "open") == "open"
            placed = _parse_ts(blk.get("placed_at"))
            stale = placed is None or (now - placed).total_seconds() >= ABANDON_S
            if row_open and not stale:
                continue                                   # the exit pass owns it
            aid = str(row.get("account_id") or "")
            if aid not in clients:
                clients[aid] = build_client(aid)
            client, cfg = clients[aid]
            if client is None or cfg is None:
                continue
            tid = str(blk.get("limit_order_id") or "")
            st = order_status(cfg, tid) if tid else {"status": "not_found"}
            if st is None:
                continue                                   # could not look: retry next tick
            if str(st.get("status") or "").lower() in _LIVE:
                if not cancel_limit(client, _bybit_category(cfg), str(row.get("symbol") or ""), tid):
                    continue
                st = order_status(cfg, tid) or st
            filled = float(st.get("filled_qty") or 0.0)
            blk.update(state=("cancelled_row_not_open" if not row_open else "abandoned"),
                       filled_qty=filled, resolved_at=now.isoformat())
            if filled > 0:
                logger.error("maker_exit: %s %s limit %s had filled %s when the sweep resolved it (row %s)",
                             aid, row.get("symbol"), tid, filled, "closed" if not row_open else "abandoned")
            notes[NOTES_KEY] = blk
            db.update_trade(row["id"], {"notes": json.dumps(notes)})
            summary["resolved"] += 1
        except Exception as exc:  # noqa: BLE001 -- one bad row never stops the sweep
            logger.warning("maker_exit: row %s failed: %s", row.get("id"), exc)
            summary["errors"] += 1
    return summary
