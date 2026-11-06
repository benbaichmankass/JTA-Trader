"""ALPACA-LIVE-MECHANICS (2026-11-06; operator popup ~16:50Z "Lane fixes the close path").

A position whose OCO legs survive an ACCEPTED cancel (the alpaca_paper GLD 39-share hold since 2026-08-27:
take-profit 2e843e04 `new`, stop 891ddff0 `held`) still flattens: close() exits THROUGH the resting
take-profit by repricing it marketable (PATCH, documented for OCO legs), and the venue's OCO cancels the stop.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from src.units.accounts.alpaca_client import AlpacaClient, CancelOutcome

INSUFFICIENT = {"retCode": 403, "retMsg": "insufficient qty available for order (requested: 39, available: 0)"}


def _tp(**kw):
    o = {"id": "2e843e04", "symbol": "GLD", "type": "limit", "order_class": "oco", "side": "sell", "qty": "39",
         "status": "new", "limit_price": "461.27"}
    o.update(kw)
    return o


STOP = {"id": "891ddff0", "symbol": "GLD", "type": "stop", "order_class": "oco", "side": "sell", "qty": "39",
        "status": "held", "stop_price": "416.09", "parent_id": "2e843e04"}


def _client(monkeypatch, *, residual, side="long", qty=39.0, px=372.40, flat_after_patch=True,
            patch_resp=None) -> (AlpacaClient, Dict[str, Any]):
    monkeypatch.setenv("ALPACA_CANCEL_SETTLE_S", "0")
    monkeypatch.setenv("ALPACA_FLATTEN_RETRY_S", "0")       # single-shot -> give-up path
    monkeypatch.setenv("ALPACA_CLOSE_CONFIRM_S", "0.05")
    monkeypatch.setattr("src.units.accounts.alpaca_client.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr("src.runtime.market_hours.us_equity_session", lambda *_a, **_k: "rth")
    cli = AlpacaClient(api_key="k", api_secret="s")
    seen: Dict[str, Any] = {"patches": [], "deletes": []}
    monkeypatch.setattr(cli, "_resolve_close_scope", lambda sym, q: type("S", (), {
        "envelope": None, "partial": False, "qty": q, "live_qty": qty})())
    # the cancel was ACCEPTED and nothing moved (cancel_accepted_ineffective)
    monkeypatch.setattr(cli, "_cancel_open_orders_detailed",
                        lambda *_a: CancelOutcome("orders_read", 2, 0, [], accepted_ids=("2e843e04", "891ddff0")))
    monkeypatch.setattr(cli, "_open_orders_for_symbol", lambda *_a, **_k: residual)
    monkeypatch.setattr(cli, "position_quote", lambda sym: {"state": "open", "qty": qty, "side": side,
                                                            "current_price": px})
    monkeypatch.setattr(cli, "positions",
                        lambda: [] if (flat_after_patch and seen["patches"]) else [{"symbol": "GLD", "qty": str(qty)}])

    def fake_request(method, path, json_body=None):
        if method == "DELETE" and path.startswith("/v2/positions/GLD"):
            seen["deletes"].append(path)
            return INSUFFICIENT
        if method == "PATCH":
            seen["patches"].append((path, dict(json_body or {})))
            return patch_resp or {"retCode": 0, "result": {"id": "2e843e04-r1"}}
        if method == "GET" and path.startswith("/v2/positions/"):
            return {"retCode": 0, "result": {"qty": str(qty), "qty_available": "0"}}
        return {"retCode": 0, "result": []}

    monkeypatch.setattr(cli, "_request", fake_request)
    return cli, seen


def test_wedged_gld_flattens_through_its_resting_take_profit(monkeypatch):
    cli, seen = _client(monkeypatch, residual=[_tp(), STOP])
    out = cli.close("GLD")
    assert out["retCode"] == 0 and out["result"]["scope"] == "oco_target_reprice"
    (path, body), = seen["patches"]
    assert path == "/v2/orders/2e843e04"                       # the take-profit, never the held stop
    assert float(body["limit_price"]) == pytest.approx(372.40 * 0.99, abs=0.01)   # marketable SELL: below mark
    assert any("cancel_orders=true" in p for p in seen["deletes"])   # escalation 1 still ran first


def test_a_short_reprices_the_buy_to_cover_target_above_the_mark(monkeypatch):
    tp = _tp(side="buy", limit_price="300.00")
    stop = dict(STOP, side="buy")
    cli, seen = _client(monkeypatch, residual=[tp, stop], side="short")
    assert cli.close("GLD")["retCode"] == 0
    assert float(seen["patches"][0][1]["limit_price"]) == pytest.approx(372.40 * 1.01, abs=0.01)


@pytest.mark.parametrize("residual,why", [
    ([_tp(qty="20"), STOP], "covers less than the whole position"),
    ([_tp(status="pending_cancel"), STOP], "documented as not replaceable"),
    ([_tp(order_class="simple"), STOP], "not an OCO/bracket leg"),
    ([_tp(), _tp(id="second")], "two candidates: ambiguous"),
    ([STOP], "no take-profit at all"),
])
def test_no_safe_target_means_nothing_is_sent(monkeypatch, residual, why):
    cli, seen = _client(monkeypatch, residual=residual)
    out = cli.close("GLD")
    assert seen["patches"] == [], why
    assert out["retCode"] != 0 and "oco target exit no_candidate" in out["retMsg"]
    assert "[share_hold=" in out["retMsg"]                     # the classification still reaches the page


def test_a_refused_reprice_is_reported_not_retried_blindly(monkeypatch):
    cli, seen = _client(monkeypatch, residual=[_tp(), STOP],
                        patch_resp={"retCode": 422, "retMsg": "order is not replaceable: pending cancel"})
    out = cli.close("GLD")
    assert len(seen["patches"]) == 1 and out["retCode"] != 0
    assert "oco target exit refused" in out["retMsg"] and "pending cancel" in out["retMsg"]


def test_an_accepted_reprice_that_does_not_flatten_is_not_a_close(monkeypatch):
    cli, _ = _client(monkeypatch, residual=[_tp(), STOP], flat_after_patch=False)
    out = cli.close("GLD")
    assert out["retCode"] == 1 and "not confirmed flat" in out["retMsg"]
