"""UI-API-HEAVY-ROUTES-502: the registry memo and the opt-in ?runs_tail=N slim rows."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.api.routers import training_center as tc


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNTIME_LOGS_DIR", str(tmp_path / "runtime_logs"))
    monkeypatch.setenv("ICT_REPO_ROOT", str(tmp_path))
    tc._registry_memo.clear()
    from src.web.api import main
    yield TestClient(main.app), tc._mirror_root() / "registry.jsonl"
    tc._registry_memo.clear()


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _row(mid: str, n: int) -> dict:
    return {"model_id": mid, "target_deployment_stage": "candidate",
            "runs": [{"run_id": f"r{i}"} for i in range(n)], "history": [{"at": i} for i in range(n)]}


def test_runs_tail_keeps_the_last_n_and_states_totals(env):
    c, path = env
    _write(path, [_row("m1", 5)])
    full = c.get("/api/bot/ml/registry").json()
    m1 = next(r for r in full["rows"] if r["model_id"] == "m1")
    assert len(m1["runs"]) == 5 and "runs_total" not in m1 and "runs_tail" not in full
    slim = c.get("/api/bot/ml/registry?runs_tail=2").json()
    s1 = next(r for r in slim["rows"] if r["model_id"] == "m1")
    assert [r["run_id"] for r in s1["runs"]] == ["r3", "r4"] and s1["runs_total"] == 5
    assert len(s1["history"]) == 2 and s1["history_total"] == 5
    assert s1["latest_run"] == {"run_id": "r4"}  # the enrichment still reads the full list
    assert slim["runs_tail"] == 2 and slim["count"] == full["count"]
    zero = next(r for r in c.get("/api/bot/ml/registry?runs_tail=0").json()["rows"] if r["model_id"] == "m1")
    assert zero["runs"] == [] and zero["runs_total"] == 5
    assert c.get("/api/bot/ml/registry?runs_tail=-1").status_code == 422
    # The slim view never mutates the memoized full body.
    again = next(r for r in c.get("/api/bot/ml/registry").json()["rows"] if r["model_id"] == "m1")
    assert len(again["runs"]) == 5


def test_memo_is_invalidated_when_the_mirror_changes(env):
    c, path = env
    _write(path, [_row("m1", 1)])
    assert {r["model_id"] for r in c.get("/api/bot/ml/registry").json()["rows"]} >= {"m1"}
    _write(path, [_row("m1", 1), _row("m2", 3)])
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    ids = {r["model_id"] for r in c.get("/api/bot/ml/registry").json()["rows"]}
    assert {"m1", "m2"} <= ids


def test_direct_python_call_still_returns_the_full_shape(env):
    _c, path = env
    _write(path, [_row("m1", 3)])
    body = tc.get_registry()
    m1 = next(r for r in body["rows"] if r["model_id"] == "m1")
    assert len(m1["runs"]) == 3 and "mirror_age_seconds" in body
