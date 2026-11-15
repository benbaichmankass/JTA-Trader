"""CRYPTO-FORMING-RDM-FORWARD: fidelity_remeasure's faithful arm models the forming decision bar for a crypto trend leg.

Synthetic 4h bars + matching 1m minutes, monkeypatched fetchers (offline). The approximate arm keeps `decision_bar`
omitted (the record's own argv); the faithful arm forwards the 1m CSV, so `decision_bar` is no longer omitted and the
faithful arm runs `--decision-bar forming`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import fidelity_remeasure as fr  # noqa: E402


def _synthetic(tmp: Path):
    rng = np.random.default_rng(5)
    t0 = pd.Timestamp("2024-01-01", tz="UTC")
    n_min = 260 * 240                                         # 260 4h bars of 1m minutes
    ts = t0 + pd.to_timedelta(np.arange(n_min), unit="min")
    c = 100 * np.cumprod(1 + 0.00002 + rng.normal(0, 0.0008, n_min))
    m1 = pd.DataFrame({"timestamp": ts, "open": c, "high": c * 1.0005, "low": c * 0.9995, "close": c, "volume": 1.0})
    m1.to_csv(tmp / "m1.csv", index=False)
    b = m1.set_index("timestamp").resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    b.to_csv(tmp / "bars.csv", index=False)
    return b


def test_faithful_arm_models_forming_for_crypto_trend(tmp_path, monkeypatch):
    bars = _synthetic(tmp_path)
    src = tmp_path / "rec__bt.json"
    src.write_text(json.dumps({"data_start": str(bars["timestamp"].iloc[0]), "data_end": str(bars["timestamp"].iloc[-1])}))
    monkeypatch.setattr(fr, "REPO", Path("/"))
    record = {"source_run": str(src).lstrip("/").replace("__bt.json", "__trades.jsonl"), "fidelity": "approximate",
              "omitted_levers": ["decision_bar"], "n_trades_oos": None, "net_r_oos": None}
    cfg = {"symbols": ["SOLUSDT"], "timeframe": "4h", "donchian": 20, "atr_period": 14, "atr_stop_mult": 2.5,
           "trail_mult": 4.0, "enabled": True, "execution": "live"}
    monkeypatch.setattr(fr.rdm, "_fetch_csv", lambda feed, days, out: Path(out).write_text((tmp_path / "bars.csv").read_text()))
    monkeypatch.setattr(fr, "_fetch_1m", lambda sym, s, e, out: (Path(out).write_text((tmp_path / "m1.csv").read_text()), None)[1])
    seen = {}
    real_run = fr._run

    def spy(argv):
        seen.setdefault("argvs", []).append(list(argv))
        return real_run(argv)
    monkeypatch.setattr(fr, "_run", spy)
    monkeypatch.setattr(fr.rdm, "build_harness_cmd", _wrap(fr.rdm.build_harness_cmd, seen))
    out = tmp_path / "out"
    out.mkdir()
    row = fr.measure("trend_donchian_sol_4h", cfg, record, out)
    arms = row.get("arms") or {}
    assert "error" not in arms.get("faithful", {}), arms
    assert arms["faithful"]["still_omitted"] == []                           # decision_bar now modelled
    assert "decision_bar" in seen["omitted_by_arm"][0]                       # approximate arm: as the record built it
    faithful_argv = seen["argvs"][-1]
    assert "--decision-bar" in faithful_argv and faithful_argv[faithful_argv.index("--decision-bar") + 1] == "forming"
    assert not list(out.glob("*1m*.csv"))                                    # bulky input never lands under --out


def _wrap(fn, seen):
    def inner(*a, **kw):
        argv, faithful, omitted = fn(*a, **kw)
        seen.setdefault("omitted_by_arm", []).append(list(omitted))
        return argv, faithful, omitted
    return inner
