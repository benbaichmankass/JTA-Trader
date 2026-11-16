"""LTR-MECHANICS-ROW-BLOCKS-DECISION (operator 2026-11-16): "even [if] there is a legitimate reason to not apply
on one account, it shouldn't prevent the decision from being applied on other accounts holding the same trade".

Mechanics is judged per ACCOUNT. A recommended action applies on every account whose mechanics match; only a
mismatched account is skipped and flagged with its reason; a by-design difference (an sl_only prop leg's TP,
#26220) is not a mismatch. Case: pkg-fe0c, where velotrade_1's by-design TP kept bybit_2/bybit_portfolio from
closing for ~8.5 h.
"""
from __future__ import annotations

import copy
import json

import pytest

from scripts.ops import live_review_apply as lra
from scripts.ops import live_review_dispatch as d
from scripts.ops import live_review_packet as pk
from src.runtime import live_review_intent as lri
from tests import test_live_review_apply as tla
from tests import test_live_review_dispatch as tld
from tests import test_live_review_trade_actions as tta
from tests.test_live_review_apply import wired  # noqa: F401  (fixture)
from tests.test_live_review_dispatch import world  # noqa: F401  (fixture)

RID = "LR-20261116T0832Z-pkg-fe0c"

CLOSE_ROW = {
    "review_id": RID, "order_package_id": "pkg-fe0c", "leg": "ml_entry",
    "accounts": ["bybit_2", "bybit_portfolio", "velotrade_1"],
    "mechanics": {"verdict": "mismatch", "evidence": "velotrade_1: venue TP 1777.97 != package TP 1740.38",
                  "per_account": {
                      "bybit_2": {"verdict": "match", "evidence": None},
                      "bybit_portfolio": {"verdict": "match", "evidence": None},
                      "velotrade_1": {"verdict": "mismatch", "evidence": "venue SL 1846.28 != package SL 1849.13"}}},
    "outcome_table_source": None, "packet_sha": "ab" * 32,
    "recommendation": {"action": "close", "reason": "ev +0.298R, n=256", "basis": "judgement",
                       "evidence_source": "judgement", "judgement_confidence": 0.7},
    "account_reads": [{"account_id": "bybit_2", "account_class": "real_money", "read": "would_apply", "evidence": "x"}],
    "disposition": {"route": "recommended", "mandate": None, "applied_at": None, "verified_readback": None},
}


def _set(world, row):  # noqa: F811
    world["files"][d.REVIEWS_PATH] = json.dumps(row) + "\n"


# ------------------------------------------------------------------ dispatch

def test_a_mixed_row_applies_on_the_matching_accounts_and_flags_the_skipped_one(world, capsys):  # noqa: F811
    _set(world, CLOSE_ROW)
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "dispatched"
    argv = world["calls"][0]
    pairs = dict(zip(argv[::2], argv[1::2]))
    assert pairs["--accounts"] == "bybit_2,bybit_portfolio" and pairs["--mechanics"] == "match"
    assert pairs["--action"] == "close" and "velotrade_1" not in pairs["--accounts"]
    assert list(res["mechanics_skipped"]) == ["velotrade_1"]
    assert "mechanics_mismatch" in res["mechanics_skipped"]["velotrade_1"]
    out = capsys.readouterr().out
    assert "SKIPPED velotrade_1" in out and "venue SL 1846.28" in out
    assert d.json.loads(d.DISPATCH_STATE.read_text())["dispatched"][RID]["mechanics_skipped"] == ["velotrade_1"]


def test_a_package_match_still_applies_everywhere_with_no_account_scope(world):  # noqa: F811
    row = copy.deepcopy(CLOSE_ROW)
    row["mechanics"] = {"verdict": "match", "evidence": "agree"}
    _set(world, row)
    d.dispatch(RID, apply=True)
    assert "--accounts" not in world["calls"][0]


@pytest.mark.parametrize("mech, clause", [
    ({"verdict": "mismatch", "evidence": "x"}, "mechanics_mismatch"),                       # legacy row, no per-account
    ({"verdict": "mismatch", "evidence": "x", "per_account": {
        "bybit_2": {"verdict": "mismatch"}, "velotrade_1": {"verdict": "could_not_look"}}}, "mechanics_mismatch"),
    ({"verdict": "could_not_look", "evidence": "x", "per_account": {}}, "mechanics_could_not_look"),
    ({"evidence": "x"}, "mechanics_unstated"),
])
def test_no_matching_account_is_still_a_refusal_and_nothing_is_sent(world, mech, clause):  # noqa: F811
    row = copy.deepcopy(CLOSE_ROW)
    row["mechanics"] = mech
    _set(world, row)
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "refused" and clause in res["detail"] and world["calls"] == []


