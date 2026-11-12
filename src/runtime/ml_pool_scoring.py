"""Score an ML leg's WHOLE POOL once per decision close (row ML-ENTRY-EQ-STRUCT-FULL-POOL; Tier 2).

WHY: a leg that trades a 171-ETF population cannot afford one ``_run_symbol_tick`` pass per symbol per tick (each pass fetches candles and runs every
rostered builder; MEASURED 2026-11-11 on /api/diag/tick_cost: ~1.2 s per symbol pass, run_one_tick mean 27 s over 343 ticks, so +171 passes would add
~200 s to every tick -- the fan-out #23619 warned about). The ``ml_entry_eq*`` legs need no candles on the tick at all: every input is in the pool
snapshot the refresher writes (src/runtime/ml_entry_eq_refresher.py). So:

* :func:`batch` scores every symbol the leg declares in ONE batched predict per booster, once per (leg, snapshot bar_close, artifact), and caches the
  result; the signal builder reads it instead of scoring per symbol.
* :func:`picks` returns the symbols that have an actionable package at the current decision close and have not been emitted yet, strongest prediction
  first. ``src/main.py::_resolve_tick_symbols`` gives a tick pass ONLY to those of a ``pool_scored`` leg's symbols that no other source already ticks
  (so a pool symbol with no package costs nothing). This narrows nothing: a symbol without a package would have emitted ``side=none`` on its pass.

``pool_scored: true`` in config/strategies.yaml declares this dispatch mode for a leg. It is NOT a gate: it changes which symbols get a pass, never
whether a leg with a package trades. A failure here is contained (logged, ``picks`` returns []), never a halt.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

POOL_SCORED_KEY = "pool_scored"
#: The legs this module knows how to score (their builder is ``_ml_entry_eq_build``; the scorer is ``ml_entry_eq.score_pool``).
SCORERS = ("ml_entry_eq", "ml_entry_eq_struct")

_lock = threading.Lock()
_CACHE: Dict[str, tuple] = {}          # leg -> (key, results)
_DECIDED: Dict[str, set] = {n: set() for n in SCORERS}   # leg -> {(symbol, bar_close)} already emitted / decided (shared with the builder)


def decided_set(name: str) -> set:
    return _DECIDED.setdefault(str(name), set())


def is_pool_scored(cfg: Optional[Mapping[str, Any]]) -> bool:
    return bool((cfg or {}).get(POOL_SCORED_KEY, False))


def batch(name: str, vcfg: Mapping[str, Any], snap: Mapping[str, Any], symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """``{symbol: package | reason}`` for every symbol the leg declares (``vcfg['symbols']``, or ``symbols``) at ``snap['bar_close']``.

    Cached per (leg, bar_close, artifact, symbol list). Raises ``ValueError('not_a_decision_bar')`` (not cached) when the snapshot's close is not a
    decision close; raises whatever ``load_model`` raises when the artifact is unreadable (the caller turns that into a named refusal)."""
    from src.units.strategies import ml_entry_eq as L
    syms = [str(s) for s in (symbols if symbols is not None else (vcfg.get("symbols") or []))]
    art = str(L.artifact_path(vcfg))
    key = (str(snap.get("bar_close")), art, tuple(syms), str(vcfg.get("session", "auto")), str(vcfg.get("structure_exit") or ""))
    with _lock:
        hit = _CACHE.get(name)
        if hit and hit[0] == key:
            return hit[1]
    res = L.score_pool(dict(vcfg), snap, syms)
    n_pkg = sum(1 for v in res.values() if isinstance(v, dict))
    top = sorted(((v["meta"]["pred_net_r"], s) for s, v in res.items() if isinstance(v, dict)), reverse=True)[:10]
    reasons: Dict[str, int] = {}
    for v in res.values():
        if isinstance(v, str):
            r = v.split(":", 1)[0]
            reasons[r] = reasons.get(r, 0) + 1
    logger.info("%s pool_scored bar=%s scored=%d packages=%d top=%s refusals=%s", name, snap.get("bar_close"), len(res), n_pkg,
                ",".join(f"{s}:{p:.3f}" for p, s in top) or "-", reasons or "-")
    with _lock:
        _CACHE[name] = (key, res)
    return res


def picks(strategies_cfg: Mapping[str, Any], legs: Optional[List[str]] = None) -> List[str]:
    """Symbols of the enabled ``pool_scored`` legs (``legs`` restricts to the ones rostered on a trading account) that hold an actionable package at
    the current snapshot's decision close and have not been decided yet, strongest predicted net R first. Never raises: [] on any failure."""
    try:
        import pandas as pd
        from src.runtime import ml_entry_eq_features as EF
        from src.runtime.ml_entry_eq_refresher import snapshot_path
        scored: Dict[str, float] = {}
        for name in SCORERS:
            vcfg = (strategies_cfg or {}).get(name) or {}
            if legs is not None and name not in legs:
                continue
            if not (is_pool_scored(vcfg) and bool(vcfg.get("enabled", False))):
                continue
            snap, _why = EF.read_snapshot(snapshot_path(), pd.Timestamp.now(tz="UTC"), max_age_h=float(vcfg.get("max_snapshot_age_h", 4.0)))
            if snap is None:
                continue
            try:
                res = batch(name, vcfg, snap)
            except ValueError:
                continue                                  # not a decision bar (or an unreadable artifact): no picks this tick
            done = decided_set(name)
            for s, v in res.items():
                if isinstance(v, dict) and (s, snap["bar_close"]) not in done:
                    scored[s] = max(scored.get(s, float("-inf")), float(v["meta"]["pred_net_r"]))
        return [s for s, _p in sorted(scored.items(), key=lambda kv: -kv[1])]
    except Exception:  # noqa: BLE001 -- a scoring fault must never break the tick; the leg just gets no extra passes this tick
        logger.exception("ml_pool_scoring.picks failed (no pool picks this tick)")
        return []
