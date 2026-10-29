"""Shadow scoring for the real-money meta-label overlay (ML-REAL-MONEY-OVERLAY, annotate only).

For every order package whose strategy is a GATE leg of a committed overlay artifact (``ml/overlay/*.json``,
written by ``scripts/research/ml_overlay_noninferior.py`` only on a PASS of RULE-ML-OVERLAY-NONINFERIOR-V2),
this computes the would-be overlay multiplier from the leg's own CLOSED candles and appends one record to
``runtime_logs/overlay_shadow.jsonl``.

It NEVER changes an order (the I7 property): ``record_overlay_shadow`` returns ``None``, takes no quantity,
and the coordinator calls it as a bare statement. The record carries the decision-bar close next to the
package entry, so serve parity (the offline features were built at the bar whose close IS the entry) is
measured on every scored package rather than assumed.

Turning it into an applied REDUCE is a separate Tier-3 change, not a flag here (there is no third gate).
Every step is wrapped: an artifact, candle or feature failure writes an ``error``/``unscored`` record or
nothing, and can never break the trading tick.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "overlay"
_CANDLE_LIMIT = 450  # overlay_features reads a 400-bar window; MIN_BARS is 201
_ARTIFACTS: dict[str, dict] | None = None


def _load_artifacts(directory: Path = ARTIFACT_DIR) -> dict[str, dict]:
    """{gate_leg: artifact} from every committed overlay artifact. A leg named by two artifacts keeps the
    first in sorted filename order and logs the clash (never scored twice)."""
    out: dict[str, dict] = {}
    if not directory.is_dir():
        return out
    for p in sorted(directory.glob("overlay_*.json")):
        try:
            art = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("overlay_shadow: unreadable artifact %s: %s", p.name, exc)
            continue
        art["_file"] = p.name
        for leg in art.get("legs_gate") or []:
            if leg in out:
                logger.warning("overlay_shadow: %s named by %s and %s; keeping %s", leg, out[leg]["_file"],
                               p.name, out[leg]["_file"])
                continue
            out[leg] = art
    return out


def artifacts() -> dict[str, dict]:
    global _ARTIFACTS
    if _ARTIFACTS is None:
        _ARTIFACTS = _load_artifacts()
    return _ARTIFACTS


def _leg_bars(strategy: str, symbol: str) -> tuple[dict | None, str, Any]:
    from src.runtime.closed_bars import drop_forming_bar
    from src.runtime.market_data import connector_for_symbol, fetch_candles
    from src.units.strategies import load_strategy_config

    cfg = load_strategy_config().get(strategy) or {}
    tf = str(cfg.get("timeframe") or "")
    # The SAME feed the signal was priced on, uncached so the decision bar has closed (prop_trail precedent).
    df = fetch_candles(symbol, tf, limit=_CANDLE_LIMIT, bypass_cache=True,
                       exchange_client=connector_for_symbol(symbol, {}))
    if df is None or not tf:
        return None, tf, None
    df = drop_forming_bar(df, tf)
    last_ts = df["timestamp"].iloc[-1] if "timestamp" in getattr(df, "columns", []) else None
    return {"high": df["high"].astype(float).tolist(), "low": df["low"].astype(float).tolist(),
            "close": df["close"].astype(float).tolist()}, tf, last_ts


def score_package(pkg: Any) -> dict | None:
    """The shadow record for ``pkg``, or ``None`` when no artifact covers its strategy. Never raises."""
    strategy = str(getattr(pkg, "strategy", "") or "")
    try:
        art = artifacts().get(strategy)
        if art is None:
            return None
        from src.runtime.overlay_features import decision_features, overlay_multiplier, score_overlay

        symbol = str(getattr(pkg, "symbol", "") or "")
        bars, tf, last_ts = _leg_bars(strategy, symbol)
        row = decision_features(bars, str(getattr(pkg, "direction", ""))) if bars else None
        entry = float(getattr(pkg, "entry", 0.0) or 0.0)
        rec: dict[str, Any] = {
            "artifact": art.get("_file"), "family": art.get("family"), "rule": art.get("rule"),
            "timeframe": tf, "decision_bar_ts": str(last_ts) if last_ts is not None else None,
            "decision_bar_close": bars["close"][-1] if bars else None, "pkg_entry": entry,
            "tau": art.get("tau"), "multiplier_if_reduce": art.get("multiplier"),
        }
        if row is None:
            rec.update(action="unscored", would_be_multiplier=1.0, p_win=None)
            return rec
        rec.update(action="annotate", p_win=round(score_overlay(art, row), 6),
                   would_be_multiplier=overlay_multiplier(art, row), features=row)
        if entry and bars:
            rec["entry_vs_bar_close_bps"] = round(1e4 * (entry - bars["close"][-1]) / bars["close"][-1], 2)
        return rec
    except Exception as exc:  # noqa: BLE001 — shadow scoring must never break the tick
        logger.warning("overlay_shadow: scoring %s failed: %s", strategy, exc)
        return {"action": "error", "error": str(exc)[:300]}


def record_overlay_shadow(pkg: Any, account_name: str = "") -> None:
    """Score once per package (cached on ``pkg.meta``) and log one line per account. Returns ``None`` by
    design: there is no value a caller could apply to a quantity."""
    try:
        meta = getattr(pkg, "meta", None)
        if isinstance(meta, dict) and "_overlay_shadow" in meta:
            rec = meta["_overlay_shadow"]
        else:
            rec = score_package(pkg)
            if isinstance(meta, dict):
                meta["_overlay_shadow"] = rec
        if rec is None:
            return None
        from src.utils.paths import runtime_logs_dir
        path = runtime_logs_dir() / "overlay_shadow.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"logged_at_utc": datetime.now(timezone.utc).isoformat(),
                   "strategy_id": str(getattr(pkg, "strategy", "") or ""),
                   "symbol": str(getattr(pkg, "symbol", "") or ""),
                   "direction": str(getattr(pkg, "direction", "") or ""),
                   "trace_id": str(getattr(pkg, "trace_id", "") or ""),
                   "account": account_name, **rec}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("overlay_shadow: record failed: %s", exc)
    return None
