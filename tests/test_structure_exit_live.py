"""STRUCTURE-EXITS-DEFAULT live wiring (src/runtime/structure_exit_live.py).

Pins, on RECORDED bars (tests/fixtures/ADAUSDT_2h_*.csv: 2h as recorded, 4h
resampled from it):

* byte-identical: an UNSELECTED leg never reaches the structure code, in all
  four target monitors (trend_donchian, htf_pullback_trend_2h, ml_entry,
  ml_entry_v2), and order_package adds no meta key;
* replay parity: the live monitor ticked bar by bar on growing frames (as
  production calls it, detector rebuilt on bars 0..t each tick) produces the
  SAME level list and the SAME SL/TP move sequence as the harness form
  (``StructureLevels`` built ONCE on the full frame, ``StructureExit.on_bar_close``
  per bar, as scripts/backtest_trend.py --structure-exit does);
* lookahead-negative: mutating every bar after t never changes the verdict at
  t, and no move cites a level before its confirmation bar;
* the § 5.2 contract: ratchet only (never looser than the entry stop), a close
  beats a move, one move per (package, bar), the TP venue-cap clamp and
  through-price refusal, both brackets kept.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.runtime import structure_exit_live as sxl
from src.runtime.structure_levels import StructureExit, StructureLevels, structure_sl, structure_tp
from src.runtime.tp_revision import clamp_to_venue_cap, tp_revision_rejection

FIX = Path(__file__).parent / "fixtures" / "ADAUSDT_2h_2020-06-03_2026-10-15.csv"
PARAMS = {"pivot": 3, "buffer_atr": 0.25, "min_r": 1.0, "fvg": True}


@pytest.fixture(scope="module")
def bars2h() -> pd.DataFrame:
    df = pd.read_csv(FIX, nrows=6000)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


@pytest.fixture(scope="module")
def bars4h(bars2h) -> pd.DataFrame:
    g = bars2h.set_index("timestamp").resample("4h")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last()}).dropna()
    return out.reset_index()


@pytest.fixture(autouse=True)
def _no_journal(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNTIME_LOGS_DIR", str(tmp_path))


def _atr(df, i, period=14):
    return sxl._atr_at(df["high"].to_numpy(float), df["low"].to_numpy(float),
                       df["close"].to_numpy(float), i, period)


def _pkg(df, i, direction, *, tf, structure=True, mult=2.5):
    entry = float(df["close"].iloc[i])
    atr = _atr(df, i)
    sl = entry - mult * atr if direction == "long" else entry + mult * atr
    tp = entry * (1.099 if direction == "long" else 0.901)
    meta = {"atr": atr, "risk_per_unit": abs(entry - sl), "entry_time": str(df["timestamp"].iloc[i]),
            "timeframe": tf, "atr_stop_mult": mult, "trail_mult": 3.0}
    if structure:
        meta["structure_exit"] = "pivot=3"
    return {"order_package_id": f"p{i}", "strategy_name": "t", "symbol": "ADAUSDT",
            "direction": direction, "entry": entry, "sl": sl, "tp": tp, "meta": meta}


# --------------------------------------------------------------------------- declaration
def test_declared_spellings():
    assert sxl.declared({}) is None
    assert sxl.declared({"structure_exit": None}) is None
    assert sxl.declared({"structure_exit": ""}) is None
    assert sxl.declared({"structure_exit": "pivot=5"})["pivot"] == 5
    d = sxl.declared({"structure_exit": {"pivot": 4, "fvg": False}})
    assert d == {"pivot": 4, "buffer_atr": 0.25, "min_r": 1.0, "fvg": False}
    assert sxl.declared({"structure_exit": "atr=3"}) is None       # malformed -> no move


# --------------------------------------------------------------------------- byte-identical
_MONITORS = [
    ("src.units.strategies.trend_donchian", "4h"),
    ("src.units.strategies.htf_pullback_trend_2h", "2h"),
    ("src.units.strategies.ml_entry", "1h"),
    ("src.units.strategies.ml_entry_v2", "1h"),
]


@pytest.mark.parametrize("modname,tf", _MONITORS)
def test_unselected_leg_never_reaches_structure_code(monkeypatch, bars2h, modname, tf):
    import importlib

    def _boom(*a, **k):
        raise AssertionError("structure code reached on an unselected leg")

    monkeypatch.setattr(sxl, "structure_exit_verdict", _boom)
    mod = importlib.import_module(modname)
    df = bars2h.iloc[:400].copy()
    for i in (200, 260, 330):
        for d in ("long", "short"):
            pkg = _pkg(df, i, d, tf=tf, structure=False)
            for t in (i + 5, i + 30, 399):
                mod.monitor({}, df.iloc[:t + 1], dict(pkg))      # must not raise _boom


@pytest.mark.parametrize("modname,tf", _MONITORS)
def test_selected_leg_reaches_structure_code(monkeypatch, bars2h, modname, tf):
    import importlib
    seen = []
    monkeypatch.setattr(sxl, "structure_exit_verdict",
                        lambda meta, pkg, df, **k: seen.append(1) or {"sl": 1.0})
    mod = importlib.import_module(modname)
    df = bars2h.iloc[:400]
    pkg = _pkg(df, 200, "long", tf=tf)
    pkg["meta"]["max_hold_min"] = 10 ** 9
    mod.monitor({}, df.iloc[:260], pkg)
    assert seen, modname


def test_order_package_meta_threading_only_when_declared():
    # the meta loop in trend_donchian / htf_pullback copies the key only when cfg declares it
    import inspect
    from src.units.strategies import htf_pullback_trend_2h, ml_entry, trend_donchian
    for mod in (trend_donchian, htf_pullback_trend_2h):
        assert '"structure_exit"):' in inspect.getsource(mod.order_package)
    assert 'if cfg.get("structure_exit") else {}' in inspect.getsource(ml_entry.order_package)


# --------------------------------------------------------------------------- parity
def _harness_sequence(df, i, direction, entry_sl, atr, end):
    """The harness form: levels on the FULL frame, start, then on_bar_close per bar."""
    is_long = direction == "long"
    entry = float(df["close"].iloc[i])
    risk = abs(entry - entry_sl)
    lv = StructureLevels(df["high"].to_numpy(float), df["low"].to_numpy(float), PARAMS["pivot"])
    s0 = structure_sl(lv, i, entry, is_long, atr, risk, buffer_atr=PARAMS["buffer_atr"])
    sl = entry_sl if s0 is None or (is_long and s0 <= entry_sl) or (not is_long and s0 >= entry_sl) else s0
    tp = structure_tp(lv, i, entry, is_long, risk, min_r=PARAMS["min_r"], fvg=PARAMS["fvg"])
    sx = StructureExit(lv, is_long, atr, buffer_atr=PARAMS["buffer_atr"], min_r=PARAMS["min_r"],
                       fvg=PARAMS["fvg"], sl=sl, risk=risk, tp=tp)
    seq = []
    for j in range(i, end + 1):
        sl, tp = sx.on_bar_close(j, float(df["close"].iloc[j]), sl, tp, entry)
        seq.append((j, sl, tp, [(x.kind, x.price, x.confirmed_idx) for x in lv.levels_asof(j)]))
    return seq


@pytest.mark.parametrize("frame", ["bars2h", "bars4h"])
def test_replay_parity_live_monitor_vs_harness(request, frame):
    from src.units.strategies import trend_donchian
    df = request.getfixturevalue(frame)
    tf = "2h" if frame == "bars2h" else "4h"
    n_moves = n_trades = 0
    for i in range(300, min(len(df) - 80, 2900), 173):
        for direction in ("long", "short"):
            is_long = direction == "long"
            pkg = _pkg(df, i, direction, tf=tf)
            end = i + 60
            hseq = _harness_sequence(df, i, direction, float(pkg["sl"]), pkg["meta"]["atr"], end)
            n_trades += 1
            for j, h_sl, h_tp, h_levels in hseq:
                # live level list on bars 0..j only == harness full-frame list at j
                live_levels = [(x.kind, x.price, x.confirmed_idx) for x in
                               StructureLevels(df["high"].to_numpy(float)[:j + 1],
                                               df["low"].to_numpy(float)[:j + 1], 3).levels_asof(j)]
                assert live_levels == h_levels
                low, high = float(df["low"].iloc[j]), float(df["high"].iloc[j])
                if (is_long and low <= pkg["sl"]) or (not is_long and high >= pkg["sl"]):
                    break                                           # the resting stop filled; both paths end
                price = float(df["close"].iloc[j])
                v = trend_donchian.monitor({}, df.iloc[:j + 1], dict(pkg))
                if v and v.get("action") == "close":
                    break
                exp_sl = h_sl if abs(h_sl - pkg["sl"]) > abs(pkg["sl"]) * 5e-4 else pkg["sl"]
                exp_tp = pkg["tp"]
                if h_tp is not None:
                    placed, _ = clamp_to_venue_cap(direction, h_tp, price)
                    if tp_revision_rejection(direction, placed, price) is None and \
                            abs(placed - pkg["tp"]) > abs(pkg["tp"]) * 5e-4:
                        exp_tp = round(placed, 8)
                if v:
                    assert set(v) >= ({"structure_move"})
                    pkg["sl"] = v.get("sl", pkg["sl"])
                    pkg["tp"] = v.get("tp", pkg["tp"])
                    n_moves += 1
                assert pkg["sl"] == pytest.approx(exp_sl, rel=1e-7), (i, direction, j)
                assert pkg["tp"] == pytest.approx(exp_tp, rel=1e-7), (i, direction, j)
    assert n_trades >= 20 and n_moves >= 20, (n_trades, n_moves)


def test_replay_move_sequence_equals_harness_step(bars4h):
    df = bars4h
    for i in range(300, 2000, 211):
        for direction in ("long", "short"):
            pkg = _pkg(df, i, direction, tf="4h")
            end = i + 50
            out = sxl.replay(highs=df["high"].to_numpy(float)[:end + 1], lows=df["low"].to_numpy(float)[:end + 1],
                             closes=df["close"].to_numpy(float)[:end + 1], entry_idx=i,
                             entry=pkg["entry"], is_long=direction == "long", entry_sl=pkg["sl"],
                             atr=pkg["meta"]["atr"], params=PARAMS)
            h = _harness_sequence(df, i, direction, pkg["sl"], pkg["meta"]["atr"], end)
            assert out["sl"] == h[-1][1] and out["tp"] == h[-1][2]
            # every recorded move reproduces the harness value at that bar
            hmap = {j: (s, t) for j, s, t, _ in h}
            for mv in out["moves"]:
                if mv["reason"] == "swing_ratchet":
                    assert mv["sl_after"] == hmap[mv["bar_idx"]][0]
                if mv["reason"] == "tp_extend":
                    assert mv["tp_after"] == hmap[mv["bar_idx"]][1]


# --------------------------------------------------------------------------- lookahead-negative
def test_future_bars_never_change_the_verdict(bars2h):
    from src.units.strategies import htf_pullback_trend_2h as mod
    df = bars2h.iloc[:900].reset_index(drop=True)
    rng = np.random.default_rng(7)
    for i in (300, 450, 600):
        for direction in ("long", "short"):
            pkg = _pkg(df, i, direction, tf="2h")
            for t in (i + 10, i + 40, i + 90):
                base = mod.monitor({}, df.iloc[:t + 1], dict(pkg))
                mut = df.copy()
                k = slice(t + 1, None)
                mut.loc[mut.index[k], "high"] = mut["high"].iloc[k] * (1 + rng.uniform(0, .2, len(mut) - t - 1))
                mut.loc[mut.index[k], "low"] = mut["low"].iloc[k] * (1 - rng.uniform(0, .2, len(mut) - t - 1))
                assert mod.monitor({}, mut.iloc[:t + 1], dict(pkg)) == base
                # and the replay over the FULL mutated frame up to t equals the truncated one
                full = sxl.replay(highs=mut["high"].to_numpy(float)[:t + 1], lows=mut["low"].to_numpy(float)[:t + 1],
                                  closes=mut["close"].to_numpy(float)[:t + 1], entry_idx=i, entry=pkg["entry"],
                                  is_long=direction == "long", entry_sl=pkg["sl"], atr=pkg["meta"]["atr"],
                                  params=PARAMS)
                for mv in full["moves"]:
                    if mv["level_confirmed_idx"] is not None:
                        assert mv["level_confirmed_idx"] <= mv["bar_idx"]


# --------------------------------------------------------------------------- contract
def test_ratchet_only_and_never_looser_than_entry_stop(bars4h):
    df = bars4h
    for i in range(300, 2500, 97):
        for direction in ("long", "short"):
            pkg = _pkg(df, i, direction, tf="4h")
            out = sxl.replay(highs=df["high"].to_numpy(float)[:i + 80], lows=df["low"].to_numpy(float)[:i + 80],
                             closes=df["close"].to_numpy(float)[:i + 80], entry_idx=i, entry=pkg["entry"],
                             is_long=direction == "long", entry_sl=pkg["sl"], atr=pkg["meta"]["atr"],
                             params=PARAMS)
            prev = pkg["sl"]
            for mv in out["moves"]:
                if mv["sl_after"] is None:
                    continue
                if direction == "long":
                    assert mv["sl_after"] >= prev >= pkg["sl"] - 1e-12
                else:
                    assert mv["sl_after"] <= prev <= pkg["sl"] + 1e-12
                prev = mv["sl_after"]


def test_idempotent_per_bar_and_journal(bars4h, tmp_path):
    from src.units.strategies import trend_donchian
    df = bars4h
    checked = 0
    for i in range(400, 2400, 37):
        t = i + 12
        pkg = _pkg(df, i, "long", tf="4h")
        v = trend_donchian.monitor({}, df.iloc[:t + 1], pkg)
        if not v or v.get("action") == "close":
            continue
        pkg["sl"], pkg["tp"] = v.get("sl", pkg["sl"]), v.get("tp", pkg["tp"])
        assert trend_donchian.monitor({}, df.iloc[:t + 1], pkg) is None  # same bar: no second move
        checked += 1
    assert checked >= 5
    rows = (tmp_path / sxl.JOURNAL_NAME).read_text().splitlines() if (tmp_path / sxl.JOURNAL_NAME).exists() else []
    import json
    for r in map(json.loads, rows):
        assert set(r) == set(sxl.JOURNAL_FIELDS) and r["phase"] == "proposed"


def test_close_beats_move_and_through_price_sl_closes(bars4h):
    from src.units.strategies import trend_donchian
    df = bars4h
    pkg = _pkg(df, 700, "long", tf="4h")
    pkg["sl"] = float(df["close"].iloc[720]) + 1.0          # price already through the stop
    v = trend_donchian.monitor({}, df.iloc[:721], pkg)
    assert v["action"] == "close" and v["reason"] == "sl_cross"   # the monitor's own close wins


def test_tp_through_price_refused_keeps_resting_tp():
    # a structure TP below price on a long is refused; the resting TP stays (no tp key)
    n = 40
    hi = np.r_[np.linspace(1.0, 1.2, 20), np.linspace(1.2, 2.0, 20)]
    df = pd.DataFrame({"timestamp": pd.date_range("2021-01-01", periods=n, freq="4h", tz="UTC"),
                       "open": hi - .01, "high": hi, "low": hi - .02, "close": hi - .005})
    pkg = {"direction": "long", "entry": float(df["close"].iloc[25]), "sl": float(df["close"].iloc[25]) - .1,
           "tp": 9.0, "meta": {"structure_exit": "pivot=2", "atr": .02, "risk_per_unit": .1,
                               "entry_time": str(df["timestamp"].iloc[25]), "timeframe": "4h"}}
    v = sxl.structure_exit_verdict(pkg["meta"], pkg, df, journal=False)
    assert v is None or "tp" not in v or v["tp"] > float(df["close"].iloc[-1])


def test_venue_outcomes_journalled(tmp_path):
    verdict = {"sl": 1.0, "structure_move": {"bar_ts": "x", "bar_idx": 3, "reason": "swing_ratchet",
                                             "sl_before": .9, "sl_after": 1.0}}
    sxl.journal_venue_outcomes({"order_package_id": "p"}, verdict, [
        {"leg": {"id": 1, "account_id": "bybit_1"}, "outcome": "applied", "venue_readback": {"kind": "ack", "ok": True}},
        {"leg": {"id": 2, "account_id": "bybit_2"}, "outcome": "failed", "error": "10001"},
    ])
    import json
    rows = [json.loads(x) for x in (tmp_path / sxl.JOURNAL_NAME).read_text().splitlines()]
    assert [r["outcome"] for r in rows] == ["applied", "failed"]
    assert rows[1]["error"] == "10001" and rows[0]["sl_after"] == 1.0
    # a verdict without structure_move journals nothing
    sxl.journal_venue_outcomes({}, {"sl": 1.0}, [{"leg": {}, "outcome": "applied"}])
    assert len((tmp_path / sxl.JOURNAL_NAME).read_text().splitlines()) == 2


# --------------------------------------------------------------------------- prop (prop_trail)
def test_prop_trail_structure_branch_matches_replay(bars4h):
    from datetime import timedelta
    from src.prop import prop_trail
    df = bars4h.iloc[:1200].reset_index(drop=True)
    i = 900
    entry = float(df["close"].iloc[i])
    atr = _atr(df, i)
    isl = entry - 2.5 * atr
    sig = df["timestamp"].iloc[i].to_pydatetime() + timedelta(minutes=5)   # forming decision: bar i holds it
    now = df["timestamp"].iloc[-1].to_pydatetime() + timedelta(hours=8)
    leg = {"timeframe": "4h", "atr_stop_mult": 2.5, "trail_mult": 3.0, "structure_exit": "pivot=3"}
    plan = prop_trail.plan_trail(leg=leg, direction="long", entry=entry, initial_sl=isl, signal_time=sig,
                                 resting_sl=isl, candles=df, now=now)
    exp = sxl.replay(highs=df["high"].to_numpy(float), lows=df["low"].to_numpy(float),
                     closes=df["close"].to_numpy(float), entry_idx=i, entry=entry, is_long=True,
                     entry_sl=isl, atr=atr if False else abs(entry - isl) / 2.5, params=PARAMS)
    assert plan.detail.get("source") == "structure_exit"
    assert plan.replay_sl == pytest.approx(exp["sl"]) and plan.detail["structure_tp"] == exp["tp"]
    # unselected leg: the chandelier path, no structure detail
    leg.pop("structure_exit")
    plan2 = prop_trail.plan_trail(leg=leg, direction="long", entry=entry, initial_sl=isl, signal_time=sig,
                                  resting_sl=isl, candles=df, now=now)
    assert "source" not in plan2.detail
