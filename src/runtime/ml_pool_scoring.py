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

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

POOL_SCORED_KEY = "pool_scored"
#: The legs this module knows how to score (their builder is ``_ml_entry_eq_build``; the scorer is ``ml_entry_eq.score_pool``).
SCORERS = ("ml_entry_eq", "ml_entry_eq_struct")

_lock = threading.Lock()
_CACHE: Dict[str, tuple] = {}          # leg -> (key, results)

#: The decided memo is PERSISTED (row ML-ENTRY-EQ-RESTART-REDECIDE, Tier 2): it used to live only in memory, so every trader restart within
#: ``max_snapshot_age_h`` of a decision close re-decided that close (MEASURED 2026-11-11 journal: ``pool_scored bar=2026-11-11T20:00`` logged by four
#: processes at 21:11, 21:24, 22:01, 22:22Z). A close is now decided exactly once across restarts. This restores the intended behaviour; it adds no
#: refusal (a symbol that was never decided at a close decides normally).
DECIDED_DIR_ENV = "ML_POOL_DECIDED_DIR"
#: How many distinct decision closes the memo keeps per leg (memory and file). 16 closes x ~173 symbols stays under the builder's 4096 prune.
KEEP_CLOSES = 16


def decided_path(name: str) -> Path:
    env = os.environ.get(DECIDED_DIR_ENV)
    if env:
        return Path(env) / f"decided_{name}.json"
    from src.utils.paths import data_dir
    return Path(data_dir()) / "ml_entry_eq" / f"decided_{name}.json"


def _close_key(bar_close: Any) -> Any:
    try:
        import pandas as pd
        return (0, pd.Timestamp(str(bar_close)).value)
    except Exception:  # noqa: BLE001 -- an unparseable close sorts first (pruned first), never raises
        return (-1, str(bar_close))


class DecidedMemo(set):
    """``{(symbol, bar_close)}`` already emitted / decided for one leg, loaded from and written to ``decided_path(name)``.

    Lazy: the file is read on first use (so the path resolves in the running process's environment). Every mutation rewrites the file atomically.
    A read or write failure is logged and contained: the memo keeps working in memory (never a halt, never a refusal)."""

    def __init__(self, name: str):
        super().__init__()
        self.name = str(name)
        self._loaded = False

    def _ensure(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        p = decided_path(self.name)
        try:
            if p.exists():
                raw = json.loads(p.read_text())
                for row in raw.get("decided") or []:
                    if isinstance(row, (list, tuple)) and len(row) == 2:
                        set.add(self, (str(row[0]), str(row[1])))
                logger.info("%s decided memo loaded: %d entries over %d closes from %s", self.name, set.__len__(self),
                            len({m[1] for m in set.__iter__(self)}), p)
        except Exception:  # noqa: BLE001
            logger.exception("%s decided memo: could not read %s (memory-only until the next write)", self.name, p)

    def _persist(self) -> None:
        closes = sorted({m[1] for m in set.__iter__(self)}, key=_close_key)
        if len(closes) > KEEP_CLOSES:
            old = set(closes[:-KEEP_CLOSES])
            for m in [m for m in set.__iter__(self) if m[1] in old]:
                set.discard(self, m)
        p = decided_path(self.name)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(json.dumps({"leg": self.name, "decided": sorted([list(m) for m in set.__iter__(self)])}))
            os.replace(tmp, p)
        except Exception:  # noqa: BLE001
            logger.exception("%s decided memo: could not write %s (kept in memory)", self.name, p)

    def __contains__(self, item: object) -> bool:
        self._ensure()
        return set.__contains__(self, item)

    def __iter__(self):
        self._ensure()
        return set.__iter__(self)

    def __len__(self) -> int:
        self._ensure()
        return set.__len__(self)

    def add(self, item) -> None:
        self.update((item,))

    def update(self, *items) -> None:
        self._ensure()
        before = set.__len__(self)
        for it in items:
            for m in it:
                set.add(self, (str(m[0]), str(m[1])))
        if set.__len__(self) != before:
            self._persist()

    def discard(self, item) -> None:
        self._ensure()
        if set.__contains__(self, item):
            set.discard(self, item)
            self._persist()

    def clear(self) -> None:
        self._loaded = True
        set.clear(self)
        self._persist()

    def forget_in_memory(self) -> None:
        """Drop the in-memory state WITHOUT touching the file: what a process restart does (tests use it to simulate one)."""
        set.clear(self)
        self._loaded = False


_DECIDED: Dict[str, DecidedMemo] = {n: DecidedMemo(n) for n in SCORERS}   # shared with the builder
#: ``{(symbol, bar_close)}`` the POOL refused when it was first scored at that close (persisted the same way). Kept apart from ``_DECIDED`` so a
#: refused symbol's pass still reports its own refusal reason; it only stops a restarted process (e.g. on a new artifact) from turning an
#: already-refused close into a late package.
_REFUSED: Dict[str, DecidedMemo] = {n: DecidedMemo(f"{n}_refused") for n in SCORERS}


def decided_set(name: str) -> DecidedMemo:
    return _DECIDED.setdefault(str(name), DecidedMemo(str(name)))


def refused_set(name: str) -> DecidedMemo:
    return _REFUSED.setdefault(str(name), DecidedMemo(f"{name}_refused"))


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
    # Every symbol REFUSED at this close was decided at this close; recording it (persisted) means a restart -- possibly with a new artifact --
    # cannot turn an already-decided close into a late package. A close first scored after a restart records nothing new for symbols already
    # recorded, and packages are recorded in ``_DECIDED`` when the builder emits them.
    refused = refused_set(name)
    bc = str(snap.get("bar_close"))
    refused.update((s, bc) for s, v in res.items() if isinstance(v, str) and (s, bc) not in refused and (s, bc) not in decided_set(name))
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
            done, refused = decided_set(name), refused_set(name)
            for s, v in res.items():
                m = (s, snap["bar_close"])
                if isinstance(v, dict) and m not in done and m not in refused:
                    scored[s] = max(scored.get(s, float("-inf")), float(v["meta"]["pred_net_r"]))
        return [s for s, _p in sorted(scored.items(), key=lambda kv: -kv[1])]
    except Exception:  # noqa: BLE001 -- a scoring fault must never break the tick; the leg just gets no extra passes this tick
        logger.exception("ml_pool_scoring.picks failed (no pool picks this tick)")
        return []
