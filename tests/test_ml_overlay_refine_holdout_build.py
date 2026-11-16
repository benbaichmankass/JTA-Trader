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


def test_holdout_artifact_is_scored_without_refit(monkeypatch, tmp_path):
    """--holdout-artifact: run_holdout scores the given artifact; export_model (the refit) is never called."""
    m = _mod()
    rng = np.random.default_rng(0)
    n = m.HOLDOUT_N_MIN + 50
    feats = list(m.FEATURES)
    df = pd.DataFrame({f: rng.normal(size=n) for f in feats})
    df["leg"], df["scored"] = "a", True
    df["entry_time"] = pd.date_range("2018-01-01", periods=n, freq="D", tz="UTC")
    df["exit_time"] = df["entry_time"] + pd.Timedelta(hours=8)
    df["direction"], df["aligned"] = "long", True
    df["net_r"] = rng.normal(0.1, 1.0, size=n)
    (tmp_path / "a__trades.jsonl").write_text("")
    monkeypatch.setattr(m, "load_leg", lambda leg, d: df)
    monkeypatch.setattr(m, "export_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("refit called")))
    art = {"features": feats, "mean": [0.0] * len(feats), "std": [1.0] * len(feats), "coef": [0.0] * len(feats),
           "intercept": 0.0, "tau": 0.4, "multiplier": 0.5}
    h = {"start": "2017-09-01", "end": "2020-06-23", "days": 3500, "wd": tmp_path, "build": False,
         "before": pd.Timestamp("2020-06-24", tz="UTC"), "artifact": art, "artifact_ref": "x sha256 y"}
    out = m.run_holdout(["a"], df, h)
    assert out["scored_artifact"] == "x sha256 y"
    assert out["n"] == n


def test_ev_breakeven_and_challenger_block(monkeypatch, tmp_path):
    m = _mod()
    assert abs(m.ev_breakeven_p(np.array([2.0, 2.0, -1.0, -1.0])) - 1 / 3) < 1e-9
    rng = np.random.default_rng(1)
    n = m.HOLDOUT_N_MIN + 80
    feats = list(m.FEATURES)
    df = pd.DataFrame({f: rng.normal(size=n) for f in feats})
    df["leg"], df["scored"], df["direction"], df["aligned"] = "a", True, "long", True
    df["entry_time"] = pd.date_range("2018-01-01", periods=n, freq="D", tz="UTC")
    df["exit_time"] = df["entry_time"] + pd.Timedelta(hours=8)
    df["net_r"] = rng.normal(0.1, 1.0, size=n)
    (tmp_path / "a__trades.jsonl").write_text("")
    monkeypatch.setattr(m, "load_leg", lambda leg, d: df)
    base = m.export_model(df, m.PRIMARY)
    h = {"start": "2017-09-01", "end": "2020-06-23", "days": 3500, "wd": tmp_path, "build": False,
         "before": pd.Timestamp("2020-06-24", tz="UTC"), "artifact": base, "artifact_ref": "b", "challenger": "ev"}
    out = m.run_holdout(["a"], df, h)
    c = out["challenger"]
    assert c["tau_rule"] == "ev" and c["n"] == n
    # paired identity: (ch - base) == (ch - take) - (base - take)
    assert abs(c["delta_ch_vs_base_mean_r"] - (c["delta_ch_vs_take_r"] - c["delta_base_vs_take_r"])) < 2e-4


def test_challenger_block_reports_below_the_n_floor(monkeypatch, tmp_path):
    """cc86-01 holdout B (n 95): the verdict stays INDETERMINATE but the paired numbers are printed."""
    m = _mod()
    rng = np.random.default_rng(2)
    n = m.HOLDOUT_N_MIN - 5
    feats = list(m.FEATURES)
    df = pd.DataFrame({f: rng.normal(size=n) for f in feats})
    df["leg"], df["scored"], df["direction"], df["aligned"] = "a", True, "long", True
    df["entry_time"] = pd.date_range("2019-12-01", periods=n, freq="D", tz="UTC")
    df["exit_time"] = df["entry_time"] + pd.Timedelta(hours=8)
    df["net_r"] = rng.normal(0.1, 1.0, size=n)
    (tmp_path / "a__trades.jsonl").write_text("")
    monkeypatch.setattr(m, "load_leg", lambda leg, d: df)
    big = pd.concat([df] * 3, ignore_index=True)
    h = {"start": "2019-12-01", "end": "2020-06-23", "days": 3500, "wd": tmp_path, "build": False,
         "before": pd.Timestamp("2020-06-24", tz="UTC"), "artifact": m.export_model(big, m.PRIMARY),
         "artifact_ref": "b", "challenger": "ev"}
    out = m.run_holdout(["a"], big, h)
    assert out["state"] == "INDETERMINATE" and out["n"] == n
    assert out["challenger"] is not None and out["challenger"]["n"] == n
