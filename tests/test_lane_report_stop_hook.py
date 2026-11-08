"""Lane stuck-wake Stop hook: planted silent stalls block, reports/non-lanes/the manager pass, fails open."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts/ops/lane_report_stop_hook.py"


def test_self_test_passes():
    r = subprocess.run([sys.executable, str(HOOK), "--self-test"], capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def test_fails_open_on_missing_transcript():
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"transcript_path": "/nonexistent"}),
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_blocks_a_silent_lane_stall(tmp_path):
    t = tmp_path / "t.jsonl"
    rows = [{"type": "user", "message": {"content": "You are lane X, dispatched by Manager Session 2026-11-07a (session_01AFoLuJ3yguifJsDomuAzGx)."}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Export sha mismatch; re-export awaits go-ahead."}]}}]
    t.write_text("\n".join(json.dumps(r) for r in rows))
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"transcript_path": str(t)}), capture_output=True, text=True, timeout=60, check=False)
    out = json.loads(r.stdout)
    assert out["decision"] == "block" and "session_01AFoLuJ3yguifJsDomuAzGx" in out["reason"]
    r2 = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"transcript_path": str(t), "stop_hook_active": True}),
                        capture_output=True, text=True, timeout=60, check=False)
    assert r2.stdout.strip() == "", "never blocks twice in a row"
