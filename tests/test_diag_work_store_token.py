"""DIAG-DIRECT-READ: the work-store credential opens the read-only diag routes (operator 2026-11-12)."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.web.api.routers import diag


def _req(headers):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw})


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WORK_STORE_TOKEN", "ws-secret")
    monkeypatch.setattr(diag, "_diag_token", lambda: "diag-secret")


def test_work_store_token_opens_diag():
    diag._require_diag_token(_req({"X-Work-Store-Token": "ws-secret"}))


def test_wrong_work_store_token_refused_even_with_good_diag_token():
    with pytest.raises(HTTPException) as e:
        diag._require_diag_token(_req({"X-Work-Store-Token": "nope", "X-Diag-Token": "diag-secret"}))
    assert e.value.status_code == 401


def test_diag_token_still_works():
    diag._require_diag_token(_req({"X-Diag-Token": "diag-secret"}))


def test_no_token_refused():
    with pytest.raises(HTTPException):
        diag._require_diag_token(_req({}))
