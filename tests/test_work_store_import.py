"""WSD-S2-IMPORTER-PARITY: the files -> work_store.db importer is lossless, idempotent and one-way,
and the parity report detects every kind of drift it exists to detect.

Fixtures are tiny synthetic stores in the real on-disk layout (checklist row files + pipeline record
files), read by the real loaders (``checklist_store.load``, ``pipeline.load``). One test also runs the
importer over the repo's own live files: the round trip must be exact on all of them.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.ops import pipeline as pl
from scripts.ops import work_store_import as cli
from src.runtime import checklist_store as cs
from src.runtime import work_store as ws
from src.runtime import work_store_import as wi

REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 5)


def _write(repo: Path, rows: list[dict], records: list[dict]) -> None:
    cdir = repo / cs.STORE
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / cs.HEADER).write_text(json.dumps({"schema_version": 1, "items": []}))
    for r in rows:
        (cdir / f"{r['id']}.json").write_text(json.dumps(r))
    pdir = repo / pl.STORE
    pdir.mkdir(parents=True, exist_ok=True)
    for n, rec in enumerate(records):
        (pdir / f"20261105T0000{n:02d}000000Z-{n:08x}.json").write_text(json.dumps(rec))


ROWS = [
    {"id": "R-OPEN", "title": "open row", "phase": None, "state": "queued", "owner": "manager", "lane": None,
     "ceiling_usd": 8, "prs": [], "blocked_on": [], "note": "first note.", "model": "m", "tier": 2,
     "due_by": "2026-11-09", "roadmap": ["L-OPS"], "_seq": 1},
    {"id": "R-UNDATED", "title": "undated", "phase": None, "state": "landed_unproven", "owner": "manager",
     "lane": "s", "ceiling_usd": None, "prs": [1], "blocked_on": [], "note": "n", "roadmap": "L-OPS",
     "observation": {"what": "x"}, "_seq": 2},
    {"id": "R-DONE", "title": "done row", "phase": None, "state": "done", "owner": "manager", "lane": None,
     "ceiling_usd": 1.5, "prs": [], "blocked_on": [], "note": "closed because reasons", "_seq": 3},
]
REC = [
    {"id": "PI-1", "what": "observe a", "state": "queued", "next_action": "check_observation",
     "origin": {"kind": "session", "ref": "s", "rerun": "python3 a.py"},
     "due_when": {"kind": "date", "due_date": "2026-11-01"}},
    {"id": "PI-2", "what": "routed to a row", "state": "routed", "routed_to": "R-OPEN | why",
     "next_action": "check_observation", "origin": {"kind": "audit", "ref": "a", "rerun": "x"},
     "due_when": {"kind": "date", "due_date": "2026-12-01"}, "kind": "not-the-item-kind"},
    {"id": "PI-3", "what": "routed nowhere", "state": "routed", "routed_to": "GHOST",
     "next_action": "check_observation", "origin": {"kind": "audit", "ref": "a", "rerun": "x"},
     "due_when": {"kind": "date", "due_date": "2026-12-01"}},
    {"id": "PI-1", "what": "observe a", "state": "killed", "next_action": "check_observation",
     "origin": {"kind": "session", "ref": "s", "rerun": "python3 a.py"},
     "due_when": {"kind": "date", "due_date": "2026-11-01"}, "terminal_reason": "superseded by PI-2"},
]


@pytest.fixture()
def repo(tmp_path):
    _write(tmp_path, ROWS, REC)
    return tmp_path


@pytest.fixture()
def store(tmp_path):
    return ws.WorkStore(tmp_path / "db" / "work_store.db")


def test_import_is_lossless_and_parity_clean(repo, store):
    out = wi.run_import(repo, store)
    assert out["errors"] == [] and out["created"] == 3 + 3
    assert out["events"] == 3 + 4  # one per row, one per pipeline RECORD
    rep = wi.parity(repo, store, today=TODAY)
    assert rep["clean"], rep
    assert rep["rows"]["equal"] == 3 and rep["items"]["equal"] == 3
    assert rep["appendix_a"]["equal"]


def test_column_mapping_and_verbatim_extra(repo, store):
    wi.run_import(repo, store)
    o = store.get("R-OPEN")
    assert o["kind"] == "build" and o["due_rule"] == {"kind": "date", "due_date": "2026-11-09"}
    assert o["due_at"] == "2026-11-09T00:00:00Z" and o["roadmap"] == ["L-OPS"]
    assert o["extra"]["note"] == "first note."
    # a string roadmap does not fit the list column: kept verbatim in extra, round-trips as a string
    u = store.get("R-UNDATED")
    assert u["extra"]["roadmap"] == "L-OPS" and wi.to_row(u)["roadmap"] == "L-OPS"
    assert "due_by" not in wi.to_row(u)  # absent in the source -> absent in the projection
    # an undated open row arrives OPEN (no bulk drop), with what G1 would have said not enforced
    assert u["state"] == "landed_unproven"
    # int in a REAL column comes back an int (byte shape), float stays float
    assert wi.to_row(o)["ceiling_usd"] == 8 and isinstance(wi.to_row(o)["ceiling_usd"], int)
    assert wi.to_row(store.get("R-DONE"))["ceiling_usd"] == 1.5
    # a closed build's terminal_reason is its note (derived; never projected back)
    d = store.get("R-DONE")
    assert d["terminal_reason"] == "closed because reasons" and "terminal_reason" not in wi.to_row(d)


def test_pipeline_states_parents_and_collisions(repo, store):
    wi.run_import(repo, store)
    p1, p2, p3 = store.get("PI-1"), store.get("PI-2"), store.get("PI-3")
    assert p1["state"] == "dropped" and p1["terminal_reason"] == "superseded by PI-2"
    assert p2["state"] == "queued" and p2["parent_id"] == "R-OPEN"
    assert p3["state"] == "queued" and p3["parent_id"] is None  # unresolvable owner: no parent
    assert wi.to_pipeline_item(p3)["state"] == "routed"
    assert wi.to_pipeline_item(p1)["state"] == "killed"
    # a pipeline record's own `kind` key never becomes the item kind
    assert p2["kind"] == "observation" and wi.to_pipeline_item(p2)["kind"] == "not-the-item-kind"
    # every pipeline record is its own event, in order
    assert [json.loads(e["patch"])["record"]["state"] for e in store.events("PI-1")] == ["queued", "killed"]


def test_rerun_is_a_noop(repo, store):
    wi.run_import(repo, store)
    head = store.chain_head()
    out = wi.run_import(repo, store)
    assert out["created"] == out["updated"] == out["events"] == 0 and out["unchanged"] == 6
    assert store.chain_head() == head


def test_a_changed_row_is_one_event_and_a_note_append_records_only_the_append(repo, store):
    wi.run_import(repo, store)
    row = json.loads((repo / cs.STORE / "R-OPEN.json").read_text())
    row["note"] += " second."
    row["state"] = "in_flight"
    (repo / cs.STORE / "R-OPEN.json").write_text(json.dumps(row))
    out = wi.run_import(repo, store)
    assert out["updated"] == 1 and out["events"] == 1
    patch = json.loads(store.events("R-OPEN")[-1]["patch"])
    assert patch["note_append"] == " second." and patch["changed"] == {"state": "in_flight"}
    assert wi.parity(repo, store, today=TODAY)["clean"]


def test_a_new_pipeline_record_appends_one_event(repo, store):
    wi.run_import(repo, store)
    rec = dict(REC[2], state="done", terminal_reason="checked: fine")
    (repo / pl.STORE / "20261105T010000000000Z-ffffffff.json").write_text(json.dumps(rec))
    out = wi.run_import(repo, store)
    assert out["updated"] == 1 and out["events"] == 1
    assert store.get("PI-3")["state"] == "done"
    assert wi.parity(repo, store, today=TODAY)["clean"]


def test_parity_catches_a_silent_store_edit(repo, store):
    wi.run_import(repo, store)
    with sqlite3.connect(store.path) as c:
        c.execute("UPDATE items SET title = 'tampered' WHERE id = 'R-OPEN'")
    rep = wi.parity(repo, store, today=TODAY)
    assert not rep["clean"]
    assert rep["rows"]["differing"] == [{"id": "R-OPEN", "keys": ["title"]}]


def test_parity_catches_missing_and_db_only(repo, store):
    wi.run_import(repo, store)
    (repo / cs.STORE / "R-DONE.json").unlink()  # the importer never deletes: the store keeps it
    _write(repo, [dict(ROWS[0], id="R-NEW", _seq=9)], [])
    rep = wi.parity(repo, store, today=TODAY)
    assert rep["rows"]["db_only"] == ["R-DONE"] and rep["rows"]["missing_in_db"] == ["R-NEW"]
    assert not rep["clean"]


def test_native_items_are_reported_not_counted_as_drift(repo, store):
    wi.run_import(repo, store)
    store.create({"id": "SYNTH-1", "kind": "build", "title": "synthetic", "roadmap": ["L-OPS"],
                  "due_rule": {"kind": "date", "due_date": "2026-11-09"}}, by="s1-lane")
    rep = wi.parity(repo, store, today=TODAY)
    assert rep["clean"] and rep["native_db_only"] == ["SYNTH-1"]


def test_a_bad_entry_is_reported_and_does_not_abort_the_run(repo, store):
    bad = dict(ROWS[0], id="R-BAD", state="not-a-state", _seq=4)
    _write(repo, [bad], [])
    out = wi.run_import(repo, store)
    assert [e["id"] for e in out["errors"]] == ["R-BAD"]
    assert store.get("R-OPEN") is not None and store.get("R-BAD") is None
    rep = wi.parity(repo, store, today=TODAY)
    assert rep["rows"]["missing_in_db"] == ["R-BAD"] and not rep["clean"]


def test_s1_store_without_extra_column_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.executescript(ws.SCHEMA.replace("  extra           TEXT,\n", ""))
    assert "extra" not in {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(items)")}
    ws.WorkStore(path)
    assert "extra" in {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(items)")}


def test_cli_apply_appends_a_report_and_summary_needs_coverage(repo, tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    monkeypatch.setattr(cli, "log_dir", lambda: logs)
    db = str(tmp_path / "db2" / "work_store.db")
    assert cli.main(["--apply", "--db", db, "--repo", str(repo)]) == 0
    lines = cli.read_log(logs)
    assert len(lines) == 1 and lines[0]["clean"] and lines[0]["readState"] == "read"
    assert json.loads((logs / cli.LATEST_NAME).read_text())["clean"]
    # one clean run is not a clean 2-day window
    s = cli.summarize(lines)
    assert s["unclean_runs"] == 0 and not s["window_covered"] and not s["window_clean"]


def test_summary_window_clean_only_when_covered_and_every_run_clean():
    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    runs = [{"at": (now - timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "clean": True}
            for i in range(48 * 12, -1, -1)]
    assert cli.summarize(runs, now=now)["window_clean"]
    runs[100]["clean"] = False
    s = cli.summarize(runs, now=now)
    assert not s["window_clean"] and s["unclean_runs"] == 1


def test_cli_failure_is_could_not_look_never_clean(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    monkeypatch.setattr(cli, "log_dir", lambda: logs)
    (tmp_path / "r" / cs.STORE).mkdir(parents=True)
    (tmp_path / "r" / cs.STORE / "BAD.json").write_text("{not json")
    assert cli.main(["--apply", "--db", str(tmp_path / "w.db"), "--repo", str(tmp_path / "r")]) == 1
    line = cli.read_log(logs)[0]
    assert line["readState"] == "could_not_look" and line["clean"] is False


def test_repo_files_round_trip_exactly(tmp_path):
    """The real checklist + pipeline on this checkout: every record must project back byte-exact."""
    store = ws.WorkStore(tmp_path / "w.db")
    out = wi.run_import(REPO, store)
    assert out["errors"] == []
    rep = wi.parity(REPO, store)
    assert rep["rows"]["differing_count"] == 0, rep["rows"]["differing"][:5]
    assert rep["items"]["differing_count"] == 0, rep["items"]["differing"][:5]
    assert rep["appendix_a"]["equal"] and rep["chain"]["ok"]


def test_api_parity_route_and_checklist_source_db(tmp_path, monkeypatch):
    """GET /api/bot/work/parity reads the timer's log; ?source=db serves the store's projection."""
    from fastapi.testclient import TestClient
    logs = tmp_path / "logs"
    monkeypatch.setattr(cli, "log_dir", lambda: logs)
    monkeypatch.setenv("WORK_STORE_DB", str(tmp_path / "api.db"))
    from src.web.api.main import app
    c = TestClient(app)
    assert c.get("/api/bot/work/parity").json()["readState"] == "absent"
    cli.append_report({"at": "2026-11-05T09:00:00Z", "clean": True, "readState": "read"}, logs)
    body = c.get("/api/bot/work/parity").json()
    assert body["readState"] == "read" and body["latest"]["clean"] and body["window"]["runs"] >= 0
    # the default checklist route is unchanged; source=db serves rows from the store, marked
    store = ws.WorkStore(tmp_path / "api.db")
    wi.run_import(REPO, store)
    files = c.get("/api/bot/work/checklist").json()
    db = c.get("/api/bot/work/checklist?source=db").json()
    # WSD-S4: the repo is frozen, so the store-served payload is the canonical one
    assert "source" not in files and db["source"] == "db" and db["canonical"] is True
    assert [i["id"] for i in db["items"]] == [i["id"] for i in files["items"]]
