"""p1_threshold_oof.py reads the threshold on the TRAINING side only (PI-20261119-RIMARY12-0006)."""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "research" / "manifests" / "setup-candidates-metalabel-rostered-paper-v1.yaml"


def test_self_test():
    r = subprocess.run([sys.executable, str(REPO / "scripts/ml/p1_threshold_oof.py"), "--self-test"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr


def _rows(n_train: int, n_eval: int, seed: int = 7) -> list[dict]:
    rnd = random.Random(seed)
    out = []
    for i in range(n_train + n_eval):
        mom = rnd.uniform(-1, 1)
        won = 1 if rnd.random() < 0.5 + 0.3 * mom else 0
        out.append({
            "ts": f"2026-{1 + i // 600:02d}-{1 + (i // 24) % 28:02d}T{i % 24:02d}:00:00+00:00",
            "direction": rnd.choice(["long", "short"]), "symbol": rnd.choice(["BTCUSDT", "ETHUSDT"]),
            "rolling_log_return_vol": rnd.uniform(0.001, 0.02), "log_return": rnd.uniform(-0.01, 0.01),
            "vol_bucket": rnd.choice(["low", "mid", "high"]), "momentum": mom, "hour_of_day": i % 24,
            "dayofweek": (i // 24) % 7, "log_return_lag_1": 0.0, "log_return_lag_2": 0.0,
            "won": won, "r_multiple": (1.2 if won else -1.0),
            # the eval cohort carries an absurd R so any leak into the OOF table is visible
            "event_source": "live_paper" if i >= n_train else "backtest",
        })
    for r in out[n_train:]:
        r["r_multiple"] = 999.0
    return out


def test_end_to_end_on_the_real_manifest_never_reads_eval_rows(tmp_path):
    pytest.importorskip("lightgbm")
    ds = tmp_path / "data.jsonl"
    ds.write_text("".join(json.dumps(r) + "\n" for r in _rows(1200, 200)))
    out = tmp_path / "thr.json"
    r = subprocess.run([sys.executable, str(REPO / "scripts/ml/p1_threshold_oof.py"), "--manifest", str(MANIFEST),
                        "--dataset", str(ds), "--out", str(out)], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr[-2000:]
    rec = json.loads(out.read_text())
    assert rec["read_state"] == "measured" and rec["current_threshold"] == 0.5
    assert rec["dataset_rows"] == 1400 and "1200 rows" in rec["population"] and "200 eval rows are never read" in rec["population"]
    assert sum(f["n_test"] for f in rec["folds"]) == 600, rec["folds"]   # 50% min train, 5 folds over 1,200
    assert all(abs(g["take_all_r"]) < 2 for g in rec["grid"]), "an eval row (R 999) leaked into the OOF table"
    sel = rec["selected"]
    assert sel is None or 0.05 <= sel["take_rate"] <= 0.60
