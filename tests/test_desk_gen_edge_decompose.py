"""DESK-18C-EDGE-OPT: the exploration/confirm script composes the registered driver and must not drift from it."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.research import desk_gen_edge_decompose as e  # noqa: E402
from scripts.research import desk_gen_replay_driver as d  # noqa: E402


def _series(n: int = 400, drift: float = -0.05, seed: int = 3):
    rng = np.random.default_rng(seed)
    t0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    px, bars = 100.0, []
    for k in range(n):
        o = px
        px = max(1.0, px + drift + rng.normal(0, 0.4))
        bars.append({"time": t0 + k * 3600, "open": o, "high": max(o, px) + 0.2, "low": min(o, px) - 0.2, "close": px})
    return d.Series.from_bars("BTCUSDT", bars), t0


def test_us_schedule_hours_gap_and_prefix():
    a, b = datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 3, 1, tzinfo=timezone.utc)
    s = e.us_schedule(a, b, 100, seed=7)
    hrs = {datetime.fromtimestamp(c, tz=timezone.utc).hour for c in s}
    assert hrs <= set(e.US_HOURS)
    srt = sorted(s)
    assert min(y - x for x, y in zip(srt, srt[1:])) >= e.CONFIRM_MIN_GAP_H * 3600
    assert e.us_schedule(a, b, 40, seed=7) == s[:40]                       # a stopping rule on a count cannot depend on an outcome


def test_c1_filter_is_the_two_registered_clauses():
    base = {"hour_utc": 15, "sl_atr": 1.0}
    assert e.c1_pass(base)
    assert not e.c1_pass({**base, "hour_utc": 12}) and not e.c1_pass({**base, "hour_utc": 21})
    assert not e.c1_pass({**base, "sl_atr": 0.99}) and not e.c1_pass({**base, "sl_atr": None})


def _st(**kw):
    st = {"n": 400, "mean_net_r": 0.2, "mean_ci95": [0.05, 0.35], "net_r_per_capital_day": 0.3, "per_capital_day_ci95": [0.1, 0.5],
          "paired_diff_vs_random": 0.15, "paired_diff_ci95": [0.02, 0.28], "folds_positive": 3}
    st.update(kw)
    return st


def test_grade_c1_pass_fail_indeterminate():
    assert e.grade_c1(_st(), 0.05)[0] == "pass"
    assert e.grade_c1(_st(n=299), 0.05)[0] == "indeterminate"
    assert e.grade_c1(_st(paired_diff_vs_random=-0.01, paired_diff_ci95=[-0.2, 0.2]), 0.05)[0] == "fail"
    assert e.grade_c1(_st(mean_net_r=-0.01), 0.05)[0] == "fail"
    assert e.grade_c1(_st(paired_diff_ci95=[-0.02, 0.28]), 0.05)[0] == "indeterminate"      # S3 CI straddles 0
    assert e.grade_c1(_st(folds_positive=2), 0.05)[0] == "indeterminate"
    assert e.grade_c1(_st(), -0.01)[0] == "indeterminate"                                    # the edge is in 3 weeks
    assert e.grade_c1(_st(), None)[0] == "indeterminate"


def test_forward_records_replays_a_real_symbol_row_with_the_drivers_engine():
    s, t0 = _series()
    cut = t0 + 200 * 3600
    i = s.last_closed(cut)
    px = float(s.c[i])
    row = {"decision_id": "DD-x", "action": "propose_entry", "info_cutoff_at": datetime.fromtimestamp(cut, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
           "proposal": {"symbol": "BTCUSDT", "side": "short", "horizon_bars": 24, "entry": {"type": "market", "level": px, "good_till_bars": 1},
                        "stop": {"level": px + 3.0}, "tp": {"level": px - 3.0}}}
    rows = [row, {"action": "no_trade"}, {**row, "decision_id": "DD-y", "proposal": {**row["proposal"], "symbol": "SPY"}}]
    start = datetime.fromtimestamp(t0 + 30 * 3600, tz=timezone.utc)
    recs, skipped = e.forward_records({"BTCUSDT": s}, rows, start, start + timedelta(hours=250), draws=20)
    assert len(recs) == 1 and recs[0]["decision_id"] == "DD-x"
    assert skipped["not_a_proposal"] == 1 and skipped["symbol_without_candles"] == 1
    direct = d.simulate(s, i, -1.0, "market", px, px + 3.0, px - 3.0, 1, 24)
    assert direct.state == "filled" and abs(recs[0]["net_r"] - direct.net_r) < 1e-12
    assert recs[0]["diff"] is not None


def test_slice_defs_count_and_terciles():
    recs = [{"judge_prior": 0.2 + 0.001 * k, "p_hit": 0.3, "expected_r_net": 0.2, "tp_basis": "swing_level", "symbol": "ADAUSDT", "side": "short",
             "horizon": 48, "etype": "market", "sl_atr": 1 + 0.01 * k, "tp_atr": 2.0, "rr": 2.0, "htf_trend": "chop", "vol_pct": 0.5,
             "ret24_atr": 0.0, "ret168_atr": 0.0, "base_mean_r": 0.9, "dist_low_atr": 2.0, "session": "us", "hour_utc": 14,
             "novelty": "new", "n_in_packet": 1, "fold": 1, "pre_cutoff": True, "index": k} for k in range(90)]
    defs = e.slice_defs(recs)
    assert len(defs["judge_prior"]) == 3
    covered = sum(sum(1 for r in recs if p(r)) for p in defs["judge_prior"].values())
    assert covered == len(recs)                                                              # terciles partition the file
    assert "suspect_batch" in defs and "fold" in defs
