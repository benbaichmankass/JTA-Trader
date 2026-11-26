"""REGIME-LIVE-VETO-COUNTERFACTUAL: signal/drop matching, replay plumbing and the registered per-axis rule."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))

import regime_veto_counterfactual as R  # noqa: E402

BAR0 = 1795651200.0          # 2026-11-25T23:00Z, a 1h bar


def _iso(t: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def ev(st, t, bar=BAR0, side="buy", entry=100.0, sl=98.0, tp=104.0, sym="BTCUSDT"):
    return {"event": f"{st}_eval", "strategy": st, "symbol": sym, "side": side, "logged_at_utc": _iso(t), "timeframe": "1h",
            "entry": entry, "stop_loss": sl, "take_profit": tp, "bar_open_ts": bar}


def drop(st, t, vol=True, sym="BTCUSDT"):
    return {"event": "regime_hard_gate", "strategy": st, "symbol": sym, "side": "long", "logged_at_utc": _iso(t), "vol_enforced": vol}


def test_signal_status_and_axis():
    t = BAR0 + 3600 + 60
    rows = [ev("a", t), drop("a", t + 2), ev("a", t + 60), drop("a", t + 61),            # every tick dropped -> dropped, ml_vol
            ev("b", t), ev("b", t + 60), drop("b", t + 61, vol=False),                  # one of two -> mixed, trend
            ev("c", t), drop("c", t + 30),                                              # drop too late (>10 s) -> kept
            ev("d", t, side="none"), {"event": "x_eval", "side": "buy", "entry": None}]  # ignored
    s = {x["strategy"]: x for x in R.signals(rows)}
    assert set(s) == {"a", "b", "c"}
    assert (s["a"]["status"], s["a"]["axis"], s["a"]["ticks"]) == ("dropped", "ml_vol", 2)
    assert (s["b"]["status"], s["b"]["axis"]) == ("mixed", "trend")
    assert (s["c"]["status"], s["c"]["axis"]) == ("kept", None)


def _bars(path):
    """1h bars from BAR0+1h; path = list of (high, low, close), open = previous close (100 first)."""
    out, prev = [], 100.0
    for i, (h, lo, c) in enumerate(path):
        out.append({"time": BAR0 + 3600 * (i + 1), "open": prev, "high": h, "low": lo, "close": c})
        prev = c
    return out


def test_replay_hits_tp_and_sl_net_of_cost():
    s = R.signals([ev("a", BAR0 + 3700)])[0]
    tp = R.replay_signal(s, _bars([(101, 99.5, 100.5), (104.5, 100, 104)]), horizon=5)
    assert tp["close_reason"] == "tp_hit" and 1.9 < tp["net_r"] < 2.0          # +2 R gross minus a positive cost
    sl = R.replay_signal(s, _bars([(100.5, 97.5, 98)]), horizon=5)
    assert sl["close_reason"] == "sl_hit" and sl["net_r"] < -1.0
    assert R.replay_signal(s, _bars([(100.5, 99.5, 100)]), horizon=5) is None   # horizon not elapsed


def test_axis_rule_pass_fail_indeterminate():
    rng = random.Random(1)
    pool = {"a": [1.0, 0.8, 1.2, -0.2, 0.9, 1.1] * 5}
    bad = [{"strategy": "a", "net_r": -1.0} for _ in range(12)]
    assert R.axis_verdict(bad, pool, rng)["verdict"] == "pass"
    good = [{"strategy": "a", "net_r": 1.0 + 0.1 * (i % 3)} for i in range(12)]
    assert R.axis_verdict(good, pool, rng)["verdict"] == "fail"
    assert R.axis_verdict(bad[:3], pool, rng)["label"] == "underpowered"


def test_grade_end_to_end_with_stub_bars(tmp_path):
    rows = []
    for k in range(6):                                  # 6 dropped (ml_vol) signals that hit their stop; 6 kept that hit TP
        b = BAR0 + 3600 * 100 * k
        rows += [ev("a", b + 3700, bar=b), drop("a", b + 3702)]
        b2 = b + 3600 * 50
        rows += [ev("a", b2 + 3700, bar=b2, side="sell", entry=100.0, sl=102.0, tp=96.0)]
    snap = tmp_path / "s.jsonl"
    snap.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def bars_fn(sym, tf, start, end):
        out, t = [], BAR0
        while t <= end.timestamp():
            out.append({"time": t, "open": 100.0, "high": 100.5, "low": 97.0, "close": 99.0})   # every bar: longs stop out, shorts profit
            t += 3600
        return out
    rep = R.grade(snap, tmp_path / "out", bars_fn=bars_fn, horizon=4)
    assert rep["n_replayed"] == 12 and rep["signals_by_status"] == {"dropped": 6, "kept": 6}
    assert rep["axes"]["ml_vol"]["n"] == 6 and rep["axes"]["ml_vol"]["mean_r"] < -1.0
    assert rep["axes"]["trend"]["label"] == "underpowered" and rep["verdict"] == "indeterminate"
    assert rep["axes"]["ml_vol"]["n_mixed_signals"] == 0
    assert json.loads((tmp_path / "out" / "verdict.json").read_text())["rule_id"] == R.RULE_ID


def test_verdict_json_meets_the_script_run_contract(tmp_path):
    """script_run.py refuses a verdict.json without verdict / read_state / population / n (c4f2-01 run 45745911700 landed
    producer_failed 'n must be present'); the grade must also be strict JSON (no NaN)."""
    import script_run as SR
    rows = []
    for k in range(6):
        b = BAR0 + 3600 * 100 * k
        rows += [ev("a", b + 3700, bar=b), drop("a", b + 3702)]
    snap = tmp_path / "s.jsonl"
    snap.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def bars_fn(sym, tf, start, end):
        out, t = [], BAR0
        while t <= end.timestamp():
            out.append({"time": t, "open": 100.0, "high": 100.5, "low": 97.0, "close": 99.0})
            t += 3600
        return out
    R.grade(snap, tmp_path / "out", bars_fn=bars_fn, horizon=4)
    v = json.loads((tmp_path / "out" / "verdict.json").read_text())
    assert v["verdict"] in SR.VERDICTS and v["read_state"] in SR.READ_STATES and str(v["population"]).strip() and "n" in v
    assert v["n"] == 6
