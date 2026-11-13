"""DEMO-FLOOR-ITER-20261113: the tooling behind the seven demo-floor iteration units.

* forming-mode arms: an arm's entry gate (side_filter; pullback adx_min/adx_max) must reach the block the forming replay
  reads -- the harness switches its own copies off in forming mode, so before this an arm silently equalled its baseline;
* the turtle_soup harness accepts the timeframe lever family (15m live, 1h / 4h) and refuses anything else;
* the timeframe grade and the R diagnosis self-tests.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))

import forming_bar_entries as fbe  # noqa: E402


def test_trend_block_carries_a_direction_arm_narrow_only():
    yaml_block = {"donchian": 20, "atr_period": 14, "atr_stop_mult": 2.0}
    b = fbe.block_with_arm_params(yaml_block, donchian=20, atr_period=14, atr_stop_mult=2.0, long_only=False,
                                  side_filter="long")
    assert b["side_filter"] == "long" and fbe.resolve_side_filter(b) == "long"
    # "both" is the CLI default: it leaves the block's own value (an arm cannot widen a YAML side gate)
    short_leg = {**yaml_block, "side_filter": "short"}
    b2 = fbe.block_with_arm_params(short_leg, donchian=20, atr_period=14, atr_stop_mult=2.0, long_only=False,
                                   side_filter="both")
    assert b2["side_filter"] == "short"
    # the original keyword set (no side_filter) is byte-identical to before
    b3 = fbe.block_with_arm_params(yaml_block, donchian=30, atr_period=14, atr_stop_mult=2.0, long_only=False)
    assert "side_filter" not in b3 and b3["donchian"] == 30


def test_pullback_block_carries_direction_and_adx_arms():
    yaml_block = {"pullback_frac": 0.5, "adx_min": None}
    b = fbe.block_with_entry_gates(yaml_block, side_filter="short", adx_min=25.0)
    assert b["side_filter"] == "short" and b["adx_min"] == 25.0
    assert fbe.block_with_entry_gates(yaml_block) == yaml_block   # no arm gate -> the YAML block unchanged
    kept = fbe.block_with_entry_gates({"adx_min": 25.0}, adx_min=None)
    assert kept["adx_min"] == 25.0                                  # narrow-only: None never clears a YAML gate


def test_turtle_harness_timeframe_gate():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "backtest_turtle_soup.py"), "--data", "x.csv",
                        "--resample", "2h"], cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "1h / 4h" in r.stderr


def test_exit_lever_ablation_declares_the_timeframe_and_forming_fetch_flags():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "research" / "exit_lever_ablation.py"), "--help"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "--timeframe" in r.stdout and "--forming-1m-fetch" in r.stdout


def test_self_tests():
    for script in ("timeframe_lever_grade.py", "leg_r_diagnosis.py"):
        r = subprocess.run([sys.executable, str(REPO / "scripts" / "research" / script), "--self-test"],
                           cwd=str(REPO), capture_output=True, text=True, timeout=300)
        assert r.returncode == 0 and "self-test passed" in r.stdout, script + r.stdout[-2000:] + r.stderr[-2000:]


def test_exit_lever_ablation_refuses_a_finer_timeframe_than_native():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "research" / "exit_lever_ablation.py"), "--leg", "turtle_soup",
                        "--arm", "A=", "--grade", "stage0", "--baseline", "A", "--n-floor", "3", "--delta-r", "0",
                        "--fold-majority", "3", "--timeframe", "5m", "--out", "/tmp/_dfi_never_written"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "finer than the leg's native 15m" in r.stderr


def test_forming_equity_fetch_refuses_a_non_equity_leg():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "research" / "exit_lever_ablation.py"), "--leg", "turtle_soup",
                        "--arm", "A=", "--grade", "stage0", "--baseline", "A", "--n-floor", "3", "--delta-r", "0",
                        "--fold-majority", "3", "--start", "2026-07-01", "--end", "2026-11-01", "--forming-equity-fetch",
                        "--out", "/tmp/_dfi_never_written"], cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "US ETF 1d leg" in r.stderr


def test_regime_cell_lever_grade_self_test_and_walkforward_flags():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "research" / "regime_cell_lever_grade.py"), "--self-test"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "cosmetic cell" in r.stdout and "self-test passed" in r.stdout
    h = subprocess.run([sys.executable, str(REPO / "scripts" / "research" / "regime_cell_walkforward.py"), "--help"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert h.returncode == 0 and "--forming-1m-fetch" in h.stdout and "--start" in h.stdout and "--out-json" in h.stdout
