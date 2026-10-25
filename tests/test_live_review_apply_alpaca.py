"""AMEND-PARITY-ALL-ACCOUNTS: an Alpaca leg of a live-review intent, end to end.

The intent goes through the account's REAL ``RiskManager.approve_amend`` and
then the REAL Alpaca executor (``live_review_apply._exec_alpaca`` →
``alpaca_amend.exec_trade_leg``) against a mocked venue that models Alpaca's
PATCH-replaces-the-order semantics. Both read-back outcomes are pinned: the
venue shows the new stop (``applied``, journal written, package stop moved), and
the venue 2xx-accepts but nothing moves (``apply_failed``, journal untouched,
one alert).
"""
from __future__ import annotations

import json

import pytest

from scripts.ops import live_review_apply as lra
from src.runtime import live_review_intent as lri
from src.units.accounts.risk import RiskManager
from tests.test_alpaca_amend import FakeAlpaca, FakeDB, _oco

PKG = {"order_package_id": "PA", "status": "open", "strategy_name": "iaum_pullback_1d", "symbol": "SPY",
       "direction": "long", "sl": 100.0, "tp": 120.0}
ACCOUNTS = {"alpaca_live": {"exchange": "alpaca", "mode": "live", "account_class": "real_money", "risk": {}}}
STRATS = {"iaum_pullback_1d": {"execution": "live", "timeframe": "1d"}}


class _DB(FakeDB):
    def __init__(self, rows):
        super().__init__(rows)
        self.package_writes = []

    def get_trades(self, filters=None, limit=None):
        rows = self.rows
        for k, v in (filters or {}).items():
            rows = [r for r in rows if str(r.get(k)) == str(v)]
        return [dict(r) for r in rows]

    def update_order_package(self, pkg_id, updates):
        self.package_writes.append({"pkg": pkg_id, **updates})


def _trade():
    return {"id": 11, "account_id": "alpaca_live", "order_package_id": "PA", "status": "open",
            "stop_loss": 100.0, "position_size": 10.0, "symbol": "SPY", "direction": "long",
            "is_backtest": 0, "notes": None}


def _intent():
    return lri.LiveReviewIntent(order_package_id="PA", action="tighten_sl", direction="long",
                                review_id="LR-20261025T2000Z-PA", new_sl=102.0, mark=105.0, atr=1.0,
                                bar_ts="2026-10-24T00:00:00Z", min_buffer_atr=1.0, mandate=lri.MANDATE_ID,
                                evidence_path="comms/live_review/tables/pa.json")


@pytest.fixture
def venue(monkeypatch):
    seen = {"alerts": [], "pings": [], "client": None}
    monkeypatch.setattr(lra, "_get_package", lambda db, pid: dict(PKG) if pid == "PA" else None)
    monkeypatch.setattr(lra, "_prop_tickets", lambda pid: [])
    monkeypatch.setattr(lra, "_risk_manager", lambda aid, cfg: RiskManager({}, dry_run=False, account_id=""))
    monkeypatch.setattr(lra, "_ping", lambda pkg, aid, level, intent: seen["pings"].append((aid, level)))
    monkeypatch.setattr(lra, "_alert", lambda pkg, aid, line: seen["alerts"].append((aid, line)))
    from src.runtime import order_monitor as om
    monkeypatch.setattr(om, "_build_account_client",
                        lambda aid: (seen["client"], {"exchange": "alpaca", "account_id": aid}))
    return seen


def _run(db):
    return lra.run(_intent(), apply=True, db=db, accounts=ACCOUNTS, strategies=STRATS,
                   review_cfg={"apply_mode": "apply"}, granted={lri.MANDATE_ID}, write_log=False, state={})


def test_alpaca_intent_applies_and_reads_back(venue):
    venue["client"] = FakeAlpaca(legs=_oco(stop=100.0, tp=120.0))
    db = _DB([_trade()])
    res = _run(db)
    (acct,) = res["accounts"]
    assert acct["verdict"] == "approve" and acct["executed"] is True and acct["read"] == "applied"
    assert acct["executor"]["result"] == "applied"
    assert acct["executor"]["oco_leg_ids_after"]["stop"] == "sl-1-r1"
    assert venue["client"].patches == [("sl-1", {"stop_price": "102.00"})]
    (tid, fields), = db.updates
    assert tid == 11 and fields["stop_loss"] == 102.0
    assert json.loads(fields["notes"])["sl_floor"]["source"] == lri.PROVENANCE
    assert res["package_sl_moved"] is True and db.package_writes == [{"pkg": "PA", "sl": 102.0}]
    assert venue["pings"] == [("alpaca_live", 102.0)] and venue["alerts"] == []
    assert res["exit"] == lra.EXIT_OK


def test_alpaca_readback_mismatch_is_apply_failed_and_writes_nothing(venue):
    venue["client"] = FakeAlpaca(legs=_oco(stop=100.0, tp=120.0), patch_effective=False)
    db = _DB([_trade()])
    res = _run(db)
    (acct,) = res["accounts"]
    assert acct["verdict"] == "approve" and acct["executed"] is False
    assert acct["executor"]["result"] == "apply_failed"
    assert db.updates == [] and db.package_writes == [] and res["package_sl_moved"] is False
    assert len(venue["alerts"]) == 1 and "apply_failed" in venue["alerts"][0][1]
    assert res["exit"] == lra.EXIT_FAILED


def test_alpaca_looser_intent_never_reaches_the_venue(venue):
    venue["client"] = FakeAlpaca(legs=_oco(stop=103.0, tp=120.0))
    db = _DB([dict(_trade(), stop_loss=103.0)])
    res = _run(db)
    (acct,) = res["accounts"]
    assert acct["verdict"] == "refuse" and venue["client"].patches == [] and db.updates == []
