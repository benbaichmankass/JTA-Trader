"""Stale-while-revalidate snapshots for slow Tier-1 read routes (UI-UPGRADE-1).

Measured 2026-10-11 from a web session against the public API: the
Overview's ``/api/bot/positions?include_paper=true`` took **5-12 s** cold
(one serial broker read per open row on the single-worker account-read
executor) and ``/api/bot/work/brief`` **16 s** (a full brief render). Both
already had a short TTL cache, so every request after it expired paid the full
cost again IN THE REQUEST PATH, and the SPA's ``Promise.all`` held the whole
page on the slowest call.

This keeps the last good value and serves it while ONE background refresh runs:

* ``age <= fresh_s``  -> served as is (``state="fresh"``).
* ``age <= stale_s``  -> served at once (``state="stale"``) and a single
  background refresh is started if none is running.
* older, or nothing cached -> built in the request (``state="built"``); callers
  that arrive while that build runs wait for it rather than starting another.

A failed background refresh is logged and the previous value is kept; its age
keeps growing, so it ages out to a foreground build after ``stale_s`` instead
of being served forever. A failed FOREGROUND build raises to the caller exactly
as the uncached route did — this layer never turns a failure into a value.

Every value carries its age, so a route can tell the client how old the
snapshot is (``X-Snapshot-Age-S``) rather than presenting it as live.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Hashable

logger = logging.getLogger(__name__)

FRESH = "fresh"
STALE = "stale"
BUILT = "built"


@dataclass
class _Entry:
    value: Any
    at: float


@dataclass
class SWRCache:
    """One named cache. ``clock`` is injectable for tests."""

    name: str
    fresh_s: float
    stale_s: float
    clock: Callable[[], float] = time.monotonic
    _data: dict[Hashable, _Entry] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _sync_inflight: dict[Hashable, threading.Event] = field(default_factory=dict)
    _async_inflight: dict[Hashable, "asyncio.Task[Any]"] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 <= self.fresh_s <= self.stale_s:
            raise ValueError(f"{self.name}: need 0 <= fresh_s <= stale_s")

    # ── shared ──────────────────────────────────────────────────────────
    def _store(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._data[key] = _Entry(value, self.clock())

    def _peek(self, key: Hashable) -> tuple[_Entry | None, float]:
        with self._lock:
            ent = self._data.get(key)
        return ent, (self.clock() - ent.at) if ent else float("inf")

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    # ── sync routes (FastAPI runs `def` handlers on its threadpool) ─────
    def get(self, key: Hashable, build: Callable[[], Any]) -> tuple[Any, float, str]:
        ent, age = self._peek(key)
        if ent is not None and age <= self.fresh_s:
            return ent.value, age, FRESH
        if ent is not None and age <= self.stale_s:
            self._refresh_in_background(key, build)
            return ent.value, age, STALE
        return self._build_sync(key, build), 0.0, BUILT

    def _build_sync(self, key: Hashable, build: Callable[[], Any]) -> Any:
        with self._lock:
            ev = self._sync_inflight.get(key)
            owner = ev is None
            if owner:
                ev = self._sync_inflight[key] = threading.Event()
        if not owner:
            ev.wait()
            ent, age = self._peek(key)
            if ent is not None and age <= self.fresh_s:
                return ent.value
            # The build we waited on failed (or was a background refresh that
            # failed, leaving only an EXPIRED value): build once ourselves so
            # the caller gets a current value or the error, never the expired one.
        try:
            value = build()
            self._store(key, value)
            return value
        finally:
            if owner:
                with self._lock:
                    self._sync_inflight.pop(key, None)
                ev.set()

    def _refresh_in_background(self, key: Hashable, build: Callable[[], Any]) -> None:
        with self._lock:
            if key in self._sync_inflight:
                return
            ev = self._sync_inflight[key] = threading.Event()

        def _run() -> None:
            try:
                self._store(key, build())
            except Exception:  # noqa: BLE001  # allow-silent: logged with a stack; the previous snapshot is kept and its growing age is served beside it, so it ages out to a foreground build instead of masking the failure
                logger.warning("swr[%s]: background refresh failed for %r; keeping previous snapshot",
                               self.name, key, exc_info=True)
            finally:
                with self._lock:
                    self._sync_inflight.pop(key, None)
                ev.set()

        threading.Thread(target=_run, name=f"swr-{self.name}", daemon=True).start()

    # ── async routes ─────────────────────────────────────────────────────
    async def aget(self, key: Hashable,
                   build: Callable[[], Awaitable[Any]]) -> tuple[Any, float, str]:
        ent, age = self._peek(key)
        if ent is not None and age <= self.fresh_s:
            return ent.value, age, FRESH
        if ent is not None and age <= self.stale_s:
            if key not in self._async_inflight:
                task = asyncio.ensure_future(self._abuild(key, build))
                self._async_inflight[key] = task
                task.add_done_callback(self._make_bg_done(key))
            return ent.value, age, STALE
        task = self._async_inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(self._abuild(key, build))
            self._async_inflight[key] = task
            task.add_done_callback(lambda _t, k=key: self._async_inflight.pop(k, None))
        value = await asyncio.shield(task)
        return value, 0.0, BUILT

    async def _abuild(self, key: Hashable, build: Callable[[], Awaitable[Any]]) -> Any:
        value = await build()
        self._store(key, value)
        return value

    def _make_bg_done(self, key: Hashable) -> Callable[["asyncio.Task[Any]"], None]:
        def _done(task: "asyncio.Task[Any]") -> None:
            self._async_inflight.pop(key, None)
            if not task.cancelled() and task.exception() is not None:
                logger.warning("swr[%s]: background refresh failed for %r; keeping previous snapshot",
                               self.name, key, exc_info=task.exception())
        return _done


def snapshot_headers(age_s: float, state: str) -> dict[str, str]:
    """Headers a route sets so a client can tell how old the served value is."""
    return {"X-Snapshot-Age-S": f"{max(age_s, 0.0):.1f}", "X-Snapshot-State": state}
