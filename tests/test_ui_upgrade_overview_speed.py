"""UI-UPGRADE-1 item 1/2: stale-while-revalidate snapshots, the backwards
audit-log tail behind /api/bot/signals, and the /api/bot/work/snapshot glance."""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

from src.web.api import _swr
from src.web.api._swr import BUILT, FRESH, STALE, SWRCache, snapshot_headers
from src.web.api.routers import dashboard as dash
from src.web.api.routers import work as wk


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


# ── SWRCache (sync) ─────────────────────────────────────────────────────────

def test_sync_fresh_stale_and_expired_paths():
    clock = _Clock()
    cache = SWRCache(name="t", fresh_s=5, stale_s=60, clock=clock)
    calls = []

    def build():
        calls.append(clock.t)
        return len(calls)

    assert cache.get("k", build) == (1, 0.0, BUILT)
    clock.t += 3
    assert cache.get("k", build)[0::2] == (1, FRESH)
    assert len(calls) == 1

    # Stale: the OLD value comes back at once and one refresh runs behind it.
    clock.t += 10
    done = threading.Event()

    def slow_build():
        calls.append(clock.t)
        done.set()
        return 99

    value, age, state = cache.get("k", slow_build)
    assert (value, state) == (1, STALE) and age == pytest.approx(13)
    assert done.wait(5)
    for _ in range(100):  # the store happens just after build() returns
        if cache.get("k", build)[0] == 99:
            break
    assert cache.get("k", build)[0] == 99

    # Expired: rebuilt in the request, never served.
    clock.t += 61
    assert cache.get("k", lambda: 7) == (7, 0.0, BUILT)


def test_background_failure_keeps_previous_value_and_it_ages_out():
    clock = _Clock()
    cache = SWRCache(name="t", fresh_s=5, stale_s=60, clock=clock)
    cache.get("k", lambda: "good")
    clock.t += 10
    finished = threading.Event()

    def boom():
        finished.set()
        raise RuntimeError("venue down")

    assert cache.get("k", boom)[0::2] == ("good", STALE)
    assert finished.wait(5)
    clock.t += 100  # past stale_s: the failure must surface, not be masked
    with pytest.raises(RuntimeError):
        cache.get("k", lambda: (_ for _ in ()).throw(RuntimeError("still down")))


def test_foreground_failure_raises_and_caches_nothing():
    cache = SWRCache(name="t", fresh_s=5, stale_s=60, clock=_Clock())
    with pytest.raises(ValueError):
        cache.get("k", lambda: (_ for _ in ()).throw(ValueError("x")))
    assert cache.get("k", lambda: 1) == (1, 0.0, BUILT)


def test_bad_window_refused():
    with pytest.raises(ValueError):
        SWRCache(name="t", fresh_s=10, stale_s=5)


def test_snapshot_headers():
    assert snapshot_headers(3.14159, STALE) == {"X-Snapshot-Age-S": "3.1",
                                                "X-Snapshot-State": "stale"}


# ── SWRCache (async) ────────────────────────────────────────────────────────

def test_async_single_flight_and_stale_serve():
    clock = _Clock()
    cache = SWRCache(name="t", fresh_s=5, stale_s=60, clock=clock)
    n = {"calls": 0}

    async def build():
        n["calls"] += 1
        await asyncio.sleep(0.01)
        return n["calls"]

    async def run():
        # two concurrent cold callers share ONE build
        a, b = await asyncio.gather(cache.aget("k", build), cache.aget("k", build))
        assert a[0] == b[0] == 1 and n["calls"] == 1
        clock.t += 10
        v, _age, state = await cache.aget("k", build)
        assert (v, state) == (1, STALE)
        await asyncio.sleep(0.05)  # let the background refresh land
        v, _age, state = await cache.aget("k", build)
        assert (v, state) == (2, FRESH)

    asyncio.run(run())


# ── backwards tail ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [1, 3, 50, 500])
@pytest.mark.parametrize("trailing_newline", [True, False])
def test_tail_lines_matches_readlines(tmp_path, monkeypatch, n, trailing_newline):
    monkeypatch.setattr(dash, "_TAIL_CHUNK", 37)  # force many block reads
    lines = [json.dumps({"i": i, "s": "x" * (i % 13), "u": " é"}, ensure_ascii=False)
             for i in range(120)]
    text = "\n".join(lines) + ("\n" if trailing_newline else "")
    p = tmp_path / "a.jsonl"
    p.write_text(text, encoding="utf-8")
    with p.open(encoding="utf-8") as fh:
        expected = [json.loads(x) for x in fh.readlines()[-n:] if x.strip()]
    assert dash._tail_jsonl(p, n) == expected


