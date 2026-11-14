"""Advice-only ENDED 2026-11-14: every in-trade class a reviewed row recommends is APPLIED.

Operator directive, manager chat 2026-11-14 ~09:25Z (relayed by Manager Session 2026-11-13a), verbatim "Just turn
on, like, no advice only. All those decisions should be implemented. And I should just get a ping when those changes
are implemented based on LTR lane". rows_lib.ADVICE_ONLY_ACTIONS and MD-TRADE-DESK functions.in_trade.advice_only
are both EMPTY; every class goes through the existing path (rows watcher / desk intake -> live_review_dispatch ->
live_review_apply -> each account's RiskManager), one ping per applied leg. The PRODUCTION tests below pin that.

History: advice-only from 2026-10-28 (popups "Advice-only tightens (Recommended)" / "Advice-only until tested",
row DESK-V1-MGMT-ADVICE-ONLY). The mechanism (the tuple, ADVICE_ONLY_VERDICT, every reader, the per-package and
per-account ltr_auto_apply exceptions) is kept, so the LEGACY tests below re-populate the tuple with the
``legacy_advice_only`` fixture and pin that the gate still works if a class is ever put back.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.ops import desk_intake as di
from scripts.ops import live_review_dispatch as d
from src.runtime import live_review_rows as rows_lib
from src.runtime import live_review_rows_watch as w
from tests import test_desk_intake as tdi
from tests import test_live_review_rows_watch as trw
from tests.test_live_review_dispatch import RID, TABLE_ROW, _set_row, world  # noqa: F401


IN_TRADE_CLASSES = ("tighten_sl", "widen_sl", "move_tp", "partial_close", "close", "change_size", "add_entry")


@pytest.fixture
def legacy_advice_only(monkeypatch):
    """The pre-2026-11-14 production value, for the tests that pin the (kept) gate mechanism."""
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", IN_TRADE_CLASSES)


# ------------------------------------------------------------------ PRODUCTION: advice-only ended 2026-11-14

def test_the_production_set_is_empty():
    assert rows_lib.ADVICE_ONLY_ACTIONS == ()
    assert rows_lib.ADVICE_ONLY_VERDICT == "advice_only"


def test_no_class_the_code_can_send_is_advice_only():
    assert set(IN_TRADE_CLASSES) <= set(w.DISPATCHABLE_ACTIONS)
    assert not set(w.DISPATCHABLE_ACTIONS) & set(rows_lib.ADVICE_ONLY_ACTIONS)
    assert not set(di.APPLY_ACTION.values()) & set(rows_lib.ADVICE_ONLY_ACTIONS)


@pytest.mark.parametrize("action", IN_TRADE_CLASSES)
def test_watcher_dispatches_every_class_on_a_recommended_row(tmp_path, action):
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([trw.row("LR-a", action=action)]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == [("LR-a", trw.TIP)]
    (rec,) = trw.log(tmp_path)
    assert rec["verdict"] == "dispatched"


@pytest.mark.parametrize("action", IN_TRADE_CLASSES)
def test_an_unscoped_package_is_dispatchable_with_the_production_file(action):
    """trw.row is pkg-1, which no ltr_auto_apply entry scopes: it no longer needs one."""
    assert w.dispatchable(trw.row("LR-u", action=action)) is None


def test_dispatcher_hands_a_tighten_to_the_apply_under_md_trade_desk(world):  # noqa: F811
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "dispatched" and world["calls"]


def test_dispatcher_hands_a_close_to_the_apply(world):  # noqa: F811
    row = copy.deepcopy(TABLE_ROW)
    row["recommendation"] = {"action": "close", "reason": "structure broke against the trade",
                             "evidence_source": "judgement", "basis": "judgement", "judgement_confidence": 0.6}
    _set_row(world, row)
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "dispatched"
    pairs = dict(zip(world["calls"][0][::2], world["calls"][0][1::2]))
    assert pairs["--action"] == "close" and pairs["--mandate"] == d.TRADE_MANDATE_ID


def test_desk_intake_no_longer_answers_advice_only(tmp_path):
    tdi.seeded(tmp_path)
    a = tdi.FakeApply()
    tdi.run(tmp_path, [tdi.in_trade_row()], apply_fn=a)
    (rec,) = tdi.log(tmp_path)
    assert rec["detail"] != "advice_only"


# ------------------------------------------------------------------ LEGACY: the kept gate, re-populated




@pytest.mark.parametrize("action", IN_TRADE_CLASSES)
def test_watcher_logs_every_class_as_advice(tmp_path, action, legacy_advice_only):
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([trw.row("LR-a", action=action)]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == []
    (rec,) = trw.log(tmp_path)
    assert rec["verdict"] == "advice_only"


# ------------------------------------------------------------------ VM rows watcher

@pytest.mark.parametrize("route", ["recommended", "auto_applied", "operator_ask"])
def test_watcher_never_dispatches_a_recommended_tighten_and_logs_it_as_advice(tmp_path, route, legacy_advice_only):
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([trw.row("LR-t", action="tighten_sl", route=route)]),
               dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == []
    (rec,) = trw.log(tmp_path)
    assert rec["verdict"] == "advice_only" and rec["review_id"] == "LR-t"
    # seen once: the next pass does not re-log or send it
    w.run_pass(git=trw.FakeGit([trw.row("LR-t")]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == [] and len(trw.log(tmp_path)) == 1


def test_watcher_dispatches_a_graduated_close(tmp_path, monkeypatch):
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", tuple(a for a in IN_TRADE_CLASSES if a != "close"))
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([trw.row("LR-c", action="close"), trw.row("LR-t", action="tighten_sl")]),
               dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == [("LR-c", trw.TIP)]
    assert {r["review_id"]: r["verdict"] for r in trw.log(tmp_path)} == {"LR-c": "dispatched",
                                                                        "LR-t": "advice_only"}


# ------------------------------------------------------------------ dispatcher (incl. the manual system-action)

def test_dispatcher_refuses_a_tighten_as_advice_without_running_the_apply_or_pinging(world, legacy_advice_only):  # noqa: F811
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "advice_only" and res["exit"] == d.EXIT_REFUSED
    assert world["calls"] == [] and world["pings"] == []


def test_dispatcher_refuses_an_ungraduated_close(world, legacy_advice_only):  # noqa: F811
    row = copy.deepcopy(TABLE_ROW)
    row["recommendation"] = {"action": "close", "reason": "structure broke against the trade",
                             "evidence_source": "judgement", "basis": "judgement", "judgement_confidence": 0.6}
    _set_row(world, row)
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "advice_only" and world["calls"] == [] and world["pings"] == []


def test_dispatcher_hands_a_graduated_close_to_the_apply(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", tuple(a for a in IN_TRADE_CLASSES if a != "close"))
    row = copy.deepcopy(TABLE_ROW)
    row["recommendation"] = {"action": "close", "reason": "structure broke against the trade",
                             "evidence_source": "judgement", "basis": "judgement", "judgement_confidence": 0.6}
    _set_row(world, row)
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "dispatched"
    argv = world["calls"][0]
    pairs = dict(zip(argv[::2], argv[1::2]))
    assert pairs["--action"] == "close" and pairs["--mandate"] == d.TRADE_MANDATE_ID


# ------------------------------------------------------------------ desk intake

def test_desk_intake_records_a_tighten_as_advice_and_never_applies_it(tmp_path, legacy_advice_only):
    tdi.seeded(tmp_path)
    a = tdi.FakeApply()
    tdi.run(tmp_path, [tdi.in_trade_row()], apply_fn=a)
    assert a.calls == []
    (rec,) = tdi.log(tmp_path)
    assert rec["verdict"] == "not_dispatchable" and rec["detail"] == "advice_only"
    assert di.APPLY_ACTION[("in_trade", "tighten_sl")] == "tighten_sl"   # still recognised, so it is graded


def test_rows_lib_is_the_one_switch(monkeypatch, tmp_path):
    """Reverting the decision is one value (or the commit): with an empty set the old tighten path returns."""
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", ())
    assert w.dispatchable(trw.row("LR-x")) is None


def test_the_mandate_records_the_same_advice_only_set_as_the_code():
    import yaml

    y = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "mandates.yaml").read_text())
    (desk,) = [m for m in y["mandates"] if m["id"] == "MD-TRADE-DESK"]
    assert tuple(desk["functions"]["in_trade"]["advice_only"]) == rows_lib.ADVICE_ONLY_ACTIONS


# ------------------------------------------------------------------ the only exception: a per-package auto mandate

def _mandates():
    import yaml

    return yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "mandates.yaml").read_text())


def test_every_exception_is_a_granted_single_package_or_paper_account_operator_mandate():
    """A package-scoped exception names ONE package and expires with it (MD-LTR-ADA-AUTO). An account-scoped
    one names only PAPER non-mirror accounts (MD-LTR-PAPER-AUTO, operator 2026-11-01) or PROP accounts
    (MD-LTR-PROP-AUTO, operator 2026-11-12 "Standing permission granted", de-risking classes only) in
    config/accounts.yaml: real money and the mirrors (paper_role portfolio) are never in an exception's scope."""
    import yaml

    from src.runtime import ltr_auto_mandate as am

    doc = _mandates()
    accts = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "accounts.yaml").read_text())
    accts = accts.get("accounts", accts)
    for m in am.active(doc):
        assert m.get("granted_by") and "operator" in str(m["granted_by"]) and str(m.get("source") or "").strip()
        assert m.get("parent") == "MD-TRADE-DESK"
        if m.get("package_scope") is not None:
            sc = m["package_scope"]
            assert str(sc["order_package_id"]).startswith("pkg-") and "*" not in str(sc["order_package_id"])
            assert m.get("expires_on_event")
        else:
            sc = m["account_scope"]
            assert sc["accounts"], m["id"]
            for aid in sc["accounts"]:
                cfg = accts.get(aid) or {}
                cls = str(cfg.get("account_class")).lower()
                assert cls in ("paper", "prop"), (m["id"], aid)
                if cls == "prop":   # prop: the operator granted the de-risking classes only (2026-11-12)
                    assert set(m["account_scope"]["actions"]) <= {"close", "partial_close", "tighten_sl"}, m["id"]
                # a Stage-2 mirror is account_class paper too: it is never in an exception's scope
                assert str(cfg.get("paper_role") or "").lower() != "portfolio", (m["id"], aid)
        assert set(sc["actions"]) <= set(rows_lib.ADVICE_ONLY_ACTIONS) | set(w.DISPATCHABLE_ACTIONS)
    # a proposal never lifts anything: only the granted list is read
    assert am.active({"mandates": [], "proposed": [m for m in am.active(doc)]}) == []


def test_the_global_set_is_unchanged_by_any_exception():
    """An exception never edits the global set; since 2026-11-14 that set (code and mandate) is empty."""
    from src.runtime import ltr_auto_mandate as am

    # MD-LTR-ADA-AUTO expired with its package (2026-10-29T10:47:53Z): no exception is active now
    assert not any(m.get("id") == "MD-LTR-ADA-AUTO" for m in am.active(_mandates()))
    assert rows_lib.ADVICE_ONLY_ACTIONS == ()
    test_the_mandate_records_the_same_advice_only_set_as_the_code()


@pytest.mark.parametrize("action", IN_TRADE_CLASSES)
def test_an_unscoped_package_stays_advice_only_under_the_legacy_set(tmp_path, action, legacy_advice_only):
    """trw.row is pkg-1, which no granted mandate scopes: advice only, against the real config/mandates.yaml."""
    from src.runtime import ltr_auto_mandate as am

    assert am.exception_for(trw.row("LR-u", action=action)) is None
    assert w.dispatchable(trw.row("LR-u", action=action)) == rows_lib.ADVICE_ONLY_VERDICT
