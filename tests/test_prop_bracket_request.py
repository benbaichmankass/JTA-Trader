"""PROP-BRACKET-APPLY (operator 2026-11-11): the system sets a VM-prop ticket's TP/SL on its own.

A request is a write to the ticket's ``meta`` (``tp_target`` / ``sl_floor``); the account's trail applies it through
its own amend code. These tests cover the request guards, the capability refusals (tradeify_1 cannot amend a TP),
the projection the executor reads, the trail applying a pinned TP, and the live-review ``prop_vm`` path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List

import pytest

from scripts.ops import live_review_apply as lra
from src.prop import bracket_request as br
from src.prop import prop_journal, prop_trail as pt
from src.prop.platform.base import Position
from src.prop.prop_executor import ExecutorConfig
from src.runtime import live_review_intent as lri

SIG = datetime(2026, 11, 8, 21, 52, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRADE_JOURNAL_DB", str(tmp_path / "trade_journal.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "bot-data"))
    monkeypatch.setattr(prop_journal, "_prop_scope", lambda acct: set())


def _ticket(tid, account, *, status="filled", direction="short", entry=87.64, sl=89.105, tp=78.964):
    prop_journal.ensure_tables()
    prop_journal.record_ticket({
        "ticket_id": tid, "account_id": account, "strategy": "trend_donchian_sol_4h", "symbol": "SOLUSDT",
        "direction": direction, "entry": entry, "sl": sl, "tp": tp, "qty": 6.8,
        "signal_time": SIG.isoformat(), "valid_until": (SIG + timedelta(hours=4)).isoformat(),
        "status": status, "meta": None, "order_package_id": "pkg-X"})


def test_capability_names_why_each_account_can_or_cannot_amend():
    assert br.amend_capability("velotrade_1")["tp"] is True
    t = br.amend_capability("tradeify_1")
    assert t["tp"] is False and t["sl"] is True and "TP_AMEND_SUPPORTED" in t["why"]
    p = br.amend_capability("breakout_2")
    assert p["tp"] is False and p["sl"] is False and "phone" in p["why"]
    assert br.amend_capability("no_such_account")["tp"] is False


def test_dry_run_writes_nothing_and_apply_writes_reads_back_and_is_projected():
    _ticket("prop-manual-aaaaaa", "velotrade_1")
    dry = br.request_bracket("prop-manual-aaaaaa", account_id="velotrade_1", tp=78.964)
    assert dry["result"] == br.R_DRY
    assert lri.tp_target_from(prop_journal.get_ticket("prop-manual-aaaaaa")["meta"]) is None
    done = br.request_bracket("prop-manual-aaaaaa", account_id="velotrade_1", tp=78.964, apply=True, reason="r")
    assert done["result"] == br.R_QUEUED
    assert lri.tp_target_from(prop_journal.get_ticket("prop-manual-aaaaaa")["meta"]) == 78.964
    row = {r["ticket_id"]: r for r in prop_journal.list_outbound_tickets(account_id="velotrade_1")}["prop-manual-aaaaaa"]
    assert row["tp_target"] == 78.964          # what the VM executor reads (/api/bot/prop/tickets)
    br.request_bracket("prop-manual-aaaaaa", account_id="velotrade_1", clear_tp=True, apply=True)
    assert lri.tp_target_from(prop_journal.get_ticket("prop-manual-aaaaaa")["meta"]) is None


def test_refusals_are_named_and_write_nothing():
    _ticket("prop-manual-bbbbbb", "tradeify_1")
    r = br.request_bracket("prop-manual-bbbbbb", account_id="tradeify_1", tp=78.964, apply=True)
    assert r["result"] == br.R_REFUSED and "cannot amend a TP" in r["detail"]
    _ticket("prop-manual-cccccc", "velotrade_1")
    for kw, frag in (({"tp": 90.0}, "profit side"), ({"sl": 90.0}, "looser"),
                     ({"tp": 70.0, "clear_tp": True}, "mutually exclusive"), ({}, "nothing to do")):
        out = br.request_bracket("prop-manual-cccccc", account_id="velotrade_1", apply=True, **kw)
        assert out["result"] == br.R_REFUSED and frag in out["detail"], (kw, out)
    assert br.request_bracket("prop-manual-cccccc", account_id="tradeify_1", tp=78.9)["result"] == br.R_REFUSED
    _ticket("prop-manual-dddddd", "velotrade_1", status="closed")
    assert br.request_bracket("prop-manual-dddddd", account_id="velotrade_1", tp=78.9)["result"] == br.R_REFUSED
    assert br.request_bracket("prop-manual-nope00", account_id="velotrade_1", tp=78.9)["result"] == br.R_REFUSED
    assert lri.tp_target_from(prop_journal.get_ticket("prop-manual-cccccc")["meta"]) is None


def test_a_tighter_sl_is_recorded_as_the_floor_the_trail_tightens_to():
    _ticket("prop-manual-eeeeee", "tradeify_1")        # SL is amendable on browser dxtrade
    r = br.request_bracket("prop-manual-eeeeee", account_id="tradeify_1", sl=88.5, apply=True)
    assert r["result"] == br.R_QUEUED
    assert lri.sl_floor_from(prop_journal.get_ticket("prop-manual-eeeeee")["meta"]) == 88.5


# ----------------------------------------------------------------- the trail applies a pinned TP

class _Adapter:
    TP_AMEND_SUPPORTED = True

    def __init__(self, tp=76.508):
        self.pos = Position(symbol="SOLUSD", side="short", quantity=6.8, entry_price=87.646,
                            stop_loss=89.105, take_profit=tp)
        self.calls: List[Any] = []

    def read_positions(self, page):
        return [Position(**self.pos.as_dict())]

    def read_quote(self, page, venue):
        return {"bid": 84.9, "ask": 84.92}

    def modify_bracket(self, page, position, stop_loss, take_profit, *, arm=False, rollout=None):
        self.calls.append((stop_loss, take_profit, arm))
        if arm and take_profit is not None:
            self.pos.take_profit = take_profit
        return {"ok": True, "clicked": arm, "why": "x"}


class _Api:
    def __init__(self, tp_target):
        self.tp_target, self.posted = tp_target, []

    def open_fills(self, account_id):
        return [{"ticket_id": "t1", "symbol": "SOLUSDT", "direction": "short", "status": "open"}]

    def all_tickets(self, account_id):
        return [{"ticket_id": "t1", "strategy": "leg", "entry": 87.64, "sl": 89.10464286,
                 "signal_time": SIG.isoformat(), "tp_target": self.tp_target}]

    def post_report(self, body):
        self.posted.append(body)
        return {"ok": True}


def _run(adapter, api, tmp_path, candles=None):
    cfg = ExecutorConfig(account_id="velotrade_1", enabled_venue_symbols=["SOLUSD"],
                         symbols={"SOLUSDT": {"venue": "SOLUSD", "price_step": 0.001}})
    # a leg that declares NO TP rule and NO structure exit: only the pin can move the TP
    leg = {"timeframe": "4h", "atr_stop_mult": 1.5, "trail_mult": 5.0, "decision_bar": "closed"}
    return pt.run_trail_step(adapter=adapter, page=None, api=api, cfg=cfg, mode="live", state_dir=tmp_path,
                             candles_fn=lambda s, tf: candles, now=SIG + timedelta(hours=8), legs={"leg": leg})


def test_the_trail_applies_a_pinned_tp_through_its_own_amend_and_reports_it(tmp_path):
    a, api = _Adapter(), _Api(78.964)
    res = _run(a, api, tmp_path)
    assert a.calls == [(None, pytest.approx(78.964), True)]          # TP only; the stop is untouched
    assert a.pos.take_profit == pytest.approx(78.964)
    assert [b["source"] for b in api.posted] == ["prop_trail_tp"] and api.posted[0]["tp"] == pytest.approx(78.964)
    assert not res.alerts


def test_a_pinned_tp_still_applies_when_the_candle_feed_is_corrupt(tmp_path):
    """PROP-TRAIL-BAD-CANDLE-EXT (#24936) skips every stop/target step off a corrupt feed. The corrupt SOL 4h low is
    in that feed until the trade closes; a pin reads no candles, so it must not be held hostage by it."""
    import pandas as pd
    rows = [{"timestamp": SIG + timedelta(hours=4 * i), "open": 86.0, "high": 87.0, "low": 85.0, "close": 86.0}
            for i in range(0, 2)]
    rows[0]["low"] = 22.93
    a = _Adapter()
    res = _run(a, _Api(78.964), tmp_path, candles=pd.DataFrame(rows))
    assert a.calls == [(None, pytest.approx(78.964), True)]          # the pin applied; the stop was not touched
    assert any("trail skipped" in x for x in res.alerts)             # the feed alert still fires


def test_no_pin_and_no_rule_leaves_the_tp_alone(tmp_path):
    a = _Adapter()
    _run(a, _Api(None), tmp_path)
    assert a.calls == []


def test_a_pin_through_the_price_or_beyond_the_cap_is_refused_and_alerted_once(tmp_path):
    for bad in (85.5, 60.0):                                          # above the ask / far past the 9.9% cap
        a = _Adapter()
        res = _run(a, _Api(bad), tmp_path)
        assert a.calls == [] and any("pinned TP" in x for x in res.alerts)


# ------------------------------------------------------------------ live_review_apply prop_vm

def _intent():
    return lri.LiveReviewIntent(order_package_id="pkg-X", action="move_tp", direction="short",
                                review_id="LR-1", new_sl=None, mark=84.9, atr=1.0, bar_ts="2026-11-11T20:00:00Z",
                                mandate=lri.MANDATE_ID, basis=lri.BASIS_TABLE, mechanics_verdict="match",
                                expected_cost_r=-0.1, worst_case_delta_r=0.4)


def test_live_review_prop_vm_move_tp_is_queued_for_velotrade_and_refused_for_tradeify():
    assert "move_tp" in lra.ACTION_PATHS["prop_vm"]          # close / reduce joined it (CAP-PROP-VM-CLOSE)
    _ticket("prop-manual-ffffff", "velotrade_1")
    _ticket("prop-manual-abcdef", "tradeify_1")

    class V:  # the verdict's level is all the executor reads
        level = 78.964
    ok = lra._exec_prop_vm_tp({"row": {"ticket_id": "prop-manual-ffffff", "account_id": "velotrade_1"}}, V, _intent())
    assert ok["result"] == lra.X_APPLIED
    no = lra._exec_prop_vm_tp({"row": {"ticket_id": "prop-manual-abcdef", "account_id": "tradeify_1"}}, V, _intent())
    assert no["result"] == lra.X_REFUSED and "TP_AMEND_SUPPORTED" in no["detail"]


def test_the_action_wrapper_resolves_the_runtime_journal_like_its_siblings():
    """Issue #25083: the first dry run said "ticket not readable in the prop journal" because the wrapper never loaded
    the runtime env (DATA_DIR / TRADE_JOURNAL_DB), so prop_journal opened a default path on the VM."""
    sh = (Path(__file__).resolve().parents[1] / "scripts/ops/amend_prop_bracket_action.sh").read_text()
    assert 'DB_PATH="$(runtime_db_path)"' in sh
    assert 'export TRADE_JOURNAL_DB="${DB_PATH}"' in sh
    assert sh.index("runtime_db_path") < sh.index('"${PY}" scripts/ops/amend_prop_bracket.py')
