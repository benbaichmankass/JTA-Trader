"""SOAK CONTRACT: every soak carries a MECHANICAL definition of done (operator
2026-10-15: a soak passes on 1-2 clean trades; no calendar, no sample size), and
its state is computed live from the journal — never from a stale or wrong DB."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ops"))
sys.path.insert(0, str(REPO / "scripts" / "ci"))

import check_soak_contracts as guard  # noqa: E402
import soak_state as ss  # noqa: E402

_TRADE_COLS = ("id", "account_id", "strategy_name", "status", "is_backtest", "closed_at", "created_at",
               "order_package_id", "direction", "position_size", "entry_price", "stop_loss",
               "take_profit_1", "sl_order_id", "tp_order_id", "exit_reason", "exit_price", "pnl",
               "fee_taker_usd", "fee_maker_usd", "cost_source", "reconcile_status",
               "protection_repairs", "protection_repair_last_kind", "notes")


def _trade(i: int, reason: str = "sl", **kw) -> dict:
    t = {"id": i, "account_id": "bybit_1", "strategy_name": "leg", "status": "closed",
         "is_backtest": 0, "closed_at": f"2026-10-0{i}T00:00:00", "created_at": "2026-10-01T00:00:00",
         "order_package_id": f"p{i}", "direction": "long", "position_size": 1.0, "entry_price": 100.0,
         "stop_loss": 95.0, "take_profit_1": 110.0, "sl_order_id": "s", "tp_order_id": "t",
         "exit_reason": reason, "exit_price": 95.0, "pnl": -5.0, "fee_taker_usd": 0.1,
         "fee_maker_usd": None, "cost_source": "estimate", "reconcile_status": None,
         "protection_repairs": None, "protection_repair_last_kind": None, "notes": "{}"}
    t.update(kw)
    return t


def _db(tmp_path: Path, newest_pkg: str, trades=()) -> str:
    p = tmp_path / "j.db"
    c = sqlite3.connect(p)
    c.execute(f"CREATE TABLE trades ({', '.join(_TRADE_COLS)})")
    c.execute("CREATE TABLE order_packages (order_package_id, strategy_name, created_at, direction, "
              "entry, sl, tp, exit_plan)")
    for t in trades:
        c.execute(f"INSERT INTO trades VALUES ({','.join('?' * len(_TRADE_COLS))})",
                  [t[k] for k in _TRADE_COLS])
    c.execute("INSERT INTO order_packages (order_package_id, strategy_name, created_at) VALUES "
              "('x', 'other', ?)", (newest_pkg,))
    c.commit()
    c.close()
    return str(p)


def _contracts(tmp_path: Path, **kw) -> Path:
    c = ss.make_contract(kind="stage1", leg="leg", account="bybit_1", started="2026-10-01", **kw)
    p = tmp_path / "SOAKS.json"
    p.write_text(json.dumps({"soaks": [c]}))
    return p


def test_stale_journal_is_unknown_never_awaiting(tmp_path):
    db = _db(tmp_path, "2026-01-01T00:00:00")
    rows = ss.soak_states(today=date(2026, 10, 4), db_path=db, contracts_path=_contracts(tmp_path))
    assert rows[0]["state"] == "unknown"
    assert "not live" in rows[0]["reason"]


def test_no_trade_yet_is_awaiting_not_failing(tmp_path):
    db = _db(tmp_path, "2026-10-04T00:00:00")
    rows = ss.soak_states(today=date(2026, 10, 4), db_path=db, contracts_path=_contracts(tmp_path))
    assert rows[0]["state"] == "awaiting_first_trade"


def test_two_clean_trades_pass(tmp_path):
    db = _db(tmp_path, "2026-10-04T00:00:00", [_trade(2), _trade(3, "tp", exit_price=110.0)])
    rows = ss.soak_states(today=date(2026, 10, 4), db_path=db,
                          contracts_path=_contracts(tmp_path, n_needed=2))
    assert rows[0]["state"] == "passed" and rows[0]["progress"] == "2/2 clean"


def test_a_reconciler_close_after_clean_trades_is_a_mechanical_fail(tmp_path):
    db = _db(tmp_path, "2026-10-04T00:00:00", [_trade(2), _trade(3), _trade(4, "reconciler_filled")])
    rows = ss.soak_states(today=date(2026, 10, 4), db_path=db, contracts_path=_contracts(tmp_path))
    assert rows[0]["state"] == "mechanical_fail" and "reconciler_filled" in rows[0]["reason"]


def test_one_clean_trade_passes_by_default(tmp_path):
    db = _db(tmp_path, "2026-10-04T00:00:00", [_trade(2)])
    rows = ss.soak_states(today=date(2026, 10, 4), db_path=db, contracts_path=_contracts(tmp_path))
    assert rows[0]["state"] == "passed"


def test_every_row_has_the_agreed_interface_keys(tmp_path):
    rows = ss.soak_states(today=date(2026, 10, 4), db_path=str(tmp_path / "absent.db"),
                          contracts_path=_contracts(tmp_path))
    for k in ("id", "leg", "account", "state", "started", "n_needed", "progress", "reason"):
        assert k in rows[0]
    assert rows[0]["state"] == "unknown"


def test_calendar_and_sample_size_soaks_are_inadmissible():
    c = ss.make_contract(kind="stage1", leg="l", account="bybit_1", started="2026-10-01")
    assert ss.contract_problems(c) == []
    assert any("n_needed" in p for p in ss.contract_problems(dict(c, n_needed=10)))
    for k in ss.BANNED_FIELDS:
        assert any(k in p for p in ss.contract_problems(dict(c, **{k: 1})))


def test_committed_contracts_cover_the_current_soak_population():
    import yaml

    acc = yaml.safe_load(open(REPO / "config/accounts.yaml"))["accounts"]
    strat = yaml.safe_load(open(REPO / "config/strategies.yaml"))["strategies"]
    assert guard.tree_findings(acc, strat, ss.load_contracts()) == []


def test_committed_contracts_are_all_mechanical():
    for c in ss.load_contracts():
        assert ss.contract_problems(c) == [], c["id"]
        assert c["n_needed"] <= ss.MAX_N_NEEDED


def test_every_committed_pass_cites_its_trades_and_evidence_record():
    for c in ss.load_contracts():
        d = c.get("disposition") or {}
        if d.get("verdict") == "PASS":
            assert d["trades"] and all((REPO / e).exists() for e in d["evidence"]), c["id"]


def test_guard_self_tests():
    assert guard._self_test() == 0
    assert ss._self_test() == 0


def _graded(**d):
    c = ss.make_contract(kind="stage1", leg="leg", account="bybit_1", started="2026-10-01")
    c["disposition"] = dict({"verdict": "KILLED", "reason": "stage-0 fails", "decided_at": "2026-10-10",
                             "evidence": ["comms/strategy_evidence/leg.json"]}, **d)
    return c


def test_disposition_quiets_a_graded_soak_until_its_review_date(tmp_path):
    c = _graded(verdict="NEEDS_DATA", until="2026-10-24", missing="a Stage-0 window")
    assert ss.contract_problems(c) == []
    p = tmp_path / "SOAKS.json"
    p.write_text(json.dumps({"soaks": [c]}))
    db = _db(tmp_path, "2026-10-24T00:00:00+00:00", [_trade(2), _trade(3)])
    assert ss.soak_states(today=date(2026, 10, 10), db_path=db, contracts_path=p) == []
    assert ss.soak_states(today=date(2026, 10, 25), db_path=db, contracts_path=p)[0]["state"] == "passed"


def test_a_pass_disposition_reads_passed(tmp_path):
    c = _graded(verdict="PASS", trades=[1, 2])
    p = tmp_path / "SOAKS.json"
    p.write_text(json.dumps({"soaks": [c]}))
    rows = ss.soak_states(today=date(2026, 10, 10), db_path=str(tmp_path / "absent.db"), contracts_path=p)
    assert rows[0]["state"] == "passed"


def test_disposition_without_evidence_or_missing_quantity_is_inadmissible():
    assert any("evidence" in m for m in ss.contract_problems(_graded(evidence=[])))
    assert any("NEEDS_DATA" in m for m in ss.contract_problems(_graded(verdict="NEEDS_DATA")))
    assert any("verdict" in m for m in ss.contract_problems(_graded(verdict="MAYBE")))


def test_unreadable_review_date_shows_the_soak_again(tmp_path):
    p = tmp_path / "SOAKS.json"
    p.write_text(json.dumps({"soaks": [_graded(until="soon")]}))
    db = _db(tmp_path, "2026-10-09T00:00:00+00:00", [_trade(2)])
    assert len(ss.soak_states(today=date(2026, 10, 10), db_path=db, contracts_path=p)) == 1
