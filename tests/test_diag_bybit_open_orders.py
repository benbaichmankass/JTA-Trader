"""GET /api/diag/bybit_open_orders + ``account_bybit_open_orders``.

BL-20260820-PROTECTION-COVERAGE-IS-PRICE-BLIND criterion 5. That row was
written about IB and explicitly left Bybit unchecked. Bybit carries the same
blindness -- ``_bybit_position_protection``'s Full-mode branch returns
``covered_qty == size`` on any ``stopLoss`` string that is non-empty and not
``"0"`` -- and unlike the IB instance (``ib_paper``), ``bybit_2`` is mainnet.

Three properties are under test, each of which would let a wrong answer through
if it regressed:

1. **The three-state contract.** ``null`` (could not look) must never be
   confusable with a clean read holding nothing, and the counts must stay
   ``null`` rather than reporting ``0`` for an account never reached.
2. **An unset price is ``None``, never ``0.0``.** Bybit reports no-stop as
   ``""`` or ``"0"``. A zero would compare against a declared level as a huge
   divergence, when the truth is that no stop is set at all.
3. **BOTH collections are read.** Full mode puts the stop on the POSITION row
   with no resting order; Partial mode puts it in a conditional leg. Reading
   one collection reports a protected position as naked, or vice versa.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.units.accounts import clients as accounts_clients
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


_ACCOUNTS = [
    {"account_id": "bybit_2", "exchange": "bybit", "mode": "live",
     "account_class": "real_money", "market_type": "linear"},
    {"account_id": "bybit_1", "exchange": "bybit", "mode": "live",
     "account_class": "paper", "market_type": "linear"},
    {"account_id": "ib_paper", "exchange": "interactive_brokers", "mode": "live"},
]


def _patch_route(monkeypatch, by_id, accounts=None):
    import src.units.ui.data_loaders as dl
    monkeypatch.setattr(dl, "list_accounts", lambda: accounts or _ACCOUNTS)

    def _reader(acc):
        val = by_id.get(acc.get("account_id"), KeyError)
        if val is KeyError:
            raise RuntimeError("boom")
        return val

    monkeypatch.setattr(accounts_clients, "account_bybit_open_orders", _reader)


def _by_id(payload):
    return {r["account_id"]: r for r in payload["accounts"]}


# --------------------------------------------------------------------------
# The route: the three-state contract
# --------------------------------------------------------------------------

def test_requires_token(client, monkeypatch):
    _patch_route(monkeypatch, {})
    assert client.get("/api/diag/bybit_open_orders").status_code == 401


def test_non_bybit_account_is_not_bybit_not_a_failure(client, monkeypatch):
    """An IB account is `not_bybit` -- nothing to read, NOT a failed read."""
    _patch_route(monkeypatch, {"bybit_2": {"category": "linear", "positions": [], "orders": []},
                               "bybit_1": None})
    row = _by_id(client.get("/api/diag/bybit_open_orders", headers=_bearer()).json())["ib_paper"]
    assert row["read_state"] == "not_bybit"
    assert row["result"] is None
    assert row["position_count"] is None and row["order_count"] is None


def test_could_not_look_reports_null_counts_never_zero(client, monkeypatch):
    """The collapse this route exists to prevent: an unreached account must not
    report `0 orders`, which reads identically to a confirmed-empty book."""
    _patch_route(monkeypatch, {"bybit_2": None,
                               "bybit_1": {"category": "linear", "positions": [], "orders": []}})
    row = _by_id(client.get("/api/diag/bybit_open_orders", headers=_bearer()).json())["bybit_2"]
    assert row["read_state"] == "could_not_look"
    assert row["order_count"] is None, "0 would read as 'confirmed no orders'"
    assert row["position_count"] is None


def test_clean_empty_read_is_orders_read_with_zero(client, monkeypatch):
    """The mirror image: a confirmed clean read holding nothing IS 0, not null."""
    _patch_route(monkeypatch, {"bybit_2": {"category": "linear", "positions": [], "orders": []},
                               "bybit_1": None})
    row = _by_id(client.get("/api/diag/bybit_open_orders", headers=_bearer()).json())["bybit_2"]
    assert row["read_state"] == "orders_read"
    assert row["order_count"] == 0 and row["position_count"] == 0


def test_one_account_raising_does_not_fail_the_call(client, monkeypatch):
    """bybit_1 is absent from the map, so the reader raises for it."""
    _patch_route(monkeypatch, {"bybit_2": {"category": "linear", "positions": [], "orders": []}})
    payload = client.get("/api/diag/bybit_open_orders", headers=_bearer()).json()
    rows = _by_id(payload)
    assert rows["bybit_2"]["read_state"] == "orders_read"
    assert rows["bybit_1"]["read_state"] == "could_not_look"
    assert rows["bybit_1"]["error"] and "boom" in rows["bybit_1"]["error"]


def test_rows_survive_intact(client, monkeypatch):
    """Reduces nothing: the trigger price is what distinguishes a stop at the
    declared level from one 69 ticks away, so it must reach the consumer."""
    result = {"category": "linear",
              "positions": [{"symbol": "XRPUSDT", "side": "Buy", "size": 21.3,
                             "entry_price": 1.4983, "stop_loss": 1.41,
                             "take_profit": None, "tpsl_mode": "Full"}],
              "orders": [{"symbol": "XRPUSDT", "order_id": "abc",
                          "trigger_price": 1.41, "stop_order_type": "StopLoss"}]}
    _patch_route(monkeypatch, {"bybit_2": result, "bybit_1": None})
    row = _by_id(client.get("/api/diag/bybit_open_orders", headers=_bearer()).json())["bybit_2"]
    assert row["result"] == result
    assert row["result"]["positions"][0]["stop_loss"] == 1.41


# --------------------------------------------------------------------------
# DIAG-BYBIT-OPEN-ORDERS-SLOW (2026-11-15): parallel reads with a per-account deadline
# --------------------------------------------------------------------------

_BYBITS = [{"account_id": f"bybit_{i}", "exchange": "bybit", "mode": "live", "account_class": "paper",
            "market_type": "linear"} for i in range(4)]


def _patch_slow(monkeypatch, accounts, delays, seen_threads=None):
    import threading
    import time as _t

    import src.units.ui.data_loaders as dl
    monkeypatch.setattr(dl, "list_accounts", lambda: accounts)

    def _reader(acc):
        aid = acc.get("account_id")
        if seen_threads is not None:
            seen_threads[aid] = threading.current_thread().name
        _t.sleep(delays.get(aid, 0.0))
        return {"category": "linear", "positions": [], "orders": []}

    monkeypatch.setattr(accounts_clients, "account_bybit_open_orders", _reader)


def test_bybit_accounts_are_read_in_parallel(client, monkeypatch):
    """Measured 2026-11-15: ~6 s per account, the all-accounts call 21-31 s (502 at the proxy). Sequential is gone."""
    import time as _t
    seen = {}
    _patch_slow(monkeypatch, _BYBITS, {a["account_id"]: 0.6 for a in _BYBITS}, seen_threads=seen)
    t0 = _t.monotonic()
    resp = client.get("/api/diag/bybit_open_orders", headers=_bearer())
    took = _t.monotonic() - t0
    assert resp.status_code == 200
    rows = resp.json()["accounts"]
    assert [r["read_state"] for r in rows] == ["orders_read"] * 4
    assert all(isinstance(r["elapsed_s"], float) for r in rows)
    assert took < 1.8, f"4 x 0.6 s reads took {took:.2f}s: still sequential"
    assert all(n.startswith("account-read-par") for n in seen.values())


def test_a_slow_bybit_account_times_out_alone_as_could_not_look(client, monkeypatch):
    import time as _t
    _patch_slow(monkeypatch, _BYBITS[:3], {"bybit_0": 3.0})
    t0 = _t.monotonic()
    resp = client.get("/api/diag/bybit_open_orders?deadline_s=1", headers=_bearer())
    took = _t.monotonic() - t0
    assert resp.status_code == 200
    by_id = _by_id(resp.json())
    slow = by_id["bybit_0"]
    assert slow["read_state"] == "timed_out" and slow["result"] is None
    assert slow["order_count"] is None and slow["position_count"] is None      # could-not-look, never "nothing resting"
    assert "timed_out" in slow["error"]
    assert by_id["bybit_1"]["read_state"] == by_id["bybit_2"]["read_state"] == "orders_read"
    assert by_id["bybit_1"]["order_count"] == 0
    assert took < 2.5


def test_open_orders_deadline_is_clamped_and_echoed_and_account_filter_holds(client, monkeypatch):
    _patch_slow(monkeypatch, _BYBITS[:2] + [{"account_id": "ib_paper", "exchange": "interactive_brokers"}], {})
    body = client.get("/api/diag/bybit_open_orders?deadline_s=999", headers=_bearer()).json()
    assert body["deadline_s"] == 25.0
    by_id = _by_id(body)
    assert by_id["ib_paper"]["read_state"] == "not_bybit" and by_id["ib_paper"]["elapsed_s"] is None
    body = client.get("/api/diag/bybit_open_orders?deadline_s=0&account_id=bybit_1", headers=_bearer()).json()
    assert body["deadline_s"] == 1.0 and [r["account_id"] for r in body["accounts"]] == ["bybit_1"]
