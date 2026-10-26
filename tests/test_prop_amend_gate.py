"""DESK-2-RISK-GATE: PropRiskManager.approve_amend / approve_action -- the firm's layer.

Each verdict state on a prop account: approve, refuse (DD headroom, leverage cap, human hold, a
bracket left missing), could_not_look (stale cushion, unreadable ruleset, unread leverage basis,
a cushion reader that raised). A tighten is never refused for the DD cushion or the daily-DD switch
(operator 2026-10-09: "keep open, block new").
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.coordinator import OrderPackage
from src.prop import prop_amend_gate as pag
from src.prop import prop_risk_gate as gate
from src.runtime import live_review_intent as lri
from src.units.accounts.prop_risk import PropRiskManager

_REPO = Path(__file__).resolve().parents[1]
JUDGE = dict(mandate=lri.TRADE_MANDATE_ID, basis=lri.BASIS_JUDGEMENT, confidence=0.6,
             reason="r", mechanics_verdict="match")
LIMITS = {"leverage_caps": {"BTCUSDT": 5, "default": 2}}


def _intent(action="tighten_sl", **kw):
    base = dict(order_package_id="P", action=action, direction="long", review_id="LR-1",
                new_sl=None, mark=100.0, atr=1.0, bar_ts="2026-10-26T20:00:00Z", min_buffer_atr=1.0, **JUDGE)
    if action == "tighten_sl":
        base["new_sl"] = 97.0
    base.update(kw)
    return lri.LiveReviewIntent(**base)


def _view(**kw):
    base = dict(account_id="tradeify_1", account_class="prop_vm", leg_sl=95.0, entry=98.0, leg_tp=110.0,
                position_size=2.0, fresh_ok=True, fresh_reason="ok", max_qty=10.0,
                extra={"symbol": "SOLUSDT"})
    base.update(kw)
    return lri.AmendAccountView(**base)


def _within(r):
    return gate.grade_ticket_risk(risk_usd=r, distance_to_dd_floor_usd=200.0,
                                  distance_to_daily_loss_usd=150.0, status_freshness="ok")


def _exceeds(r):
    return gate.grade_ticket_risk(risk_usd=r, distance_to_dd_floor_usd=200.0,
                                  distance_to_daily_loss_usd=5.0, status_freshness="ok")


def _stale(r):
    return gate.grade_ticket_risk(risk_usd=r, distance_to_dd_floor_usd=200.0, status_freshness="stale")


def _boom(r):
    raise AssertionError("the cushion must not be read for an action that does not add risk")


def _decide(intent, view=None, cushion=_within, limits=LIMITS, equity=5000.0):
    view = view or _view()
    base = (lri.decide_amend(intent, view, dry_run=False) if intent.action == "tighten_sl"
            else lri.decide_action(intent, view, dry_run=False))
    return pag.decide_prop(base, intent, view, limits=limits, cushion_for=cushion,
                           symbol=(view.extra or {}).get("symbol"), account_size_usd=5000.0, equity_usd=equity)


# ------------------------------------------------------------------ risk-reducing actions

def test_tighten_is_never_refused_for_the_dd_cushion():
    v = _decide(_intent(), cushion=_boom)
    assert v.verdict == lri.V_APPROVE and v.level == 97.0


@pytest.mark.parametrize("intent", [_intent("close"), _intent("partial_close", size_fraction=0.5),
                                    _intent("move_tp", new_tp=108.0)])
def test_reducing_and_tp_actions_never_read_the_cushion(intent):
    assert _decide(intent, cushion=_boom).verdict == lri.V_APPROVE


def test_base_refusal_and_could_not_look_pass_through_unchanged():
    loosen = _decide(_intent(new_sl=94.0))
    assert (loosen.verdict, loosen.reason) == (lri.V_REFUSE, lri.R_LOOSENS)
    unread = _decide(_intent(), _view(leg_sl=None))
    assert unread.verdict == lri.V_COULD_NOT_LOOK


def test_an_amend_that_would_leave_a_leg_without_a_bracket_is_refused():
    assert _decide(_intent("move_tp", new_tp=108.0), _view(leg_sl=None)).reason == f"{lri.R_BRACKETS}:sl"
    assert _decide(_intent("widen_sl", new_sl=94.0), _view(leg_tp=None)).reason == f"{lri.R_BRACKETS}:tp"


def test_a_humans_stop_is_never_fought():
    v = _decide(_intent(), _view(account_class="phone", extra={"human_hold": "sl 96.5 by hand"}))
    assert (v.verdict, v.reason) == (lri.V_REFUSE, pag.R_HUMAN_HOLD)


# ------------------------------------------------------------------ actions that add risk

def test_widen_within_the_cushion_is_approved():
    v = _decide(_intent("widen_sl", new_sl=94.0))      # adds (95-94) x 2 = $2
    assert v.verdict == lri.V_APPROVE and v.level == 94.0


def test_widen_refused_for_dd_headroom():
    v = _decide(_intent("widen_sl", new_sl=90.0), cushion=_exceeds)   # adds $10 >= $5 daily headroom
    assert (v.verdict, v.reason) == (lri.V_REFUSE, f"{pag.R_DD_HEADROOM}:daily_loss")


def test_a_stale_cushion_is_could_not_look_never_approve():
    v = _decide(_intent("widen_sl", new_sl=94.0), cushion=_stale)
    assert (v.verdict, v.reason) == (lri.V_COULD_NOT_LOOK, f"{lri.R_COULD_NOT_LOOK}:{pag.CNL_CUSHION}:stale")


def test_a_cushion_reader_that_raises_is_could_not_look():
    def bad(r):
        raise RuntimeError("db locked")
    v = _decide(_intent("widen_sl", new_sl=94.0), cushion=bad)
    assert v.verdict == lri.V_COULD_NOT_LOOK and v.reason.endswith("RuntimeError")


def test_add_refused_for_the_firms_leverage_cap():
    # SOLUSDT -> the default 2:1 cap on $5,000 = $10,000 notional; (2 + 1) units x $100 = $300 fits
    assert _decide(_intent("add_entry", size_fraction=0.5)).verdict == lri.V_APPROVE
    big = _view(position_size=100.0, max_qty=1000.0)      # (100 + 50) x $100 = $15,000 > $10,000
    v = _decide(_intent("add_entry", size_fraction=0.5), big)
    assert (v.verdict, v.reason) == (lri.V_REFUSE, f"{pag.R_LEVERAGE}:SOLUSDT")
    btc = _view(position_size=100.0, max_qty=1000.0, extra={"symbol": "BTCUSDT"})   # 5:1 -> $25,000
    roomy = lambda r: gate.grade_ticket_risk(risk_usd=r, distance_to_dd_floor_usd=1000.0,  # noqa: E731
                                             distance_to_daily_loss_usd=1000.0, status_freshness="ok")
    assert _decide(_intent("add_entry", size_fraction=0.5), btc, cushion=roomy).verdict == lri.V_APPROVE
    # the same add clears the cap but adds 50 x $5 = $250 against $150 left today: the cushion refuses it
    assert _decide(_intent("add_entry", size_fraction=0.5), btc).reason == f"{pag.R_DD_HEADROOM}:daily_loss"


def test_add_with_an_unreadable_ruleset_or_basis_is_could_not_look():
    assert _decide(_intent("add_entry", size_fraction=0.5), limits=None).reason == \
        f"{lri.R_COULD_NOT_LOOK}:{pag.CNL_RULESET}"
    v = pag.decide_prop(lri.decide_action(_intent("add_entry", size_fraction=0.5), _view(), dry_run=False),
                        _intent("add_entry", size_fraction=0.5), _view(), limits=LIMITS, cushion_for=_within,
                        symbol="SOLUSDT", account_size_usd=None, equity_usd=None)
    assert v.reason == f"{lri.R_COULD_NOT_LOOK}:{pag.CNL_LEVERAGE}"


def test_add_past_the_cushion_is_refused():
    v = _decide(_intent("add_entry", size_fraction=0.5), cushion=_exceeds)   # 1 unit x $5 to stop = $5
    assert (v.verdict, v.reason) == (lri.V_REFUSE, f"{pag.R_DD_HEADROOM}:daily_loss")


# ------------------------------------------------------------------ PropRiskManager wiring

def _prm(monkeypatch, cushion=_within, **cfg):
    base = {"account_state": "funded", "account_size_usd": 5000.0,
            "backtest_ruleset": "prop_rulesets/tradeify_247_1step.yaml",
            "risk": {"daily_dd_switch": {"armed": True}}}
    base.update(cfg)
    rm = PropRiskManager(base, account_name="")
    monkeypatch.setattr(rm, "amend_cushion", cushion)
    monkeypatch.setattr(rm, "_amend_equity", lambda: 5000.0)
    return rm


def test_prop_risk_manager_tighten_approved_while_the_daily_dd_switch_blocks(monkeypatch):
    rm = _prm(monkeypatch, cushion=_boom)
    monkeypatch.setattr(rm, "check_dd_switch", lambda: True)
    order = OrderPackage(strategy="s", symbol="SOLUSDT", direction="long", entry=100.0, sl=94.0, tp=110.0)
    ok, why, _ = rm.fresh_entry_check(order, 5000.0)
    assert ok is False and why == "DAILY_DD_SWITCH"          # new risk is blocked ...
    assert rm.approve_amend(_intent(), _view()).verdict == lri.V_APPROVE   # ... a tighten is not
    # and the widen the apply path would build from that fresh-entry check is refused
    v = rm.approve_action(_intent("widen_sl", new_sl=94.0), _view(fresh_ok=ok, fresh_reason=why))
    assert (v.verdict, v.reason) == (lri.V_REFUSE, "fresh_entry_check:DAILY_DD_SWITCH")


def test_prop_risk_manager_refuses_a_widen_for_dd_headroom(monkeypatch):
    rm = _prm(monkeypatch, cushion=_exceeds)
    v = rm.approve_action(_intent("widen_sl", new_sl=90.0), _view())
    assert (v.verdict, v.reason) == (lri.V_REFUSE, f"{pag.R_DD_HEADROOM}:daily_loss")


def test_prop_risk_manager_reads_the_firms_real_limits(monkeypatch):
    rm = _prm(monkeypatch)
    assert rm.firm_limits()["leverage_caps"]["BTCUSDT"] == 5
    assert _prm(monkeypatch, backtest_ruleset="prop_rulesets/does_not_exist.yaml").firm_limits() is None
    assert _prm(monkeypatch, backtest_ruleset=None).firm_limits() == {}


def test_every_prop_account_in_accounts_yaml_has_a_readable_ruleset():
    accounts = yaml.safe_load((_REPO / "config/accounts.yaml").read_text())["accounts"]
    props = {k: v for k, v in accounts.items()
             if isinstance(v, dict) and v.get("type") == "prop" and v.get("retired") is not True}
    assert props, "the population is empty: the probe found no prop account"
    for name, cfg in props.items():
        assert PropRiskManager(cfg, account_name="").firm_limits() is not None, name


def test_apply_path_passes_the_phone_hold_and_symbol():
    from scripts.ops import live_review_apply as lra
    leg = {"kind": "ticket", "row": {"meta": '{"phone_trail": {"human_hold": "by hand"}}'}}
    assert lra.leg_extra(leg, {"symbol": "ETHUSDT"}) == {"symbol": "ETHUSDT", "human_hold": "by hand"}
    assert lra.leg_extra({"kind": "trade", "row": {}}, {"symbol": "X"}) == {"symbol": "X"}
