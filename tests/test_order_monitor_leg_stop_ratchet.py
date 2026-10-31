"""TRAIL-RATCHET-AUDIT: a trail amend never loosens a leg's own (tighter) stop.

The strategy monitors ratchet against the PACKAGE stop. That stop does not move while a sibling leg's amend
failed, so a leg that already applied a tighter stop could be sent a looser candidate. The order monitor now
treats the leg's own synced `trades.stop_loss` as a floor, exactly like `notes.sl_floor`.
"""
from __future__ import annotations

from src.runtime import order_monitor as om
from tests.test_order_monitor_package_legs import FakeDB


def _leg(tid, account, sl, direction):
    return {"id": tid, "account_id": account, "order_package_id": "P", "status": "open",
            "stop_loss": sl, "position_size": 1.0, "symbol": "ETHUSDT", "direction": direction,
            "strategy_name": "trend_donchian_eth_4h", "is_backtest": 0}


def _run(monkeypatch, legs, new_sl, pkg_sl, direction):
    sent = []
    db = FakeDB(legs)
    monkeypatch.setattr(om, "_send_modify_to_exchange",
                        lambda leg, **kw: sent.append((leg["id"], kw.get("sl"))) or {"ok": True})
    pkg = {"order_package_id": "P", "linked_trade_id": legs[0]["id"], "status": "open", "sl": pkg_sl,
           "tp": 1.0, "strategy_name": "trend_donchian_eth_4h", "symbol": "ETHUSDT", "direction": direction}
    om._apply_update(db, pkg, {"sl": new_sl}, om._StrategyTickSummary())
    return sent


def test_long_leg_with_tighter_own_stop_is_not_loosened(monkeypatch):
    # package stop 100 (sibling failed), leg 1 already at 108; candidate 105 > pkg 100 but < 108.
    sent = _run(monkeypatch, [_leg(1, "a", 108.0, "long"), _leg(2, "b", 100.0, "long")], 105.0, 100.0, "long")
    assert sent == [(2, 105.0)], sent  # leg 1 is never sent the looser level


def test_short_leg_with_tighter_own_stop_is_not_loosened(monkeypatch):
    sent = _run(monkeypatch, [_leg(1, "a", 92.0, "short"), _leg(2, "b", 100.0, "short")], 95.0, 100.0, "short")
    assert sent == [(2, 95.0)], sent


def test_tightening_candidate_still_reaches_every_leg(monkeypatch):
    # negative control: candidate tighter than every leg's own stop is sent to both.
    sent = _run(monkeypatch, [_leg(1, "a", 108.0, "long"), _leg(2, "b", 100.0, "long")], 110.0, 100.0, "long")
    assert sorted(sent) == [(1, 110.0), (2, 110.0)], sent
