"""AMEND-PARITY-ALPACA-TRAIL-READBACK — the monitor-trail SL modify on Alpaca
is verified at the venue.

``execute.modify_open_order``'s alpaca branch used to treat a
``modify_protective`` 2xx as success. A stop move carrying the trade's qty and
direction now goes through ``alpaca_amend.tighten(apply=True)`` (#20150's
executor): ``ok`` only on a venue read-back, a looser stop is a no-op, a
partially filled bracket is refused, and a refusal / failed read-back pages the
operator for that one trade (throttled) while the monitor retries next tick.

The fake venue is ``tests/test_alpaca_amend.FakeAlpaca`` (PATCH replaces the
order, the stop rests ``held``), made an ``AlpacaClient`` so the branch's
isinstance check passes. Nothing here touches a network.
"""
from __future__ import annotations

import pytest

from src.units.accounts import execute
from src.units.accounts.alpaca_client import AlpacaClient
from src.units.accounts.execute import modify_open_order
from tests.test_alpaca_amend import FakeAlpaca, _oco

CFG = {"account_id": "alpaca_paper", "exchange": "alpaca", "mode": "live"}


class FakeAlpacaClient(FakeAlpaca, AlpacaClient):
    """FakeAlpaca's venue model, typed as an AlpacaClient. ``modify_protective``
    (the TP path and the legacy path) is recorded, never sent."""

    def __init__(self, *a, mp_rc=0, **kw):
        FakeAlpaca.__init__(self, *a, **kw)
        self.mp_calls = []
        self.mp_rc = mp_rc

    def modify_protective(self, symbol, sl=None, tp=None, qty=None):
        self.mp_calls.append({"symbol": symbol, "sl": sl, "tp": tp, "qty": qty})
        if self.mp_rc:
            return {"retCode": self.mp_rc, "retMsg": "target rejected"}
        return {"retCode": 0, "result": {"patched": ["tp-1"]}}


@pytest.fixture(autouse=True)
def pings(monkeypatch):
    sent = []
    monkeypatch.setattr("src.runtime.notify.send_telegram_direct",
                        lambda msg, **kw: sent.append(msg) or True)
    execute._ALPACA_READBACK_ALERT_AT.clear()
    yield sent
    execute._ALPACA_READBACK_ALERT_AT.clear()


def _modify(client, **kw):
    args = {"symbol": "SPY", "side": "long", "qty": 10.0, "trade_id": 41}
    args.update(kw)
    return modify_open_order(client, CFG, **args)


def test_readback_success_is_ok(pings):
    c = FakeAlpacaClient(legs=_oco(stop=100.0))
    res = _modify(c, sl=102.0)
    assert res["ok"] is True and res["error"] is None
    assert res["readback"] == "applied"
    assert c.patches == [("sl-1", {"stop_price": "102.00"})]
    assert res["exchange_response"]["sl"]["venue_after"] == 102.0
    assert c.mp_calls == []          # the stop never took the unverified path
    assert pings == []


def test_2xx_but_ineffective_is_not_ok_and_pings(pings):
    # Alpaca 2xx-accepts the PATCH and nothing moves (PI-20261002-APBY4NTV-0001).
    c = FakeAlpacaClient(legs=_oco(stop=100.0), patch_effective=False)
    res = _modify(c, sl=102.0)
    assert res["ok"] is False
    assert res["readback"] == "apply_failed"
    assert "still rests" in res["error"]
    assert len(pings) == 1 and "alpaca_paper SPY long" in pings[0]
    assert "trade=41" in pings[0]
    # The monitor retries every tick; the page is throttled per trade.
    res2 = _modify(c, sl=102.0)
    assert res2["ok"] is False and len(pings) == 1


def test_negative_control_same_setup_effective_patch_is_ok(pings):
    """The ineffective case fails BECAUSE of the read-back: flip only
    ``patch_effective`` and the identical call succeeds."""
    c = FakeAlpacaClient(legs=_oco(stop=100.0), patch_effective=True)
    assert _modify(c, sl=102.0)["ok"] is True
    assert pings == []


