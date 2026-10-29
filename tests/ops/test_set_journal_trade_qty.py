"""set-journal-trade-qty: the helper's own controls pass and the wrapper is wired."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ops" / "set_journal_trade_qty.py"


def test_self_test_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--self-test"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("PASS") >= 12 and "FAIL" not in r.stdout


def test_wrapper_is_dry_run_unless_apply_true():
    src = (REPO / "scripts/ops/set_journal_trade_qty_action.sh").read_text()
    assert "--apply" in src and "true|True) ARGS+=(--apply)" in src


def test_wrapper_syntax():
    r = subprocess.run(["bash", "-n", str(REPO / "scripts/ops/set_journal_trade_qty_action.sh")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
