"""TICK-STAGE2-RECONCILE-OFFTICK: reconciliation on its own thread, serialized
with entry dispatch by journal_sync, and an exit pass that a held journal lock
cannot push past the 60 s exit-evaluation requirement.

Pins:
  * the lock serializes a reconciliation pass against an entry dispatch, both ways;
  * it is re-entrant (typed dispatch -> dispatch) and wraps the real
    Coordinator.multi_account_execute;
  * a raising pass is contained, counted and retried on the next pass;
  * a dead thread is restarted; persistent failure or staleness raises ONE
    latched flag and a recovery clears it (no halting, Prime Directive 7);
  * on the exit thread a best-effort telemetry write gives up after the short
    bound rather than its 5 s default when another writer holds the journal.
"""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from src.runtime import journal_sync as js
from src.runtime import reconcile_loop as rl


@pytest.fixture(autouse=True)
def _reset():
    rl._reset_for_tests()
    yield
    rl._reset_for_tests()


def _other_thread_can_take_the_lock() -> bool:
    got = []

    def probe():
        ok = js._LOCK.acquire(timeout=1)
        got.append(ok)
        if ok:
            js._LOCK.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join(2)
    return got == [True]


# --- the lock -------------------------------------------------------------------

def test_dispatch_waits_for_an_in_flight_reconciliation_pass():
    in_pass = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def slow_pass():
        order.append("pass_start")
        in_pass.set()
        release.wait(5)
        order.append("pass_end")

    t = threading.Thread(target=rl.run_one_pass, args=(slow_pass,))
    t.start()
    assert in_pass.wait(5)

    def dispatch():
        with js.journal_sync("entry_dispatch"):
            order.append("dispatch")

    d = threading.Thread(target=dispatch)
    d.start()
    time.sleep(0.2)
    assert "dispatch" not in order, "dispatch ran inside a reconciliation pass"
    release.set()
    t.join(5)
    d.join(5)
    assert order == ["pass_start", "pass_end", "dispatch"]


def test_reconciliation_pass_waits_for_an_in_flight_dispatch():
    holding = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def dispatch():
        with js.journal_sync("entry_dispatch"):
            order.append("dispatch_start")
            holding.set()
            release.wait(5)
            order.append("dispatch_end")

    d = threading.Thread(target=dispatch)
    d.start()
    assert holding.wait(5)
    t = threading.Thread(target=rl.run_one_pass,
                         args=(lambda: order.append("pass"),))
    t.start()
    time.sleep(0.2)
    assert "pass" not in order, "reconciliation saw a half-done dispatch"
    release.set()
    d.join(5)
    t.join(5)
    assert order == ["dispatch_start", "dispatch_end", "pass"]


def test_lock_is_reentrant():
    with js.journal_sync("outer"):
        with js.journal_sync("inner"):
            assert js.is_held_by_current_thread()
    assert not js.is_held_by_current_thread()


def test_lock_released_when_body_raises():
    with pytest.raises(ValueError):
        with js.journal_sync("x"):
            raise ValueError("boom")
    assert not js.is_held_by_current_thread()
    assert _other_thread_can_take_the_lock()


def test_multi_account_execute_holds_the_lock():
    from src.core.coordinator import Coordinator
    fn = Coordinator.multi_account_execute
    assert hasattr(fn, "__wrapped__"), "dispatch is not journal_sync-wrapped"
    seen = []

    def body(self, pkg, **kw):
        seen.append(js.is_held_by_current_thread())
        return []

    import src.core.coordinator as c
    wrapped = c._journal_synced(body)
    assert wrapped(object(), object()) == []
    assert seen == [True]
    assert not js.is_held_by_current_thread()


def test_typed_dispatch_reenters_without_deadlock(monkeypatch):
    """multi_account_execute_typed -> multi_account_execute on one thread."""
    import src.core.coordinator as c
    inner = c._journal_synced(lambda *a, **k: [js.is_held_by_current_thread()])
    outer = c._journal_synced(lambda *a, **k: inner())
    done = []
    t = threading.Thread(target=lambda: done.append(outer()))
    t.start()
    t.join(3)
    assert done == [[True]]


# --- failure containment ----------------------------------------------------------

def test_a_raising_pass_is_contained_and_retried_next_pass(monkeypatch):
    monkeypatch.setenv("RECONCILE_LOOP_INTERVAL_SECONDS", "0.01")
    calls = {"n": 0}
    stop = threading.Event()

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("venue timeout")
        if calls["n"] >= 3:
            stop.set()

    t = threading.Thread(target=rl._loop, args=(flaky, stop), daemon=True)
    t.start()
    t.join(5)
    st = rl.status()
    assert calls["n"] >= 3, "the loop stopped after a raising pass"
    assert st["failures"] == 1
    assert st["consecutive_failures"] == 0
    assert st["last_ok_utc"] is not None
    assert "venue timeout" in st["last_error"]
    assert not js.is_held_by_current_thread()


