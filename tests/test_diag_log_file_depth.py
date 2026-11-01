"""DIAG-LOG-DEPTH: /log_file filters before the cap and never truncates silently."""
from __future__ import annotations

import pytest

from src.web.api.routers import diag


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    f = tmp_path / "x.log"
    f.write_text("".join(f"2026-11-01T{h:02d}:00:00 row{h} {'ERR' if h % 5 == 0 else 'ok'}\n"
                         for h in range(24)) * 100)
    monkeypatch.setitem(diag._LOG_FILES, "heartbeat", f)
    monkeypatch.setenv("DIAG_READ_TOKEN", "t")
    app = FastAPI()
    app.include_router(diag.router)
    c = TestClient(app, headers={"Authorization": "Bearer t"})
    return c


def _get(c, q):
    r = c.get(f"/api/diag/log_file?name=heartbeat&{q}")
    assert r.status_code == 200, r.text
    return r.json()


def test_cap_is_reported(client):
    j = _get(client, "lines=10")
    assert j["lines_scanned"] == 2400 and j["lines_returned"] == 10
    assert j["lines_dropped"] == 2390 and j["truncated"] is True
    assert j["limit_state"] == "as_requested" and j["read_state"] == "complete"


def test_clamp_is_reported(client):
    j = _get(client, "lines=5000")
    assert j["limit_state"] == "clamped_to_max" and j["lines_returned"] == 1000
    assert j["truncated"] is True and j["lines_dropped"] == 1400


def test_grep_before_cap_reaches_past_the_tail(client):
    j = _get(client, "lines=1000&grep=T03:00")
    assert j["lines_matched"] == 100 and j["truncated"] is False
    assert all("T03:00" in ln for ln in j["lines"])


def test_no_truncation_when_fits(client):
    j = _get(client, "lines=1000&grep=ERR")
    assert j["lines_matched"] == 500 and j["truncated"] is False and j["lines_dropped"] == 0


def test_bad_grep_400(client):
    assert client.get("/api/diag/log_file?name=heartbeat&grep=a%3Bb").status_code == 400
