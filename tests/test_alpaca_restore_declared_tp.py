"""Re-arm the DECLARED target beside a resting stop; never invent one (BRACKETS-ALWAYS item 4, manager pick B).

The real AlpacaClient cancel-confirm / OCO / stop-only code runs against a routed ``_request`` returning Alpaca REST
shapes (the pattern tests/test_alpaca_partial_tp_replace.py uses). Sequence under test: cancel the stop CONFIRMED ->
OCO at the row's stop and declared TP -> immediate stop fallback; transient refusals retry on a cooldown, capped;
price refusals are reported, not retried.
"""
from __future__ import annotations

import pytest

import src.runtime.order_monitor as om
from src.units.accounts.alpaca_client import AlpacaClient

STOP_ID = "bae72f61-aa51-40aa-8f24-8f43a6a71b8d"


class _Venue(AlpacaClient):
    def __init__(self, *, cancel="canceled", oco="ok", stop_ok=True, stop_class="simple", n_stops=1):
        self.api_key, self.api_secret = "k", "s"
        self.cancel, self.oco, self.stop_ok, self.stop_class, self.n_stops = cancel, oco, stop_ok, stop_class, n_stops
        self.calls: list = []
        self.cancelled = False

    def _open_orders_for_symbol(self, symbol, since=None):  # type: ignore[override]
        return [{"id": STOP_ID if i == 0 else f"s{i}", "symbol": "QQQ", "type": "stop", "side": "buy",
                 "qty": "40", "stop_price": "670.00", "order_class": self.stop_class, "status": "new"}
                for i in range(self.n_stops)]

    def _request(self, method, path, json_body=None):  # type: ignore[override]
        self.calls.append((method, path, json_body))
        if method == "DELETE" and path == f"/v2/orders/{STOP_ID}":
            self.cancelled = True
            return {"retCode": 0, "result": {}}
        if method == "GET" and path == f"/v2/orders/{STOP_ID}":
            status = {"canceled": "canceled", "filled": "filled", "stuck": "pending_cancel"}[self.cancel]
            return {"retCode": 0, "result": {"id": STOP_ID, "status": status, "filled_qty": "40" if status == "filled" else "0"}}
        if method == "GET" and path.startswith("/v2/positions/"):
            return {"retCode": 0, "result": {"symbol": "QQQ", "qty": "40", "side": "short", "current_price": "660.0"}}
        if method == "POST":
            b = json_body or {}
            if b.get("order_class") == "oco":
                if self.oco == "ok":
                    return {"retCode": 0, "result": {"id": "oco-new"}}
                msg = ("take_profit.limit_price must be lower than the stop price" if self.oco == "price"
                       else "insufficient qty available for order (requested: 40, available: 0)")
                return {"retCode": 422, "retMsg": msg}
            if b.get("type") == "stop":
                return {"retCode": 0, "result": {"id": "stop-new"}} if self.stop_ok else {"retCode": 403, "retMsg": "refused"}
        return {"retCode": 500, "retMsg": f"unrouted {method} {path}"}

    def posts(self):
        return [b for m, _p, b in self.calls if m == "POST"]


ROW = {"id": 7783, "account_id": "alpaca_paper", "symbol": "QQQ", "direction": "short", "position_size": 40.0,
       "stop_loss": 670.0, "take_profit_1": 640.0}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    om._ALPACA_TP_RESTORE.clear()
    pages: list = []
    monkeypatch.setattr(om, "_page_rearm_refusal", lambda kind, *a, **k: pages.append(kind))
    monkeypatch.setattr(om, "_alpaca_partial_tp_log_path", lambda: str(tmp_path / "log.jsonl"))
    monkeypatch.setattr(AlpacaClient, "cancel_order_confirmed",
                        lambda self, oid, **kw: _ORIG(self, oid, timeout_s=0.0, poll_s=0.0, sleep=lambda s: None))
    return pages


_ORIG = AlpacaClient.cancel_order_confirmed


def _run(v, row=ROW, rows=None, now=1000.0):
    return om._alpaca_restore_declared_target(None, v, "alpaca_paper", "QQQ", row, rows or [row], now=now)


def test_the_declared_target_is_restored_as_an_oco_at_the_rows_levels():
    v = _Venue()
    assert _run(v) == "restored"
    oco = [b for b in v.posts() if b.get("order_class") == "oco"]
    assert len(oco) == 1 and oco[0]["qty"] == "40" and oco[0]["side"] == "buy"
    assert float(oco[0]["take_profit"]["limit_price"]) == 640.0
    assert float(oco[0]["stop_loss"]["stop_price"]) == 670.0
    # the stop was cancelled AND confirmed before the OCO was posted
    seq = [(m, p) for m, p, _b in v.calls]
    assert seq.index(("DELETE", f"/v2/orders/{STOP_ID}")) < seq.index(("GET", f"/v2/orders/{STOP_ID}")) < \
        next(i for i, (m, _p) in enumerate(seq) if m == "POST")


def test_an_undeclared_target_is_never_invented():
    v = _Venue()
    assert _run(v, row={**ROW, "take_profit_1": None}) == "undeclared"
    assert v.calls == []


def test_a_refused_oco_falls_back_to_the_stop_at_once_and_waits_the_cooldown(_env):
    v = _Venue(oco="transient")
    assert _run(v, now=1000.0) == "oco_refused_transient"
    assert [b.get("type") for b in v.posts() if b.get("type") == "stop"] == ["stop"]   # stop re-placed at once
    v2 = _Venue()
    assert _run(v2, now=1000.0 + 60) == "cooldown" and v2.calls == []                 # no churn inside 15 min
    assert _run(v2, now=1000.0 + 901) == "restored"


def test_a_price_refusal_is_reported_and_not_retried(_env):
    v = _Venue(oco="price")
    assert _run(v) == "price_refused"
    assert "target_restore_price_refused" in _env
    v2 = _Venue()
    assert _run(v2, now=999999.0) == "price_refused" and v2.calls == []                # same TP: never re-sent
    assert _run(v2, row={**ROW, "take_profit_1": 645.0}, now=999999.0) == "restored"  # a new declared TP: retried


def test_attempts_are_capped_with_one_red_flag(_env):
    t = 0.0
    for _ in range(om._ALPACA_TP_RESTORE_MAX_ATTEMPTS):
        assert _run(_Venue(oco="transient"), now=t) == "oco_refused_transient"
        t += 901
    assert _run(_Venue(), now=t) == "exhausted"
    assert _run(_Venue(), now=t + 901) == "exhausted"
    assert _env.count("target_restore_exhausted") == 1


def test_an_unconfirmed_cancel_places_nothing():
    v = _Venue(cancel="stuck")
    assert _run(v) == "cancel_unconfirmed" and v.posts() == []


def test_a_stop_that_filled_during_the_cancel_posts_nothing():
    v = _Venue(cancel="filled")
    assert _run(v) == "stop_filled" and v.posts() == []


def test_a_refused_fallback_pages_unprotected(_env):
    v = _Venue(oco="transient", stop_ok=False)
    _run(v)
    assert "target_restore_unprotected" in _env


@pytest.mark.parametrize("kw", [{"stop_class": "bracket"}, {"n_stops": 2}])
def test_anything_but_one_plain_stop_is_not_restorable(kw):
    v = _Venue(**kw)
    assert _run(v) == "not_restorable" and v.calls == []


def test_two_rows_on_the_symbol_is_not_restorable():
    v = _Venue()
    assert _run(v, rows=[ROW, {**ROW, "id": 7900}]) == "not_restorable" and v.calls == []
