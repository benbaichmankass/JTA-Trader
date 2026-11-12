"""CF-GRADES-EQUITY-COMMITTED (2026-11-12): no real-money balance may be serialized into the public repo by the research writers.

Two writers were found committing balances: the counterfactual grader (legs[].equity_pre_usd, and per_account.pct_of_account,
which with pnl_usd back-solves the balance) and alpaca_baseline_affordability (equity_usd, budget_usd = risk_pct x equity, and the
balance inside note/population strings). Each is tested at the writer, with a positive control (the checker fires on a leaking
record) and a negative control (R / P&L / counts are fine), and the committed tip files are scanned too.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

#: key names that carry or derive a balance. ``pct_of_account`` is here because pnl_usd / pct x 100 recovers equity.
BALANCE_KEY = re.compile(r"(?i)(^|_)(equity|balance|buying_?power|net_?liquidation|wallet|pct_of_account|budget_usd)(_|$)|totalequity")
#: not a balance: provenance fields that merely NAME the equity source, and the as-of timestamp
ALLOWED_KEYS = {"equity_as_of", "equity_source", "balance_snapshots"}


def balance_keys(obj, path=""):
    """Every key path in ``obj`` whose name looks like a balance and whose value is not None (a null carries nothing)."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if BALANCE_KEY.search(str(k)) and str(k) not in ALLOWED_KEYS and v is not None:
                out.append(f"{path}/{k}")
            out += balance_keys(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += balance_keys(v, f"{path}[{i}]")
    return out


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# ---- the checker itself: positive and negative controls ----
def test_checker_fires_on_a_leaking_record_and_names_the_path():
    leak = {"legs": [{"account_id": "a", "equity_pre_usd": 123.4}], "arms": [{"per_account": {"a": {"pct_of_account": 1.2}}}],
            "measurement": {"equity_usd": 5.0, "budget_usd": 0.1, "totalEquity": "9"}}
    got = balance_keys(leak)
    assert "/legs[0]/equity_pre_usd" in got and "/arms[0]/per_account/a/pct_of_account" in got
    assert "/measurement/equity_usd" in got and "/measurement/budget_usd" in got and "/measurement/totalEquity" in got


def test_checker_is_quiet_on_r_pnl_counts_nulls_and_provenance():
    ok = {"legs": [{"account_id": "a", "equity_pre_usd": None, "pnl_usd_venue": 3.2, "risk_usd": 1.0}],
          "arms": [{"net_r": 0.4, "per_account": {"a": {"pnl_usd": 0.4, "account_class": "real_money"}}}],
          "measurement": {"equity_as_of": "2026-11-06T01:00:13Z", "equity_source": "route", "n_affordable": 138, "risk_pct": 0.02}}
    assert balance_keys(ok) == []


# ---- the grader writer ----
def test_grade_package_never_serializes_equity_even_when_equity_is_known():
    cg = _load("counterfactual_grader", "scripts/research/counterfactual_grader.py")
    T0 = 1_792_000_000
    bars = [{"time": T0 + 900 * i, "open": 100 - 0.05 * i, "high": 100 - 0.05 * i + 0.1, "low": 100 - 0.05 * i - 0.1,
             "close": 100 - 0.05 * i, "volume": 1.0, "dur": 900} for i in range(60)]
    pkg = {"order_package_id": "pkg-x", "strategy_name": "s", "symbol": "ADAUSDT", "direction": "short", "entry": 100.0, "sl": 100.0,
           "tp": 96.0, "exit_plan": '{"stop": {"price": 101.0}}', "meta": {"atr": 0.5, "trail_mult": 5.0}}
    legs = [{"id": 1, "account_id": "bybit_2", "account_class": "real_money", "status": "closed", "position_size": 10.0,
             "entry_price": 100.0, "exit_price": 99.0, "exit_reason": "sl", "pnl": 9.5, "timestamp": cg.lrc._iso(T0),
             "closed_at": "2026-10-20T01:00:00+00:00", "fee_taker_usd": 0.0, "cost_source": None}]
    rec = cg.grade_package(pkg, legs, bars, [], [], {"bybit_2": 77777.0}, {}, n_random=5)   # 77777.0 is synthetic
    assert rec["status"] == "graded"
    assert balance_keys(rec) == []
    assert "77777" not in json.dumps(rec)
    assert rec["arms"][0]["per_account"]["bybit_2"]["pnl_usd"] == 9.5      # the P&L the arms need is still there


# ---- the RQ-20261106-d5a1-01 writer ----
def test_affordability_record_carries_no_balance(tmp_path, monkeypatch):
    m = _load("alpaca_baseline_affordability", "scripts/research/alpaca_baseline_affordability.py")
    monkeypatch.setattr(m, "_pool", lambda: (["AAA", "BBB"], "0" * 64))
    monkeypatch.setattr(m, "_risk_pct", lambda: 0.02)
    monkeypatch.setattr(m, "_atr_stop_mult", lambda: m.ATR_STOP_MULT)
    monkeypatch.setattr(m, "pass_affordability", lambda syms, eq, rp: {"n_affordable": 1, "n_no_bars": 0, "per_symbol": {}})
    monkeypatch.setattr(m, "pass_pull_load", lambda syms: {"http_calls": 2, "n_symbols": 2, "wall_seconds": 1.0, "n_429": 0,
                                                           "latency_s": {"p95": 0.1}})
    a = types.SimpleNamespace(equity=88888.88, equity_as_of="2026-11-06T01:00:13Z", equity_source="route", unit="U", out=str(tmp_path))
    assert m.run(a) == 0
    for name in ("verdict.json", "measurement.json"):
        text = (tmp_path / name).read_text()
        assert balance_keys(json.loads(text)) == [], name
        assert "88888" not in text and "1777" not in text, name       # neither the balance nor risk_pct x balance


# ---- the committed tip ----
def test_committed_grade_and_rq_files_carry_no_balance():
    bad = []
    for f in sorted((REPO / "comms/research/counterfactual_grades").glob("*.json")):
        bad += [f"{f.name}{k}" for k in balance_keys(json.loads(f.read_text()))]
    for f in sorted((REPO / "comms/research/RQ-20261106-d5a1-01").glob("*/*.json")):
        bad += [f"{f.parent.name}/{f.name}{k}" for k in balance_keys(json.loads(f.read_text()))]
    assert bad == [], bad[:5]
