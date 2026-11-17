"""PI-20261027-KYYBSZXS-0001: a REFUSED re-arm OCO must not leave the position with less protection.

`AlpacaClient.place_protective` is cancel-before-place. MEASURED 2026-11-16 14:32:55-14:35:03Z on alpaca_paper:
seven refusals, "insufficient qty available for order (requested: 9375, available: 0)" (during the false close-all
that #26522 fixed; the flatten itself had cancelled the legs). "Place first" cannot work on Alpaca (the resting
legs reserve the shares, hence available 0), so after a refusal the legs it cancelled are put back, at their OLD
prices, always GTC, READ BACK from the venue, and a failed restore is reported (and alerted, through the
naked-position alert path, by the order monitor). A sibling's standalone target released for the retry is put back
when the retry is also refused; when the retry succeeds it stays released (documented, manager 2026-11-17 06:02Z:
the shares are shared on Alpaca, so both cannot be held; a merged-OCO design is filed).

Fixtures reuse the captured alpaca_paper/SPY shape of tests/test_alpaca_rearm_scoped_cancel.py.
"""
from __future__ import annotations

import logging

from src.runtime import order_monitor
from src.units.accounts.alpaca_client import AlpacaClient

from tests.test_alpaca_rearm_scoped_cancel import (
    _LIVE_SPY, _OCO8, _OCO8_STOP, _Venue, _rearm,
)

_REFUSED = {"retCode": 403,
            "retMsg": "insufficient qty available for order (requested: 8, available: 0)"}
_OK = {"retCode": 0, "result": {"id": "restored-1"}}


class _Readback(_Venue):
    """_Venue plus ``GET /v2/orders/<id>`` (the restore's read-back) answering ``read_status``."""

    def __init__(self, open_rows, post_results=None, read_status="new"):
        super().__init__(open_rows, post_results)
        self.read_status = read_status

    def _request(self, method, path, json_body=None):  # type: ignore[override]
        if method == "GET" and path.startswith("/v2/orders/") and "?" not in path:
            self.calls.append((method, path, json_body))
            if self.read_status is None:
                return {"retCode": 404, "retMsg": "not found"}
            return {"retCode": 0, "result": {"id": path.rsplit("/", 1)[1], "status": self.read_status}}
        return super()._request(method, path, json_body)


def _posts(v):
    return [b for m, p, b in v.calls if m == "POST"]


def test_refused_oco_restores_the_cancelled_own_oco_at_its_old_prices_and_reads_it_back():
    v = _Readback(_LIVE_SPY, post_results=[_REFUSED, _OK])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 403                           # the re-arm still reads as refused
    assert r["restored"]["ok"] == 1 and r["restored"]["attempted"] == 1 and not r["restored"]["failed"]
    assert "restored 1/1" in r["retMsg"] and "insufficient qty" in r["retMsg"]
    new_oco, restore = _posts(v)
    assert new_oco["stop_loss"] == {"stop_price": "760.00"}              # the NEW levels were tried first
    assert restore["order_class"] == "oco" and restore["qty"] == "8" and restore["side"] == "sell"
    assert restore["time_in_force"] == "gtc"
    assert restore["take_profit"] == {"limit_price": "840.65"}           # the OLD target
    assert restore["stop_loss"] == {"stop_price": "763.69"}              # the OLD stop
    assert ("GET", "/v2/orders/restored-1", None) in v.calls             # read back
    assert v.deletes() == sorted([_OCO8["id"], _OCO8_STOP["id"]])        # the 11-share sibling untouched


def test_restore_that_reads_back_as_not_resting_counts_as_failed():
    v = _Readback(_LIVE_SPY, post_results=[_REFUSED, _OK], read_status="rejected")
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["restored"]["ok"] == 0
    assert any("read back as 'rejected'" in f for f in r["restored"]["failed"])


def test_restore_whose_readback_fails_counts_as_failed_not_ok():
    v = _Readback(_LIVE_SPY, post_results=[_REFUSED, _OK], read_status=None)
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["restored"]["ok"] == 0 and r["restored"]["failed"]


def test_successful_oco_places_nothing_to_restore():
    v = _Readback(_LIVE_SPY, post_results=[{"retCode": 0, "result": {"id": "oco-new"}}])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 0 and r["result"]["orderId"] == "oco-new"
    assert "restored" not in r
    assert len(_posts(v)) == 1


