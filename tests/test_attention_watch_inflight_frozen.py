"""probe_inflight after the WSD-S4 freeze dates a row by its updated_at, not its frozen export file's last commit.

2026-11-13's daily brief named ML-SHADOW-NEVER-ORDERS "15d untouched" while the work store showed a write on
2026-11-12: the per-row file is never committed after the freeze, so git log dated every row to the freeze."""
from datetime import datetime, timezone

from scripts.ops import attention_watch as aw
from src.runtime import checklist_store as ck

NOW = datetime(2026, 11, 13, 6, 40, tzinfo=timezone.utc)


def _rows(monkeypatch, rows, frozen=True):
    monkeypatch.setattr(ck, "load_path", lambda p: {"items": rows})
    monkeypatch.setattr(ck, "seeded", lambda p: True)
    monkeypatch.setattr(aw, "_checklist_frozen", lambda: frozen)
    monkeypatch.setattr(aw, "_git", lambda *a: (_ for _ in ()).throw(AssertionError("frozen path reads no git")))


def test_frozen_uses_updated_at(monkeypatch):
    _rows(monkeypatch, [
        {"id": "FRESH", "state": "in_flight", "updated_at": "2026-11-12T14:49:58Z"},
        {"id": "OLD", "state": "in_flight", "updated_at": "2026-11-01T00:00:00Z", "lane": "x"},
        {"id": "DONE", "state": "done", "updated_at": "2026-10-01T00:00:00Z"},
    ])
    out = aw.probe_inflight(NOW, shallow=False)
    assert out["status"] == aw.BREACHED
    assert [r["id"] for r in out["rows"]] == ["OLD"]
    assert "1 of 2" in out["detail"] and "checklist frozen" in out["detail"]


def test_frozen_all_fresh_is_ok_even_on_shallow_clone(monkeypatch):
    _rows(monkeypatch, [{"id": "A", "state": "in_flight", "updated_at": "2026-11-13T01:00:00Z"}])
    out = aw.probe_inflight(NOW, shallow=True)
    assert out["status"] == aw.OK and out["rows"] == []


def test_frozen_unreadable_timestamp_is_counted_not_stale(monkeypatch):
    _rows(monkeypatch, [{"id": "A", "state": "in_flight", "updated_at": None}])
    out = aw.probe_inflight(NOW, shallow=False)
    assert out["status"] == aw.OK and "1 with no readable updated_at" in out["detail"]
