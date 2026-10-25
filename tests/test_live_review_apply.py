"""LTR-6R-APPLY-PATH: a package-level live-review intent, decided PER ACCOUNT.

Operator structural directive 2026-10-25: the review acts at the order-package
level and never does per-account risk management; every action goes through
EACH account's own RiskManager (``approve_amend``) and that account's own
executor. These tests pin the decision (tighten-only, noise floor + clip, one
amend per bar, shadow, dry-run, the daily-DD switch, could-not-look), the
``apply_mode`` selector, the per-leg ``sl_floor`` the monitor and the prop
trail respect, and the per-account apply with its read-only dry-run CLI.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pandas as pd
import pytest

from src.runtime import live_review_intent as lri
from src.runtime import order_monitor as om
from src.units.accounts.risk import RiskManager


def _intent(**kw) -> lri.LiveReviewIntent:
    base = dict(order_package_id="P", action="tighten_sl", direction="short", review_id="LR-20261025T2000Z-P",
                new_sl=0.2100, mark=0.2000, atr=0.0040, bar_ts="2026-10-25T18:00:00Z", min_buffer_atr=1.0,
                mandate=lri.MANDATE_ID, evidence_path="comms/live_review/tables/x.json")
    base.update(kw)
    return lri.LiveReviewIntent(**base)


def _view(**kw) -> lri.AmendAccountView:
    base = dict(account_id="bybit_2", account_class="bybit", leg_sl=0.2200)
    base.update(kw)
    return lri.AmendAccountView(**base)


def _decide(intent=None, view=None, *, dry_run=False, own=None):
    return lri.decide_amend(intent or _intent(), view or _view(), dry_run=dry_run,
                            account_min_buffer_atr=own)


# ------------------------------------------------------------------ decision

def test_a_tighten_inside_bounds_is_approved():
    v = _decide()
    assert (v.verdict, v.level, v.reason) == ("approve", 0.2100, "within_bounds")


def test_a_loosening_attempt_is_refused():
    v = _decide(_intent(new_sl=0.2300))            # short: above the 0.22 stop = looser
    assert (v.verdict, v.reason) == ("refuse", lri.R_LOOSENS)
    long_ = _decide(_intent(direction="long", new_sl=0.1700, mark=0.2000), _view(leg_sl=0.1800))
    assert (long_.verdict, long_.reason) == ("refuse", lri.R_LOOSENS)


def test_looser_than_the_resting_venue_stop_is_refused_even_if_tighter_than_the_journal():
    v = _decide(view=_view(leg_sl=0.2200, venue_sl=0.2050))
    assert (v.verdict, v.reason) == ("refuse", lri.R_LOOSENS)


def test_inside_the_noise_floor_is_clipped_to_the_floor():
    # floor = mark + 1.0 x ATR = 0.2040; asked 0.2010 is inside it
    v = _decide(_intent(new_sl=0.2010))
    assert v.verdict == "clip"
    assert v.level == pytest.approx(0.2040)
    assert v.reason.startswith("clipped_to_noise_floor")


def test_an_account_may_only_make_the_floor_stricter():
    v = _decide(_intent(new_sl=0.2100), own=3.0)    # own floor = 0.2120 → clip
    assert v.verdict == "clip" and v.level == pytest.approx(0.2120)
    loose_own = _decide(_intent(new_sl=0.2100), own=0.1)   # cannot loosen the intent's 1.0
    assert loose_own.verdict == "approve"


def test_clip_that_would_not_tighten_this_account_is_refused():
    v = _decide(_intent(new_sl=0.2010), _view(leg_sl=0.2030))   # floor 0.2040 is looser than 0.2030
    assert (v.verdict, v.reason) == ("refuse", lri.R_NOISE_FLOOR)


def test_a_shadow_leg_takes_no_action():
    v = _decide(view=_view(strategy_execution="shadow"))
    assert (v.verdict, v.reason) == ("refuse", lri.R_SHADOW)
    assert lri.account_read(v) == "no_action"


def test_dry_run_account_and_non_tighten_actions_refuse():
    assert _decide(dry_run=True).reason == lri.R_DRY
    assert _decide(_intent(action="flag")).reason == lri.R_NOT_TIGHTEN
    assert _decide(_intent(action="no_action")).reason == lri.R_NOT_TIGHTEN


def test_one_amend_per_package_per_closed_bar():
    v = _decide(view=_view(last_amend_bar="2026-10-25T18:00:00Z"))
    assert (v.verdict, v.reason) == ("refuse", lri.R_RATE)
    assert _decide(view=_view(last_amend_bar="2026-10-25T16:00:00Z")).verdict == "approve"


def test_wrong_side_of_mark_refuses_and_already_tighter_is_no_action():
    assert _decide(_intent(new_sl=0.1990)).reason == lri.R_WRONG_SIDE
    v = _decide(view=_view(leg_sl=0.2100))
    assert v.reason == lri.R_ALREADY and lri.account_read(v) == "no_action"


@pytest.mark.parametrize("kw", [{"intent": {"mark": None}}, {"intent": {"atr": None}}, {"view": {"leg_sl": None}}])
def test_a_failed_read_is_could_not_look_never_refuse_or_approve(kw):
    v = _decide(_intent(**kw.get("intent", {})), _view(**kw.get("view", {})))
    assert v.verdict == lri.V_COULD_NOT_LOOK and v.level is None and not v.ok
    assert v.reason.startswith(lri.R_COULD_NOT_LOOK)
    assert lri.account_read(v) == "unknown"
    assert set(lri.VERDICTS) == {"approve", "clip", "refuse", "could_not_look"}


def test_probe_with_unread_market_is_could_not_look_naming_the_missing_fields():
    for kw, want in (({"mark": None, "atr": None}, "mark,atr"), ({"atr": None}, "atr"), ({"mark": None}, "mark")):
        v = _decide(_intent(new_sl=None, **kw))
        assert v.verdict == lri.V_COULD_NOT_LOOK, v
        assert v.reason == f"{lri.R_COULD_NOT_LOOK}:{want}"
        assert lri.account_read(v) == "unknown"


def test_malformed_intent_stays_bad_input():
    assert _decide(_intent(direction="sideways")).reason == lri.R_BAD_INPUT
    assert _decide(_intent(direction="sideways", mark=None)).reason == lri.R_BAD_INPUT
    # an explicit level that will not parse is malformed even if the market read failed
    v = _decide(_intent(new_sl="not-a-number", mark=None))
    assert (v.verdict, v.reason) == ("refuse", lri.R_BAD_INPUT)
    # no level and a good market read is not a read failure either
    assert _decide(_intent(new_sl=None)).reason == lri.R_BAD_INPUT


def test_candle_fetch_uses_a_dedicated_ib_client_id_disjoint_from_the_others():
    from pathlib import Path

    import yaml

    from scripts.ops import live_review_apply as lra

    cid = int(lra.LIVE_REVIEW_IB_MD_CLIENT_ID)
    accts = yaml.safe_load(Path("config/accounts.yaml").read_text())["accounts"]
    used = {600}  # web-api candle fetcher (src/web/api/routers/candles.py)
    for cfg in accts.values():
        if isinstance(cfg, dict) and cfg.get("ib_client_id") is not None:
            base = int(cfg["ib_client_id"])
            used |= {base, base + 1} | {base + 100 * k for k in range(6)}
    assert cid not in used


def test_candles_pass_the_dedicated_client_id_to_the_connector(monkeypatch):
    from scripts.ops import live_review_apply as lra
    from src.runtime import market_data as md

    seen = {}
    monkeypatch.setattr(md, "connector_for_symbol", lambda sym, settings=None: seen.update(s=settings) or "C")
    monkeypatch.setattr(md, "fetch_candles", lambda *a, **k: seen.update(client=k.get("exchange_client")) or [])
    lra._candles("MGC", "1d")
    assert seen["s"] == {"IB_MD_CLIENT_ID": lra.LIVE_REVIEW_IB_MD_CLIENT_ID} and seen["client"] == "C"


# --------------------------------------------------- RiskManager.approve_amend

class _Switch:
    def __init__(self, armed, tripped, read="ok"):
        self.cfg = type("C", (), {"armed": armed})()
        self._t, self._r = tripped, read
        self.observed = 0

    def blocks_new_entries(self, row=None, now=None):
        return self._t

    def status(self, row=None):
        return {"read_state": self._r}

    def observe(self, *a, **k):            # pragma: no cover — must NOT be called
        self.observed += 1


def _rm(switch=None, dry=False, **risk):
    rm = RiskManager(dict(risk), dry_run=dry, account_id="")
    if switch is not None:
        rm.dd_switch = switch
    return rm


def test_a_tripped_dd_switch_does_not_refuse_a_tighten():
    """Manager decision 2026-10-25: a tighten only reduces risk; the switch
    refuses NEW ENTRIES (evaluate(..., opening=False) semantics)."""
    for sw in (_Switch(armed=True, tripped=True), _Switch(armed=True, tripped=False, read="could_not_look")):
        v = _rm(sw).approve_amend(_intent(), _view())
        assert (v.verdict, v.level) == ("approve", 0.2100)
        assert sw.observed == 0


def test_risk_manager_dry_run_and_own_buffer():
    assert _rm(_Switch(False, False), dry=True).approve_amend(_intent(), _view()).reason == lri.R_DRY
    v = _rm(_Switch(False, False), live_review_min_buffer_atr=3.0).approve_amend(_intent(), _view())
    assert v.verdict == "clip" and v.level == pytest.approx(0.2120)


def test_prop_risk_manager_inherits_approve_amend():
    from src.units.accounts.prop_risk import PropRiskManager

    rm = PropRiskManager({"risk": {}, "account_size_usd": 5000}, account_name=None)
    rm.dd_switch = _Switch(armed=True, tripped=True)
    assert rm.approve_amend(_intent(), _view(account_id="tradeify_1")).verdict == "approve"


# ----------------------------------------------------------------- apply_mode

def test_apply_mode_defaults_overrides_and_unknown_spelling():
    assert lri.apply_mode_for("bybit_2", {}) == "recommend"
    cfg = {"apply_mode": "apply", "accounts": {"bybit_portfolio": {"apply_mode": "off"}}}
    assert lri.apply_mode_for("bybit_2", cfg) == "apply"
    assert lri.apply_mode_for("bybit_portfolio", cfg) == "off"
    assert lri.apply_mode_for("x", {"apply_mode": "yes please"}) == "recommend"


def test_missing_config_reads_recommend(tmp_path):
    assert lri.apply_mode_for("bybit_2", lri.load_config(tmp_path / "absent.yaml")) == "recommend"


def test_committed_config_is_recommend_not_apply():
    """Only an operator commit may set apply (dispatch: do not set apply_mode: apply)."""
    cfg = lri.load_config()
    assert cfg.get("apply_mode") == "recommend"
    assert all((v or {}).get("apply_mode") != "apply" for v in (cfg.get("accounts") or {}).values())
    assert lri.min_buffer_atr_from(cfg) == 1.0


# ------------------------------------------------- per-leg floor: the monitor

def test_floor_helpers():
    assert lri.sl_floor_from(json.dumps({"sl_floor": {"level": 0.21}})) == 0.21
    assert lri.sl_floor_from({"sl_floor": 0.21}) == 0.21
    assert lri.sl_floor_from("not json") is None and lri.sl_floor_from({}) is None
    assert lri.floor_blocks("short", 0.2150, 0.2100) is True      # looser than floor
    assert lri.floor_blocks("short", 0.2050, 0.2100) is False     # tighter: trail may go on
    assert lri.floor_blocks("long", 0.1900, 0.1950) is True
    assert lri.floor_blocks("short", 0.2150, None) is False


class _MonDB:
    def __init__(self, trades):
        self.trades, self.package_writes, self.trade_writes = trades, [], []

    def get_trades(self, filters=None, limit=None):
        rows = self.trades
        for k, v in (filters or {}).items():
            rows = [r for r in rows if str(r.get(k)) == str(v)]
        return [dict(r) for r in rows]

    def update_order_package(self, pkg_id, updates):
        self.package_writes.append({"pkg": pkg_id, **updates})

    def update_trade(self, trade_id, updates):
        self.trade_writes.append((trade_id, updates))


def _mleg(tid, account, sl, notes=None):
    return {"id": tid, "account_id": account, "order_package_id": "P", "status": "open", "stop_loss": sl,
            "position_size": 1.0, "symbol": "XRPUSDT", "direction": "short",
            "strategy_name": "xrp_pullback_2h", "is_backtest": 0, "notes": notes}


def test_monitor_never_trails_a_floored_leg_looser(monkeypatch):
    floored = _mleg(1, "bybit_2", 0.2100, json.dumps({"sl_floor": {"level": 0.2100}}))
    db = _MonDB([floored, _mleg(2, "bybit_portfolio", 0.2200)])
    seen = []
    monkeypatch.setattr(om, "_send_modify_to_exchange",
                        lambda trade, **kw: seen.append((trade["account_id"], kw.get("sl"))) or {"ok": True})
    monkeypatch.setattr(om, "_note_unsupported_management_op", lambda **kw: None)
    pkg = {"order_package_id": "P", "linked_trade_id": 1, "status": "open", "sl": 0.2200, "tp": 0.19,
           "strategy_name": "xrp_pullback_2h", "symbol": "XRPUSDT"}
    om._apply_update(db, pkg, {"sl": 0.2150}, om._StrategyTickSummary())
    assert seen == [("bybit_portfolio", 0.2150)]              # the floored leg got no SL modify
    assert [t for t, _ in db.trade_writes] == [2]              # its stored stop is untouched
    assert [w.get("sl") for w in db.package_writes] == [0.2150]   # the trail still advances the package


def test_monitor_trails_a_floored_leg_once_the_candidate_is_tighter(monkeypatch):
    db = _MonDB([_mleg(1, "bybit_2", 0.2100, json.dumps({"sl_floor": {"level": 0.2100}}))])
    seen = []
    monkeypatch.setattr(om, "_send_modify_to_exchange",
                        lambda trade, **kw: seen.append(kw.get("sl")) or {"ok": True})
    pkg = {"order_package_id": "P", "linked_trade_id": 1, "status": "open", "sl": 0.2200, "tp": 0.19,
           "strategy_name": "xrp_pullback_2h", "symbol": "XRPUSDT"}
    om._apply_update(db, pkg, {"sl": 0.2050}, om._StrategyTickSummary())
    assert seen == [0.2050]


# ------------------------------------------------ per-leg floor: prop trail

def _candles(n=10, start=None, px=100.0):
    start = start or datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)
    rows = [{"timestamp": start + timedelta(hours=i), "open": px, "high": px + 1, "low": px - 1, "close": px}
            for i in range(n)]
    return pd.DataFrame(rows)


def test_prop_trail_tightens_to_the_floor_and_never_plans_looser():
    from src.prop import prop_trail

    leg = {"trail_mult": 5.0, "atr_stop_mult": 2.0, "timeframe": "1h", "decision_bar": "closed"}
    kw = dict(leg=leg, direction="short", entry=100.0, initial_sl=104.0,
              signal_time=datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc), resting_sl=104.0,
              candles=_candles(), now=datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc))
    base = prop_trail.plan_trail(**kw)
    assert base.action == "hold"                       # the replay alone does not tighten
    floored = prop_trail.plan_trail(**kw, sl_floor=102.5)
    assert floored.action == "tighten" and floored.sl == pytest.approx(102.5)
    assert floored.detail.get("sl_floor") == 102.5
    looser_floor = prop_trail.plan_trail(**kw, sl_floor=110.0)   # a looser floor changes nothing
    assert looser_floor.action == base.action and looser_floor.replay_sl == base.replay_sl


# -------------------------------------------------- per-account apply (run)

from scripts.ops import live_review_apply as lra  # noqa: E402


class _ApplyDB(_MonDB):
    def __init__(self, trades, pkg):
        super().__init__(trades)
        self.pkg = pkg


def _trade(tid, account, sl=0.2200):
    return {"id": tid, "account_id": account, "order_package_id": "P", "status": "open", "stop_loss": sl,
            "position_size": 10.0, "symbol": "ADAUSDT", "direction": "short", "is_backtest": 0,
            "notes": None, "sl_order_id": f"o{tid}"}


PKG = {"order_package_id": "P", "status": "open", "strategy_name": "ada_pullback_2h", "symbol": "ADAUSDT",
       "direction": "short", "sl": 0.2200, "tp": 0.1900}
ACCOUNTS = {"bybit_2": {"exchange": "bybit", "mode": "live", "account_class": "real_money", "risk": {}},
            "bybit_portfolio": {"exchange": "bybit", "mode": "live", "risk": {}},
            "alpaca_live": {"exchange": "alpaca", "mode": "live", "risk": {}},
            "tradeify_1": {"exchange": "breakout", "type": "prop", "mode": "live", "risk": {}},
            "breakout_2": {"exchange": "breakout", "type": "prop", "mode": "live", "risk": {}}}
STRATS = {"ada_pullback_2h": {"execution": "live", "timeframe": "2h"}}


@pytest.fixture
def wired(monkeypatch):
    """Every seam faked: no DB file, no venue, no prop journal."""
    state: Dict[str, Any] = {"tickets": [], "dry": set(), "buffers": {}, "exec": [], "pings": [],
                             "alerts": [], "bybit_result": None}
    monkeypatch.setattr(lra, "_get_package", lambda db, pid: dict(db.pkg) if pid == "P" else None)
    monkeypatch.setattr(lra, "_prop_tickets", lambda pid: [dict(t) for t in state["tickets"]])
    monkeypatch.setattr(lra, "_is_phone", lambda aid: aid == "breakout_2")

    def _rm(aid, cfg):
        risk = {"live_review_min_buffer_atr": state["buffers"][aid]} if aid in state["buffers"] else {}
        rm = RiskManager(risk, dry_run=aid in state["dry"], account_id="")
        rm.dd_switch = _Switch(armed=True, tripped=True)   # tripped everywhere: must not matter
        return rm
    monkeypatch.setattr(lra, "_risk_manager", _rm)

    def _bybit(db, leg, pkg, level, intent):
        state["exec"].append(("bybit", leg["account_id"], level))
        if state["bybit_result"]:
            return dict(state["bybit_result"])
        db.update_trade(int(leg["row"]["id"]), {"stop_loss": level, "notes": json.dumps(
            {"sl_floor": {"level": level}})})
        return {"result": "applied", "venue_after": level}
    monkeypatch.setattr(lra, "_exec_bybit", _bybit)
    monkeypatch.setattr(lra, "_exec_prop_vm",
                        lambda leg, level, intent: state["exec"].append(("prop_vm", leg["account_id"], level))
                        or {"result": lra.X_APPLIED})
    monkeypatch.setattr(lra, "_exec_phone",
                        lambda leg, level, intent: state["exec"].append(("phone", leg["account_id"], level))
                        or {"result": lra.X_APPLIED, "amend_id": "t#a1"})
    monkeypatch.setattr(lra, "_ping", lambda pkg, aid, level, intent: state["pings"].append((aid, level)))
    monkeypatch.setattr(lra, "_alert", lambda pkg, aid, line: state["alerts"].append((aid, line)))
    return state


def _run(db, wired, *, mode="apply", apply=True, granted=frozenset({lri.MANDATE_ID}), state=None, **ikw):
    return lra.run(_intent(**ikw), apply=apply, db=db, accounts=ACCOUNTS, strategies=STRATS,
                   review_cfg={"apply_mode": mode}, granted=set(granted), write_log=False,
                   state=state if state is not None else {})


def test_every_account_decides_for_itself_and_the_package_stop_holds(wired):
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    wired["dry"].add("bybit_portfolio")
    res = _run(db, wired)
    by = {a["account_id"]: a for a in res["accounts"]}
    assert by["bybit_2"]["verdict"] == "approve" and by["bybit_2"]["executed"] is True
    assert by["bybit_portfolio"]["reason"] == lri.R_DRY and not by["bybit_portfolio"].get("executed")
    assert wired["exec"] == [("bybit", "bybit_2", 0.2100)]           # the refusing account's leg is never touched
    assert res["package_sl_moved"] is False and db.package_writes == []   # siblings disagree → floors, not the shared stop
    assert wired["pings"] == [("bybit_2", 0.2100)]
    reads = {r["account_id"]: r["read"] for r in res["writeback"]["account_reads"]}
    assert reads == {"bybit_2": "would_apply", "bybit_portfolio": "refused_by_account_risk"}


def test_a_clip_on_one_account_never_reaches_another_accounts_leg(wired, monkeypatch):
    """Account-scoped execution (desk design § 3.0): bybit_portfolio's own
    stricter floor clips it to 0.2120 while bybit_2 applies 0.2100. Each leg
    gets ITS level, the shared package stop does not move, and the order
    monitor then holds each leg at its own applied level."""
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    wired["buffers"]["bybit_portfolio"] = 3.0
    res = _run(db, wired)
    assert sorted(wired["exec"]) == [("bybit", "bybit_2", 0.2100), ("bybit", "bybit_portfolio", pytest.approx(0.2120))]
    assert res["package_sl_moved"] is False and db.package_writes == []
    floors = {t: json.loads(u["notes"])["sl_floor"]["level"] for t, u in db.trade_writes}
    assert floors == {1: 0.2100, 2: pytest.approx(0.2120)}
    # the next trail candidate (0.2110) reaches only bybit_portfolio: it is looser than bybit_2's 0.2100
    legs = [{**_mleg(1, "bybit_2", 0.2100, json.dumps({"sl_floor": {"level": 0.2100}})), "symbol": "ADAUSDT"},
            {**_mleg(2, "bybit_portfolio", 0.2120, json.dumps({"sl_floor": {"level": 0.2120}})), "symbol": "ADAUSDT"}]
    mdb = _MonDB(legs)
    seen = []
    monkeypatch.setattr(om, "_send_modify_to_exchange",
                        lambda trade, **kw: seen.append((trade["account_id"], kw.get("sl"))) or {"ok": True})
    om._apply_update(mdb, {**PKG, "linked_trade_id": 1}, {"sl": 0.2110}, om._StrategyTickSummary())
    assert seen == [("bybit_portfolio", 0.2110)]
    assert res["writeback"]["disposition"]["route"] == "auto_applied"
    assert res["writeback"]["disposition"]["mandate"] == lri.MANDATE_ID


def test_when_every_trade_leg_agrees_the_shared_package_stop_moves(wired):
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    res = _run(db, wired)
    assert res["package_sl_moved"] is True and db.package_writes == [{"pkg": "P", "sl": 0.2100}]


def test_account_types_route_to_their_own_executors(wired):
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(3, "alpaca_live")], PKG)
    wired["tickets"] = [
        {"ticket_id": "tk1", "account_id": "tradeify_1", "order_package_id": "P", "status": "filled",
         "sl": 0.2200, "meta": None},
        {"ticket_id": "tk2", "account_id": "breakout_2", "order_package_id": "P", "status": "filled",
         "sl": 0.2200, "meta": json.dumps({"phone_trail": {"resting_sl": 0.2180}})}]
    res = _run(db, wired)
    by = {a["account_id"]: a for a in res["accounts"]}
    assert by["alpaca_live"]["reason"] == lri.R_NO_PATH and by["alpaca_live"]["read"] == "no_action"
    assert by["tradeify_1"]["account_class"] == "prop_vm" and by["tradeify_1"]["executed"] is True
    assert by["breakout_2"]["account_class"] == "phone" and by["breakout_2"]["executed"] is True
    assert sorted(e[0] for e in wired["exec"]) == ["bybit", "phone", "prop_vm"]
    assert res["package_sl_moved"] is False        # the alpaca trade leg did not apply


def test_recommend_mode_computes_but_never_executes(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    res = _run(db, wired, mode="recommend")
    assert res["accounts"][0]["verdict"] == "approve" and wired["exec"] == [] and db.trade_writes == []
    assert res["writeback"]["disposition"]["route"] == "recommended"


def test_apply_without_a_granted_mandate_is_refused(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    res = _run(db, wired, granted=frozenset())
    assert wired["exec"] == [] and res["exit"] == lra.EXIT_REFUSED
    assert "not granted" in res["accounts"][0]["executor"]["detail"]


def test_off_mode_and_shadow_leg_take_no_action(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    assert _run(db, wired, mode="off")["accounts"][0]["reason"] == lri.R_APPLY_OFF
    shadow = lra.run(_intent(), apply=True, db=db, accounts=ACCOUNTS,
                     strategies={"ada_pullback_2h": {"execution": "shadow"}},
                     review_cfg={"apply_mode": "apply"}, granted={lri.MANDATE_ID}, write_log=False)
    assert shadow["accounts"][0]["reason"] == lri.R_SHADOW and wired["exec"] == []


def test_a_loosening_intent_is_refused_on_every_account(wired):
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    res = _run(db, wired, new_sl=0.2300)
    assert {a["reason"] for a in res["accounts"]} == {lri.R_LOOSENS}
    assert wired["exec"] == [] and db.package_writes == []


def test_a_clip_is_applied_at_the_clipped_level(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    res = _run(db, wired, new_sl=0.2010)
    assert res["accounts"][0]["verdict"] == "clip"
    assert wired["exec"][0][2] == pytest.approx(0.2040)


def test_dry_run_cli_prints_every_account_and_writes_nothing(wired, monkeypatch, capsys):
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    wired["dry"].add("bybit_portfolio")
    monkeypatch.setattr(lra, "_open_db", lambda: db)
    monkeypatch.setattr(lra, "_open_packages", lambda d: [dict(PKG)])
    monkeypatch.setattr(lra, "_accounts", lambda: ACCOUNTS)
    monkeypatch.setattr(lra, "_strategies", lambda: STRATS)
    monkeypatch.setattr(lra, "market_state",
                        lambda pkg, s: {"mark": 0.2000, "atr": 0.0040, "bar_ts": "b1", "timeframe": "2h"})
    monkeypatch.setattr(lri, "load_config", lambda path=None: {"apply_mode": "recommend", "min_buffer_atr": 1.0})
    rc = lra.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert ">>> P ada_pullback_2h bybit_2 [bybit/recommend]: approve" in out      # probe at the floor
    assert ">>> P ada_pullback_2h bybit_portfolio [bybit/recommend]: refuse None — account_mode_dry_run" in out
    assert wired["exec"] == [] and db.trade_writes == [] and db.package_writes == []


def test_apply_cli_refuses_without_the_full_evidence_set(capsys):
    assert lra.main(["--apply", "--package", "P", "--new-sl", "0.21"]) == lra.EXIT_REFUSED
    assert lra.main(["--apply", "--dry-run"]) == lra.EXIT_REFUSED


def test_atr_from_candles():
    c = _candles(20)
    assert lra.atr_from_candles(c) == pytest.approx(2.0)
    assert lra.atr_from_candles(pd.DataFrame()) is None


# ------------------------------------------- could_not_look, readback, pings

def test_could_not_look_retries_every_cycle_and_flags_once_after_three(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    wired["bybit_result"] = {"result": lra.X_COULD_NOT_LOOK, "detail": "venue read read_failed"}
    st: Dict[str, Any] = {}
    for cycle in range(1, 6):
        res = _run(db, wired, state=st)
        rec = res["accounts"][0]
        assert rec["verdict"] == lri.V_COULD_NOT_LOOK and rec["read"] == "unknown"
        assert rec["could_not_look_streak"] == cycle
        assert res["exit"] == lra.EXIT_UNREADABLE
    assert len(wired["exec"]) == 5                       # retried every cycle: no halting
    assert len(wired["alerts"]) == 1 and "3 cycles" in wired["alerts"][0][1]
    assert db.trade_writes == [] and db.package_writes == []
    wired["bybit_result"] = None                         # the read recovers
    res = _run(db, wired, state=st)
    assert res["accounts"][0]["executed"] is True and "P|bybit_2" not in st["could_not_look"]


def test_readback_mismatch_is_apply_failed_and_pings_once(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    wired["bybit_result"] = {"result": lra.X_APPLY_FAILED, "detail": "venue reads 0.22 after the amend"}
    st: Dict[str, Any] = {}
    for _ in range(3):
        res = _run(db, wired, state=st)
        assert res["accounts"][0]["executed"] is False and res["exit"] == lra.EXIT_FAILED
    assert len(wired["alerts"]) == 1 and "apply_failed" in wired["alerts"][0][1]
    assert wired["pings"] == [] and db.package_writes == []


def test_a_refusal_on_a_real_money_account_pings_once_paper_never(wired):
    accounts = {**ACCOUNTS, "bybit_2": {**ACCOUNTS["bybit_2"], "account_class": "real_money"},
                "bybit_portfolio": {**ACCOUNTS["bybit_portfolio"], "account_class": "paper"}}
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    wired["dry"].update({"bybit_2", "bybit_portfolio"})
    st: Dict[str, Any] = {}
    for _ in range(2):
        lra.run(_intent(), apply=True, db=db, accounts=accounts, strategies=STRATS,
                review_cfg={"apply_mode": "apply"}, granted={lri.MANDATE_ID}, write_log=False, state=st)
    assert [a for a, _ in wired["alerts"]] == ["bybit_2"]


def test_recommend_runs_never_ping_or_count_streaks(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    st: Dict[str, Any] = {}
    res = _run(db, wired, apply=False, mode="recommend", state=st, mark=None)
    assert res["accounts"][0]["verdict"] == lri.V_COULD_NOT_LOOK
    assert wired["alerts"] == [] and not st.get("could_not_look")


class _FakeAps:
    """Seams of amend_position_sl for _exec_bybit: a venue whose stop reads
    `after` once the modify is sent."""

    def __init__(self, before, after, read_after="resolved"):
        self.before, self.after, self.read_after, self.sent = before, after, read_after, 0

    def _build_client(self, aid):
        return object(), {"exchange": "bybit", "mode": "live"}

    def _venue_state(self, client, cfg, sym, direction, oid):
        if self.sent:
            return {"read_state": self.read_after, "position": {"size": 1}, "venue_sl": self.after}
        return {"read_state": "resolved", "position": {"size": 1}, "venue_sl": self.before}

    def _send_modify(self, leg, **kw):
        self.sent += 1
        return {"ok": True}

    def _tick_size(self, *a):
        return 0.0001

    @staticmethod
    def same_level(a, b, tol):
        return a is not None and b is not None and abs(a - b) <= tol


@pytest.mark.parametrize("after,read_after,want", [
    (0.2100, "resolved", "applied"),
    (0.2200, "resolved", "apply_failed"),       # the venue still shows the old stop
    (None, "read_failed", "apply_failed"),      # sent, but could not read it back
])
def test_exec_bybit_reads_the_venue_back(monkeypatch, after, read_after, want):
    import scripts.ops.amend_position_sl as aps_mod

    fake = _FakeAps(before=0.2200, after=after, read_after=read_after)
    for name in ("_build_client", "_venue_state", "_send_modify", "_tick_size", "same_level"):
        monkeypatch.setattr(aps_mod, name, getattr(fake, name))
    db = _MonDB([])
    res = lra._exec_bybit(db, {"row": _trade(1, "bybit_2")}, PKG, 0.2100, _intent())
    assert res["result"] == want
    assert (db.trade_writes != []) is (want == "applied")    # journal written only after a matching read-back


def test_exec_bybit_venue_read_failure_is_could_not_look_and_sends_nothing(monkeypatch):
    import scripts.ops.amend_position_sl as aps_mod

    fake = _FakeAps(before=None, after=None)
    for name in ("_build_client", "_venue_state", "_send_modify", "_tick_size", "same_level"):
        monkeypatch.setattr(aps_mod, name, getattr(fake, name))
    res = lra._exec_bybit(_MonDB([]), {"row": _trade(1, "bybit_2")}, PKG, 0.2100, _intent())
    assert res["result"] == lra.X_COULD_NOT_LOOK and fake.sent == 0
