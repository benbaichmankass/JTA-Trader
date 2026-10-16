"""Tests for scripts/research/news_alpha_ic.py (checklist NEWS-ALPHA-HARNESS) and the GDELT feature builder.

Controls, all on synthetic data with a KNOWN answer:
  * POSITIVE: a feature that legitimately leads returns and vol (known before the bar opens) survives
    discovery, confirms on the holdout and passes net of the cost stack.
  * NEGATIVE (noise): an unrelated feature produces no survivor -> the unit FAILS, never passes.
  * NEGATIVE (planted lookahead): the same predictive feature stamped as available AT the bar open is refused
    by L1 -> read_state producer_failed, never a verdict.
  * LEDGER: a second discovery run is refused (budget spent twice); a holdout read for a non-survivor is refused;
    a budget overflow is refused.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.research import news_alpha_features as naf
from scripts.research import news_alpha_ic as nai

UNIT = "RQ-20261012-5bd1-99"
SYMS = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]


def _unit(qdir: Path, features, targets, *, unit=UNIT, mde=0.1, design="ts") -> Path:
    grid = {"features": features, "targets": targets, "horizons": ["1h"], "populations": ["pop"]}
    raw = {
        "id": unit, "status": "queued", "grid": grid,
        "grid_cells": len(features) * len(targets),
        "power": {"min_detectable_effect": mde},
        "decision_rule": {"id": "RULE-TEST", "registered_at": "2026-10-12"},
        "news_alpha": {"source": "gdelt_panel", "design": design, "bar": "1h", "price_source": "binance_vision",
                       "populations": {"pop": SYMS}, "discovery_start": "2025-05-01",
                       "holdout": ["2025-09-01", "2025-11-30"]},
    }
    qdir.mkdir(parents=True, exist_ok=True)
    p = qdir / f"{unit}.yaml"
    p.write_text(yaml.safe_dump(raw))
    return p


def _world(tmp: Path, *, leak: bool = False):
    """Hourly prices where `signal` (known before each bar) drives the bar's return sign and its vol."""
    rng = np.random.default_rng(7)
    idx = pd.date_range("2025-04-01", "2025-12-15", freq="1h", tz="UTC")
    pdir = tmp / "prices"
    pdir.mkdir()
    frows = []
    for s in SYMS:
        sig = rng.standard_normal(len(idx))
        noise = rng.standard_normal(len(idx))
        vol = 0.004 * np.exp(0.35 * sig)
        ret = 0.0012 * np.sign(sig) + vol * rng.standard_normal(len(idx))
        close = 100 * np.exp(np.cumsum(ret))
        open_ = np.r_[100.0, close[:-1]]
        hi = np.maximum(open_, close) * (1 + vol * 0.5)
        lo = np.minimum(open_, close) * (1 - vol * 0.5)
        pd.DataFrame({"timestamp": idx, "open": open_, "high": hi, "low": lo, "close": close,
                      "volume": 1000 * (1 + np.abs(sig))}).to_csv(pdir / f"{s}_1h.csv", index=False)
        avail = idx if leak else idx - pd.Timedelta(minutes=15)
        frows.append(pd.DataFrame({"ts": idx, "symbol": s, "max_available_at": avail,
                                   "planted": sig, "noise": noise}))
    fcsv = tmp / "features.csv"
    pd.concat(frows).to_csv(fcsv, index=False)
    return pdir, fcsv


def _run(tmp, phase, fcsv, pdir, qdir, out, ledger, run_id="r1"):
    return nai.main(["--unit", UNIT, "--phase", phase, "--out", str(out), "--queue-dir", str(qdir),
                     "--features-csv", str(fcsv), "--prices-dir", str(pdir), "--ledger", str(ledger),
                     "--repo-root", str(tmp / "norepo"), "--run-id", run_id])


