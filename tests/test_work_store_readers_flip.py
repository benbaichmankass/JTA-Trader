"""WSD-S4-READERS-FLIP: freeze the files, flip every reader to work_store.db, keep the rollback.

Design: docs/plans/WORK-STORE-DESIGN-2026-11.md § 4 steps 2-3, § 6 S4, § 7.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts.ops import pipeline as pl
from scripts.ops import work as work_cli
from src.runtime import checklist_store as cs
from src.runtime import work_read as wr
from src.runtime import work_store as ws
from src.runtime import work_store_import as wi
from tests.test_work_store_import import REC, ROWS, _write

REPO = Path(__file__).resolve().parents[1]


def _freeze(repo: Path, on: bool = True) -> None:
    hp = repo / cs.STORE / cs.HEADER
    h = json.loads(hp.read_text())
    if on:
        h[wr.FROZEN_KEY] = {"row": "WSD-S4-READERS-FLIP"}
    else:
        h.pop(wr.FROZEN_KEY, None)
    hp.write_text(json.dumps(h))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A fixture repo treated as THE repo, its files imported into a store at WORK_STORE_DB."""
    repo = tmp_path / "repo"
    _write(repo, ROWS, REC)
    db = tmp_path / "db" / "work_store.db"
    monkeypatch.setenv("WORK_STORE_DB", str(db))
    monkeypatch.setattr(wr, "REPO", repo)
    monkeypatch.setattr(cs, "REPO", repo)
    store = ws.WorkStore(db)
    assert wi.run_import(repo, store)["errors"] == []
    return repo, store


def _files_rows(repo):
    return [{k: v for k, v in r.items() if k != cs.SEQ} for r in cs._read_rows(repo / cs.STORE)]


def test_unfrozen_reads_files_frozen_reads_the_store(env):
    repo, store = env
    it = store.get("R-OPEN")
    store.set("R-OPEN", {"title": "edited natively"}, by="session_x", expected_version=it["version"])
    assert cs.load(repo)["items"][0]["title"] == "open row"          # not frozen: the files
    _freeze(repo)
    rows = cs.load(repo)["items"]
    assert [r["id"] for r in rows] == ["R-OPEN", "R-UNDATED", "R-DONE"]  # the checklist's own order
    assert rows[0]["title"] == "edited natively"                       # frozen: the store
    assert _files_rows(repo)[0]["title"] == "open row"                 # the export is untouched
    assert cs.read_row("R-OPEN", repo)["title"] == "edited natively"


def test_a_fixture_or_archive_path_is_never_flipped(env, tmp_path):
    repo, _ = env
    _freeze(repo)
    other = tmp_path / "other"
    _write(other, ROWS[:1], [])
    _freeze(other)
    assert [r["id"] for r in cs.load(other)["items"]] == ["R-OPEN"]  # not the canonical repo: files


def test_no_local_db_means_the_export_files(env, monkeypatch, tmp_path):
    repo, _ = env
    _freeze(repo)
    monkeypatch.setenv("WORK_STORE_DB", str(tmp_path / "absent.db"))
    assert [r["id"] for r in cs.load(repo)["items"]] == ["R-OPEN", "R-UNDATED", "R-DONE"]