def test_refusal_with_nothing_cancelled_is_returned_unchanged():
    """No own leg rests (a genuinely naked position): there is nothing to put back."""
    v = _Readback([], post_results=[_REFUSED])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r == _REFUSED
    assert len(_posts(v)) == 1


def test_could_not_look_cancels_nothing_so_restores_nothing():
    v = _Readback(_LIVE_SPY, post_results=[_REFUSED])
    r = _rearm(v, 8, sibling_qtys=None)                  # sibling sizes unreadable: nothing cancelled
    assert v.deletes() == [] and r == _REFUSED


def test_own_stop_only_is_restored_as_a_plain_gtc_stop():
    own_stop = {**_OCO8_STOP, "order_class": "simple"}
    v = _Readback([own_stop], post_results=[_REFUSED, _OK])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["restored"]["ok"] == 1
    _, restore = _posts(v)
    assert restore == {"symbol": "SPY", "qty": "8", "side": "sell", "type": "stop",
                       "time_in_force": "gtc", "stop_price": "763.69"}


def test_own_target_only_is_restored_as_a_plain_gtc_limit():
    own_tp = {**_OCO8, "order_class": "simple", "legs": None}
    v = _Readback([own_tp], post_results=[_REFUSED, _OK])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["restored"]["ok"] == 1
    _, restore = _posts(v)
    assert restore == {"symbol": "SPY", "qty": "8", "side": "sell", "type": "limit",
                       "time_in_force": "gtc", "limit_price": "840.65"}


def test_a_refused_restore_is_reported_never_raised_and_the_retcode_still_reads_refused(caplog):
    v = _Readback(_LIVE_SPY, post_results=[_REFUSED, {"retCode": 403, "retMsg": "still no shares"}])
    with caplog.at_level(logging.ERROR):
        r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 403
    assert r["restored"]["ok"] == 0 and r["restored"]["failed"]
    assert "FAILED" in r["retMsg"] and "still no shares" in r["retMsg"]
    assert any(rec.levelno == logging.ERROR for rec in caplog.records)


def test_a_raising_restore_post_is_contained():
    class _Raises(_Readback):
        def _request(self, method, path, json_body=None):  # type: ignore[override]
            if method == "POST" and len([c for c in self.calls if c[0] == "POST"]) >= 1:
                self.calls.append((method, path, json_body))
                raise RuntimeError("socket closed")
            return super()._request(method, path, json_body)
    v = _Raises(_LIVE_SPY, post_results=[_REFUSED])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 403 and r["restored"]["failed"] and "socket closed" in r["retMsg"]


_SIB_TP = {"id": "22222222-aaaa-4bbb-8ccc-000000000002", "symbol": "SPY",
           "order_class": "simple", "type": "limit", "side": "sell",
           "qty": "11", "limit_price": "830.43", "status": "new", "legs": None}


def test_released_sibling_target_is_restored_when_the_retry_is_also_refused():
    v = _Readback([_SIB_TP], post_results=[_REFUSED, _REFUSED, _OK])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 403
    assert v.deletes() == [_SIB_TP["id"]]
    posts = _posts(v)
    assert len(posts) == 3                                # OCO, retry OCO, restore of the sibling target
    assert posts[2] == {"symbol": "SPY", "qty": "11", "side": "sell", "type": "limit",
                        "time_in_force": "gtc", "limit_price": "830.43"}
    assert r["restored"]["ok"] == 1 and not r["restored"]["failed"]


def test_released_sibling_target_stays_released_when_the_retry_succeeds():
    """Documented, kept (manager 2026-11-17 06:02Z): arming the STOP outranks the sibling's target geometry."""
    v = _Readback([_SIB_TP], post_results=[_REFUSED, {"retCode": 0, "result": {"id": "oco-new"}}])
    r = _rearm(v, 8, sibling_qtys=[11])
    assert r["retCode"] == 0 and "restored" not in r
    assert v.deletes() == [_SIB_TP["id"]]
    assert len(_posts(v)) == 2


def test_a_sibling_bracket_or_stop_is_never_deleted_on_a_refusal():
    """A sibling STOP (or a target sharing its group) is never released, refusal or not."""
    v = _Readback(_LIVE_SPY, post_results=[_REFUSED, _OK])
    _rearm(v, 8, sibling_qtys=[11])
    deleted = v.deletes()
    assert not any(i in deleted for i in ("6682fcfd-ed19-41ab-984e-674189d2f8d1",
                                         "8b4956ce-1782-47cc-a6f0-379bddbe4aba"))


