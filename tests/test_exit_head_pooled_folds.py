"""Pooled calendar folds + the D8 power census (COMPUTE-FILL-W48, plan node P2-PR1125-D8-exit-now-powered)."""
import json
import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
import exit_head_kaggle_bakeoff as K  # noqa: E402


def _synth(seed: int, n=4000):
    rng = random.Random(seed)
    px, t0, rows = 100.0, 1_600_000_000, []
    for i in range(n):
        o = px
        px = max(1.0, px * (1 + 0.004 * math.sin(i / 150.0 + seed) + rng.gauss(0, 0.006)))
        rows.append({"timestamp": (t0 + 3600 * i) * 1000, "open": o, "high": max(o, px) * 1.001,
                     "low": min(o, px) * 0.999, "close": px, "volume": 1000.0 + rng.random()})
    return rows


def test_census_mde_and_fold_floor():
    a = SimpleNamespace(num_folds=5, pool_folds=True, power_sd=0.99, power_mde=0.05, unit="U", rule_id="R",
                        registered_at="2026-11-25", candle_source="candle_dataset")
    legs = [{"leg": "L", "symbol": f"S{i}", "n_trades": 100} for i in range(60)]           # 6,000 pooled
    row = K.census_row(a, legs, {}, {})
    assert row["n"] == 5000 and abs(row["measurement"]["mde_r"] - 2.801585 * 0.99 / math.sqrt(5000)) < 1e-9
    assert row["verdict"] == "pass"                                                        # 0.0392 <= 0.05
    a.pool_folds = False                                                                   # per leg: 100 // 6 < 64
    assert K.census_row(a, legs, {}, {})["n"] == 0 and K.census_row(a, legs, {}, {})["verdict"] == "fail"


def test_universe_twins_are_the_60_perp_bp2_set():
    legs = K.universe_legs("bp2", "trend_donchian_eth_4h")
    assert len(legs) == 60 and {s for s, _ in legs} == {"trend_donchian_eth_4h"} and ("trend_donchian_eth_4h", "BTCUSDT") in legs


def test_pooled_mode_pools_every_leg_and_reports_one_pooled_leg(tmp_path, monkeypatch):
    import pandas as pd

    def fake_fetch(sym, dst, start, end=None):
        return K._csv_from_df(pd.DataFrame(_synth(abs(hash(sym)) % 1000)), dst)

    monkeypatch.setattr(K, "fetch_bybit_candles", fake_fetch)
    out = tmp_path / "o"
    K.main(["--unit", "RQ-TEST", "--out", str(out), "--candle-source", "bybit", "--pool-folds",
            "--legs", "trend_donchian:LINKUSDT,trend_donchian:XRPUSDT", "--arms", "holding_pays_neg25",
            "--num-folds", "2", "--registered-at", "2026-11-25", "--rule-id", "RULE-TEST"])
    v = json.loads((out / "verdict.json").read_text())
    legs = v["measurement"]["legs"]
    pooled = [lg for lg in legs if lg["leg"] == "POOLED"]
    per = [lg for lg in legs if lg.get("read_state") == "pooled"]
    assert len(pooled) == 1 and len(per) == 2
    assert pooled[0]["n_total_trades"] == sum(lg["n_total_trades"] for lg in per) > 0
    assert "POOLED entry times" in v["population"]


def test_causal_random_control_never_closes_a_trade_after_its_own_exit():
    import pandas as pd
    import exit_head_label_bakeoff as L
    df = pd.DataFrame({"close": [100.0 + i for i in range(50)]})
    T = lambda e, x, r: SimpleNamespace(entry_index=e, exit_index=x, entry=100.0 + e + 1, risk=1.0, direction="long", r_multiple=r)  # noqa: E731
    test = [(0, "L", "S", df, T(0, 3, 9.0)), (0, "L", "S", df, T(10, 40, 2.0))]
    # the head closed trade 2 at age 5 (exit_bar_index 16); trade 1 (exits at bar 3) can never reach age 5
    champ = [{"exit_head_fired": False}, {"exit_head_fired": True, "exit_bar_index": 16}]
    sums = L._causal_random_fold(test, champ, draws=200, seed=1)
    # draws that pick trade 1 keep its declared exit (dR 0); draws that pick trade 2 close at bar 16: r = (116-111)/1 = 5 vs 2.0 -> +3
    assert set(round(x, 6) for x in sums) <= {0.0, 3.0} and 0.0 in sums and 3.0 in sums
    summ = L._causal_random_summary([{"r_holding_pays": 2.0, "baseline_r": 2.0}] * 2, [sums], 200)
    assert summ["draws"] == 200 and summ["control_p95"] == 1.5 and summ["head_mean_dr_per_trade"] == 0.0