def test_raising_pass_releases_the_lock_for_dispatch():
    rl.run_one_pass(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert _other_thread_can_take_the_lock()


@pytest.mark.parametrize("bad", ["", "0", "-1", "abc"])
def test_interval_fails_toward_the_default(monkeypatch, bad):
    monkeypatch.setenv("RECONCILE_LOOP_INTERVAL_SECONDS", bad)
    assert rl.interval_seconds() == 60.0


@pytest.mark.parametrize("val,on", [(None, True), ("", True), ("0", True),
                                    ("1", False), ("true", False), ("YES", False)])
def test_rollback_switch(monkeypatch, val, on):
    if val is None:
        monkeypatch.delenv("RECONCILE_OFFTICK_DISABLED", raising=False)
    else:
        monkeypatch.setenv("RECONCILE_OFFTICK_DISABLED", val)
    assert rl.offtick_enabled() is on


def test_dead_thread_is_restarted(monkeypatch):
    monkeypatch.setenv("RECONCILE_LOOP_INTERVAL_SECONDS", "30")
    started = threading.Event()
    rl.ensure_running(lambda: started.set(), send=lambda m: None)
    assert started.wait(3)
    assert rl.status()["thread_alive"]


def test_persistent_failure_raises_one_latched_flag_then_recovers(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(rl, "start", lambda fn: True)  # no thread in this test
    monkeypatch.setattr(rl, "_thread", type("T", (), {"is_alive": lambda s: True})())
    for _ in range(rl.FAILURE_FLAG_AFTER):
        rl.run_one_pass(lambda: (_ for _ in ()).throw(RuntimeError("down")))
    rl.ensure_running(lambda: None, send=sent.append)
    rl.ensure_running(lambda: None, send=sent.append)
    assert len(sent) == 1 and "FAILING" in sent[0]
    rl.run_one_pass(lambda: None)
    rl.ensure_running(lambda: None, send=sent.append)
    assert len(sent) == 2 and "RECOVERED" in sent[1]


def test_stale_loop_raises_flag(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(rl, "_thread", type("T", (), {"is_alive": lambda s: True})())
    monkeypatch.setenv("RECONCILE_LOOP_STALE_SECONDS", "0.05")
    rl._state["started_monotonic"] = time.monotonic() - 1.0
    rl.ensure_running(lambda: None, send=sent.append)
    assert len(sent) == 1 and "STALE" in sent[0]


# --- the exit thread's bounded telemetry write -------------------------------------

def _full_record(pkg_id):
    import re
    from src.runtime import position_telemetry as pt
    insert = pt._UPSERT.split("ON CONFLICT")[0]
    rec = {k: None for k in re.findall(r":(\w+)", insert)}
    rec.update(order_package_id=pkg_id, symbol="XRPUSDT", account_id="bybit_2",
               strategy="s", peak_r=1.0, updated_at="2026-11-05T08:01:00Z")
    return rec


def _in_thread(name, fn):
    out = []
    t = threading.Thread(target=lambda: out.append(fn()), name=name)
    t.start()
    t.join(10)
    return out[0]


def test_write_busy_timeout_is_short_only_on_the_exit_thread(monkeypatch):
    monkeypatch.delenv("EXIT_LOOP_DB_WRITE_TIMEOUT_SECONDS", raising=False)
    assert _in_thread(js.EXIT_LOOP_THREAD_NAME, lambda: js.write_busy_timeout(5.0)) == 0.25
    assert _in_thread("MainThread-like", lambda: js.write_busy_timeout(5.0)) == 5.0
    assert _in_thread(rl.THREAD_NAME, lambda: js.write_busy_timeout(5.0)) == 5.0


def test_held_journal_lock_costs_the_exit_pass_the_short_bound_not_5s(tmp_path):
    """The 2026-11-05T08:01Z breach shape: another writer holds the journal; the
    exit pass's telemetry write must give up in about 0.25 s, not 5 s."""
    from src.runtime import position_telemetry as pt
    db = str(tmp_path / "j.db")
    with sqlite3.connect(db) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute(f"""CREATE TABLE {pt.TABLE} (
            order_package_id TEXT PRIMARY KEY, trade_id TEXT, strategy TEXT,
            symbol TEXT, account_id TEXT, direction TEXT, entry REAL,
            risk_per_unit REAL, last_price REAL, open_r REAL, peak_r REAL,
            peak_state TEXT, giveback_r REAL, bars_held INTEGER,
            bars_since_peak INTEGER, cap_r REAL, pct_of_cap REAL,
            r_to_stop REAL, r_to_target REAL, rr_from_here REAL,
            peak_provenance TEXT, levers TEXT, updated_at TEXT,
            peak_authoritative INTEGER)""")
    rec = _full_record("pkg-1")
    # Positive control: with no foreign holder the same write LANDS, so the
    # False below is the lock, not a malformed record.
    assert _in_thread(js.EXIT_LOOP_THREAD_NAME, lambda: pt.write_record(rec, db_path=db))
    holder = sqlite3.connect(db, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        t0 = time.monotonic()
        ok = _in_thread(js.EXIT_LOOP_THREAD_NAME, lambda: pt.write_record(rec, db_path=db))
        elapsed = time.monotonic() - t0
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert ok is False
    assert elapsed < 2.0, f"exit-thread write waited {elapsed:.2f}s under a held lock"
