"""The w9 gate REPORTS: controls pass, and the report never exits 1 (operator 2026-11-12, reports only)."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = [sys.executable, str(REPO / "scripts/ci/report_w9_gates.py")]


def test_self_test_controls_pass():
    r = subprocess.run(SCRIPT + ["--self-test"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout


def test_report_never_blocks_and_emits_json():
    r = subprocess.run(SCRIPT + ["--json"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert {x["check"] for x in out} == {"ml-advisory-scope", "lever-consumer-parity", "prop-floor", "active-mgmt-standard"}
    for x in out:
        assert x["read_state"] in ("ok", "could_not_look") and "population" in x
