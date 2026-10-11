"""UI-UPGRADE-1-AUTH — Google ID token + passkey sign-in, device sessions, site gate.

The Google verifier and the WebAuthn verifier run FOR REAL here: the tests mint
ID tokens with a local RSA key (only the cert FETCH is patched) and drive the
passkey endpoints with a software authenticator, so a forged / expired /
wrong-audience token, a replayed assertion and a counter regression are each
rejected by the actual library, not by a mock.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time

import cbor2
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.web.api import auth as auth_module
from src.web.api import main as api_main
from src.web.api import web_sessions as ws

EMAIL = "ben.baichmankass@gmail.com"
CLIENT_ID = "1234-test.apps.googleusercontent.com"
ORIGIN = "https://benbaichmankass.github.io"
RP_ID = "benbaichmankass.github.io"
KID = "test-kid"


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "tj.db"))
    monkeypatch.setenv("ALLOWED_EMAIL", EMAIL)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("WEB_SESSION_PEPPER", "p" * 32)
    monkeypatch.setenv("JWT_SIGNING_KEY", "k" * 64)
    monkeypatch.delenv("SITE_AUTH_ENFORCE", raising=False)
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    ws.reset_memory_for_tests()
    yield


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


@pytest.fixture
def google(monkeypatch):
    """A local Google: RSA key + patched cert fetch. Returns a token minter."""
    from google.oauth2 import id_token as g

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    monkeypatch.setattr(g, "_fetch_certs", lambda request, url: {KID: pub})

    def mint(*, signer=None, aud=CLIENT_ID, email=EMAIL, verified=True,
             iss="https://accounts.google.com", exp_delta=3600, iat_delta=0):
        now = int(time.time())
        claims = {"iss": iss, "aud": aud, "sub": "1", "email": email,
                  "email_verified": verified, "iat": now + iat_delta, "exp": now + exp_delta}
        return pyjwt.encode(claims, signer or key, algorithm="RS256", headers={"kid": KID})

    return mint


class SoftKey:
    """A software WebAuthn authenticator (ES256, 'none' attestation)."""

    def __init__(self):
        self.priv = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.count = 0

    def _cose(self) -> bytes:
        n = self.priv.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1,
                            -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def register(self, options: dict) -> dict:
        cd = json.dumps({"type": "webauthn.create", "challenge": options["challenge"],
                         "origin": ORIGIN, "crossOrigin": False}).encode()
        auth = (hashlib.sha256(RP_ID.encode()).digest() + bytes([0x45])
                + self.count.to_bytes(4, "big") + b"\0" * 16
                + len(self.cred_id).to_bytes(2, "big") + self.cred_id + self._cose())
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cd), "attestationObject": b64(att)}}

    def assertion(self, options: dict, *, count=None, origin=ORIGIN) -> dict:
        self.count = (self.count + 1) if count is None else count
        cd = json.dumps({"type": "webauthn.get", "challenge": options["challenge"],
                         "origin": origin, "crossOrigin": False}).encode()
        auth = (hashlib.sha256(RP_ID.encode()).digest() + bytes([0x05])
                + self.count.to_bytes(4, "big"))
        sig = self.priv.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cd), "authenticatorData": b64(auth),
                             "signature": b64(sig)}}


def signin(client, google) -> str:
    r = client.post("/api/auth/google", json={"id_token": google()})
    assert r.status_code == 200, r.text
    return r.json()["preauth_ticket"]


def enrol(client, google, key: SoftKey, label="Laptop") -> dict:
    """Full first-device enrolment; returns the register/finish body (has a session)."""
    pre = signin(client, google)
    code = ws.issue_enrol_code()
    b = client.post("/api/auth/passkey/register/begin",
                    json={"preauth_ticket": pre, "enrol_code": code, "label": label})
    assert b.status_code == 200, b.text
    f = client.post("/api/auth/passkey/register/finish",
                    json={"challenge_id": b.json()["challenge_id"],
                          "credential": key.register(b.json()["options"])})
    assert f.status_code == 200, f.text
    return f.json()


def login(client, google, key: SoftKey, label="Phone", **kw):
    pre = signin(client, google)
    b = client.post("/api/auth/passkey/assert/begin", json={"preauth_ticket": pre})
    assert b.status_code == 200, b.text
    cred = key.assertion(b.json()["options"], **kw)
    r = client.post("/api/auth/passkey/assert/finish",
                    json={"preauth_ticket": pre, "challenge_id": b.json()["challenge_id"],
                          "credential": cred, "device_label": label})
    return r, cred, b.json()


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# POST /api/auth/google
# ---------------------------------------------------------------------------


def test_google_valid_token_yields_preauth_ticket_not_a_session(client, google):
    r = client.post("/api/auth/google", json={"id_token": google()})
    assert r.status_code == 200
    body = r.json()
    assert body["preauth_ticket"] and body["expires_in"] == 300
    assert "session_token" not in body
    assert body["passkey_enrolled"] is False


def test_google_forged_signature_rejected(client, google):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    r = client.post("/api/auth/google", json={"id_token": google(signer=other)})
    assert r.status_code == 401 and r.json()["detail"]["error"] == "invalid_google_token"


def test_google_expired_token_rejected(client, google):
    r = client.post("/api/auth/google", json={"id_token": google(exp_delta=-3600)})
    assert r.status_code == 401


def test_google_token_issued_5s_in_the_future_is_accepted(client, google):
    """A VM clock a few seconds behind Google's must not reject a fresh token."""
    r = client.post("/api/auth/google", json={"id_token": google(iat_delta=5)})
    assert r.status_code == 200, r.text


