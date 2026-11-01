"""ml_entry — the ML ENTRY decision model as a strategy (row ML-ENTRY-LIVE-ADAPTER; Tier 3).

One model, pooled across symbols and tied to no strategy (operator directive 2026-11-01, row ML-DECISION-MODELS): at the
close of every 4th 1h bar it decides LONG / SHORT / NOTHING for a symbol from market context alone. Evidence:
``research/results/RQ-20261101-c692-01/`` (pooled held-out PASS) and ``research/results/RQ-20261101-c692-06/`` (the same
frozen model on the bybit_2 symbols). Spec: ``docs/research/ml-decision-models-2026-11-01/DESIGN.md`` section 2.

Pure signal generator (``.claude/skills/new-strategy/SKILL.md``): no accounts, no sizing (the RiskManager sizes; this
module emits a fixed neutral confidence), no order placement. Both brackets are always set at entry: SL = 2 x ATR14,
TP = 3 x ATR14 (the reference bracket the model was scored with); a 24 h time stop rides ``meta.max_hold_min`` and is
enforced by :func:`monitor` through the same ``max_hold_verdict`` the desk uses.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pandas as pd

import src.runtime.ml_decision_features as F

logger = logging.getLogger(__name__)

NAME = "ml_entry"
ARTIFACT = Path(__file__).resolve().parents[3] / "ml" / "served" / "ml_decision_entry_v1" / "model.json"
#: The RiskManager maps ``confidence`` to a size scalar only when an account sets ``confidence_sizing`` (default
#: ``off`` -> 1.0; bybit_2 / bybit_portfolio set none, MEASURED 2026-11-01). 1.0 is the full account basis under every
#: mode, i.e. the RiskManager's default risk: this model never sizes (operator 2026-11-01 "No position sizing").
NEUTRAL_CONFIDENCE = 1.0
_CACHE: Dict[str, Any] = {}


def load_model(path: Path = ARTIFACT) -> Dict[str, Any]:
    """``{"meta": ..., "long": Booster, "short": Booster}``, cached by mtime. Raises when the artifact is unreadable."""
    import lightgbm as lgb
    st = path.stat()
    hit = _CACHE.get(str(path))
    if hit and hit[0] == st.st_mtime:
        return hit[1]
    art = json.loads(path.read_text(encoding="utf-8"))
    model = {"meta": {k: v for k, v in art.items() if k != "booster_txt"},
             "long": lgb.Booster(model_str=art["booster_txt"]["long"]),
             "short": lgb.Booster(model_str=art["booster_txt"]["short"])}
    _CACHE[str(path)] = (st.st_mtime, model)
    return model


def is_decision_bar(ts: pd.Timestamp, every_h: int) -> bool:
    """The decision is taken at the CLOSE of bar ``ts`` (bar open time) when that close lands on an ``every_h`` hour."""
    return int((ts + pd.Timedelta(hours=1)).hour) % int(every_h) == 0


def cost_r_estimate(meta: Mapping[str, Any], row: Mapping[str, float]) -> Optional[float]:
    """Estimated round-trip cost per R when the artifact declares a ``cost_gate`` (None otherwise, so v1 is untouched).
    Cost per R = (fee + slippage + funding, in bps) / 1e4 / (2 x ATR/price), so it needs only ``atr_pct`` from the feature
    row and the constant ``k_cost_x_atr`` = total round-trip bps / 20,000 fixed from the research cost stack."""
    g = meta.get("cost_gate")
    if not g:
        return None
    a = float(row[g.get("input", "atr_pct")])
    return float(g["k_cost_x_atr"]) / a if a > 0 else float("inf")


def decide(row: Mapping[str, float], model: Dict[str, Any]) -> Dict[str, Any]:
    x = pd.DataFrame([[row[k] for k in model["meta"]["features"]]], columns=model["meta"]["features"])
    p_long = float(model["long"].predict(x)[0])
    p_short = float(model["short"].predict(x)[0])
    side = "long" if p_long >= p_short else "short"
    best = p_long if side == "long" else p_short
    est = cost_r_estimate(model["meta"], row)
    gated = est is not None and est > float(model["meta"]["cost_gate"]["max_cost_r"])
    return {"p_long": p_long, "p_short": p_short, "side": side if (best > float(model["meta"]["tau"]) and not gated) else "none",
            "pred_net_r": best, "cost_r_est": est, "gated": gated}


def order_package(cfg: dict, candles_df: Optional[pd.DataFrame] = None,
                  reference_frames: Optional[Mapping[str, pd.DataFrame]] = None,
                  model: Optional[Dict[str, Any]] = None) -> dict:
    """``candles_df``: the symbol's CLOSED 1h bars (last row = decision bar). ``reference_frames``: closed 1h bars of
    the cross-sectional reference symbols (must include BTCUSDT). Raises ``ValueError`` on a non-actionable tick."""
    symbol = str(cfg.get("symbol") or "")
    if candles_df is None or len(candles_df) < F.MIN_BARS:
        raise ValueError(f"insufficient_bars:{0 if candles_df is None else len(candles_df)}")
    df = candles_df.reset_index(drop=True)
    model = model or load_model()
    meta = model["meta"]
    br = meta["bracket"]
    t = pd.Timestamp(df["ts"].iloc[-1])
    if not is_decision_bar(t, int(br["decision_every_h"])):
        raise ValueError("not_a_decision_bar")
    frames = dict(reference_frames or {})
    frames[symbol] = df
    row = F.decision_row(symbol, frames, reference=meta.get("xs_reference"))
    if row is None:
        raise ValueError("feature_row_unformable")
    n_ref = int(row.pop("_n_reference"))
    min_ref = int(cfg.get("min_reference_symbols", 40))
    if n_ref < min_ref:
        raise ValueError(f"reference_symbols:{n_ref}<{min_ref}")
    d = decide(row, model)
    if d["gated"]:
        raise ValueError(f"cost_gate:est_cost_r={d['cost_r_est']:.4f}>{float(meta['cost_gate']['max_cost_r']):g}")
    if d["side"] == "none":
        raise ValueError(f"below_tau:pred={d['pred_net_r']:.4f}")
    atr = F.atr_last(df)
    entry = float(df["close"].iloc[-1])  # next-bar open ~ this close; the venue fills at market
    s = 1.0 if d["side"] == "long" else -1.0
    sl = entry - s * float(br["sl_atr"]) * atr
    tp = entry + s * float(br["tp_atr"]) * atr
    if not (atr > 0 and sl > 0 and tp > 0):
        raise ValueError("bracket_unformable")
    pkg = {
        "symbol": symbol, "direction": d["side"], "entry": entry, "sl": sl, "tp": tp,
        "confidence": NEUTRAL_CONFIDENCE,
        "meta": {"model_id": meta.get("model_id"), "decision_bar": t.isoformat(), "p_long": round(d["p_long"], 5),
                 "p_short": round(d["p_short"], 5), "tau": meta["tau"], "atr14": atr, "n_reference": n_ref,
                 "tp_intent": "predictive", "tp_basis": f"{float(br['tp_atr']):g} x ATR14 first-passage target the model was scored on",
                 "max_hold_min": int(br["horizon_h"]) * 60,
                 "features": {k: round(float(v), 6) for k, v in row.items()}},
    }
    if d["cost_r_est"] is not None:  # only a gated artifact (v2) reports it; the v1 package meta is unchanged
        pkg["meta"]["cost_r_est"] = round(d["cost_r_est"], 5)
    return pkg


def _telemetry(candles_df: Optional[pd.DataFrame], open_pkg: dict) -> None:
    """M31 peak-R position telemetry, the same hook as e4_oi_shock_1h / squeeze_breakout_4h. Observe-only: it reads
    nothing back and cannot alter the exit. Swallows everything."""
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
        logger.debug("ml_entry: telemetry failed", exc_info=True)


def monitor(cfg, candles_df, open_pkg):  # noqa: ARG001 -- canonical signature
    """The 24 h time stop only (the model was scored hold-to-bracket with a time stop); never raises.
    Also records peak-R position telemetry (observe-only)."""
    _telemetry(candles_df, open_pkg)
    try:
        from datetime import datetime, timezone
        from src.units.strategies.claude_desk import max_hold_verdict
        return max_hold_verdict(open_pkg, datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001 -- a monitor must never raise
        logger.debug("ml_entry.monitor: verdict failed", exc_info=True)
        return None
