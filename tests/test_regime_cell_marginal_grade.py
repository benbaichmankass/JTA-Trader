import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import regime_cell_marginal_grade as M  # noqa: E402


def test_self_test_runs():
    M._selftest()


def test_no_legs_is_producer_failed(tmp_path):
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/regime_cell_marginal_grade.py"), "--out", str(tmp_path),
                        "--leg", "x=/nonexistent"], capture_output=True, text=True, check=False)
    assert r.returncode != 0  # a missing file is an error, never a verdict


def test_underpowered_never_fails():
    rows = [{"direction": "long", "net_r": 1.0, "regime": "chop", "vol_regime": "calm", "_t": 1000.0 + i} for i in range(10)]
    g = M.grade_cell(rows, ("chop", "calm", "long"), 1000.0, 1010.0, draws=20)
    assert g["verdict"] == "indeterminate_underpowered" and g["added_r"] < 0
