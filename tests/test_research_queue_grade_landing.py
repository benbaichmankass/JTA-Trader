"""The grade job's landing step must re-derive dispositions when the stale-branch refresh conflicts.

Run 45567748608: refresh=failed_conflict, PR stranded, 80-min verify wait, step failed. commit-to-main only
re-derives conflicted generated files when the caller passes `refresh-command`.
"""
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github/workflows/research-queue-grade.yml"


def test_landing_step_declares_refresh_command():
    wf = yaml.safe_load(WF.read_text())
    steps = wf["jobs"]["grade"]["steps"]
    land = [s for s in steps if s.get("name") == "Land the dispositions on main"]
    assert len(land) == 1
    w = land[0]["with"]
    assert w["verify-merged"] == "true"
    assert "queue_grade.py --write" in w.get("refresh-command", "")
