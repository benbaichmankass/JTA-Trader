"""JOURNAL-LOCK-RESIDUAL (2026-11-06): a burst of slow broker closes must not
stretch one exit pass past the 60 s re-evaluation requirement.

Measured 15:00-15:01Z: five max_hold closes ran serially on the exit thread
(7-17 s each of Alpaca settle/flatten/confirm waits) -> pass 52.7 s, interval
82.0 s. The fix defers the DISPATCH of further time-based closes once the pass
has spent its close budget; evaluation of every package is unchanged.
"""
from src.runtime import order_monitor as om


class _Db:
    def __init__(self, rows):
        self._rows = rows

    def get_order_packages_by_strategy(self, name, status="open"):
        return self._rows.get(name, [])


def _wire(monkeypatch, rows, verdicts, clock, close_cost):
    applied = []
    monkeypatch.setattr(om, "_resolve_db", lambda p: _Db(rows))
    monkeypatch.setattr(om, "_load_live_strategy_cfgs", lambda: {})
    monkeypatch.setattr(om, "exit_population", lambda s, d: list(rows))
    monkeypatch.setattr(
        om, "_call_strategy_monitor",
        lambda name, cfg, candles, pkg: (verdicts[pkg["order_package_id"]], "ok"))
    monkeypatch.setattr(om, "_track_monitor_blindness", lambda **k: None)

    def fake_apply(db, pkg, verdict, summary):
        applied.append(pkg["order_package_id"])
        clock[0] += close_cost
        summary.closed_count += 1

    monkeypatch.setattr(om, "_apply_update", fake_apply)
    monkeypatch.setattr(om.time, "monotonic", lambda: clock[0])
    return applied


def _rows(n):
    return {"ml_entry": [{"order_package_id": f"p{i}", "symbol": f"S{i}", "meta": "{}"}
                         for i in range(n)]}


MAX_HOLD = {"action": "close", "reason": "max_hold"}


def test_burst_of_slow_max_hold_closes_defers_past_budget(monkeypatch):
    monkeypatch.setenv("EXIT_PASS_CLOSE_BUDGET_S", "10")
    clock = [0.0]
    rows = _rows(5)
    verdicts = {f"p{i}": MAX_HOLD for i in range(5)}
    applied = _wire(monkeypatch, rows, verdicts, clock, close_cost=8.0)
    out = om.run_exit_evaluation_tick(ohlcv_fetcher=None)
    # 8 s < 10 s -> second runs (16 s), third+ deferred: pass spends 16 s, not 40 s.
    assert applied == ["p0", "p1"]
    assert out["__closes_deferred__"]["deferred"] == 3
    assert clock[0] == 16.0


def test_protective_close_is_never_deferred(monkeypatch):
    monkeypatch.setenv("EXIT_PASS_CLOSE_BUDGET_S", "10")
    clock = [0.0]
    rows = _rows(4)
    verdicts = {"p0": MAX_HOLD, "p1": MAX_HOLD,
                "p2": {"action": "close", "reason": "sl_cross"},
                "p3": MAX_HOLD}
    applied = _wire(monkeypatch, rows, verdicts, clock, close_cost=8.0)
    out = om.run_exit_evaluation_tick(ohlcv_fetcher=None)
    assert applied == ["p0", "p1", "p2"]  # stop-loss close runs over budget
    assert out["__closes_deferred__"]["deferred"] == 1


def test_first_close_always_runs_even_with_tiny_budget(monkeypatch):
    monkeypatch.setenv("EXIT_PASS_CLOSE_BUDGET_S", "0.001")
    clock = [0.0]
    rows = _rows(3)
    applied = _wire(monkeypatch, rows, {f"p{i}": MAX_HOLD for i in range(3)},
                    clock, close_cost=1.0)
    om.run_exit_evaluation_tick(ohlcv_fetcher=None)
    assert applied == ["p0"]


def test_budget_zero_disables_deferral(monkeypatch):
    monkeypatch.setenv("EXIT_PASS_CLOSE_BUDGET_S", "0")
    clock = [0.0]
    rows = _rows(5)
    applied = _wire(monkeypatch, rows, {f"p{i}": MAX_HOLD for i in range(5)},
                    clock, close_cost=8.0)
    out = om.run_exit_evaluation_tick(ohlcv_fetcher=None)
    assert len(applied) == 5 and "__closes_deferred__" not in out


def test_no_deferral_key_when_fast(monkeypatch):
    monkeypatch.setenv("EXIT_PASS_CLOSE_BUDGET_S", "10")
    clock = [0.0]
    applied = _wire(monkeypatch, _rows(3), {f"p{i}": MAX_HOLD for i in range(3)},
                    clock, close_cost=1.0)
    out = om.run_exit_evaluation_tick(ohlcv_fetcher=None)
    assert len(applied) == 3 and "__closes_deferred__" not in out