def test_google_token_issued_far_in_the_future_still_rejected(client, google):
    r = client.post("/api/auth/google", json={"id_token": google(iat_delta=120)})
    assert r.status_code == 401


def test_google_wrong_audience_rejected(client, google):
    r = client.post("/api/auth/google", json={"id_token": google(aud="someone-elses-client")})
    assert r.status_code == 401


def test_google_wrong_issuer_rejected(client, google):
    r = client.post("/api/auth/google", json={"id_token": google(iss="https://evil.example")})
    assert r.status_code == 401


def test_google_wrong_email_rejected(client, google):
    r = client.post("/api/auth/google", json={"id_token": google(email="other@example.com")})
    assert r.status_code == 403 and r.json()["detail"]["error"] == "email_not_allowlisted"


def test_google_unverified_email_rejected(client, google):
    r = client.post("/api/auth/google", json={"id_token": google(verified=False)})
    assert r.status_code == 403 and r.json()["detail"]["error"] == "email_not_verified"


def test_google_garbage_token_rejected(client, google):
    assert client.post("/api/auth/google", json={"id_token": "not.a.jwt"}).status_code == 401


def test_google_unconfigured_is_503_and_names_nothing(client, google, monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID")
    r = client.post("/api/auth/google", json={"id_token": google()})
    assert r.status_code == 503 and r.json()["detail"] == {"error": "auth_unavailable"}
    assert "GOOGLE" not in r.text


def test_google_failures_are_rate_limited(client, google):
    for _ in range(ws.FAIL_LIMIT):
        client.post("/api/auth/google", json={"id_token": "x.y.z"})
    r = client.post("/api/auth/google", json={"id_token": google()})
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# Passkey registration + assertion + sessions
# ---------------------------------------------------------------------------


def test_register_requires_preauth_ticket_and_enrol_code(client, google):
    key = SoftKey()
    pre = signin(client, google)
    no_ticket = client.post("/api/auth/passkey/register/begin", json={"enrol_code": "x"})
    assert no_ticket.status_code == 401
    no_code = client.post("/api/auth/passkey/register/begin", json={"preauth_ticket": pre})
    assert no_code.status_code == 403 and no_code.json()["detail"]["error"] == "invalid_enrol_code"
    bad = client.post("/api/auth/passkey/register/begin",
                      json={"preauth_ticket": pre, "enrol_code": "dead-beef-0000"})
    assert bad.status_code == 403
    assert ws.list_passkeys() == [] and key  # nothing enrolled


def test_enrol_code_is_single_use_and_hashed_at_rest(client, google):
    pre = signin(client, google)
    code = ws.issue_enrol_code()
    import sqlite3
    from src.utils.paths import trade_journal_db_path
    raw = sqlite3.connect(trade_journal_db_path()).execute("SELECT id FROM web_sessions").fetchall()
    assert all(code not in r[0] for r in raw)
    assert client.post("/api/auth/passkey/register/begin",
                       json={"preauth_ticket": pre, "enrol_code": code}).status_code == 200
    again = client.post("/api/auth/passkey/register/begin",
                        json={"preauth_ticket": pre, "enrol_code": code})
    assert again.status_code == 403


def test_expired_enrol_code_rejected():
    code = ws.issue_enrol_code(ttl=-1)
    assert ws.consume_enrol_code(code) is False


def test_first_device_enrol_then_sign_in_with_assertion(client, google):
    key = SoftKey()
    first = enrol(client, google, key)
    assert first["session_token"].startswith("ws_")
    assert first["expires_in"] == 30 * 24 * 3600
    r, _, _ = login(client, google, key)
    assert r.status_code == 200, r.text
    assert r.json()["session_token"].startswith("ws_")
    assert r.json()["session_token"] != first["session_token"]


def test_session_token_stored_hashed_and_256_bit(client, google):
    key = SoftKey()
    tok = enrol(client, google, key)["session_token"]
    import sqlite3
    from src.utils.paths import trade_journal_db_path
    rows = sqlite3.connect(trade_journal_db_path()).execute(
        "SELECT id FROM web_sessions WHERE kind='session'").fetchall()
    assert len(rows) == 1 and tok not in rows[0][0] and rows[0][0] == ws.hash_secret(tok)
    assert len(unb64(tok[len("ws_"):])) == 32


def test_assertion_without_enrolled_passkey_is_409(client, google):
    pre = signin(client, google)
    r = client.post("/api/auth/passkey/assert/begin", json={"preauth_ticket": pre})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "no_passkey_enrolled"


def test_replayed_assertion_rejected(client, google):
    key = SoftKey()
    enrol(client, google, key)
    r, cred, b = login(client, google, key)
    assert r.status_code == 200
    pre = signin(client, google)
    replay = client.post("/api/auth/passkey/assert/finish",
                         json={"preauth_ticket": pre, "challenge_id": b["challenge_id"],
                               "credential": cred})
    assert replay.status_code == 400 and replay.json()["detail"]["error"] == "invalid_challenge"


def test_assertion_for_a_stale_challenge_rejected(client, google):
    """A captured assertion cannot be re-bound to a fresh challenge."""
    key = SoftKey()
    enrol(client, google, key)
    r, cred, _ = login(client, google, key)
    assert r.status_code == 200
    pre = signin(client, google)
    b2 = client.post("/api/auth/passkey/assert/begin", json={"preauth_ticket": pre}).json()
    replay = client.post("/api/auth/passkey/assert/finish",
                         json={"preauth_ticket": pre, "challenge_id": b2["challenge_id"],
                               "credential": cred})
    assert replay.status_code == 401


def test_sign_counter_regression_rejected(client, google):
    key = SoftKey()
    enrol(client, google, key)
    assert login(client, google, key, count=5)[0].status_code == 200
    r, _, _ = login(client, google, key, count=3)           # cloned authenticator
    assert r.status_code == 401 and r.json()["detail"]["error"] == "assertion_failed"
    r, _, _ = login(client, google, key, count=5)           # equal is a regression too
    assert r.status_code == 401
    assert login(client, google, key, count=6)[0].status_code == 200
    assert ws.get_passkey(b64(key.cred_id))["sign_count"] == 6


def test_wrong_origin_assertion_rejected(client, google):
    key = SoftKey()
    enrol(client, google, key)
    r, _, _ = login(client, google, key, origin="https://evil.example")
    assert r.status_code == 401


def test_assertion_signed_by_another_key_rejected(client, google):
    key, imposter = SoftKey(), SoftKey()
    enrol(client, google, key)
    imposter.cred_id = key.cred_id                           # claims the real credential id
    r, _, _ = login(client, google, imposter)
    assert r.status_code == 401


def test_add_second_device_from_a_signed_in_device_needs_no_code(client, google):
    first = SoftKey()
    tok = enrol(client, google, first)["session_token"]
    second = SoftKey()
    b = client.post("/api/auth/passkey/register/begin", json={"label": "Tablet"}, headers=bearer(tok))
    assert b.status_code == 200
    f = client.post("/api/auth/passkey/register/finish", headers=bearer(tok),
                    json={"challenge_id": b.json()["challenge_id"],
                          "credential": second.register(b.json()["options"])})
    assert f.status_code == 200 and "session_token" not in f.json()
    assert len(ws.list_passkeys()) == 2


# ---------------------------------------------------------------------------
# Device sessions: list / revoke / sliding / ws-ticket
# ---------------------------------------------------------------------------


def test_sessions_require_a_signed_in_device_even_with_gate_off(client):
    assert client.get("/api/auth/sessions").status_code == 401
    assert client.get("/api/auth/sessions", headers=bearer("ws_nope")).status_code == 401
    assert client.post("/api/auth/ws-ticket").status_code == 401


def test_list_and_revoke_sessions(client, google):
    key = SoftKey()
    a = enrol(client, google, key)
    b = login(client, google, key)[0].json()
    listing = client.get("/api/auth/sessions", headers=bearer(a["session_token"])).json()["sessions"]
    assert {s["handle"] for s in listing} == {a["session_handle"], b["session_handle"]}
    assert [s for s in listing if s["current"]][0]["handle"] == a["session_handle"]
    assert not any("token" in s or "id" in s for s in listing)       # no secret material

    d = client.delete(f"/api/auth/sessions/{b['session_handle']}", headers=bearer(a["session_token"]))
    assert d.status_code == 200
    assert client.get("/api/auth/sessions", headers=bearer(b["session_token"])).status_code == 401
    assert client.get("/api/auth/sessions", headers=bearer(a["session_token"])).status_code == 200
    assert client.delete("/api/auth/sessions/nonexistent", headers=bearer(a["session_token"])).status_code == 404


def test_revoke_via_post_twin_and_sign_out_everywhere(client, google):
    key = SoftKey()
    a = enrol(client, google, key)
    others = [login(client, google, key)[0].json() for _ in range(2)]
    r = client.post(f"/api/auth/sessions/{others[0]['session_handle']}/revoke",
                    headers=bearer(a["session_token"]))
    assert r.status_code == 200
    r = client.post("/api/auth/sessions/revoke-others", headers=bearer(a["session_token"]))
    assert r.json() == {"revoked": 1}
    assert client.get("/api/auth/me", headers=bearer(a["session_token"])).status_code == 200
    assert client.get("/api/auth/me", headers=bearer(others[1]["session_token"])).status_code == 401


def test_revoked_session_rejected_by_gate_and_by_existing_session_dependency(client, google, monkeypatch):
    key = SoftKey()
    a = enrol(client, google, key)
    b = login(client, google, key)[0].json()
    client.delete(f"/api/auth/sessions/{b['session_handle']}", headers=bearer(a["session_token"]))
    monkeypatch.setenv("SITE_AUTH_ENFORCE", "1")
    assert client.get("/api/bot/strategies", headers=bearer(b["session_token"])).status_code == 401


def test_expired_session_rejected_and_sliding_extends(client, google):
    import sqlite3
    from src.utils.paths import trade_journal_db_path
    key = SoftKey()
    tok = enrol(client, google, key)["session_token"]
    db = sqlite3.connect(trade_journal_db_path())
    sid = ws.hash_secret(tok)
    # last seen long ago, 1 day left -> a request slides it back out to ~30 days
    db.execute("UPDATE web_sessions SET last_seen_at=?, expires_at=? WHERE id=?",
               (int(time.time()) - 3600, int(time.time()) + 86400, sid))
    db.commit()
    assert client.get("/api/auth/me", headers=bearer(tok)).status_code == 200
    exp = db.execute("SELECT expires_at FROM web_sessions WHERE id=?", (sid,)).fetchone()[0]
    assert exp - time.time() > 29 * 86400
    db.execute("UPDATE web_sessions SET expires_at=? WHERE id=?", (int(time.time()) - 1, sid))
    db.commit()
    assert client.get("/api/auth/me", headers=bearer(tok)).status_code == 401


def test_session_dies_when_email_is_de_allowlisted(client, google, monkeypatch):
    tok = enrol(client, google, SoftKey())["session_token"]
    monkeypatch.setenv("ALLOWED_EMAIL", "someone.else@example.com")
    assert client.get("/api/auth/me", headers=bearer(tok)).status_code == 401


def test_pepper_unset_fails_closed(client, google, monkeypatch):
    monkeypatch.delenv("WEB_SESSION_PEPPER")
    r = client.post("/api/auth/google", json={"id_token": google()})
    assert r.status_code == 503 and r.json()["detail"] == {"error": "auth_unavailable"}


def test_ws_ticket_is_single_use_and_short_lived(client, google, monkeypatch):
    tok = enrol(client, google, SoftKey())["session_token"]
    t = client.post("/api/auth/ws-ticket", headers=bearer(tok)).json()
    assert t["expires_in"] == 60
    assert ws.mem_take("wsticket", t["ticket"]) is not None
    assert ws.mem_take("wsticket", t["ticket"]) is None             # burned
    expired = ws.mem_put("wsticket", -1, "h")
    assert ws.mem_take("wsticket", expired) is None


def _ws_conn(path, query="", headers=()):
    from starlette.requests import HTTPConnection
    return HTTPConnection({"type": "websocket", "path": path, "query_string": query.encode(),
                           "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
                           "scheme": "ws", "server": ("t", 80)})


def test_ws_gate_consumes_ticket_once(client, google, monkeypatch):
    monkeypatch.setenv("SITE_AUTH_ENFORCE", "1")
    a = enrol(client, google, SoftKey())
    t = client.post("/api/auth/ws-ticket", headers=bearer(a["session_token"])).json()["ticket"]
    auth_module.require_site_session(_ws_conn("/ws/market", f"ticket={t}"))
    with pytest.raises(Exception) as e:
        auth_module.require_site_session(_ws_conn("/ws/market", f"ticket={t}"))
    assert getattr(e.value, "status_code", None) == 403
    # ticket for a since-revoked session is refused
    t2 = client.post("/api/auth/ws-ticket", headers=bearer(a["session_token"])).json()["ticket"]
    ws.revoke_session(a["session_handle"])
    with pytest.raises(Exception):
        auth_module.require_site_session(_ws_conn("/ws/market", f"ticket={t2}"))


def test_ws_market_refused_without_ticket_when_enforced(client, monkeypatch):
    monkeypatch.setenv("SITE_AUTH_ENFORCE", "1")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/market?symbols=BTCUSDT"):
            pass


# ---------------------------------------------------------------------------
# The site gate
# ---------------------------------------------------------------------------

_GET_ROUTES = ["/api/health", "/api/bot/strategies", "/api/bot/config", "/api/bot/stats",
               "/api/bot/db/tables", "/api/pnl", "/api/status", "/api/bot/work/checklist"]


@pytest.mark.parametrize("flag", [None, "", "0", "false", "off", "no"])
def test_enforce_off_responses_are_unchanged(client, monkeypatch, flag):
    """Gate off (the default) == the dependency not being there at all."""
    if flag is not None:
        monkeypatch.setenv("SITE_AUTH_ENFORCE", flag)
    seen = {p: client.get(p) for p in _GET_ROUTES}
    api_main.app.dependency_overrides[auth_module.require_site_session] = lambda: None
    try:
        base = {p: client.get(p) for p in _GET_ROUTES}
    finally:
        api_main.app.dependency_overrides.clear()
    for p in _GET_ROUTES:
        assert (seen[p].status_code, seen[p].headers.get("content-type")) == \
               (base[p].status_code, base[p].headers.get("content-type")), p
        if p in ("/api/health", "/api/status", "/api/pnl", "/api/bot/db/tables"):
            assert seen[p].content == base[p].content, p      # byte-identical


def test_enforce_off_never_gates_data_routes(client):
    assert client.get("/api/health").status_code == 200
    r = client.get("/api/bot/strategies")
    assert not (r.status_code == 401 and r.json().get("detail") == {"error": "invalid_session"})


@pytest.fixture
def enforced(monkeypatch):
    monkeypatch.setenv("SITE_AUTH_ENFORCE", "1")


def test_enforced_anonymous_data_routes_are_401(client, enforced):
    for p in ("/api/bot/strategies", "/api/bot/config", "/api/bot/stats", "/api/bot/work/checklist"):
        r = client.get(p)
        assert r.status_code == 401 and r.json()["detail"] == {"error": "invalid_session"}, p
    assert client.post("/api/bot/learning/progress", json={}).status_code == 401


def test_enforced_garbage_and_non_session_bearers_are_401(client, enforced):
    for h in ({"Authorization": "Bearer nope"}, {"Authorization": "Bearer ws_nope"},
              {"Authorization": "Basic abc"}):
        assert client.get("/api/bot/strategies", headers=h).status_code == 401


def test_enforced_valid_session_passes_the_gate(client, google, enforced):
    tok = enrol(client, google, SoftKey())["session_token"]
    r = client.get("/api/bot/strategies", headers=bearer(tok))
    assert not (r.status_code in (401, 403) and r.json().get("detail") == {"error": "invalid_session"})


def test_enforced_public_surface_stays_public(client, google, enforced):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/config").status_code == 200
    assert client.post("/api/auth/google", json={"id_token": google()}).status_code == 200
    # the legacy password login is an auth route: reachable (503 here — no password hash set —
    # is its own answer, NOT the gate's invalid_session)
    r = client.post("/api/auth/login", json={"email": EMAIL, "password": "x"})
    assert r.json()["detail"] != {"error": "invalid_session"}


def test_enforced_cors_preflight_unaffected(client, enforced):
    r = client.options("/api/bot/stats", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert "authorization" in r.headers["access-control-allow-headers"].lower()


def test_enforced_401_still_carries_cors_headers(client, enforced):
    r = client.get("/api/bot/stats", headers={"Origin": ORIGIN})
    assert r.status_code == 401
    assert r.headers.get("access-control-allow-origin") == ORIGIN


def test_enforced_diag_keeps_its_own_token(client, enforced, monkeypatch):
    monkeypatch.delenv("DIAG_READ_TOKEN", raising=False)
    r = client.get("/api/diag/status")
    assert r.json().get("detail") != {"error": "invalid_session"}      # diag's own answer
    monkeypatch.setenv("DIAG_READ_TOKEN", "diagtok")
    assert client.get("/api/diag/status").status_code in (401, 403)     # diag's own 401, not the gate's
    assert client.get("/api/diag/status").json().get("detail") != {"error": "invalid_session"}
    ok = client.get("/api/diag/status", headers=bearer("diagtok"))
    assert ok.status_code not in (401, 403)


def test_enforced_prop_phone_and_report_bearers_unaffected(client, enforced, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "svc")
    for path in ("/api/bot/prop/report", "/api/bot/prop/phone/claim"):
        r = client.post(path, json={})
        assert r.json().get("detail") != {"error": "invalid_session"}, path   # their own gate answered
    bad = client.post("/api/bot/prop/report", json={}, headers=bearer("wrong"))
    assert bad.status_code == 401 and bad.json()["detail"] == "bad token"
    ok = client.post("/api/bot/prop/report", json={}, headers=bearer("svc"))
    assert ok.status_code != 401


def test_enforced_service_token_is_read_only(client, enforced, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "svc")
    g = client.get("/api/bot/strategies", headers=bearer("svc"))
    assert g.status_code != 401
    p = client.post("/api/bot/learning/progress", json={}, headers=bearer("svc"))
    assert p.status_code == 401 and p.json()["detail"] == {"error": "invalid_session"}
    assert client.get("/api/bot/strategies", headers=bearer("wrongsvc")).status_code == 401


def test_service_token_unset_never_authenticates(client, enforced, monkeypatch):
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    assert client.get("/api/bot/strategies", headers=bearer("")).status_code == 401


def test_password_login_still_works_and_legacy_jwt_still_gates_its_routes(client):
    import hashlib as h
    os.environ["WEBAPP_PASSWORD_SHA256"] = h.sha256(b"pw").hexdigest()
    try:
        r = client.post("/api/auth/login", json={"email": EMAIL, "password": "pw"})
        assert r.status_code == 200
        legacy = r.json()["access_token"]
    finally:
        del os.environ["WEBAPP_PASSWORD_SHA256"]
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers=bearer(legacy)).status_code != 401


@pytest.mark.asyncio
async def test_existing_require_session_also_accepts_a_device_session(client, google):
    from starlette.requests import Request
    tok = enrol(client, google, SoftKey())["session_token"]
    req = Request({"type": "http", "method": "GET", "path": "/api/pnl", "query_string": b"",
                   "headers": [(b"authorization", f"Bearer {tok}".encode())]})
    claims = await auth_module.require_session(req)
    assert claims["email"] == EMAIL
    bad = Request({"type": "http", "method": "GET", "path": "/api/pnl", "query_string": b"",
                   "headers": [(b"authorization", b"Bearer ws_forged")]})
    with pytest.raises(Exception) as e:
        await auth_module.require_session(bad)
    assert e.value.status_code == 401


def test_web_sessions_table_is_invisible_to_the_data_explorer():
    from src.web.api.routers import db_explorer
    assert "web_sessions" not in db_explorer._TABLE_ALLOWLIST
