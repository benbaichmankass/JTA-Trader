"""TRADE-ACTION-DIRECT-PATH phase 1b: the SPA console's Approve, the second surface on ONE state machine."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.runtime import trade_approvals as ta
from tests.test_trade_approvals import _row


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "_root", lambda: tmp_path)
    from src.web.api import main
    from src.web.api.auth import require_session
    main.app.dependency_overrides[require_session] = lambda: {"email": "operator"}
    yield TestClient(main.app, raise_server_exceptions=False), tmp_path
    main.app.dependency_overrides.pop(require_session, None)


def _ask(tmp_path):
    return ta.offer(_row(), vm_verdict="advice_only", send=lambda t, k: True, fallback=lambda t: False,
                    now=datetime.now(timezone.utc), root=tmp_path)["token"]


def test_list_and_approve_from_the_console_then_telegram_reads_already_approved(env):
    client, tmp = env
    token = _ask(tmp)
    lst = client.get("/api/bot/trade-approvals?state=pending").json()
    assert lst["count"] == 1 and lst["asks"][0]["token"] == token
    r = client.post(f"/api/bot/trade-approvals/{token}", json={"choice": "approve"})
    assert r.status_code == 200 and r.json()["outcome"] == "approved" and r.json()["record_id"]
    assert ta.read_pending(tmp)["asks"][token]["decided_via"] == "spa"
    again = ta.handle_callback(f"tapv:a:{token}", authorised=True, root=tmp)
    assert again["outcome"] == "already_approved"
    assert client.post(f"/api/bot/trade-approvals/{token}", json={"choice": "reject"}).status_code == 409


def test_bad_input_and_unknown(env):
    client, tmp = env
    assert client.post("/api/bot/trade-approvals/XYZ", json={"choice": "approve"}).status_code == 400
    assert client.post("/api/bot/trade-approvals/0123456789", json={"choice": "maybe"}).status_code == 400
    assert client.post("/api/bot/trade-approvals/0123456789", json={"choice": "approve"}).status_code == 404


def test_without_a_session_nothing_is_decided(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "_root", lambda: tmp_path)
    from src.web.api import main
    client = TestClient(main.app, raise_server_exceptions=False)
    token = _ask(tmp_path)
    r = client.post(f"/api/bot/trade-approvals/{token}", json={"choice": "approve"})
    assert r.status_code in (401, 403, 503)
    assert ta.read_pending(tmp_path)["asks"][token]["state"] == "pending"
