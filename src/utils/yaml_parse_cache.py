"""Memoize ``yaml.safe_load`` by the EXACT TEXT parsed (TICK-DURATION-115S).

WHY. The live trader re-parses ``config/strategies.yaml`` (217 KB) with
pure-Python ``yaml.safe_load`` inside the per-symbol signal build: a local
cProfile of ``multiplexed_intent_signal_builder`` over 3 symbols
(BTCUSDT/ETHUSDT/SPY/SOLUSDT harness, candle fetches stubbed) measured 43
``load_strategy_config`` calls = 15.1 s of 16.7 s profiled (90%), i.e. ~14
full parses per symbol at ~100-125 ms each unprofiled. ``/api/diag/tick_cost``
on 2026-11-04T23:22Z (37 ticks) put ``pipeline.signal_build`` at 851 calls x
2.04 s mean while the candle fetches nested inside it averaged ~0.22 s per
call: the other ~1.8 s per call is this parse.

WHAT THIS CHANGES, AND WHY NO DECISION CAN CHANGE.

* Callers still OPEN AND READ the file on every call, exactly as before, so an
  edit (``ict-git-sync`` pulling ``main``) is seen on the very next call, as
  before. Only the PARSE of a text already parsed is skipped.
* ``yaml.safe_load`` is a pure function of its input text. The cache key is a
  SHA-256 over that exact text, so a hit returns the parse of byte-identical
  input — the same value a fresh parse would return.
* Every hit returns ``copy.deepcopy`` of the cached tree, so a caller that
  mutates what it got (adds a default, pops a key) can never leak that into
  another caller's view. ``deepcopy`` preserves the aliasing YAML anchors
  create, so the copy is structurally what a fresh parse returns. Measured
  ~0.6 ms per copy of the strategies tree vs ~100-125 ms per parse.
* Same loader (``yaml.safe_load``), not ``CSafeLoader``: no parser swap, so
  there is no edge case where two parsers disagree.
* Parse ERRORS are never cached: a text that fails to parse raises on every
  call, exactly as before.

Thread-safe (the exit-evaluation loop runs on its own thread). Bounded: at
most ``_MAX_ENTRIES`` distinct texts are held (oldest evicted), so a file that
changes every few minutes cannot grow memory.
"""

from __future__ import annotations

import copy
import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any

_MAX_ENTRIES = 32
_lock = threading.Lock()
_cache: OrderedDict[str, Any] = OrderedDict()
_stats = {"hits": 0, "misses": 0}


def _record(name: str, elapsed_ms: float) -> None:
    """Fold into ``/api/diag/tick_cost`` so the deployed effect is observable:
    ``config.yaml_parse`` (misses: real parses) vs ``config.yaml_cache_hit``.
    Uses ``record_hook`` directly, not ``hook()``, so these leaves never
    overwrite the current-phase attribution of an enclosing fetch. Dotted
    names, so they never count toward ``attributed_pct``. Never raises."""
    try:
        from src.runtime.tick_cost import record_hook
        record_hook(name, elapsed_ms)
    except Exception:  # noqa: BLE001 -- measurement must never break a caller
        pass


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def safe_load_text(text: str) -> Any:
    """``yaml.safe_load(text)``, memoized by the exact text; returns a deep copy."""
    import yaml

    k = _key(text)
    with _lock:
        if k in _cache:
            _cache.move_to_end(k)
            _stats["hits"] += 1
            tree = _cache[k]
            hit = True
        else:
            hit = False
    if hit:
        t0 = time.monotonic()
        out = copy.deepcopy(tree)
        _record("config.yaml_cache_hit", (time.monotonic() - t0) * 1000.0)
        return out
    t0 = time.monotonic()
    parsed = yaml.safe_load(text)  # raises exactly as before; never cached on error
    _record("config.yaml_parse", (time.monotonic() - t0) * 1000.0)
    with _lock:
        _stats["misses"] += 1
        _cache[k] = parsed
        _cache.move_to_end(k)
        while len(_cache) > _MAX_ENTRIES:
            _cache.popitem(last=False)
    return copy.deepcopy(parsed)


def safe_load_path(path: Any) -> Any:
    """Read *path* (UTF-8 text mode, as the callers did) then ``safe_load_text``.

    Raises ``FileNotFoundError`` / ``OSError`` exactly as ``open()`` would.
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return safe_load_text(text)


def stats() -> dict:
    with _lock:
        return {**_stats, "entries": len(_cache)}


def clear() -> None:
    with _lock:
        _cache.clear()
        _stats["hits"] = 0
        _stats["misses"] = 0
