"""The decoupled exit loop's wiring — the actual Tier-2 behaviour change.

Everything before this was scaffolding that changed nothing. These pin the three
properties that make the change safe to deploy: the rollback works, the loop
cannot be permanently stopped by a raising pass, and a hanging pass leaves
liveness ageing rather than refreshing it.
"""
from __future__ import annotations

import importlib

import pytest

main = importlib.import_module("src.main")


# --- the interval knob fails ON ------------------------------------------------

@pytest.mark.parametrize("bad", ["", "0", "-5", "abc"])
def test_unusable_interval_falls_back_rather_than_pausing(monkeypatch, bad):
    """A typo must not silently stop exit evaluation, which is the one thing this
    loop exists to do. Pausing is not offered as a value; the rollback puts the
    work back on the tick instead of dropping it."""
    monkeypatch.setenv("EXIT_LOOP_INTERVAL_SECONDS", bad)
    assert main.exit_loop_interval_seconds() == 30.0


def test_interval_default_is_near_the_measured_pass():
    """~28s measured pass, so 30s is effectively back-to-back with slack."""
    assert main.exit_loop_interval_seconds() == 30.0


# --- the rollback switch -------------------------------------------------------

@pytest.mark.parametrize("val,expected_decoupled", [
    (None, True), ("", True), ("0", True), ("false", True),
    ("1", False), ("true", False), ("yes", False), ("ON", False),
])
def test_rollback_switch_semantics(val, expected_decoupled):
    """Default-OFF kill-switch over an ON capability (the REGIME_ROUTER_DISABLED
    shape), NOT a default-off *_ENABLED gate in front of a required capability."""
    assert main._truthy(val) is (not expected_decoupled)


# --- a raising pass must not stop the loop ------------------------------------

def test_a_raising_pass_does_not_kill_the_loop(monkeypatch):
    """A crash-loop here would be invisible from the main heartbeat. The loop has
    to survive its own failures; `exit_loop_health` is what notices it is not
    producing passes, because a thread can be alive and useless."""
    calls = {"n": 0}

    def boom(**kwargs):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise KeyboardInterrupt      # break the infinite loop under test
        raise RuntimeError("pass exploded")

    recorded: list[float] = []
    import src.runtime.exit_loop_health as h
    import src.runtime.order_monitor as om
    monkeypatch.setattr(om, "run_exit_evaluation_tick", boom)
    monkeypatch.setattr(h, "record_pass", lambda ms, **_: recorded.append(ms))
    monkeypatch.setattr(h, "write_state_file", lambda *a, **k: None)
    monkeypatch.setattr(main, "_build_monitor_ohlcv_fetcher", lambda s: None)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)

    with pytest.raises(KeyboardInterrupt):
        main._exit_loop({})

    assert calls["n"] == 3, "loop stopped early on a raising pass"
    # Each failed pass still recorded — a pass that ran and failed is not a pass
    # that never happened, and conflating them would hide a crash-loop.
    assert len(recorded) == 2


def test_record_pass_is_called_after_the_pass_returns(monkeypatch):
    """Order matters: recording BEFORE would make a hanging pass refresh liveness,
    which is the silent wedge this whole design exists to avoid."""
    order: list[str] = []
    import src.runtime.exit_loop_health as h
    import src.runtime.order_monitor as om

    def slow_pass(**kwargs):
        order.append("pass")
        raise KeyboardInterrupt        # stop after one iteration

    monkeypatch.setattr(om, "run_exit_evaluation_tick", slow_pass)
    monkeypatch.setattr(h, "record_pass", lambda ms, **_: order.append("record"))
    monkeypatch.setattr(h, "write_state_file", lambda *a, **k: None)
    monkeypatch.setattr(main, "_build_monitor_ohlcv_fetcher", lambda s: None)

    with pytest.raises(KeyboardInterrupt):
        main._exit_loop({})
    # The pass raised, so no record for it — and crucially `record` never precedes
    # `pass`.
    assert order == ["pass"]


