"""ALPACA-LIVE-MECHANICS (2026-11-06; operator popup ~16:50Z "Lane fixes the close path").

A position whose OCO legs survive an ACCEPTED cancel (the alpaca_paper GLD 39-share hold since 2026-08-27)
still flattens: close() exits THROUGH the resting OCO. The fake broker behaves the way Alpaca did live:
  * 17:40Z  the pair is validated on every replace: long TP limit > SL stop, short TP limit < SL stop;
  * 18:50Z  replacing the held stop issues a NEW leg (891ddff0 -> c928eda6, `replaces` = old id), the old leg
            stays in the nested listing with status `replaced`, and the new one can read `pending_replace`
            for a moment;
  * 18:52Z  a PATCH carrying stop_price on the limit parent is refused ("limit orders must not have stop_price").
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.units.accounts.alpaca_client import AlpacaClient, CancelOutcome, oco_pair_valid

INSUFFICIENT = {"retCode": 403, "retMsg": "insufficient qty available for order (requested: 39, available: 0)"}
PAIR_REFUSAL = "take_profit.limit_price must be > stop_loss.stop_price"


class Broker:
    def __init__(self, side="sell", tp=461.27, sl=416.09, qty=39.0, *, stop_id="891ddff0", stale_legs=(),
                 pending_reads=0, settle_lag=0, allow_stop_patch=True, tp_extra=None):
        self.side, self.tp, self.sl, self.qty = side, tp, sl, qty
        self.tp_id, self.sl_id = "2e843e04", stop_id
        self.stale: List[Dict[str, Any]] = list(stale_legs)    # replaced legs still listed under the parent
        self.pending_reads, self.allow_stop_patch = pending_reads, allow_stop_patch
        self.settle_lag = settle_lag                            # reads the NEW leg stays pending_replace
        self.tp_extra = tp_extra or {}
        self.patches: List[Dict[str, Any]] = []
        self.pairs_after: List[tuple] = []
        self.flat = False
        self._n = 0

    def _stop_leg(self) -> Dict[str, Any]:
        leg = {"id": self.sl_id, "symbol": "GLD", "type": "stop", "order_class": "oco", "side": self.side,
               "qty": str(self.qty), "stop_price": str(self.sl), "parent_id": self.tp_id,
               "status": "pending_replace" if self.pending_reads > 0 else "held"}
        if self.stale:
            leg["replaces"] = self.stale[-1]["id"]
        return leg

    def residual(self) -> List[Dict[str, Any]]:
        if self.flat:
            return []
        tp = {"id": self.tp_id, "symbol": "GLD", "type": "limit", "order_class": "oco", "side": self.side,
              "qty": str(self.qty), "status": "new", "limit_price": str(self.tp)}
        tp.update(self.tp_extra)
        out = [tp, self._stop_leg()] + [dict(s) for s in self.stale]
        if self.pending_reads > 0:
            self.pending_reads -= 1
        return out

    def patch(self, oid: str, body: Dict[str, Any], mark: float) -> Dict[str, Any]:
        self.patches.append({"id": oid, **body})
        if any(s["id"] == oid for s in self.stale):
            return {"retCode": 422, "retMsg": "order is not open"}
        new_tp, new_sl = self.tp, self.sl
        if oid == self.tp_id:
            if "stop_price" in body:
                return {"retCode": 422, "retMsg": "limit orders must not have stop_price"}
            new_tp = float(body["limit_price"])
        elif oid == self.sl_id:
            if not self.allow_stop_patch:
                return {"retCode": 422, "retMsg": "order is held and cannot be replaced"}
            new_sl = float(body["stop_price"])
        else:
            return {"retCode": 404, "retMsg": "order not found"}
        if not oco_pair_valid(self.side, new_tp, new_sl):
            return {"retCode": 422, "retMsg": PAIR_REFUSAL}
        if oid == self.sl_id:                                    # a replace issues a NEW leg
            old = self._stop_leg()
            old.update(status="replaced")
            old.pop("replaces", None)
            self.stale.append(old)
            self.sl_id = f"{self.sl_id}-r{len(self.stale)}"
            self.pending_reads = self.settle_lag
        self.tp, self.sl = new_tp, new_sl
        self.pairs_after.append((self.tp, self.sl))
        if (self.side == "sell" and self.tp <= mark) or (self.side == "buy" and self.tp >= mark):
            self.flat = True                                     # a marketable TP fills; the OCO cancels the stop
        return {"retCode": 0, "result": {"id": oid + "-new"}}


def _client(monkeypatch, b: Broker, *, side="long", px=372.40):
    monkeypatch.setenv("ALPACA_CANCEL_SETTLE_S", "0")
    monkeypatch.setenv("ALPACA_FLATTEN_RETRY_S", "0")
    monkeypatch.setenv("ALPACA_CLOSE_CONFIRM_S", "0.05")
    monkeypatch.setenv("ALPACA_OCO_SETTLE_S", "2")
    monkeypatch.setattr("src.units.accounts.alpaca_client.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr("src.runtime.market_hours.us_equity_session", lambda *_a, **_k: "rth")
    cli = AlpacaClient(api_key="k", api_secret="s")
    monkeypatch.setattr(cli, "_resolve_close_scope", lambda sym, q: type("S", (), {
        "envelope": None, "partial": False, "qty": q, "live_qty": b.qty})())
    monkeypatch.setattr(cli, "_cancel_open_orders_detailed",
                        lambda *_a: CancelOutcome("orders_read", 2, 0, [], accepted_ids=(b.tp_id, b.sl_id)))
    monkeypatch.setattr(cli, "_open_orders_for_symbol", lambda *_a, **_k: b.residual())
    monkeypatch.setattr(cli, "position_quote", lambda sym: {"state": "open", "qty": b.qty, "side": side,
                                                            "current_price": px})
    monkeypatch.setattr(cli, "positions", lambda: [] if b.flat else [{"symbol": "GLD", "qty": str(b.qty)}])

    def fake_request(method, path, json_body=None):
        if method == "DELETE" and path.startswith("/v2/positions/GLD"):
            return INSUFFICIENT
        if method == "PATCH":
            return b.patch(path.rsplit("/", 1)[-1], dict(json_body or {}), px)
        if method == "GET" and path.startswith("/v2/positions/"):
            return {"retCode": 0, "result": {"qty": str(b.qty), "qty_available": "0"}}
        return {"retCode": 0, "result": []}

    monkeypatch.setattr(cli, "_request", fake_request)
    return cli


def _pairs_valid(b: Broker) -> bool:
    return all(oco_pair_valid(b.side, tp, sl) for tp, sl in b.pairs_after)


# ── the GLD state right now (after 18:50Z): stop already replaced to 354.4, TP still 461.27 ──────────────
GLD_NOW = dict(sl=354.40, stop_id="c928eda6", stale_legs=[{
    "id": "891ddff0", "symbol": "GLD", "type": "stop", "order_class": "oco", "side": "sell", "qty": "39",
    "stop_price": "416.09", "parent_id": "2e843e04", "status": "replaced"}])


def test_gld_now_moves_only_the_target_against_the_current_stop(monkeypatch):
    b = Broker(**GLD_NOW)
    out = _client(monkeypatch, b).close("GLD")
    assert out["retCode"] == 0 and out["result"]["scope"] == "oco_target_reprice"
    assert [p["id"] for p in b.patches] == ["2e843e04"]          # no stop PATCH, never the replaced 891ddff0
    assert set(b.patches[0]) == {"id", "limit_price"}             # never stop_price on the limit parent
    assert float(b.patches[0]["limit_price"]) == pytest.approx(372.40 * 0.99, abs=0.01)
    assert _pairs_valid(b)


def test_a_replaced_leg_is_never_selected(monkeypatch):
    cli = _client(monkeypatch, Broker(**GLD_NOW))
    tp, stop, why = cli._select_oco_pair(Broker(**GLD_NOW).residual(), "sell", 39.0)
    assert why is None and tp["id"] == "2e843e04" and stop["id"] == "c928eda6"


def test_from_the_original_state_stop_first_then_target_against_the_new_leg(monkeypatch):
    b = Broker()                                                  # TP 461.27, stop 416.09 above the mark
    out = _client(monkeypatch, b).close("GLD")
    assert out["retCode"] == 0
    assert [p["id"] for p in b.patches] == ["891ddff0", "2e843e04"]
    assert float(b.patches[0]["stop_price"]) == pytest.approx(372.40 * 0.95, abs=0.01)
    assert _pairs_valid(b) and len(b.pairs_after) == 2


def test_the_target_waits_until_the_new_stop_has_settled(monkeypatch):
    b = Broker(settle_lag=2)                                      # the NEW leg reads pending_replace twice
    out = _client(monkeypatch, b).close("GLD")
    assert out["retCode"] == 0 and [p["id"] for p in b.patches] == ["891ddff0", "2e843e04"]
    assert b.pending_reads == 0                                   # the reads waited the pending window out


def test_a_stop_that_never_settles_does_not_send_the_target(monkeypatch):
    b = Broker(settle_lag=10_000)
    cli = _client(monkeypatch, b)
    monkeypatch.setenv("ALPACA_OCO_SETTLE_S", "0")                # one read, then the window is over
    out = cli.close("GLD")
    assert out["retCode"] != 0 and "not seen settled" in out["retMsg"]
    assert [p["id"] for p in b.patches] == ["891ddff0"]


def test_a_current_stop_in_flight_is_not_patched_again(monkeypatch):
    b = Broker(pending_reads=10_000, sl=416.09)
    out = _client(monkeypatch, b).close("GLD")
    assert b.patches == [] and "still in flight" in out["retMsg"]


def test_short_keeps_tp_below_sl_at_every_step(monkeypatch):
    b = Broker(side="buy", tp=300.00, sl=330.00)
    out = _client(monkeypatch, b, side="short", px=310.00).close("GLD")
    assert out["retCode"] == 0 and _pairs_valid(b)
    assert [p["id"] for p in b.patches] == ["2e843e04"]          # 313.10 < 330: stop already valid


@pytest.mark.parametrize("side,pos,mark,tp,sl,expect", [
    ("sell", "long", 372.40, 461.27, 416.09, ["891ddff0", "2e843e04"]),   # stop above the mark: stop first
    ("sell", "long", 372.40, 461.27, 354.40, ["2e843e04"]),               # stop already valid: target only
    ("sell", "long", 100.00, 120.00, 95.00, ["2e843e04"]),
    ("buy", "short", 80.00, 60.00, 70.00, ["891ddff0", "2e843e04"]),     # short stop the mark ran through
    ("buy", "short", 50.00, 40.00, 55.00, ["2e843e04"]),
])
def test_every_accepted_patch_keeps_a_valid_pair(monkeypatch, side, pos, mark, tp, sl, expect):
    b = Broker(side=side, tp=tp, sl=sl)
    out = _client(monkeypatch, b, side=pos, px=mark).close("GLD")
    assert out["retCode"] == 0 and _pairs_valid(b)
    assert [p["id"] for p in b.patches] == expect
    assert not any("stop_price" in p for p in b.patches if p["id"] == "2e843e04")


def test_a_held_stop_alpaca_will_not_replace_is_named(monkeypatch):
    b = Broker(allow_stop_patch=False)
    out = _client(monkeypatch, b).close("GLD")
    assert out["retCode"] != 0 and "stop replace refused" in out["retMsg"] and b.pairs_after == []


def test_an_accepted_reprice_that_does_not_flatten_is_not_a_close(monkeypatch):
    b = Broker(**GLD_NOW)
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
    b = Broker(tp_extra=extra)
    out = _client(monkeypatch, b).close("GLD")
    assert b.patches == [], why
    assert out["retCode"] != 0 and "oco target exit no_candidate" in out["retMsg"]


def test_pair_rule_helper():
    assert oco_pair_valid("sell", 368.68, 354.40) and not oco_pair_valid("sell", 368.68, 416.09)
    assert oco_pair_valid("buy", 313.10, 325.50) and not oco_pair_valid("buy", 313.10, 300.00)
