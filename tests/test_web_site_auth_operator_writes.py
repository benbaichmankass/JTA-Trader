"""UI-OAUTH-SIGNIN: operator-write POST routes take EITHER the operator session OR their service token.

Decision: 2026-11-09 operator UI redesign spec, UI-REDESIGN-2026-11 addendum 4 (the Admin page's WAKE
SWITCHES "view + flip, same backend as set_wake_toggle / GET+POST /api/bot/wake-toggles"). The signed-in
dashboard sends ``Bearer ws_...``; the console MCP connector, the Telegram decision bot and work.py keep
their tokens. Pinned per route, with the gate OFF and ON:
  * a live operator session passes, and ``by`` comes from the session, never from the body;
  * the service token still passes;
  * anonymous / wrong token / revoked session are refused (401, or 503 when the token is unset).
``POST /api/bot/alerts`` stays service-token only: its writers are alert posters, not the operator, and
there is no dashboard caller for it (reviewed, see the PR body).
"""
from __future__ import annotations

import pytest

from src.web.api import web_sessions as ws
from tests import test_web_site_auth as base
from tests.test_web_site_auth import SoftKey, bearer, enrol

env = base.env
google = base.google

TOKEN = "svc-token"


@pytest.fixture(params=["gate_off", "gate_on"])
def client(request, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.web.api import main
    if request.param == "gate_on":
        monkeypatch.setenv("SITE_AUTH_ENFORCE", "1")
    monkeypatch.setenv("DASHBOARD_API_TOKEN", TOKEN)
    monkeypatch.setenv("WORK_STORE_TOKEN", TOKEN)
    monkeypatch.setenv("RUNTIME_STATE_DIR", str(tmp_path / "rs"))
    monkeypatch.setenv("WORK_STORE_DB", str(tmp_path / "work_store.db"))
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def session(client, google):
    return enrol(client, google, SoftKey())


def _refused(r) -> bool:
    return r.status_code in (401, 403, 503)


# ── wake-toggles ─────────────────────────────────────────────────────────────

FLIP = {"key": None, "on": False, "by": "spoofed-name"}


def _flip_body():
    from src.runtime import wake_toggles as wt
    return {**FLIP, "key": sorted(wt.TOGGLES)[0]}


def test_wake_toggle_flip_with_operator_session_records_operator_spa(client, session):
    r = client.post("/api/bot/wake-toggles", json=_flip_body(), headers=bearer(session["session_token"]))
    assert r.status_code == 200, r.text
    last = r.json()["recent_flips"][0]
    assert last["by"] == "operator-spa"            # not the body's "spoofed-name", never the email
    assert "@" not in last["by"]


def test_wake_toggle_flip_with_service_token_still_works(client):
    r = client.post("/api/bot/wake-toggles", json=_flip_body(), headers=bearer(TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["recent_flips"][0]["by"] == "spoofed-name"     # service callers name themselves


@pytest.mark.parametrize("headers", [{}, bearer("wrong"), bearer("ws_not-a-session")])
def test_wake_toggle_flip_anonymous_or_bad_credential_is_refused(client, headers):
    r = client.post("/api/bot/wake-toggles", json=_flip_body(), headers=headers)
    assert r.status_code == 401, (r.status_code, r.text)


def test_wake_toggle_flip_with_revoked_session_is_refused(client, session):
    ws.revoke_session(session["session_handle"])
    r = client.post("/api/bot/wake-toggles", json=_flip_body(), headers=bearer(session["session_token"]))
    assert r.status_code == 401


def test_wake_toggle_session_works_even_with_service_token_unset(client, session, monkeypatch):
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    ok = client.post("/api/bot/wake-toggles", json=_flip_body(), headers=bearer(session["session_token"]))
    assert ok.status_code == 200
    anon = client.post("/api/bot/wake-toggles", json=_flip_body())
    assert anon.status_code == 503                                  # fail-closed is unchanged


def test_wake_toggle_session_of_a_de_allowlisted_email_is_refused(client, session, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAIL", "someone-else@example.invalid")
    r = client.post("/api/bot/wake-toggles", json=_flip_body(), headers=bearer(session["session_token"]))
    assert r.status_code == 401


# ── work/decision ────────────────────────────────────────────────────────────


def test_work_decision_operator_session_passes_auth(client, session):
    # No such object: a 404 proves the auth check passed and the router ran.
    r = client.post("/api/bot/work/decision", headers=bearer(session["session_token"]),
                    json={"object_id": "NOPE", "request_id": "r1", "chosen": "a"})
    assert r.status_code == 404, (r.status_code, r.text)


def test_work_decision_service_token_still_passes(client):
    r = client.post("/api/bot/work/decision", headers=bearer(TOKEN),
                    json={"object_id": "NOPE", "request_id": "r1", "chosen": "a"})
    assert r.status_code == 404


@pytest.mark.parametrize("headers", [{}, bearer("wrong")])
def test_work_decision_anonymous_is_refused(client, headers):
    r = client.post("/api/bot/work/decision", headers=headers,
                    json={"object_id": "NOPE", "request_id": "r1", "chosen": "a"})
    assert r.status_code == 401


def test_work_decision_submitted_by_comes_from_the_session(client, session, monkeypatch):
    from src.web.api.routers import work
    seen = {}
    monkeypatch.setattr(work, "_find_request", lambda o, r: (
        {"id": r, "options": [{"key": "a"}], "allowsFreeText": False, "answer": None}, ""))

    def fake_append(**kw):
        seen.update(kw)
        return {"submission_id": "s1", "submitted_at": "2026-11-12T00:00:00Z"}
    monkeypatch.setattr(work, "append_submission", fake_append)
    r = client.post("/api/bot/work/decision", headers=bearer(session["session_token"]),
                    json={"object_id": "OBJ", "request_id": "r1", "chosen": "a", "submitted_by": "spoof"})
    assert r.status_code == 200, r.text
    # Never the email: decision records can reach the repo (manager 2026-11-13).
    assert seen["submitted_by"] == "operator-spa"
    assert "@" not in seen["submitted_by"]


# ── work/items ───────────────────────────────────────────────────────────────

ITEM = {"id": "UIO-TEST-1", "kind": "build", "title": "session write test", "roadmap": ["L-OPS"],
        "due_rule": {"kind": "date", "due_date": "2026-11-30"}}


def test_work_items_create_with_operator_session_records_operator_spa(client, session):
    r = client.post("/api/bot/work/items", headers=bearer(session["session_token"]),
                    json={**ITEM, "by": "spoof"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["item"]["updated_by"] == "operator-spa"
    assert "@" not in r.json()["item"]["updated_by"]


def test_work_items_create_with_session_needs_no_by(client, session):
    r = client.post("/api/bot/work/items", headers=bearer(session["session_token"]),
                    json={**ITEM, "id": "UIO-TEST-2"})
    assert r.status_code in (200, 201), r.text


def test_work_items_create_with_work_store_token_still_works(client):
    r = client.post("/api/bot/work/items", headers={"X-Work-Store-Token": TOKEN},
                    json={**ITEM, "id": "UIO-TEST-3", "by": "work.py test"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["item"]["updated_by"] == "work.py test"


def test_work_items_set_note_close_with_session_record_operator_spa(client, session):
    """Every work-item session write stores operator-spa, never the email (manager 2026-11-13)."""
    h = bearer(session["session_token"])
    r = client.post("/api/bot/work/items", headers=h, json={**ITEM, "id": "UIO-TEST-4"})
    assert r.status_code in (200, 201), r.text
    item = r.json()["item"]
    for path, body in (("set", {"fields": {"title": "renamed by session"}}),
                       ("note", {"text": "a session note"}),
                       ("close", {"state": "done", "reason": "session close test"})):
        r = client.post(f"/api/bot/work/items/UIO-TEST-4/{path}", json={**body, "by": "spoof"},
                        headers={**h, "If-Match": str(item["version"])})
        assert r.status_code == 200, (path, r.text)
        item = r.json()["item"]
        assert item["updated_by"] == "operator-spa", path
        assert "@" not in item["updated_by"], path


@pytest.mark.parametrize("path", ["/api/bot/work/items", "/api/bot/work/items/X/set",
                                  "/api/bot/work/items/X/note", "/api/bot/work/items/X/close"])
@pytest.mark.parametrize("headers", [{}, bearer("wrong"), {"X-Work-Store-Token": "wrong"}])
def test_work_items_anonymous_or_bad_token_is_refused(client, path, headers):
    r = client.post(path, headers=headers, json={**ITEM, "by": "x"})
    assert r.status_code == 401, (path, r.status_code, r.text)


# ── alerts stays service-only ────────────────────────────────────────────────


def test_alerts_post_does_not_take_a_session(client, session):
    r = client.post("/api/bot/alerts", headers=bearer(session["session_token"]),
                    json={"kind": "test", "body": "x"})
    assert _refused(r)
