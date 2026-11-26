"""--phase confirm (wave-2 confirmation of named U05 LEADS on a fresh window) and the event-design vol outcome fix.

Synthetic world: six symbols, hourly bars, an event class `alpha` planted every 130 h per symbol whose event bar has
3x the normal range (a real abnormal-RV effect), and a class `beta` that carries no effect."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scripts.research import news_alpha_ic as nai

UNIT = "RQ-20261126-5bd9-99"
SYMS = [f"S{i}USDT" for i in range(6)]
CELLS = ["alpha|abn_rv|1h|all|all", "beta|abn_rv|1h|all|all"]


def _world(tmp: Path):
    rng = np.random.default_rng(11)
    idx = pd.date_range("2025-08-01", "2026-03-01", freq="1h", tz="UTC")
    pdir = tmp / "prices"
    pdir.mkdir()
    frows = []
    for k, s in enumerate(SYMS):
        ev = np.zeros(len(idx), dtype=bool)
        ev[(np.arange(len(idx)) + 17 * k) % 130 == 0] = True
        beta = np.zeros(len(idx), dtype=bool)
        beta[(np.arange(len(idx)) + 29 * k + 60) % 130 == 0] = True
        vol = np.where(ev, 0.012, 0.004)
        ret = vol * rng.standard_normal(len(idx))
        close = 100 * np.exp(np.cumsum(ret))
        open_ = np.r_[100.0, close[:-1]]
        hi = np.maximum(open_, close) * (1 + vol)
        lo = np.minimum(open_, close) * (1 - vol)
        pd.DataFrame({"timestamp": idx, "open": open_, "high": hi, "low": lo, "close": close,
                      "volume": 1000.0}).to_csv(pdir / f"{s}_1h.csv", index=False)
        frows.append(pd.DataFrame({"ts": idx, "symbol": s, "max_available_at": idx - pd.Timedelta(minutes=15),
                                   "cls_alpha": np.where(ev, 1.0, np.nan), "cls_beta": np.where(beta, 1.0, np.nan)}))
    fcsv = tmp / "features.csv"
    pd.concat(frows).to_csv(fcsv, index=False)
    return pdir, fcsv


def _unit(tmp: Path, *, mde=0.3, src_p=0.01) -> Path:
    src = tmp / "source_discovery.json"
    src.write_text(json.dumps({"cells": [{"cell": c, "stat": 0.05, "p": src_p} for c in CELLS]}))
    raw = {"id": UNIT, "status": "queued", "grid": {"cells": CELLS}, "grid_cells": len(CELLS),
           "power": {"min_detectable_effect": mde},
           "news_alpha": {"source": "gdelt_panel", "design": "event", "bar": "1h", "price_source": "binance_vision",
                          "populations": {"all": SYMS}, "discovery_start": "2025-11-01",
                          "holdout": ["2025-11-01", "2026-02-20"],
                          "confirm": {"source_discovery": str(src)}}}
    q = tmp / "queue"
    q.mkdir(exist_ok=True)
    (q / f"{UNIT}.yaml").write_text(yaml.safe_dump(raw))
    return q


def _run(tmp, q, pdir, fcsv, out):
    led = tmp / "LEDGER.jsonl"
    led.touch()
    return nai.main(["--unit", UNIT, "--phase", "confirm", "--out", str(out), "--queue-dir", str(q),
                     "--features-csv", str(fcsv), "--prices-dir", str(pdir), "--ledger", str(led),
                     "--repo-root", str(tmp / "norepo"), "--run-id", "t1"])


def test_confirm_grades_planted_lead_and_spends_one_test(tmp_path):
    pdir, fcsv = _world(tmp_path)
    q = _unit(tmp_path)
    out = tmp_path / "out"
    assert _run(tmp_path, q, pdir, fcsv, out) == 0
    v = json.loads((out / "verdict.json").read_text())
    doc = json.loads((out / "confirm.json").read_text())
    by = {r["cell"]: r for r in doc["cells"]}
    assert doc["window_rule"]["floor_reached"] is True
    assert all(r["n"] >= 88 for r in by.values())                    # the window ends only once the floor is met
    assert by[CELLS[0]]["outcome"] == "PASS" and by[CELLS[1]]["outcome"] == "FAIL"
    assert v["verdict"] == "pass" and v["read_state"] == "measured" and v["n"] > 0
    rows = [json.loads(x) for x in (out / "ledger_rows.jsonl").read_text().splitlines()]
    assert {r["cell"] for r in rows} == set(CELLS) and all(r["wave"] == 2 for r in rows)
    # the one test per cell is spent: a second run is refused
    assert _run(tmp_path, q, pdir, fcsv, out) == 0
    assert json.loads((out / "verdict.json").read_text())["read_state"] == "producer_failed"


def test_underpowered_confirm_is_insufficient_and_spends_nothing(tmp_path):
    pdir, fcsv = _world(tmp_path)
    q = _unit(tmp_path, mde=0.05)                                  # floor 3140 events: never reached
    out = tmp_path / "out"
    assert _run(tmp_path, q, pdir, fcsv, out) == 0
    v = json.loads((out / "verdict.json").read_text())
    assert v["verdict"] == "indeterminate" and v["result_state"] == "insufficient"
    assert not (out / "ledger_rows.jsonl").exists()


def test_confirm_refuses_a_cell_that_was_not_a_lead(tmp_path):
    pdir, fcsv = _world(tmp_path)
    q = _unit(tmp_path, src_p=0.2)
    out = tmp_path / "out"
    _run(tmp_path, q, pdir, fcsv, out)
    v = json.loads((out / "verdict.json").read_text())
    assert v["read_state"] == "producer_failed" and "not a LEAD" in v["note"]


def test_event_vol_holdout_outcome_no_longer_needs_the_ts_improvement_field():
    assert nai.holdout_outcome({"kind": "vol", "holm_reject": True, "p": 0.001}) == "PASS"
    assert nai.holdout_outcome({"kind": "vol", "holm_reject": False, "p": 0.001}) == "FAIL"
    ts = {"kind": "vol", "holm_reject": True, "p": 0.01, "improvement": 0.01}
    assert nai.holdout_outcome(ts) == "FAIL"                       # ts design keeps the >= 2% HAR bar
    assert nai.holdout_outcome({**ts, "improvement": 0.03}) == "PASS"
    d = {"kind": "direction", "holm_reject": True, "discovery_net": {"mean": 0.001}, "net": {"t": 2.5}}
    assert nai.holdout_outcome(d) == "PASS"
    assert nai.holdout_outcome({**d, "net": {"t": 1.0}}) == "PASS_RANK_ONLY"
