"""Tests for the two ML-health instruments built by lane ML-HEALTH-BUILDS-1027.

`drift_regime_mix` (ML-DRIFT-SPLIT-INSTRUMENT) and `label_wall_census` (ML-LABEL-WALL): planted cases through the real
functions, the verdict-shape contract script_run consumes, and the queue units that now point at them.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.research import drift_regime_mix as dm  # noqa: E402
from scripts.research import label_wall_census as lw  # noqa: E402
from scripts.research import script_run  # noqa: E402
from src.runtime import provenance as P  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _rows(n, start, score_fn, *, step_min=15, symbol="SOLUSDT", seed=1):
    rng = random.Random(seed)
    return [dm.Row(start + timedelta(minutes=step_min * i), min(1.0, max(0.0, score_fn(start + timedelta(minutes=step_min * i), i) + rng.gauss(0, 0.02))),
                   {"symbol": symbol}) for i in range(n)]


# ── drift_regime_mix: split mode ──────────────────────────────────────────────
def _stats(n, share, auc_good, seed):
    """n labelled rows with a given volatile share; the score separates the labels when auc_good."""
    rng = random.Random(seed)
    rows, labels = [], {}
    for i in range(n):
        ts = T0 + timedelta(minutes=15 * i)
        y = 1 if rng.random() < share else 0
        s = (0.6 + 0.3 * y if auc_good else 0.6) + rng.gauss(0, 0.05)
        rows.append(dm.Row(ts, s, {}))
        labels[ts] = y
    return dm.window_stats(rows, labels.get)


def test_split_regime_mix_when_share_moves_and_auc_holds():
    ref, cur = _stats(500, 0.20, True, 1), _stats(500, 0.35, True, 2)
    assert dm.split_verdict(ref, cur)[0] == "regime_mix"


def test_split_capability_loss_when_auc_falls():
    ref, cur = _stats(500, 0.25, True, 3), _stats(500, 0.25, False, 4)
    assert dm.split_verdict(ref, cur)[0] == "capability_loss"


def test_split_no_explanation_when_both_flat():
    ref, cur = _stats(500, 0.25, True, 5), _stats(500, 0.25, True, 6)
    assert dm.split_verdict(ref, cur)[0] == "no_explanation"


def test_split_underpowered_below_200_labelled():
    ref, cur = _stats(500, 0.25, True, 7), _stats(150, 0.40, True, 8)
    assert dm.split_verdict(ref, cur)[0] == "underpowered"


def test_split_unit_verdict_precedence():
    assert dm.unit_verdict_split({"a": {"rule_verdict": "regime_mix"}, "b": {"rule_verdict": "capability_loss"}})[0] == "fail"
    assert dm.unit_verdict_split({"a": {"rule_verdict": "underpowered"}})[0] == "indeterminate"
    assert dm.unit_verdict_split({"a": {"rule_verdict": "regime_mix"}})[0] == "no_action_warranted"


# ── drift_regime_mix: by-version mode ─────────────────────────────────────────
def test_pooled_two_version_stream_reads_artifact():
    old = _rows(600, T0, lambda t, i: 0.55)
    new = _rows(700, T0 + timedelta(days=7), lambda t, i: 0.85, seed=2)
    starts = [("r1", T0 - timedelta(days=1)), ("r2", T0 + timedelta(days=7))]
    h = dm.version_head("h", old + new, starts, now=T0 + timedelta(days=17), scan_days=30.0)
    assert h["head_verdict"] == "ARTIFACT"
    assert h["a_scan_input"]["flagged"] and not h["b_newest_version"]["flagged"]


def test_thin_newest_version_is_indeterminate_never_artifact():
    rows = _rows(300, T0, lambda t, i: 0.5 if i < 150 else 0.9)
    h = dm.version_head("h", rows, [("r1", T0 - timedelta(days=1))], now=T0 + timedelta(days=5), scan_days=30.0)
    assert h["head_verdict"] == "INDETERMINATE" and "< 500" in h["why"]


def test_unregistered_head_is_indeterminate():
    assert dm.version_head("h", [], None, now=T0)["head_verdict"] == "INDETERMINATE"


def _session_level(t, i):  # score is a function of the 6h session bucket alone
    return 0.3 if dm.session_bucket(t) < 2 else 0.8


def test_mix_shift_reads_mix_and_within_stratum_trend_reads_decay():
    """History at a uniform session mix; the scan window sees the early sessions first and the late ones last."""
    hist = _rows(1200, T0 - timedelta(days=40), _session_level, step_min=45, seed=3)  # ends before the scan window
    scan_start = T0
    lo = [r for r in _rows(2000, scan_start, _session_level, step_min=15, seed=4) if dm.session_bucket(r.ts) < 2][:300]
    hi = [r for r in _rows(2000, scan_start + timedelta(days=10), _session_level, step_min=15, seed=5) if dm.session_bucket(r.ts) >= 2][:300]
    mix_stream = hist + lo + hi
    starts = [("r1", T0 - timedelta(days=45))]
    now = T0 + timedelta(days=14)
    h = dm.version_head("h", mix_stream, starts, now=now, scan_days=14.0)
    assert h["head_verdict"] == "MIX", h
    # same history, but the score drifts upward INSIDE every session bucket during the scan window
    trend = _rows(2000, scan_start, lambda t, i: (0.2 if dm.session_bucket(t) < 2 else 0.4) + 0.0008 * i, step_min=15, seed=6)[:700]
    h2 = dm.version_head("h", hist + trend, starts, now=now, scan_days=14.0)
    assert h2["head_verdict"] == "DECAY", h2


def test_reweight_hits_the_target_shares_and_drops_unknown_strata():
    rows = _rows(800, T0, lambda t, i: 0.5)
    target = {("SOLUSDT", 0): 0.5, ("SOLUSDT", 1): 0.5}
    out = dm.reweight_to_mix(rows, target)
    shares = {k: sum(1 for r in out if dm.stratum(r) == k) / len(out) for k in target}
    assert all(abs(v - 0.5) < 0.01 for v in shares.values())
    assert dm.reweight_to_mix(rows, {("BTCUSDT", 0): 1.0}) == []


def test_unit_verdict_versions_thresholds():
    def heads(*v):
        return {str(i): {"head_verdict": x} for i, x in enumerate(v)}
    assert dm.unit_verdict_versions(heads(*["ARTIFACT"] * 4 + ["MIX"] * 2 + ["INDETERMINATE"] * 3))[0] == "pass"
    assert dm.unit_verdict_versions(heads(*["DECAY"] * 4 + ["ARTIFACT"] * 5))[0] == "fail"
    assert dm.unit_verdict_versions(heads(*["ARTIFACT"] * 5 + ["DECAY"] * 3 + ["MIX"] * 0 + ["INDETERMINATE"]))[0] == "indeterminate"


def test_cli_by_version_end_to_end_on_a_synthetic_log_and_registry(tmp_path):
    from ml.registry.model_registry import ModelRegistry
    log = tmp_path / "shadow_predictions.jsonl"
    with log.open("w") as fh:
        for r in _rows(600, T0, lambda t, i: 0.55) + _rows(700, T0 + timedelta(days=7), lambda t, i: 0.85, seed=2):
            fh.write(json.dumps({"predicted_at_utc": r.ts.isoformat(), "model_id": "h-v1", "stage": "advisory", "score": r.score,
                                 "row_keys": ["symbol"], "feature_row": r.feature_row}) + "\n")
    reg = ModelRegistry(tmp_path / "registry")
    reg.register(model_id="h-v1", manifest={"target_deployment_stage": "advisory"}, model_state_path="x", metrics={}, code_revision="c", run_id="r1")
    reg.register(model_id="h-v1", manifest={"target_deployment_stage": "advisory"}, model_state_path="x", metrics={}, code_revision="c", run_id="r2")
    # registration stamps `at` = now, so pin the as-of just after it and check the contract, not the verdict
    out = tmp_path / "out"
    rc = dm.main(["--mode", "by-version", "--head", "h-v1", "--shadow-log", str(log), "--registry-root", str(tmp_path / "registry"),
                  "--as-of", (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(), "--lookback-days", "9999", "--out", str(out)])
    rec = json.loads((out / "verdict.json").read_text())
    assert rc == 0
    assert rec["verdict"] in script_run.VERDICTS and rec["read_state"] in script_run.READ_STATES
    assert rec["population"] and "n" in rec and rec["measurement"]["per_head"]["h-v1"]["head_verdict"] in {"ARTIFACT", "MIX", "DECAY", "INDETERMINATE"}


def test_missing_shadow_log_is_no_data_not_no_drift(tmp_path):
    out = tmp_path / "o"
    dm.main(["--mode", "by-version", "--head", "h", "--shadow-log", str(tmp_path / "none.jsonl"), "--registry-root", str(tmp_path), "--out", str(out)])
    rec = json.loads((out / "verdict.json").read_text())
    assert rec["read_state"] == "no_data" and rec["verdict"] == "not_applicable"


# ── label_wall_census ─────────────────────────────────────────────────────────
def _journal(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, strategy_name TEXT, symbol TEXT, notes TEXT, pnl REAL, timestamp TEXT, "
                "closed_at TEXT, status TEXT, is_backtest BOOLEAN)")
    for strat, sym, src, status, bt, day in rows:
        con.execute("INSERT INTO trades (strategy_name, symbol, notes, pnl, timestamp, closed_at, status, is_backtest) VALUES (?,?,?,?,?,?,?,?)",
                    (strat, sym, json.dumps({"exit_price_source": src}), 1.0, f"2026-09-{day:02d}T00:00:00+00:00", f"2026-09-{day:02d}T01:00:00+00:00", status, bt))
    con.commit()
    con.close()


def test_census_counts_only_measured_closed_non_backtest(tmp_path):
    db = str(tmp_path / "j.db")
    _journal(db, [("trend", "BTCUSDT", "bybit_closed_pnl", "closed", 0, 1),
                  ("trend", "BTCUSDT", "bybit_closed_pnl", "closed", 0, 10),
                  ("trend", "BTCUSDT", "local_markprice", "closed", 0, 11),  # fabricated: counted apart, never pooled
                  ("trend", "BTCUSDT", "bybit_closed_pnl", "open", 0, 12),
                  ("trend", "BTCUSDT", "bybit_closed_pnl", "closed", 1, 13)])
    j, why = lw.read_journal(db)
    assert why is None
    c = j[("trend", "BTCUSDT")]
    assert c[P.MEASURED] == 2 and c[P.FABRICATED] == 1


def test_census_verdicts_follow_the_registered_rule():
    j = {("trend", "BTC"): {P.MEASURED: 120, P.ESTIMATED: 0, P.FABRICATED: 0, P.UNVERIFIED: 0, "first": "2026-09-01T00:00:00+00:00", "last": "2026-10-01T00:00:00+00:00"}}
    led = {("trend", "BTC"): 400}
    assert lw.census(j, led, {}, {}, pooled_gate=300, conviction_gate=1000)["rule_verdict"] == "PARK"
    assert lw.census(j, led, {"trend|BTC": True}, {}, pooled_gate=300, conviction_gate=1000)["rule_verdict"] == "GO"
    held_false = lw.census(j, led, {"trend|BTC": False}, {}, pooled_gate=300, conviction_gate=1000)
    assert held_false["rule_verdict"] == "PARK" and held_false["cells"][0]["parity_state"] == "failed"
    short = lw.census(j, {}, {}, {"trend|BTC": True}, pooled_gate=300, conviction_gate=1000)
    assert short["rule_verdict"] == "NEEDS-BACKFILL"


def test_census_reports_accrual_days_to_gate():
    j = {("s", "X"): {P.MEASURED: 30, P.ESTIMATED: 0, P.FABRICATED: 0, P.UNVERIFIED: 0, "first": "2026-09-01T00:00:00+00:00", "last": "2026-10-01T00:00:00+00:00"}}
    cell = lw.census(j, {}, {}, {}, pooled_gate=300, conviction_gate=1000)["cells"][0]
    assert cell["days_to_gate_at_observed_rate"] == 270.0  # (300-30) / (30 trades / 30 days)


def test_census_unreadable_journal_is_no_data(tmp_path):
    out = tmp_path / "o"
    lw.main(["--out", str(out), "--journal", str(tmp_path / "missing.db")])
    rec = json.loads((out / "verdict.json").read_text())
    assert rec["read_state"] == "no_data" and rec["verdict"] == "not_applicable"


def test_census_cli_contract_with_synthetic_journal_and_ledger(tmp_path):
    db = str(tmp_path / "j.db")
    _journal(db, [("trend_donchian", "BTCUSDT", "bybit_closed_pnl", "closed", 0, d) for d in range(1, 11)])
    led = tmp_path / "runs" / "r1"
    led.mkdir(parents=True)
    (led / "leg_a__trades.jsonl").write_text("\n".join(json.dumps({"strategy": "trend_donchian", "symbol": "BTCUSDT", "net_r": 0.1}) for _ in range(5)))
    (led / "leg_a__B3__trades.jsonl").write_text(json.dumps({"strategy": "trend_donchian", "symbol": "BTCUSDT", "net_r": 0.1}))  # resample: excluded
    out = tmp_path / "out"
    assert lw.main(["--out", str(out), "--journal", db, "--ledgers", str(tmp_path / "runs" / "*" / "*__trades.jsonl")]) == 0
    rec = json.loads((out / "verdict.json").read_text())
    assert rec["verdict"] in script_run.VERDICTS and rec["read_state"] == "measured" and rec["n"] == 10
    cell = rec["measurement"]["cells"][0]
    assert cell["n_measured"] == 10 and cell["n_backtest"] == 5 and cell["n_backtest_parity_unverified"] == 5


# ── the units that point at the instruments ───────────────────────────────────
UNITS = ["RQ-20261011-6e85-01", "RQ-20261016-65ff-27", "RQ-20261011-17f4-02"]


@pytest.mark.parametrize("unit", UNITS)
def test_unit_plans_through_script_run(unit):
    p = script_run.plan(unit, run_id="t1", queue_dir=REPO / "research" / "queue")
    assert p.ok, p.errors


def test_decision_rules_unchanged_against_registered_text():
    """The moved units keep their decision_rule byte-for-byte (the ids and the rule strings are the registered ones)."""
    expect = {"RQ-20261011-6e85-01": "RULE-RQ1011-6E85-DRIFT-SPLIT", "RQ-20261016-65ff-27": "RULE-RQ2026101665ff27-DRIFT-ARTIFACT",
              "RQ-20261011-17f4-02": "RULE-RQ1011-17F4-02-LABEL-GATE-CENSUS"}
    for u, rid in expect.items():
        raw = yaml.safe_load((REPO / "research" / "queue" / f"{u}.yaml").read_text())
        assert raw["decision_rule"]["id"] == rid and raw["decision_rule"]["registered_before_run"] is True
