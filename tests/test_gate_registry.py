"""GATE-REGISTRY: the gate registry DB, its refresh/drift scan, and the /api/bot/gates routes."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.runtime import gate_registry as gr

GUARDS_PY = '''GUARDS: List[Dict[str, Any]] = [
    {
        "name": "alpha-guard",
        "steps": [],
    },
    {
        "name": "beta-guard",
        "steps": [],
    },
]
'''


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(root)})


def _seed(root: Path) -> None:
    (root / "comms/gates").mkdir(parents=True)
    (root / "scripts/ci").mkdir(parents=True)
    (root / "src/runtime").mkdir(parents=True)
    (root / "scripts/ci/run_guards.py").write_text(GUARDS_PY)
    (root / "src/runtime/a.py").write_text('X = os.environ.get("OLD_FLAG_DISABLED")\n')
    (root / "src/runtime/b.py").write_text("def gate():\n    return False\n")
    seed = {
        "scan_baseline": {"env_flags": ["OLD_FLAG_DISABLED"], "ci_guards": ["alpha-guard"]},
        "decisions": {"decided_at": "2026-01-01", "decided_by": "operator", "decisions": [
            {"id": "G-REMOVE", "choice": "REMOVE", "note": "", "cat": "runtime-order-path"},
            {"id": "G-KEEP", "choice": "KEEP", "note": "keep it"},
            {"id": "G-PROPOSED", "choice": "REMOVE", "note": "", "cat": "proposed-w9",
             "where": "not in place: a proposal"},
        ]},
        "gates": [
            {"id": "G-REMOVE", "category": "runtime-order-path", "where": "src/runtime/b.py:1", "where_more": [],
             "blocks": "b", "added": "2026-01-01 abc fix (#1)", "auth": "NONE FOUND", "authorization": "NONE",
             "real_money": True, "hits_14d": "not measured: on the VM", "rec": "REMOVE", "effect": "BLOCKS-RIGHT"},
            {"id": "G-KEEP", "category": "writers", "where": "src/runtime/a.py:1", "where_more": [],
             "blocks": "a", "added": "2026-01-01 def x", "auth": "operator said so", "authorization": "VERBATIM",
             "real_money": False, "hits_14d": "not measured", "rec": "KEEP", "effect": "PREVENTS-WRONG"},
            {"id": "G-GONE", "category": "writers", "where": "src/runtime/gone.py:9", "where_more": [],
             "blocks": "c", "added": None, "auth": "x", "authorization": "PARAPHRASE", "real_money": False,
             "hits_14d": "not measured", "rec": "KEEP", "effect": "NEITHER"},
            {"id": "CI-alpha-guard", "category": "ci-guard", "where": "scripts/ci/run_guards.py:3", "where_more": [],
             "blocks": "merge", "added": None, "auth": "x", "authorization": "NONE", "real_money": False,
             "hits_14d": "not measured", "rec": "KEEP", "effect": "NEITHER"},
        ],
    }
    (root / gr.SEED_RELPATH).write_text(json.dumps(seed))
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _seed(root)
    db = str(tmp_path / "tj.db")
    monkeypatch.setattr(gr, "repo_root", lambda: root)
    monkeypatch.setattr(gr, "trade_journal_db_path", lambda: db)
    alerts: list[str] = []
    monkeypatch.setattr(gr, "_alert", lambda text: alerts.append(text) or True)
    return root, db, alerts


def _rows(db):
    c = gr.connect(db)
    try:
        return {g["id"]: g for g in gr.list_gates(c)["gates"]}
    finally:
        c.close()


def test_seed_decisions_drift_and_unregistered(tree):
    root, db, alerts = tree
    meta = gr.refresh(db, root)
    assert meta["read_state"] == "read", meta
    rows = _rows(db)
    # decisions applied; undecided default; never-in-code proposal carried as a row
    assert rows["G-REMOVE"]["operator_decision"] == "remove" and rows["G-REMOVE"]["implementation_state"] == "pending"
    assert rows["G-KEEP"]["operator_decision"] == "keep" and rows["G-KEEP"]["implementation_state"] == "as_is"
    assert rows["G-GONE"]["operator_decision"] == "undecided"
    assert rows["G-PROPOSED"]["mode_in_code"] is None
    # a cited file that is gone is drift, reported (alerted once), not blocked
    assert rows["G-GONE"]["drift"] == "site_missing" and rows["G-GONE"]["mode_in_code"] is None
    # a guard with no row → an unregistered row
    assert rows["CI-beta-guard"]["registry_state"] == "unregistered" and rows["CI-beta-guard"]["drift"] == "unregistered"
    assert rows["CI-alpha-guard"]["drift"] is None and rows["CI-alpha-guard"]["mode_in_code"] == "blocks"
    # hits are null with a read-state, never 0
    assert rows["G-KEEP"]["hits_14d"] is None and rows["G-KEEP"]["hits_read_state"] == "not_measurable"
    assert rows["G-REMOVE"]["added_at"] == "2026-01-01" and rows["G-REMOVE"]["real_money"] is True
    assert len(alerts) == 2
    gr.refresh(db, root)
    assert len(alerts) == 2  # each drifting row alerts once


def test_new_env_flag_is_reported_and_implementation_is_detected(tree):
    root, db, _alerts = tree
    gr.refresh(db, root)
    (root / "src/runtime/c.py").write_text('Y = os.environ.get("NEW_THING_ENABLED")\n')
    (root / "src/runtime/b.py").write_text("def gate():\n    return True  # removed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "remove the b gate G-REMOVE (#4242)")
    gr.refresh(db, root)
    rows = _rows(db)
    assert rows["UNREG-ENV-NEW_THING_ENABLED"]["registry_state"] == "unregistered"
    assert "OLD_FLAG" not in " ".join(rows)  # baseline flags are not reported
    r = rows["G-REMOVE"]
    assert r["implementation_state"] == "implemented" and r["implementation_pr"] == 4242
    assert r["mode_in_code"] == "removed" and r["implementation_sha"]


def test_operator_decision_wins_over_an_older_file_and_is_logged(tree):
    root, db, _ = tree
    gr.refresh(db, root)
    c = gr.connect(db)
    try:
        rec = gr.record_decision(c, "G-KEEP", "report_only", "make it a check", "operator")
        assert rec["decision"] == "report_only"
        with pytest.raises(ValueError):
            gr.record_decision(c, "G-KEEP", "maybe", None, "operator")
        with pytest.raises(KeyError):
            gr.record_decision(c, "NOPE", "keep", None, "operator")
    finally:
        c.close()
    gr.refresh(db, root)  # the seed's older KEEP must not overwrite it
    c = gr.connect(db)
    try:
        found = gr.get_gate(c, "G-KEEP")
    finally:
        c.close()
    assert found["gate"]["operator_decision"] == "report_only"
    assert found["gate"]["implementation_state"] == "pending"
    assert [h["decision"] for h in found["history"]] == ["report_only", "keep"]


def test_filters_and_counts(tree):
    root, db, _ = tree
    gr.refresh(db, root)
    c = gr.connect(db)
    try:
        everything = gr.list_gates(c)
        assert everything["population"]["total"] == everything["population"]["returned"]
        assert everything["gates"][0]["drift"]  # drift / unregistered first
        rm = gr.list_gates(c, real_money="true")
        assert [g["id"] for g in rm["gates"]] == ["G-REMOVE"]
        assert rm["population"]["total"] == everything["population"]["total"]
        assert {g["id"] for g in gr.list_gates(c, state="unregistered")["gates"]} == {"CI-beta-guard"}
        assert {g["id"] for g in gr.list_gates(c, decision="keep")["gates"]} == {"G-KEEP"}
        with pytest.raises(ValueError):
            gr.list_gates(c, state="bogus")
    finally:
        c.close()


@pytest.fixture
def client(tree):
    from src.web.api import main
    from src.web.api.auth import require_session
    from src.web.api.routers import gates as gates_router
    gates_router._bg_started = True  # no background thread in tests
    main.app.dependency_overrides[require_session] = lambda: {"email": "operator"}
    yield TestClient(main.app, raise_server_exceptions=False), tree
    main.app.dependency_overrides.pop(require_session, None)


def test_api_list_get_and_decide(client):
    c, _tree = client
    r = c.get("/api/bot/gates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["readState"] == "read" and body["population"]["total"] >= 6 and body["refresh"]["at"]
    assert c.get("/api/bot/gates?state=bogus").status_code == 400
    assert c.get("/api/bot/gates?real_money=maybe").status_code == 400
    one = c.get("/api/bot/gates/G-REMOVE").json()
    assert one["gate"]["operator_decision"] == "remove" and one["history"]
    assert c.get("/api/bot/gates/NOPE").status_code == 404
    p = c.post("/api/bot/gates/G-GONE/decision", json={"decision": "keep", "note": "fine"})
    assert p.status_code == 200, p.text
    assert p.json()["ok"] and "no code changed" in p.json()["message"]
    assert c.get("/api/bot/gates/G-GONE").json()["gate"]["operator_decision"] == "keep"
    assert c.post("/api/bot/gates/G-GONE/decision", json={"decision": "drop"}).status_code == 400
    assert c.post("/api/bot/gates/NOPE/decision", json={"decision": "keep"}).status_code == 404


def test_post_without_a_session_records_nothing(tree):
    root, db, _ = tree
    gr.refresh(db, root)
    from src.web.api import main
    from src.web.api.routers import gates as gates_router
    gates_router._bg_started = True
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.post("/api/bot/gates/G-GONE/decision", json={"decision": "remove"})
    assert r.status_code in (401, 403, 500, 503)
    assert _rows(db)["G-GONE"]["operator_decision"] == "undecided"
