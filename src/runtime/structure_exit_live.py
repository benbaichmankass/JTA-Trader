"""Live structure exit: the `structure_exit` verdict source for monitor().

Row STRUCTURE-EXITS-DEFAULT, scope doc
docs/research/structure-exits-default-scope-2026-11-01.md § 5 (operator
2026-11-03: "Build it now - we said it's the new default until we prove
something else works better").

WHAT IT IS
----------
A pure verdict source a strategy ``monitor()`` calls when the leg DECLARES

    structure_exit: "pivot=3"                       # or
    structure_exit: {pivot: 3, buffer_atr: 0.25, min_r: 1.0, fvg: true}

in ``config/strategies.yaml`` (threaded into the package meta at entry, like
``tp_revision``). Undeclared = :func:`declared` returns None and the monitor
runs exactly the code it ran before (byte-identical; tests pin it). Selecting
it on a leg is Tier-3. It is a declared exit field of the leg, not a switch:
no ``*_ENABLED`` flag, no third execution gate.

It imports the ONE shared causal detector, ``src/runtime/structure_levels.py``
(``StructureLevels`` + ``StructureExit.on_bar_close``), the same object the
harness arm ``scripts/backtest_trend.py --structure-exit`` steps per bar. No
swing / FVG code lives here.

HOW ONE TICK DECIDES (pure, stateless, deterministic)
-----------------------------------------------------
1. CLOSED bars only (the forming bar is dropped). The detector is built on
   bars ``0..last`` ONLY (truncated, so it cannot see past the last close).
2. Replay the harness step from the entry bar to the last closed bar:
   start SL = the package's ENTRY stop (``meta.entry_sl`` else ``open_pkg.sl``
   at entry) ratcheted toward the structure start stop (never loosened past
   the entry stop: § 5.2 rule 3); start TP = the structure TP at the entry bar;
   then ``StructureExit.on_bar_close(j, close_j, sl, tp, entry)`` for every
   closed bar ``j`` -- SL ratchets toward price only, TP is extend-only.
3. The verdict is the difference between the replayed target and what the
   package believes rests at the venue:
   * SL tighter than the resting stop and on the safe side of price -> ``sl``;
     a target already through price -> a close (``structure_sl_cross``),
     exactly as a resting stop would have filled (a close beats a move);
   * TP: the replayed structure TP, through ``tp_revision``'s venue-cap clamp
     and through-price refusal; a refused or absent structure TP keeps the
     resting TP (both brackets always exist -- Active management clause 3).
   Because the target only changes when a bar closes, there is at most one
   move per (package, bar), and once the venue holds it the verdict is None.
4. A move a venue refuses leaves ``order_packages.sl/tp`` unchanged (the
   existing exchange-first modify path), so the same verdict re-fires next
   tick: retried, never dropped. Every proposed move and every venue outcome
   is journalled (:data:`JOURNAL_NAME`, schema :data:`JOURNAL_FIELDS`).

Never widens a stop, so a RiskManager re-check on widen never triggers from
here; a TP extension is not a risk widen.

Known, stated difference from the harness arm: the harness ``start()`` may set
the initial stop WIDER than the ATR stop (clamped to 3x); live never loosens
past the entry stop, so on those trades the live start stop is the tighter of
the two and R is the entry R. Parity is pinned on the per-bar step
(tests/test_structure_exit_live.py), which is the part both paths share.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from src.runtime.structure_levels import StructureExit, StructureLevels, structure_sl, structure_tp

logger = logging.getLogger(__name__)

FIELD = "structure_exit"
SOURCE = "structure_exit"
REASON_SL_CROSS = "structure_sl_cross"
JOURNAL_NAME = "structure_exit_moves.jsonl"
#: One journal row per proposed move (phase "proposed", from the monitor) and
#: one per venue outcome per leg (phase "venue", from order_monitor).
JOURNAL_FIELDS = (
    "ts", "phase", "order_package_id", "strategy", "symbol", "direction",
    "bar_ts", "bar_idx", "level_type", "level_price", "level_formed_idx",
    "level_confirmed_idx", "reason", "sl_before", "sl_after", "tp_before",
    "tp_after", "account_id", "trade_id", "outcome", "venue_readback", "error",
)
_DEFAULTS = {"pivot": 3, "buffer_atr": 0.25, "min_r": 1.0, "fvg": True}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def declared(leg: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The leg's structure-exit params, or None when it does not declare one.

    Accepts ``"pivot=N"`` (the harness CLI spelling) or a mapping. A malformed
    declaration is None (logged): an unreadable exit spec must not move a stop.
    """
    raw = (leg or {}).get(FIELD) if isinstance(leg, Mapping) else None
    if raw in (None, "", False):
        return None
    try:
        if isinstance(raw, str):
            from src.runtime.structure_levels import parse_structure_exit
            n = parse_structure_exit(raw)
            out = dict(_DEFAULTS, pivot=n)
        elif isinstance(raw, Mapping):
            out = dict(_DEFAULTS)
            out.update({k: raw[k] for k in _DEFAULTS if k in raw})
            out["pivot"] = int(out["pivot"])
            out["buffer_atr"] = float(out["buffer_atr"])
            out["min_r"] = float(out["min_r"])
            out["fvg"] = bool(out["fvg"])
        else:
            return None
        if out["pivot"] < 1:
            return None
        return out
    except Exception:  # noqa: BLE001
        logger.warning("structure_exit: malformed declaration %r -- ignored", raw)
        return None


