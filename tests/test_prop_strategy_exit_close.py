"""PROP-VM-STRATEGY-EXIT-CLOSE (operator 2026-11-12, decisions page x1 YES): a strategy's own exit CLOSES the prop
position, as in the backtest, on every prop account class -- with no Claude in the loop.

A closed ORDER PACKAGE (strategy reason) with the venue position still open produces exactly ONE close per account
class (VM: vm_close's watched close; phone: one phone_cancel close request); an already-flat venue produces none; a
rerun produces none; a bookkeeping close reason produces none."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from src.prop import phone_cancel as pc
from src.prop import phone_executor as pe
from src.prop import prop_journal, strategy_exit_close as sec, vm_close
from src.prop.platform.base import Position
from src.prop.prop_executor import CycleResult, ExecutorConfig

SIG = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 12, 11, 40, tzinfo=timezone.utc)


def test_any_closed_package_counts_no_reason_filter():
    """Operator 2026-11-12 ~11:45Z (binding): no gate that was not asked for -- so no close-reason filter."""
    for r in ("sl", "tp", "trail_stop", "netting_attributed", "reconciler_filled", "", None):
        assert sec.package_exited("closed", r), r
    assert not sec.package_exited("open", "sl")


# ------------------------------------------------------------------ VM accounts (tradeify_1 / velotrade_1)

class _Adapter:
    def __init__(self, flat=False):
        self.gone = flat
        self.calls: List[Any] = []
        self.reads = 0

    def read_positions(self, page):
        self.reads += 1
        return [] if self.gone else [Position(symbol="SOLUSD", side="short", quantity=6.8, entry_price=87.64,
                                              stop_loss=89.1, take_profit=79.0, raw={"positionCode": "PC"})]

    def read_orders(self, page):
        return []

    def read_account(self, page):
        class A:
            def as_dict(self):
                return {}
        return A()

    def flatten(self, page, venue, *, arm=False, side=None, quantity=None, entry_price=None):
        self.calls.append(("flatten", venue, arm))
        if arm:
            self.gone = True
        return {"ok": True, "clicked": arm}


class _Api:
    def __init__(self, op_status="closed", close_reason="sl", journal=True):
        self.t = {"ticket_id": "T1", "symbol": "SOLUSDT", "direction": "short", "status": "filled",
                  "op_status": op_status, "close_reason": close_reason, "close_request": None}
        self.journal = journal

    def all_tickets(self, account_id):
        return [dict(self.t)]

    def open_fills(self, account_id):
        return [{"ticket_id": "T1", "symbol": "SOLUSDT", "direction": "short"}] if self.journal else []


CFG = ExecutorConfig(account_id="tradeify_1", enabled_venue_symbols=["SOLUSD"],
                     symbols={"SOLUSDT": {"venue": "SOLUSD", "price_step": 0.001, "lot_step": 0.01, "min_lots": 0.01}})


def _step(a, api, tmp_path):
    return vm_close.run_close_step(adapter=a, page=None, api=api, cfg=CFG, mode="live", state_dir=tmp_path,
                                   res=CycleResult(mode="live"), sleep=lambda s: None, reads=2)


def test_vm_package_exit_with_the_venue_open_closes_once_and_never_again(tmp_path):
    a = _Adapter()
    res = _step(a, _Api(), tmp_path)
    assert a.calls == [("flatten", "SOLUSD", True)]
    done = json.loads((tmp_path / vm_close.DONE_FILE).read_text())
    assert done[sec.vm_request_id("T1")]["result"] == "closed"
    assert sum("close applied" in x for x in res.alerts) == 1              # ONE alert per close
    b = _Adapter()
    _step(b, _Api(), tmp_path)                                             # rerun: nothing
    assert b.calls == []


def test_vm_already_flat_venue_produces_nothing(tmp_path):
    a = _Adapter(flat=True)
    res = _step(a, _Api(), tmp_path)
    assert a.calls == [] and res.alerts == []
    assert sec.vm_request_id("T1") not in vm_close._load_done(tmp_path)    # no record: nothing was closed


def test_vm_no_open_journal_row_reads_no_venue(tmp_path):
    a = _Adapter()
    _step(a, _Api(journal=False), tmp_path)
    assert a.calls == [] and a.reads == 0


@pytest.mark.parametrize("op_status,reason", [("open", "sl"), ("orphaned", None)])
def test_vm_an_open_package_is_not_closed(tmp_path, op_status, reason):
    a = _Adapter()
    _step(a, _Api(op_status=op_status, close_reason=reason), tmp_path)
    assert a.calls == []


def test_vm_an_explicit_request_wins_over_the_synthetic_one():
    assert sec.vm_synth_request({"ticket_id": "T1", "status": "filled", "op_status": "closed", "close_reason": "sl",
                                 "close_request": {"id": "vmc-1"}}) is None


# ------------------------------------------------------------------ phone accounts (breakout_2)

TOKEN = "t" * 43


@pytest.fixture
def phone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    dev = tmp_path / "devices.yaml"
    dev.write_text(yaml.safe_dump({"devices": [
        {"device_id": "p1", "account_id": "breakout_2", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}]}))
    monkeypatch.setattr(pe, "DEVICES_PATH", dev)
    acc = tmp_path / "accounts.yaml"
    acc.write_text(yaml.safe_dump({"accounts": {"breakout_2": {"mode": "live"}}}))
    monkeypatch.setattr(pe, "ACCOUNTS_PATH", acc)
    monkeypatch.delenv("PROP_PHONE_MODE_BREAKOUT_2", raising=False)
    sent: List[str] = []
    monkeypatch.setattr("src.runtime.notify.send_telegram_direct", lambda m, **k: sent.append(m) or True)
    prop_journal.ensure_tables()
    conn = prop_journal._connect()
    conn.execute("CREATE TABLE IF NOT EXISTS order_packages (order_package_id TEXT PRIMARY KEY, status TEXT, "
                 "close_reason TEXT, updated_at TEXT)")
    conn.commit()
    conn.close()
    return sent


def _pkg(pid, status, reason):
    conn = prop_journal._connect()
    conn.execute("INSERT OR REPLACE INTO order_packages VALUES (?,?,?,?)", (pid, status, reason, NOW.isoformat()))
    conn.commit()
    conn.close()


def _ticket(tid, *, status="filled", pkg="pkg-a20ebe8b65ce4c44"):
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": "breakout_2", "strategy": "trend_donchian_eth_4h", "symbol": "ETHUSDT",
        "direction": "short", "entry": 2193.86, "sl": 2260.0, "tp": 2000.0, "qty": 0.3936,
        "signal_time": SIG.isoformat(), "valid_until": (SIG + timedelta(hours=1)).isoformat(), "status": status,
        "order_package_id": pkg, "meta": None})


def _close(tid):
    return (prop_journal.get_ticket(tid)["meta"] or {}).get(pc.CLOSE_KEY) or {}


def test_phone_package_exit_issues_exactly_one_close_and_alerts_once(phone):
    _ticket("P1")
    _pkg("pkg-a20ebe8b65ce4c44", "closed", "sl")
    assert sec.plan_phone_exits("breakout_2", now=NOW) == 1
    c = _close("P1")
    assert c["status"] == "emitted" and c["action"] == "close" and c["reason"].startswith(sec.REASON_PREFIX + "sl")
    assert len(phone) == 1 and "strategy exited" in phone[0]
    assert sec.plan_phone_exits("breakout_2", now=NOW) == 0                 # rerun: nothing
    c2 = dict(c, status="done")                                            # even after the phone reported it
    conn = prop_journal._connect()
    row = conn.execute("SELECT meta FROM prop_tickets WHERE ticket_id='P1'").fetchone()
    m = json.loads(row["meta"])
    m[pc.CLOSE_KEY] = c2
    conn.execute("UPDATE prop_tickets SET meta=? WHERE ticket_id='P1'", (json.dumps(m),))
    conn.commit()
    conn.close()
    assert sec.plan_phone_exits("breakout_2", now=NOW) == 0
    assert len(phone) == 1


@pytest.mark.parametrize("status,reason,tstatus", [("open", "sl", "filled"), ("closed", "sl", "closed"),
                                                   ("closed", "sl", "placed")])
def test_phone_no_close_when_the_package_is_open_or_no_position(phone, status, reason, tstatus):
    _ticket("P2", status=tstatus)
    _pkg("pkg-a20ebe8b65ce4c44", status, reason)
    assert sec.plan_phone_exits("breakout_2", now=NOW) == 0
    assert _close("P2") == {}


def test_the_phone_claim_path_plans_strategy_exits_before_serving_closes(phone):
    src = (Path(__file__).resolve().parents[1] / "src/prop/phone_executor.py").read_text()
    assert src.count("strategy_exit_close.plan_phone_exits(acct, now=now)") == 2
    for chunk in src.split("strategy_exit_close.plan_phone_exits(acct, now=now)")[1:]:
        assert chunk.index("phone_cancel.plan_closes(acct, now=now)") < 200
