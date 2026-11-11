"""FEATURE-IMPACT-MAP v0: the script's self-test (shares, ensemble sum, no silent 0, no halting) runs in CI."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_feature_impact_self_test():
    r = subprocess.run([sys.executable, str(REPO / "scripts/ml/feature_impact.py"), "--self-test"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "self-test: OK" in r.stdout
