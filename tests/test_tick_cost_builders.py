"""TICK-BUILDER-TIMING: per-strategy builder time is reported inside tick_cost, bounded and outside attributed_pct."""
from __future__ import annotations

from src.runtime import tick_cost as T


def test_builders_are_reported_sorted_with_per_tick_share():
    T._reset_for_tests()
    T.begin_tick()
    T.record_builder("slow_leg", 300.0)
    T.record_builder("fast_leg", 10.0)
    T.record_builder("slow_leg", 100.0)
    T.end_tick()
    snap = T.snapshot()
    b = snap["builders"]
    assert list(b) == ["slow_leg", "fast_leg"]
    assert b["slow_leg"] == {"n": 2, "mean_ms": 200.0, "max_ms": 300.0, "per_tick_ms": 400.0}
    assert snap["builder_names_refused"] == 0
    assert "slow_leg" not in snap["hooks"]               # never in the hook table, so never in attributed_pct


def test_builder_table_is_bounded_and_counts_refusals(monkeypatch):
    T._reset_for_tests()
    monkeypatch.setattr(T, "_MAX_BUILDER_NAMES", 2)
    for n in ("a", "b", "c"):
        T.record_builder(n, 1.0)
    assert T.snapshot()["builder_names_refused"] == 1


def test_the_multiplexer_records_each_builder_call():
    import inspect

    from src.runtime import intent_multiplexer as M
    assert "_record_builder_ms(name, _t_build)" in inspect.getsource(M._collect_intents)
