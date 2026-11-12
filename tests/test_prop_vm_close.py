"""CAP-PROP-VM-CLOSE (operator 2026-11-12: "The system needs to be able to do that on its own."): the system closes
or partly closes a VM-executed prop position (tradeify_1, velotrade_1) with no operator at a terminal.

A request is a write to the ticket's ``meta.close_request``; the account's own executor tick carries it out through
its watched close and reads the venue back. These tests cover the request guards and capability refusals, the
projection the executor reads, the executor step (close, partial, retry, read_only), the REST partial-close body,
and the live-review ``prop_vm`` path under an account-scoped auto mandate.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from scripts.ops import live_review_apply as lra
from src.prop import prop_journal, vm_close
from src.prop.platform.base import Position
from src.prop.platform.dxtrade_api import DXtradeApiAdapter
from src.prop.prop_executor import CycleResult, ExecutorConfig
from src.runtime import live_review_intent as lri

SIG = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    monkeypatch.setattr(prop_journal, "_prop_scope", lambda acct: set())


def _ticket(tid, account, *, status="filled"):
    prop_journal.ensure_tables()
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": account, "strategy": "trend_donchian_sol_4h", "symbol": "SOLUSDT",
        "direction": "short", "entry": 87.64, "sl": 89.105, "tp": 78.964, "qty": 6.8,
        "signal_time": SIG.isoformat(), "valid_until": (SIG + timedelta(hours=4)).isoformat(),
        "status": status, "meta": None, "order_package_id": "pkg-X"})


# ------------------------------------------------------------------ the request

def test_capability_names_what_each_account_can_close():
    v = vm_close.close_capability("velotrade_1")
    assert v["close"] and v["partial"]
    t = vm_close.close_capability("tradeify_1")
    assert t["close"] and not t["partial"] and "FULL size only" in t["why"]
    p = vm_close.close_capability("breakout_2")
    assert not p["close"] and "phone" in p["why"]
    assert vm_close.close_capability("no_such_account")["close"] is False


def test_dry_writes_nothing_apply_writes_reads_back_and_is_projected():
    _ticket("prop-manual-aaaaaa", "velotrade_1")
    dry = vm_close.request_close("prop-manual-aaaaaa", account_id="velotrade_1", fraction=0.5)
    assert dry["result"] == vm_close.R_DRY
    assert vm_close.close_request_from(prop_journal.get_ticket("prop-manual-aaaaaa")["meta"]) is None
    done = vm_close.request_close("prop-manual-aaaaaa", account_id="velotrade_1", fraction=0.5, apply=True,
                                  review_id="LR-1", reason="r")
    assert done["result"] == vm_close.R_QUEUED and done["close_id"].startswith("vmc-")
    req = vm_close.close_request_from(prop_journal.get_ticket("prop-manual-aaaaaa")["meta"])
    assert req["id"] == done["close_id"] and req["fraction"] == 0.5 and req["review_id"] == "LR-1"
    row = {r["ticket_id"]: r for r in prop_journal.list_outbound_tickets(account_id="velotrade_1")}["prop-manual-aaaaaa"]
    assert row["close_request"]["id"] == done["close_id"]           # what the VM executor reads (/api/bot/prop/tickets)


def test_refusals_are_named_and_write_nothing():
    _ticket("prop-manual-bbbbbb", "tradeify_1")
    r = vm_close.request_close("prop-manual-bbbbbb", account_id="tradeify_1", fraction=0.5, apply=True)
    assert r["result"] == vm_close.R_REFUSED and "cannot partly close" in r["detail"]
    assert vm_close.request_close("prop-manual-bbbbbb", account_id="tradeify_1", apply=True)["result"] \
        == vm_close.R_QUEUED                                         # a FULL close on the browser adapter is fine
    _ticket("prop-manual-cccccc", "velotrade_1")
    for kw in ({"fraction": 1.0}, {"fraction": 0.0}, {"fraction": "x"}):
        assert vm_close.request_close("prop-manual-cccccc", account_id="velotrade_1", apply=True, **kw)["result"] \
            == vm_close.R_REFUSED, kw
    assert vm_close.request_close("prop-manual-cccccc", account_id="tradeify_1")["result"] == vm_close.R_REFUSED
    _ticket("prop-manual-dddddd", "velotrade_1", status="closed")
    assert vm_close.request_close("prop-manual-dddddd", account_id="velotrade_1")["result"] == vm_close.R_REFUSED
    assert vm_close.request_close("prop-manual-nope00", account_id="velotrade_1")["result"] == vm_close.R_REFUSED
    assert vm_close.close_request_from(prop_journal.get_ticket("prop-manual-cccccc")["meta"]) is None


# ------------------------------------------------------------------ the executor step

class _Adapter:
    PARTIAL_CLOSE_SUPPORTED = True

    def __init__(self, qty=6.8, *, flatten_ok=True, keep_brackets=True):
        self.pos = Position(symbol="SOLUSD", side="short", quantity=qty, entry_price=87.64, stop_loss=89.105,
                            take_profit=78.964, raw={"positionCode": "PC1"})
        self.flatten_ok, self.keep_brackets = flatten_ok, keep_brackets
        self.calls: List[Any] = []
        self.gone = False

    def read_positions(self, page):
        return [] if self.gone else [self.pos]

    def read_orders(self, page):
        return []

    def read_account(self, page):
        class A:
            def as_dict(self):
                return {"balance": 1.0}
        return A()

    def flatten(self, page, venue, *, arm=False, side=None, quantity=None, entry_price=None):
        self.calls.append(("flatten", venue, arm, side, quantity))
        if arm and self.flatten_ok:
            self.gone = True
        return {"ok": True, "clicked": arm}

    def reduce_position(self, page, pos, qty, *, arm=False, client_id=None):
        self.calls.append(("reduce", qty, arm, client_id))
        if arm:
            self.pos = Position(symbol="SOLUSD", side="short", quantity=round(self.pos.quantity - qty, 6),
                                entry_price=87.64, stop_loss=89.105 if self.keep_brackets else None,
                                take_profit=78.964, raw={"positionCode": "PC1"})
        return {"ok": True}


class _Api:
    def __init__(self, req: Optional[Dict[str, Any]], journal=True):
        self.req, self.journal = req, journal

    def all_tickets(self, account_id):
        return [{"ticket_id": "T1", "symbol": "SOLUSDT", "direction": "short", "close_request": self.req}]

    def open_fills(self, account_id):
        return [{"ticket_id": "T1", "symbol": "SOLUSDT", "direction": "short"}] if self.journal else []


CFG = ExecutorConfig(account_id="velotrade_1", enabled_venue_symbols=["SOLUSD"],
                     symbols={"SOLUSDT": {"venue": "SOLUSD", "price_step": 0.001, "lot_step": 0.1, "min_lots": 0.1}})


def _step(a, api, tmp_path, mode="live"):
    return vm_close.run_close_step(adapter=a, page=None, api=api, cfg=CFG, mode=mode, state_dir=tmp_path,
                                   res=CycleResult(mode=mode), sleep=lambda s: None, reads=2)


def test_a_close_request_is_closed_confirmed_flat_and_done_once(tmp_path):
    a = _Adapter()
    res = _step(a, _Api({"id": "vmc-1", "fraction": None}), tmp_path)
    assert a.calls == [("flatten", "SOLUSD", True, "short", 6.8)]
    assert any("close applied and read back" in x for x in res.alerts)
    done = json.loads((tmp_path / vm_close.DONE_FILE).read_text())
    assert done["vmc-1"]["result"] == "closed"
    a2 = _Adapter()
    _step(a2, _Api({"id": "vmc-1", "fraction": None}), tmp_path)    # the same request never acts twice
    assert a2.calls == []


def test_read_only_walks_the_close_dry_and_leaves_it_pending(tmp_path):
    a = _Adapter()
    _step(a, _Api({"id": "vmc-2", "fraction": None}), tmp_path, mode="read_only")
    assert a.calls == [("flatten", "SOLUSD", False, "short", 6.8)] and not a.gone
    assert not (tmp_path / vm_close.DONE_FILE).exists()
    _step(a, _Api({"id": "vmc-2", "fraction": None}), tmp_path, mode="off")
    assert len(a.calls) == 1


def test_a_failed_close_retries_every_tick_and_red_flags_once(tmp_path):
    a = _Adapter(flatten_ok=False)
    alerts = []
    for _ in range(4):
        alerts += _step(a, _Api({"id": "vmc-3", "fraction": None}), tmp_path).alerts
    assert sum(1 for c in a.calls if c[0] == "flatten") == 4          # no halting: it keeps trying
    assert sum("retries every tick" in x for x in alerts) == 1
    assert sum(x.startswith("RED FLAG") for x in alerts) == 1
    a.flatten_ok = True
    _step(a, _Api({"id": "vmc-3", "fraction": None}), tmp_path)
    assert json.loads((tmp_path / vm_close.DONE_FILE).read_text())["vmc-3"]["result"] == "closed"


def test_a_partial_close_reduces_and_checks_both_brackets_still_rest(tmp_path):
    a = _Adapter()
    res = _step(a, _Api({"id": "vmc-4", "fraction": 0.5}), tmp_path)
    assert a.calls == [("reduce", pytest.approx(3.4), True, "vmc-4")]
    assert a.pos.quantity == pytest.approx(3.4) and a.pos.stop_loss == 89.105 and a.pos.take_profit == 78.964
    assert json.loads((tmp_path / vm_close.DONE_FILE).read_text())["vmc-4"]["result"] == "reduced"
    assert any("partial close (0.5) applied" in x for x in res.alerts)


def test_a_partial_that_loses_a_bracket_is_apply_failed_and_never_resent(tmp_path):
    a = _Adapter(keep_brackets=False)
    res = _step(a, _Api({"id": "vmc-5", "fraction": 0.5}), tmp_path)
    out = json.loads((tmp_path / vm_close.DONE_FILE).read_text())["vmc-5"]
    assert out["result"] == "apply_failed" and "SL" in out["why"] and "both brackets" in out["why"]
    assert any("NOT applied" in x for x in res.alerts)
    _step(a, _Api({"id": "vmc-5", "fraction": 0.5}), tmp_path)
    assert sum(1 for c in a.calls if c[0] == "reduce") == 1           # a partial is sent once


def test_a_partial_below_the_venue_minimum_or_without_support_is_refused(tmp_path):
    a = _Adapter(qty=0.1)
    _step(a, _Api({"id": "vmc-6", "fraction": 0.5}), tmp_path)
    assert a.calls == [] and "minimum" in json.loads((tmp_path / vm_close.DONE_FILE).read_text())["vmc-6"]["why"]
    b = _Adapter()
    b.PARTIAL_CLOSE_SUPPORTED = False
    _step(b, _Api({"id": "vmc-7", "fraction": 0.5}), tmp_path)
    assert b.calls == []


def test_no_journal_row_refuses_and_touches_nothing(tmp_path):
    a = _Adapter()
    _step(a, _Api({"id": "vmc-8", "fraction": None}, journal=False), tmp_path)
    assert a.calls == []
    assert json.loads((tmp_path / vm_close.DONE_FILE).read_text())["vmc-8"]["result"] == "refused"


def test_the_tick_runs_the_close_step_before_the_trail():
    src = (Path(__file__).resolve().parents[1] / "scripts/prop/prop_executor_tick.py").read_text()
    body = src[src.index("def run_cycle_and_trail"):src.index("def run_api_tick")]
    assert body.index("vm_close.run_close_step") < body.index("prop_trail.run_trail_step")


# ------------------------------------------------------------------ the REST partial close

def _api_adapter(sent):
    def transport(method, url, data, headers, timeout):
        sent.append((method, url, json.loads(data) if data else None))
        return 200, {}, "{}"
    a = DXtradeApiAdapter(transport=transport, sleep=lambda s: None)
    a.base_url, a.token, a.account = "https://x/dxsca-web", "tok", "ACC"
    return a


def test_reduce_position_is_one_close_market_order_against_the_position_code():
    sent: List[Any] = []
    a = _api_adapter(sent)
    pos = Position(symbol="SOLUSD", side="short", quantity=6.8, entry_price=87.64, stop_loss=89.1,
                   take_profit=79.0, raw={"positionCode": "PC1"})
    dry = a.reduce_position(None, pos, 3.4, client_id="vmc-1")
    assert dry["ok"] and not dry["clicked"] and sent == []
    assert dry["would_send"] == {"orderCode": "vmc-1", "type": "MARKET", "instrument": "SOLUSD", "quantity": "3.4",
                                 "positionEffect": "CLOSE", "positionCode": "PC1", "side": "BUY", "tif": "GTC"}
    assert a.reduce_position(None, pos, 3.4, arm=True, client_id="vmc-1")["ok"]
    assert len(sent) == 1 and sent[0][0] == "POST" and sent[0][1].endswith("/accounts/ACC/orders")
    for bad in (6.8, 0.0, 3.45, 6.75):                                # whole, zero, off-step, leaves < min
        assert not a.reduce_position(None, pos, bad, arm=True)["ok"], bad
    no_code = Position(symbol="SOLUSD", side="short", quantity=6.8, raw={})
    assert "positionCode" in a.reduce_position(None, no_code, 3.4, arm=True)["why"]
    assert len(sent) == 1
    assert DXtradeApiAdapter.PARTIAL_CLOSE_SUPPORTED is True


def test_a_duplicate_reduce_post_reads_as_already_placed():
    a = DXtradeApiAdapter(transport=lambda *x: (409, {}, json.dumps({"errorCode": "100"})), sleep=lambda s: None)
    a.base_url, a.token, a.account = "https://x", "tok", "ACC"
    pos = Position(symbol="SOLUSD", side="long", quantity=1.0, raw={"positionCode": "PC1"})
    r = a.reduce_position(None, pos, 0.5, arm=True, client_id="vmc-1")
    assert r["ok"] and "already_placed" in r["why"]


# ------------------------------------------------------------------ live_review_apply prop_vm

def _ti(action, **kw):
    base = dict(order_package_id="pkg-X", action=action, direction="short", review_id="LR-9", new_sl=None, mark=84.9,
                atr=1.0, bar_ts="2026-11-12T08:00:00Z", mandate=lri.TRADE_MANDATE_ID, basis=lri.BASIS_JUDGEMENT,
                confidence=0.7, reason="static DD floor", mechanics_verdict="match")
    base.update(kw)
    return lri.LiveReviewIntent(**base)


def test_prop_vm_lists_close_and_reduce_and_the_executor_queues_them():
    assert {"move_tp", "close", "reduce"} <= lra.ACTION_PATHS["prop_vm"]
    _ticket("prop-manual-eeeeee", "velotrade_1")
    _ticket("prop-manual-ffffff", "tradeify_1")
    leg_v = {"row": {"ticket_id": "prop-manual-eeeeee", "account_id": "velotrade_1"}}
    leg_t = {"row": {"ticket_id": "prop-manual-ffffff", "account_id": "tradeify_1"}}
    ok = lra._exec_prop_vm_close(leg_v, "reduce", _ti("partial_close", size_fraction=0.4))
    assert ok["result"] == lra.X_APPLIED and ok["fraction"] == pytest.approx(0.4)
    assert vm_close.close_request_from(prop_journal.get_ticket("prop-manual-eeeeee")["meta"])["fraction"] \
        == pytest.approx(0.4)
    no = lra._exec_prop_vm_close(leg_t, "reduce", _ti("partial_close", size_fraction=0.4))
    assert no["result"] == lra.X_REFUSED and "cannot partly close" in no["detail"]
    full = lra._exec_prop_vm_close(leg_t, "close", _ti("close"))
    assert full["result"] == lra.X_APPLIED
    assert vm_close.close_request_from(prop_journal.get_ticket("prop-manual-ffffff")["meta"])["fraction"] is None


PROP_AUTO = {"mandates": [{
    "id": "MD-LTR-PROP-AUTO", "kind": "ltr_auto_apply", "granted_by": "operator", "parent": "MD-TRADE-DESK",
    "account_scope": {"accounts": ["breakout_2", "tradeify_1", "velotrade_1"],
                      "actions": ["tighten_sl", "partial_close", "close"]}}]}


def test_an_auto_close_reaches_only_the_prop_vm_leg_and_its_own_risk_manager(monkeypatch):
    from tests import test_live_review_apply as tla
    from src.units.accounts.risk import RiskManager

    _ticket("prop-manual-111111", "tradeify_1")
    tk = dict(prop_journal.get_ticket("prop-manual-111111"))
    pkg = dict(tla.PKG)
    monkeypatch.setattr(lra, "_get_package", lambda db, pid: dict(pkg) if pid == pkg["order_package_id"] else None)
    monkeypatch.setattr(lra, "_prop_tickets", lambda pid: [tk])
    monkeypatch.setattr(lra, "_is_phone", lambda aid: False)
    decided: List[str] = []

    def _rm(aid, cfg):
        rm = RiskManager({}, dry_run=False, account_id=aid)
        orig = rm.approve_action
        rm.approve_action = lambda i, v: decided.append(v.account_id) or orig(i, v)
        return rm
    monkeypatch.setattr(lra, "_risk_manager", _rm)
    monkeypatch.setattr(lra, "_ping_action", lambda *a: None)
    monkeypatch.setattr(lra, "_alert", lambda *a: None)
    db = tla._ApplyDB([{**tla._trade(1, "bybit_2"), "entry_price": 0.21}], pkg)
    res = lra.run(_ti("close", mandate="MD-LTR-PROP-AUTO", order_package_id=pkg["order_package_id"]), apply=True, db=db, accounts=tla.ACCOUNTS,
                  strategies=tla.STRATS, review_cfg={"apply_mode": "apply"}, granted=set(), write_log=False, state={},
                  mandates_doc=PROP_AUTO)
    assert res["scope_excluded"] == ["bybit_2"]                      # real money untouched
    (rec,) = res["accounts"]
    assert rec["account_id"] == "tradeify_1" and rec["account_class"] == "prop_vm" and rec["executed"], rec
    assert decided == ["tradeify_1"]                                 # the account's own RiskManager decided
    assert vm_close.close_request_from(prop_journal.get_ticket("prop-manual-111111")["meta"]) is not None