def _ledger(tmp: Path, budget=600) -> Path:
    p = tmp / "TEST-LEDGER.jsonl"
    p.write_text(json.dumps({"kind": "budget", "family": "NEWS-ALPHA", "discovery_budget_tests": budget,
                             "holdout_cap_tests": 20}) + "\n")
    return p


def test_positive_control_passes_net_of_cost(tmp_path):
    pdir, fcsv = _world(tmp_path)
    qdir, out = tmp_path / "q", tmp_path / "out"
    _unit(qdir, ["planted"], ["fwd_ret", "fwd_rv"])
    led = _ledger(tmp_path)
    assert _run(tmp_path, "discovery", fcsv, pdir, qdir, out, led) == 0
    disc = json.loads((out / "discovery.json").read_text())
    assert disc["l1_rows_asserted"] > 0
    assert set(disc["survivors"]) == {"planted|fwd_ret|1h|pop|all", "planted|fwd_rv|1h|pop|all"}
    for c in disc["cells"]:
        assert c["l3_placebo"]["outside_central_95"] is True
        assert c["window"][1] < "2025-09-01"                      # L4: nothing from the holdout
    assert _run(tmp_path, "holdout", fcsv, pdir, qdir, out, led) == 0
    v = json.loads((out / "verdict.json").read_text())
    assert v["verdict"] == "pass" and v["read_state"] == "measured", v
    hold = json.loads((out / "holdout.json").read_text())
    outcomes = {c["cell"]: c["outcome"] for c in hold["cells"]}
    assert outcomes["planted|fwd_ret|1h|pop|all"] == "PASS"
    assert outcomes["planted|fwd_rv|1h|pop|all"] == "PASS"
    led_rows = [json.loads(x) for x in (out / "ledger_rows.jsonl").read_text().splitlines()]
    assert sum(r["kind"] == "discovery_test" for r in led_rows) == 2
    assert sum(r["kind"] == "holdout_test" for r in led_rows) == 2
    # the record fan-out obeys the research-result contract
    for r in v["records"]:
        assert r["read_state"] == "measured" and isinstance(r["n"], int)


def test_noise_feature_fails_never_passes(tmp_path):
    pdir, fcsv = _world(tmp_path)
    qdir, out = tmp_path / "q", tmp_path / "out"
    _unit(qdir, ["noise"], ["fwd_ret", "fwd_rv"])
    led = _ledger(tmp_path)
    assert _run(tmp_path, "discovery", fcsv, pdir, qdir, out, led) == 0
    assert json.loads((out / "discovery.json").read_text())["survivors"] == []
    assert _run(tmp_path, "holdout", fcsv, pdir, qdir, out, led) == 0
    v = json.loads((out / "verdict.json").read_text())
    assert v["verdict"] == "fail" and v["read_state"] == "measured", v
    assert json.loads((out / "holdout.json").read_text())["cells"] == []      # holdout never read


def test_planted_lookahead_is_refused_by_l1(tmp_path):
    pdir, fcsv = _world(tmp_path, leak=True)
    qdir, out = tmp_path / "q", tmp_path / "out"
    _unit(qdir, ["planted"], ["fwd_ret"])
    led = _ledger(tmp_path)
    assert _run(tmp_path, "discovery", fcsv, pdir, qdir, out, led) == 0
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "producer_failed" and v["verdict"] == "not_applicable" and v["n"] is None
    assert "L1 leakage" in v["note"]
    assert not (out / "ledger_rows.jsonl").exists()                         # nothing spent from the budget
    # the holdout phase cannot proceed off a failed discovery either
    assert _run(tmp_path, "holdout", fcsv, pdir, qdir, out, led) == 0
    assert json.loads((out / "verdict.json").read_text())["read_state"] == "producer_failed"


