"""Console connector sign-in (G1): DCR -> authorize (Google ID token) -> PKCE code -> token -> /mcp."""
from __future__ import annotations

import json
import re
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from src.console_connector import oauth, server

BASE = "https://console.example.test"
CID = "google-client-id.apps.googleusercontent.com"
EMAIL = "operator@example.test"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def _verifier(claims):
    def v(token, audience):
        if token != "good-google-token":
            raise ValueError("bad signature")
        return claims
    return v


@pytest.fixture
def make(tmp_path):
    def _make(claims=None):
        claims = claims or {"aud": CID, "email": EMAIL, "email_verified": True}
        srv = oauth.OAuthServer(base_url=BASE, google_client_id=CID, allowed_email=EMAIL,
                                state_path=tmp_path / "state.json", verifier=_verifier(claims))
        return srv, TestClient(server.create_app(auth=srv))
    return _make


def _register(c):
    r = c.post("/register", json={"client_name": "claude", "redirect_uris": [REDIRECT]})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _authorize(c, client_id, verifier="v" * 50, state="st-1"):
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
         "code_challenge": oauth.pkce_s256(verifier), "code_challenge_method": "S256", "state": state}
    page = c.get("/authorize", params=q)
    assert page.status_code == 200, page.text
    assert CID in page.text and "accounts.google.com/gsi/client" in page.text
    return re.search(r'rid: "([^"]+)"', page.text).group(1)


def _code(c, rid, token="good-google-token"):
    return c.post("/authorize/google", json={"rid": rid, "id_token": token})


def _full_login(c, verifier="v" * 50):
    client_id = _register(c)
    rid = _authorize(c, client_id, verifier)
    r = _code(c, rid)
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["redirect"]).query)
    assert q["state"] == ["st-1"]
    tok = c.post("/token", data={"grant_type": "authorization_code", "code": q["code"][0], "client_id": client_id,
                                 "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    return client_id, tok.json()


def _mcp(c, token=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return c.post("/mcp", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                           "params": {"name": "hello", "arguments": {}}})


def test_discovery_metadata(make):
    _, c = make()
    prm = c.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == BASE + "/mcp" and prm["authorization_servers"] == [BASE]
    asm = c.get("/.well-known/oauth-authorization-server").json()
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert asm["registration_endpoint"] == BASE + "/register"


def test_mcp_without_token_is_401_with_resource_metadata_challenge(make):
    _, c = make()
    r = _mcp(c)
    assert r.status_code == 401
    assert 'resource_metadata="' + BASE + '/.well-known/oauth-protected-resource"' in r.headers["www-authenticate"]
    assert _mcp(c, "made-up").status_code == 401


def test_full_flow_then_mcp_and_refresh_rotation(make, tmp_path):
    _, c = make()
    client_id, tok = _full_login(c)
    assert tok["token_type"] == "Bearer" and tok["expires_in"] == oauth.ACCESS_TTL_S
    r = _mcp(c, tok["access_token"])
    assert r.status_code == 200 and r.json()["result"]["structuredContent"]["hello"]
    # the state file never holds a usable token
    raw = (tmp_path / "state.json").read_text()
    assert tok["access_token"] not in raw and tok["refresh_token"] not in raw
    # refresh rotates: the new token works, the old refresh token is spent
    new = c.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": client_id})
    assert new.status_code == 200
    assert _mcp(c, new.json()["access_token"]).status_code == 200
    again = c.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": client_id})
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


def test_code_is_single_use_and_pkce_is_enforced(make):
    _, c = make()
    client_id = _register(c)
    rid = _authorize(c, client_id, "right" * 10)
    code = parse_qs(urlparse(_code(c, rid).json()["redirect"]).query)["code"][0]
    bad = c.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id,
                                 "code_verifier": "wrong" * 10})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    # the failed attempt consumed the code: the right verifier cannot reuse it
    reuse = c.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id,
                                   "code_verifier": "right" * 10})
    assert reuse.status_code == 400


def test_wrong_email_unverified_and_bad_signature_are_refused(make):
    for claims, status in (({"aud": CID, "email": "someone@else.test", "email_verified": True}, 403),
                           ({"aud": CID, "email": EMAIL, "email_verified": False}, 403),
                           ({"aud": "other-client", "email": EMAIL, "email_verified": True}, 401)):
        _, c = make(claims)
        rid = _authorize(c, _register(c))
        r = _code(c, rid)
        assert r.status_code == status, (claims, r.text)
        assert "redirect" not in r.json()
    _, c = make()
    assert _code(c, _authorize(c, _register(c)), token="forged").status_code == 401


def test_pending_request_is_single_use(make):
    _, c = make()
    rid = _authorize(c, _register(c))
    assert _code(c, rid).status_code == 200
    assert _code(c, rid).status_code == 400


def test_registration_refuses_foreign_redirect_hosts(make):
    _, c = make()
    for uri in ("https://evil.example/cb", "http://claude.ai/api/mcp/auth_callback", "https://claude.ai.evil.example/cb"):
        r = c.post("/register", json={"redirect_uris": [uri]})
        assert r.status_code == 400, uri
    assert c.post("/register", json={"redirect_uris": ["https://claude.com/api/mcp/auth_callback"]}).status_code == 201


def test_authorize_refuses_unregistered_redirect_and_missing_pkce(make):
    _, c = make()
    client_id = _register(c)
    base = {"response_type": "code", "client_id": client_id, "code_challenge": "x", "code_challenge_method": "S256"}
    assert c.get("/authorize", params={**base, "redirect_uri": "https://claude.ai/other"}).status_code == 400
    assert c.get("/authorize", params={**base, "redirect_uri": REDIRECT, "code_challenge_method": "plain"}).status_code == 400
    assert c.get("/authorize", params={**base, "client_id": "nope", "redirect_uri": REDIRECT}).status_code == 400


def test_tokens_survive_restart(make, tmp_path):
    _srv, c = make()
    _, tok = _full_login(c)
    srv2 = oauth.OAuthServer(base_url=BASE, google_client_id=CID, allowed_email=EMAIL,
                             state_path=tmp_path / "state.json", verifier=_verifier({}))
    assert _mcp(TestClient(server.create_app(auth=srv2)), tok["access_token"]).status_code == 200


def test_expired_access_token_is_refused(make, tmp_path):
    t = [1000.0]
    srv = oauth.OAuthServer(base_url=BASE, google_client_id=CID, allowed_email=EMAIL,
                            state_path=tmp_path / "s.json", clock=lambda: t[0],
                            verifier=_verifier({"aud": CID, "email": EMAIL, "email_verified": True}))
    c = TestClient(server.create_app(auth=srv))
    _, tok = _full_login(c)
    t[0] += oauth.ACCESS_TTL_S + 1
    assert _mcp(c, tok["access_token"]).status_code == 401


def test_auth_on_but_unconfigured_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_CONNECTOR_AUTH", "google")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ALLOWED_EMAIL", raising=False)
    monkeypatch.setenv("CONSOLE_CONNECTOR_STATE", str(tmp_path / "s.json"))
    c = TestClient(server.create_app())
    r = _mcp(c, secrets.token_urlsafe(8))
    assert r.status_code == 503 and json.loads(r.text)["error"] == "server_misconfigured"


def test_auth_off_by_default_keeps_tunnel_deploy_working(monkeypatch):
    monkeypatch.delenv("CONSOLE_CONNECTOR_AUTH", raising=False)
    assert _mcp(TestClient(server.create_app())).status_code == 200