def test_an_overrunning_pass_does_not_sleep(monkeypatch):
    """If a pass overruns the interval the next starts immediately: the cadence is
    a floor on frequency, not a schedule to catch up on. Piling passes onto one
    shared IB socket is how the June 2026 wedges started."""
    slept: list[float] = []
    import src.runtime.exit_loop_health as h
    import src.runtime.order_monitor as om
    n = {"i": 0}

    def long_pass(**kwargs):
        n["i"] += 1
        if n["i"] >= 2:
            raise KeyboardInterrupt
        # simulate a 60s pass against a 30s interval
        t0 = main.time.monotonic()
        monkeypatch.setattr(main.time, "monotonic", lambda: t0 + 60.0)

    monkeypatch.setattr(om, "run_exit_evaluation_tick", long_pass)
    monkeypatch.setattr(h, "record_pass", lambda ms, **_: None)
    monkeypatch.setattr(h, "write_state_file", lambda *a, **k: None)
    monkeypatch.setattr(main, "_build_monitor_ohlcv_fetcher", lambda s: None)
    monkeypatch.setattr(main.time, "sleep", lambda s: slept.append(s))

    with pytest.raises(KeyboardInterrupt):
        main._exit_loop({})
    assert slept == [], f"slept after an overrunning pass: {slept}"


def test_start_exit_loop_never_raises_into_startup(monkeypatch):
    """A failure to start must not take the trader down with it."""
    def bad_thread(*a, **k):
        raise RuntimeError("cannot spawn")
    monkeypatch.setattr(main.threading, "Thread", bad_thread)
    main._start_exit_loop({})    # must not raise


# --- RESTART-GAP-EXIT-FIRST (2026-11-05): exit loop first, final pass on SIGTERM

@pytest.fixture
def _fresh_shutdown_events(monkeypatch):
    """The shutdown events are module state; give every test its own."""
    import threading
    monkeypatch.setattr(main, "_EXIT_LOOP_SHUTDOWN", threading.Event())
    monkeypatch.setattr(main, "_EXIT_LOOP_FINAL_PASS_DONE", threading.Event())
    monkeypatch.setattr(main, "_EXIT_LOOP_THREAD", None)