def test_cancel_row_protection_is_an_intended_cancel_and_restores_nothing():
    v = _Readback(_LIVE_SPY)
    r = AlpacaClient.cancel_row_protection(v, "SPY", qty=8, direction="long", sibling_qtys=[11])
    assert r["retCode"] == 0
    assert _posts(v) == []


# ---------------------------------------------------------------------------
# The order monitor raises ONE money-path ERROR alert when the restore also failed.
# ---------------------------------------------------------------------------
def test_restore_failure_raises_exactly_one_critical_alert_through_the_naked_position_path(monkeypatch, tmp_path):
    """The alert goes through execution_diagnostics (the naked-position alert's own surfaces):
    one operator-alert record and one pending ping, critical, naming account/symbol/trade_id."""
    from src.runtime import execution_diagnostics as ed
    appended: list = []
    monkeypatch.setattr(ed, "PENDING_PINGS_DIR", tmp_path / "pings")
    monkeypatch.setattr(ed, "_append_operator_alert", lambda kind, prio, body: appended.append((kind, prio, body)))
    monkeypatch.setattr(order_monitor, "_REARM_RESTORE_ALERT_AT", {})
    restored = {"attempted": 1, "ok": 0, "failed": ["own OCO: still no shares"], "summary": "x"}
    order_monitor._alert_rearm_restore_failed("alpaca_live", "SPY", 7001, restored)
    order_monitor._alert_rearm_restore_failed("alpaca_live", "SPY", 7001, restored)   # latched: same trade
    assert len(appended) == 1
    kind, prio, body = appended[0]
    assert kind == "rearm_restore_failed" and prio == "critical"
    for needle in ("alpaca_live", "SPY", "7001", "position may be unprotected", "still no shares"):
        assert needle in body, needle
    pings = list((tmp_path / "pings").glob("*-rearm-restore-failed.json"))
    assert len(pings) == 1                                                            # exactly one ping file
    import json
    payload = json.loads(pings[0].read_text())
    assert payload["priority"] == "critical" and "7001" in payload["body"]
    order_monitor._alert_rearm_restore_failed("alpaca_live", "SLV", 7002, restored)   # another trade: its own alert
    assert len(appended) == 2


def _sweep_with(monkeypatch, tmp_path, restored):
    """Run the real broker-naked sweep against a fake Alpaca whose re-arm is refused with *restored*."""
    from tests.test_alpaca_naked_rearm import _FakeAlpaca, _FakeDB, _insert

    class _Refusing(_FakeAlpaca):
        def place_protective(self, order):
            self.rearmed.append(order)
            return {"retCode": 403, "retMsg": "insufficient qty available", "restored": restored}

    db = _FakeDB(tmp_path / "j.db")
    _insert(db, id=7001, account_id="alpaca_live", symbol="SPY", direction="long",
            position_size=20, stop_loss=730.0, take_profit_1=818.5,
            created_at="2026-06-25T00:00:00+00:00", status="open")
    monkeypatch.setattr("src.bot.data_loaders.list_accounts",
                        lambda: [{"account_id": "alpaca_live", "exchange": "alpaca"}])
    fake = _Refusing(protected=False)
    monkeypatch.setattr("src.units.accounts.clients.alpaca_client_for", lambda acc: fake)
    alerts: list = []
    monkeypatch.setattr(order_monitor, "_alert_rearm_restore_failed",
                        lambda acct, sym, tid, rest: alerts.append((acct, sym, tid, rest)))
    summary = order_monitor._check_broker_naked_equity_positions(db)
    return summary, alerts


def test_sweep_alerts_when_the_refused_rearm_could_not_be_restored(monkeypatch, tmp_path):
    restored = {"attempted": 1, "ok": 0, "failed": ["own OCO: still no shares"], "summary": "x"}
    summary, alerts = _sweep_with(monkeypatch, tmp_path, restored)
    assert summary["rearmed"] == 0
    assert alerts == [("alpaca_live", "SPY", 7001, restored)]


def test_sweep_does_not_alert_when_the_refused_rearm_was_restored(monkeypatch, tmp_path):
    restored = {"attempted": 1, "ok": 1, "failed": [], "summary": "restored 1/1"}
    summary, alerts = _sweep_with(monkeypatch, tmp_path, restored)
    assert summary["rearmed"] == 0 and alerts == []
