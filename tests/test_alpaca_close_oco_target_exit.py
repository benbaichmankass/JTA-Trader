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

import json
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


def _client(monkeypatch, b: Broker, *, side="long", px=372.40, rung3=False):
    monkeypatch.setenv("ALPACA_CANCEL_SETTLE_S", "0")
    monkeypatch.setenv("ALPACA_FLATTEN_RETRY_S", "0")
    monkeypatch.setenv("ALPACA_CLOSE_CONFIRM_S", "0.05")
    monkeypatch.setenv("ALPACA_OCO_SETTLE_S", "2")
    monkeypatch.setattr("src.units.accounts.alpaca_client.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr("src.runtime.market_hours.us_equity_session", lambda *_a, **_k: "rth")
    cli = AlpacaClient(api_key="k", api_secret="s")
    if not rung3:                                                 # the rung-2 tests: no account reset
        monkeypatch.setattr("src.units.accounts.alpaca_client._LADDER_WEDGE_STATES", frozenset())
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


# ── RUNG 3 (operator ~18:55Z: "We can close all the positions on that account if needed to reset ... it can't
#    depend on me"): PAPER resets the account; LIVE never closes-all and raises ONE red flag ──────────────────
def _ladder_client(monkeypatch, *, env="paper", wedge=True):
    b = Broker(allow_stop_patch=False)                            # rung 2 cannot complete
    cli = _client(monkeypatch, b, rung3=True)
    cli.env = env
    calls = {"close_all": 0, "flags": []}
    if not wedge:                                                 # a transient hold: nothing rests at all
        monkeypatch.setattr(cli, "_open_orders_for_symbol", lambda *_a, **_k: [])
        monkeypatch.setattr(cli, "_cancel_open_orders_detailed", lambda *_a: CancelOutcome("orders_read", 0, 0, []))
    inner = cli._request

    def req(method, path, json_body=None):
        if method == "DELETE" and path == "/v2/positions?cancel_orders=true":
            calls["close_all"] += 1
            b.flat = True
            return {"retCode": 207, "result": [{"symbol": "GLD", "status": 200}, {"symbol": "SPY", "status": 200}]}
        return inner(method, path, json_body)

    monkeypatch.setattr(cli, "_request", req)
    monkeypatch.setattr(cli, "positions", lambda: [] if b.flat else [{"symbol": "GLD", "qty": "39"},
                                                                    {"symbol": "SPY", "qty": "51"}])
    monkeypatch.setattr("src.runtime.api_reporting.report_api_failure",
                        lambda **kw: calls["flags"].append(kw))
    return cli, b, calls


def test_rung3_paper_resets_the_account_on_a_broker_wedge(monkeypatch):
    cli, b, calls = _ladder_client(monkeypatch, env="paper")
    out = cli.close("GLD")
    assert calls["close_all"] == 1 and calls["flags"] == []
    assert out["retCode"] == 0 and out["result"]["scope"] == "account_reset"
    assert set(out["result"]["closed_symbols"]) == {"GLD", "SPY"}


def test_rung3_never_fires_on_a_transient_hold(monkeypatch):
    cli, _b, calls = _ladder_client(monkeypatch, env="paper", wedge=False)
    out = cli.close("GLD")
    assert calls["close_all"] == 0 and out["retCode"] != 0


def test_rung3_live_never_closes_all_and_raises_one_red_flag(monkeypatch):
    cli, _b, calls = _ladder_client(monkeypatch, env="live")
    out = cli.close("GLD")
    assert calls["close_all"] == 0 and out["retCode"] != 0
    assert "close ladder exhausted on a LIVE account" in out["retMsg"] and "2e843e04" in out["retMsg"]
    (flag,) = calls["flags"]
    assert flag["op"] == "close_ladder_exhausted_live" and "891ddff0" in flag["error"]


def test_account_reset_method_refuses_on_live():
    cli = AlpacaClient(api_key="k", api_secret="s", env="live")
    assert cli._account_reset_close_all("GLD")["state"] == "not_paper"


# ── the journal after a reset: every other open trade closed `account_reset`, nothing orphaned ───────────────
class _JDB:
    def __init__(self, trades):
        self.trades = {t["id"]: dict(t) for t in trades}
        self.pkgs: dict = {}

    def get_trades(self, filters=None):
        f = filters or {}
        return [dict(t) for t in self.trades.values() if all(t.get(k) == v for k, v in f.items())]

    def update_trade(self, tid, up):
        self.trades[tid].update(up)

    def update_order_package(self, pid, up):
        self.pkgs.setdefault(pid, {}).update(up)


def test_journal_account_reset_closes_the_others_and_their_packages():
    from src.units.accounts.execute import journal_account_reset
    db = _JDB([
        {"id": 5209, "account_id": "alpaca_paper", "status": "open", "order_package_id": "pkg-gld", "notes": "{}"},
        {"id": 6918, "account_id": "alpaca_paper", "status": "open", "order_package_id": "pkg-spy", "notes": "{}"},
        {"id": 6919, "account_id": "alpaca_paper", "status": "open", "order_package_id": "pkg-qqq", "notes": None},
        {"id": 7000, "account_id": "bybit_1", "status": "open", "order_package_id": "pkg-btc", "notes": "{}"},
    ])
    out = journal_account_reset({"account_id": "alpaca_paper", "account_class": "paper"}, keep_trade_id=5209, db=db)
    assert sorted(out["closed_trades"]) == [6918, 6919] and out["error"] is None
    assert db.trades[5209]["status"] == "open"                    # its own caller journals it
    assert db.trades[7000]["status"] == "open"                    # another account is never touched
    assert db.trades[6918]["exit_reason"] == "account_reset"
    assert json.loads(db.trades[6918]["notes"])["closed_by"] == "alpaca_account_reset"
    assert set(out["closed_packages"]) == {"pkg-spy", "pkg-qqq"}
    assert db.pkgs["pkg-spy"] == {"status": "closed", "close_reason": "account_reset"}


def test_journal_account_reset_refuses_real_money():
    from src.units.accounts.execute import journal_account_reset
    db = _JDB([{"id": 1, "account_id": "alpaca_live", "status": "open", "notes": "{}"}])
    out = journal_account_reset({"account_id": "alpaca_live", "account_class": "real_money"}, db=db)
    assert out["closed_trades"] == [] and db.trades[1]["status"] == "open" and "refused" in out["error"]


def test_close_open_position_runs_the_journal_sweep_on_an_account_reset(monkeypatch):
    from src.units.accounts import execute as ex
    seen = {}
    monkeypatch.setattr(ex, "journal_account_reset",
                        lambda cfg, keep_trade_id=None: seen.update(cfg=cfg, keep=keep_trade_id) or {"closed_trades": [1]})
    cli = AlpacaClient(api_key="k", api_secret="s")
    monkeypatch.setattr(cli, "close", lambda sym, qty=None: {"retCode": 0, "result": {
        "orderId": "account_reset", "scope": "account_reset", "closed_symbols": ["GLD", "SPY"]}})
    out = ex.close_open_position(cli, {"exchange": "alpaca", "account_id": "alpaca_paper"},
                                 symbol="GLD", side="long", qty=39, trade_id=5209)
    assert out["ok"] and out["account_reset"] == {"closed_trades": [1]} and seen["keep"] == 5209


# ── ACCEPTED-BUT-NOT-FLAT is a wedge too (live 20:11Z/20:13Z after #23918): the flatten DELETE was accepted, the
#    cancel pass had cancelled the stop c928eda6, and the take-profit 2e843e04 still held all 39 shares ───────────
class _NotFlatBroker:
    """GLD as it stood at 20:13Z: stop gone, TP `new` @461.27 holding everything, the flatten DELETE accepted."""

    def __init__(self, *, reprice_ok=True, side="sell", holder_qty="39", ineffective=False):
        self.side, self.reprice_ok, self.holder_qty = side, reprice_ok, holder_qty
        self.ineffective = ineffective                     # PATCH accepted (2xx), broker never acts (GLD 2026-11-09)
        self.tp = 461.27
        self.flat = False
        self.patches: List[Dict[str, Any]] = []
        self.close_all = 0

    def residual(self):
        if self.flat:
            return []
        return [{"id": "2e843e04", "symbol": "GLD", "type": "limit", "order_class": "oco", "side": self.side,
                 "qty": self.holder_qty, "status": "new", "limit_price": str(self.tp)},
                {"id": "c928eda6", "symbol": "GLD", "type": "stop", "order_class": "oco", "side": self.side,
                 "qty": "39", "status": "canceled", "stop_price": "354.4", "parent_id": "2e843e04"}]


def _not_flat_client(monkeypatch, b: _NotFlatBroker, *, env="paper", px=372.40):
    monkeypatch.setenv("ALPACA_CANCEL_SETTLE_S", "0")
    monkeypatch.setenv("ALPACA_FLATTEN_RETRY_S", "0")
    monkeypatch.setenv("ALPACA_CLOSE_CONFIRM_S", "0.05")
    monkeypatch.setattr("src.units.accounts.alpaca_client.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr("src.runtime.market_hours.us_equity_session", lambda *_a, **_k: "rth")
    cli = AlpacaClient(api_key="k", api_secret="s", env=env)
    flags: List[Dict[str, Any]] = []
    monkeypatch.setattr("src.runtime.api_reporting.report_api_failure", lambda **kw: flags.append(kw))
    monkeypatch.setattr(cli, "_resolve_close_scope", lambda sym, q: type("S", (), {
        "envelope": None, "partial": False, "qty": q, "live_qty": 39.0})())
    monkeypatch.setattr(cli, "_cancel_open_orders_detailed", lambda *_a: CancelOutcome("orders_read", 1, 0, []))
    monkeypatch.setattr(cli, "_open_orders_for_symbol", lambda *_a, **_k: b.residual())
    monkeypatch.setattr(cli, "position_quote", lambda sym: {"state": "open", "qty": 39.0, "side": "long",
                                                            "current_price": px})
    monkeypatch.setattr(cli, "positions", lambda: [] if b.flat else [{"symbol": "GLD", "qty": "39"}])

    def fake_request(method, path, json_body=None):
        if method == "DELETE" and path == "/v2/positions?cancel_orders=true":
            b.close_all += 1
            b.flat = True
            return {"retCode": 207, "result": [{"symbol": "GLD", "status": 200}]}
        if method == "DELETE" and path.startswith("/v2/positions/GLD"):
            return {"retCode": 0, "result": {"id": "liq-accepted"}}      # ACCEPTED, never fills
        if method == "PATCH":
            b.patches.append({"path": path, **(json_body or {})})
            if not b.reprice_ok:
                return {"retCode": 422, "retMsg": "order is not replaceable"}
            if b.ineffective:
                return {"retCode": 0, "result": {"id": "2e843e04-r"}}
            b.tp = float(json_body["limit_price"])
            b.flat = b.tp <= px
            return {"retCode": 0, "result": {"id": "2e843e04-r"}}
        if method == "GET" and path.startswith("/v2/positions/"):
            return {"retCode": 0, "result": {"qty": "39", "qty_available": "0"}}
        return {"retCode": 0, "result": []}

    monkeypatch.setattr(cli, "_request", fake_request)
    return cli, flags


def test_accepted_not_flat_escalates_to_the_take_profit_reprice(monkeypatch):
    b = _NotFlatBroker()
    cli, flags = _not_flat_client(monkeypatch, b)
    out = cli.close("GLD")
    assert out["retCode"] == 0 and out["result"]["scope"] == "oco_target_reprice"
    (p,) = b.patches
    assert p["path"] == "/v2/orders/2e843e04" and set(p) == {"path", "limit_price"}   # alone: no stop left
    assert float(p["limit_price"]) == pytest.approx(372.40 * 0.99, abs=0.01)
    assert b.close_all == 0 and flags == []


def test_accepted_not_flat_reprice_refused_resets_a_paper_account(monkeypatch):
    b = _NotFlatBroker(reprice_ok=False)
    cli, flags = _not_flat_client(monkeypatch, b)
    out = cli.close("GLD")
    assert b.close_all == 1 and out["retCode"] == 0 and out["result"]["scope"] == "account_reset"
    assert flags == []


def test_accepted_not_flat_on_live_flags_once_and_names_the_missing_stop(monkeypatch):
    b = _NotFlatBroker(reprice_ok=False)
    cli, flags = _not_flat_client(monkeypatch, b, env="live")
    out = cli.close("GLD")
    assert b.close_all == 0 and out["retCode"] == 1
    assert "close ladder exhausted on a LIVE account" in out["retMsg"] and "POSITION HAS NO STOP" in out["retMsg"]
    (flag,) = flags
    assert flag["op"] == "close_ladder_exhausted_live" and "stopless" in flag["error"]


def test_accepted_not_flat_without_a_holding_order_is_an_ordinary_retry(monkeypatch):
    b = _NotFlatBroker(holder_qty="10")                           # nothing holds the whole position
    cli, flags = _not_flat_client(monkeypatch, b)
    out = cli.close("GLD")
    assert out["retCode"] == 1 and "leaving DB row open to retry" in out["retMsg"]
    assert b.patches == [] and b.close_all == 0 and flags == []


def test_a_cancelled_stop_never_counts_as_the_holder(monkeypatch):
    cli, _ = _not_flat_client(monkeypatch, _NotFlatBroker())
    tp, stop, why = cli._select_oco_pair(_NotFlatBroker().residual(), "sell", 39.0)
    assert why is None and tp["id"] == "2e843e04" and stop is None


def _ineffective_reprice_client(monkeypatch, env):
    """GLD 2026-11-09: the flatten is refused (insufficient qty), rung 2 reprices the take-profit, Alpaca accepts the
    PATCH and never acts: the position stays open. Only the close-all (paper) can clear it."""
    b = Broker(**GLD_NOW)
    cli = _client(monkeypatch, b)
    cli.env = env
    calls = {"close_all": 0, "flags": [], "flat": False}
    inner = cli._request

    def req(method, path, json_body=None):
        if method == "DELETE" and path == "/v2/positions?cancel_orders=true":
            calls["close_all"] += 1
            calls["flat"] = True
            return {"retCode": 207, "result": [{"symbol": "GLD", "status": 200}]}
        return inner(method, path, json_body)

    monkeypatch.setattr(cli, "_request", req)
    monkeypatch.setattr(cli, "positions", lambda: [] if calls["flat"] else [{"symbol": "GLD", "qty": "39"}])
    monkeypatch.setattr("src.runtime.api_reporting.report_api_failure", lambda **kw: calls["flags"].append(kw))
    return cli, b, calls


def test_reprice_accepted_but_ineffective_resets_a_paper_account(monkeypatch):
    cli, b, calls = _ineffective_reprice_client(monkeypatch, "paper")
    out = cli.close("GLD")
    assert len(b.patches) == 1 and calls["close_all"] == 1 and calls["flags"] == []
    assert out["retCode"] == 0 and out["result"]["scope"] == "account_reset"
    assert out["result"]["closed_symbols"] == ["GLD"]


def test_reprice_accepted_but_ineffective_on_live_never_closes_all_and_flags_once(monkeypatch):
    cli, _b, calls = _ineffective_reprice_client(monkeypatch, "live")
    out = cli.close("GLD")
    assert calls["close_all"] == 0 and out["retCode"] == 1
    assert "close ladder exhausted on a LIVE account" in out["retMsg"]
    (flag,) = calls["flags"]
    assert flag["op"] == "close_ladder_exhausted_live" and "reprice_not_flat" in flag["error"]
