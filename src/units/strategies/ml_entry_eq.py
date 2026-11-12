"""ml_entry_eq -- the EQUITY-NATIVE ENTRY model as a TESTING leg (alpaca_paper; Tier 2) and, with cfg['artifact'] + structure_exit, the ml_entry_eq_struct leg (alpaca_live + alpaca_portfolio; Tier 3).

One pooled LightGBM (config B: 15 own-symbol + 6 cross-sectional pool features, NO crypto / market-proxy feature) trained on the 173-ETF Alpaca liquidity
pool; restricted LONG when the predicted net R at the decision close exceeds tau (0.20); SL 2 x ATR14, TP 3 x ATR14, 24 h time stop. Evidence:
RQ-20261105-e9a1-02 (run 42143223941): n 858, net +0.0392 R, iid t 0.9, month-clustered t 0.3 -- a MECHANICS soak, not an edge claim. Real money is the
operator's call. Spec: docs/research/ml-entry-eq-serve-spec-2026-11-06.md.

Pure signal generator (.claude/skills/new-strategy/SKILL.md): no accounts, no sizing (neutral confidence), no order placement, and NO NETWORK: every
input comes from the pool snapshot the refresher wrote (src/runtime/ml_entry_eq_refresher.py). The exit path never calls the feature builder: the bracket
is fixed at entry (no TP revision, no re-scoring), :func:`monitor` only enforces the 24 h time stop.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd

import src.runtime.ml_entry_eq_features as F

logger = logging.getLogger(__name__)

NAME = "ml_entry_eq"
STRUCT_NAME = "ml_entry_eq_struct"   # the structure-exit 5-seed-ensemble leg (RQ-20261107-98e3-06); same module, own artifact via cfg["artifact"]
REPO = Path(__file__).resolve().parents[3]
ARTIFACT = Path(__file__).resolve().parents[3] / "ml" / "candidates" / "ml_entry_eq_v1" / "model.json"
NEUTRAL_CONFIDENCE = 1.0
_CACHE: Dict[str, Any] = {}


def artifact_path(cfg: Optional[Mapping[str, Any]] = None) -> Path:
    """The leg's artifact: ``cfg['artifact']`` (repo-relative) when declared, else the default (the fixed-bracket leg's, unchanged)."""
    a = (cfg or {}).get("artifact")
    return (REPO / str(a)) if a else ARTIFACT


def load_model(path: Path = ARTIFACT) -> Dict[str, Any]:
    """``{"meta": ..., "boosters": [Booster, ...], "long": boosters[0]}``, cached by mtime. ``booster_txt.long`` is one text (v1) or a list (an
    ensemble: schema /2); sha256 of the concatenated texts must equal ``booster_sha256`` or this raises. Raises when the artifact is unreadable."""
    import lightgbm as lgb
    st = path.stat()
    hit = _CACHE.get(str(path))
    if hit and hit[0] == st.st_mtime:
        return hit[1]
    art = json.loads(path.read_text(encoding="utf-8"))
    raw = art["booster_txt"]["long"]
    texts = list(raw) if isinstance(raw, list) else [raw]
    if hashlib.sha256("".join(texts).encode()).hexdigest() != art.get("booster_sha256"):
        raise ValueError(f"{path.name}: booster sha256 does not match the artifact's booster_sha256")
    boosters = [lgb.Booster(model_str=t) for t in texts]
    model = {"meta": {k: v for k, v in art.items() if k != "booster_txt"}, "boosters": boosters, "long": boosters[0]}
    _CACHE[str(path)] = (st.st_mtime, model)
    return model


def pool_symbols() -> List[str]:
    return [str(s) for s in load_model()["meta"]["pool_symbols"]]


def score_rows(rows: List[Mapping[str, float]], model: Dict[str, Any]) -> List[float]:
    """Mean-of-boosters prediction for MANY rows in one predict call per booster (a row's prediction does not depend on the other rows)."""
    if not rows:
        return []
    cols = model["meta"]["features"]
    x = pd.DataFrame([[r[k] for k in cols] for r in rows], columns=cols)
    bs = model.get("boosters") or [model["long"]]
    preds = sum(b.predict(x).astype(float) for b in bs) / len(bs)  # provenance: predict -- live decision scoring (mean of the N boosters)
    return [float(v) for v in preds]


def score(row: Mapping[str, float], model: Dict[str, Any]) -> float:
    return score_rows([row], model)[0]


def _precheck(cfg: Mapping[str, Any], snapshot: Mapping[str, Any], symbol: str, meta: Mapping[str, Any]) -> Dict[str, Any]:
    """Everything before the model call for ONE symbol: the feature row, ATR/close and the session refusal. Raises ``ValueError(<named reason>)``."""
    br = meta["bracket"]
    bc = pd.Timestamp(snapshot["bar_close"])
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
    return {"row": row, "atr": atr, "entry": entry}


def _package(cfg: Mapping[str, Any], snapshot: Mapping[str, Any], symbol: str, meta: Mapping[str, Any], pre: Mapping[str, Any], pred: float) -> dict:
    """The LONG package for one pre-checked symbol and its model score, or ``ValueError(<named reason>)``."""
    br = meta["bracket"]
    bc = pd.Timestamp(snapshot["bar_close"])
    row, atr, entry = pre["row"], pre["atr"], pre["entry"]
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
                 # declared structure exit (SL-only): absent = no key, byte-identical for the fixed-bracket leg
                 **({"structure_exit": cfg["structure_exit"]} if cfg.get("structure_exit") else {}),
                 "max_hold_min": int(br["horizon_bars"]) * 60, "pool_covered": snapshot.get("covered"), "pool_size": snapshot.get("pool_size"),
                 "features": {k: round(float(v), 6) for k, v in row.items()}},
    }


