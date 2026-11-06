"""WSD-S6D-RESEARCH-RESULTS: the research results store (scripts/research/research_store.py) and its
live-VM projection (src/units/db/trainer_store.py::_build_research_runs)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from src.units.db import trainer_store as ts

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "research" / "research_store.py"


def test_research_store_self_test():
    r = subprocess.run([sys.executable, str(SCRIPT), "--self-test"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "self-test: OK" in r.stdout


def test_trainer_store_ingests_research_runs(tmp_path):
    mirror = tmp_path / "trainer_mirror"
    (mirror / "research").mkdir(parents=True)
    rows = [
        {"event_id": "a" * 64, "unit_id": "RQ-20301231-001", "kind": "result", "run_key": "77", "at": "2030-12-31T00:00:00Z",
         "verdict": "pass", "read_state": "measured", "n": 40, "decision_rule_id": "RULE-X", "workflow": "research-script-run",
         "payload_sha256": "b" * 64, "first_source": "runner:research-queue-dispatch:1",
         "sources": ["runner:research-queue-dispatch:1"], "recorded_at": "2030-12-31T00:01:00Z", "summary": {"rows": 1}},
        {"event_id": "c" * 64, "unit_id": "RQ-20301231-001", "kind": "grade", "run_key": "k", "at": "2030-12-31",
         "verdict": None, "read_state": "needs_review", "n": None, "first_source": "git_backfill", "sources": ["git_backfill"],
         "recorded_at": "2030-12-31T00:02:00Z"},
    ]
    (mirror / "research" / "research_runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    db = tmp_path / "trainer_store.db"
    counts = ts.ingest_trainer_store(mirror_root=mirror, db_path=str(db))
    assert counts["research_runs"] == 2
    assert "research_runs" in ts.TRAINER_STORE_TABLES
    with sqlite3.connect(db) as conn:
        got = conn.execute("SELECT kind, verdict, n, json(sources) FROM research_runs ORDER BY kind").fetchall()
    # a null verdict / n stays NULL (rendered "--"), never 0
    assert got == [("grade", None, None, '["git_backfill"]'),
                   ("result", "pass", 40, '["runner:research-queue-dispatch:1"]')]


def test_trainer_store_research_runs_absent_mirror_file_is_empty(tmp_path):
    mirror = tmp_path / "trainer_mirror"
    mirror.mkdir()
    counts = ts.ingest_trainer_store(mirror_root=mirror, db_path=str(tmp_path / "t.db"))
    assert counts["research_runs"] == 0


def test_db_explorer_allowlists_research_runs():
    src = (REPO / "src" / "web" / "api" / "routers" / "db_explorer.py").read_text()
    assert '"research_runs"' in src


def test_research_runs_view_states_read_state(tmp_path):
    mirror = tmp_path / "trainer_mirror"
    mirror.mkdir()
    v = ts.research_runs_view(mirror_root=mirror, db_path=str(tmp_path / "t.db"))
    assert v["read_state"] == "no_mirror_file" and v["total"] is None and v["mirror_file_mtime"] is None
    (mirror / "research").mkdir()
    (mirror / "research" / "research_runs.jsonl").write_text(json.dumps(
        {"event_id": "a" * 64, "unit_id": "RQ-20301231-001", "kind": "dispatch", "run_key": "t", "at": "t",
         "first_source": "runner:research-queue-dispatch:9", "sources": ["runner:research-queue-dispatch:9"],
         "recorded_at": "2030-12-31T00:00:00Z"}) + "\n")
    v = ts.research_runs_view(mirror_root=mirror, db_path=str(tmp_path / "t.db"), unit="RQ-20301231-001")
    assert v["read_state"] == "read" and v["total"] == 1 and v["by_source"] == {"runner": 1}
    assert v["rows"][0]["sources"] == ["runner:research-queue-dispatch:9"] and v["ingested_at"]
