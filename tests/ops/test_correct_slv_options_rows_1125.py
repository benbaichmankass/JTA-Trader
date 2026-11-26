"""correct-slv-options-rows-1125: the three 2026-11-25 alpaca_options_paper rows corrected from their venue fills."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cso", ROOT / "scripts/ops/correct_slv_options_rows_1125.py")
cso = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cso)


def _db(tmp_path, override=None):
    override = override or {}
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, account_id TEXT, symbol TEXT, direction TEXT, status TEXT,"
              " entry_price REAL, exit_price REAL, position_size REAL, pnl REAL, pnl_percent REAL, pnl_basis TEXT,"
              " exit_reason TEXT, stop_loss REAL, notes TEXT)")
    rows = [
        (8569, "alpaca_options_paper", "SLV", "short", "closed", 34.64, 35.535, 1.0, None, "sl_cross", 35.5, {"closed_by": "x"}),
        (8612, "alpaca_options_paper", "SLV261231P00034000", "short", "closed", 1.56, None, 1.0, None,
         "exit_coverage_no_strategy", None, {}),
        (8613, "alpaca_options_paper", "SLV261231P00035000", "long", "closed", 1.96, None, 1.0, None,
         "exit_coverage_no_strategy", None, {}),
    ]
    for r in rows:
        r = list(r)
        if r[0] in override:
            for k, v in override[r[0]].items():
                r[{"pnl": 8, "entry": 5, "status": 4}[k]] = v
        c.execute("INSERT INTO trades (id, account_id, symbol, direction, status, entry_price, exit_price, position_size,"
                  " pnl, exit_reason, stop_loss, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (*r[:11], json.dumps(r[11])))
    c.commit()
    return c


def _row(c, i):
    c.row_factory = sqlite3.Row
    r = dict(c.execute("SELECT * FROM trades WHERE id = ?", (i,)).fetchone())
    r["notes"] = json.loads(r["notes"])
    return r


def test_venue_arithmetic_with_the_contract_multiplier():
    assert cso.leg_pnl(cso.LEGS[8612], 1.0) == -2.00
    assert cso.leg_pnl(cso.LEGS[8613], 1.0) == -8.00


def test_dry_run_plans_three_rows_and_writes_nothing(tmp_path):
    c = _db(tmp_path)
    before = c.execute("SELECT * FROM trades ORDER BY id").fetchall()
    p = cso.plan(c)
    assert p["problems"] == [] and sorted(w["id"] for w in p["writes"]) == [8569, 8612, 8613]
    c.row_factory = None
    assert c.execute("SELECT * FROM trades ORDER BY id").fetchall() == [tuple(x) for x in before]


def test_apply_writes_the_venue_figures_and_the_unmeasured_declaration(tmp_path):
    c = _db(tmp_path)
    assert cso.apply(c, cso.plan(c), "2026-11-26T16:00:00+00:00") == 3
    a, b, parent = _row(c, 8612), _row(c, 8613), _row(c, 8569)
    assert (a["exit_price"], a["pnl"], a["pnl_basis"]) == (1.58, -2.00, "venue_fills_net")
    assert (b["exit_price"], b["pnl"], b["pnl_basis"]) == (1.88, -8.00, "venue_fills_net")
    assert a["notes"]["exit_fill"]["order_id"].startswith("4910cbab") and a["notes"]["exit_price_source"] == "exchange_fill"
    assert parent["pnl"] is None and parent["exit_reason"] == "entry_unfilled"
    assert parent["notes"]["pnl_source"] == "unmeasured" and parent["notes"]["pre_mark_exit_reason"] == "sl_cross"
    assert parent["notes"]["entry_filled_after_close"]["pnl_carried_on"] == [8612, 8613]
    assert parent["notes"]["closed_by"] == "x" and parent["stop_loss"] == 35.5          # existing fields kept
    assert cso.plan(c)["writes"] == [] and sorted(cso.plan(c)["skipped"]) == [8569, 8612, 8613]   # idempotent


@pytest.mark.parametrize("override", [{8612: {"pnl": -1.0}}, {8613: {"entry": 2.10}}, {8569: {"status": "open"}}])
def test_any_mismatch_refuses_and_writes_nothing(tmp_path, override):
    c = _db(tmp_path, override)
    p = cso.plan(c)
    assert p["problems"]
    snap = c.execute("SELECT * FROM trades ORDER BY id").fetchall()
    with pytest.raises(SystemExit):
        cso.apply(c, p, "2026-11-26T16:00:00+00:00")
    assert c.execute("SELECT * FROM trades ORDER BY id").fetchall() == snap
