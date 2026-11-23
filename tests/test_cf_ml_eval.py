"""CF-ML-EVAL: the counterfactual block beside an ML evaluation's realised R. Never raises; a failure is a recorded read_state."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import cf_ml_eval as ce  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

T0 = 1_792_000_000


def _bars(sym, tf, lo, hi):
    n = int((hi - lo) // 3600) + 2
    return [{"time": lo - (lo % 3600) + 3600 * i, "open": 100 - 0.2 * i, "high": 100.1 - 0.2 * i, "low": 99.9 - 0.2 * i, "close": 100 - 0.2 * i,
             "volume": 1.0, "dur": 3600} for i in range(n)]


def _row(i):
    return {"strategy": "trend_donchian", "symbol": "BTCUSDT", "entry_time": lrc._iso(T0 + 3600 * 10 * i), "exit_time": lrc._iso(T0 + 3600 * (10 * i + 5)),
            "entry": 100.0, "sl": 99.0, "direction": "short", "exit_price": 98.0, "exit_reason": "stop", "net_r": 1.5, "cost_fee_r": 0.01, "cost_funding_r": 0.0}


def test_block_reports_realised_beside_arms_with_fidelity():
    b = ce.cf_block([_row(i) for i in range(6)], {"timeframe": "1h", "symbol": "BTCUSDT", "strategy": "trend_donchian",
                                                  "params": {"atr_stop_mult": 2.0, "trail_mult": 3.0}}, n_random=5, bars_fn=_bars)
    assert b["read_state"] == "measured" and b["realised_mean_net_r"] == 1.5 and b["n_used"] == 6
    s = b["cf_summary"]
    assert s["n_graded"] == 6 and s["fidelity_abs_gap_r"]["n"] == 6 and "original_brackets" in s and s["alt_brackets_mean_by_cell"]


def test_unreadable_inputs_are_a_recorded_state_never_zero_never_a_raise():
    assert ce.cf_block([], None)["reason"] == "no_rows"
    assert ce.cf_block([_row(0)], {"timeframe": "7q", "symbol": "BTCUSDT"})["reason"] == "timeframe_or_symbol_unresolved"
    assert ce.cf_block([_row(0)], {"timeframe": "1h", "symbol": "SPY"})["reason"] == "no_bar_source"
    assert ce.cf_block([_row(0)], {"timeframe": "1h", "symbol": "BTCUSDT"}, bars_fn=lambda *a: [])["reason"] == "no_bars"

    def boom(*a):
        raise RuntimeError("net down")
    got = ce.cf_block([_row(0)], {"timeframe": "1h", "symbol": "BTCUSDT"}, bars_fn=boom)
    assert got["read_state"] == "could_not_look" and "net down" in got["reason"]


def test_holdout_hook_is_additive_and_has_an_opt_out():
    src = (REPO / "scripts/research/exit_head_holdout.py").read_text()
    assert "--no-cf" in src and 'out["cf"]' in src and "if not a.no_cf" in src
