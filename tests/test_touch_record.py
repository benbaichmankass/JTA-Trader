"""DESK-12-SANDBOX: the touch record projection, the soak's untouched-only count, the R3 and
live-vs-backtest splits. Positive controls plant a touch; the live journal has none yet (MEASURED 2026-10-26:
0 of 1583 closed bybit_1 trades), so a quiet probe on live data proves nothing without these."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "research"):
    sys.path.insert(0, str(p))

import r3_cost_fidelity as r3  # noqa: E402
import soak_state as ss  # noqa: E402
import touch_split as ts  # noqa: E402
import touch_record as tr  # noqa: E402

AMEND = {"source": "live_review_mandate", "mandate": "MD-LIVE-TIGHTEN-SL", "review_id": "LR-1", "at": "2026-10-26T10:00:00Z",
         "from": 95.0, "to": 98.0, "venue_before": 95.0, "venue_after": 98.0}


def trade(i, amends=None, acct="bybit_1", leg="ada_pullback_2h", pnl=10.0):
    notes = {"sl_amends": amends} if amends is not None else {}
    return {"id": i, "account_id": acct, "strategy_name": leg, "status": "closed", "is_backtest": 0,
            "order_package_id": f"pkg-{i}", "direction": "long", "entry_price": 100.0, "stop_loss": 98.0,
            "take_profit_1": 110.0, "position_size": 1.0, "pnl": pnl, "symbol": "ADAUSDT", "notes": json.dumps(notes),
            "exit_reason": "tp", "exit_price": 110.0, "sl_order_id": "s", "tp_order_id": "t", "closed_at": "2026-10-26T11:00:00Z", "fee_taker_usd": 0.1}


def test_untouched_trade_has_no_record():
    assert tr.touches(trade(1)) == [] and not tr.is_touched(trade(1))


def test_ltr_amend_is_a_touch_with_the_design_fields():
    (r,) = tr.touches(trade(2, [AMEND]))
    assert r["source"] == "ltr_apply" and r["account"] == "bybit_1" and r["order_package_id"] == "pkg-2"
    assert (r["level_before"], r["level_after"], r["applied_at"], r["verdict"]) == (95.0, 98.0, AMEND["at"], "applied")
    assert r["intent_id"] is None and r["decision_id"] is None  # never invented


def test_desk_fields_pass_through_and_source_classified():
    a = dict(AMEND, source="claude_desk", decision_id="DD-20261026T1000Z-x", intent_id="i-1")
    (r,) = tr.touches(trade(3, [a]))
    assert r["source"] == "desk" and r["decision_id"] == "DD-20261026T1000Z-x" and r["intent_id"] == "i-1"
    assert tr.classify_source("manual_amend_operator") == "manual"


def test_unparseable_notes_is_untouched_not_a_crash():
    t = trade(4)
    t["notes"] = "{not json"
    assert tr.touches(t) == []


def test_split_is_a_partition():
    rows = [trade(1), trade(2, [AMEND]), trade(3)]
    u, t = tr.split(rows)
    assert len(u) + len(t) == len(rows) and [x["id"] for x in t] == [2]


def test_soak_grade_marks_touched_and_evaluate_excludes_it():
    g_t, g_u = ss.grade_trade(trade(2, [AMEND])), ss.grade_trade(trade(1))
    assert g_t["touched"] is True and g_u["touched"] is False
    assert g_t["clean"] is True  # graded and shown ...
    ev = ss.evaluate([g_t, g_u], 2)  # ... but never one of the leg's clean trades
    assert ev["state"] == "in_progress" and ev["clean"] == [1] and ev["touched"] == [2]
    assert ss.evaluate([g_t], 1)["state"] == "awaiting_first_trade"


def test_r3_cell_is_untouched_only_with_touched_beside(tmp_path, monkeypatch):
    t_ok, t_touch = trade(1), trade(2, [AMEND])
    (tmp_path / "trades.json").write_text(json.dumps([t_ok, t_touch]))
    rows = [{"trade_id": i, "side": s, "bps": b, "strategy": "ada_pullback_2h", "account_id": "bybit_1",
             "ref_source": "order_packages", "venue": "bybit_perps"} for i, b in ((1, 1.0), (2, 99.0)) for s in ("entry", "exit")]
    monkeypatch.setattr(r3.d3, "measure", lambda _d: {"rows": rows, "excluded": {}})
    res = r3.run(tmp_path, datetime.now(timezone.utc))
    (cell,) = [c for c in res["per_leg"]["ada_pullback_2h"]["cells"] if c["account_id"] == "bybit_1"]
    assert cell["n_entry"] == 1 and cell["entry_mean"] == 1.0  # the 99 bps touched fill is not in the verdict
    assert cell["touched_split"]["n_touched_trades"] == 1 and cell["touched_split"]["entry_mean"] == 99.0


def test_split_report_counts_and_grading_hook():
    pk = [{"order_package_id": f"pkg-{i}", "meta": "{}"} for i in (1, 2)]
    b = ts.build([trade(1), trade(2, [dict(AMEND, decision_id="DD-20261026T1000Z-x")]), trade(9, acct="bybit_2")], pk)
    p = b["population"]
    assert (p["touched_trades"], p["untouched_trades"], p["closed_non_backtest_on_accounts"]) == (1, 1, 2)
    (leg,) = b["legs"]
    assert leg["split"]["touched"]["closed"] == 1 and len(b["touch_records"]) == 1
    assert leg["grading"]["applied"][0]["key"] == "DD-20261026T1000Z-x" and leg["grading"]["control"]["n"] == 1
    assert "1 touched / 1 untouched" in ts.render(b)
