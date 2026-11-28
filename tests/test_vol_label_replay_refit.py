"""ml_vol_label_replay `replay-refit` (RESEARCH-NO-WAIT-FOR-DATA, 2026-11-28; units RQ-20261128-f1a5-05 / -rc4e-01).

A regime head's recipe refit on one span labels a DISJOINT span; the fidelity read compares refit vs live labels and a
thin or low-agreement overlap reads label_not_live_faithful, never a pass; overlapping spans are refused."""
import json
import math
import random
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))
import ml_vol_label_replay as V  # noqa: E402


def test_label_agreement_and_verdict():
    a = {f"t{i}": {"vol_regime": "calm" if i % 4 else "volatile"} for i in range(2000)}
    b = dict(a)
    b.update({f"t{i}": {"vol_regime": "unknown"} for i in range(10)})          # unknown bars are not compared
    agr = V.label_agreement(a, b)
    assert agr == {"bars_compared": 1990, "agree_pct": 100.0}
    assert V.refit_verdict(agr, 85.0)["state"] == "label_faithful"
    assert V.refit_verdict({"bars_compared": 500, "agree_pct": 99.0}, 85.0)["state"] == "label_not_live_faithful"
    assert V.refit_verdict({"bars_compared": 5000, "agree_pct": 80.0}, 85.0)["state"] == "label_not_live_faithful"
    assert V.refit_verdict({"bars_compared": 0, "agree_pct": None}, 85.0)["state"] == "label_not_live_faithful"


def _synthetic(tmp: Path) -> tuple[Path, Path]:
    rng = random.Random(7)
    rows = []
    for i in range(3000):
        day = 1 + i // 96
        ts = f"2020-{1 + (day - 1) // 28:02d}-{1 + (day - 1) % 28:02d}T{(i % 96) // 4:02d}:{15 * (i % 4):02d}:00+00:00"
        vol = abs(rng.gauss(0.01, 0.006))
        rows.append({"ts": ts, "rolling_log_return_vol": vol, "log_return": rng.gauss(0, vol),
                     "regime_label": "volatile" if vol > 0.016 else "range"})
    ds = tmp / "data.jsonl"
    ds.write_text("".join(json.dumps(r) + "\n" for r in rows))
    man = tmp / "m.yaml"
    man.write_text(yaml.safe_dump({"model_id": "toy-regime", "trainer_config": {
        "target_column": "regime_label", "feature_columns": ["rolling_log_return_vol", "log_return", "fc_ret_med"],
        "categorical_columns": [], "n_iter": 20, "seed": 1,
        "lgbm_params": {"num_leaves": 7, "min_data_in_leaf": 20, "learning_rate": 0.1}}}))
    return ds, man


def test_refit_head_drops_absent_features_and_scores(tmp_path):
    ds, man = _synthetic(tmp_path)
    head = V.refit_head(manifest=man, dataset=ds, symbol="toy", train_start="2020-01-01", train_end="2020-01-20",
                        drop_features=["fc_ret_med"])
    assert head["resolution"]["dropped_features"] == ["fc_ret_med"] and head["resolution"]["n_train"] > 1000
    assert head["model_id"] == "toy-regime+refit[2020-01-01..2020-01-20]"
    p = head["predictor"].predict_proba({"rolling_log_return_vol": 0.05, "log_return": 0.0})
    q = head["predictor"].predict_proba({"rolling_log_return_vol": 0.002, "log_return": 0.0})
    assert p["volatile"] > q["volatile"] and math.isfinite(p["volatile"])


def test_overlapping_spans_are_refused(tmp_path):
    ds, man = _synthetic(tmp_path)
    rc = V.main(["replay-refit", "--symbol", "toy", "--manifest", str(man), "--dataset", str(ds),
                 "--train-start", "2020-01-10", "--train-end", "2020-01-20", "--score-start", "2020-01-15",
                 "--score-end", "2020-01-25", "--out", str(tmp_path / "o.jsonl")])
    assert rc == 2