def test_tail_lines_empty_and_missing(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text("", encoding="utf-8")
    assert dash._tail_jsonl(p, 5) == []
    assert dash._tail_jsonl(tmp_path / "nope.jsonl", 5) == []


# ── /api/bot/work/snapshot ─────────────────────────────────────────────────

def _fake_store(monkeypatch, items):
    from src.runtime import checklist_store
    monkeypatch.setattr(checklist_store, "load", lambda *_a, **_k: {"items": items})
    monkeypatch.setattr(wk, "_snapshot_cache", None)


def test_snapshot_partitions(monkeypatch):
    items = (
        [{"id": f"D{i}", "state": "done", "updated_at": f"2026-10-0{i}T00:00:00Z"} for i in range(1, 8)]
        + [{"id": "LU", "state": "landed_unproven", "updated_at": "2026-10-09T00:00:00Z"}]
        + [{"id": "F1", "state": "in_flight"}]
        + [{"id": f"Q{i}", "state": "queued"} for i in range(7)]
        + [{"id": "W", "state": "blocked", "blocked_on": [
            {"kind": "operator_decision", "ref": "x", "what": "approve it"},
            {"kind": "work_item", "ref": "y"}]},
           {"id": "OWN", "state": "queued", "owner": "operator + build lane"},
           {"id": "DONEOP", "state": "done", "updated_at": "2026-01-01",
            "blocked_on": [{"kind": "operator_decision"}]}]
    )
    _fake_store(monkeypatch, items)
    body = wk.get_work_snapshot()
    assert body["present"] is True
    assert [r["id"] for r in body["closedRecent"]] == ["D7", "D6", "D5", "D4", "D3"]
    assert "LU" not in {r["id"] for r in body["closedRecent"]}  # merged is not done
    assert [r["id"] for r in body["openNow"]] == ["F1"]
    assert [r["id"] for r in body["next"]] == ["Q0", "Q1", "Q2", "Q3", "Q4"]
    assert [r["id"] for r in body["waitingOnOperator"]] == ["W"]
    assert body["waitingOnOperator"][0]["asks"] == [{"what": "approve it", "ref": "x"}]
    assert sum(body["counts"].values()) == body["total"] == len(items)


def test_snapshot_next_is_the_ranked_runnable_queue(monkeypatch):
    """`next` is what the manager dispatches next: ranked rows first, blocked rows excluded."""
    items = ([{"id": f"Q{i}", "state": "queued"} for i in range(3)]
             + [{"id": "R2", "state": "queued", "priority_rank": 2},
                {"id": "R1", "state": "queued", "priority_rank": 1},
                {"id": "RB", "state": "queued", "priority_rank": 1,
                 "blocked_on": [{"kind": "work_item", "ref": "R1"}]}])
    _fake_store(monkeypatch, items)
    body = wk.get_work_snapshot()
    assert [r["id"] for r in body["next"]] == ["R1", "R2", "Q0", "Q1", "Q2"]
    assert body["next"][0]["priorityRank"] == 1 and body["next"][2]["priorityRank"] is None


def test_snapshot_unreadable_is_not_empty_work(monkeypatch):
    from src.runtime import checklist_store

    def boom(*_a, **_k):
        raise OSError("disk")

    monkeypatch.setattr(checklist_store, "load", boom)
    monkeypatch.setattr(wk, "_snapshot_cache", None)
    body = wk.get_work_snapshot()
    assert body["present"] is False and "disk" in body["reason"]
    assert body["total"] is None


def test_snapshot_over_http_against_the_real_store():
    from fastapi.testclient import TestClient
    from src.web.api.main import app

    wk._snapshot_cache = None
    r = TestClient(app).get("/api/bot/work/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["present"] is True and body["total"] > 0
    assert len(r.content) < 50_000  # the point: a glance, not the 400 KB checklist


def test_module_exports():
    assert _swr.FRESH == "fresh" and _swr.BUILT == "built"
