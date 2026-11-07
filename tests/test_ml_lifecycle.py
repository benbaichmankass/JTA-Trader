import json
from datetime import datetime, timedelta, timezone

from ml.lifecycle import plan as P
from ml.lifecycle import scheduler as S

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


_ALL = P.load_all()


def _plans():
    return {k: v for k, v in _ALL.items() if k == "btc-regime-15m-lgbm-v2"}


def test_all_plans_valid_and_cover_population():
    assert {p.stem for p in P.population()} == set(P.load_all())
    for k, v in P.load_all().items():
        assert P.validate(k, v) == [], k


def test_fresh_state_everything_due_and_cycle_row_defers_retrain():
    plans = _plans()
    keys = {d["key"] for d in S.due_jobs(plans, {}, {}, NOW)}
    assert "btc-regime-15m-lgbm-v2/retrain" in keys
    cyc = {plans["btc-regime-15m-lgbm-v2"]["manifest"]: NOW - timedelta(hours=3)}
    keys = {d["key"] for d in S.due_jobs(plans, {}, cyc, NOW)}
    assert "btc-regime-15m-lgbm-v2/retrain" not in keys


def test_backoff_and_drift_trigger():
    st = {"btc-regime-15m-lgbm-v2/retrain": {"last_ok_ts": (NOW - timedelta(days=5)).isoformat(),
                                             "consecutive_failures": 1,
                                             "last_attempt_ts": (NOW - timedelta(hours=1)).isoformat()}}
    assert "btc-regime-15m-lgbm-v2/retrain" not in {d["key"] for d in S.due_jobs(_plans(), st, {}, NOW)}
    d = S.due_jobs(_plans(), {"btc-regime-15m-lgbm-v2/retrain": {"last_ok_ts": NOW.isoformat()}}, {}, NOW,
                   drift_hot={"btc-regime-15m-lgbm-v2"})
    assert any(x["trigger"] == "drift" for x in d)


def test_failure_contained_and_red_flag_once(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(S.P, "load_all", lambda: _plans())
    monkeypatch.setattr(S.P, "fill", lambda c, p, x: ["false"])
    monkeypatch.setattr(S, "BACKOFF_H", 0)
    monkeypatch.setattr(S, "RED_FLAG_AFTER", 2)
    for _ in range(4):
        assert S.main(["--max-jobs", "1"]) == 0  # never non-zero: no halting
    cyc = (tmp_path / "runtime_logs/training_cycle.jsonl").read_text().splitlines()
    assert sum('"lifecycle_red_flag"' in line for line in cyc) == 1
    res = [json.loads(x) for x in (tmp_path / "runtime_logs/trainer/lifecycle_results.jsonl").read_text().splitlines()]
    assert all(r["provenance"] == "MEASURED" for r in res)
