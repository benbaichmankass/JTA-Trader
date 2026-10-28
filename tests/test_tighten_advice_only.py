"""Tightens are ADVICE ONLY (operator 2026-10-28 ~20:35Z, popup "Advice-only tightens (Recommended)").

Evidence: comms/research/ltr_tighten_optimize/verdict.json (LTR-TIGHTEN-OPTIMIZE; DESK-LIFECYCLE-S0, PR #20967).
A recommended tighten row is recorded and graded but NEVER dispatched, on any route and on all three automatic
paths (the VM rows watcher, the dispatcher and desk intake); every other trade action is unchanged.
These tests run with the production value of rows_lib.ADVICE_ONLY_ACTIONS (no patching).
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


def test_the_production_set_is_exactly_tighten_sl():
    assert rows_lib.ADVICE_ONLY_ACTIONS == ("tighten_sl",)
    assert rows_lib.ADVICE_ONLY_VERDICT == "tighten_advice_only"


# ------------------------------------------------------------------ VM rows watcher

@pytest.mark.parametrize("route", ["recommended", "auto_applied", "operator_ask"])
def test_watcher_never_dispatches_a_recommended_tighten_and_logs_it_as_advice(tmp_path, route):
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([trw.row("LR-t", action="tighten_sl", route=route)]),
               dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == []
    (rec,) = trw.log(tmp_path)
    assert rec["verdict"] == "tighten_advice_only" and rec["review_id"] == "LR-t"
    # seen once: the next pass does not re-log or send it
    w.run_pass(git=trw.FakeGit([trw.row("LR-t")]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == [] and len(trw.log(tmp_path)) == 1


def test_watcher_still_dispatches_a_recommended_close(tmp_path):
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([trw.row("LR-c", action="close"), trw.row("LR-t", action="tighten_sl")]),
               dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == [("LR-c", trw.TIP)]
    assert {r["review_id"]: r["verdict"] for r in trw.log(tmp_path)} == {"LR-c": "dispatched",
                                                                        "LR-t": "tighten_advice_only"}


# ------------------------------------------------------------------ dispatcher (incl. the manual system-action)

def test_dispatcher_refuses_a_tighten_as_advice_without_running_the_apply_or_pinging(world):  # noqa: F811
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "tighten_advice_only" and res["exit"] == d.EXIT_REFUSED
    assert world["calls"] == [] and world["pings"] == []


def test_dispatcher_still_hands_a_recommended_close_to_the_apply(world):  # noqa: F811
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

def test_desk_intake_records_a_tighten_as_advice_and_never_applies_it(tmp_path):
    tdi.seeded(tmp_path)
    a = tdi.FakeApply()
    tdi.run(tmp_path, [tdi.in_trade_row()], apply_fn=a)
    assert a.calls == []
    (rec,) = tdi.log(tmp_path)
    assert rec["verdict"] == "not_dispatchable" and rec["detail"] == "tighten_advice_only"
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