def _boot_main(monkeypatch, order, *, loop="true"):
    """Run main() up to the restart-report join, recording the boot order."""
    import src.runtime.boot_audit as ba
    import src.utils.db_init as dbi
    monkeypatch.setenv("LOOP", loop)
    monkeypatch.delenv("EXIT_LOOP_DECOUPLE_DISABLED", raising=False)
    monkeypatch.setattr(main, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(main, "build_settings_from_env", lambda: {})
    monkeypatch.setattr(main, "validate_startup", lambda: None)
    monkeypatch.setattr(dbi, "enable_wal_mode", lambda *a, **k: order.append("wal"))
    monkeypatch.setattr(main, "_start_exit_loop", lambda s: order.append("exit_loop"))
    monkeypatch.setattr(main, "_install_final_pass_on_sigterm",
                        lambda: order.append("sigterm_handler"))
    import src.units.accounts.dup_key_check as dk
    monkeypatch.setattr(dk, "warn_on_duplicate_keys", lambda *a, **k: None)

    def report(*a, **k):
        order.append("restart_report")
        raise KeyboardInterrupt          # stop boot here; everything after is not under test
    monkeypatch.setattr(ba, "start_restart_report_thread", report)
    with pytest.raises(KeyboardInterrupt):
        main.main()


def test_main_starts_the_exit_loop_before_the_restart_report(monkeypatch, _fresh_shutdown_events):
    """MEASURED 2026-11-05 10:58Z: the report join (13.4s) plus leverage and the
    adapter build (9.0s) ran before the exit thread, inside a 64.1s restart gap.
    The exit loop must start right after WAL, ahead of all of them."""
    order: list[str] = []
    _boot_main(monkeypatch, order)
    assert order == ["wal", "exit_loop", "sigterm_handler", "restart_report"], order


def test_single_tick_mode_starts_no_exit_loop(monkeypatch, _fresh_shutdown_events):
    """LOOP=false runs one tick and returns; it never had an exit thread."""
    order: list[str] = []
    _boot_main(monkeypatch, order, loop="false")
    assert "exit_loop" not in order and "sigterm_handler" not in order, order


def test_shutdown_during_the_sleep_runs_one_final_pass(monkeypatch, _fresh_shutdown_events):
    """SIGTERM while the loop sleeps cuts the sleep short; exactly one more pass
    runs, is recorded, and the loop returns with FINAL_PASS_DONE set."""
    import src.runtime.exit_loop_health as h
    import src.runtime.order_monitor as om
    passes: list[int] = []
    recorded: list[float] = []
    slept: list[float] = []

    def a_pass(**kwargs):
        passes.append(1)

    def sleep(s):
        slept.append(s)
        main._EXIT_LOOP_SHUTDOWN.set()   # SIGTERM lands during the first sleep step

    monkeypatch.setattr(om, "run_exit_evaluation_tick", a_pass)
    monkeypatch.setattr(h, "record_pass", lambda ms, **_: recorded.append(ms))
    monkeypatch.setattr(h, "write_state_file", lambda *a, **k: None)
    monkeypatch.setattr(main, "_build_monitor_ohlcv_fetcher", lambda s: None)
    monkeypatch.setattr(main.time, "sleep", sleep)

    main._exit_loop({})                  # returns instead of looping forever
    assert len(passes) == 2 and len(recorded) == 2
    assert slept == [1.0], "sleep must stop at the first step once shutdown is set"
    assert main._EXIT_LOOP_FINAL_PASS_DONE.is_set()


def test_sleep_steps_cover_the_whole_slack(_fresh_shutdown_events, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(main.time, "sleep", lambda s: slept.append(s))
    main._exit_loop_sleep(2.5)
    assert slept == [1.0, 1.0, 0.5]
    slept.clear()
    main._exit_loop_sleep(0.0)
    assert slept == []


def test_sigterm_handler_always_re_raises_sigterm(monkeypatch, _fresh_shutdown_events):
    """Whatever happens, the process still dies by SIGTERM (systemd records the
    same exit, restart_cause is unchanged). No exit thread -> no wait."""
    import signal
    calls: list = []
    monkeypatch.setattr(signal, "signal", lambda sig, h: calls.append(("signal", sig, h)))
    monkeypatch.setattr(main.os, "kill", lambda pid, sig: calls.append(("kill", sig)))
    main._on_sigterm(signal.SIGTERM, None)
    assert main._EXIT_LOOP_SHUTDOWN.is_set()
    assert calls == [("signal", signal.SIGTERM, signal.SIG_DFL), ("kill", signal.SIGTERM)]


def test_sigterm_handler_waits_for_the_final_pass(monkeypatch, _fresh_shutdown_events):
    import signal
    import threading
    calls: list = []
    monkeypatch.setattr(signal, "signal", lambda sig, h: calls.append("signal"))
    monkeypatch.setattr(main.os, "kill", lambda pid, sig: calls.append("kill"))

    def fake_loop():
        main._EXIT_LOOP_SHUTDOWN.wait(5)
        calls.append("final_pass")
        main._EXIT_LOOP_FINAL_PASS_DONE.set()
    t = threading.Thread(target=fake_loop, daemon=True)
    t.start()
    monkeypatch.setattr(main, "_EXIT_LOOP_THREAD", t)
    main._on_sigterm(signal.SIGTERM, None)
    assert calls == ["final_pass", "signal", "kill"]


def test_final_pass_rollback_installs_no_handler(monkeypatch):
    import signal
    installed: list = []
    monkeypatch.setattr(signal, "signal", lambda sig, h: installed.append(sig))
    monkeypatch.setenv("EXIT_LOOP_FINAL_PASS_DISABLED", "1")
    assert main._install_final_pass_on_sigterm() is False
    assert installed == []
    monkeypatch.delenv("EXIT_LOOP_FINAL_PASS_DISABLED")
    assert main._install_final_pass_on_sigterm() is True
    assert installed == [signal.SIGTERM]
