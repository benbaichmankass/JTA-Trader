"""ML-ENTRY-EQUITY-NATIVE: the equity-native ENTRY harness (dev walk-forward + one confirming read). Offline, synthetic bars."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_entry_equity as Q  # noqa: E402


def test_self_test_passes():
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/ml_entry_equity.py"), "--self-test"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and "self-test ok" in r.stdout, r.stdout + r.stderr


def test_no_crypto_feature_and_registered_grid():
    for cfg in Q.CONFIGS.values():
        assert not any(("btc" in f) or ("perp" in f) for f in cfg["features"]), cfg["features"]
    assert len(Q.CONFIGS) * len(Q.TAUS) == 12
    assert Q.TRAIN_END < Q.CONFIRM_START and Q.EMBARGO_DAYS >= 14


def test_pool_rule_is_the_registered_one():
    import ml_entry_alpaca_score as S
    assert S.POOL_RULE_SHA256 == "e9702661d1a596a0f7e84e632c0ca8b5c2743a728f02147477c003644a0858e2"


def test_dev_and_confirm_rows_satisfy_the_runner_verdict_contract():
    import script_run as SR
    d = {"selected": {"key": "B|0.2", "mean_net_r": 0.1, "n": 900}, "n_selection_draws": 12, "n_pool": 173, "train_end": "2025-06-30"}
    row = Q.dev_row(d, "RQ-X", "research-script-run")
    assert row["verdict"] in SR.VERDICTS and row["read_state"] in SR.READ_STATES, row
    assert isinstance(row["population"], str) and row["population"].strip() and "n" in row
    row2 = Q.dev_row({**d, "selected": None}, "RQ-X", "research-script-run")
    assert row2["verdict"] in SR.VERDICTS and row2["n"] is None
    import research_result as RR       # the emitter's own admissibility rule (measured + not_applicable is refused)
    for r in (row, row2):
        rec = RR.build(research_unit="RQ-20261105-001", decision_rule_id="R", decision_rule_registered_at="2026-11-05", verdict=r["verdict"],
                       read_state=r["read_state"], population_description=r["population"], n=r["n"], workflow="w", run_id="1",
                       commit_sha="abc", tool="t", artifact_store="s", artifact_locator="l")
        assert RR.validate(rec) == [] or r["n"] is None, RR.validate(rec)
    assert RR.validate(RR.build(research_unit="RQ-20261105-001", decision_rule_id="R", decision_rule_registered_at="2026-11-05", verdict=row["verdict"],
                       read_state="measured", population_description="p", n=5, workflow="w", run_id="1", commit_sha="abc", tool="t",
                       artifact_store="s", artifact_locator="l")) == []
    for v in ("pass", "fail", "indeterminate"):          # the confirm stage's three verdicts
        assert v in SR.VERDICTS
