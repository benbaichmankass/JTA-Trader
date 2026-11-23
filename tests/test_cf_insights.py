"""CF-INSIGHTS analysis helpers: unique-trade dedupe, week-block CI, entry-arm fill accounting, slices."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import cf_insights as ci  # noqa: E402


def _r(k, et, rep, arm, sym="BTCUSDT", ctx=None, d="long"):
    return {"k": k, "strat": "trend_donchian_x", "fam": "trend_donchian", "sym": sym, "tf": "4h", "dir": d, "et": et, "rep": rep, "arm": arm,
            "ctx": ctx or {}, "post_mfe": None, "post_mae": None, "pv": None, "gap": 0.0}


def test_dedupe_keeps_one_job_per_unique_trade_deterministically():
    rows = [_r("b", "2026-01-01 00:00:00+00:00", 0.0, {}), _r("a", "2026-01-01 00:00:00+00:00", 0.0, {}), _r("c", "2026-01-02 00:00:00+00:00", 0.0, {})]
    u = ci.dedupe(rows)
    assert [r["k"] for r in u] == ["a", "c"]


def test_block_ci_covers_the_mean_and_ignores_nan_and_is_nan_when_empty():
    rng = np.random.default_rng(0)
    v = rng.normal(0.1, 1.0, 4000)
    wk = np.repeat(np.arange(200), 20)
    mu, lo, hi, n = ci.block_ci(v, wk)
    assert n == 4000 and lo < mu < hi and lo < 0.1 < hi
    assert np.isnan(ci.block_ci(np.array([np.nan, np.nan]), np.array([1, 2]))[0])


def test_entry_side_counts_unfilled_as_no_trade_and_prices_what_skipping_cost():
    rows = [_r(f"k{i}", f"2026-01-{i + 1:02d} 00:00:00+00:00", 1.0 if i < 3 else -1.0, {"ext_limit_0.25atr": (0.5 if i >= 3 else None)}) for i in range(6)]
    e = ci.entry_side(rows)[0]
    assert e["fill_rate"] == 0.5 and e["n_filled"] == 3 and e["mean_r_of_unfilled_trades"] == 1.0    # the three missed trades were the winners
    assert e["mean_delta_filled_r"] == 1.5 and e["net_effect_per_signal_r"] == round((4.5 - 3.0) / 6, 4)


def test_stop_curve_reads_a_monotone_curve_from_arm_names():
    rows = [_r(f"k{i}", f"2026-01-{i % 28 + 1:02d} {i // 28:02d}:00:00+00:00", 0.0,
               {"sl1_tp3": 0.0, "sl1.5_tp3": 0.1, "ext_sl2x_tp3R": 0.15, "ext_sl2x_notp": 0.2}) for i in range(600)]
    c = ci.stop_curve(rows)
    assert c["with_tp_mean_by_stop_mult"]["1.5"] == 0.1 and c["with_tp_mean_by_stop_mult"]["2"] == 0.15 and c["no_tp_by_stop_mult"]["2"] == 0.2