def test_a_failed_store_read_raises_never_empty(env, monkeypatch):
    repo, _ = env
    _freeze(repo)
    monkeypatch.setattr(wr, "checklist_rows", lambda s: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        cs.load(repo)


def test_frozen_write_row_goes_to_the_store_not_the_file(env):
    repo, store = env
    _freeze(repo)
    before = (repo / cs.STORE / "R-OPEN.json").read_text()
    row = cs.read_row("R-OPEN", repo)
    row["note"] = row["note"] + " appended."
    row["updated_by"] = "session_y"
    cs.write_row(row, repo)
    assert (repo / cs.STORE / "R-OPEN.json").read_text() == before
    got = cs.read_row("R-OPEN", repo)
    assert got["note"] == "first note. appended." and got == {**row}
    assert store.get("R-OPEN")["updated_by"] == "session_y"
    # a new row lands in the store, after the others, and the file is never created
    cs.write_row({"id": "R-NEW", "title": "new", "state": "queued", "owner": "manager",
                  "due_by": "2026-11-20", "roadmap": ["L-OPS"], "note": ""}, repo)
    assert not (repo / cs.STORE / "R-NEW.json").exists()
    assert [r["id"] for r in cs.load(repo)["items"]][-1] == "R-NEW"


def test_frozen_write_refused_by_the_store_raises(env):
    repo, _ = env
    _freeze(repo)
    with pytest.raises(wr.WorkWriteError):  # the store's own validator answers (an empty title)
        cs.write_row({"id": "R-BAD", "title": "  ", "state": "queued", "owner": "manager",
                      "due_by": "2026-11-20", "roadmap": ["L-OPS"]}, repo)


def test_checklist_cli_writes_through(env):
    repo, store = env
    _freeze(repo)
    from scripts.ops import checklist as ccli
    ccli.op_note(repo, "R-OPEN", "via the cli.", True, "session_z")
    assert store.get("R-OPEN")["extra"]["note"] == "first note. via the cli."
    assert json.loads((repo / cs.STORE / "R-OPEN.json").read_text())["note"] == "first note."


def test_pipeline_reads_and_writes_through(env):
    repo, store = env
    _freeze(repo)
    pstore = repo / pl.STORE
    res = pl.read_log(pstore)
    assert set(res.items) == {"PI-1", "PI-2", "PI-3"} and res.due_now is not None
    assert res.sources["PI-2"].startswith("work_store:v")
    n_files = len(list(pstore.glob("*.json")))
    cur = dict(res.items["PI-3"])
    cur.update(state="killed", terminal_reason="no owner; closed in the test")
    pl.append(cur, pstore, intent="update", based_on=pl.version_of("PI-3", pstore))
    assert len(list(pstore.glob("*.json"))) == n_files                 # no record file written
    assert store.get("PI-3")["state"] == "dropped"
    assert pl.read_log(pstore).items["PI-3"]["state"] == "killed"
    with pytest.raises(pl.PipelineError, match="STALE SNAPSHOT"):
        pl.append(cur, pstore, intent="update", based_on="work_store:v1")
    assert pl.read_files(pstore).items["PI-3"]["state"] == "routed"     # the export is frozen


def test_importer_never_writes_back_over_a_native_write(env):
    repo, store = env
    _freeze(repo)
    it = store.get("R-OPEN")
    store.set("R-OPEN", {"title": "native"}, by="session_x", expected_version=it["version"])
    # a straggler file change to a row nobody touched natively IS imported (nothing lost at cutover)
    (repo / cs.STORE / "R-UNDATED.json").write_text(json.dumps({**ROWS[1], "title": "late file edit"}))
    out = wi.run_import(repo, store)
    assert out["errors"] == []
    assert store.get("R-OPEN")["title"] == "native"
    assert store.get("R-UNDATED")["title"] == "late file edit"
    rep = wi.parity(repo, store)
    assert rep["rows"]["differing_count"] == 0 and rep["rows"]["native_divergent_count"] == 1
    assert rep["clean"]


def test_checklist_route_shape_is_unchanged_fixture_diff(env, monkeypatch):
    """THE SHAPE PROOF: the SPA's /work/checklist envelope served from the store equals the one
    served from the files for the same data -- every key, every item, the summary."""
    repo, store = env
    from src.web.api.routers import work as router
    monkeypatch.setattr(router, "repo_root", lambda: str(repo))
    monkeypatch.setattr(router, "_checklist_cache", None)
    from_files = router._checklist_payload()
    _freeze(repo)
    from_store = router._checklist_payload()
    assert from_store["present"] and from_store["readState"] == "read"
    assert set(from_store) == set(from_files)
    assert set(from_store["freshness"]) == set(from_files["freshness"])
    for k in from_files:
        if k != "freshness":
            assert from_store[k] == from_files[k], k
    assert from_store["freshness"]["warnings"] == []


def test_export_round_trip_is_the_rollback(env, tmp_path):
    repo, store = env
    _freeze(repo)
    it = store.get("R-OPEN")
    store.set("R-OPEN", {"title": "native"}, by="s", expected_version=it["version"])
    store.create({"id": "R-NATIVE", "kind": "build", "title": "filed after the freeze",
                  "due_rule": {"kind": "date", "due_date": "2026-11-30"}, "roadmap": ["L-OPS"]}, by="s")
    o = store.get("PI-3")
    store.close("PI-3", state="dropped", reason="closed natively", by="s", expected_version=o["version"])
    live_rows = cs.load(repo)["items"]
    live_pipe = pl.read_log(repo / pl.STORE).items
    out = work_cli.export_to_files(repo, store.list_items(limit=10 ** 6), unfreeze=True)
    assert out["unfrozen"] and out["rows_written"] == 2 and out["records_written"] == 1
    assert not wr.frozen(repo)
    assert {r["id"]: r for r in cs.load(repo)["items"]} == {r["id"]: r for r in live_rows}
    assert pl.read_files(repo / pl.STORE).items == live_pipe
    # idempotent: a second export writes nothing
    again = work_cli.export_to_files(repo, store.list_items(limit=10 ** 6))
    assert again["rows_written"] == 0 and again["records_written"] == 0


def test_brief_section0_is_due_now(env):
    repo, store = env
    _freeze(repo)
    from scripts.ops import render_daily_brief as rb
    res = pl.read_log(repo / pl.STORE)
    obs, builds = wr.due_now_split(store)
    lines = "\n".join(rb.section0_lines(res, date.today()))
    assert f"**{len(obs) + len(builds)} due**" in lines
    assert [i["id"] for i in rb.ranked_items(res, date.today())] == sorted(
        obs, key=lambda i: rb._rank_key(res.items[i]))


def test_the_repo_is_frozen_and_routes_to_the_store():
    """The committed freeze: the real header carries the key, so readers on the VM read the store."""
    assert wr.frozen(REPO)
    head = json.loads((REPO / cs.STORE / cs.HEADER).read_text())
    assert "work.py" in head[wr.FROZEN_KEY]["write_with"]


def test_a_monkeypatched_store_global_is_never_canonical(env, tmp_path, monkeypatch):
    """Regression (CI 2026-11-06): pipeline.STORE patched to a tmp dir made that dir 'canonical'
    (REPO / <absolute> == <absolute>), so a test's append reached the live API."""
    repo, _ = env
    _freeze(repo)
    tmp_store = tmp_path / "pl"
    monkeypatch.setattr(pl, "STORE", tmp_store)
    assert not wr.is_canonical(tmp_store, tmp_store)
    assert not wr.is_canonical(tmp_store, wr.PIPELINE_STORE)
    pl.append(dict(REC[0], id="PI-TMP"), tmp_store, intent="new")
    assert "PI-TMP" in pl.read_files(tmp_store).items  # written to the tmp FILES, not any store


def test_tests_never_reach_the_live_api(monkeypatch, tmp_path):
    monkeypatch.setenv("WORK_STORE_DB", str(tmp_path / "absent.db"))
    monkeypatch.delenv("WORK_STORE_URL", raising=False)
    with pytest.raises(wr.WorkWriteError, match="live work-store API"):
        wr.get_row("ANY")


# ── last_review lives in the store (WSD-S4-READERS-FLIP, manager decision 2026-11-12) ────────────

LR = {"report_id": "WR-1", "reviewed_at": "2026-11-12T05:58:00Z", "by": "mgr"}


def _header_bytes(repo):
    return (repo / cs.STORE / cs.HEADER).read_bytes()


def test_meta_roundtrip_versioned(env):
    _, store = env
    assert store.meta_get("last_review") is None
    a = store.meta_set("last_review", LR, by="s")
    b = store.meta_set("last_review", {**LR, "report_id": "WR-2"}, by="s")
    assert (a["version"], b["version"]) == (1, 2)
    assert store.meta_get("last_review")["value"]["report_id"] == "WR-2"
    with pytest.raises(ws.WorkStoreValidationError):
        store.meta_set("items", {}, by="s")


def test_frozen_header_write_goes_to_store_not_file(env, monkeypatch):
    repo, store = env
    _freeze(repo)
    before = _header_bytes(repo)
    cs.write_header("last_review", LR, repo, by="session_x")
    assert _header_bytes(repo) == before                      # the register folder is untouched
    assert store.meta_get("last_review")["value"] == LR
    assert cs.load(repo)["last_review"] == LR                 # readers see the store's value


def test_file_value_is_fallback_when_store_lacks_the_key(env):
    repo, _ = env
    _freeze(repo)
    hp = repo / cs.STORE / cs.HEADER
    h = json.loads(hp.read_text())
    h["last_review"] = {"report_id": "OLD"}
    hp.write_text(json.dumps(h))
    assert cs.load(repo)["last_review"] == {"report_id": "OLD"}


def test_unfrozen_header_write_still_writes_file(env):
    repo, store = env
    cs.write_header("last_review", LR, repo)
    assert json.loads(_header_bytes(repo))["last_review"] == LR
    assert store.meta_get("last_review") is None


def test_other_header_keys_still_write_the_file(env):
    repo, store = env
    _freeze(repo)
    cs.write_header("updated_by", "x", repo)
    assert json.loads(_header_bytes(repo))["updated_by"] == "x"


def test_cli_op_meta_shape_and_outbox_roundtrip():
    o = work_cli.make_op("meta", "last_review", {"value": LR}, "s", "op1")
    parsed = work_cli.parse_outbox_comment(work_cli.outbox_comment(o))
    assert parsed == o


def test_export_writes_header_keys_back(env, tmp_path):
    repo, store = env
    store.meta_set("last_review", LR, by="s")
    root = tmp_path / "exp"
    (root / cs.STORE).mkdir(parents=True)
    (root / cs.STORE / cs.HEADER).write_text(json.dumps({"schema_version": 2}))
    out = work_cli.export_to_files(root, store.list_items(limit=10 ** 6),
                                   header_meta=work_cli._header_meta(store.path))
    assert out["header_keys_written"] == ["last_review"]
    assert json.loads((root / cs.STORE / cs.HEADER).read_text())["last_review"] == LR
