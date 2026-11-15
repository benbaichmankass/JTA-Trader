"""UI-UPGRADE-1-AUTH-HARDEN items kept in UI-OAUTH-SIGNIN: (a) passkey list/revoke, (b), (f), (g), (h).

Parked, not built (operator 2026-11-12: "no more gates that I don't explicitly give you
permission for"): the (a) step-up, (c), (d) and (e). Each adds a refusal no operator quote names.

Uses the real Google verifier (local RSA key) and a software WebAuthn
authenticator from tests/test_web_site_auth.py, so each refusal comes from the
real code path, not a mock.
"""
from __future__ import annotations

import asyncio
import inspect
import time


from src.web.api import auth as auth_module
from src.web.api import web_sessions as ws
from src.web.api.routers import auth_google
from tests import test_web_site_auth as base
from tests.test_web_site_auth import SoftKey, bearer, enrol, login, signin

# Reuse the base module's fixtures (pytest collects module-level fixture objects).
env = base.env
client = base.client
google = base.google


def _begin_add(client, tok, label="Tablet"):
    return client.post("/api/auth/passkey/register/begin", json={"label": label}, headers=bearer(tok))


# (a) passkey list + revoke; revoking a passkey revokes its sessions (the step-up half is parked: no operator quote)

def test_a_signed_in_session_can_add_a_passkey(client, google):
    a = enrol(client, google, SoftKey())
    assert _begin_add(client, a["session_token"]).status_code == 200


def test_a_passkeys_list_has_no_key_material(client, google):
    a = enrol(client, google, SoftKey(), label="Laptop")
    r = client.get("/api/auth/passkeys", headers=bearer(a["session_token"]))
    assert r.status_code == 200
    (pk,) = r.json()["passkeys"]
    assert pk["label"] == "Laptop" and set(pk) == {"handle", "label", "created_at", "last_seen_at"}
    assert client.get("/api/auth/passkeys").status_code == 401        # needs a device


def test_a_revoking_a_passkey_revokes_its_sessions_only(client, google):
    k1, k2 = SoftKey(), SoftKey()
    a = enrol(client, google, k1)
    b = _begin_add(client, a["session_token"])
    client.post("/api/auth/passkey/register/finish", headers=bearer(a["session_token"]),
                json={"challenge_id": b.json()["challenge_id"], "credential": k2.register(b.json()["options"])})
    r2, _, _ = login(client, google, k2)
    tok2 = r2.json()["session_token"]
    handles = {p["label"]: p["handle"] for p in
               client.get("/api/auth/passkeys", headers=bearer(tok2)).json()["passkeys"]}
    out = client.post(f"/api/auth/passkeys/{handles['Laptop']}/revoke", headers=bearer(tok2))
    assert out.status_code == 200 and out.json()["sessions_revoked"] == 1
    assert ws.validate_session(a["session_token"]) is None              # k1's session died
    assert ws.validate_session(tok2) is not None                        # k2's lives
    assert ws.get_passkey(next(p["id"] for p in ws.list_passkeys())) is not None
    assert len(ws.list_passkeys()) == 1
    r, _, _ = login(client, google, k1)                                 # revoked key cannot sign in
    assert r.status_code == 401


# (b) the site gate is async: no threadpool hop when off

def test_b_site_gate_is_a_coroutine_and_off_is_a_no_op(monkeypatch):
    assert inspect.iscoroutinefunction(auth_module.require_site_session)
    monkeypatch.delenv("SITE_AUTH_ENFORCE", raising=False)
    called = []
    monkeypatch.setattr(auth_module, "run_in_threadpool", lambda *a, **k: called.append(a))
    assert asyncio.run(auth_module.require_site_session(object())) is None   # never touches conn
    assert called == []


# (f) the failure log is bounded

def test_f_fail_log_is_bounded(monkeypatch):
    monkeypatch.setattr(ws, "_FAIL_LOG_MAX_IPS", 50)
    ws.reset_memory_for_tests()
    old = time.time() - ws.FAIL_WINDOW_SECONDS - 1
    for i in range(50):
        ws._fail_log[f"10.0.0.{i}"] = [old]
    for i in range(200):
        ws.record_failure(f"10.1.{i // 250}.{i % 250}")
    assert len(ws._fail_log) <= 51
    for _ in range(100):
        ws.record_failure("10.9.9.9")
    assert len(ws._fail_log["10.9.9.9"]) == ws.FAIL_LIMIT
    assert ws.too_many_failures("10.9.9.9") is True
    assert ws.too_many_failures("192.0.2.1") is False and "192.0.2.1" not in ws._fail_log


# (g) the enrol code survives a cancelled ceremony and is burned at finish

def test_g_enrol_code_survives_a_cancelled_begin(client, google):
    code = ws.issue_enrol_code()
    b1 = client.post("/api/auth/passkey/register/begin",
                     json={"preauth_ticket": signin(client, google), "enrol_code": code})
    assert b1.status_code == 200                       # ...and the user cancels the OS prompt
    pre = signin(client, google)
    b2 = client.post("/api/auth/passkey/register/begin", json={"preauth_ticket": pre, "enrol_code": code})
    assert b2.status_code == 200
    f = client.post("/api/auth/passkey/register/finish",
                    json={"challenge_id": b2.json()["challenge_id"],
                          "credential": SoftKey().register(b2.json()["options"])})
    assert f.status_code == 200 and "session_token" in f.json()
    # the first, abandoned challenge cannot reuse the now-burned code
    f1 = client.post("/api/auth/passkey/register/finish",
                     json={"challenge_id": b1.json()["challenge_id"],
                           "credential": SoftKey().register(b1.json()["options"])})
    assert f1.status_code in (401, 403)
    assert len(ws.list_passkeys()) == 1


# (h) no test host in the trusted-proxy list

def test_h_testclient_is_not_a_trusted_proxy(client, google):
    src = inspect.getsource(auth_google._client_ip)
    assert "testclient" not in src
    for _ in range(ws.FAIL_LIMIT):                     # spoofed X-Forwarded-For must not dodge the limiter
        client.post("/api/auth/google", json={"id_token": "garbage"},
                    headers={"X-Forwarded-For": f"203.0.113.{_}"})
    r = client.post("/api/auth/google", json={"id_token": "garbage"},
                    headers={"X-Forwarded-For": "203.0.113.250"})
    assert r.status_code == 429


def test_a_revoke_unknown_passkey_is_404(client, google):
    a = enrol(client, google, SoftKey())
    assert client.post("/api/auth/passkeys/nope/revoke", headers=bearer(a["session_token"])).status_code == 404
