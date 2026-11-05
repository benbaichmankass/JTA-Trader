"""The timeframe harness reproduces ml_decision_entry at 1h and scales windows as registered (row ML-TIMEFRAME)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import ml_entry_timeframe as T  # noqa: E402


def test_self_test_runs_clean():
    T._self_test()


def test_every_registered_unit_has_a_known_arm():
    for unit, (tf, sc) in T.UNITS.items():
        assert tf in T.TF_MIN and sc in ("bar", "clock"), unit
        assert (Path(__file__).resolve().parents[1] / "research" / "queue" / f"{unit}.yaml").exists(), unit


def test_count_model_matches_the_registered_ratios():
    c = T.count()
    base = c["1h/bar"]["decision_rows_est"]
    assert c["5m/bar"]["decision_rows_est"] == 12 * base and c["15m/bar"]["decision_rows_est"] == 4 * base
    assert c["5m/clock"]["decision_rows_est"] == base and c["4h/bar"]["decision_rows_est"] * 4 == base


# ---- b620-01 repair (2026-11-05): frozen-bar mask + float64 reproduce round 1 EXACTLY; the rule is untouched; the K-seed unit is parked ----
import json

_DIAG = Path(__file__).resolve().parents[1] / "comms" / "research" / "RQ-20261101-b620-01" / "diagnosis-20261105"


def test_round1_reproduces_exactly_on_the_masked_table():
    """The committed measurements, not a re-run: the harness pipeline AND round 1's own code on the masked table give round 1 to the last digit."""
    for name, key_n, key_mean in (("harness_masked_float64.json", "per_seed_n", "mean"), ("round1_code_on_masked_table.json", None, "mean")):
        rec = json.loads((_DIAG / name).read_text())
        assert abs(rec[key_mean] - T.REF_ROUND1["mean"]) < 1e-12, name
        ns = rec[key_n] if key_n else [v[0] for v in rec["per_seed"].values()]
        assert ns == T.REF_ROUND1["n"], name


def test_float32_without_exactness_is_recorded_as_the_contrast():
    rec = json.loads((_DIAG / "harness_masked_float64.json").read_text())["float32_masked_for_contrast"]
    assert abs(rec["mean"] - T.REF_ROUND1["mean"]) > 1e-4          # float32 alone does not reproduce round 1 digit for digit
    assert rec["n"] != T.REF_ROUND1["n"]


def test_b620_rule_is_unchanged_and_rearmed_not_rewritten():
    import yaml
    root = Path(__file__).resolve().parents[1]
    u = yaml.safe_load((root / "research/queue/RQ-20261101-b620-01.yaml").read_text())
    r = u["decision_rule"]
    assert r["registered_at"] == "2026-11-01" and "within 0.0005" in r["rule"] and "within 1%" in r["rule"] and "+0.0089486" in r["rule"]
    assert u["status"] == "queued" and not u.get("last_dispatched_at") and u["rearmed_at"] > "2026-11-03T02"
    assert "grading" not in u and "grading_before_rearm" in u


def test_the_dropped_kseed_unit_is_parked_not_dispatchable():
    import yaml
    root = Path(__file__).resolve().parents[1]
    assert not (root / "research/queue/RQ-20261105-15c9-01.yaml").exists()
    u = yaml.safe_load((root / "research/queue/blocked/RQ-20261105-15c9-01.yaml").read_text())
    assert u["status"] == "blocked" and u["blocked_on"] and "DROPPED" in u["blocked_on"][0]["what"]
