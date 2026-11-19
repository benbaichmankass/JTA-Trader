import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import codirection_drawdown as cd  # noqa: E402


def _journal(tmp_path, n_legs=5, n_days=260, seed=3):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2026-01-01", periods=n_days, freq="1D", tz="UTC")
    rows = []
    for leg in range(n_legs):
        for t in days[::2]:
            rows.append({"leg": f"L{leg}", "entry_time": str(t), "exit_time": str(t + pd.Timedelta(hours=30)),
                         "direction": "long" if rng.random() < 0.5 else "short", "net_r": float(rng.normal(0, 1))})
    p = tmp_path / "j.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    return p


def test_self_test_passes():
    assert cd._self_test() == 0


def test_journal_path_measures_and_grades(tmp_path):
    res = cd.run(Path("."), 3, 3, 200, 1, 100, 20, journal=_journal(tmp_path))
    assert res["read_state"] == "measured"
    assert res["verdict"] in {"hit", "miss", "indeterminate"}
    assert res["result"]["sum_r"]["n_snapshots"] > 100


def test_too_few_snapshots_is_indeterminate_not_miss(tmp_path):
    res = cd.run(Path("."), 3, 3, 100, 1, 10_000, 20, journal=_journal(tmp_path))
    assert res["verdict"] == "indeterminate"


def test_unreadable_journal_says_could_not_look(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    res = cd.run(Path("."), 3, 3, 100, 1, 10, 2, journal=p)
    assert res["read_state"] == "could_not_look"
