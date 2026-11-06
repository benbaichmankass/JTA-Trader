"""ml_entry_eq -- the EQUITY-NATIVE ENTRY model as a TESTING leg (alpaca_paper only; Tier 2, held for the manager's merge).

One pooled LightGBM (config B: 15 own-symbol + 6 cross-sectional pool features, NO crypto / market-proxy feature) trained on the 173-ETF Alpaca liquidity
pool; restricted LONG when the predicted net R at the decision close exceeds tau (0.20); SL 2 x ATR14, TP 3 x ATR14, 24 h time stop. Evidence:
RQ-20261105-e9a1-02 (run 42143223941): n 858, net +0.0392 R, iid t 0.9, month-clustered t 0.3 -- a MECHANICS soak, not an edge claim. Real money is the
operator's call. Spec: docs/research/ml-entry-eq-serve-spec-2026-11-06.md.

Pure signal generator (.claude/skills/new-strategy/SKILL.md): no accounts, no sizing (neutral confidence), no order placement, and NO NETWORK: every
input comes from the pool snapshot the refresher wrote (src/runtime/ml_entry_eq_refresher.py). The exit path never calls the feature builder: the bracket
is fixed at entry (no TP revision, no re-scoring), :func:`monitor` only enforces the 24 h time stop.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

import src.runtime.ml_entry_eq_features as F

logger = logging.getLogger(__name__)

NAME = "ml_entry_eq"
ARTIFACT = Path(__file__).resolve().parents[3] / "ml" / "candidates" / "ml_entry_eq_v1" / "model.json"
NEUTRAL_CONFIDENCE = 1.0
_CACHE: Dict[str, Any] = {}


def load_model(path: Path = ARTIFACT) -> Dict[str, Any]:
    """``{"meta": ..., "long": Booster}``, cached by mtime. Raises when the artifact is unreadable."""
    import lightgbm as lgb
    st = path.stat()
    hit = _CACHE.get(str(path))
    if hit and hit[0] == st.st_mtime:
        return hit[1]
    art = json.loads(path.read_text(encoding="utf-8"))
    model = {"meta": {k: v for k, v in art.items() if k != "booster_txt"}, "long": lgb.Booster(model_str=art["booster_txt"]["long"])}
    _CACHE[str(path)] = (st.st_mtime, model)
    return model


def pool_symbols() -> List[str]:
    return [str(s) for s in load_model()["meta"]["pool_symbols"]]


def score(row: Mapping[str, float], model: Dict[str, Any]) -> float:
    cols = model["meta"]["features"]
    return float(model["long"].predict(pd.DataFrame([[row[k] for k in cols]], columns=cols))[0])  # provenance: predict -- live decision scoring


def order_package(cfg: dict, snapshot: Mapping[str, Any], model: Optional[Dict[str, Any]] = None) -> dict:
    """The LONG package for ``cfg['symbol']`` from the pool snapshot, or ``ValueError(<named reason>)`` for a non-actionable tick."""
    symbol = str(cfg.get("symbol") or "")
    model = model or load_model()
    meta = model["meta"]
    br = meta["bracket"]
    bc = pd.Timestamp(snapshot["bar_close"])
    if not F.is_decision_close(bc):
        raise ValueError("not_a_decision_bar")
    row = F.feature_vector(snapshot, symbol, features=meta["features"])
    if row is None:
        raise ValueError("symbol_not_in_snapshot")
    sym = snapshot["symbols"][symbol]
    atr, entry = float(sym["atr14"]), float(sym["close"])
    if any(v != v for v in row.values()) or not (atr > 0 and entry > 0):
        raise ValueError("feature_row_unformable")
    import src.runtime.ml_entry_profile as PR
    sess = PR.session_refusal(cfg.get("session", "auto"), symbol, bc, int(br["horizon_bars"]) * 60)
    if sess:
        raise ValueError(sess)
    pred = score(row, model)
    tau = float(meta["tau"])
    if not pred > tau:
        raise ValueError(f"below_tau:pred={pred:.4f};tau={tau:.4f};bar={bc.isoformat()}")
    sl, tp = entry - float(br["sl_atr"]) * atr, entry + float(br["tp_atr"]) * atr
    if not (sl > 0 and tp > 0):
        raise ValueError("bracket_unformable")
    return {
        "symbol": symbol, "direction": "long", "entry": entry, "sl": sl, "tp": tp, "confidence": NEUTRAL_CONFIDENCE,
        "meta": {"model_id": meta.get("model_id"), "decision_bar": bc.isoformat(), "pred_net_r": round(pred, 5), "tau": tau, "atr14": atr,
                 "risk_per_unit": abs(entry - sl), "entry_time": bc.isoformat(), "tp_intent": "predictive",
                 "tp_basis": f"{float(br['tp_atr']):g} x ATR14 first-passage target the model was scored on (fixed at entry, no revision)",
                 "max_hold_min": int(br["horizon_bars"]) * 60, "pool_covered": snapshot.get("covered"), "pool_size": snapshot.get("pool_size"),
                 "features": {k: round(float(v), 6) for k, v in row.items()}},
    }


def monitor(cfg, candles_df, open_pkg):  # noqa: ARG001 -- canonical signature
    """The 24 h time stop only; never raises, never touches the snapshot or any pool fetch."""
    try:
        from datetime import datetime, timezone
        from src.units.strategies.claude_desk import max_hold_verdict
        return max_hold_verdict(open_pkg, datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001 -- a monitor must never raise
        logger.debug("ml_entry_eq.monitor: verdict failed", exc_info=True)
        return None
