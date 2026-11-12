"""``GET /api/bot/stream`` -- one push stream for the trading dashboard (UI-TRADING-PUSH, step T1).

Design: ``docs/plans/UI-TWO-SURFACE-DESIGN-2026-11.md`` § 4.2. ONE broadcaster task reads each
source's cursor once per second and fans the SAME bytes out to every connected client, so the
VM's read load is O(1) in viewers (the per-connection loop in ``market_ws.py`` is O(n)).

Frames (Server-Sent Events, ``id: <seq>``, ``event: <type>``, ``data: <json>``)::

    {seq, ts, type, payload}   type in alert | package | trade | position | bracket | health | hello

  * alert     a new row of the alert ledger (``runtime_logs/alerts_ledger.jsonl``, byte-offset cursor;
              a trimmed/rotated ledger is re-read from the last emitted ``ts``)
  * package   an order package created, or an OPEN package whose status/updated_at moved (incl. closing)
  * trade     a live (non-backtest) trade row created, or an open trade that closed
  * bracket   an open trade whose stop_loss / take_profit_1 changed (SL/TP lines move on the chart)
  * position  the open-trade set changed (ids opened / closed) -- the client re-reads REST /positions
  * health    the /api/bot/health/latest document, pushed only when it changes (30 s compute)
  * hello     first frame on every connection: the current seq and what the ring buffer holds

Reconnect: ``Last-Event-ID`` (or ``?last_event_id=``) replays frames from a 10-minute ring buffer.
If the id is older than the buffer, the hello frame says ``gap: true`` and the client re-snapshots
via REST -- REST stays the authority on membership (``ws.ts`` lesson). Comment heartbeats every
15 s keep Caddy and browsers from idling the connection out.

Auth: the app gate (``require_site_session``) covers this path like every ``/api/bot/*`` GET. A
browser ``EventSource`` cannot send an Authorization header, so with ``SITE_AUTH_ENFORCE`` on it
passes a single-use ``?ticket=`` from ``POST /api/auth/ws-ticket`` -- the same ticket ``/ws/market``
takes (auth.py). A ticket is consumed by the first request; a reconnect fetches a new one.

Failure handling: a source that cannot be read is skipped for that second and reported in the
next ``hello``/``status`` (``sources[<name>].read_state = could_not_look`` with the error); the
broadcaster never stops and never emits a fabricated or empty frame for it. The trader writes
nothing new: every read is ``mode=ro`` on existing tables, by primary key or by the
``status`` index, once per second in total. The broadcaster idles (no reads) while nobody is
connected.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot", tags=["stream"])

TICK_S = 1.0
HEALTH_EVERY_S = 30.0
HEARTBEAT_S = 15.0
RING_SECONDS = 600
RING_MAX = 5000
CLIENT_QUEUE_MAX = 1000
LEDGER_READ_MAX = 256 * 1024        # bytes per tick from the ledger tail
NEW_ROWS_MAX = 200                  # rows per table per tick

TRADE_COLS = ("id", "symbol", "direction", "entry_price", "exit_price", "stop_loss", "take_profit_1",
              "position_size", "status", "pnl", "strategy_name", "account_id", "account_class",
              "order_package_id", "timestamp", "closed_at", "exit_reason")
PACKAGE_COLS = ("order_package_id", "strategy_name", "symbol", "direction", "entry", "sl", "tp",
                "confidence", "status", "linked_trade_id", "close_reason", "created_at", "updated_at")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _default_db_path() -> str:
    from src.utils.paths import trade_journal_db_path
    return trade_journal_db_path()


def _default_ledger_path() -> Path:
    from src.runtime import alerts_ledger
    return alerts_ledger.ledger_path()


def _default_health() -> dict[str, Any]:
    from src.web.api.routers import health_snapshots
    return health_snapshots.get_latest()


class Broadcaster:
    """Reads every source once per tick and fans frames out. One instance per process."""

    def __init__(self, *, db_path: Callable[[], str] = _default_db_path,
                 ledger_path: Callable[[], Path] = _default_ledger_path,
                 health: Callable[[], dict[str, Any]] = _default_health,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._db_path, self._ledger_path, self._health, self._clock = db_path, ledger_path, health, clock
        self.seq = 0
        self.ring: deque[tuple[int, float, bytes]] = deque()
        self.clients: set[asyncio.Queue] = set()
        self.sources: dict[str, dict[str, Any]] = {}
        self.started = False
        self._task: asyncio.Task | None = None
        self._primed = False
        # cursors
        self._ledger_off = 0
        self._ledger_ino: int | None = None
        self._ledger_last_ts = ""
        self._trade_max_id = 0
        self._open_trades: dict[int, tuple] = {}
        self._pkg_rowid = 0
        self._open_pkgs: dict[str, str] = {}
        self._health_hash = ""
        self._health_at = -1e9
        self._pending: list[tuple[str, Any]] = []

    # ── frames ──────────────────────────────────────────────────────────────────────────
    def emit(self, ftype: str, payload: Any) -> None:
        """Queue a frame. Safe from the worker thread: frames are published on the loop by ``flush``."""
        self._pending.append((ftype, payload))

    def flush(self) -> int:
        """Publish queued frames (event-loop thread only: asyncio queues are not thread-safe)."""
        pending, self._pending = self._pending, []
        for ftype, payload in pending:
            self._publish(ftype, payload)
        return len(pending)

    def _publish(self, ftype: str, payload: Any) -> None:
        self.seq += 1
        frame = {"seq": self.seq, "ts": _now_iso(), "type": ftype, "payload": payload}
        data = json.dumps(frame, default=str, separators=(",", ":"))
        raw = f"id: {self.seq}\nevent: {ftype}\ndata: {data}\n\n".encode()
        now = self._clock()
        self.ring.append((self.seq, now, raw))
        while self.ring and (len(self.ring) > RING_MAX or now - self.ring[0][1] > RING_SECONDS):
            self.ring.popleft()
        for q in list(self.clients):
            try:
                q.put_nowait(raw)
            except asyncio.QueueFull:
                # a stalled client drops to a re-snapshot rather than holding memory or the fan-out
                self.clients.discard(q)
                q.put_nowait_closed = True  # type: ignore[attr-defined]

    def backfill(self, last_id: int | None) -> tuple[list[bytes], bool]:
        """Frames after ``last_id`` from the ring, and whether a gap means the client must re-snapshot."""
        if last_id is None:
            return [], False
        oldest = self.ring[0][0] if self.ring else self.seq + 1
        gap = last_id < oldest - 1
        return [raw for s, _, raw in self.ring if s > last_id], gap

    def status(self) -> dict[str, Any]:
        return {"seq": self.seq, "clients": len(self.clients), "ring_frames": len(self.ring),
                "ring_oldest_seq": self.ring[0][0] if self.ring else None, "sources": self.sources}

    # ── sources ─────────────────────────────────────────────────────────────────────────
    def _mark(self, name: str, err: Exception | None = None, **extra: Any) -> None:
        if err is None:
            self.sources[name] = {"read_state": "read", "at": _now_iso(), **extra}
        else:
            self.sources[name] = {"read_state": "could_not_look", "at": _now_iso(),
                                  "error": f"{type(err).__name__}: {str(err)[:200]}"}

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self._db_path()}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn

    def read_ledger(self, emit: bool = True) -> None:
        try:
            p = Path(self._ledger_path())
            if not p.exists():
                self._mark("alerts", None, state="absent")
                return
            st = p.stat()
            if self._ledger_ino is not None and (st.st_ino != self._ledger_ino or st.st_size < self._ledger_off):
                self._ledger_off = 0     # trimmed or rotated: re-read, dedup by ts below
            self._ledger_ino = st.st_ino
            if not emit:                 # priming: start at the end, emit nothing old
                self._ledger_off = st.st_size
                self._mark("alerts")
                return
            with p.open("rb") as fh:
                fh.seek(self._ledger_off)
                chunk = fh.read(LEDGER_READ_MAX)
            end = chunk.rfind(b"\n")
            if end < 0:
                self._mark("alerts")
                return
            self._ledger_off += end + 1
            for line in chunk[: end + 1].splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                ts = str(row.get("ts") or "")
                if ts and ts <= self._ledger_last_ts:
                    continue
                self._ledger_last_ts = ts or self._ledger_last_ts
                self.emit("alert", {k: row.get(k) for k in ("ts", "kind", "channel", "priority", "delivered",
                                                             "reason", "body")})
            self._mark("alerts")
        except Exception as exc:  # noqa: BLE001  # allow-silent: reported as could_not_look in status/hello
            self._mark("alerts", exc)

    def read_journal(self, emit: bool = True) -> None:
        try:
            with self._conn() as conn:
                self._read_trades(conn, emit)
                self._read_packages(conn, emit)
            self._mark("journal", None, open_trades=len(self._open_trades), open_packages=len(self._open_pkgs))
        except Exception as exc:  # noqa: BLE001  # allow-silent: reported as could_not_look in status/hello
            self._mark("journal", exc)

    def _read_trades(self, conn: sqlite3.Connection, emit: bool) -> None:
        cols = ", ".join(TRADE_COLS)
        if not self._primed:
            self._trade_max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM trades").fetchone()[0]
        new = conn.execute(f"SELECT {cols} FROM trades WHERE id > ? AND COALESCE(is_backtest, 0) = 0 "
                           f"ORDER BY id LIMIT ?", (self._trade_max_id, NEW_ROWS_MAX)).fetchall()
        hi = conn.execute("SELECT COALESCE(MAX(id), 0) FROM trades").fetchone()[0]
        opened = conn.execute(f"SELECT {cols} FROM trades WHERE status = 'open' AND COALESCE(is_backtest, 0) = 0"
                              ).fetchall()
        now_open = {r["id"]: (r["stop_loss"], r["take_profit_1"]) for r in opened}
        if emit and self._primed:
            for r in new:
                self.emit("trade", dict(r))
            gone = [i for i in self._open_trades if i not in now_open]
            if gone:
                qs = ",".join("?" * len(gone))
                for r in conn.execute(f"SELECT {cols} FROM trades WHERE id IN ({qs})", gone).fetchall():
                    self.emit("trade", dict(r))
            for r in opened:
                prev = self._open_trades.get(r["id"])
                if prev is not None and prev != now_open[r["id"]]:
                    self.emit("bracket", {"trade_id": r["id"], "symbol": r["symbol"], "account_id": r["account_id"],
                                          "strategy_name": r["strategy_name"], "stop_loss": r["stop_loss"],
                                          "take_profit_1": r["take_profit_1"], "prev_stop_loss": prev[0],
                                          "prev_take_profit_1": prev[1]})
            born = [i for i in now_open if i not in self._open_trades]
            if born or gone:
                self.emit("position", {"opened": born, "closed": gone, "open_count": len(now_open)})
        self._trade_max_id = max(self._trade_max_id, hi)
        self._open_trades = now_open

    def _read_packages(self, conn: sqlite3.Connection, emit: bool) -> None:
        cols = ", ".join(PACKAGE_COLS)
        if not self._primed:
            self._pkg_rowid = conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM order_packages").fetchone()[0]
        new = conn.execute(f"SELECT rowid AS _rowid, {cols} FROM order_packages WHERE rowid > ? ORDER BY rowid LIMIT ?",
                           (self._pkg_rowid, NEW_ROWS_MAX)).fetchall()
        opened = conn.execute(f"SELECT {cols} FROM order_packages WHERE status = 'open'").fetchall()
        now_open = {r["order_package_id"]: str(r["updated_at"]) for r in opened}
        if emit and self._primed:
            new_ids = set()
            for r in new:
                d = dict(r)
                d.pop("_rowid", None)
                new_ids.add(d["order_package_id"])
                self.emit("package", d)
            for r in opened:
                pid = r["order_package_id"]
                if pid in self._open_pkgs and self._open_pkgs[pid] != now_open[pid] and pid not in new_ids:
                    self.emit("package", dict(r))
            gone = [i for i in self._open_pkgs if i not in now_open]
            if gone:
                qs = ",".join("?" * len(gone))
                for r in conn.execute(f"SELECT {cols} FROM order_packages WHERE order_package_id IN ({qs})",
                                      gone).fetchall():
                    self.emit("package", dict(r))
        if new:
            self._pkg_rowid = max(self._pkg_rowid, new[-1]["_rowid"])
        self._open_pkgs = now_open

    def read_health(self, emit: bool = True) -> None:
        now = self._clock()
        if now - self._health_at < HEALTH_EVERY_S:
            return
        self._health_at = now
        try:
            doc = self._health()
            h = hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()
            if emit and h != self._health_hash:
                self.emit("health", doc)
            self._health_hash = h
            self._mark("health")
        except Exception as exc:  # noqa: BLE001  # allow-silent: reported as could_not_look in status/hello
            self._mark("health", exc)

    def tick(self) -> None:
        """One pass over every source. The first pass only primes cursors (emits nothing old)."""
        if not self._primed:
            self.read_ledger(emit=False)
            self.read_journal(emit=False)
            self._primed = True
            self.read_health(emit=True)
            return
        self.read_ledger()
        self.read_journal()
        self.read_health()

    # ── lifecycle ───────────────────────────────────────────────────────────────────────
    async def run(self) -> None:
        while True:
            if self.clients:
                try:
                    await asyncio.to_thread(self.tick)
                except Exception:  # allow-silent: not silent -- logged with stack; the broadcaster never stops
                    logger.exception("stream broadcaster tick failed")
                self.flush()
            else:
                self._primed = False     # idle: no reads; re-prime on the next connection
                self._pending.clear()
            await asyncio.sleep(TICK_S)

    def ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run())
            self.started = True


BROADCASTER = Broadcaster()


def _hello(b: Broadcaster, gap: bool, replayed: int) -> bytes:
    payload = {"seq": b.seq, "gap": gap, "replayed": replayed, "ring_oldest_seq": b.ring[0][0] if b.ring else None,
               "ring_seconds": RING_SECONDS, "sources": b.sources,
               "resnapshot": "GET /api/bot/positions and /api/bot/accounts/balances on hello with gap or on first load"}
    data = json.dumps({"seq": b.seq, "ts": _now_iso(), "type": "hello", "payload": payload}, default=str,
                      separators=(",", ":"))
    return f"event: hello\ndata: {data}\nretry: 3000\n\n".encode()


async def _events(request: Request, b: Broadcaster, last_id: int | None) -> AsyncIterator[bytes]:
    q: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE_MAX)
    b.clients.add(q)
    b.ensure_started()
    try:
        frames, gap = b.backfill(last_id)
        yield _hello(b, gap, len(frames))
        for raw in frames:
            yield raw
        while True:
            if await request.is_disconnected():
                return
            if getattr(q, "put_nowait_closed", False):
                return       # dropped as too slow; EventSource reconnects with Last-Event-ID
            try:
                yield await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
    finally:
        b.clients.discard(q)


@router.get("/stream")
async def stream(request: Request, last_event_id: str | None = Header(default=None),  # async-route-allow: returns an async SSE generator that must run on the loop (asyncio queues), does no blocking work itself
                 last_event_id_q: int | None = Query(default=None, alias="last_event_id")) -> StreamingResponse:
    """Server-Sent Events: alert / package / trade / bracket / position / health frames for every client
    from ONE reader. See the module docstring for frame shapes, reconnect and auth."""
    lid: int | None = last_event_id_q
    if lid is None and last_event_id:
        try:
            lid = int(last_event_id)
        except ValueError:
            lid = None
    return StreamingResponse(_events(request, BROADCASTER, lid), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.get("/stream/status")
def stream_status() -> dict[str, Any]:
    """The broadcaster's own state: seq, connected clients, ring size and each source's read_state."""
    return {"read_state": "read" if BROADCASTER.started else "idle", **BROADCASTER.status()}
