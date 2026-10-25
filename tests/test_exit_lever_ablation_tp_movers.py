"""exit_lever_ablation.py: a GEOM-B1 TP arm on a leg that declares tp_revision (PI-20261021-6SBYWRKB-0001).

RQ-20261018-012 / -014 died exit 1 after arm A on trend_donchian_eth_4h: the argv builder forwards the
leg's `tp_revision` as `--tp-revision`, the arm adds `--tp-target-r` / `--tp-retarget-mode`, and
backtest_trend.run_backtest raises ValueError on two TP movers. The run landed with no readable cause
because `*.log` is gitignored. Planted/clean pairs: the conflicting arm is refused before any harness run
and says why in failure.json; the same arm with `-tp_revision` runs; a harness failure leaves failure.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops"), str(REPO)]
import exit_lever_ablation as e  # noqa: E402

LEG = "trend_donchian_eth_4h"
RETARGET = "--tp-target-r=3;--tp-retarget-mode=stall_pull_in;--tp-retarget-stall-bars=10"


def _cfg() -> dict:
    import yaml
    legs = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text(encoding="utf-8"))
    return legs.get("strategies", legs)[LEG]


def test_premise_the_leg_declares_tp_revision():
    # If this flips, the leg no longer reproduces the crash and the e2e pair below proves less.
    assert _cfg().get("tp_revision"), f"{LEG} no longer declares tp_revision"


@pytest.mark.parametrize("spec,conflict", [
    (f"R1={RETARGET}", True),
    ("T3=--tp-target-r=3", True),
    (f"R1=-tp_revision;{RETARGET}", False),
    ("D=trail_decay_stall_bars=8", False),
])
def test_conflict_detection(spec, conflict):
    label, sets, unsets, extra = e.parse_arm(spec)
    msg = e.tp_mover_conflict(label, e.arm_cfg(_cfg(), sets, unsets), extra)
    assert (msg is not None) is conflict
    if conflict:
        assert "-tp_revision" in msg


def test_no_conflict_on_a_leg_without_tp_revision():
    assert e.tp_mover_conflict("R1", {"tp_r": 50.0}, ["--tp-target-r", "3"]) is None


@pytest.fixture(scope="module")
def csv(tmp_path_factory):
    import numpy as np
    import pandas as pd
    d = tmp_path_factory.mktemp("tpmovers")
    rng = np.random.default_rng(7)
    ts = pd.date_range("2022-01-01", "2025-01-01", freq="4h", tz="UTC")
    c = 2000 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, len(ts))))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, len(ts))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, len(ts))))
    p = d / "c.csv"
    pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S%z"), "open": o, "high": h, "low": lo,
                  "close": c, "volume": 1000.0}).to_csv(p, index=False)
    return p


def _run(csv: Path, out: Path, *arms: str) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", LEG]
    for a in arms:
        argv += ["--arm", a]
    argv += ["--data-csv", str(csv), "--grade", "replace", "--baseline", "A", "--delta-r", "0",
             "--fold-majority", "2", "--folds", "3", "--n-floor", "5", "--out", str(out)]
    return subprocess.run(argv, cwd=REPO, capture_output=True, text=True, check=False, timeout=600)


def test_planted_conflict_is_refused_before_any_harness_run(csv, tmp_path):
    r = _run(csv, tmp_path, "A=", f"R1={RETARGET}")
    assert r.returncode == 2, r.stderr[-2000:]
    fail = json.loads((tmp_path / "failure.json").read_text())
    assert fail["stage"] == "preflight" and "-tp_revision" in fail["errors"][0]
    assert not (tmp_path / "arms").exists(), "the baseline ran before the refusal"


def test_clean_replacement_arm_runs_to_a_verdict(csv, tmp_path):
    r = _run(csv, tmp_path, "A=", f"R1=-tp_revision;{RETARGET}")
    assert r.returncode == 0, r.stderr[-2000:]
    v = json.loads((tmp_path / "verdict.json").read_text())
    assert v["verdict"] in e.VERDICTS
    assert not (tmp_path / "failure.json").exists()


def test_harness_failure_leaves_a_landable_cause(csv, tmp_path):
    # `--tp-thesis bogus` is an argparse refusal inside the harness: arm A completes, arm X dies.
    r = _run(csv, tmp_path, "A=", "X=--tp-thesis=bogus")
    assert r.returncode == 1
    fail = json.loads((tmp_path / "failure.json").read_text())
    assert fail["stage"] == "harness" and fail["arm"] == "X" and fail["arms_completed"] == ["A"]
    assert "bogus" in fail["stderr_tail"]
    # failure.json must survive the landing bundle (`git ls-files --exclude-standard`): not ignored.
    probe = subprocess.run(["git", "check-ignore", "-q", "comms/research/RQ-X/1/failure.json"], cwd=REPO, check=False)
    assert probe.returncode == 1
