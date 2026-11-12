"""SITE-AUTH step (i): POST-only carve-outs for service-token write routes.

With SITE_AUTH_ENFORCE on, the gate passes the DASHBOARD_API_TOKEN service
bearer on GET/HEAD only. These POST routes check their own token inside the
router and fail closed, so the gate lets them through to that check. Pinned:
  * with the right token, each POST reaches its router (not a gate 401);
  * with no token, each POST is still refused (by the router, 401/503);
  * the GET reads on the same paths stay behind the gate;
  * every carved-out route really fails closed when its token is unset.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "svc-token"

POSTS = [
    "/api/bot/alerts",
    "/api/bot/devices/register",
    "/api/bot/wake-toggles",
    "/api/bot/work/decision",
    "/api/bot/work/items",
    "/api/bot/work/items/SOME-ID/note",
    "/api/bot/live-review/rows",
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SITE_AUTH_ENFORCE", "1")
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    monkeypatch.setenv("WORK_STORE_TOKEN", TOKEN)
    from src.web.api import main
    return TestClient(main.app, raise_server_exceptions=False)


def _gate_401(resp) -> bool:
    """The site gate's own refusal, as opposed to a router's."""
    from src.web.api import auth
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    return resp.status_code == 401 and body.get("detail") == auth._UNAUTH.detail


@pytest.mark.parametrize("path", POSTS)
def test_post_with_service_token_reaches_the_router(client, path):
    r = client.post(path, json={}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert not _gate_401(r), (path, r.status_code, r.text)


@pytest.mark.parametrize("path", POSTS)
def test_post_without_token_is_still_refused(client, path):
    r = client.post(path, json={})
    assert r.status_code in (401, 403, 503), (path, r.status_code)


@pytest.mark.parametrize("path", ["/api/bot/alerts", "/api/bot/wake-toggles", "/api/bot/work/decisions"])
def test_gets_on_the_same_paths_stay_gated(client, path):
    r = client.get(path)
    assert _gate_401(r), (path, r.status_code)


def test_carveout_is_post_only(client):
    from src.web.api import auth
    assert not auth._is_site_public("/api/bot/alerts")
    assert auth._is_site_public_post("/api/bot/alerts")
    assert not auth._is_site_public_post("/api/bot/alertsX")
    assert not auth._is_site_public_post("/api/bot/work/itemsX")


@pytest.mark.parametrize("path", POSTS)
def test_every_carved_route_fails_closed_when_its_token_is_unset(client, monkeypatch, path):
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    monkeypatch.delenv("WORK_STORE_TOKEN", raising=False)
    r = client.post(path, json={}, headers={"Authorization": "Bearer anything"})
    assert r.status_code in (401, 503), (path, r.status_code)
