"""Slice allocation — split one (account, symbol) risk budget across strategies.

Checklist row NETTED-SLICES. Operator, verbatim, 2026-10-15:

    "We can have different strategies working with netted positions as long as
    we know how much of that position belongs to each strategy, and each piece
    of that position has its own brackets. ... We don't need to collapse it, we
    just need to make sure we know how to allocate between the trades
    correctly. And it should be based on those other things, not just
    backtesting. It's just that backtesting is also a parameter here."

and earlier: *"If we're running the same strategy and symbol on 2 different
timeframes, than we need to make sure that we know how to allocate the trades
properly (and not, say alphabetically)"*.

This replaces the pick-one election ONLY on accounts that declare
``position_model: slices`` (:func:`account_uses_slices`). Every other account
still elects one strategy per symbol per tick through ``intents.elect_from_gated``.

Two halves, both pure apart from the cached data reads:

* :func:`score_candidate` — the score, from four terms in ``[0, 1]`` weighted by
  ``config/slice_allocation.yaml`` (the formula and why each term is what it is
  is in that file's header, which is the one place to change it — Tier-3).
* :func:`allocation_weights` — ``score_i / Σ score`` over one account's
  contenders. Equal scores get equal shares; a strategy's NAME never moves a
  weight. If every score is zero or unreadable the split is EQUAL and the
  returned basis says so (``equal_split_last_resort``) — labelled, not hidden.

The budget arithmetic that turns a weight into a quantity lives in
:func:`slice_qty`, called by the coordinator after the RiskManager has sized the
trade, so a slice can never exceed the per-trade size the RiskManager approved.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

POSITION_MODEL_KEY = "position_model"
POSITION_MODEL_SLICES = "slices"

#: Package meta key the planner writes and the coordinator reads.
SLICE_ALLOCATION_META_KEY = "slice_allocation"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "config" / "slice_allocation.yaml"
_EVIDENCE_DIR = _REPO_ROOT / "comms" / "strategy_evidence"

#: Used only when the YAML cannot be read. Mirrors config/slice_allocation.yaml;
#: tests/test_slice_allocation.py pins the two equal so they cannot drift.
_DEFAULT_CONFIG: Dict[str, Any] = {
    "weights": {"confidence": 0.4, "backtest": 0.3, "live": 0.2, "regime": 0.1},
    "live_window_trades": 30,
    "symbol_budget_trades": 1.0,
}

NEUTRAL = 0.5

_CFG_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None
_CFG_TTL_S = 300.0
_LIVE_CACHE: Optional[Tuple[float, Dict[str, Tuple[int, int]]]] = None
_LIVE_TTL_S = 300.0
_BT_CACHE: Dict[str, Tuple[float, Tuple[float, str]]] = {}


def account_uses_slices(account_cfg: Optional[Mapping[str, Any]]) -> bool:
    """True when the account declares ``position_model: slices``."""
    if not isinstance(account_cfg, Mapping):
        return False
    return str(account_cfg.get(POSITION_MODEL_KEY) or "").strip().lower() == POSITION_MODEL_SLICES


def load_config(force: bool = False) -> Dict[str, Any]:
    """The allocation config, TTL-cached. Falls back to the pinned defaults
    (and logs) when the file cannot be read — a missing file must not strand a
    tick, and the defaults are the same numbers the file carries."""
    global _CFG_CACHE
    now = time.monotonic()
    if not force and _CFG_CACHE is not None and now - _CFG_CACHE[0] < _CFG_TTL_S:
        return _CFG_CACHE[1]
    cfg: Dict[str, Any] = {k: (dict(v) if isinstance(v, dict) else v)
                           for k, v in _DEFAULT_CONFIG.items()}
    try:
        import yaml  # type: ignore

        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        if isinstance(raw.get("weights"), dict):
            cfg["weights"] = {
                k: float(raw["weights"].get(k, 0.0) or 0.0)
                for k in _DEFAULT_CONFIG["weights"]
            }
        if raw.get("live_window_trades") is not None:
            cfg["live_window_trades"] = max(1, int(raw["live_window_trades"]))
        if raw.get("symbol_budget_trades") is not None:
            cfg["symbol_budget_trades"] = max(0.0, float(raw["symbol_budget_trades"]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("slice_allocation: config unreadable (%s) — using pinned defaults", exc)
    _CFG_CACHE = (now, cfg)
    return cfg


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _finite(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ── the four terms ──────────────────────────────────────────────────────────


def confidence_term(candidate: Any) -> Tuple[float, str]:
    v = _finite(getattr(candidate, "confidence", None))
    if v is None:
        return NEUTRAL, "unreadable"
    return _clamp01(v), "measured"


def backtest_term(strategy: str, *, evidence_dir: Optional[Path] = None) -> Tuple[float, str]:
    """``0.5 + expectancy_r_oos`` from the leg's committed evidence record.

    Only ``coverage_state: measured`` counts. ``no_record`` / any other state is
    NEUTRAL 0.5: an absent record is a statement about us, never about the leg
    (comms/strategy_evidence/README.md).
    """
    if evidence_dir is None:
        hit = _BT_CACHE.get(strategy)
        if hit is not None and time.monotonic() - hit[0] < _CFG_TTL_S:
            return hit[1]
        out = _backtest_term_uncached(strategy, _EVIDENCE_DIR)
        _BT_CACHE[strategy] = (time.monotonic(), out)
        return out
    return _backtest_term_uncached(strategy, evidence_dir)


def _backtest_term_uncached(strategy: str, evidence_dir: Path) -> Tuple[float, str]:
    path = evidence_dir / f"{strategy}.json"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
    except FileNotFoundError:
        return NEUTRAL, "no_record"
    except Exception:  # noqa: BLE001
        return NEUTRAL, "unreadable"
    if str(rec.get("coverage_state") or "") != "measured":
        return NEUTRAL, f"coverage_{rec.get('coverage_state') or 'unknown'}"
    exp = _finite(rec.get("expectancy_r_oos"))
    if exp is None:
        return NEUTRAL, "no_expectancy"
    return _clamp01(NEUTRAL + exp), "measured"


def _live_counts(window: int, db_path: Optional[str] = None) -> Dict[str, Tuple[int, int]]:
    """``{strategy: (wins, n)}`` over each leg's last *window* closed live trades."""
    global _LIVE_CACHE
    now = time.monotonic()
    use_cache = db_path is None
    if use_cache and _LIVE_CACHE is not None and now - _LIVE_CACHE[0] < _LIVE_TTL_S:
        return _LIVE_CACHE[1]
    out: Dict[str, Tuple[int, int]] = {}
    try:
        if db_path is None:
            from src.utils.paths import trade_journal_db_path
            db_path = trade_journal_db_path()
        if not db_path or not os.path.exists(db_path):
            return out
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        try:
            rows = conn.execute(
                "SELECT strategy_name, pnl FROM ("
                "  SELECT strategy_name, pnl, ROW_NUMBER() OVER ("
                "    PARTITION BY strategy_name ORDER BY id DESC) AS rn"
                "  FROM trades WHERE status = 'closed' AND pnl IS NOT NULL"
                "  AND COALESCE(is_backtest, 0) = 0 AND strategy_name IS NOT NULL"
                ") WHERE rn <= ?",
                (int(window),),
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("slice_allocation: live track record unreadable: %s", exc)
        return out
    for name, pnl in rows:
        w, n = out.get(str(name), (0, 0))
        out[str(name)] = (w + (1 if float(pnl) > 0 else 0), n + 1)
    if use_cache:
        _LIVE_CACHE = (now, out)
    return out


def live_term(strategy: str, counts: Mapping[str, Tuple[int, int]]) -> Tuple[float, str]:
    """Laplace-smoothed live win rate ``(wins + 1) / (n + 2)``; 0.5 with no trades."""
    wins, n = counts.get(str(strategy), (0, 0))
    if n <= 0:
        return NEUTRAL, "no_trades"
    return (wins + 1.0) / (n + 2.0), "measured"


def regime_term(candidate: Any, policy: Optional[Mapping[str, Any]] = None) -> Tuple[float, str]:
    """1.0 on an EXPLICIT ``on`` cell for the intent's regime and side, else 0.5."""
    try:
        if policy is None:
            from src.runtime.intents import _load_regime_policy
            policy = _load_regime_policy()
        if not policy:
            return NEUTRAL, "policy_unreadable"
        from src.runtime.regime import would_gate
        verdict = would_gate(
            strategy=str(getattr(candidate, "strategy", "") or ""),
            side=str(getattr(candidate, "side", "") or ""),
            regime=getattr(candidate, "regime", None),
            policy=dict(policy),
        )
    except Exception:  # noqa: BLE001
        return NEUTRAL, "unreadable"
    if verdict.get("cell") == "on":
        return 1.0, "explicit_on"
    return NEUTRAL, str(verdict.get("cell") or "default-on")


def score_candidate(
    candidate: Any,
    *,
    config: Optional[Mapping[str, Any]] = None,
    live_counts: Optional[Mapping[str, Tuple[int, int]]] = None,
    regime_policy: Optional[Mapping[str, Any]] = None,
    evidence_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """``{"score": float, "terms": {name: (value, state)}}`` for one intent."""
    cfg = config or load_config()
    weights = dict(cfg.get("weights") or _DEFAULT_CONFIG["weights"])
    strategy = str(getattr(candidate, "strategy", "") or "")
    if live_counts is None:
        live_counts = _live_counts(int(cfg.get("live_window_trades") or 30))
    terms = {
        "confidence": confidence_term(candidate),
        "backtest": backtest_term(strategy, evidence_dir=evidence_dir),
        "live": live_term(strategy, live_counts),
        "regime": regime_term(candidate, regime_policy),
    }
    wsum = sum(max(0.0, float(weights.get(k, 0.0))) for k in terms)
    if wsum <= 0:
        score = NEUTRAL
    else:
        score = sum(max(0.0, float(weights.get(k, 0.0))) * terms[k][0] for k in terms) / wsum
    return {"score": round(score, 6), "terms": {k: [round(v, 6), s] for k, (v, s) in terms.items()}}


def allocation_weights(scores: Mapping[str, float]) -> Tuple[Dict[str, float], str]:
    """``score_i / Σ score``. Returns ``(weights, basis)``.

    ``basis`` is ``"score"`` normally and ``"equal_split_last_resort"`` when no
    score is positive — the deterministic fallback, labelled as such. The NAME
    of a strategy never changes a weight.
    """
    clean = {k: max(0.0, _finite(v) or 0.0) for k, v in scores.items()}
    total = sum(clean.values())
    if not clean:
        return {}, "no_contenders"
    if total <= 0:
        eq = 1.0 / len(clean)
        return {k: eq for k in clean}, "equal_split_last_resort"
    return {k: v / total for k, v in clean.items()}, "score"


def slice_qty(
    *,
    sized_qty: float,
    entry: float,
    sl: float,
    weight: float,
    budget_trades: float,
    held_risk: float,
) -> Dict[str, Any]:
    """Turn a weight into a quantity, inside the symbol's risk budget.

    * ``unit_risk = sized_qty · |entry − sl|`` — the RiskManager's one-trade
      risk for this account (the per-trade cap, in quote currency).
    * ``budget = budget_trades · unit_risk``.
    * ``remaining = max(0, budget − held_risk)`` where ``held_risk`` is the
      current stop-risk of open slices held by strategies NOT contending this
      tick (contenders hold nothing of their own — the same-strategy guard).
    * ``qty = min(sized_qty, weight · remaining / |entry − sl|)``.

    Never above ``sized_qty``: a slice cannot exceed the per-trade size the
    RiskManager approved.
    """
    dist = abs(float(entry) - float(sl))
    sized = max(0.0, float(sized_qty))
    w = _clamp01(float(weight))
    if dist <= 0 or sized <= 0:
        return {"qty": 0.0, "unit_risk": 0.0, "budget": 0.0, "remaining": 0.0,
                "reason": "no_risk_distance" if dist <= 0 else "no_size"}
    unit_risk = sized * dist
    budget = max(0.0, float(budget_trades)) * unit_risk
    remaining = max(0.0, budget - max(0.0, float(held_risk)))
    qty = min(sized, w * remaining / dist)
    return {
        "qty": qty,
        "unit_risk": unit_risk,
        "budget": budget,
        "remaining": remaining,
        "reason": "budget_exhausted" if remaining <= 0 else "allocated",
    }


def reset_caches() -> None:
    """Test hook."""
    global _CFG_CACHE, _LIVE_CACHE
    _CFG_CACHE = None
    _LIVE_CACHE = None
    _BT_CACHE.clear()


__all__: Sequence[str] = (
    "POSITION_MODEL_KEY", "POSITION_MODEL_SLICES", "SLICE_ALLOCATION_META_KEY",
    "account_uses_slices", "load_config", "score_candidate", "allocation_weights",
    "slice_qty", "confidence_term", "backtest_term", "live_term", "regime_term",
)