def test_partially_filled_bracket_is_refused_nothing_sent(pings):
    c = FakeAlpacaClient(legs=_oco(stop=100.0), partial_parent_legs=["sl-1", "tp-1"])
    res = _modify(c, sl=102.0)
    assert res["ok"] is False and res["readback"] == "refused"
    assert "parent_partially_filled" in res["error"]
    assert c.patches == [] and c.mp_calls == []
    assert len(pings) == 1


def test_looser_stop_is_refused_as_noop_never_sent(pings):
    c = FakeAlpacaClient(legs=_oco(stop=100.0))
    for lvl in (99.0, 100.0):
        res = _modify(c, sl=lvl)
        assert res["ok"] is True, res
        assert res["readback"] == "noop_already_at_or_tighter"
        assert res["venue_sl"] == 100.0
    assert c.patches == [] and c.mp_calls == []
    assert pings == []


def test_wedged_stop_through_market_is_refused_and_pings(pings):
    # The GLD wedge shape: the resting stop is through the mark.
    c = FakeAlpacaClient(legs=_oco(stop=106.0))  # long, mark 105
    res = _modify(c, sl=104.0)
    assert res["ok"] is False and "venue_stop_through_market" in res["error"]
    assert c.patches == [] and len(pings) == 1


def test_could_not_look_is_not_ok_and_does_not_page(pings):
    c = FakeAlpacaClient(legs=_oco(stop=100.0))
    c.position = {"state": "could_not_look"}
    res = _modify(c, sl=102.0)
    assert res["ok"] is False and res["readback"] == "could_not_look"
    assert c.patches == [] and pings == []


def test_short_via_sell_spelling_tightens_down(pings):
    c = FakeAlpacaClient(legs=_oco(stop=110.0, tp=90.0, side="buy"),
                         position={"state": "open", "qty": 10.0, "side": "short",
                                   "current_price": 105.0})
    res = _modify(c, side="sell", sl=108.0)
    assert res["ok"] is True and c.patches == [("sl-1", {"stop_price": "108.00"})]


def test_sl_and_tp_stop_verified_then_target_patched(pings):
    c = FakeAlpacaClient(legs=_oco(stop=100.0, tp=120.0))
    res = _modify(c, sl=102.0, tp=118.0)
    assert res["ok"] is True
    assert c.patches == [("sl-1", {"stop_price": "102.00"})]
    assert c.mp_calls == [{"symbol": "SPY", "sl": None, "tp": 118.0, "qty": 10.0}]


def test_target_failure_after_stop_applied_is_not_ok(pings):
    c = FakeAlpacaClient(legs=_oco(stop=100.0), mp_rc=422)
    res = _modify(c, sl=102.0, tp=118.0)
    assert res["ok"] is False and "target PATCH failed" in res["error"]
    assert res["readback"] == "applied"


def test_tp_only_keeps_modify_protective_path(pings):
    c = FakeAlpacaClient(legs=_oco())
    res = _modify(c, tp=118.0)
    assert res["ok"] is True
    assert c.patches == []
    assert c.mp_calls == [{"symbol": "SPY", "sl": None, "tp": 118.0, "qty": 10.0}]


def test_no_qty_keeps_legacy_path(pings):
    c = FakeAlpacaClient(legs=_oco())
    res = _modify(c, sl=102.0, qty=None)
    assert res["ok"] is True and c.patches == []
    assert c.mp_calls == [{"symbol": "SPY", "sl": 102.0, "tp": None, "qty": None}]


def test_monitor_seam_reports_failed_readback(monkeypatch, pings):
    """End to end through the order monitor's modify seam: the leg row's
    direction + position_size reach the read-back, and a 2xx-ineffective PATCH
    comes back ok=False (the monitor then leaves the package level unchanged
    and retries next tick)."""
    from src.runtime import order_monitor as om

    c = FakeAlpacaClient(legs=_oco(stop=100.0), patch_effective=False)
    monkeypatch.setattr(om, "_build_account_client", lambda a: (c, dict(CFG)))
    res = om._send_modify_to_exchange(
        {"id": 41, "account_id": "alpaca_paper", "symbol": "SPY",
         "direction": "long", "position_size": 10},
        sl=102.0, side="long", qty=10.0,
    )
    assert res["ok"] is False and res["readback"] == "apply_failed"
    assert len(pings) == 1
