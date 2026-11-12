"""GET /api/bot/performance/reviews[/{id}] -- list + fetch-one."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.web.api import main as api_main
from src.web.api.routers import performance_reviews as pr


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "comms" / "reviews").mkdir(parents=True)
    (tmp_path / "docs" / "reviews").mkdir(parents=True)
    monkeypatch.setattr(pr, "repo_root", lambda: str(tmp_path))
    return tmp_path


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


def _json_review(root, stem, reviewed_at, **extra):
    doc = {"reviewed_at": reviewed_at, "window_start": "2026-10-28T19:00:00Z",
           "window_end": reviewed_at, "overall_assessment": "caution", **extra}
    (root / "comms" / "reviews" / f"{stem}.json").write_text(json.dumps(doc))


def _md(root, name, body="# Weekly walkthrough X\n\ntext\n"):
    (root / "docs" / "reviews" / name).write_text(body)


def test_lists_newest_first_across_both_sources(root, client):
    _json_review(root, "performance-review-20261028-190000", "2026-10-28T19:00:00Z")
    _json_review(root, "performance-review-20261104-190000", "2026-11-04T19:00:00Z")
    _md(root, "2026-11-11-weekly-walkthrough.md", "# Weekly walkthrough 2026-11-11\n")
    _md(root, "2026-10-15-weekly-walkthrough-ml.md", "# ML brief\n")
    _md(root, "2026-11-11-health-review.md")          # not a review we list
    body = client.get("/api/bot/performance/reviews").json()
    assert body["read_state"] == "read"
    assert [r["id"] for r in body["reviews"]] == [
        "2026-11-11-weekly-walkthrough",
        "performance-review-20261104-190000",
        "performance-review-20261028-190000",
        "2026-10-15-weekly-walkthrough-ml",
    ]
    first, second = body["reviews"][0], body["reviews"][1]
    assert first["title"] == "Weekly walkthrough 2026-11-11"
    assert first["stamp_basis"] == "filename_date" and first["stamp"] == "2026-11-11T00:00:00Z"
    assert second["stamp_basis"] == "reviewed_at" and second["stamp"] == "2026-11-04T19:00:00Z"
    assert second["path"] == "comms/reviews/performance-review-20261104-190000.json"
    assert second["summary"] == "caution" and second["kind"] == "performance_review"
    assert body["total"] == body["count"] == 4


def test_kind_filter_and_unknown_kind(root, client):
    _json_review(root, "performance-review-20261104-190000", "2026-11-04T19:00:00Z")
    _md(root, "2026-11-11-weekly-walkthrough.md")
    body = client.get("/api/bot/performance/reviews?kind=performance_review").json()
    assert [r["kind"] for r in body["reviews"]] == ["performance_review"]
    assert client.get("/api/bot/performance/reviews?kind=nope").status_code == 400


def test_empty_but_readable_is_read_not_could_not_look(root, client):
    body = client.get("/api/bot/performance/reviews").json()
    assert body["read_state"] == "read" and body["reviews"] == [] and body["total"] == 0


def test_missing_source_is_partial_and_both_missing_is_could_not_look(root, client):
    (root / "docs" / "reviews").rmdir()
    _json_review(root, "performance-review-20261104-190000", "2026-11-04T19:00:00Z")
    body = client.get("/api/bot/performance/reviews").json()
    assert body["read_state"] == "partial"
    assert {s["source"]: s["read_state"] for s in body["sources"]} == {
        "comms/reviews": "read", "docs/reviews": "absent"}
    import shutil
    shutil.rmtree(root / "comms")
    body = client.get("/api/bot/performance/reviews").json()
    assert body["read_state"] == "could_not_look" and body["reviews"] == []


def test_fetch_one_json_and_markdown(root, client):
    _json_review(root, "performance-review-20261104-190000", "2026-11-04T19:00:00Z", calls=[1])
    _md(root, "2026-11-11-weekly-walkthrough.md", "# T\nbody\n")
    j = client.get("/api/bot/performance/reviews/performance-review-20261104-190000").json()
    assert j["content_json"]["calls"] == [1] and j["content_text"] is None
    m = client.get("/api/bot/performance/reviews/2026-11-11-weekly-walkthrough").json()
    assert m["content_text"] == "# T\nbody\n" and m["content_json"] is None
    assert m["review"]["format"] == "markdown"


def test_fetch_unknown_is_404_and_traversal_cannot_escape(root, client):
    (root / "secret.md").write_text("nope")
    assert client.get("/api/bot/performance/reviews/nope").status_code == 404
    assert client.get("/api/bot/performance/reviews/..%2F..%2Fsecret").status_code == 404
    assert client.get("/api/bot/performance/reviews/secret").status_code == 404


def test_cors_header_like_other_bot_gets(root, client):
    r = client.get("/api/bot/performance/reviews",
                   headers={"Origin": "https://dashboard.example"})
    assert r.status_code == 200
