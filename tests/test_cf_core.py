"""CF-B0-ENGINE-LIFT: cf_core is the ONE counterfactual engine; the live grader imports it and nothing is copied.

The golden file tests/data/cf_core_golden.json was captured from counterfactual_grader.py BEFORE the lift (git 4125d42
lineage); `test_grader_callers_are_byte_identical_to_the_pre_lift_golden` proves the lift changed no output.
Regenerate only on a deliberate engine change: CF_CORE_WRITE_GOLDEN=1 pytest tests/test_cf_core.py -k golden.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
spec = importlib.util.spec_from_file_location("counterfactual_grader", REPO / "scripts/research/counterfactual_grader.py")
cg = importlib.util.module_from_spec(spec)
sys.modules["counterfactual_grader"] = cg
spec.loader.exec_module(cg)

GOLDEN = REPO / "tests" / "data" / "cf_core_golden.json"
T0 = 1_792_000_000
GRADED_AT = "2026-10-30T00:00:00+00:00"


def _walk(rng, n, dur, start=100.0, vol=0.15, drift=0.0):
    bars, px = [], start
    for i in range(n):
        o = px
        c = o + drift + rng.gauss(0, vol)
        h = max(o, c) + abs(rng.gauss(0, vol / 2))
        lo = min(o, c) - abs(rng.gauss(0, vol / 2))
        bars.append({"time": T0 + i * dur, "open": o, "high": h, "low": lo, "close": c, "dur": dur})
        px = c
    return bars


def _cases() -> dict:
    out = {"simulate": [], "grade": []}
    rng = random.Random(20261030)
    for k in range(60):
        side = "long" if k % 2 else "short"
        sign = 1.0 if side == "long" else -1.0
        bars = _walk(rng, 80, 900, drift=sign * rng.choice([-0.02, 0.0, 0.03]))
        e = 100.0
        r = 1.0
        kw = dict(side=side, entry_ref=e, r_dist=r, t_entry=T0, stop0=e - sign * r,
                  tp=None if k % 5 == 0 else e + sign * rng.choice([2.0, 3.0]))
        acts = [{"ts": T0 + 900 * rng.randint(1, 30), "kind": "set_stop", "level": e - sign * rng.uniform(-0.5, 0.9)}]
        if k % 3 == 0:
            acts.append({"ts": T0 + 900 * rng.randint(1, 30), "kind": "close", "frac": 0.5})
        rules = [{"kind": "stop_at", "trigger_r": 1.0, "level_r": 0.0}] if k % 4 == 0 else []
        trail = 1.5 if k % 6 == 0 else None
        s = cg.simulate(bars, actions=acts, rules=rules, trail_dist=trail, **kw)
        cm = {"fee_bps": 5.5, "slip_exit_bps": 1.5, "fund_bps_window": 1.0, "fee_source": "t"}
        n = cg.net_of(s, side=side, entry_fill=e, r_dist=r, t_entry=T0, cm=cm)
        out["simulate"].append({"sim": s, "net": n})
    out["stitch"] = cg.stitch_bars({"15m": [dict(b, dur=None) for b in _walk(random.Random(1), 20, 900)][:0] or
                                    [{k_: v for k_, v in b.items() if k_ != "dur"} for b in _walk(random.Random(1), 20, 900)],
                                    "5m": [{k_: v for k_, v in b.items() if k_ != "dur"} for b in _walk(random.Random(2), 30, 300)]},
                                   T0)
    for k in range(8):
        side = "long" if k % 2 else "short"
        sign = 1.0 if side == "long" else -1.0
        pkg = {"order_package_id": f"pkg-{k}", "strategy_name": "s", "symbol": "ADAUSDT", "direction": side, "entry": 100.0,
               "sl": 100.0, "tp": 100.0 + sign * 3.0, "exit_plan": json.dumps({"stop": {"price": 100.0 - sign * 1.0}}),
               "meta": {"atr": 0.5, "trail_mult": 5.0}}
        bars = _walk(rng, 70, 900, drift=sign * 0.03)
        t_close = T0 + 900 * (20 + k)
        leg = {"id": 1, "account_id": "bybit_2", "account_class": "real_money", "status": "closed", "position_size": 10.0,
               "entry_price": 100.0, "exit_price": 100.0 - sign * 1.0, "exit_reason": "sl", "pnl": -9.5,
               "timestamp": cg.lrc._iso(T0), "closed_at": cg.lrc._iso(t_close), "fee_taker_usd": 0.0, "cost_source": None}
        acts = [{"ts_epoch": T0 + 3600, "kind": "set_stop", "level": 100.0 - sign * 0.5, "source": "operator",
                 "time_provenance": "ESTIMATED"}] if k % 2 else []
        hz = {"seconds": 6 * 3600.0, "hours": 6.0, "source": "test", "timeframe": "15m"}
        out["grade"].append(cg.grade_package(pkg, [leg], bars, [], acts, {"bybit_2": 200.0}, {}, graded_at=GRADED_AT,
                                             n_random=25, horizon=hz))
    return json.loads(json.dumps(out, sort_keys=True))


def test_grader_callers_are_byte_identical_to_the_pre_lift_golden():
    got = _cases()
    if os.environ.get("CF_CORE_WRITE_GOLDEN"):
        GOLDEN.write_text(json.dumps(got, sort_keys=True, indent=0))
    want = json.loads(GOLDEN.read_text())
    assert json.dumps(got, sort_keys=True) == json.dumps(want, sort_keys=True)
    assert len(want["simulate"]) == 60 and len(want["grade"]) == 8


# ---- one engine, no copy, no network
def test_the_live_grader_and_tm_bench_use_the_one_engine():
    import cf_core
    import tm_bench
    for name in ("simulate", "net_of", "grade_package", "stitch_bars", "cost_model", "resolve_horizon", "post_exit_block"):
        assert getattr(cg, name) is getattr(cf_core, name), f"{name} is a copy, not the cf_core engine"
    assert tm_bench._engine is cf_core and tm_bench.ENGINE_SIMULATE is cf_core.simulate


def test_cf_core_makes_no_network_or_subprocess_call(monkeypatch):
    import socket
    import subprocess
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("cf_core reached for the network / a subprocess")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    assert _cases()["grade"][0]["status"] == "graded"


# ---- the random control must not read the trade's exit time
def test_causal_random_control_never_reads_the_exit_time_and_the_legacy_one_does():
    import cf_core
    bars = _walk(random.Random(3), 80, 900)
    kw = dict(t_entry=T0, horizon_s=20 * 900.0)
    short = cf_core.random_usable_bars(bars, t_close=T0 + 5 * 900, mode="causal", **kw)
    long_ = cf_core.random_usable_bars(bars, t_close=T0 + 60 * 900, mode="causal", **kw)
    assert [b["time"] for b in short] == [b["time"] for b in long_] and len(short) == 20      # invariant to the exit
    leg_s = cf_core.random_usable_bars(bars, t_close=T0 + 5 * 900, mode="legacy_own_length", **kw)
    leg_l = cf_core.random_usable_bars(bars, t_close=T0 + 60 * 900, mode="legacy_own_length", **kw)
    assert len(leg_s) == 5 and len(leg_l) == 60                                               # the leak: window = realised life
    import pytest
    with pytest.raises(ValueError):
        cf_core.random_usable_bars(bars, t_close=T0, mode="bogus", **kw)


def test_grade_package_causal_mode_is_labelled_and_the_default_record_is_unlabelled():
    import json as _j
    pkg = {"order_package_id": "pkg-c", "strategy_name": "s", "symbol": "ADAUSDT", "direction": "short", "entry": 100.0, "sl": 100.0,
           "tp": 96.0, "exit_plan": _j.dumps({"stop": {"price": 101.0}}), "meta": {"atr": 0.5, "trail_mult": 5.0}}
    bars = _walk(random.Random(4), 70, 900, drift=-0.03)
    leg = {"id": 1, "account_id": "bybit_2", "account_class": "real_money", "status": "closed", "position_size": 10.0,
           "entry_price": 100.0, "exit_price": 101.0, "exit_reason": "sl", "pnl": -9.5, "timestamp": cg.lrc._iso(T0),
           "closed_at": cg.lrc._iso(T0 + 900 * 25), "fee_taker_usd": 0.0, "cost_source": None}
    acts = [{"ts_epoch": T0 + 3600, "kind": "set_stop", "level": 100.5, "source": "operator", "time_provenance": "ESTIMATED"}]
    hz = {"seconds": 6 * 3600.0, "hours": 6.0, "source": "test", "timeframe": "15m"}
    a = cg.grade_package(pkg, [leg], bars, [], acts, {"bybit_2": 200.0}, {}, graded_at=GRADED_AT, n_random=20, horizon=hz)
    b_ = cg.grade_package(pkg, [leg], bars, [], acts, {"bybit_2": 200.0}, {}, graded_at=GRADED_AT, n_random=20, horizon=hz,
                          random_mode="causal")
    assert "mode" not in a["random_control"] and b_["random_control"]["mode"] == "causal"


# ---- cf_bars
def test_package_pages_walks_offsets_and_refuses_a_truncated_read():
    import cf_bars
    import pytest
    data = [{"i": i} for i in range(7)]
    calls = []

    def page(limit, offset):
        calls.append(offset)
        return data[offset:offset + limit]
    assert [r["i"] for r in cf_bars.package_pages(page, page_size=3)] == list(range(7)) and calls == [0, 3, 6]
    with pytest.raises(RuntimeError):
        list(cf_bars.package_pages(lambda lim, off: data[:3], page_size=3, max_pages=4))


def test_historical_bars_window_shape_and_the_no_bars_state():
    import datetime as dt

    import cf_bars
    rows = [{"timestamp": dt.datetime.fromtimestamp(T0 + 3600 * i, dt.timezone.utc), "open": 1, "high": 2, "low": 0.5, "close": 1.5}
            for i in range(10)] * 2                                                  # duplicates collapse
    f = lambda sym, tf, t0, t1: rows                                                 # noqa: E731
    got = cf_bars.historical_bars("ADAUSDT", "1h", T0 + 3 * 3600 + 1, T0 + 6 * 3600, f)
    assert [b["time"] for b in got] == [T0 + 3 * 3600, T0 + 4 * 3600, T0 + 5 * 3600] and got[0]["dur"] == 3600.0
    assert cf_bars.bars_for_package({"symbol": "X"}, t_entry=T0, t_close=T0 + 7200, horizon_s=3600, tf="1h",
                                    fetcher=lambda *a: [])[1] == "no_bars"
    assert cf_bars.bars_for_package({"symbol": "X"}, t_entry=T0, t_close=T0 + 7200, horizon_s=3600, tf="1h", fetcher=f)[1] is None


# ---- fidelity adapter (PI-20261030-TMBENCH-0001): the harness fills a trail exit AT its level even past the exit bar's open
def _trade_dict(exit_r, stop_last, tgt_last, o_last):
    nan = float("nan")
    return {"entry_over_risk": 100.0, "tfm": 240, "bars": 3, "symbol": "ETHUSDT", "cost_fee_r": 0.01, "leg": "x",
            "exit_reason": "trail_stop", "exit_r": exit_r,
            "c_r": [0.2, 0.4, exit_r], "o_r": [0.0, 0.2, o_last], "fav": [0.5, 0.8, 1.0], "adv": [-0.1, 0.1, 0.9],
            "stop_r": [-1.0, 0.0, stop_last], "target_r": [3.0, 3.0, tgt_last]}


def test_exit_bar_fills_at_the_harness_level_not_the_gap_open():
    import tm_bench
    t = _trade_dict(exit_r=1.5, stop_last=1.5, tgt_last=float("nan"), o_last=1.2)     # long; trail level 1.5 R is above the open
    bars = tm_bench.engine_bars(t)
    net, info = tm_bench.replay(t, bars, {"fee_bps": 0.0, "slip_exit_bps": 0.0, "fund_bps_window": 0.0, "fee_source": "t"})
    assert abs(info["gross_r"] - 1.5) <= 0.01 and info["sim"]["fills"][-1]["reason"] == "stop"
    # the engine itself still gap-fills at the open (the unchanged, tested rule): the fix lives in the adapter only
    raw = [dict(b) for b in bars]
    raw[-1]["open"] = 100.0 + 1.2
    s = cf_core_sim(raw, t)
    assert abs((s["fills"][-1]["px"] - 100.0) - 1.2) < 1e-9


def cf_core_sim(bars, t):
    import tm_bench
    return tm_bench.ENGINE_SIMULATE(bars, side="long", entry_ref=100.0, r_dist=1.0, t_entry=0.0, stop0=99.0, tp=103.0,
                                    actions=tm_bench.leg_actions(t))
