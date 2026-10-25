"""TP doctrine B1, rule 2: the pullback-family ``tp_extend`` TP revision.

TPX-PULLBACK-PRODUCER (row on main; record
docs/research/evidence/tpx-xrp-family-read-2026-10-22.json). The research
verdict for cell X6 (``tpx_t3_a0.85_e1_m3``) was measured by
``scripts/backtest_pullback.py --tp-target-r 3 --tp-extend-r 1
--tp-approach-frac 0.85 --tp-max-extends 3 --tp-thesis native
--tp-cap-pct 0.099``. These tests pin that the live producer
(``tp_revision.tp_extend_path`` via ``htf_pullback_trend_2h.monitor``) moves
the SAME target on the SAME bars, so a leg declaring the rule trades the cell
that was measured -- and that a leg declaring nothing is byte-identical.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.runtime import tp_revision as tr
from src.units.strategies import htf_pullback_trend_2h as hp

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, str(ROOT / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


BP = _load("_tpx_pullback", "scripts/backtest_pullback.py")
import tp_geometry as TPG  # noqa: E402  (on sys.path via backtest_pullback)

X6 = dict(target_r=3.0, extend_r=1.0, approach_frac=0.85, max_extends=3)
DECL = {"rule": "tp_extend", "extend_r": 1.0, "approach_frac": 0.85, "max_extends": 3}
LEG = dict(trend_lookback=40, pullback_lookback=10, pullback_frac=0.5, atr_period=14,
           atr_stop_mult=2.5, trail_mult=6.0)


def _synth(seed, n=3000):
    """Seeded 2h series with trending regimes, volatile enough to trade and calm
    enough that 3R + extensions sit inside the 9.9% anchor cap (on a wilder
    series every extension is clamped away and the lever cannot fire)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([-0.004, -0.002, 0.0, 0.002, 0.004], size=n // 150 + 1),
                      150)[:n]
    c = 0.5 * np.exp(np.cumsum(drift + rng.normal(0, 0.005, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    ts = pd.date_range("2024-01-01", periods=n, freq="2h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": lo, "close": c,
                         "volume": 1.0})


def _harness_x6(df, tmp_path):
    out = tmp_path / "x6.jsonl"
    BP.run_backtest(df, timeout_bars=200, cooldown_bars=1, timeframe="2h", symbol="XRPUSDT",
                    tp_r=50.0, tp_cap_pct=0.099, emit_path=str(out),
                    tp_geometry=TPG.TPGeometrySpec(thesis="native", **X6), **LEG)
    return [json.loads(line) for line in out.read_text().splitlines()]


def _meta(df, i, risk, declare=True):
    meta = {"atr": risk / 2.5, "atr_period": 14, "trail_mult": 6.0, "tp_r": 3.0,
            "risk_per_unit": risk, "entry_time": str(df["timestamp"].iloc[i]),
            "timeframe": "2h", "adx_min": None}
    if declare:
        meta.update(tp_revision=dict(DECL), trend_lookback=40)
    return meta


def _rule_target(df, i, j, entry, risk, direction):
    """The live rule's target after bar j closed (bars[:j+1] are the closed bars).
    None = no extension yet = the entry-time TP stands."""
    rev = tr.plan_tp_revision(leg=_meta(df, i, risk), direction=direction, entry=entry,
                              risk=risk, bars=df.iloc[:j + 1],
                              entry_time=str(df["timestamp"].iloc[i]),
                              ref_price=float(df["close"].iloc[j]))
    return rev


@pytest.mark.parametrize("seed", [0, 3])
def test_live_rule_reproduces_the_harness_x6_targets_and_tp_exits(seed, tmp_path):
    df = _synth(seed)
    trades = _harness_x6(df, tmp_path)
    idx = {str(t): k for k, t in enumerate(df["timestamp"])}
    checked_ext = checked_tp_after_ext = 0
    for t in trades:
        i, x = idx[t["entry_time"]], idx[t["exit_time"]]
        entry, risk, d = float(t["entry"]), abs(float(t["entry"]) - float(t["sl"])), t["direction"]
        # The harness revises on every bar it survives; the exit bar is tested
        # against the PRE-revision target, except a timeout, which survives it.
        last = x if t["exit_reason"] == "timeout" else x - 1
        rev = _rule_target(df, i, last, entry, risk, d) if last > i else None
        cap = entry * (1.099 if d == "long" else 0.901)
        base = min(entry + 3 * risk, cap) if d == "long" else max(entry - 3 * risk, cap)
        live_target = base if rev is None else rev.tp
        live_r = ((live_target - entry) if d == "long" else (entry - live_target)) / risk
        assert live_r == pytest.approx(t["final_target_r"], abs=1e-3), t
        assert (0 if rev is None else rev.detail["n_extends"]) == t["n_extends"], t
        if t["n_extends"]:
            checked_ext += 1
        if t["exit_reason"] == "take_profit":
            # The harness fills a TP exit AT its target: the live resting TP is
            # that same price, so the exit R reproduces.
            assert live_r == pytest.approx(t["gross_r"], abs=1e-3), t
            checked_tp_after_ext += bool(t["n_extends"])
    # The fixture must actually exercise the lever (a negative needs a denominator).
    assert checked_ext >= 8 and checked_tp_after_ext >= 5


def test_monitor_emits_the_same_tp_through_the_live_path(tmp_path):
    """End to end through htf_pullback_trend_2h.monitor(): the forming last row
    is excluded, the verdict carries {tp, tp_reason}, and the level equals the
    harness tracker's after the same closed bar."""
    df = _synth(0)
    trades = [t for t in _harness_x6(df, tmp_path) if t["n_extends"] >= 2]
    assert trades
    idx = {str(t): k for k, t in enumerate(df["timestamp"])}
    hits = 0
    for t in trades:
        i, x = idx[t["entry_time"]], idx[t["exit_time"]]
        entry, risk, d = float(t["entry"]), abs(float(t["entry"]) - float(t["sl"])), t["direction"]
        last = x if t["exit_reason"] == "timeout" else x - 1
        frame = df.iloc[:last + 2]          # bars[:last+1] closed + one forming row
        pkg = {"order_package_id": "p", "strategy_name": "xrp_pullback_2h", "direction": d,
               "entry": entry, "sl": entry - risk if d == "long" else entry + risk,
               "tp": 0.0, "meta": _meta(df, i, risk)}
        pkg.pop("tp")                       # no resting-TP cross test in the way
        v = hp.monitor({}, frame, pkg)
        if v is None or "tp" not in v:
            continue                        # e.g. the forming close is already through it
        assert "tp_extend" in v["tp_reason"]
        got_r = ((v["tp"] - entry) if d == "long" else (entry - v["tp"])) / risk
        assert got_r == pytest.approx(t["final_target_r"], abs=1e-3)
        hits += 1
    assert hits >= 1


def test_undeclared_leg_is_byte_identical(tmp_path):
    df = _synth(0)
    t = next(t for t in _harness_x6(df, tmp_path) if t["n_extends"] >= 1)
    idx = {str(ts): k for k, ts in enumerate(df["timestamp"])}
    i, x = idx[t["entry_time"]], idx[t["exit_time"]]
    entry, risk, d = float(t["entry"]), abs(float(t["entry"]) - float(t["sl"])), t["direction"]
    frame = df.iloc[:x + 1]
    base = {"order_package_id": "p", "strategy_name": "xrp_pullback_2h", "direction": d,
            "entry": entry, "sl": entry - risk if d == "long" else entry + risk}
    declared = hp.monitor({}, frame, {**base, "meta": _meta(df, i, risk, declare=True)})
    plain = hp.monitor({}, frame, {**base, "meta": _meta(df, i, risk, declare=False)})
    assert plain is None or "tp" not in plain
    if declared is not None:
        assert {k: v for k, v in declared.items() if k not in ("tp", "tp_reason")} == (plain or {})


def test_close_verdict_wins_over_a_revision():
    df = _synth(0)
    i = 300
    entry = float(df["close"].iloc[i])
    pkg = {"order_package_id": "p", "strategy_name": "xrp_pullback_2h", "direction": "long",
           "entry": entry, "sl": float(df["close"].iloc[-1]) * 2, "meta": _meta(df, i, 0.01)}
    v = hp.monitor({}, df.iloc[:400], pkg)
    assert v["action"] == "close" and "tp" not in v


def test_path_core_extends_only_while_thesis_holds_and_respects_the_cap():
    # long, entry 100, risk 1, target 3R = 103. Closes approach (>= 102.55).
    closes = [100, 101, 102.6, 102.7, 103.6, 104.5, 105.5, 106.5]
    mids = [99] * len(closes)
    t, d = tr.tp_extend_path(closes, mids, start=0, end=2, direction="long", entry=100.0,
                             risk=1.0, target_r=3.0, extend_r=1.0, anchor_cap_pct=0.0)
    assert t == pytest.approx(104.0) and d["n_extends"] == 1
    t, d = tr.tp_extend_path(closes, mids, start=0, end=7, direction="long", entry=100.0,
                             risk=1.0, target_r=3.0, extend_r=1.0, max_extends=3,
                             anchor_cap_pct=0.0)
    assert t == pytest.approx(106.0) and d["n_extends"] == 3            # bounded
    # thesis broken (close below the midline) -> never extends -> None
    assert tr.tp_extend_path(closes, [200] * len(closes), start=0, end=7, direction="long",
                             entry=100.0, risk=1.0, target_r=3.0, extend_r=1.0,
                             anchor_cap_pct=0.0) is None
    # NaN midline = could not look = never extends
    assert tr.tp_extend_path(closes, [float("nan")] * len(closes), start=0, end=7,
                             direction="long", entry=100.0, risk=1.0, target_r=3.0,
                             extend_r=1.0, anchor_cap_pct=0.0) is None
    # a 3.5% anchor cap swallows every extension past 103.5
    t, d = tr.tp_extend_path(closes, mids, start=0, end=7, direction="long", entry=100.0,
                             risk=1.0, target_r=3.0, extend_r=1.0, anchor_cap_pct=0.035)
    assert t == pytest.approx(103.5) and d["n_extends"] == 1


def test_path_core_short_mirror():
    closes = [100, 99, 97.4, 96.4]
    t, d = tr.tp_extend_path(closes, [101] * 4, start=0, end=3, direction="short",
                             entry=100.0, risk=1.0, target_r=3.0, extend_r=0.5,
                             anchor_cap_pct=0.0)
    assert t == pytest.approx(96.0) and d["n_extends"] == 2


@pytest.mark.parametrize("bad", [
    {"rule": "tp_extend"},                                   # no extend_r: not a revision
    {"rule": "tp_extend", "extend_r": 0},
])
def test_rule_without_a_declared_step_is_inert(bad):
    df = _synth(0)
    meta = _meta(df, 300, 0.01)
    meta["tp_revision"] = bad
    assert tr.plan_tp_revision(leg=meta, direction="long", entry=float(df["close"].iloc[300]),
                               risk=0.01, bars=df.iloc[:500], entry_time=meta["entry_time"],
                               ref_price=float(df["close"].iloc[500])) is None


def test_entry_bar_missing_from_bars_is_could_not_look():
    df = _synth(0)
    meta = _meta(df, 300, 0.01)
    meta["entry_time"] = "2031-01-01T00:00:00Z"
    assert tr.plan_tp_revision(leg=meta, direction="long", entry=1.0, risk=0.01,
                               bars=df.iloc[:500], entry_time=meta["entry_time"],
                               ref_price=1.0) is None


def test_order_package_threads_the_declaration_only_when_declared():
    df = _synth(0)
    cfg = {"name": "xrp_pullback_2h", "symbol": "XRPUSDT", "timeframe": "2h", "tp_r": 3.0,
           **LEG}
    for end in range(400, 3000):
        try:
            plain = hp.order_package(dict(cfg), df.iloc[:end].copy())
        except ValueError:
            continue
        declared = hp.order_package({**cfg, "tp_revision": dict(DECL)}, df.iloc[:end].copy())
        break
    else:
        pytest.fail("fixture produced no signal")
    assert "tp_revision" not in plain["meta"] and "trend_lookback" not in plain["meta"]
    assert declared["meta"]["tp_revision"] == DECL
    assert declared["meta"]["trend_lookback"] == 40
    assert {k: v for k, v in declared.items() if k != "meta"} == \
        {k: v for k, v in plain.items() if k != "meta"}
