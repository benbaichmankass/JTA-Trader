"""venue_read_cache — let a reconciliation phase read the venue WITHOUT holding journal_sync.

Row LIVE-TICK-NEAR-BUDGET (2026-11-20, Tier 2, manager-approved design). Gates this adds or changes: none.
Nothing here decides whether anything trades; it only moves WHEN a phase's venue reads happen.

WHY. Every reconciliation phase holds ``journal_sync`` for its whole body (order_monitor._recon_phase), so
its broker I/O runs under the lock and the trader tick waits for it. MEASURED /api/diag/tick_cost, 76
ticks after the 04:41:12Z restart on 2026-11-20: main ``journal_sync.wait`` mean 6.51 s (max 15.2 s);
off-loop ``journal_sync.hold`` max 15.9 s, equal to the equity naked sweep's max (mean 9.9 s), which makes
per-row Alpaca reads (``positions``, ``protection_state``, ``protection_coverage``) under the lock.

HOW, WITHOUT BREAKING WHAT THE LOCK PROTECTS. The lock exists so a reconcile step never sees a dispatch
half-done. So:
  1. PREFETCH: the phase's venue READS run with no lock, through a :class:`Recorder`, and the venue
     generation (``journal_sync.venue_generation``) is noted.
  2. The phase body then runs under the lock with the cache active. Each cached read is served ONLY if the
     generation has not moved since the prefetch. The generation moves on every venue-mutating Alpaca call
     in this process (bumped inside the clients' ``_request``) and on every entry-dispatch / pairs release,
     so a trail amend, re-arm, cancel, live-review apply or dispatch that landed in between turns every
     cached read into a live read made under the lock: exactly today's behaviour.
  3. Writes are never cached; they go to the venue under the lock as before, and they bump the generation,
     so reads after a write in the same body are live too.
A cached read is at most as stale as a read made at the start of today's ~10 s locked phase already was.

Never raises into a phase: any failure here falls back to the live client.
"""
from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

#: The read methods this cache may serve. Everything else passes straight through.
CACHED_READS = ("positions", "protection_state", "protection_coverage")

_state = threading.local()


def _generation() -> int | None:
    try:
        from src.runtime.journal_sync import venue_generation
        return venue_generation()
    except Exception:  # noqa: BLE001
        return None


def _key(account_id: str, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple:
    def norm(v: Any) -> Any:
        if isinstance(v, dict):  # a position dict: key on what the read depends on
            return ("pos", str(v.get("symbol") or "").upper(), str(v.get("qty") or v.get("size") or ""),
                    str(v.get("side") or ""))
        return v if isinstance(v, (str, int, float, bool, type(None))) else repr(v)
    return (account_id, method, tuple(norm(a) for a in args),
            tuple(sorted((k, norm(v)) for k, v in kwargs.items())))


class Cache:
    """The reads one prefetch made, valid while the venue generation is unchanged."""

    def __init__(self) -> None:
        self.gen0 = _generation()
        self.data: dict[tuple, Any] = {}
        self.hits = 0
        self.misses = 0
        self.invalidated = 0

    def valid(self) -> bool:
        return self.gen0 is not None and _generation() == self.gen0

    def recorder(self, account_id: str, client: Any) -> Recorder:
        return Recorder(self, account_id, client)

    def stats(self) -> dict[str, Any]:
        return {"prefetched": len(self.data), "hits": self.hits, "misses": self.misses,
                "invalidated": self.invalidated}


class Recorder:
    """Calls the live client and stores each cached-read result (the unlocked prefetch)."""

    def __init__(self, cache: Cache, account_id: str, client: Any) -> None:
        self._cache, self._account, self._client = cache, account_id, client

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._client, name)
        if name not in CACHED_READS:
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            out = target(*args, **kwargs)
            self._cache.data[_key(self._account, name, args, kwargs)] = out
            return out
        return call


class CachedClient:
    """The client a locked phase body uses: cached reads while valid, live for everything else."""

    def __init__(self, cache: Cache, account_id: str, client: Any) -> None:
        self._cache, self._account, self._client = cache, account_id, client

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._client, name)
        if name not in CACHED_READS:
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            c = self._cache
            k = _key(self._account, name, args, kwargs)
            if k in c.data:
                if c.valid():
                    c.hits += 1
                    return c.data[k]
                c.invalidated += 1
            else:
                c.misses += 1
            return target(*args, **kwargs)
        return call


@contextlib.contextmanager
def active(cache: Cache | None) -> Iterator[None]:
    """Make *cache* the one :func:`wrap` serves from, for this thread, inside the block."""
    prev = getattr(_state, "cache", None)
    _state.cache = cache
    try:
        yield
    finally:
        _state.cache = prev


def wrap(account_id: str, client: Any) -> Any:
    """The client a phase body should use: cached reads when a cache is active, else the client itself."""
    if client is None:
        return None
    cache = getattr(_state, "cache", None)
    if cache is None:
        return client
    try:
        return CachedClient(cache, account_id, client)
    except Exception:  # noqa: BLE001
        return client
