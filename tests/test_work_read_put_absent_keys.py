"""work_read._put leaves a key the item does not carry out of the patch (never sends it as null), and still clears a
key the item carries as None. Regression for 2026-11-12: a checklist.py note round-trip nulled `summary`."""

from src.runtime import work_read


class _FakeStore:
    def __init__(self, prior):
        self.prior = prior
        self.sets = []

    def get(self, item_id):
        return dict(self.prior)

    def set(self, item_id, diff, by=None, expected_version=None):
        self.sets.append(diff)
        return {"item": {**self.prior, **diff}}


def _run(monkeypatch, prior, item):
    store = _FakeStore(prior)
    monkeypatch.setattr(work_read, "local_store", lambda: store)
    work_read._put(item, "test")
    return store.sets


def test_absent_summary_is_not_nulled(monkeypatch):
    prior = {"id": "R", "kind": "build", "version": 3, "title": "t", "summary": "keep me", "extra": {"note": "a"}}
    item = {"id": "R", "kind": "build", "title": "t", "extra": {"note": "a b"}}  # from_row output: no summary key
    sets = _run(monkeypatch, prior, item)
    assert sets == [{"extra": {"note": "a b"}}], sets


def test_present_none_still_clears(monkeypatch):
    prior = {"id": "R", "kind": "build", "version": 3, "title": "t", "lane": "s1"}
    item = {"id": "R", "kind": "build", "title": "t", "lane": None}
    sets = _run(monkeypatch, prior, item)
    assert sets == [{"lane": None}], sets
