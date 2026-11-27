"""LTR-PROP-RECEIPT-CONFIRM-WRITEBACK: every venue_unconfirmed receipt resolves (src/runtime/live_review_confirm.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import live_review_confirm as C

T0 = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _applied(action="tighten_sl", executor=None, level=100.0, acct="tradeify_1", rid="LR-1", unconfirmed=True):
    return {"at": T0.isoformat(), "review_id": rid, "order_package_id": "pkg-1", "action": action,
            "accounts_applied": [{"account_id": acct, "level": level, "executor": dict(executor or {}, result="applied",
                                                                                         venue_confirmed=False)}],
            "disposition": {"applied_at": T0.isoformat(), "venue_unconfirmed": [acct] if unconfirmed else []}}


def _item(**kw):
    return C.unconfirmed([_applied(**kw)])[0]


def _tk(meta=None):
    return {"ticket_id": "t1", "meta": json.dumps(meta or {})}


def _fill(**kw):
    d = {"id": 7, "status": "open", "closed_at": None, "sl": 95.0, "tp": 120.0}
    d.update(kw)
    return d


def test_only_venue_unconfirmed_accounts_are_watched():
    assert C.unconfirmed([_applied(unconfirmed=False)]) == []
    it = _item()
    assert (it["review_id"], it["account_id"], it["level"]) == ("LR-1", "tradeify_1", 100.0)


def test_phone_amend_amended_is_confirmed():
    it = _item(executor={"amend_id": "a1", "sl": 100.0})
    r = C.resolve(it, _tk({"phone_trail": {"amend": {"id": "a1", "status": "amended", "sl_read": 100.0}}}), _fill())
    assert r["outcome"] == C.CONFIRMED


@pytest.mark.parametrize("st", ["no_position", "human_moved"])
def test_phone_amend_refusals_are_refused(st):
    it = _item(executor={"amend_id": "a1", "sl": 100.0})
    assert C.resolve(it, _tk({"phone_trail": {"amend": {"id": "a1", "status": st}}}), _fill())["outcome"] == C.REFUSED


def test_phone_amend_still_claimed_is_pending():
    it = _item(executor={"amend_id": "a1", "sl": 100.0})
    r = C.resolve(it, _tk({"phone_trail": {"amend": {"id": "a1", "status": "claimed"}}}), _fill())
    assert r["outcome"] == C.PENDING


def test_superseded_amend_falls_back_to_the_fill_level():
    it = _item(executor={"amend_id": "a1", "sl": 100.0})
    r = C.resolve(it, _tk({"phone_trail": {"amend": {"id": "a2", "status": "claimed"}}}), _fill(sl=100.0))
    assert r["outcome"] == C.CONFIRMED


def test_prop_vm_floor_confirmed_by_the_fill_row_stop():
    it = _item(executor={})                       # _exec_prop_vm carries no handle; the level is on accounts_applied
    assert C.resolve(it, _tk(), _fill(sl=100.0))["outcome"] == C.CONFIRMED
    assert C.resolve(it, _tk(), _fill(sl=95.0))["outcome"] == C.PENDING


@pytest.mark.parametrize("side,sl,want", [("long", 101.0, C.CONFIRMED), ("long", 99.0, C.PENDING),
                                          ("short", 99.0, C.CONFIRMED), ("short", 101.0, C.PENDING)])
def test_a_tighten_is_confirmed_at_or_through_the_floor_never_looser(side, sl, want):
    assert C.resolve(_item(executor={}), _tk(), _fill(sl=sl, direction=side))["outcome"] == want


def test_prop_vm_tp_confirmed_by_the_fill_row_target():
    it = _item(action="move_tp", executor={"tp": 130.0}, level=130.0)
    assert C.resolve(it, _tk(), _fill(tp=130.0))["outcome"] == C.CONFIRMED
    assert C.resolve(it, _tk(), _fill(tp=120.0))["outcome"] == C.PENDING


def test_level_request_on_a_closed_fill_is_closed_before_confirm():
    it = _item(executor={})
    r = C.resolve(it, _tk(), _fill(status="closed", closed_at=(T0 + timedelta(minutes=5)).isoformat()))
    assert r["outcome"] == C.CLOSED_BEFORE


def test_prop_vm_full_close_confirmed_when_the_fill_closes_after_the_apply():
    it = _item(action="close", executor={"close_id": "vmc-1"})
    late = (T0 + timedelta(minutes=204)).isoformat()   # the motivating tradeify_1 case
    assert C.resolve(it, _tk(), _fill())["outcome"] == C.PENDING
    assert C.resolve(it, _tk(), _fill(status="closed", closed_at=late))["outcome"] == C.CONFIRMED


def test_phone_close_done_and_not_found():
    it = _item(action="close", executor={"close_id": "c1"})
    assert C.resolve(it, _tk({"phone_close": {"id": "c1", "status": "done"}}), _fill())["outcome"] == C.CONFIRMED
    assert C.resolve(it, _tk({"phone_close": {"id": "c1", "status": "not_found"}}), _fill())["outcome"] == C.REFUSED
    assert C.resolve(it, _tk({"phone_close": {"id": "c1", "status": "failed"}}), _fill())["outcome"] == C.PENDING


def test_prop_vm_partial_close_says_there_is_no_readback_here():
    it = _item(action="partial_close", executor={"close_id": "vmc-2"})
    assert C.resolve(it, _tk(), _fill())["outcome"] == C.NO_READBACK_HERE


def test_no_ticket_is_could_not_look_not_pending():
    assert C.resolve(_item(), None, None)["outcome"] == C.COULD_NOT_LOOK


def _setup(tmp_path, rows):
    (tmp_path / C.APPLIED_LOG).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return tmp_path


def _confirms(d):
    p = d / C.CONFIRM_LOG
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_pass_records_a_resolution_once(tmp_path):
    d = _setup(tmp_path, [_applied(executor={})])
    alerts = []
    read = lambda it: (_tk(), _fill(sl=100.0))  # noqa: E731
    assert C.run_confirm_pass(now=T0 + timedelta(minutes=2), log_dir=d, read=read, alert=alerts.append) == {"confirmed": 1}
    assert C.run_confirm_pass(now=T0 + timedelta(minutes=3), log_dir=d, read=read, alert=alerts.append) == {}
    recs = _confirms(d)
    assert len(recs) == 1 and recs[0]["outcome"] == "confirmed" and recs[0]["latency_s"] == 120.0
    assert alerts == []


def test_pending_flags_once_after_the_age_then_reports_the_resolution(tmp_path):
    d = _setup(tmp_path, [_applied(action="close", executor={"close_id": "vmc-1"})])
    alerts = []
    open_ = lambda it: (_tk(), _fill())  # noqa: E731
    C.run_confirm_pass(now=T0 + timedelta(minutes=10), log_dir=d, read=open_, alert=alerts.append)
    assert alerts == []                                            # under the flag age
    C.run_confirm_pass(now=T0 + timedelta(minutes=40), log_dir=d, read=open_, alert=alerts.append)
    C.run_confirm_pass(now=T0 + timedelta(minutes=80), log_dir=d, read=open_, alert=alerts.append)
    assert len(alerts) == 1 and "still not confirmed" in alerts[0]  # ONE flag, the pass keeps watching
    closed = lambda it: (_tk(), _fill(status="closed", closed_at=(T0 + timedelta(minutes=204)).isoformat()))  # noqa: E731
    C.run_confirm_pass(now=T0 + timedelta(minutes=205), log_dir=d, read=closed, alert=alerts.append)
    assert len(alerts) == 2 and "confirmed" in alerts[1]            # a flagged item reports how it ended
    rec = _confirms(d)[0]
    assert rec["outcome"] == "confirmed" and rec["was_flagged"] is True and rec["handle"] == {"close_id": "vmc-1"}


def test_a_read_error_is_contained_and_retried(tmp_path):
    d = _setup(tmp_path, [_applied(executor={})])

    def boom(it):
        raise RuntimeError("db locked")

    assert C.run_confirm_pass(now=T0, log_dir=d, read=boom, alert=lambda s: True) == {"could_not_look": 1}
    assert _confirms(d) == []                                       # not terminal: watched next pass
    assert C.run_confirm_pass(now=T0, log_dir=d, read=lambda it: (_tk(), _fill(sl=100.0)),
                              alert=lambda s: True) == {"confirmed": 1}


def test_unresolved_past_the_give_up_age_is_recorded_once(tmp_path):
    d = _setup(tmp_path, [_applied(action="close", executor={"close_id": "vmc-1"})])
    alerts = []
    C.run_confirm_pass(now=T0 + timedelta(seconds=C.GIVE_UP_AFTER_S + 1), log_dir=d,
                       read=lambda it: (_tk(), _fill()), alert=alerts.append)
    assert [r["outcome"] for r in _confirms(d)] == [C.EXPIRED] and len(alerts) == 1


def test_the_rows_watch_loop_runs_the_confirm_pass():
    import inspect

    from src.runtime import live_review_rows_watch as W
    assert "run_confirm_pass" in inspect.getsource(W._loop)
