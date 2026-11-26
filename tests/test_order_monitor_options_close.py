"""AUD-20261125-OPTIONS-CLOSE-LEAVES-LEGS: a monitor-decided close of an options-expression row must liquidate the
structure's option legs (not the equity underlying) and must report ok only when EVERY leg is closed."""
from __future__ import annotations

import json

from src.runtime import order_monitor as om

OPT_CFG = {"account_id": "alpaca_options_paper", "exchange": "alpaca", "mode": "live",
           "options": {"enabled": True, "express_as": "debit_vertical"}}
EQ_CFG = {"account_id": "alpaca_paper", "exchange": "alpaca", "mode": "live", "options": None}
LEGS = ["SLV261231P00034000", "SLV261231P00035000"]


def _trade(with_legs=True):
    notes = {"options": {"structure": "debit_vertical", "legs": [
        {"symbol": s, "side": "buy" if i == 0 else "sell"} for i, s in enumerate(LEGS)]}} if with_legs else {}
    return {"id": 8569, "account_id": "alpaca_options_paper", "symbol": "SLV", "direction": "short",
            "position_size": 2, "notes": json.dumps(notes)}


class _Exec:
    def __init__(self, failed=()):
        self.calls, self.failed = [], list(failed)

    def close_structure(self, occ):
        self.calls.append(list(occ))
        if self.failed:
            return {"retCode": 1, "result": {"closed": [], "failed": [{"symbol": s} for s in self.failed]}}
        return {"retCode": 0, "result": {"closed": [s.upper() for s in occ], "failed": []}}


def _patch(monkeypatch, cfg, executor, equity_calls):
    monkeypatch.setattr(om, "_build_account_client", lambda aid: (object(), cfg))
    monkeypatch.setattr(om, "_options_executor_for", lambda c: executor)
    import src.units.accounts.execute as ex
    import src.units.accounts.clients as cl
    monkeypatch.setattr(cl, "account_supports_management", lambda c, op: True)
    monkeypatch.setattr(ex, "close_open_position", lambda *a, **k: equity_calls.append(k) or {"ok": True})


def test_options_row_closes_every_leg_not_the_underlying(monkeypatch):
    eq, exe = [], _Exec()
    _patch(monkeypatch, OPT_CFG, exe, eq)
    out = om._send_close_to_exchange(_trade())
    assert out["ok"] is True and exe.calls == [LEGS]
    assert eq == []                                   # the equity close of the underlying is NOT sent


def test_a_failed_leg_is_not_ok_so_the_row_stays_open(monkeypatch):
    eq, exe = [], _Exec(failed=[LEGS[1]])
    _patch(monkeypatch, OPT_CFG, exe, eq)
    out = om._send_close_to_exchange(_trade())
    assert out["ok"] is False and "options_leg_close_failed" in out["error"] and eq == []


def test_no_executor_is_not_ok(monkeypatch):
    eq = []
    _patch(monkeypatch, OPT_CFG, None, eq)
    out = om._send_close_to_exchange(_trade())
    assert out == {"ok": False, "error": "options_executor_unavailable"} and eq == []


def test_equity_account_still_uses_the_equity_close(monkeypatch):
    eq, exe = [], _Exec()
    _patch(monkeypatch, EQ_CFG, exe, eq)
    out = om._send_close_to_exchange({**_trade(), "account_id": "alpaca_paper"})
    assert out["ok"] is True and exe.calls == [] and len(eq) == 1


def test_options_row_without_recorded_legs_falls_back_unchanged(monkeypatch):
    eq, exe = [], _Exec()
    _patch(monkeypatch, OPT_CFG, exe, eq)
    out = om._send_close_to_exchange(_trade(with_legs=False))
    assert out["ok"] is True and exe.calls == [] and len(eq) == 1
