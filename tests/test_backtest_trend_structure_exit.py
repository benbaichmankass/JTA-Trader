"""--structure-exit on the canonical trend engine (row STRUCTURE-EXITS-DEFAULT)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "backtest_candles.csv"


def _run(*extra):
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "backtest_trend.py"), "--data", str(CSV),
                          "--timeframe", "1h", *extra], capture_output=True, text=True, timeout=300)
    return out


def _net_line(txt):
    return [l for l in txt.splitlines() if "net_r=" in l][0]


@pytest.mark.skipif(not CSV.exists(), reason="sample candles absent")
def test_default_off_is_byte_identical_to_explicit_empty():
    a, b = _run(), _run("--structure-exit", "")
    assert a.returncode == 0 and _net_line(a.stdout) == _net_line(b.stdout)
    assert "structure_exit" not in a.stdout


@pytest.mark.skipif(not CSV.exists(), reason="sample candles absent")
def test_structure_arm_changes_exits_and_takes_profit():
    base, st = _run(), _run("--structure-exit", "pivot=3")
    assert st.returncode == 0
    assert _net_line(base.stdout) != _net_line(st.stdout)
    assert "take_profit" in st.stdout          # a real structure TP exists
    assert "'structure_exit': 'pivot=3'" in st.stdout


@pytest.mark.skipif(not CSV.exists(), reason="sample candles absent")
def test_bad_spec_and_trail_level_combo_refused():
    assert _run("--structure-exit", "bogus").returncode == 2
    assert _run("--structure-exit", "pivot=3", "--trail-level", "swing",
                "--trail-level-tight-mult", "1.0").returncode == 2


def _run_pb(*extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "backtest_pullback.py"), "--data", str(CSV),
                           "--timeframe", "1h", *extra], capture_output=True, text=True, timeout=300)


@pytest.mark.skipif(not CSV.exists(), reason="sample candles absent")
def test_pullback_default_off_identical_and_structure_arm_live():
    a, b = _run_pb(), _run_pb("--structure-exit", "")
    assert a.returncode == 0 and _net_line(a.stdout) == _net_line(b.stdout)
    st = _run_pb("--structure-exit", "pivot=3")
    assert st.returncode == 0 and "take_profit" in st.stdout
    assert _net_line(a.stdout) != _net_line(st.stdout)
    assert _run_pb("--structure-exit", "x").returncode == 2
