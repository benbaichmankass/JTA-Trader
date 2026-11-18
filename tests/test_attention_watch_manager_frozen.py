"""probe_manager after the WSD-S4 freeze dates the register by its newest row updated_at, not a git commit.

2026-11-18 (HEALTH-REVIEW-20261118): the 'manager' alarm read "checklist last written 71h ago" while the work
store held rows written that day -- the checklist files are never committed after the freeze."""
from datetime import datetime, timezone

from scripts.ops import attention_watch as aw
from src.runtime import checklist_store as ck

NOW = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)


def _rows(monkeypatch, rows, frozen=True):
    monkeypatch.setattr(ck, "load_path", lambda p: {"items": rows})
    monkeypatch.setattr(aw, "_checklist_frozen", lambda: frozen)
    monkeypatch.setattr(aw, "_last_commit_time",
                        lambda *a: (_ for _ in ()).throw(AssertionError("frozen path reads no git")))


def test_frozen_fresh_row_is_ok(monkeypatch):
    _rows(monkeypatch, [{"id": "A", "updated_at": "2026-11-15T00:00:00Z"},
                        {"id": "B", "updated_at": "2026-11-18T15:19:21Z"}])
    out = aw.probe_manager(NOW)
    assert out["status"] == aw.OK and "checklist last written 3h ago" in out["detail"]
    assert "checklist frozen" in out["detail"]


def test_frozen_silent_register_breaches(monkeypatch):
    _rows(monkeypatch, [{"id": "A", "updated_at": "2026-11-15T00:00:00Z"}])
    assert aw.probe_manager(NOW)["status"] == aw.BREACHED


def test_frozen_no_readable_timestamp_is_unknown_not_ok(monkeypatch):
    _rows(monkeypatch, [{"id": "A", "updated_at": None}])
    out = aw.probe_manager(NOW)
    assert out["status"] == aw.UNKNOWN and "could not look" in out["detail"]
