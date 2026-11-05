"""ML-ENTRY-LIVE-MONITOR: the pre-registered rule, exactly as written; report-only."""
from __future__ import annotations

import importlib.util
import math
import random
from pathlib import Path

import pytest

from src.runtime import ml_entry_live_monitor as M


def _row(i, r, *, acct="bybit_2", reason="tp", cost="broker", strat="ml_entry"):
    # entry 100, stop 98, size 1 -> risk 2 USD; pnl chosen so net R == r with fee 0
    return {"id": i, "account_id": acct, "strategy_name": strat, "exit_reason": reason, "entry_price": 100.0,
            "stop_loss": 98.0, "position_size": 1.0, "pnl": r * 2.0, "fee_taker_usd": 0.0, "fee_maker_usd": 0.0,
            "funding_paid_usd": 0.0, "cost_source": cost}


def _rows(n, mean, sd=0.5, seed=1, **kw):
    rnd = random.Random(seed)
    xs = [rnd.gauss(0, 1) for _ in range(n)]
    m = sum(xs) / n
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return [_row(i, mean + sd * (x - m) / s, **kw) for i, x in enumerate(xs)]


def test_checkpoints_every_50_from_100():
    assert [M.checkpoint_for(n) for n in (0, 99, 100, 149, 150, 199, 200, 251)] == [0, 0, 100, 100, 150, 150, 200, 250]


def test_below_100_is_no_verdict_not_a_pass():
    a = M.assess(_rows(99, -1.0))["bybit_2"]
    assert a["state"] == M.STATE_INSUFFICIENT and a["flags"] == [] and a["n"] == 99


def test_negative_flag_exact_threshold():
    n, sd = 100, 0.5
    se = sd / math.sqrt(n)
    # mean + 2SE just below 0 -> flag; just above -> none
    assert M.flags_for(-2 * se - 1e-6, se) == [M.FLAG_NEGATIVE]
    assert M.flags_for(-2 * se + 1e-6, se) == []
    a = M.assess(_rows(n, -0.2, sd))["bybit_2"]
    assert M.FLAG_NEGATIVE in a["flags"]


def test_below_dev_needs_worse_than_band_minus_2se():
    se = 0.05
    assert M.flags_for(-0.041 - 2 * se - 1e-6, se) == [M.FLAG_NEGATIVE, M.FLAG_BELOW_DEV]
    assert M.flags_for(-0.041 - 2 * se + 1e-6, se) == [M.FLAG_NEGATIVE] if -0.041 - 2 * se + 2 * se < 0 else True
    # a mean at the dev band is NEGATIVE-flaggable only when SE is small; never BELOW_DEV
    assert M.FLAG_BELOW_DEV not in M.flags_for(-0.041, 0.01)
    assert M.flags_for(None, None) == []


def test_positive_book_never_flags():
    a = M.assess(_rows(300, 0.05))["bybit_2"]
    assert a["flags"] == [] and a["state"] == M.STATE_EVALUATED and a["checkpoint"] == 300


def test_operational_closes_are_excluded_and_counted():
    rows = _rows(100, 0.0) + [_row(900 + i, -5.0, reason="operator_flatten_reconciled") for i in range(2)]
    a = M.assess(rows)["bybit_2"]
    assert a["n"] == 100 and a["excluded_operational"] == {"operator_flatten_reconciled": 2} and a["closed_rows"] == 102


def test_other_strategies_and_accounts_do_not_mix():
    rows = _rows(100, 0.1, acct="bybit_2") + _rows(10, -1.0, acct="bybit_2", strat="ml_entry_v2") \
        + _rows(40, -1.0, acct="bybit_portfolio")
    out = M.assess(rows)
    assert out["bybit_2"]["n"] == 100 and out["bybit_portfolio"]["state"] == M.STATE_INSUFFICIENT


def test_uncomputable_and_uncosted_are_counted_not_zeroed():
    bad = _row(1, 0.0)
    bad["stop_loss"] = None
    rows = _rows(100, 0.0, cost=None) + [bad]
    a = M.assess(rows)["bybit_2"]
    assert a["r_uncomputable"] == 1 and a["n"] == 100 and a["uncosted"] == 100


