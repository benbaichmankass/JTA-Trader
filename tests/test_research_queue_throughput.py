import subprocess
import sys
from pathlib import Path

from scripts.ci import check_research_queue_throughput as C
from scripts.research import queue_throughput as T

REPO = Path(__file__).resolve().parents[1]


def test_alarm_self_test_passes():
    assert C._self_test() == 0


def test_real_queue_is_readable_and_summarised():
    t = T.throughput(REPO)
    assert t["units"] > 0 and t["runnable"] >= 0 and "idle_alarm" in t
    assert "fired" in T.summary_line(t)


def test_keeper_runs_the_alarm_outside_the_dispatch_job():
    wf = (REPO / ".github/workflows/schedule-keeper.yml").read_text()
    assert "check_research_queue_throughput.py" in wf
    assert "research_throughput.outcome == 'failure'" in wf


def test_brief_renders_throughput_or_declared_hole():
    sys.path.insert(0, str(REPO))
    from scripts.ops import render_daily_brief as B
    assert "Research queue" in "\n".join(B._research_lines({"researchThroughput": None}))
    t = T.throughput(REPO)
    assert "research queue (24h)" in "\n".join(B._research_lines({"researchThroughput": t}))


def test_session_bound_unit_is_not_a_dispatch_failure(tmp_path, capsys):
    import json
    import yaml
    from scripts.research import dispatch_queue
    u = {"id": "RQ-20260901-001", "status": "queued", "cadence": "once", "theme": "infra", "priority": 2, "title": "t", "question": "q",
         "run": {"workflow": "none -- session-local"}, "lands": {"store": "s"}}
    (tmp_path / "RQ-20260901-001.yaml").write_text(yaml.safe_dump(u))
    rc = dispatch_queue.main(["--queue-dir", str(tmp_path), "--json"])
    row = json.loads(capsys.readouterr().out)["decisions"][0]
    assert row["outcome"] == "not_due" and "session-bound" in row["reason"] and rc == 0
    assert subprocess.run([sys.executable, str(REPO / "scripts/ci/check_research_queue_throughput.py"), "--self-test"],
                          cwd=REPO).returncode == 0


def test_runs_as_a_script_from_outside_the_repo(tmp_path):
    """PI-20261112-ZZU98A5J-0001: `python3 scripts/research/queue_throughput.py` crashed on import
    (ModuleNotFoundError: scripts) unless PYTHONPATH=. was set."""
    import os
    import sys
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "scripts" / "research" / "queue_throughput.py"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert "ModuleNotFoundError" not in r.stderr, r.stderr[-500:]
    assert r.returncode == 0, r.stderr[-500:]
