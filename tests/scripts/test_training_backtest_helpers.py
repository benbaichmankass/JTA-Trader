"""scripts/training harness: a raising build_signal() must not read as a null result.

AUD-20260927-CA-B02 / PI-20260927-CAB02-0001: ``simple_backtest`` swallowed every
``build_signal`` exception and returned the same zero-trade dict as a genuine
"no setup" run, which SUMMARY.md rendered as ``OK`` with E[R]=0.000.
"""
import importlib.util
import pathlib

import pandas as pd

from scripts.training.backtest_helpers import simple_backtest

_spec = importlib.util.spec_from_file_location(
    "run_experiment_under_test",
    pathlib.Path(__file__).resolve().parents[2] / "scripts/training/run_experiment.py",
)
run_experiment = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_experiment)


def _candles(n=300):
    return pd.DataFrame({
        "timestamp": range(n),
        "close": [100.0 + (i % 7) for i in range(n)],
    })


def _exit(sig, future):
    return sig["entry"] + 1.0, "tp"


def test_no_setup_is_a_clean_null_with_zero_errors():
    out = simple_backtest(_candles(), lambda w: None, _exit, lookback_bars=20)
    assert out["trades"] == 0
    assert out["build_signal_errors"] == 0
    assert out["build_signal_first_error"] is None


def test_raising_build_signal_is_distinguishable_from_no_setup():
    def broken(window):
        return window["no_such_column"]  # KeyError — the "wrong column name" bug

    out = simple_backtest(_candles(), broken, _exit, lookback_bars=20)
    assert out["trades"] == 0
    assert out["build_signal_errors"] > 0
    assert "KeyError" in out["build_signal_first_error"]


def test_intermittent_errors_still_trade_and_are_counted():
    calls = {"n": 0}

    def flaky(window):
        calls["n"] += 1
        if calls["n"] % 2:
            raise ValueError("boom")
        return {"direction": "long", "entry": 100.0, "sl": 99.0, "tp": 101.0}

    out = simple_backtest(_candles(), flaky, _exit, lookback_bars=20)
    assert out["trades"] > 0
    assert out["build_signal_errors"] > 0
    assert out["build_signal_first_error"].startswith("ValueError")


def test_summary_row_flags_signal_errors_not_ok():
    bad = {"metrics": {"trades": 0, "expectancy_r": 0.0,
                       "build_signal_errors": 5,
                       "build_signal_first_error": "KeyError: 'x'"}}
    row = run_experiment._summary_row("H1", bad)
    assert "SIGNAL_ERRORS" in row and "| OK |" not in row

    clean = {"metrics": {"trades": 0, "expectancy_r": 0.0, "build_signal_errors": 0},
             "baseline_metrics": {"expectancy_r": 0.0}}
    assert "| OK |" in run_experiment._summary_row("H1", clean)
