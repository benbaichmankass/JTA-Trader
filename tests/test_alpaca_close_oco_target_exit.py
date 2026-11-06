"""ALPACA-LIVE-MECHANICS (2026-11-06; operator popup ~16:50Z "Lane fixes the close path").

A position whose OCO legs survive an ACCEPTED cancel (the alpaca_paper GLD 39-share hold since 2026-08-27:
take-profit 2e843e04 `new` 461.27, stop 891ddff0 `held` 416.09) still flattens: close() exits THROUGH the
resting OCO. Live 17:40Z showed Alpaca validates the OCO as a PAIR on every replace ("take_profit.limit_price
must be > stop_loss.stop_price"), so the fake broker below enforces exactly that rule on every PATCH, and every
test pins the invariant (long: TP > SL; short: TP < SL) at every step.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.units.accounts.alpaca_client import AlpacaClient, CancelOutcome, oco_pair_valid

INSUFFICIENT = {"retCode": 403, "retMsg": "insufficient qty available for order (requested: 39, available: 0)"}
PAIR_REFUSAL = "take_profit.limit_price must be > stop_loss.stop_price"


class Broker:
    """An OCO pair as Alpaca holds it. Every PATCH is checked against the pair AS IT WOULD STAND after it."""

    def __init__(self, side="sell", tp=461.27, sl=416.09, qty=39.0, *, allow_pair_patch=False,
                 allow_stop_patch=True, renumber=False, tp_extra=None):
        self.side, self.tp, self.sl, self.qty = side, tp, sl, qty
        self.allow_pair_patch, self.allow_stop_patch, self.renumber = allow_pair_patch, allow_stop_patch, renumber
        self.tp_id, self.sl_id = "2e843e04", "891ddff0"
        self.tp_extra = tp_extra or {}
        self.patches: List[Dict[str, Any]] = []
        self.pairs_after: List[tuple] = []          # (tp, sl) after every ACCEPTED patch
        self.flat = False

    def residual(self) -> List[Dict[str, Any]]:
        if self.flat:
            return []
        tp = {"id": self.tp_id, "symbol": "GLD", "type": "limit", "order_class": "oco", "side": self.side,
              "qty": str(self.qty), "status": "new", "limit_price": str(self.tp)}
        tp.update(self.tp_extra)
        sl = {"id": self.sl_id, "symbol": "GLD", "type": "stop", "order_class": "oco", "side": self.side,
              "qty": str(self.qty), "status": "held", "stop_price": str(self.sl), "parent_id": self.tp_id}
        return [tp, sl]

    def patch(self, oid: str, body: Dict[str, Any], mark: float) -> Dict[str, Any]:
        self.patches.append({"id": oid, **body})
        new_tp, new_sl = self.tp, self.sl
        if oid == self.tp_id:
            if "stop_price" in body and not self.allow_pair_patch:
                return {"retCode": 422, "retMsg": "stop_price is not applicable to a limit order"}
            new_tp = float(body.get("limit_price", self.tp))
            new_sl = float(body.get("stop_price", self.sl))
        elif oid == self.sl_id:
            if not self.allow_stop_patch:
                return {"retCode": 422, "retMsg": "order is held and cannot be replaced"}
            new_sl = float(body["stop_price"])
        else:
            return {"retCode": 404, "retMsg": "order not found"}
        if not oco_pair_valid(self.side, new_tp, new_sl):
            return {"retCode": 422, "retMsg": PAIR_REFUSAL}
        self.tp, self.sl = new_tp, new_sl
        self.pairs_after.append((self.tp, self.sl))
        if self.renumber:
            if oid == self.tp_id:
                self.tp_id = self.tp_id + "-r"
            else:
                self.sl_id = self.sl_id + "-r"
        # a marketable TP fills at once; the OCO cancels the stop
        if (self.side == "sell" and self.tp <= mark) or (self.side == "buy" and self.tp >= mark):
            self.flat = True
        return {"retCode": 0, "result": {"id": oid + "-new"}}


def _client(monkeypatch, broker: Broker, *, side="long", px=372.40):
    monkeypatch.setenv("ALPACA_CANCEL_SETTLE_S", "0")
    monkeypatch.setenv("ALPACA_FLATTEN_RETRY_S", "0")            # single-shot -> give-up path
    monkeypatch.setenv("ALPACA_CLOSE_CONFIRM_S", "0.05")
    monkeypatch.setattr("src.units.accounts.alpaca_client.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr("src.runtime.market_hours.us_equity_session", lambda *_a, **_k: "rth")
    cli = AlpacaClient(api_key="k", api_secret="s")
    monkeypatch.setattr(cli, "_resolve_close_scope", lambda sym, q: type("S", (), {
        "envelope": None, "partial": False, "qty": q, "live_qty": broker.qty})())
    monkeypatch.setattr(cli, "_cancel_open_orders_detailed",
                        lambda *_a: CancelOutcome("orders_read", 2, 0, [], accepted_ids=(broker.tp_id, broker.sl_id)))
    monkeypatch.setattr(cli, "_open_orders_for_symbol", lambda *_a, **_k: broker.residual())
    monkeypatch.setattr(cli, "position_quote", lambda sym: {"state": "open", "qty": broker.qty, "side": side,
                                                            "current_price": px})
    monkeypatch.setattr(cli, "positions", lambda: [] if broker.flat else [{"symbol": "GLD", "qty": str(broker.qty)}])

    def fake_request(method, path, json_body=None):
        if method == "DELETE" and path.startswith("/v2/positions/GLD"):
            return INSUFFICIENT
        if method == "PATCH":
            return broker.patch(path.rsplit("/", 1)[-1], dict(json_body or {}), px)
        if method == "GET" and path.startswith("/v2/positions/"):
            return {"retCode": 0, "result": {"qty": str(broker.qty), "qty_available": "0"}}
        return {"retCode": 0, "result": []}

    monkeypatch.setattr(cli, "_request", fake_request)
    return cli


def _invariant_held(b: Broker) -> bool:
    return all(oco_pair_valid(b.side, tp, sl) for tp, sl in b.pairs_after)


# ── the GLD case, exactly as it refused live at 17:40Z ────────────────────────────────────────────────────
def test_the_live_refusal_is_reproduced_by_a_target_only_reprice():
    b = Broker()
    assert b.patch(b.tp_id, {"limit_price": "368.68"}, 372.40) == {"retCode": 422, "retMsg": PAIR_REFUSAL}


def test_long_gld_flattens_stop_first_then_target_keeping_tp_above_sl(monkeypatch):
    b = Broker(side="sell")                                       # Alpaca refuses stop_price on the parent
    out = _client(monkeypatch, b).close("GLD")
    assert out["retCode"] == 0 and out["result"]["scope"] == "oco_target_reprice"
    ids = [p["id"] for p in b.patches]
    assert ids == ["2e843e04", "891ddff0", "2e843e04"]           # pair attempt, then stop, then target
    assert float(b.patches[1]["stop_price"]) == pytest.approx(372.40 * 0.95, abs=0.01)
    assert float(b.patches[2]["limit_price"]) == pytest.approx(372.40 * 0.99, abs=0.01)
    assert _invariant_held(b) and len(b.pairs_after) == 2


def test_long_pair_in_one_patch_when_alpaca_accepts_it(monkeypatch):
    b = Broker(side="sell", allow_pair_patch=True)
    out = _client(monkeypatch, b).close("GLD")
    assert out["retCode"] == 0 and [p["id"] for p in b.patches] == ["2e843e04"]
    assert set(b.patches[0]) == {"id", "limit_price", "stop_price"} and _invariant_held(b)


def test_short_flattens_with_tp_below_sl_at_every_step(monkeypatch):
    b = Broker(side="buy", tp=300.00, sl=330.00)                  # short: buy-to-cover TP below, SL above
    out = _client(monkeypatch, b, side="short", px=310.00).close("GLD")
    assert out["retCode"] == 0
    assert float(b.patches[1]["stop_price"]) == pytest.approx(310.00 * 1.05, abs=0.01)
    assert float(b.patches[2]["limit_price"]) == pytest.approx(310.00 * 1.01, abs=0.01)
    assert _invariant_held(b)


@pytest.mark.parametrize("side,pos,mark,tp,sl", [
    ("sell", "long", 372.40, 461.27, 416.09),     # the GLD hold: stop far ABOVE the mark
    ("sell", "long", 100.00, 120.00, 95.00),      # an ordinary long OCO
    ("buy", "short", 50.00, 40.00, 55.00),        # an ordinary short OCO
    ("buy", "short", 80.00, 60.00, 70.00),        # a short whose stop the mark has run through
])
def test_every_accepted_patch_keeps_a_valid_pair(monkeypatch, side, pos, mark, tp, sl):
    b = Broker(side=side, tp=tp, sl=sl)
    out = _client(monkeypatch, b, side=pos, px=mark).close("GLD")
    assert out["retCode"] == 0 and _invariant_held(b)
    assert not any(p.get("_refused") for p in b.patches)


def test_a_replace_that_renumbers_the_target_is_re_read_before_the_second_patch(monkeypatch):
    b = Broker(side="sell", renumber=True)
    assert _client(monkeypatch, b).close("GLD")["retCode"] == 0
    assert b.patches[2]["id"] == "2e843e04"                       # stop renumbered, target id still current


def test_a_held_stop_alpaca_will_not_replace_is_named_and_nothing_else_moves(monkeypatch):
    b = Broker(side="sell", allow_stop_patch=False)
    out = _client(monkeypatch, b).close("GLD")
    assert out["retCode"] != 0 and "stop replace refused" in out["retMsg"]
    assert [p["id"] for p in b.patches] == ["2e843e04", "891ddff0"] and b.pairs_after == []
    assert "[share_hold=" in out["retMsg"]


def test_an_accepted_reprice_that_does_not_flatten_is_not_a_close(monkeypatch):
    b = Broker(side="sell")
    cli = _client(monkeypatch, b)
    monkeypatch.setattr(cli, "positions", lambda: [{"symbol": "GLD", "qty": "39"}])
    out = cli.close("GLD")
    assert out["retCode"] == 1 and "not confirmed flat" in out["retMsg"]


@pytest.mark.parametrize("extra,why", [
    ({"qty": "20"}, "covers less than the whole position"),
    ({"status": "pending_cancel"}, "documented as not replaceable"),
    ({"order_class": "simple"}, "not an OCO/bracket leg"),
])
def test_no_safe_target_means_nothing_is_sent(monkeypatch, extra, why):
    b = Broker(side="sell", tp_extra=extra)
    out = _client(monkeypatch, b).close("GLD")
    assert b.patches == [], why
    assert out["retCode"] != 0 and "oco target exit no_candidate" in out["retMsg"]


def test_pair_rule_helper():
    assert oco_pair_valid("sell", 368.68, 353.78) and not oco_pair_valid("sell", 368.68, 416.09)
    assert oco_pair_valid("buy", 313.10, 325.50) and not oco_pair_valid("buy", 313.10, 300.00)
