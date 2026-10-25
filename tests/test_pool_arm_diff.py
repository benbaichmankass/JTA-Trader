"""scripts/research/pool_arm_diff.py: the pooled paired read of per-leg ablation arms.

Covers: a planted pooled effect that no single leg resolves passes; a null does not; the entry-set difference counts a
side missing from one arm as 0 R; a pool whose MDE exceeds the bar is INDETERMINATE (never graded); missing arm emits
are INDETERMINATE and unmeasured; a decisive loser is FAIL.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import pool_arm_diff as p  # noqa: E402


def _rows(leg, n, seed, shift, t0=datetime(2021, 1, 1, tzinfo=timezone.utc)):
    rng = random.Random(seed)
    base, arm = [], []
    for i in range(n):
        ts = t0 + timedelta(hours=12 * i)
        b = rng.gauss(0.0, 1.3)
        key = (leg, str(ts), "long")
        base.append(
            {"key": key, "entry": ts, "exit": ts + timedelta(hours=6), "net_r": b}
        )
        arm.append(
            {
                "key": key,
                "entry": ts,
                "exit": ts + timedelta(hours=6),
                "net_r": b + shift + rng.gauss(0, 0.4),
            }
        )
    return base, arm


def _pool(shift, legs=5, n=500):
    per = {}
    for i in range(legs):
        b, a = _rows(f"l{i}", n, i, shift)
        ctrl = [dict(r, net_r=r["net_r"] - 0.05) for r in a]
        per[f"l{i}"] = {"A": b, "C": a, "K": ctrl}
    return per


KW = dict(
    baseline="A",
    candidate="C",
    controls=["K"],
    bar=0.03,
    min_n=500,
    n_folds=6,
    fold_majority=5,
    dd_mult=1.35,
    reps=800,
)


def test_planted_pooled_effect_passes_where_one_leg_cannot_resolve_it():
    one = {"l0": _pool(0.06)["l0"]}
    assert (
        p.grade(one, **KW)["verdict"] == "indeterminate"
    )  # 500 trades: MDE above the 0.03 bar
    assert p.grade(_pool(0.06), **KW)["verdict"] == "pass"


def test_null_does_not_pass():
    assert p.grade(_pool(0.0), **KW)["verdict"] in ("fail", "indeterminate")


def test_decisive_loser_is_fail():
    assert p.grade(_pool(-0.2), **KW)["verdict"] == "fail"


def test_missing_side_counts_as_zero_r():
    t = datetime(2021, 1, 1, tzinfo=timezone.utc)
    base = [{"key": ("l", "a", "long"), "entry": t, "exit": t, "net_r": 1.0}]
    arm = [{"key": ("l", "b", "long"), "entry": t, "exit": t, "net_r": 2.0}]
    d = p.paired(base, arm)
    assert sorted(v for _, v in d.values()) == [-1.0, 2.0]


def test_below_min_n_is_indeterminate():
    assert (
        p.grade(_pool(0.06, legs=1, n=100), **{**KW, "min_n": 500})["verdict"]
        == "indeterminate"
    )


def test_missing_emits_are_unmeasured(tmp_path):
    out = tmp_path / "o"
    rc = p.main(
        [
            "--unit",
            "l0=RQ-X",
            "--candidate",
            "C",
            "--bar",
            "0.03",
            "--min-n",
            "5",
            "--folds",
            "6",
            "--fold-majority",
            "5",
            "--dd-mult",
            "1.35",
            "--root",
            str(tmp_path),
            "--out",
            str(out),
        ]
    )
    rec = json.loads((out / "verdict.json").read_text())
    assert (
        rc == 0
        and rec["verdict"] == "indeterminate"
        and rec["read_state"] == "unmeasured"
    )