# ---------------------------------------------------------------------------
# The replay (shared by the live verdict and the parity test)
# ---------------------------------------------------------------------------
def _level_for_sl(levels: StructureLevels, j: int, close: float, is_long: bool):
    return (levels.last_swing_low(j, below=close) if is_long
            else levels.last_swing_high(j, above=close))


def _level_for_tp(levels: StructureLevels, j: int, entry: float, is_long: bool,
                  risk: float, min_r: float, fvg: bool):
    floor = entry + min_r * risk if is_long else entry - min_r * risk
    return (levels.resistance_above(j, floor, fvg=fvg) if is_long
            else levels.support_below(j, floor, fvg=fvg))


def replay(*, highs, lows, closes, entry_idx: int, entry: float, is_long: bool,
           entry_sl: float, atr: float, params: Mapping[str, Any]) -> Dict[str, Any]:
    """Step the harness's structure exit over closed bars ``entry_idx..len-1``.

    Returns ``{"sl", "tp", "moves": [...]}`` -- ``tp`` None when no structure
    level qualified (the caller keeps its resting TP). Each move records the
    bar, the level that produced it and before/after values. Pure.
    """
    m = len(closes)
    risk = abs(entry - entry_sl)
    if m == 0 or not (0 <= entry_idx < m) or risk <= 0 or not atr or atr <= 0:
        return {"sl": entry_sl, "tp": None, "moves": []}
    n = int(params["pivot"])
    buf, min_r, fvg = float(params["buffer_atr"]), float(params["min_r"]), bool(params["fvg"])
    levels = StructureLevels(list(highs)[:m], list(lows)[:m], n)
    moves: List[Dict[str, Any]] = []
    # start: never looser than the entry stop
    s0 = structure_sl(levels, entry_idx, entry, is_long, atr, risk, buffer_atr=buf)
    sl = entry_sl
    if s0 is not None and ((is_long and s0 > sl) or (not is_long and s0 < sl)):
        lv = (levels.last_swing_low(entry_idx, below=entry) if is_long
              else levels.last_swing_high(entry_idx, above=entry))
        moves.append(_move(entry_idx, "start_sl", lv, sl, s0, None, None))
        sl = s0
    tp = structure_tp(levels, entry_idx, entry, is_long, risk, min_r=min_r, fvg=fvg)
    if tp is not None:
        moves.append(_move(entry_idx, "start_tp", _level_for_tp(levels, entry_idx, entry, is_long, risk, min_r, fvg),
                           sl, sl, None, tp))
    sx = StructureExit(levels, is_long, atr, buffer_atr=buf, min_r=min_r, fvg=fvg,
                       sl=sl, risk=risk, tp=tp)
    for j in range(entry_idx, m):
        c = float(closes[j])
        sl0, tp0 = sl, tp
        sl, tp = sx.on_bar_close(j, c, sl, tp, entry)
        if sl != sl0:
            moves.append(_move(j, "swing_ratchet", _level_for_sl(levels, j, c, is_long), sl0, sl, tp0, tp0))
        if tp != tp0:
            moves.append(_move(j, "tp_extend", _level_for_tp(levels, j, entry, is_long, risk, min_r, fvg),
                               sl, sl, tp0, tp))
    return {"sl": sl, "tp": tp, "moves": moves}


