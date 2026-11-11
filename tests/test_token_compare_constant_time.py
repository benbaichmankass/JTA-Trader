"""SEC hardening (c), 2026-11-11: service-token checks compare in constant time.

prop._require_write_token (which also guards POST /api/bot/alerts and
/api/bot/wake-toggles) and devices._check_admin_token compared with ``!=``.
They now use ``hmac.compare_digest`` on bytes. Bytes, not str: with str,
a non-ASCII byte in a header raises TypeError, so a junk header got a 500
instead of a 401. These tests pin both properties.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "s3cr3t-token"


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    monkeypatch.setenv("WORK_STORE_TOKEN", TOKEN)


def _helpers():
    from src.web.api.routers import devices, prop, work, work_items
    return [
        prop._require_write_token,
        devices._check_admin_token,
        work._require_decision_write_token,
        lambda a: work_items._require_work_store_token(a),
    ]


@pytest.mark.parametrize("idx", range(4))
def test_right_token_passes(idx):
    _helpers()[idx](f"Bearer {TOKEN}")


@pytest.mark.parametrize("idx", range(4))
@pytest.mark.parametrize("bad", ["Bearer nope", f"Bearer {TOKEN}x", "Bearer \xe9\xe9"])
def test_wrong_or_non_ascii_token_is_401(idx, bad):
    with pytest.raises(HTTPException) as ei:
        _helpers()[idx](bad)
    assert ei.value.status_code == 401


def test_service_token_ok_non_ascii_is_false():
    from src.web.api import auth
    assert auth._service_token_ok(TOKEN) is True
    assert auth._service_token_ok("\xe9") is False


def test_no_plain_equality_against_a_secret_in_web_auth():
    """No ``x != expected`` / ``x == expected`` in the web routers or auth."""
    files = [ROOT / "src/web/api/auth.py", *sorted((ROOT / "src/web/api/routers").glob("*.py"))]
    hits = []
    for f in files:
        tree = ast.parse(f.read_text(), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and any(isinstance(o, (ast.Eq, ast.NotEq)) for o in node.ops):
                names = [n.id for n in [node.left, *node.comparators] if isinstance(n, ast.Name)]
                if "expected" in names:
                    hits.append(f"{f.relative_to(ROOT)}:{node.lineno}")
    assert not hits, hits