def test_ledger_refusals(tmp_path):
    pdir, fcsv = _world(tmp_path)
    qdir = tmp_path / "q"
    _unit(qdir, ["noise"], ["fwd_ret"])
    led = _ledger(tmp_path)
    out1 = tmp_path / "out1"
    assert _run(tmp_path, "discovery", fcsv, pdir, qdir, out1, led) == 0
    # fold run 1's ledger into the family ledger, then a re-run of the unit is refused
    led.write_text(led.read_text() + (out1 / "ledger_rows.jsonl").read_text())
    out2 = tmp_path / "out2"
    assert _run(tmp_path, "discovery", fcsv, pdir, qdir, out2, led, run_id="r2") == 0
    v = json.loads((out2 / "verdict.json").read_text())
    assert v["read_state"] == "producer_failed" and "already has" in v["note"]
    # a holdout read for a cell that is not a ledgered survivor is refused
    disc = json.loads((out1 / "discovery.json").read_text())
    disc["survivors"] = ["noise|fwd_ret|1h|pop|all"]
    (out1 / "discovery.json").write_text(json.dumps(disc))
    assert _run(tmp_path, "holdout", fcsv, pdir, qdir, out1, led) == 0
    v = json.loads((out1 / "verdict.json").read_text())
    assert v["read_state"] == "producer_failed" and "not a ledgered discovery survivor" in v["note"]
    # budget overflow
    (tmp_path / "x").mkdir()
    led2 = _ledger(tmp_path / "x", budget=0)
    out3 = tmp_path / "out3"
    assert _run(tmp_path, "discovery", fcsv, pdir, qdir, out3, led2) == 0
    assert "exceeds the declared family budget" in json.loads((out3 / "verdict.json").read_text())["note"]


def test_grid_count_mismatch_is_producer_failed(tmp_path):
    qdir = tmp_path / "q"
    p = _unit(qdir, ["noise"], ["fwd_ret"])
    raw = yaml.safe_load(p.read_text())
    raw["grid_cells"] = 5
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(nai.ProducerFailed, match="grid_cells"):
        nai.load_spec(UNIT, qdir)


def test_registered_units_enumerate_to_their_declared_counts():
    """Every NEWS-ALPHA unit's grid enumerates to its grid_cells (the harness refuses otherwise)."""
    repo = Path(__file__).resolve().parents[1]
    units = sorted(repo.glob("research/queue/RQ-20261012-5bd1-*.yaml")) + \
        sorted(repo.glob("research/queue/blocked/RQ-20261012-5bd1-*.yaml"))
    assert len(units) == 14
    checked = 0
    for p in units:
        raw = yaml.safe_load(p.read_text())
        g = raw.get("grid") or {}
        if not ({"features", "event_classes"} & set(g)) or "item_types" in g or "arms" in g or "series" in g:
            continue
        assert len(nai.enumerate_cells(raw)) == raw["grid_cells"], p.name
        checked += 1
    assert checked >= 9


def test_stat_primitives():
    assert nai.bh_survivor(0.10 * 1 / 600, 1, 600) and not nai.bh_survivor(0.001, 1, 600)
    assert nai.holm_rejections([0.001, 0.2], 20) == [True, False]
    assert nai.holm_rejections([0.004], 20) == [False]                  # 0.004 > 0.05/20
    rng = np.random.default_rng(0)
    m, t, T = nai.nw_tstat(rng.standard_normal(5000) + 0.1, 3)
    assert T == 5000 and t > 5
    assert abs(nai.norm_p_two_sided(1.959964) - 0.05) < 1e-4


# ── feature builder (GDELT panel -> PIT features) ───────────────────────────────────────────────────────
def _panel(missing_hour=None):
    hours = pd.date_range("2025-01-01", periods=24 * 60, freq="1h", tz="UTC")
    rng = np.random.default_rng(3)
    rows, cov = [], []
    for h in hours:
        ok = 3 if (missing_hour is not None and h == missing_hour) else 4
        cov.append({"hour": h, "files_ok": ok, "files_missing": 4 - ok, "files_error": 0,
                    "max_avail": h + pd.Timedelta(minutes=45)})
        n = int(rng.poisson(5))
        if n:
            tones = rng.normal(-1, 2, n)
            rows.append({"hour": h, "entity": "BTC", "n": n, "n_dom": max(1, n - 1), "tone_sum": tones.sum(),
                         "tone_sq": (tones ** 2).sum(), "tone_min": tones.min(), "tone_max": tones.max(),
                         "cls_hack_exploit": int(rng.random() < 0.05)})
        rows.append({"hour": h, "entity": "MACRO", "n": 100, "n_dom": 50, "tone_sum": -100.0, "tone_sq": 500.0,
                     "tone_min": -9.0, "tone_max": 5.0, "top_conflict": int(rng.poisson(10))})
    return pd.DataFrame(rows), pd.DataFrame(cov)


