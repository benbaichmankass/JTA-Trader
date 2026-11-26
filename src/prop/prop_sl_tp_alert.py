"""Prop SL/TP crossing alert — one-shot ping when price crosses an open prop
trade's stop-loss or take-profit level.

A MANUAL prop account is a bridge: the bot has no broker feed, so it never
learns when the human actually closed a trade. This module bridges that gap:
once per tick it fetches the current price for every open prop position that has
SL/TP levels set, and fires a one-shot Telegram + FCM alert when price crosses
either level — prompting the operator to check the terminal and report back.

Design notes:

- **One alert per level per position.** Once SL or TP has been alerted, that
  flag persists so a subsequent tick where price is still past the level doesn't
  re-fire. Cleared only when the position closes (i.e. the key drops from the
  state file because ``find_open_prop_positions`` no longer returns it).
- **State file:** ``runtime_logs/prop_sl_tp_alert.json`` —
  ``{position_key: {sl_alerted_at: ISO|null, tp_alerted_at: ISO|null}}``.
  Pruned to currently-open keys on each save.
- **Price fetch:** uses ``connector_for_symbol`` + ``fetch_candles`` (the same
  path the signal builders use) — last close bar. Best-effort; a fetch failure
  skips the position for this tick without raising.
- **Direction logic:** BUY/long — SL crossed when price ≤ SL, TP crossed when
  price ≥ TP; SELL/short — SL crossed when price ≥ SL, TP crossed when
  price ≤ TP.
- **Machine-executed accounts wait a grace** (``MACHINE_CLOSE_GRACE``, 2026-11-24).
  The first cross is only RECORDED (``<level>_crossed_at`` / ``_crossed_price``);
  the alert fires once the grace has elapsed AND the position is still open
  (``find_open_prop_positions`` drops a closed position, so a recorded close
  means no alert). The message says "no close recorded", not "HIT?".
- **Baseline, no enable gate** (Prime Directive). ``PROP_SL_TP_ALERT_DISABLED``
  env (truthy) is the sanctioned kill-switch without a redeploy. Best-effort +
  isolated; never raises into the caller.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from src.prop.prop_monitor_pulse import find_open_prop_positions

logger = logging.getLogger(__name__)

_STATE_FILENAME = "prop_sl_tp_alert.json"

#: Machine-executed accounts (REST / phone / browser): the executor records its
#: own closes, so a price cross is NOT news. The alert waits this long after the
#: cross and fires only if the position is STILL open (no close recorded) --
#: a real "the executor missed it" alarm. Operator popup 2026-11-24, verbatim:
#: "Alert only if no close (Recommended)". Manual accounts keep the immediate ping.
MACHINE_CLOSE_GRACE = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_path() -> str:
    from src.utils.paths import runtime_logs_dir
    return str(runtime_logs_dir() / _STATE_FILENAME)


def _load_state() -> Dict[str, Dict[str, Any]]:
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_state(state: Dict[str, Dict[str, Any]]) -> None:
    try:
        path = _state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("prop_sl_tp_alert: state save failed: %s", exc)


def _fetch_current_price(symbol: str, settings: dict) -> Optional[float]:
    """Fetch the latest close price for *symbol*. Returns None on any failure."""
    try:
        from src.runtime.market_data import connector_for_symbol, fetch_candles
        client = connector_for_symbol(symbol, settings)
        if client is None:
            return None
        df = fetch_candles(symbol, "5m", settings=settings,
                           exchange_client=client, limit=3)
        if df is None or df.empty:
            return None
        return float(df.iloc[-1]["close"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("prop_sl_tp_alert: price fetch failed for %s: %s", symbol, exc)
        return None


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _sl_crossed(direction: str, current: float, sl: float) -> bool:
    d = direction.lower()
    if d in ("buy", "long"):
        return current <= sl
    if d in ("sell", "short"):
        return current >= sl
    return False


def _tp_crossed(direction: str, current: float, tp: float) -> bool:
    d = direction.lower()
    if d in ("buy", "long"):
        return current >= tp
    if d in ("sell", "short"):
        return current <= tp
    return False


def run_prop_sl_tp_alert(
    *,
    now: Optional[datetime] = None,
    settings: Optional[dict] = None,
    emitter: Optional[Callable[[Dict[str, Any], str, float], None]] = None,
) -> Dict[str, Any]:
    """Check open prop positions against current price; alert on SL/TP crossings.

    Called once per trader tick. Fires at most one SL alert and one TP alert per
    position over its lifetime. Returns stats ``{open, sl_fired, tp_fired,
    disabled}``. Never raises.
    """
    stats = {"open": 0, "sl_fired": 0, "tp_fired": 0, "disabled": False}
    if str(os.environ.get("PROP_SL_TP_ALERT_DISABLED", "")).strip().lower() in (
        "1", "true", "yes"
    ):
        stats["disabled"] = True
        return stats

    now = now or _now()

    if settings is None:
        try:
            from src.runtime.validation import build_settings_from_env
            settings = build_settings_from_env()
        except Exception as exc:  # noqa: BLE001
            logger.warning("prop_sl_tp_alert: settings build failed: %s", exc)
            settings = {}

    try:
        positions = find_open_prop_positions(now=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("prop_sl_tp_alert: open-position scan failed: %s", exc)
        return stats
    stats["open"] = len(positions)

    if emitter is None:
        from src.prop.breakout_notify import emit_prop_sl_tp_alert as emitter  # type: ignore

    state = _load_state()
    new_state: Dict[str, Dict[str, Any]] = {}
    state_changed = False
    machine_cache: Dict[str, bool] = {}

    def _is_machine(account_id: Any) -> bool:
        acct = str(account_id or "")
        if acct not in machine_cache:
            from src.prop.breakout_notify import _machine_executed
            machine_cache[acct] = bool(_machine_executed(acct))
        return machine_cache[acct]

    for pos in positions:
        key = pos["key"]
        symbol = str(pos.get("symbol") or "")
        direction = str(pos.get("direction") or "")
        machine = _is_machine(pos.get("account_id") or pos.get("account"))

        prior = state.get(key, {})
        new_entry: Dict[str, Any] = {
            k: prior.get(k) for k in (
                "sl_alerted_at", "tp_alerted_at",
                "sl_crossed_at", "tp_crossed_at",
                "sl_crossed_price", "tp_crossed_price")
        }

        levels = {"sl": pos.get("sl"), "tp": pos.get("tp")}
        if not levels["sl"] and not levels["tp"]:
            new_state[key] = new_entry
            continue

        current_price = _fetch_current_price(symbol, settings)
        crossed_fn = {"sl": _sl_crossed, "tp": _tp_crossed}

        for lvl in ("sl", "tp"):
            level_val = levels[lvl]
            if not level_val or new_entry[f"{lvl}_alerted_at"]:
                continue
            try:
                crossed_now = (current_price is not None and
                               crossed_fn[lvl](direction, current_price, float(level_val)))
                fire_price: Optional[float] = None
                fire_pos = pos
                if not machine:
                    if crossed_now:
                        fire_price = current_price
                else:
                    if crossed_now and not new_entry[f"{lvl}_crossed_at"]:
                        new_entry[f"{lvl}_crossed_at"] = now.isoformat()
                        new_entry[f"{lvl}_crossed_price"] = current_price
                        state_changed = True
                    crossed_at = _parse_iso(new_entry[f"{lvl}_crossed_at"])
                    if crossed_at is not None and now - crossed_at >= MACHINE_CLOSE_GRACE:
                        # Still in `positions` => no close recorded in the grace.
                        fire_price = float(new_entry[f"{lvl}_crossed_price"]
                                           if new_entry[f"{lvl}_crossed_price"] is not None
                                           else current_price)
                        fire_pos = dict(pos, missed_close_minutes=int(
                            (now - crossed_at).total_seconds() // 60))
                if fire_price is None:
                    continue
                emitter(fire_pos, lvl, fire_price)
                new_entry[f"{lvl}_alerted_at"] = now.isoformat()
                stats[f"{lvl}_fired"] += 1
                state_changed = True
                logger.info(
                    "prop_alert %s alert fired %s %s price=%.4f level=%.4f "
                    "machine=%s (key=%s)",
                    lvl.upper(), symbol, direction, fire_price, float(level_val),
                    machine, key,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "prop_sl_tp_alert: %s emit failed for %s: %s", lvl.upper(), key, exc
                )

        new_state[key] = new_entry

    # Prune state to open keys only; save when anything changed.
    open_keys = {p["key"] for p in positions}
    if state_changed or open_keys != set(state.keys()):
        _save_state(new_state)

    if stats["sl_fired"] or stats["tp_fired"]:
        logger.info(
            "prop_sl_tp_alert: open=%d sl_fired=%d tp_fired=%d",
            stats["open"], stats["sl_fired"], stats["tp_fired"],
        )
    return stats


__all__ = ["run_prop_sl_tp_alert", "MACHINE_CLOSE_GRACE"]
