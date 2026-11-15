"""Tests for GET /api/diag/exchange_positions (BL-20260619 — broker-truth read).

Read-only endpoint that surfaces each account's EXCHANGE-side open positions
(not the journal) so a session can confirm whether a journal orphan actually
exists on the broker before any cleanup. Mirrors get_account_balances' pattern.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.api import main as api_main

_TOKEN = "t" * 64


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DIAG_READ_TOKEN", _TOKEN)
    monkeypatch.setenv("JWT_SIGNING_KEY", "x" * 64)
    monkeypatch.setenv("ALLOWED_EMAIL", "test@example.com")
    monkeypatch.setenv("WEBAPP_PASSWORD_SHA256", "deadbeef")


@pytest.fixture
def client(env):
    return TestClient(api_main.app, raise_server_exceptions=False)


def _bearer(tok=_TOKEN):
    return {"Authorization": f"Bearer {tok}"}


def _patch_loaders(monkeypatch, accounts, positions_by_id):
    import src.units.ui.data_loaders as dl

    def _list_accounts():
        return accounts

    def _aop(acc):
        val = positions_by_id.get(acc.get("account_id"), KeyError)
        if val is KeyError:
            raise RuntimeError("boom")
        return val

    monkeypatch.setattr(dl, "list_accounts", _list_accounts)
    monkeypatch.setattr(dl, "account_open_positions", _aop)


_ACCOUNTS = [
    {"account_id": "ib_paper", "exchange": "interactive_brokers"},
    {"account_id": "bybit_2", "exchange": "bybit"},
    {"account_id": "breakout_1", "exchange": "breakout"},
]


def test_requires_token(client, monkeypatch):
    _patch_loaders(monkeypatch, _ACCOUNTS, {})
    assert client.get("/api/diag/exchange_positions").status_code == 401


def test_distinguishes_live_flat_and_unreadable(client, monkeypatch):
    # ib_paper holds a live position; bybit_2 is flat ([]); breakout_1 can't be
    # read (None). None must be preserved as "could-not-read", NOT coerced to [].
    _patch_loaders(monkeypatch, _ACCOUNTS, {
        "ib_paper": [{"symbol": "MGC", "side": "short", "size": 232,
                      "entry_price": 4303.8, "unrealised_pnl": -12.0}],
        "bybit_2": [],
        "breakout_1": None,
    })
    resp = client.get("/api/diag/exchange_positions", headers=_bearer())
    assert resp.status_code == 200
    body = resp.json()
    by_id = {a["account_id"]: a for a in body["accounts"]}
    assert by_id["ib_paper"]["count"] == 1
    assert by_id["ib_paper"]["positions"][0]["symbol"] == "MGC"
    assert by_id["bybit_2"]["positions"] == [] and by_id["bybit_2"]["count"] == 0
    assert by_id["breakout_1"]["positions"] is None  # could-not-read, not flat
    assert by_id["breakout_1"]["count"] is None


def test_account_id_filter(client, monkeypatch):
    _patch_loaders(monkeypatch, _ACCOUNTS, {"ib_paper": [], "bybit_2": [], "breakout_1": None})
    resp = client.get("/api/diag/exchange_positions?account_id=ib_paper", headers=_bearer())
    assert resp.status_code == 200
    body = resp.json()
    assert body["requested_account_id"] == "ib_paper"
    assert [a["account_id"] for a in body["accounts"]] == ["ib_paper"]


def test_one_account_raising_does_not_fail_the_call(client, monkeypatch):
    # account_open_positions raising for one account must not 500 the endpoint;
    # that account reports error + positions=null, the rest still return.
    _patch_loaders(monkeypatch, _ACCOUNTS, {"ib_paper": [], "bybit_2": []})  # breakout_1 missing -> raises
    resp = client.get("/api/diag/exchange_positions", headers=_bearer())
    assert resp.status_code == 200
    by_id = {a["account_id"]: a for a in resp.json()["accounts"]}
    assert by_id["breakout_1"]["positions"] is None
    assert by_id["breakout_1"]["error"] and "boom" in by_id["breakout_1"]["error"]
    assert by_id["ib_paper"]["positions"] == []


# ── DIAG-EXCHANGE-POSITIONS-SLOW (2026-11-14): parallel reads, per-account deadline ──
# Measured live: per-account reads take 4-7 s, and walking them in sequence passed the
# proxy's 30 s upstream limit (HTTP 502 for every all-accounts caller).

def _patch_slow(monkeypatch, accounts, delay_by_id, seen_threads=None):
    import threading
    import time as _t

    import src.units.ui.data_loaders as dl

    def _aop(acc):
        if seen_threads is not None:
            seen_threads[acc["account_id"]] = threading.current_thread().name
        _t.sleep(delay_by_id.get(acc["account_id"], 0.0))
        return []

    monkeypatch.setattr(dl, "list_accounts", lambda: accounts)
    monkeypatch.setattr(dl, "account_open_positions", _aop)


_NON_IB = [{"account_id": f"bybit_{i}", "exchange": "bybit"} for i in range(4)]


def test_non_ib_accounts_are_read_in_parallel(client, monkeypatch):
    import time as _t
    _patch_slow(monkeypatch, _NON_IB, {a["account_id"]: 0.6 for a in _NON_IB})
    t0 = _t.monotonic()
    resp = client.get("/api/diag/exchange_positions", headers=_bearer())
    took = _t.monotonic() - t0
    assert resp.status_code == 200
    rows = resp.json()["accounts"]
    assert [r["read_state"] for r in rows] == ["ok"] * 4
    assert took < 1.8, f"4 x 0.6 s reads took {took:.2f}s: still sequential"   # sequential would be >= 2.4 s


def test_ib_accounts_stay_on_the_single_worker_lane(client, monkeypatch):
    seen = {}
    accts = [{"account_id": "ib_paper", "exchange": "interactive_brokers"},
             {"account_id": "ib_live", "exchange": "interactive_brokers"},
             {"account_id": "bybit_2", "exchange": "bybit"}]
    _patch_slow(monkeypatch, accts, {}, seen_threads=seen)
    resp = client.get("/api/diag/exchange_positions", headers=_bearer())
    assert resp.status_code == 200
    assert seen["ib_paper"].startswith("account-read_") and seen["ib_live"].startswith("account-read_")
    assert seen["bybit_2"].startswith("account-read-par")


def test_a_slow_account_times_out_alone_and_never_fails_the_call(client, monkeypatch):
    import time as _t
    accts = _NON_IB[:3]
    _patch_slow(monkeypatch, accts, {"bybit_0": 3.0, "bybit_1": 0.0, "bybit_2": 0.0})
    t0 = _t.monotonic()
    resp = client.get("/api/diag/exchange_positions?deadline_s=1", headers=_bearer())
    took = _t.monotonic() - t0
    assert resp.status_code == 200
    by_id = {r["account_id"]: r for r in resp.json()["accounts"]}
    assert by_id["bybit_0"]["read_state"] == "timed_out"
    assert by_id["bybit_0"]["positions"] is None and by_id["bybit_0"]["count"] is None   # could-not-look, never flat
    assert "timed_out" in by_id["bybit_0"]["error"]
    assert by_id["bybit_1"]["read_state"] == by_id["bybit_2"]["read_state"] == "ok"
    assert by_id["bybit_1"]["positions"] == []
    assert took < 2.5


def test_deadline_is_clamped_and_echoed(client, monkeypatch):
    _patch_slow(monkeypatch, _NON_IB[:1], {})
    body = client.get("/api/diag/exchange_positions?deadline_s=999", headers=_bearer()).json()
    assert body["deadline_s"] == 25.0
    body = client.get("/api/diag/exchange_positions?deadline_s=0", headers=_bearer()).json()
    assert body["deadline_s"] == 1.0
    assert body["accounts"][0]["read_state"] == "ok" and isinstance(body["accounts"][0]["elapsed_s"], float)
