"""MD-LTR-ADA-AUTO: a per-package exception to advice-only, keyed on config/mandates.yaml.

Operator 2026-10-29 ~07:40Z, verbatim on checklist row MD-LTR-ADA-AUTO: "I want to put a standing mandate
for ltr lanes recommendations on this trade to be applied automatically"; popups: scope "Every action",
mechanism "VM applies it directly". Every other package stays advice-only (tests/test_tighten_advice_only.py).
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from scripts.ops import live_review_apply as lra
from scripts.ops import live_review_dispatch as d
from scripts.ops import live_review_wake as lrw
from src.runtime import live_review_due as lrd
from src.runtime import live_review_intent as lri
from src.runtime import live_review_rows_watch as w
from src.runtime import ltr_auto_mandate as am
from tests import test_live_review_rows_watch as trw
from tests.test_live_review_apply import ACCOUNTS, STRATS, _ApplyDB, _intent, wired  # noqa: F401
from tests.test_live_review_dispatch import RID, TABLE_ROW, _judged, _set_row, world  # noqa: F401

IN_TRADE_CLASSES = ("tighten_sl", "widen_sl", "move_tp", "partial_close", "close", "change_size", "add_entry")
ADA = "pkg-465a5d7d27644027"
REAL = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "mandates.yaml").read_text())


def doc(pkg="pkg-1", actions=IN_TRADE_CLASSES, **kw):
    entry = {"id": "MD-T-AUTO", "kind": am.KIND, "granted_by": "operator",
             "package_scope": {"order_package_id": pkg, "actions": list(actions)}, "review_cadence_minutes": 120}
    entry.update(kw)
    return {"mandates": [entry], "proposed": []}


# ------------------------------------------------------------------ the committed grant

def test_the_committed_grant_is_the_operators_words_one_package_every_action():
    (m,) = [x for x in REAL["mandates"] if x["id"] == "MD-LTR-ADA-AUTO"]
    assert m["kind"] == am.KIND and m["granted_by"] and m["granted_at"] == "2026-10-29"
    assert "applied automatically" in m["source"] and '"Every action"' in m["source"]
    assert '"VM applies it directly"' in m["source"]
    assert m["package_scope"]["order_package_id"] == ADA
    assert tuple(m["package_scope"]["actions"]) == IN_TRADE_CLASSES
    assert m["expires_on_event"] == "order_package_closed" and m["review_cadence_minutes"] == 120
    assert [b.split(" ")[0] for b in m["bounds"]] == list(am.BOUNDS)
    assert not m.get("autoland")        # landing stays a human merge


def test_the_committed_grant_expired_with_its_package_and_scopes_nothing():
    """pkg-465a5d7d27644027 closed 2026-10-29T10:47:53Z; the entry carries expired_at per its on_expiry clause."""
    m = next(x for x in REAL["mandates"] if x.get("id") == "MD-LTR-ADA-AUTO")
    assert m["expired_at"] == "2026-10-29T10:47:53Z" and str(m["expired_reason"]).startswith("order_package_closed")
    assert am.exception_for({"order_package_id": ADA, "recommendation": {"action": "close"}}, REAL) is None
    assert am.exception_for({"order_package_id": "pkg-other", "recommendation": {"action": "close"}}, REAL) is None
    assert am.cadence(REAL) == {}


# ------------------------------------------------------------------ the reader

def test_scoping_needs_package_action_kind_and_the_granted_list():
    assert am.scoping("pkg-1", "close", doc())["id"] == "MD-T-AUTO"
    assert am.scoping("pkg-2", "close", doc()) is None
    assert am.scoping("pkg-1", "close", doc(actions=["move_tp"])) is None
    no_kind = doc()
    no_kind["mandates"][0].pop("kind")
    assert am.scoping("pkg-1", "close", no_kind) is None
    proposed = {"mandates": [], "proposed": doc()["mandates"]}
    assert am.scoping("pkg-1", "close", proposed) is None       # a proposal grants nothing
    assert am.scoping("pkg-*", "close", doc(pkg="pkg-*")) is not None and am.scoping("pkg-1", "close", doc(pkg="pkg-*")) is None


def test_expiry_and_unreadable_file_fail_closed(tmp_path):
    now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    assert am.scoping("pkg-1", "close", doc(expired_at="2026-10-29T10:00:00Z"), now) is None
    assert am.scoping("pkg-1", "close", doc(expires_on="2026-10-28"), now) is None
    assert am.scoping("pkg-1", "close", doc(expires_on="2026-10-29"), now) is not None
    assert am.scoping("pkg-1", "close", doc(expires_on="not a date"), now) is None
    assert am.load(tmp_path / "missing.yaml") == {}
    (tmp_path / "bad.yaml").write_text(": : :\n- [")
    assert am.load(tmp_path / "bad.yaml") == {}


# ------------------------------------------------------------------ VM rows watcher

@pytest.fixture
def granted(monkeypatch):
    monkeypatch.setattr(am, "load", lambda path=None: doc("pkg-1"))


@pytest.mark.parametrize("action", IN_TRADE_CLASSES)
def test_watcher_dispatches_every_class_on_the_scoped_package(tmp_path, granted, action):
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([trw.row("LR-a", action=action)]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == [("LR-a", trw.TIP)]
    (rec,) = trw.log(tmp_path)
    assert rec["verdict"] == "dispatched" and rec["auto_mandate"] == "MD-T-AUTO"


def test_watcher_keeps_every_other_package_advice_only(tmp_path, granted):
    other = dict(trw.row("LR-o", action="close"), order_package_id="pkg-2")
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([other]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == []
    assert trw.log(tmp_path)[0]["verdict"] == "advice_only"


@pytest.mark.parametrize("route", ["operator_ask", "none"])
def test_the_exception_never_dispatches_an_advice_route(tmp_path, granted, route):
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([trw.row("LR-r", action="close", route=route)]), dispatch=disp,
               now_fn=lambda: trw.T0, logs=tmp_path)
    assert disp.calls == [] and trw.log(tmp_path)[0]["detail"] == f"route_{route}"


# ------------------------------------------------------------------ dispatcher

def test_dispatcher_hands_a_scoped_row_over_under_the_auto_mandate(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(am, "load", lambda path=None: doc("pkg-aaaa"))
    row = _judged(TABLE_ROW)
    _set_row(world, row)
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "dispatched" and res["auto_mandate"] == "MD-T-AUTO"
    pairs = dict(zip(world["calls"][0][::2], world["calls"][0][1::2]))
    assert pairs["--mandate"] == "MD-T-AUTO" and float(pairs["--new-sl"]) == 0.2101


def test_dispatcher_close_on_the_scoped_package_names_the_auto_mandate(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(am, "load", lambda path=None: doc("pkg-aaaa"))
    row = copy.deepcopy(TABLE_ROW)
    row["recommendation"] = {"action": "close", "reason": "thesis failed", "evidence_source": "judgement",
                             "basis": "judgement", "judgement_confidence": 0.6}
    _set_row(world, row)
    res = d.dispatch(RID, apply=True)
    pairs = dict(zip(world["calls"][0][::2], world["calls"][0][1::2]))
    assert res["verdict"] == "dispatched" and pairs["--action"] == "close" and pairs["--mandate"] == "MD-T-AUTO"


def test_dispatcher_still_refuses_an_unscoped_package_as_advice(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(am, "load", lambda path=None: doc("pkg-zzzz"))
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "advice_only" and world["calls"] == [] and world["pings"] == []


def test_dispatcher_keeps_the_mandate_clauses_on_a_scoped_row(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(am, "load", lambda path=None: doc("pkg-aaaa"))
    row = _judged(TABLE_ROW)
    row["mechanics"] = {"verdict": "mismatch", "evidence": "x"}
    _set_row(world, row)
    res = d.dispatch(RID, apply=True)
    assert res["verdict"] == "refused" and "mechanics_mismatch" in res["detail"] and world["calls"] == []


# ------------------------------------------------------------------ apply: grant re-check and bounds

PKG_A = {"order_package_id": "pkg-P", "status": "open", "strategy_name": "ada_pullback_2h", "symbol": "ADAUSDT",
         "direction": "short", "entry": 0.2062, "sl": 0.2200, "tp": 0.1900,
         "meta": '{"risk_per_unit": 0.0047}'}


def _leg(tid, account):
    return {"id": tid, "account_id": account, "order_package_id": "pkg-P", "status": "open", "stop_loss": 0.2200,
            "position_size": 10.0, "symbol": "ADAUSDT", "direction": "short", "is_backtest": 0,
            "notes": None, "sl_order_id": f"o{tid}"}


def _auto_run(wired, monkeypatch, *, mdoc=None, state=None, **ikw):  # noqa: F811
    monkeypatch.setattr(lra, "_get_package", lambda db, pid: dict(db.pkg) if pid == db.pkg["order_package_id"] else None)
    db = _ApplyDB([_leg(1, "bybit_2"), _leg(2, "bybit_portfolio")], PKG_A)
    kw = dict(order_package_id="pkg-P", mandate="MD-T-AUTO")
    kw.update(ikw)
    st = state if state is not None else {}
    res = lra.run(_intent(**kw), apply=True, db=db, accounts=ACCOUNTS, strategies=STRATS,
                  review_cfg={"apply_mode": "apply"}, granted=set(), write_log=False, state=st,
                  mandates_doc=mdoc if mdoc is not None else doc("pkg-P"))
    return res, st


def test_an_auto_tighten_applies_on_every_account_with_one_ping(wired, monkeypatch):  # noqa: F811
    res, st = _auto_run(wired, monkeypatch)
    assert res["exit"] == lra.EXIT_OK and res["auto_mandate"] == "MD-T-AUTO"
    assert [e[1] for e in wired["exec"]] == ["bybit_2", "bybit_portfolio"]
    assert wired["pings"] == [("bybit_2,bybit_portfolio", 0.21)]        # ONE ping per action
    assert st["auto_review_ids"]["pkg-P"] == [_intent(order_package_id="pkg-P").review_id]
    assert "auto_bar" not in st


def test_no_per_bar_cap_a_second_review_on_the_same_bar_applies(wired, monkeypatch):  # noqa: F811
    """REMOVE-PER-BAR-CAP (operator 2026-10-29): two DIFFERENT reviews on one bar both act on every account."""
    _, st = _auto_run(wired, monkeypatch)
    res, _ = _auto_run(wired, monkeypatch, state=st, review_id="LR-second", new_sl=0.2090)
    assert res["exit"] == lra.EXIT_OK and len(wired["exec"]) == 4


def test_the_same_review_id_never_applies_twice(wired, monkeypatch):  # noqa: F811
    _, st = _auto_run(wired, monkeypatch)
    res, _ = _auto_run(wired, monkeypatch, state=st)
    assert res["exit"] == lra.EXIT_REFUSED and "idempotent_per_review_id" in res["detail"]
    assert len(wired["exec"]) == 2                                      # nothing more was sent


def test_an_auto_mandate_that_does_not_scope_the_package_applies_nothing(wired, monkeypatch):  # noqa: F811
    res, _ = _auto_run(wired, monkeypatch, mdoc=doc("pkg-other"))
    assert res["exit"] == lra.EXIT_REFUSED and wired["exec"] == [] and wired["pings"] == []
    res, _ = _auto_run(wired, monkeypatch, mdoc=doc("pkg-P", actions=["close"]))
    assert res["exit"] == lra.EXIT_REFUSED and wired["exec"] == []


def test_the_desk_mandate_path_is_unchanged_per_account_pings(wired, monkeypatch):  # noqa: F811
    res, st = _auto_run(wired, monkeypatch, mandate=lri.MANDATE_ID, mdoc=doc("pkg-P"))
    assert res["exit"] == lra.EXIT_REFUSED                              # MD-LIVE-TIGHTEN-SL not in `granted`
    monkeypatch.setattr(lra, "_get_package", lambda db, pid: dict(db.pkg))
    db = _ApplyDB([_leg(1, "bybit_2"), _leg(2, "bybit_portfolio")], PKG_A)
    lra.run(_intent(order_package_id="pkg-P"), apply=True, db=db, accounts=ACCOUNTS, strategies=STRATS,
            review_cfg={"apply_mode": "apply"}, granted={lri.MANDATE_ID}, write_log=False, state={},
            mandates_doc=doc("pkg-P"))
    assert wired["pings"] == [("bybit_2", 0.21), ("bybit_portfolio", 0.21)]


def _bound(action="tighten_sl", st=None, pkg=None, **kw):
    base = dict(order_package_id="pkg-P", action=action, mandate="MD-T-AUTO")
    base.update(kw)
    return lra.auto_bound_refusal(_intent(**base), dict(pkg or PKG_A), st or {})


def test_widen_never_beyond_minus_1r():
    assert _bound("widen_sl", new_sl=0.2100) is None                   # inside entry + risk = 0.2109
    assert _bound("widen_sl", new_sl=0.2109) is None                   # at -1R exactly
    ex, why = _bound("widen_sl", new_sl=0.2120)
    assert ex == lra.EXIT_REFUSED and "widen_within_1r" in why
    ex, why = _bound("widen_sl", new_sl=0.2100, pkg=dict(PKG_A, meta=None))
    assert ex == lra.EXIT_REFUSED and "unread" in why                  # never widened blind
    long_pkg = dict(PKG_A, direction="long", entry=1.00, tp=1.20, meta='{"risk_per_unit": 0.05}')
    assert _bound("widen_sl", pkg=long_pkg, direction="long", new_sl=0.96, mark=1.05) is None
    assert _bound("widen_sl", pkg=long_pkg, direction="long", new_sl=0.94, mark=1.05)[0] == lra.EXIT_REFUSED


def test_tp_stays_a_live_target_and_both_brackets_exist():
    assert "both_brackets" in _bound(pkg=dict(PKG_A, tp=None))[1]
    assert "tp_live_target" in _bound(pkg=dict(PKG_A, tp=0.2050))[1]   # a short's TP above the mark
    assert _bound("close", pkg=dict(PKG_A, tp=None)) is None           # a close removes the position
    # a move_tp's own target is checked per account by decide_action (TP doctrine)
    v = lri.decide_action(_intent(action="move_tp", new_tp=0.2010, mark=0.2000),
                          lri.AmendAccountView(account_id="bybit_2", leg_sl=0.2100, entry=0.2062, leg_tp=0.19),
                          dry_run=False)
    assert v.verdict == lri.V_REFUSE and "tp_through_mark" in v.reason


def test_an_unread_bar_refuses_nothing():
    """REMOVE-PER-BAR-CAP: the bar is provenance only; no bound reads it, so an unread bar holds nothing back."""
    assert _bound(bar_ts=None) is None


def test_a_bound_refusal_alerts_once_per_review(wired, monkeypatch):  # noqa: F811
    st = {}
    for _ in range(2):
        res, _ = _auto_run(wired, monkeypatch, state=st, action="widen_sl", new_sl=0.2150,
                           reason="vol expansion", basis=lri.BASIS_JUDGEMENT, confidence=0.6)
    assert "widen_within_1r" in res["detail"] and wired["exec"] == []
    assert len(wired["alerts"]) == 1


def test_applied_review_ids_counts_tightens_trade_actions_and_the_floor():
    notes = {"sl_amends": [{"source": lri.PROVENANCE, "review_id": "LR-a"}],
             "live_review_actions": [{"source": lri.PROVENANCE, "review_id": "LR-b", "action": "move_tp"}],
             "sl_floor": {"source": lri.PROVENANCE, "review_id": "DA-c"}}
    assert lra.applied_review_ids(notes) == ("DA-c", "LR-a", "LR-b")
    assert lra.applied_review_ids({"live_review_actions": [{"source": "other", "review_id": "x"}]}) == ()


# ------------------------------------------------------------------ the bybit tighten keeps both brackets

class _Aps:
    def __init__(self):
        self.sent = 0

    def _build_client(self, aid):
        return object(), {"exchange": "bybit"}

    def _venue_state(self, client, cfg, sym, direction, oid):
        return {"read_state": "resolved", "position": {"size": 1}, "venue_sl": 0.2100 if self.sent else 0.2200}

    def _send_modify(self, leg, **kw):
        self.sent += 1
        return {"ok": True}

    def _tick_size(self, *a):
        return 0.0001

    @staticmethod
    def same_level(a, b, tol):
        return a is not None and b is not None and abs(a - b) <= tol


@pytest.mark.parametrize("tps,want,sent", [
    ([0.19, 0.19], lra.X_APPLIED, 1),
    ([None], lra.X_COULD_NOT_LOOK, 0),            # no resting TP before: nothing sent
    ([0.19, None], lra.X_APPLY_FAILED, 1),        # the TP vanished: never a success
])
def test_exec_bybit_tighten_reads_both_brackets(monkeypatch, tps, want, sent):
    import scripts.ops.amend_position_sl as aps_mod
    from tests.test_live_review_apply import PKG, _MonDB, _trade

    fake = _Aps()
    for name in ("_build_client", "_venue_state", "_send_modify", "_tick_size", "same_level"):
        monkeypatch.setattr(aps_mod, name, getattr(fake, name))
    seq = list(tps)
    monkeypatch.setattr(lra, "_venue_tp", lambda *a: {"read_state": "resolved", "venue_tp": seq.pop(0)})
    res = lra._exec_bybit(_MonDB([]), {"row": _trade(1, "bybit_2")}, PKG, 0.2100, _intent())
    assert res["result"] == want and fake.sent == sent


# ------------------------------------------------------------------ the VM cadence wake (row-write fix)

NOW = datetime(2026, 10, 29, 10, 1, tzinfo=timezone.utc)
CAD = {"pkg-1": {"mandate": "MD-T-AUTO", "minutes": 120}}


def _due_row(**kw):
    base = {"order_package_id": "pkg-1", "strategy": "ada_pullback_2h", "account_id": "bybit_2",
            "symbol": "ADAUSDT", "direction": "short", "open_r": 0.2, "peak_r": 0.3, "giveback_r": 0.1,
            "r_to_target": 3.0, "updated_at": NOW.isoformat(), "lifecycle": "open"}
    base.update(kw)
    return base


def _floor_review(at):
    return {"order_package_id": "pkg-1", "reviewed_at": at.isoformat(),
            "trigger": {"event": "daily_floor", "level": "x"}, "state": {"peak_r": None}}


def test_a_scoped_open_package_is_due_once_per_cadence_slot():
    cfg = lrd.load_config()
    old = [_floor_review(NOW - timedelta(hours=3))]
    res = lrd.compute_due([_due_row()], old, cfg, NOW, cadence=CAD)
    (ev,) = [e for e in res["due"][0]["events"] if e["event"] == "mandate_cadence"]
    assert ev["level"] == "2026-10-29T10:00:00+00:00"
    answered = old + [{"order_package_id": "pkg-1", "reviewed_at": (NOW - timedelta(hours=1)).isoformat(),
                       "trigger": {"event": "mandate_cadence", "level": ev["level"]}, "state": {}}]
    assert lrd.compute_due([_due_row()], answered, cfg, NOW, cadence=CAD)["due_count"] == 0
    # unscoped packages get no mandate cadence event (they may get the DESK-AM-REFOCUS judgement slot instead)
    unscoped = lrd.compute_due([_due_row()], old, cfg, NOW)
    assert not [e for d in unscoped["due"] for e in d["events"] if e["event"] == "mandate_cadence"]


def test_the_cadence_wake_is_deduped_by_slot_not_held_by_the_cooldown():
    cfg = lrw.load_cfg()

    def due(level):
        return {"read_state": "looked", "due_count": 1, "generated_at": NOW.isoformat(),
                "due": [{"order_package_id": "pkg-1", "leg": "ada_pullback_2h", "symbol": "ADAUSDT",
                         "account_id": "bybit_2", "telemetry_updated_at": NOW.isoformat(),
                         "events": [{"event": "mandate_cadence", "level": level, "why": "x"}]}]}
    p1 = lrw.plan(due("2026-10-29T10:00:00+00:00"), [], cfg, NOW)
    assert p1["kind"] == "wake"
    late = NOW + timedelta(minutes=100)          # the 10:00 wake posted late (11:41)
    posted = lrw.parse_markers([{"body": lrw.render(p1, late, "run")}])
    assert lrw.plan(due("2026-10-29T10:00:00+00:00"), posted, cfg, late)["kind"] == "quiet"      # same slot
    nxt = datetime(2026, 10, 29, 12, 0, 30, tzinfo=timezone.utc)                                # 19 min later
    assert lrw.plan(due("2026-10-29T12:00:00+00:00"), posted, cfg, nxt)["kind"] == "wake"        # next slot


def test_the_records_validator_requires_the_cadence_level():
    from scripts.ci import check_live_review_records as clr

    row = {"reviewed_at": "2026-10-29T10:05:00Z", "trigger": {"event": "mandate_cadence", "level": None}}
    assert clr.trigger_problems(row)
    row["trigger"]["level"] = "2026-10-29T10:00:00+00:00"
    assert clr.trigger_problems(row) == []


# ================================================================== MD-LTR-BYBIT1-AUTO (account scope)
#
# Operator 2026-11-01 ~11:38Z, popup answered verbatim "Auto-apply on bybit_1 (Rec.)": every in-trade call on
# a bybit_1 package is applied by the VM; real money, mirrors and prop stay advice-only. These tests PROVE the
# real-money and mirror legs are unchanged (MD-DEMO-FLOOR-BUILD shared_code_rule).

B1 = "MD-LTR-BYBIT1-AUTO"


def acct_doc(accounts=("bybit_1",), actions=IN_TRADE_CLASSES, **kw):
    entry = {"id": "MD-A-AUTO", "kind": am.KIND, "granted_by": "operator",
             "account_scope": {"accounts": list(accounts), "actions": list(actions)}}
    entry.update(kw)
    return {"mandates": [entry], "proposed": []}


def test_the_committed_bybit1_grant_is_the_operators_words_bybit1_only_every_action():
    (m,) = [x for x in REAL["mandates"] if x["id"] == B1]
    assert m["kind"] == am.KIND and m["granted_by"] and m["granted_at"] == "2026-11-01"
    assert m["parent"] == "MD-TRADE-DESK"
    assert '"Auto-apply on bybit_1 (Rec.)"' in m["source"]
    assert '"Should live-review calls be applied automatically on the paper soak account (bybit_1) only?"' \
        in " ".join(m["source"].split())
    assert "package_scope" not in m and m["account_scope"]["accounts"] == ["bybit_1"]
    assert tuple(m["account_scope"]["actions"]) == IN_TRADE_CLASSES
    assert [b.split(" ")[0] for b in m["bounds"]] == list(am.BOUNDS)
    # no calendar expiry (the operator's words name none), no cadence, landing stays a human merge
    assert not m.get("expires_on") and not m.get("expired_at") and not m.get("review_cadence_minutes")
    assert not m.get("autoland")
    assert am.is_auto_mandate(B1, REAL) and am.account_scope(m) == frozenset({"bybit_1"})


def test_bybit1_paper_is_scoped_and_no_real_money_mirror_or_prop_account_is():
    """bybit_1 is the paper demo floor in config/accounts.yaml; every account it could share a package with
    stays out of scope."""
    accts = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "accounts.yaml").read_text())
    accts = accts.get("accounts", accts)
    assert str(accts["bybit_1"].get("account_class")).lower() == "paper"
    (m,) = [x for x in REAL["mandates"] if x["id"] == B1]
    for aid, cfg in accts.items():
        if aid in m["account_scope"]["accounts"]:
            assert str((cfg or {}).get("account_class")).lower() == "paper", aid


@pytest.mark.parametrize("accounts,want", [
    (["bybit_1"], B1),
    (["bybit_2", "bybit_portfolio", "bybit_1"], B1),     # shared package: dispatched; the apply acts on bybit_1 only
    (["bybit_2", "bybit_portfolio"], None),              # real money + mirror: advice-only, unchanged
    (["breakout_1"], None),                              # prop: advice-only, unchanged
    (["alpaca_paper"], None),                            # another paper account: not in this grant
    ([], None),
    (None, None),                                        # unread accounts: fail closed
    ("bybit_1", None),                                   # not a list: fail closed
])
def test_the_committed_grant_scopes_a_row_by_its_accounts(accounts, want):
    for action in IN_TRADE_CLASSES:
        row = {"order_package_id": "pkg-f07b659a7db94e8a", "accounts": accounts, "recommendation": {"action": action}}
        assert am.exception_for(row, REAL) == want
    assert am.exception_for({"order_package_id": "pkg-f07b659a7db94e8a", "accounts": ["bybit_1"],
                             "recommendation": {"action": "hold"}}, REAL) is None


def test_malformed_account_scopes_grant_nothing():
    row = {"order_package_id": "pkg-1", "accounts": ["bybit_1"], "recommendation": {"action": "close"}}
    assert am.exception_for(row, acct_doc()) == "MD-A-AUTO"
    assert am.exception_for(row, acct_doc(accounts=("bybit_*",))) is None        # never a pattern
    assert am.exception_for(row, acct_doc(accounts=())) is None
    assert am.exception_for(row, acct_doc(actions=())) is None
    both = acct_doc(package_scope={"order_package_id": "pkg-1", "actions": ["close"]})
    assert am.exception_for(row, both) is None                                  # both scopes: malformed
    assert am.exception_for(row, {"mandates": [], "proposed": acct_doc()["mandates"]}) is None
    assert am.exception_for(row, acct_doc(expired_at="2026-11-01T12:00:00Z")) is None
    assert am.cadence(acct_doc()) == {}                                         # no package to wake


def test_named_scoping_keeps_the_grant_it_was_handed():
    d2 = {"mandates": doc("pkg-1")["mandates"] + acct_doc()["mandates"], "proposed": []}
    assert am.named_scoping("MD-A-AUTO", "pkg-1", "close", d2)["id"] == "MD-A-AUTO"
    assert am.named_scoping("MD-T-AUTO", "pkg-1", "close", d2)["id"] == "MD-T-AUTO"
    assert am.named_scoping("MD-T-AUTO", "pkg-2", "close", d2) is None
    assert am.named_scoping("MD-A-AUTO", "pkg-2", "close", d2)["id"] == "MD-A-AUTO"
    assert am.named_scoping("MD-A-AUTO", "pkg-2", "hold", d2) is None


# ------------------------------------------------------------------ watcher + dispatcher

def _arow(rid, accounts, action="close"):
    return dict(trw.row(rid, action=action), accounts=accounts)


@pytest.mark.parametrize("accounts,dispatched", [(["bybit_1"], True), (["bybit_2", "bybit_portfolio"], False)])
def test_watcher_dispatches_bybit1_rows_and_keeps_real_money_advice_only(tmp_path, monkeypatch, accounts, dispatched):
    monkeypatch.setattr(am, "load", lambda path=None: REAL)
    disp = trw.FakeDispatch()
    w.run_pass(git=trw.FakeGit([]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    w.run_pass(git=trw.FakeGit([_arow("LR-b", accounts)]), dispatch=disp, now_fn=lambda: trw.T0, logs=tmp_path)
    (rec,) = trw.log(tmp_path)
    if dispatched:
        assert disp.calls == [("LR-b", trw.TIP)] and rec["auto_mandate"] == B1
    else:
        assert disp.calls == [] and rec["verdict"] == "advice_only" and "auto_mandate" not in rec


def test_dispatcher_real_money_row_stays_advice_only_under_the_bybit1_grant(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(am, "load", lambda path=None: REAL)
    res = d.dispatch(RID, apply=True)             # TABLE_ROW.accounts == [bybit_2, bybit_portfolio]
    assert res["verdict"] == "advice_only" and world["calls"] == [] and world["pings"] == []


def test_dispatcher_hands_a_bybit1_close_over_under_the_bybit1_grant(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(am, "load", lambda path=None: REAL)
    row = copy.deepcopy(TABLE_ROW)
    row["accounts"] = ["bybit_1"]
    row["recommendation"] = {"action": "close", "reason": "thesis failed", "evidence_source": "judgement",
                             "basis": "judgement", "judgement_confidence": 0.7}
    _set_row(world, row)
    res = d.dispatch(RID, apply=True)
    pairs = dict(zip(world["calls"][0][::2], world["calls"][0][1::2]))
    assert res["verdict"] == "dispatched" and pairs["--action"] == "close" and pairs["--mandate"] == B1


# ------------------------------------------------------------------ apply: only the bybit_1 leg moves

ACCTS_B1 = dict(ACCOUNTS, bybit_1={"exchange": "bybit", "mode": "live", "account_class": "paper", "risk": {}})


def _b1_run(wired, monkeypatch, legs, *, mdoc=None, state=None, **ikw):  # noqa: F811
    monkeypatch.setattr(lra, "_get_package", lambda db, pid: dict(db.pkg) if pid == db.pkg["order_package_id"] else None)
    db = _ApplyDB([dict(_leg(i + 1, a), entry_price=0.2062, take_profit_1=0.1900) for i, a in enumerate(legs)], PKG_A)
    kw = dict(order_package_id="pkg-P", mandate=B1)
    kw.update(ikw)
    st = state if state is not None else {}
    res = lra.run(_intent(**kw), apply=True, db=db, accounts=ACCTS_B1, strategies=STRATS,
                  review_cfg={"apply_mode": "apply"}, granted=set(), write_log=False, state=st,
                  mandates_doc=mdoc if mdoc is not None else REAL)
    return res, st, db


def test_a_tighten_on_a_shared_package_moves_only_the_bybit1_leg(wired, monkeypatch):  # noqa: F811
    res, st, db = _b1_run(wired, monkeypatch, ["bybit_2", "bybit_portfolio", "bybit_1"])
    assert res["exit"] == lra.EXIT_OK and res["auto_mandate"] == B1 and res["auto_account_scope"] == ["bybit_1"]
    assert wired["exec"] == [("bybit", "bybit_1", 0.21)]                     # nothing sent for bybit_2 / mirror
    assert [a["account_id"] for a in res["accounts"]] == ["bybit_1"]
    assert res["scope_excluded"] == ["bybit_2", "bybit_portfolio"]
    assert [t for t, _ in db.trade_writes] == [3]                            # only the bybit_1 trade row
    assert res["package_sl_moved"] is False and db.package_writes == []      # the shared stop never moves
    assert wired["pings"] == [("bybit_1", 0.21)] and wired["alerts"] == []
    assert [a["account_id"] for a in res["writeback"]["accounts_applied"]] == ["bybit_1"]


def test_a_bybit1_only_tighten_still_leaves_the_shared_package_stop(wired, monkeypatch):  # noqa: F811
    res, _, db = _b1_run(wired, monkeypatch, ["bybit_1"])
    assert wired["exec"] == [("bybit", "bybit_1", 0.21)] and res["scope_excluded"] == []
    assert res["package_sl_moved"] is False and db.package_writes == []


@pytest.mark.parametrize("action,extra", [
    ("close", {}),
    ("move_tp", {"new_tp": 0.1950}),
    ("partial_close", {"size_fraction": 0.5}),
])
def test_every_trade_action_reaches_only_the_bybit1_leg(wired, monkeypatch, action, extra):  # noqa: F811
    sent = []
    monkeypatch.setattr(lra, "_exec_trade_action",
                        lambda db, leg, pkg, cls, v, intent: sent.append(leg["account_id"]) or {"result": lra.X_APPLIED})
    res, _, _ = _b1_run(wired, monkeypatch, ["bybit_2", "bybit_portfolio", "bybit_1"], action=action,
                        reason="thesis failed", basis=lri.BASIS_JUDGEMENT, confidence=0.7, mandate=B1, **extra)
    assert sent == ["bybit_1"], [(a["account_id"], a.get("verdict"), a.get("reason")) for a in res["accounts"]]
    assert res["scope_excluded"] == ["bybit_2", "bybit_portfolio"] and wired["alerts"] == []


def test_a_real_money_only_package_is_untouched_by_the_bybit1_grant(wired, monkeypatch):  # noqa: F811
    res, st, db = _b1_run(wired, monkeypatch, ["bybit_2", "bybit_portfolio"])
    assert res["exit"] == lra.EXIT_REFUSED and "scopes no open leg" in res["detail"]
    assert wired["exec"] == [] and wired["pings"] == [] and wired["alerts"] == []
    assert db.trade_writes == [] and db.package_writes == [] and res.get("accounts") == []
    assert "auto_review_ids" not in st


def test_real_money_and_mirror_behaviour_is_identical_with_and_without_the_bybit1_grant(wired, monkeypatch):  # noqa: F811
    """The same desk-mandate tighten on a bybit_2 + mirror package, with the committed file (which carries
    MD-LTR-BYBIT1-AUTO) and with an empty one: identical execution, pings and account reads."""
    outs = []
    for mdoc in (REAL, {"mandates": [], "proposed": []}):
        wired["exec"].clear(), wired["pings"].clear(), wired["alerts"].clear()
        monkeypatch.setattr(lra, "_get_package", lambda db, pid: dict(db.pkg))
        db = _ApplyDB([_leg(1, "bybit_2"), _leg(2, "bybit_portfolio")], PKG_A)
        res = lra.run(_intent(order_package_id="pkg-P"), apply=True, db=db, accounts=ACCTS_B1, strategies=STRATS,
                      review_cfg={"apply_mode": "apply"}, granted={lri.MANDATE_ID}, write_log=False, state={},
                      mandates_doc=mdoc)
        outs.append((list(wired["exec"]), list(wired["pings"]), list(wired["alerts"]),
                     res["writeback"]["account_reads"], res["package_sl_moved"], db.package_writes))
    assert outs[0] == outs[1]
    assert outs[0][0] == [("bybit", "bybit_2", 0.21), ("bybit", "bybit_portfolio", 0.21)]


def test_the_bybit1_grant_cannot_be_named_for_a_prop_or_real_money_leg(wired, monkeypatch):  # noqa: F811
    """Even named explicitly on the command line, the grant reaches no leg outside bybit_1."""
    wired["tickets"] = [{"account_id": "tradeify_1", "ticket_id": "t1", "sl": 0.22, "meta": None}]
    res, _, _ = _b1_run(wired, monkeypatch, ["bybit_2"])
    assert res["exit"] == lra.EXIT_REFUSED and wired["exec"] == [] and wired["alerts"] == []


def test_the_bybit1_bounds_still_bind(wired, monkeypatch):  # noqa: F811
    _, st, _ = _b1_run(wired, monkeypatch, ["bybit_1"])
    res, _, _ = _b1_run(wired, monkeypatch, ["bybit_1"], state=st)             # same review_id
    assert res["exit"] == lra.EXIT_REFUSED and "idempotent_per_review_id" in res["detail"]
    res, _, _ = _b1_run(wired, monkeypatch, ["bybit_1"], action="widen_sl", new_sl=0.2150, review_id="LR-w",
                        reason="vol", basis=lri.BASIS_JUDGEMENT, confidence=0.6)
    assert "widen_within_1r" in res["detail"]
    pkg_no_tp = dict(PKG_A, tp=None)
    monkeypatch.setattr(lra, "_get_package", lambda db, pid: dict(pkg_no_tp))
    res = lra.run(_intent(order_package_id="pkg-P", mandate=B1, review_id="LR-t"), apply=True,
                  db=_ApplyDB([_leg(1, "bybit_1")], pkg_no_tp), accounts=ACCTS_B1, strategies=STRATS,
                  review_cfg={"apply_mode": "apply"}, granted=set(), write_log=False, state={}, mandates_doc=REAL)
    assert "both_brackets" in res["detail"]
    assert len(wired["exec"]) == 1                                             # only the first tighten was sent
