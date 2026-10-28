"""FIX-CA-12 (CA-A08-diag-venue-reads-collapse-could-not-look).

Nine token-gated venue-truth diag routes used to answer HTTP 200 with
``accounts: []`` (and ``ib_open_orders`` ``count: 0``) both when
``list_accounts()`` raised and when ``account_id`` named no configured
account — so "could not look" / "wrong account id" read exactly like "looked,
the venue holds nothing".

Contract now:
  * account list unreadable (``list_accounts`` raised, or ``accounts.yaml``
    failed to parse) -> 503 ``accounts_unreadable``;
  * ``account_id`` names no configured account -> 404 ``unknown_account_id``
    on the seven multi-account routes; the two single-account raw routes keep
    their existing explicit ``read_state: unknown_account``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.api import main as api_main

_TOKEN = "t" * 64

# route -> extra query params it requires
_ROUTES = {
    "/api/diag/exchange_positions": {},
    "/api/diag/venue_session": {},
    "/api/diag/ib_open_orders": {},
    "/api/diag/broker_account_status": {},
    "/api/diag/bybit_open_orders": {},
    "/api/diag/bybit_raw_order_history": {
        "account_id": "bybit_2", "symbol": "BTCUSDT",
        "start_ms": 1_700_000_000_000, "end_ms": 1_700_086_400_000},
    "/api/diag/bybit_raw_closed_pnl": {
        "account_id": "bybit_2", "symbol": "BTCUSDT",
        "start_ms": 1_700_000_000_000, "end_ms": 1_700_086_400_000},
    "/api/diag/bybit_raw_positions": {},
    "/api/diag/alpaca_open_orders": {},
}
_MULTI_ACCOUNT = [r for r, p in _ROUTES.items() if "account_id" not in p]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DIAG_READ_TOKEN", _TOKEN)
    monkeypatch.setenv("JWT_SIGNING_KEY", "x" * 64)
    monkeypatch.setenv("ALLOWED_EMAIL", "test@example.com")
    monkeypatch.setenv("WEBAPP_PASSWORD_SHA256", "deadbeef")
    return TestClient(api_main.app, raise_server_exceptions=False)


def _get(client, route, **params):
    return client.get(route, params=params,
                      headers={"Authorization": f"Bearer {_TOKEN}"})


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_list_accounts_raising_is_503_not_empty(client, monkeypatch, route):
    from src.units.ui import data_loaders

    def _boom():
        raise RuntimeError("accounts.yaml unreadable")

    monkeypatch.setattr(data_loaders, "list_accounts", _boom)
    r = _get(client, route, **_ROUTES[route])
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "accounts_unreadable"


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_accounts_yaml_parse_failure_is_503(client, monkeypatch, tmp_path,
                                            route):
    """list_accounts() itself swallows a YAML parse failure to [] — the
    route must still tell that apart from 'no accounts configured'."""
    from src.units.ui import data_loaders

    bad = tmp_path / "accounts.yaml"
    bad.write_text("accounts: [unclosed\n")
    monkeypatch.setattr(data_loaders, "ACCOUNTS_YAML_PATH", bad)
    r = _get(client, route, **_ROUTES[route])
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "accounts_unreadable"


@pytest.mark.parametrize("route", sorted(_MULTI_ACCOUNT))
def test_unknown_account_id_is_404(client, monkeypatch, route):
    from src.units.ui import data_loaders

    monkeypatch.setattr(data_loaders, "list_accounts",
                        lambda: [{"account_id": "bybit_2",
                                  "exchange": "bybit"}])
    r = _get(client, route, account_id="bybit_typo")
    assert r.status_code == 404, r.text
    body = r.json()["detail"]
    assert body["error"] == "unknown_account_id"
    assert body["account_id"] == "bybit_typo"


def test_bybit_margin_fields_reported_on_a_healthy_available_read(client, monkeypatch):
    """BYBIT1-AVAILABLE-USD-ZERO: margin_fields used to appear only when the
    available read FAILED, so a valid venue_available 0.00 beside ~122k equity
    could not be explained. They are now on every bybit row."""
    from src.units.accounts import clients
    from src.units.ui import data_loaders

    monkeypatch.setattr(data_loaders, "list_accounts",
                        lambda: [{"account_id": "bybit_1", "exchange": "bybit"}])

    class _C:
        def get_wallet_balance(self, accountType):
            return {"retCode": 0, "result": {"list": [{
                "accountType": "UNIFIED", "totalEquity": "122000",
                "totalAvailableBalance": "0", "totalInitialMargin": "12000",
                "coin": [{"coin": "USDT"}]}]}}

    monkeypatch.setattr(clients, "bybit_client_for", lambda acc: _C())
    monkeypatch.setattr("src.web.api.routers.diag._bybit_identity",
                        lambda c: {"read_state": "identity_read", "user_id": "u"})
    r = _get(client, "/api/diag/broker_account_status", account_id="bybit_1")
    assert r.status_code == 200, r.text
    row = r.json()["accounts"][0]
    # collapsed-state: venue_available — this test stubs ONE healthy wallet response to pin that margin_fields ride along on a non-failing read; the other three read states are pinned in tests/test_bybit_available_read_state.py
    assert row["available_margin"]["read_state"] == "venue_available"
    assert row["margin_fields"]["totalEquity"] == "122000"
    assert row["margin_fields_error"] is None