def _move(j, reason, lv, sl_b, sl_a, tp_b, tp_a) -> Dict[str, Any]:
    return {"bar_idx": int(j), "reason": reason,
            "level_type": getattr(lv, "kind", None), "level_price": getattr(lv, "price", None),
            "level_formed_idx": getattr(lv, "formed_idx", None),
            "level_confirmed_idx": getattr(lv, "confirmed_idx", None),
            "sl_before": sl_b, "sl_after": sl_a, "tp_before": tp_b, "tp_after": tp_a}


# ---------------------------------------------------------------------------
# The live verdict
# ---------------------------------------------------------------------------
def _ts_col(df) -> Optional[str]:
    for c in ("timestamp", "ts", "time"):
        if c in getattr(df, "columns", ()):
            return c
    return None


def _atr_at(highs, lows, closes, idx: int, period: int = 14) -> Optional[float]:
    if idx < 1:
        return None
    trs = []
    for k in range(max(1, idx - period + 1), idx + 1):
        h, lo, pc = float(highs[k]), float(lows[k]), float(closes[k - 1])
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return sum(trs) / len(trs) if trs else None


def structure_exit_verdict(meta: Mapping[str, Any], open_pkg: Mapping[str, Any], candles_df: Any,
                           *, timeframe: Optional[str] = None,
                           journal: bool = True) -> Optional[Dict[str, Any]]:
    """The structure verdict for one open package, or None (no change / not
    computable). Call ONLY when :func:`declared` is not None. Never raises."""
    try:
        params = declared(meta)
        if params is None or candles_df is None or len(candles_df) == 0:
            return None
        direction = str(open_pkg.get("direction") or "").lower()
        if direction not in ("long", "short"):
            return None
        is_long = direction == "long"
        price = float(candles_df["close"].iloc[-1])       # latest price, forming bar included
        from src.runtime.closed_bars import drop_forming_bar
        tf = str(timeframe or meta.get("timeframe") or "")
        bars = drop_forming_bar(candles_df, tf) if tf else candles_df
        tcol = _ts_col(bars)
        entry = _f(open_pkg.get("entry"))
        if tcol is None or entry is None or len(bars) < 2:
            return None
        import pandas as pd
        ts = pd.to_datetime(bars[tcol], utc=True).reset_index(drop=True)
        et = meta.get("entry_time") or meta.get("decision_bar")
        if et is None:
            return None
        et = pd.to_datetime(et, utc=True)
        idx = int((ts <= et).sum()) - 1
        if idx < 0 or idx >= len(bars):
            return None
        highs = bars["high"].to_numpy(float)
        lows = bars["low"].to_numpy(float)
        closes = bars["close"].to_numpy(float)
        rpu = _f(meta.get("risk_per_unit"))
        entry_sl = _f(meta.get("entry_sl"))
        if entry_sl is None and rpu:
            entry_sl = entry - rpu if is_long else entry + rpu
        if entry_sl is None:
            return None
        atr = _f(meta.get("atr")) or _f(meta.get("atr14")) or _atr_at(highs, lows, closes, idx)
        if not atr or atr <= 0:
            return None
        out = replay(highs=highs, lows=lows, closes=closes, entry_idx=idx, entry=entry,
                     is_long=is_long, entry_sl=entry_sl, atr=atr, params=params)
        cur_sl, cur_tp = _f(open_pkg.get("sl")), _f(open_pkg.get("tp"))
        verdict: Dict[str, Any] = {}
        last = out["moves"][-1] if out["moves"] else None
        tsl = out["sl"]
        from src.runtime.monitor_verdict import MEANINGFUL_MODIFY_REL_TOL
        if cur_sl is not None and tsl is not None and (
                (is_long and tsl > cur_sl) or (not is_long and tsl < cur_sl)) and (
                abs(tsl - cur_sl) > max(abs(cur_sl) * MEANINGFUL_MODIFY_REL_TOL, 1e-8)):
            if (is_long and tsl >= price) or (not is_long and tsl <= price):
                v = {"action": "close", "reason": REASON_SL_CROSS, "exit_price": price}
                _journal_proposed(journal, open_pkg, ts, last, cur_sl, tsl, cur_tp, cur_tp,
                                  reason=REASON_SL_CROSS)
                return v
            verdict["sl"] = round(tsl, 8)
        ttp = out["tp"]
        if ttp is not None:
            from src.runtime.tp_revision import clamp_to_venue_cap, tp_revision_rejection
            placed, clamped = clamp_to_venue_cap(direction, ttp, price)
            if tp_revision_rejection(direction, placed, price) is None:
                if cur_tp is None or abs(placed - cur_tp) > max(abs(cur_tp) * MEANINGFUL_MODIFY_REL_TOL, 1e-8):
                    verdict["tp"] = round(placed, 8)
                    r = abs(entry - entry_sl)
                    verdict["tp_reason"] = (
                        f"{SOURCE}: structure level {ttp:.8g} ({(placed - entry) / r if is_long else (entry - placed) / r:+.2f}R)"
                        + (f", CLAMPED to the venue cap from {ttp:.8g}" if clamped else ""))
        if not verdict:
            return None
        verdict["structure_move"] = {
            "bar_ts": str(ts.iloc[-1]), "bar_idx": len(ts) - 1,
            **({k: last[k] for k in ("reason", "level_type", "level_price", "level_formed_idx",
                                     "level_confirmed_idx")} if last else {}),
            "sl_before": cur_sl, "sl_after": verdict.get("sl", cur_sl),
            "tp_before": cur_tp, "tp_after": verdict.get("tp", cur_tp),
        }
        _journal_proposed(journal, open_pkg, ts, last, cur_sl, verdict.get("sl", cur_sl), cur_tp,
                          verdict.get("tp", cur_tp), reason=(last or {}).get("reason"))
        return verdict
    except Exception:  # noqa: BLE001 -- a verdict source must never break its monitor
        logger.debug("structure_exit_verdict failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------
def _journal_path():
    from src.utils.paths import runtime_logs_dir
    return runtime_logs_dir() / JOURNAL_NAME


def journal_append(row: Mapping[str, Any]) -> None:
    """Append one row (keys restricted to JOURNAL_FIELDS). Never raises."""
    try:
        rec = {k: row.get(k) for k in JOURNAL_FIELDS}
        rec["ts"] = rec["ts"] or datetime.now(timezone.utc).isoformat()
        p = _journal_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:  # noqa: BLE001
        logger.debug("structure_exit journal append failed", exc_info=True)


def _journal_proposed(on, open_pkg, ts, last, sl_b, sl_a, tp_b, tp_a, *, reason) -> None:
    if not on:
        return
    journal_append({
        "phase": "proposed", "order_package_id": open_pkg.get("order_package_id"),
        "strategy": open_pkg.get("strategy_name"), "symbol": open_pkg.get("symbol"),
        "direction": open_pkg.get("direction"), "bar_ts": str(ts.iloc[-1]), "bar_idx": len(ts) - 1,
        "level_type": (last or {}).get("level_type"), "level_price": (last or {}).get("level_price"),
        "level_formed_idx": (last or {}).get("level_formed_idx"),
        "level_confirmed_idx": (last or {}).get("level_confirmed_idx"),
        "reason": reason, "sl_before": sl_b, "sl_after": sl_a, "tp_before": tp_b, "tp_after": tp_a,
    })


def journal_venue_outcomes(open_pkg: Mapping[str, Any], verdict: Mapping[str, Any],
                           leg_outcomes: List[Mapping[str, Any]]) -> None:
    """order_monitor hook: one row per leg with the venue's answer. Only for a
    verdict this module produced (it carries ``structure_move``). Never raises."""
    try:
        mv = verdict.get("structure_move") if isinstance(verdict, Mapping) else None
        if not isinstance(mv, Mapping):
            return
        for o in leg_outcomes:
            leg = o.get("leg") or {}
            journal_append({
                **{k: mv.get(k) for k in JOURNAL_FIELDS if k in mv},
                "phase": "venue", "order_package_id": open_pkg.get("order_package_id"),
                "strategy": open_pkg.get("strategy_name"), "symbol": open_pkg.get("symbol"),
                "direction": open_pkg.get("direction"), "account_id": leg.get("account_id"),
                "trade_id": leg.get("id"), "outcome": o.get("outcome"),
                "venue_readback": o.get("venue_readback"), "error": o.get("error"),
            })
    except Exception:  # noqa: BLE001
        logger.debug("structure_exit venue journal failed", exc_info=True)
