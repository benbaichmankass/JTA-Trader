"""ml_entry_v2 -- the ML ENTRY v2 candidate as a TESTING leg (bybit_1 demo only; Tier 3, held).

Same pooled-model machinery as ``ml_entry`` (shared ``decide`` / ``order_package`` / feature code), a different artifact
(``ml/served/ml_decision_entry_v2``): the R2 regularised recipe, the 0.06 cost-per-R gate and the SL 2 / TP 4 ATR bracket.
Status: the dev stack (+0.0478 vs +0.0089) did NOT hold on the one W1 read (RQ-20261101-b609-01: -0.1161, n=320, vs frozen v1
-0.0405), so v2 is NOT a candidate for any real-money roster. It trades the Stage-1 demo floor only, to prove the mechanics
(a 4 ATR target, the cost gate, the gated refusals) while the edge is decided OFFLINE by the registered fresh-window read
RQ-20261101-b610-01 (a replay of this frozen artifact on November data). No sizing: confidence is the neutral full basis.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pandas as pd

from src.units.strategies import ml_entry as _base

logger = logging.getLogger(__name__)

NAME = "ml_entry_v2"
ARTIFACT = Path(__file__).resolve().parents[3] / "ml" / "served" / "ml_decision_entry_v2" / "model.json"
NEUTRAL_CONFIDENCE = _base.NEUTRAL_CONFIDENCE
is_decision_bar = _base.is_decision_bar


def load_model(path: Path = ARTIFACT) -> Dict[str, Any]:
    return _base.load_model(path)


def order_package(cfg: dict, candles_df: Optional[pd.DataFrame] = None,
                  reference_frames: Optional[Mapping[str, pd.DataFrame]] = None,
                  model: Optional[Dict[str, Any]] = None) -> dict:
    return _base.order_package(cfg, candles_df=candles_df, reference_frames=reference_frames, model=model or load_model())


def _telemetry(candles_df: Optional[pd.DataFrame], open_pkg: dict) -> None:
    """M31 peak-R position telemetry under this strategy's own name. Observe-only: reads nothing back; swallows everything."""
    try:
        if candles_df is None or len(candles_df) == 0:
            return
        from src.runtime.exit_levers import since_entry
        from src.runtime.position_telemetry import record_position_telemetry

        meta = open_pkg.get("meta") or {}
        record_position_telemetry(
            candles_df=candles_df, atr=meta.get("atr14"), open_pkg=open_pkg, meta=meta,
            window=since_entry(candles_df, open_pkg), direction=str(open_pkg.get("direction") or ""),
            current_price=float(candles_df["close"].iloc[-1]), stop=open_pkg.get("sl"),
            target=open_pkg.get("tp"), strategy=NAME)
    except Exception:  # noqa: BLE001 -- telemetry must never break the time stop
        logger.debug("ml_entry_v2: telemetry failed", exc_info=True)


def monitor(cfg, candles_df, open_pkg):  # noqa: ARG001 -- canonical signature
    """24 h time stop plus observe-only peak-R telemetry; never raises."""
    _telemetry(candles_df, open_pkg)
    try:
        from datetime import datetime, timezone
        from src.units.strategies.claude_desk import max_hold_verdict
        return max_hold_verdict(open_pkg, datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001 -- a monitor must never raise
        logger.debug("ml_entry_v2.monitor: verdict failed", exc_info=True)
        return None
