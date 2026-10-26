"""`rearm_ib_protective.py` — arm BOTH brackets on a FULLY naked IB position.

Built 2026-10-26 for ib_paper/MGC (short 12, no stop, no TP; journal row 6673
says 14). Every refusal is exercised here so the first run of the code is not a
live dispatch (the attach-ib-target lesson, BL-20260817).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "rearm_ib_protective", _ROOT / "scripts" / "ops" / "rearm_ib_protective.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ROW = {"id": 6673, "symbol": "MGC", "direction": "short", "position_size": 14.0,
       "stop_loss": 4270.02857143, "take_profit_1": 3766.9909}


def _broker(**over):
    b = {"positions": [{"local_symbol": "MGCZ6", "con_id": 1, "position": -12.0}],
         "orders": [], "contract_local_symbol": "MGCZ6", "mark": 4025.8}
    b.update(over)
    return b


@pytest.fixture
def mod(monkeypatch):
    m = _load()
    monkeypatch.setattr(m, "_load_account", lambda a: {"account_id": a,
                                                      "exchange": "interactive_brokers"})
    monkeypatch.setattr(m, "_open_rows", lambda a, s: [dict(ROW)])
    monkeypatch.setattr(m, "_tick", lambda s: 0.1)
    m._placed = []

    def _place(cfg, **kw):
        m._placed.append(kw)
        return {"retCode": 0}
    monkeypatch.setattr(m, "_place", _place)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    return m


def _run(m, capsys, monkeypatch, broker, *extra, after=None):
    seq = [broker] + ([after] if after is not None else [])
    calls = {"n": 0}

    def _br(cfg, sym):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]
    monkeypatch.setattr(m, "_broker_read", _br)
    code = m.main(["--account", "ib_paper", "--symbol", "MGC", "--row", "6673", *extra])
    return code, json.loads(capsys.readouterr().out)


def test_dry_run_ready_sizes_to_broker_qty(mod, capsys, monkeypatch):
    code, out = _run(mod, capsys, monkeypatch, _broker())
    assert code == 0 and out["state"] == "ready" and out["qty"] == 12.0
    assert "BUY STP 12.0 @ 4270.02857143" in out["would"]
    assert out["oca_group"] == "oca-protect-t6673" and mod._placed == []


def test_refuses_when_any_order_rests_on_symbol(mod, capsys, monkeypatch):
    o = {"symbol": "MGC", "order_type": "STP", "status": "Submitted"}
    code, out = _run(mod, capsys, monkeypatch, _broker(orders=[o]), "--apply")
    assert code == 4 and out["state"] == "refused" and mod._placed == []


def test_cancelled_row_is_not_resting(mod, capsys, monkeypatch):
    o = {"symbol": "MGC", "order_type": "STP", "status": "Cancelled"}
    code, out = _run(mod, capsys, monkeypatch, _broker(orders=[o]))
    assert code == 0 and out["state"] == "ready"


def test_other_symbol_orders_ignored(mod, capsys, monkeypatch):
    o = {"symbol": "MHG", "order_type": "STP", "status": "Submitted"}
    code, out = _run(mod, capsys, monkeypatch, _broker(orders=[o]))
    assert code == 0


@pytest.mark.parametrize("over,code", [
    ({"orders": None}, 2),
    ({"positions": None}, 2),
    ({"positions": []}, 4),
    ({"positions": [{"local_symbol": "MGCZ6", "position": 12.0}]}, 4),   # long vs short
    ({"positions": [{"local_symbol": "MGCZ6", "position": -15.0}]}, 4),  # > journal 14
    ({"contract_local_symbol": "MGCG7"}, 4),                             # wrong month
    ({"mark": 4300.0}, 4),                                               # above the stop
    ({"mark": None}, 4),                                                 # unreadable mark
])
def test_refusals(mod, capsys, monkeypatch, over, code):
    c, out = _run(mod, capsys, monkeypatch, _broker(**over), "--apply")
    assert c == code and mod._placed == []


def test_unreadable_mark_waiver_is_explicit(mod, capsys, monkeypatch):
    c, out = _run(mod, capsys, monkeypatch, _broker(mark=None), "--allow-unverified-mark")
    assert c == 0 and out["mark_check"].startswith("SKIPPED")


def test_refuses_two_open_rows_or_wrong_row(mod, capsys, monkeypatch):
    monkeypatch.setattr(mod, "_open_rows", lambda a, s: [dict(ROW), dict(ROW, id=7000)])
    c, _ = _run(mod, capsys, monkeypatch, _broker(), "--apply")
    assert c == 4
    monkeypatch.setattr(mod, "_open_rows", lambda a, s: [dict(ROW, id=7000)])
    c, _ = _run(mod, capsys, monkeypatch, _broker(), "--apply")
    assert c == 4 and mod._placed == []


def test_refuses_missing_tp(mod, capsys, monkeypatch):
    monkeypatch.setattr(mod, "_open_rows", lambda a, s: [dict(ROW, take_profit_1=None)])
    c, _ = _run(mod, capsys, monkeypatch, _broker(), "--apply")
    assert c == 4 and mod._placed == []


def _legs(sl=4270.0, tp=3767.0, group="oca-protect-t6673", qty=12.0):
    return [
        {"symbol": "MGC", "order_type": "STP", "status": "PreSubmitted",
         "aux_price": sl, "lmt_price": 0.0, "oca_group": group, "total_quantity": qty},
        {"symbol": "MGC", "order_type": "LMT", "status": "Submitted",
         "aux_price": 0.0, "lmt_price": tp, "oca_group": group, "total_quantity": qty},
    ]


def test_apply_places_journal_levels_and_verifies(mod, capsys, monkeypatch):
    c, out = _run(mod, capsys, monkeypatch, _broker(), "--apply",
                  after=_broker(orders=_legs()))
    assert c == 0 and out["state"] == "rearmed"
    assert mod._placed == [{"account_id": "ib_paper", "symbol": "MGC",
                            "direction": "short", "qty": 12.0,
                            "sl": 4270.02857143, "tp": 3766.9909, "row_id": 6673}]


def test_apply_unverified_when_legs_wrong(mod, capsys, monkeypatch):
    c, out = _run(mod, capsys, monkeypatch, _broker(), "--apply",
                  after=_broker(orders=_legs(qty=14.0)))
    assert c == 3 and out["state"] == "placed_unverified"


def test_apply_unconfirmed_when_reread_fails(mod, capsys, monkeypatch):
    c, out = _run(mod, capsys, monkeypatch, _broker(), "--apply",
                  after=_broker(orders=None))
    assert c == 3 and out["state"] == "placed_unconfirmed"


def test_place_rejected(mod, capsys, monkeypatch):
    monkeypatch.setattr(mod, "_place", lambda cfg, **kw: {"retCode": 1, "retMsg": "x"})
    c, out = _run(mod, capsys, monkeypatch, _broker(), "--apply")
    assert c == 1 and out["state"] == "place_failed"
