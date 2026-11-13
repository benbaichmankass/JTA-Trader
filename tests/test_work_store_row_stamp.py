"""WORK-ROW-AGE-STALE: a store write moves an imported checklist row's own updated_at/updated_by with it,
so every row reader (SPA Work page, attention_watch, blocker_watch, work_digest) sees the real age."""
from __future__ import annotations

from src.runtime import work_store as ws


def _mk(store, item_id, extra):
    return store.create({"id": item_id, "kind": "build", "title": "t", "extra": extra}, by="importer-s")["item"]


def test_a_write_moves_the_imported_row_stamp(tmp_path):
    store = ws.WorkStore(tmp_path / "work_store.db")
    it = _mk(store, "ROW-A", {"_source": "checklist", "updated_at": "2026-11-05T00:46:28Z", "updated_by": "old-s"})
    out = store.note("ROW-A", "progress", by="lane-s", expected_version=it["version"])["item"]
    assert out["extra"]["updated_at"] == out["updated_at"] and out["extra"]["updated_by"] == "lane-s"
    assert out["extra"]["updated_at"] > "2026-11-05T00:46:28Z"
    assert out["extra"]["_source"] == "checklist"          # nothing else in extra is touched


def test_a_native_item_without_a_row_stamp_is_left_alone(tmp_path):
    store = ws.WorkStore(tmp_path / "work_store.db")
    it = _mk(store, "ROW-B", {"_source": "native"})
    out = store.note("ROW-B", "progress", by="lane-s", expected_version=it["version"])["item"]
    assert "updated_at" not in (out.get("extra") or {})
