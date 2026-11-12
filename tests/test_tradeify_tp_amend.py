"""CAP-TRADEIFY-TP-AMEND (operator 2026-11-12, decisions page w12 "Build it"): the browser DXtrade adapter (tradeify_1)
moves a take-profit as its own rollout step: SL untouched and resting, the TP kept on the profit side of the live
quote, typed into the same measured Position Details field the SL uses, and verified on the next read."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.prop.platform.base import Position
from src.prop.platform import dxtrade as dx

Q = {"bid": 100.0, "ask": 100.2}


def test_tp_step_guard():
    ok = dx.rollout_tp_mismatch
    assert ok("long", 95.0, 110.0, None, 112.0, Q) == []
    assert ok("short", 105.0, 90.0, None, 92.0, Q) == []
    assert ok("long", 95.0, 110.0, 95.0, 108.0, Q) == []                    # same SL passed back is fine
    assert any("stop loss unchanged" in x for x in ok("long", 95.0, 110.0, 96.0, 108.0, Q))
    assert any("not above the ask" in x for x in ok("long", 95.0, 110.0, None, 100.1, Q))   # would act as a close
    assert any("not below the bid" in x for x in ok("short", 105.0, 90.0, None, 100.05, Q))
    assert any("never added" in x for x in ok("long", 95.0, None, None, 110.0, Q))
    assert any("both brackets" in x for x in ok("long", None, 110.0, None, 112.0, Q))
    assert any("no live quote" in x for x in ok("long", 95.0, 110.0, None, 112.0, None))
    assert any("unchanged" in x for x in ok("long", 95.0, 110.0, None, 110.0, Q))


def test_tp_verify():
    before = Position(symbol="ETH/USD", side="long", quantity=0.01, stop_loss=95.0, take_profit=110.0)
    good = Position(symbol="ETH/USD", side="long", quantity=0.01, stop_loss=95.0, take_profit=112.0)
    assert dx.rollout_verify_tp_mismatch(before, good, 112.0) == []
    moved_sl = Position(symbol="ETH/USD", side="long", quantity=0.01, stop_loss=96.0, take_profit=112.0)
    assert any("SL reads" in x for x in dx.rollout_verify_tp_mismatch(before, moved_sl, 112.0))
    lost_sl = Position(symbol="ETH/USD", side="long", quantity=0.01, stop_loss=None, take_profit=112.0)
    assert any("SL reads" in x for x in dx.rollout_verify_tp_mismatch(before, lost_sl, 112.0))
    assert any("TP reads" in x for x in dx.rollout_verify_tp_mismatch(before, before, 112.0))
    assert dx.rollout_verify_tp_mismatch(before, None, 112.0) == ["position not found on the next read"]


class _Loc:
    def blur(self):
        pass


class _Page:
    """Records typed fields; the panel and rows are served by the patched adapter readers."""
    def __init__(self):
        self.filled: Dict[str, str] = {}
        self.clicks: List[str] = []

    def click(self, sel, timeout=None):
        self.clicks.append(sel)

    def fill(self, sel, val, timeout=None):
        self.filled[sel] = val

    def locator(self, sel):
        return _Loc()

    def wait_for_timeout(self, ms):
        pass


def _adapter(monkeypatch, after_tp):
    a = dx.DXtradeAdapter()
    pos = Position(symbol="ETH/USD", side="long", quantity=0.01, stop_loss=95.0, take_profit=110.0)
    monkeypatch.setattr(a, "read_one_click", lambda page: {"state": "off"})
    monkeypatch.setattr(a, "_locate_edit_control", lambda *x: {"ok": True})
    monkeypatch.setattr(a, "read_quote", lambda page, sym: dict(Q))
    panel = {"ok": True}
    monkeypatch.setattr(a, "_read_position_panel", lambda page: panel)
    monkeypatch.setattr(dx, "position_panel_mismatch", lambda *x, **k: [])
    monkeypatch.setattr(dx, "verify_form_values", lambda fields, want: [])
    monkeypatch.setattr(a, "_confirm_dialog", lambda page: None)
    monkeypatch.setattr(a, "read_positions", lambda page: [Position(symbol="ETH/USD", side="long", quantity=0.01,
                                                                     stop_loss=95.0, take_profit=after_tp)])
    return a, pos


def test_an_armed_tp_step_types_only_the_tp_and_verifies(monkeypatch, tmp_path: Path):
    a, pos = _adapter(monkeypatch, 112.0)
    page, ro = _Page(), dx.ModifyRollout(tmp_path / "modify_rollout.json")
    r = a.modify_bracket(page, pos, None, 112.0, arm=True, rollout=ro)
    assert r["ok"] and r["rollout"] == "verified" and "new TP" in r["why"], r
    assert list(page.filled) == ["[data-metis-pp] [data-metis-pp-field=take_profit]"]     # the SL is never typed
    assert ro.last()["state"] == "verified" and ro.last()["tp"] == 112.0


def test_a_tp_step_that_does_not_read_back_is_verify_failed(monkeypatch, tmp_path: Path):
    a, pos = _adapter(monkeypatch, 110.0)
    r = a.modify_bracket(_Page(), pos, None, 112.0, arm=True, rollout=dx.ModifyRollout(tmp_path / "m.json"))
    assert not r["ok"] and r["rollout"] == "verify_failed" and "TP reads" in r["why"]


def test_a_tp_through_the_price_is_refused_before_any_click(monkeypatch, tmp_path: Path):
    a, pos = _adapter(monkeypatch, 100.0)
    page = _Page()
    r = a.modify_bracket(page, pos, None, 100.1, arm=True, rollout=dx.ModifyRollout(tmp_path / "m.json"))
    assert not r["ok"] and not r["clicked"] and "rollout refused" in r["why"] and page.clicks == []


def test_an_sl_step_is_unchanged_tighten_only(monkeypatch, tmp_path: Path):
    a, pos = _adapter(monkeypatch, 110.0)
    r = a.modify_bracket(_Page(), pos, 90.0, None, arm=True, rollout=dx.ModifyRollout(tmp_path / "m.json"))
    assert not r["ok"] and "tighten only" in r["why"]                      # a looser stop is still refused


def test_the_flag_is_flipped_with_the_step():
    assert dx.DXtradeAdapter.TP_AMEND_SUPPORTED is True
