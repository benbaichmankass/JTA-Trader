"""TICK-DURATION-115S: the trader loop sleeps to the next interval boundary.

Before: a flat TICK_INTERVAL_SECONDS after every tick, so a 100.8 s tick made a
~160 s cycle (measured 2026-11-04, 37 ticks over 5,891 s) at a phase that
drifted against bar closes. After: the next tick starts at the first
``k*interval + offset`` grid point after this tick's start, or after
``min_sleep`` when the tick overran it.
"""

from __future__ import annotations

import pytest

from src.main import tick_sleep_seconds

B = 1793800800.0  # 2026-11-04T12:40:00Z, a 5m (and 1m) boundary
assert B % 300 == 0


def test_short_tick_sleeps_to_the_next_boundary_plus_offset():
    # aligned tick started at :02, took 38 s -> wake at next :02
    assert tick_sleep_seconds(B + 40, B + 2, 60, 2, 5) == pytest.approx(22.0)


def test_overrun_tick_restarts_after_the_floor_only():
    assert tick_sleep_seconds(B + 70, B + 2, 60, 2, 5) == 5
    assert tick_sleep_seconds(B + 200, B + 2, 60, 2, 5) == 5


def test_never_sleeps_less_than_the_floor_near_the_boundary():
    assert tick_sleep_seconds(B + 59, B + 2, 60, 2, 5) == 5


def test_early_wake_still_targets_the_following_boundary():
    # woke 0.3 s before the :02 grid point -> counts as AT it
    assert tick_sleep_seconds(B + 30, B + 1.7, 60, 2, 5) == pytest.approx(32.0)  # B+62 - (B+30)


def test_steady_state_short_ticks_land_on_every_5m_close():
    """Simulate the loop: 40 s ticks stay locked to the grid, so each 5m close
    gets a tick that starts `offset` seconds after it."""
    t = B + 2
    starts = []
    for _ in range(10):
        starts.append(t)
        end = t + 40
        t = end + tick_sleep_seconds(end, t, 60, 2, 5)
    assert all((s - 2) % 60 == pytest.approx(0) for s in starts)
    assert sum(1 for s in starts if (s - 2) % 300 == 0) == 2  # 10 min -> 2 closes


def test_long_ticks_run_back_to_back_with_the_floor():
    t = B + 2
    for _ in range(5):
        end = t + 100
        nxt = end + tick_sleep_seconds(end, t, 60, 2, 5)
        assert nxt - t == pytest.approx(105)  # was 160 with the flat 60 s sleep
        t = nxt


def test_defaults_come_from_env_and_bad_values_fall_back(monkeypatch):
    monkeypatch.setenv("TICK_ALIGN_OFFSET_SECONDS", "not-a-number")
    monkeypatch.setenv("TICK_MIN_SLEEP_SECONDS", "-3")
    # falls back to offset 2, floor 5
    assert tick_sleep_seconds(B + 40, B + 2, 60) == pytest.approx(22.0)
    assert tick_sleep_seconds(B + 90, B + 2, 60) == 5


def test_non_positive_interval_never_spins(monkeypatch):
    assert tick_sleep_seconds(B, B, 0, 2, 5) == 5