def test_features_are_point_in_time_and_never_fabricate_zero():
    miss = pd.Timestamp("2025-02-10 05:00", tz="UTC")
    panel, cov = _panel(miss)
    f = naf.build_features(panel, cov, bar="1h", symbols_to_entity={"BTCUSDT": "BTC"})
    f["max_available_at"] = pd.to_datetime(f["max_available_at"], utc=True)
    have = f.dropna(subset=["max_available_at"])
    assert (have["max_available_at"] < have["ts"]).all()                      # L1 holds by construction
    row = f[f["ts"] == miss + pd.Timedelta(hours=1)].iloc[0]
    assert np.isnan(row["tone_level"]) and np.isnan(row["count_shock_z"])     # partial hour -> NaN, not 0
    assert f["count_shock_z"].notna().sum() > 500 and f["conflict"].notna().sum() > 500
    d = naf.build_features(panel, cov, bar="1d", symbols_to_entity={"BTCUSDT": "BTC"})
    d["max_available_at"] = pd.to_datetime(d["max_available_at"], utc=True)
    dh = d.dropna(subset=["max_available_at"])
    assert (dh["max_available_at"] < dh["ts"]).all()
    assert np.isnan(d.loc[d["ts"] == pd.Timestamp("2025-02-11", tz="UTC"), "tone_level"]).all()


def test_mixed_bar_populations(tmp_path):
    """One unit, an hourly population and a daily one (the U07 shape): each cell reads its own bar."""
    pdir, fcsv = _world(tmp_path)
    for s in SYMS:
        h = pd.read_csv(pdir / f"{s}_1h.csv", parse_dates=["timestamp"]).set_index("timestamp")
        d = h.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        d.reset_index().to_csv(pdir / f"{s}_1d.csv", index=False)
    qdir, out = tmp_path / "q", tmp_path / "out"
    p = _unit(qdir, ["planted"], ["fwd_rv"])
    raw = yaml.safe_load(p.read_text())
    raw["grid"] = {"features": ["planted"], "targets": ["fwd_rv"], "populations": ["hourly", "daily"],
                   "horizons_hourly": ["4h"], "horizons_daily": ["1d", "5d"]}
    raw["grid_cells"] = 3
    raw["news_alpha"]["populations"] = {"hourly": SYMS, "daily": SYMS}
    raw["news_alpha"]["population_bars"] = {"daily": "1d"}
    p.write_text(yaml.safe_dump(raw))
    spec = nai.load_spec(UNIT, qdir)
    assert spec.bars == ["1d", "1h"] and spec.view("daily").h_bars("5d") == 5 and spec.view("hourly").h_bars("4h") == 4
    led = _ledger(tmp_path)
    assert _run(tmp_path, "discovery", fcsv, pdir, qdir, out, led) == 0
    disc = json.loads((out / "discovery.json").read_text())
    by = {c["cell"]: c for c in disc["cells"]}
    assert set(by) == {"planted|fwd_rv|4h|hourly|all", "planted|fwd_rv|1d|daily|all", "planted|fwd_rv|5d|daily|all"}
    assert all(c["state"] == "measured" for c in by.values()), by
    assert by["planted|fwd_rv|1d|daily|all"]["rows"] < by["planted|fwd_rv|4h|hourly|all"]["rows"] / 10