def score_pool(cfg: Mapping[str, Any], snapshot: Mapping[str, Any], symbols: List[str], model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Score EVERY symbol in ``symbols`` at the snapshot's decision close in ONE batched predict per booster (row ML-ENTRY-EQ-STRUCT-FULL-POOL).

    Returns ``{symbol: package_dict | "<named refusal reason>"}`` -- the same packages and the same reasons ``order_package`` gives one symbol at a
    time (``order_package`` IS this function on one symbol, so the two cannot drift). Raises ``ValueError("not_a_decision_bar")`` for the whole pool
    when the snapshot's close is not a decision close. A booster's prediction for a row does not depend on the other rows in the batch."""
    model = model or load_model(artifact_path(cfg))
    meta = model["meta"]
    if not F.is_decision_close(pd.Timestamp(snapshot["bar_close"])):
        raise ValueError("not_a_decision_bar")
    out: Dict[str, Any] = {}
    pres: Dict[str, Dict[str, Any]] = {}
    for s in symbols:
        try:
            pres[str(s)] = _precheck(cfg, snapshot, str(s), meta)
        except ValueError as exc:
            out[str(s)] = str(exc)
    if pres:
        names = list(pres)
        preds = score_rows([pres[s]["row"] for s in names], model)
        for s, p in zip(names, preds):
            try:
                out[s] = _package(cfg, snapshot, s, meta, pres[s], float(p))
            except ValueError as exc:
                out[s] = str(exc)
    return out


def order_package(cfg: dict, snapshot: Mapping[str, Any], model: Optional[Dict[str, Any]] = None) -> dict:
    """The LONG package for ``cfg['symbol']`` from the pool snapshot, or ``ValueError(<named reason>)`` for a non-actionable tick."""
    symbol = str(cfg.get("symbol") or "")
    res = score_pool(cfg, snapshot, [symbol], model)[symbol]
    if isinstance(res, str):
        raise ValueError(res)
    return res


def monitor(cfg, candles_df, open_pkg):  # noqa: ARG001 -- canonical signature
    """The 24 h time stop; for a package that declares ``structure_exit`` (ml_entry_eq_struct) also the SL-ONLY structure verdict (the stop only tightens;
    a ``structure_sl_cross`` closes) merged after it, via ml_entry.py's helpers. Never raises, never touches the snapshot or any pool fetch."""
    base = None
    try:
        from datetime import datetime, timezone
        from src.units.strategies.claude_desk import max_hold_verdict
        base = max_hold_verdict(open_pkg, datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001 -- a monitor must never raise
        logger.debug("ml_entry_eq.monitor: verdict failed", exc_info=True)
    if isinstance(base, dict) and base.get("action") == "close":
        return base
    try:
        from src.units.strategies import ml_entry as ME
        sx = ME.structure_verdict(open_pkg, candles_df)
        if sx is ME._NOT_DECLARED:
            return base
        return ME.merge_structure_sl(base, sx)
    except Exception:  # noqa: BLE001 -- a monitor must never raise
        logger.debug("ml_entry_eq.monitor: structure verdict failed", exc_info=True)
        return base
