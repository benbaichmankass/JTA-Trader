"""/api/diag/* accepts DIAG_READ_TOKEN in X-Diag-Token as well as Authorization: Bearer.

WSD-S1-PROXY-AUTH-COLLISION (2026-11-05): a cloud environment that holds any network
secret for ict-bot.duckdns.org alters the session's Authorization header. A fresh
ICT-env session got 401 even though its DIAG_READ_TOKEN fingerprint matched the VM's.
"""
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.web.api.routers import diag

ROOT = Path(__file__).resolve().parent.parent


def _req(headers: dict) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/diag/version",
                    "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("DIAG_READ_TOKEN", "diag-secret")


def _status(headers):
    try:
        diag._require_diag_token(_req(headers))
        return 200
    except HTTPException as exc:
        return exc.status_code


def test_header_accepted():
    assert _status({"X-Diag-Token": "diag-secret"}) == 200


def test_bearer_still_accepted():
    assert _status({"Authorization": "Bearer diag-secret"}) == 200


@pytest.mark.parametrize("headers", [
    {"X-Diag-Token": "wrong"},
    {"X-Diag-Token": "   "},
    {"X-Diag-Token": "wrong", "Authorization": "Bearer diag-secret"},  # the header alone decides
    {"Authorization": "Bearer wrong"},
    {},
])
def test_rejected(headers):
    assert _status(headers) == 401


def test_header_beside_a_foreign_authorization_is_accepted():
    """The fix's point: a proxy-altered Authorization no longer matters."""
    assert _status({"X-Diag-Token": "diag-secret", "Authorization": "Bearer something-else"}) == 200


def test_unset_token_is_503_even_with_the_header(monkeypatch):
    monkeypatch.delenv("DIAG_READ_TOKEN", raising=False)
    assert _status({"X-Diag-Token": "anything"}) == 503


def test_diag_fetch_sends_both_headers(tmp_path):
    """Run the shipped script's config-writing lines and read the curl config back."""
    text = (ROOT / "scripts/ops/diag_fetch.sh").read_text()
    lines = [ln for ln in text.splitlines() if re.match(r"^printf 'header = ", ln)]
    assert len(lines) == 2, lines
    import subprocess
    cfg = tmp_path / "cfg"
    script = "\n".join(ln.replace('"$cfg"', '"$CFG"') for ln in lines)
    subprocess.run(["bash", "-c", f": > \"$CFG\"\n{script}"], check=True,
                   env={"PATH": "/usr/bin:/bin", "CFG": str(cfg), "DIAG_READ_TOKEN": "t0k"})
    body = cfg.read_text()
    assert 'header = "Authorization: Bearer t0k"' in body
    assert 'header = "X-Diag-Token: t0k"' in body