def test_a_tighten_row_is_scoped_the_same_way(world):  # noqa: F811
    row = copy.deepcopy(tld.TABLE_ROW)
    row["review_id"] = tld.RID
    row["mechanics"] = {"verdict": "mismatch", "evidence": "x", "per_account": {
        "bybit_2": {"verdict": "match"}, "bybit_portfolio": {"verdict": "mismatch", "evidence": "TP differs"}}}
    world["files"][d.REVIEWS_PATH] = json.dumps(row) + "\n"
    d.dispatch(tld.RID, apply=True)
    argv = world["calls"][0]
    assert dict(zip(argv[::2], argv[1::2]))["--accounts"] == "bybit_2"


# ------------------------------------------------------------------ the apply honours the scope

def test_the_apply_acts_only_on_the_scoped_accounts_and_never_moves_the_shared_stop(wired, monkeypatch):  # noqa: F811
    done = []
    monkeypatch.setattr(lra, "_exec_trade_action",
                        lambda db, leg, pkg, cls, v, intent: done.append(leg["account_id"]) or {"result": lra.X_APPLIED})
    monkeypatch.setattr(lra, "_fresh_entry", lambda *a, **k: (True, "ok", 100.0))
    db = tla._ApplyDB([tta._tr(1, "bybit_2"), tta._tr(2, "alpaca_live")], tla.PKG)
    intent = tta._ti("close", account_scope=("bybit_2",))
    res = lra.run(intent, apply=True, db=db, accounts=tla.ACCOUNTS, strategies=tla.STRATS,
                  review_cfg={"apply_mode": "apply"}, granted={lri.TRADE_MANDATE_ID}, write_log=False, state={})
    assert done == ["bybit_2"]
    assert res["mechanics_scope"] == ["bybit_2"] and res["mechanics_skipped"] == ["alpaca_live"]
    assert [a["account_id"] for a in res["accounts"]] == ["bybit_2"] and res["package_sl_moved"] is False


def test_an_empty_scope_is_refused_before_any_account(wired, monkeypatch):  # noqa: F811
    monkeypatch.setattr(lra, "_exec_trade_action", lambda *a, **k: pytest.fail("must not act"))
    db = tla._ApplyDB([tta._tr(1, "bybit_2")], tla.PKG)
    res = lra.run(tta._ti("close", account_scope=("velotrade_1",)), apply=True, db=db, accounts=tla.ACCOUNTS,
                  strategies=tla.STRATS, review_cfg={"apply_mode": "apply"}, granted={lri.TRADE_MANDATE_ID},
                  write_log=False, state={})
    assert res["exit"] == lra.EXIT_REFUSED and "mechanics_scope_empty" in res["detail"]


# ------------------------------------------------------------------ by-design differences are not mismatches

POS = [{"symbol": "ETHUSDT", "direction": "short", "qty": 0.66, "sl": 1849.13, "tp": 1777.97}]


def test_an_sl_only_prop_legs_ticket_tp_is_by_design_not_a_mismatch():
    bad, ev, compared = pk._compare_prop_levels("velotrade_1", "ETHUSDT", "short", 1849.13, 1740.38, POS,
                                                ticket_tp=1777.97, tp_by_design=True)
    assert bad == 0 and compared == 2 and any("by design" in e and "#26220" in e for e in ev)


def test_a_prop_tp_that_is_neither_the_ticket_tp_nor_the_package_tp_is_still_a_mismatch():
    bad, ev, _ = pk._compare_prop_levels("velotrade_1", "ETHUSDT", "short", 1849.13, 1740.38, POS,
                                         ticket_tp=1760.0, tp_by_design=True)
    assert bad == 1 and any("TP" in e and "!=" in e for e in ev)
    bad, _, _ = pk._compare_prop_levels("velotrade_1", "ETHUSDT", "short", 1849.13, 1740.38, POS,
                                        ticket_tp=1777.97, tp_by_design=False)       # a leg that is not sl_only
    assert bad == 1


def test_an_sl_stop_difference_is_never_by_design():
    pos = [{**POS[0], "sl": 1846.28}]
    bad, ev, _ = pk._compare_prop_levels("velotrade_1", "ETHUSDT", "short", 1849.13, 1740.38, pos,
                                         ticket_tp=1777.97, tp_by_design=True)
    assert bad == 1 and any("SL" in e for e in ev)


def test_the_sl_only_declaration_is_read_from_the_leg_config():
    assert pk._sl_only_leg("ml_entry") is True            # structure_exit: "pivot=5;sl_only"
    assert pk._sl_only_leg("no_such_leg") is False and pk._sl_only_leg(None) is False
