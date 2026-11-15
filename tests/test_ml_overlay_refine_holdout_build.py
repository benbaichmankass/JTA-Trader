"""RQ-20261115-7e18-03: `--refine nested` must honour the CLI's holdout build flag.

The nested path passed {"build": False} to run_holdout unconditionally, so a runner without --holdout-corpus-dir
never built the holdout corpus and every nested read came back INDETERMINATE ("no holdout corpus").
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("ml_overlay_noninferior_t", ROOT / "scripts/research/ml_overlay_noninferior.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _run(monkeypatch, tmp_path, build: bool):
    m = _mod()
    n = m.N_GATE_MIN + 10
    df = pd.DataFrame({"leg": ["a"] * n, "scored": True, "entry_time": pd.date_range("2021-01-01", periods=n, freq="D"),
                       "net_r": np.zeros(n)})
    seen = {}
    monkeypatch.setattr(m, "load_leg", lambda leg, d: df)
    monkeypatch.setattr(m, "run_cpcv_nested", lambda d, g: {"picks": {'{"C": 0.1, "q": 0.2}': 1}})
    monkeypatch.setattr(m, "evaluate", lambda *a, **k: {"pass": True, "folds": []})

    def fake_holdout(gate, train_df, h, cfg=None):
        seen["build"] = h.get("build", True)
        return {"state": "CONFIRMS"}

    monkeypatch.setattr(m, "run_holdout", fake_holdout)
    hold = {"start": "2017-09-01", "end": "2020-06-30", "days": 3500, "wd": tmp_path, "build": build}
    out = m.run_refine("nested", "TD", ["a"], ["a"], tmp_path, hold)
    return out, seen


def test_nested_builds_holdout_without_corpus_dir(monkeypatch, tmp_path):
    out, seen = _run(monkeypatch, tmp_path, build=True)
    assert seen["build"] is True
    assert out["verdict"] == "PASS"


def test_nested_reuses_holdout_with_corpus_dir(monkeypatch, tmp_path):
    _out, seen = _run(monkeypatch, tmp_path, build=False)
    assert seen["build"] is False
