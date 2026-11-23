"""CF-BACKTEST-FIDELITY: cf_bulk uses the harness's own params (the __bt.json sidecar) so the replay carries the SAME trail geometry the
harness used, resolves symbol/timeframe/strategy the rows do not carry, and replays a harness timeout as a close."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import cf_bulk  # noqa: E402
import cf_harness  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

T0 = 1_792_000_000


def _tree(tmp_path, rows, bt):
    d = tmp_path / "comms" / "research" / "RQ-x" / "1" / "cells"
    d.mkdir(parents=True)
    (d / "trend_X_B__trades.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (d / "trend_X_B__bt.json").write_text(json.dumps(bt))
    return "comms/research/RQ-x/1/cells/trend_X_B__trades.jsonl"


def _row(**kw):
    r = {"entry_time": "2026-01-01 00:00:00+00:00", "exit_time": "2026-01-02 00:00:00+00:00", "entry": 100.0, "sl": 98.0, "direction": "long",
         "exit_reason": "trail_stop", "net_r": 1.0}
    r.update(kw)
    return r


def test_sidecar_resolves_symbol_timeframe_strategy_and_rebuilds_trail_geometry(tmp_path):
    rel = _tree(tmp_path, [_row()], {"strategy": "trend_donchian", "symbol": "ETHUSDT", "timeframe": "4h",
                                     "params": {"atr_stop_mult": 2.0, "trail_mult": 3.5, "tp_r": 6.0}})
    cf_bulk.sidecar.__defaults__[1].clear()
    jobs, counts = cf_bulk.load_jobs([rel], tmp_path)
    (j,) = jobs.values()
    assert j["symbol"] == "ETHUSDT" and j["strategy"] == "trend_donchian" and j["_tf"] == "4h"
    assert counts["symbol_from_sidecar"] == 1 and counts["strategy_from_sidecar"] == 1
    assert j["_leg_meta"]["trail_mult"] == 3.5 and j["_leg_meta"]["atr"] == 1.0          # |100-98| / atr_stop_mult 2.0
    assert j["_leg_meta"]["tp"] == 112.0                                                    # entry + 6R
    shards, _ = cf_bulk.plan_shards(jobs)
    assert shards[0]["timeframe"] == "4h" and shards[0]["symbol"] == "ETHUSDT"              # the file name carries no timeframe


def test_no_sidecar_keeps_the_old_unresolved_states(tmp_path):
    d = tmp_path / "comms" / "research" / "RQ-y" / "1"
    d.mkdir(parents=True)
    (d / "a_trades.jsonl").write_text(json.dumps(_row()) + "\n")
    cf_bulk.sidecar.__defaults__[1].clear()
    jobs, _ = cf_bulk.load_jobs(["comms/research/RQ-y/1/a_trades.jsonl"], tmp_path)
    (j,) = jobs.values()
    assert j["symbol"] == "UNKNOWN" and "_leg_meta" not in j and "_tf" not in j


def _bars(path):
    return [{"time": T0 + 3600 * i, "open": px, "high": px + 0.05, "low": px - 0.05, "close": px, "volume": 1.0, "dur": 3600} for i, px in enumerate(path)]


def test_harness_timeout_is_replayed_as_a_close_and_other_exits_are_unchanged():
    trade = {"strategy": "s", "symbol": "BTCUSDT", "direction": "long", "entry_time": lrc._iso(T0), "exit_time": lrc._iso(T0 + 3600 * 4),
             "entry": 100.0, "sl": 99.0, "exit_price": 100.4, "exit_reason": "timeout", "net_r": 0.4, "cost_fee_r": 0.0, "cost_funding_r": 0.0}
    bars = _bars([100.0, 100.2, 100.3, 100.4, 100.4, 100.4, 101.2, 101.2, 101.2, 101.2])
    cfg = {"timeframe": "1h", "max_hold_bars": 4}
    got = cf_harness.cf_fields(trade, bars, horizon_cfg=cfg, n_random=5)
    held = cf_harness.cf_fields(dict(trade, exit_reason="stop"), bars, horizon_cfg=cfg, n_random=5)
    assert got["status"] == "graded" and got["fidelity"]["abs_gap_r"] < 0.15                  # closed near the recorded 100.4
    assert held["fidelity"]["abs_gap_r"] > got["fidelity"]["abs_gap_r"]                         # a non-timeout row is not closed early


def _graded(i, orig, replay, arm):
    return {"strategy": "trend_donchian", "symbol": "BTCUSDT", "entry_time": f"2026-01-{i % 28 + 1:02d} {i // 28:02d}:00:00+00:00",
            "cf": {"status": "graded", "post_exit": {"verdict": {"resolved": False}},
                   "arms": {"original_brackets": {"net_r": orig}, "replayed_actual_net_r": replay,
                            "alt_brackets": [{"sl_mult": 1.5, "tp_r": 6.0, "net_r": arm}], "less_management": [], "more_management": []}}}


def test_bt_is_also_read_against_the_replayed_harness_trade_and_the_registered_rule_is_unchanged():
    # arm beats a no-trail original bracket by +0.5 R, but only equals the harness's own (trailing) trade: the registered delta says PASS,
    # the replay-baseline delta says FAIL. Both are reported; the registered rule keeps its original_brackets baseline.
    recs = [_graded(i, orig=-0.5, replay=0.0, arm=0.0 + (0.001 * (i % 3))) for i in range(150)]
    leg = cf_bulk.leg_verdicts(recs)["trend_donchian|BTCUSDT"]
    assert leg["bt"]["verdict"] == "PASS" and leg["bt"]["mean_delta_r"] > 0.45
    assert leg["bt_vs_replay"]["verdict"] == "FAIL" and abs(leg["bt_vs_replay"]["mean_delta_r"]) < 0.01
