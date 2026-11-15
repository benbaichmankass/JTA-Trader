"""Self-tests of the opt-in attempt-3 iteration grids (units RQ-20261113-62e3-01..04) on the RESEARCH-EDGE harnesses.

Each harness keeps its committed grid as the DEFAULT; the self-test asserts that identity plus the new arm mechanics
(funding-aware side filter, residual momentum, dividend factor, time-only exit) on synthetic data. No network, no archive.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script", [
    "scripts/research/edge_portfolio_discovery.py",
    "scripts/research/edge_etf_tsmom.py",
    "scripts/research/edge_movement_capture.py",
])
def test_harness_self_test(script):
    r = subprocess.run([sys.executable, str(REPO / script), "--self-test"], cwd=REPO, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout
    assert r.stdout.count("PASS") >= 6
