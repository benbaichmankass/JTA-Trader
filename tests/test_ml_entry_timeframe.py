"""The timeframe harness reproduces ml_decision_entry at 1h and scales windows as registered (row ML-TIMEFRAME)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import ml_entry_timeframe as T  # noqa: E402


def test_self_test_runs_clean():
    T._self_test()


def test_every_registered_unit_has_a_known_arm():
    for unit, (tf, sc) in T.UNITS.items():
        assert tf in T.TF_MIN and sc in ("bar", "clock"), unit
        assert (Path(__file__).resolve().parents[1] / "research" / "queue" / f"{unit}.yaml").exists(), unit


def test_count_model_matches_the_registered_ratios():
    c = T.count()
    base = c["1h/bar"]["decision_rows_est"]
    assert c["5m/bar"]["decision_rows_est"] == 12 * base and c["15m/bar"]["decision_rows_est"] == 4 * base
    assert c["5m/clock"]["decision_rows_est"] == base and c["4h/bar"]["decision_rows_est"] * 4 == base
