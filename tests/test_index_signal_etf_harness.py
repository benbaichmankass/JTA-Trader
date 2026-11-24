"""IELE-INDEX-DRIVEN-HARNESS / IELE-DIRSWITCH-HARNESS: the harness self-tests run in CI (parity, no lookahead, cost stack on the ETF)."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(script: str) -> str:
    r = subprocess.run([sys.executable, str(REPO / "scripts/research" / script), "--self-test"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_index_signal_etf_harness_self_test():
    out = _run("index_signal_etf_harness.py")
    assert "SELF-TEST PASS" in out and "FAIL" not in out
    for needle in ("parity", "no lookahead", "cost_r = 2*slip", "entry price is the ETF open"):
        assert needle in out


def test_index_direction_switch_self_test():
    out = _run("index_direction_switch.py")
    assert "SELF-TEST PASS" in out and "FAIL" not in out