def test_operational_set_equals_attribution_vocabulary():
    p = Path(__file__).resolve().parents[2] / "scripts/research/real_money_close_attribution.py"
    spec = importlib.util.spec_from_file_location("rmca", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert M.OPERATIONAL_EXIT_REASONS == frozenset(mod.NOT_STRATEGY_EXIT)


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "runtime_logs_dir", lambda: tmp_path)
    monkeypatch.setattr("src.runtime.alert_cooldown.state_path", lambda kind, resolver=None: tmp_path / f"{kind}_cd.json", raising=False)
    sent = []
    monkeypatch.setattr(M, "_send_alert", lambda m: sent.append(m))
    return sent


def _entry(sent):
    return [m for m in sent if "freshness" not in m]


def test_tick_pings_once_per_checkpoint_and_is_report_only(sandbox):
    sent = sandbox
    rows = _rows(100, -0.3)
    r1 = M.run_ml_entry_live_monitor(rows=rows, force=True)
    assert "bybit_2" in r1["alerted"] and len(_entry(sent)) == 1 and "REPORT, not a switch" in _entry(sent)[0]
    # same checkpoint again: no second ping
    M.run_ml_entry_live_monitor(rows=rows + _rows(10, -0.3, seed=9), force=True)
    assert len(_entry(sent)) == 1
    # next checkpoint (150): evaluated and pinged again
    M.run_ml_entry_live_monitor(rows=_rows(150, -0.3, seed=3), force=True)
    assert len(_entry(sent)) == 2
    st = M.status()["bybit_2"]
    assert st["evaluated"]["checkpoint"] == 150 and "ENTRY_LIVE_NEGATIVE" in st["evaluated"]["flags"]
    assert "bybit_2 n=150" in M.brief_line(M.status())


def test_below_100_keeps_state_without_verdict(sandbox):
    M.run_ml_entry_live_monitor(rows=_rows(40, -1.0), force=True)
    assert _entry(sandbox) == [] and M.status()["bybit_2"]["evaluated"] is None
    assert "n=40/100 (no verdict yet)" in M.brief_line(M.status())


def test_unreadable_journal_changes_nothing(sandbox, monkeypatch):
    monkeypatch.setattr(M, "_read_rows", lambda p: (_ for _ in ()).throw(RuntimeError("locked")))
    monkeypatch.setattr("src.utils.paths.trade_journal_db_path", lambda: "/nonexistent.db")
    assert M.run_ml_entry_live_monitor(force=True) == {"checked": False, "reason": "read_failed"}
    assert M.status() == {}


def test_served_freshness_measures_the_artifact_field(tmp_path):
    import json
    from datetime import datetime, timezone
    p = tmp_path / "model.json"
    p.write_text(json.dumps({"model_id": "ml-decision-entry-v1", "train_end_exclusive": "2025-09-22 19:00:00+00:00"}))
    f = M.served_model_freshness(datetime(2026, 11, 4, 19, tzinfo=timezone.utc), p)
    assert f["read_state"] == "measured" and f["age_days"] == 408.0 and f["grade"] == "stale"
    p.write_text(json.dumps({"model_id": "x", "train_end_exclusive": "2026-10-25 00:00:00+00:00"}))
    assert M.served_model_freshness(datetime(2026, 11, 4, tzinfo=timezone.utc), p)["grade"] == "fresh"
    assert M.served_model_freshness(artifact_path=tmp_path / "nope.json")["read_state"] == "unreadable"


def test_the_repo_artifact_is_readable_and_stale_flag_pings_once(sandbox):
    sent = sandbox
    M.run_ml_entry_live_monitor(rows=[], force=True)
    M.run_ml_entry_live_monitor(rows=[], force=True)
    assert len([m for m in sent if "freshness" in m]) == 1   # 408-day-old artifact on the real path; once per cooldown
    assert M._load_state()["__model_freshness__"]["read_state"] == "measured"
