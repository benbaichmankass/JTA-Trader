"""RESEARCH-TRIAL-LEDGER: scripts/research/trial_ledger.py + the data fingerprint on E5 records.

Every positive check is paired with a PLANTED-BAD input that the same code must refuse, drop or
label -- a counter that also counts the rows it should skip passes every happy-path test.
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts" / "research"))

import research_result as rr  # noqa: E402
import script_run as sr  # noqa: E402
import trial_ledger as tl  # noqa: E402


# ── fixture repo ────────────────────────────────────────────────────────────
def _w(root: Path, rel: str, obj) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, str):
        p.write_text(obj, encoding="utf-8")
    elif isinstance(obj, list):
        p.write_text("".join(json.dumps(r) + "\n" for r in obj), encoding="utf-8")
    else:
        p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _trades(n: int, mean: float, sd: float, seed: int, start_day: int = 1):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        day = start_day + i
        out.append({"net_r": round(rnd.gauss(mean, sd), 4),
                    "exit_time": f"2026-{1 + (day // 28) % 12:02d}-{1 + day % 28:02d} 00:00:00+00:00"})
    return out


def _e5(unit, measurement, *, read_state="measured", store="research/results/", rule="RULE-X"):
    return {"research_unit": unit, "read_state": read_state, "verdict": "pass",
            "decision_rule": {"id": rule, "registered_at": "2026-10-01"},
            "artifact": {"store": store}, "measurement": measurement}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path
    _w(root, "config/accounts.yaml",
       "accounts:\n"
       "  live_a: {account_class: real_money, mode: live, strategies: [aaa_pullback_2h]}\n"
       "  dry_b: {account_class: real_money, mode: dry_run, strategies: [bbb_trend_4h]}\n"
       "  paper_c: {account_class: paper, mode: live, strategies: [bbb_trend_4h]}\n")
    m20 = []
    for cell in ("c1", "c2", "c3"):
        m20.append({"kind": "cell", "leg": "aaa_pullback_2h", "lever": "trail_decay", "cell": cell, "split": "2025-07-01"})
    # PLANTED-BAD: the same cell re-run (same config) and a leg_status row (no config at all)
    m20.append({"kind": "cell", "leg": "aaa_pullback_2h", "lever": "trail_decay", "cell": "c1", "split": "2025-07-01"})
    m20.append({"kind": "leg_status", "leg": "aaa_pullback_2h", "cell": None})
    _w(root, "docs/research/m20-sweep-corpus.jsonl", m20)

    base = _trades(60, 0.2, 1.0, seed=1)
    twin = [dict(r, net_r=r["net_r"] * 1.01) for r in base]          # ~identical series -> one cluster
    other = _trades(60, 0.1, 1.0, seed=99)                            # independent series -> its own
    _w(root, "comms/research/RQ-20261001-001/1/arms/A__trades.jsonl", base)
    _w(root, "comms/research/RQ-20261001-001/1/arms/B__trades.jsonl", twin)
    _w(root, "comms/research/RQ-20261001-001/1/arms/C__trades.jsonl", other)
    arms = {k: {"net_r": 1.0, "argv": ["python3", "scripts/backtest_pullback.py", "--emit-trades",
                                       f"comms/research/RQ-20261001-001/1/arms/{k}__trades.jsonl"]}
            for k in ("A", "B", "C")}
    rows = [
        _e5("RQ-20261001-001", {"leg": "aaa_pullback_2h", "arms": arms}),
        # a weekly re-ask of the SAME arms is the same configs, not three more
        _e5("RQ-20261001-001", {"leg": "aaa_pullback_2h", "arms": arms}),
        # PLANTED-BAD, none may be counted as a config:
        _e5("RQ-20261001-002", {"leg": "aaa_pullback_2h", "verdict": "CONSISTENT"}),            # live-vs-backtest read
        _e5("RQ-20261001-003", {"leg": "aaa_pullback_2h", "net_total_r": 3.0},
            store="docs/research/m20-sweep-corpus.jsonl"),                                        # already in m20
        _e5("RQ-20261001-004", {"leg": "aaa_pullback_2h", "net_total_r": 3.0}, read_state="producer_failed"),
        _e5("RQ-20261001-005", {"leg": "aaa_pullback_2h", "net_total_r": 3.0}, rule=tl.LEDGER_RULE_ID),
        _e5("RQ-20261001-006", {"leg": "aaa_pullback_2h", "arms": {"A": {"1": {"ev": -5}}}}),   # prop-EV sizing arm
    ]
    _w(root, "research/results/RQ-20261001-001/1.jsonl", rows[:2])
    for i, r in enumerate(rows[2:], start=2):
        _w(root, f"research/results/{r['research_unit']}/{i}.jsonl", [r])
    _w(root, "research/queue/RQ-20261001-001.yaml",
       "id: RQ-20261001-001\ntitle: arms sweep\nstatus: done\ngrading: {verdict: pass, graded_at: '2026-10-02'}\n")
    _w(root, "research/queue/RQ-20261001-009.yaml",
       "id: RQ-20261001-009\ntitle: lvb\nstatus: queued\nrun: {command: [python3, scripts/research/x.py, --leg, bbb_trend_4h]}\n")

    ev_trades = _trades(80, 0.25, 1.0, seed=7)
    _w(root, "comms/strategy_evidence/runs/aaa__trades.jsonl", ev_trades)
    mean = sum(r["net_r"] for r in ev_trades) / len(ev_trades)
    _w(root, "comms/strategy_evidence/aaa_pullback_2h.json", {
        "strategy": "aaa_pullback_2h", "harness": "pullback", "coverage_state": "measured",
        "config_fingerprint": "sha256:aaa", "net_r_oos": round(mean * 80, 4), "expectancy_r_oos": round(mean, 4),
        "n_trades_oos": 80, "decision_rule": {"id": "RULE-D1-STAGE0-NET-OF-FULL-COST", "verdict": "pass"},
        "source_run": "comms/strategy_evidence/runs/aaa__trades.jsonl"})
    # PLANTED-BAD: no source_run (harness_failed) and a head-to-head record with no `strategy`
    _w(root, "comms/strategy_evidence/bbb_trend_4h.json", {
        "strategy": "bbb_trend_4h", "harness": "trend", "coverage_state": "harness_failed",
        "decision_rule": {"verdict": None}, "source_run": None})
    _w(root, "comms/strategy_evidence/x_h2h.json", {"id": "H2H-1", "decision_rule": {"verdict": "pass"}})
    return root


# ── counting ────────────────────────────────────────────────────────────────
def test_counts_distinct_configs_and_drops_the_planted_non_trials(repo):
    L = tl.build(repo)
    row = L["legs"]["aaa_pullback_2h::pullback"]
    # 3 m20 cells (duplicate + leg_status dropped) + 3 E5 arms (re-ask deduped; 5 planted rows dropped) + 1 evidence
    assert row["n_configs_by_source"] == {"e5": 3, "evidence": 1, "m20": 3}, row
    assert row["n_configs"] == 7
    assert L["inputs"]["e5"]["config_entries"] == 6     # 3 arms x 2 rows seen, deduped to 3 configs


def test_effective_n_clusters_correlated_series_and_labels_the_upper_bound(repo):
    row = tl.build(repo)["legs"]["aaa_pullback_2h::pullback"]
    # series-bearing: A, B (twin of A), C, evidence -> A+B one cluster; m20 cells have no series
    assert row["n_configs_with_series"] == 4
    assert row["n_clusters"] < row["n_configs_with_series"]
    assert row["effective_n"] == row["n_clusters"] + 3
    assert "upper bound" in row["effective_n_basis"]       # PLANTED-BAD: m20 cells cannot be clustered


def test_cluster_count_pairs():
    a = {f"d{i}": float(i % 3) for i in range(30)}
    assert tl.cluster_count([a, dict(a)]) == 1
    anti = {k: -v for k, v in a.items()}
    assert tl.cluster_count([a, anti]) == 2                # planted-bad: anticorrelated is NOT the same idea


def test_queue_grading_folds_into_the_index_not_into_n(repo):
    L = tl.build(repo)
    q = {u["unit"]: u for u in L["legs"]["aaa_pullback_2h::pullback"]["tried"]["queue_units"]}
    assert q["RQ-20261001-001"]["verdict"] == "pass"
    # a unit that only names --leg is indexed, and adds no config
    b = L["legs"]["bbb_trend_4h::trend"]
    assert [u["unit"] for u in b["tried"]["queue_units"]] == ["RQ-20261001-009"]
    # the queue unit adds no config; bbb's only config is its own evidence record
    assert b["n_configs_by_source"] == {"evidence": 1}


def test_real_money_is_live_real_money_only(repo):
    L = tl.build(repo)
    assert L["summary"]["real_money_legs"] == ["aaa_pullback_2h"]   # planted-bad: dry_run real_money + paper excluded


# ── deflation ───────────────────────────────────────────────────────────────
def test_dsr_at_n1_is_psr_and_falls_with_n():
    r = [x["net_r"] for x in _trades(100, 0.2, 1.0, seed=3)]
    d1, d30 = tl.dsr(r, 1), tl.dsr(r, 30)
    assert d1["dsr"] == d1["psr_n1"] and d1["sr0"] == 0.0
    assert d30["dsr"] < d1["dsr"] and d30["sr0"] > 0
    assert tl.dsr([0.5] * 50, 5)["state"] == "insufficient_series"   # planted-bad: zero variance is no number


def test_haircut_ordering_and_negative_expectancy():
    r = [x["net_r"] for x in _trades(400, 0.15, 1.0, seed=5)]
    exp = sum(r) / len(r)
    h = tl.haircut(r, 10, exp)
    assert h["holm"]["p_adj"] == h["bonferroni"]["p_adj"]
    assert h["bhy"]["p_adj"] >= h["bonferroni"]["p_adj"] >= h["p_single"]
    assert h["bhy"]["haircut_expectancy_r"] <= h["bonferroni"]["haircut_expectancy_r"] <= exp
    neg = [-x for x in r]
    hn = tl.haircut(neg, 10, -exp)                        # planted-bad: a loser is not "haircut" upward
    assert hn["bhy"]["haircut_expectancy_r"] == pytest.approx(-exp, abs=1e-6)


def test_haircut_matches_hand_arithmetic():
    r = [x["net_r"] for x in _trades(200, 0.2, 1.0, seed=11)]
    mu = sum(r) / len(r)
    sd = math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1))
    t = mu / sd * math.sqrt(len(r))
    h = tl.haircut(r, 4, mu)
    p = 2 * (1 - tl._Z.cdf(t))
    assert h["t_stat"] == pytest.approx(t, rel=1e-5)
    assert h["bonferroni"]["p_adj"] == pytest.approx(min(1.0, 4 * p))
    assert h["bhy"]["p_adj"] == pytest.approx(min(1.0, 4 * p * (1 + 1 / 2 + 1 / 3 + 1 / 4)))


def test_every_evidence_record_gets_n_and_a_statistic_or_a_stated_reason(repo):
    L = tl.build(repo)
    ev = L["evidence"]
    a = ev["aaa_pullback_2h"]
    assert a["state"] == "computed" and a["N_used"] >= 1 and "dsr" in a["dsr"]
    assert a["series_cross_check"] == "ok"
    assert set(a["survives"]) == {"dsr_gt_0_95", "haircut_bhy_gt_0", "haircut_bonferroni_gt_0", "both"}
    assert ev["bbb_trend_4h"]["state"] == "no_series" and "NOT a fail" in ev["bbb_trend_4h"]["why"]
    assert ev["x_h2h"]["state"] == "not_a_leg_record"
    assert tl.verdict_for(L)["verdict"] == "pass"


def test_series_mismatch_is_flagged(repo):
    p = repo / "comms/strategy_evidence/aaa_pullback_2h.json"
    d = json.loads(p.read_text())
    d["expectancy_r_oos"] = 9.0                            # planted-bad: record disagrees with its own trades
    p.write_text(json.dumps(d))
    assert tl.build(repo)["evidence"]["aaa_pullback_2h"]["series_cross_check"].startswith("MISMATCH")


def test_unreadable_record_makes_the_weekly_verdict_indeterminate(repo):
    (repo / "comms/strategy_evidence/zzz.json").write_text("{not json")
    L = tl.build(repo)
    assert L["evidence"]["zzz"]["state"] == "unreadable"
    v = tl.verdict_for(L)
    assert v["verdict"] == "indeterminate" and "zzz" in v["measurement"]["records_without_state"]


def test_out_dir_form_writes_ledger_and_verdict(repo, tmp_path):
    out = tmp_path / "out"
    assert tl.main(["--root", str(repo), "--out", str(out)]) == 0
    assert json.loads((out / "trial_ledger.json").read_text())["report_only"] is True
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "measured" and v["verdict"] in sr.VERDICTS


def test_committed_ledger_covers_every_evidence_record():
    """The snapshot on the branch must cover the evidence dir as it stands (53 on 2026-10-16)."""
    ledger = json.loads((_REPO / "comms/research/trial_ledger.json").read_text())
    on_disk = {p.stem for p in (_REPO / "comms/strategy_evidence").glob("*.json")}
    assert set(ledger["evidence"]) == on_disk
    assert ledger["report_only"] is True


# ── data fingerprint (script_run.derive_record -> produced_by.data_fingerprint) ──
def _plan(root: Path, argv):
    return sr.Plan(unit="RQ-20300101-001", path=root / "q.yaml", commands=[argv], timeout_minutes=10,
                   out_dir=Path("comms/research/RQ-20300101-001/r1"), rule_id="RULE-X", rule_registered_at="2030-01-01")


def test_fingerprint_hashes_named_inputs_and_moves_when_data_moves(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/c.csv").write_text("1,2\n")
    p = _plan(tmp_path, ["python3", "scripts/research/x.py", "--data", "data", "--out", str(Path("comms/research/RQ-20300101-001/r1"))])
    fp1 = sr.data_fingerprint(p, {"data_window": {"start": "2025-01-01"}}, repo=tmp_path)
    assert fp1["state"] == "fingerprinted" and fp1["n_files"] == 1 and fp1["window"] == {"start": "2025-01-01"}
    (tmp_path / "data/c.csv").write_text("1,3\n")
    assert sr.data_fingerprint(p, None, repo=tmp_path)["sha256"] != fp1["sha256"]


def test_fingerprint_refuses_outputs_traversal_and_absolute_paths(tmp_path):
    out = tmp_path / "comms/research/RQ-20300101-001/r1"
    out.mkdir(parents=True)
    (out / "verdict.json").write_text("{}")
    (tmp_path / "outside.txt").write_text("x")
    p = _plan(tmp_path, ["python3", "scripts/research/x.py", "--out", "comms/research/RQ-20300101-001/r1",
                         "--a", "../outside.txt", "--b", "/etc/hostname"])
    fp = sr.data_fingerprint(p, {"data_inputs": ["comms/research/RQ-20300101-001/r1/verdict.json"]}, repo=tmp_path)
    assert fp["state"] == "not_established" and fp["why"]


def test_derive_record_carries_the_fingerprint(tmp_path):
    p = _plan(tmp_path, ["python3", "scripts/research/x.py"])
    rec = sr.derive_record(p, repo=tmp_path)              # no manifest -> producer_failed, still fingerprinted
    assert rec["read_state"] == "producer_failed"
    assert json.loads(rec["data_fingerprint"])["state"] == "not_established"


def _record(**fp):
    rec = rr.build(research_unit="RQ-20300101-001", decision_rule_id="R", decision_rule_registered_at="2030-01-01",
                   verdict="pass", read_state="measured", population_description="p", n=1, workflow="w.yml",
                   run_id="1", commit_sha="abc", tool="t", artifact_store="research/results/", **fp)
    return rec


def test_validator_accepts_good_fingerprints_and_refuses_planted_bad_ones():
    assert not rr.validate(_record())                     # absent: legal (pre-2026-10-16 records)
    assert not rr.validate(_record(data_fingerprint={"state": "fingerprinted", "sha256": "a" * 64}))
    assert not rr.validate(_record(data_fingerprint={"state": "not_established", "why": "named no input"}))
    for bad in ({}, {"state": "fingerprinted", "sha256": "nothex"}, {"state": "not_established"}, {"state": "ok"}):
        assert rr.validate(_record(data_fingerprint=bad)), bad


def test_emit_cli_lands_the_fingerprint_and_refuses_junk(tmp_path):
    common = ["--emit", "--root", str(tmp_path), "--research-unit", "RQ-20300101-001", "--decision-rule-id", "R",
              "--decision-rule-registered-at", "2030-01-01", "--verdict", "pass", "--read-state", "measured",
              "--population", "p", "--n", "1", "--workflow", "w.yml", "--run-id", "7", "--commit-sha", "abc",
              "--tool", "t", "--artifact-store", "research/results/"]
    fp = {"state": "fingerprinted", "sha256": "b" * 64, "n_files": 1}
    assert rr.main(common + ["--data-fingerprint", json.dumps(fp)]) == 0
    rows = [json.loads(x) for p in tmp_path.rglob("7.jsonl") for x in p.read_text().splitlines()]
    assert rows and rows[0]["produced_by"]["data_fingerprint"] == fp
    junk = [("8" if tok == "7" else tok) for tok in common]
    assert rr.main(junk + ["--data-fingerprint", "[1, 2]"]) == 1                   # planted-bad: not an object
    assert not list(tmp_path.rglob("8.jsonl"))


def test_derive_record_accepts_a_duck_typed_plan_without_commands(tmp_path):
    """Contract tests elsewhere pass a SimpleNamespace(unit, out_dir, rule_id, rule_registered_at);
    the fingerprint must read that as 'named no input', never AttributeError (CI on #18594)."""
    from types import SimpleNamespace
    plan = SimpleNamespace(unit="RQ-20300101-001", out_dir=Path("comms/research/RQ-20300101-001/r1"),
                           rule_id="RULE-X", rule_registered_at="2030-01-01")
    rec = sr.derive_record(plan, repo=tmp_path)
    assert json.loads(rec["data_fingerprint"])["state"] == "not_established"
