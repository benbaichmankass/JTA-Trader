"""The crypto structure-label ENTRY harness: self-test (synthetic Binance-style klines; no network)."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_self_test_passes():
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/ml_entry_crypto_struct.py"), "--self-test"],
                       capture_output=True, text=True, timeout=900, cwd=REPO)
    assert r.returncode == 0 and "self-test ok" in r.stdout, r.stdout + r.stderr
