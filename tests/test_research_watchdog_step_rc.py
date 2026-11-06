"""The research-watchdog "Watch" step: rc 1 (clean escalation) must end GREEN, rc >= 2 (crash) RED.

GitHub runs `run:` under `bash -e`; the step's `set -uo pipefail` does not clear -e, so a bare pipeline
rc 1 killed the step before `rc=${PIPESTATUS[0]}` (MEASURED: 5 scheduled runs paged "[RUN failure]"
after a clean escalation, 2026-11-06). The shipping script is extracted from the workflow, never copied.
"""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/research-watchdog.yml"


def _script(tmp: Path, rc: int) -> Path:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(s for j in wf["jobs"].values() for s in j["steps"] if s.get("name") == "Watch")
    body = step["run"].replace("${{ github.event_name }}", "push").replace("${{ inputs.live }}", "false")
    lines = [ln for ln in body.splitlines()]
    i = next(k for k, ln in enumerate(lines) if "research_watchdog.py" in ln)
    lines[i] = f"printf 'line\\n' > /tmp/rows.jsonl; (echo out; exit {rc}) | tee /tmp/watchdog.txt"
    s = tmp / "step.sh"
    s.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return s


def _exit(tmp_path, rc):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not installed")
    env = {"GITHUB_OUTPUT": str(tmp_path / "out"), "GITHUB_STEP_SUMMARY": str(tmp_path / "sum"), "PATH": "/usr/bin:/bin"}
    return subprocess.run([bash, "-e", str(_script(tmp_path, rc))], env=env, capture_output=True, text=True).returncode


@pytest.mark.parametrize("rc,green", [(0, True), (1, True), (2, False), (127, False)])
def test_watch_step_exit(tmp_path, rc, green):
    assert (_exit(tmp_path, rc) == 0) is green
