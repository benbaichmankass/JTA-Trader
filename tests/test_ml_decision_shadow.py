"""Observe-only ML ENTRY decision log (src/runtime/ml_decision_shadow.py).

Pins: (1) offset-0 hourly bars built from 15m klines ARE the native 1h bars; (2) at a traded 4h close the logged decision
equals the strategy's own order_package decision on the same bars (v1 and v2); (3) nothing here can place an order (no
order/account/risk import; off-4h rows are never trading bars; the strategies refuse off the 4h close); (4) the 15m cache
fetches only the tail and never keeps the forming bar; (5) freshness has four states; (6) one end-to-end pass.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.runtime import ml_decision_shadow as M

REPO = Path(__file__).resolve().parents[1]
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOTUSDT", "LTCUSDT", "LINKUSDT", "AVAXUSDT", "BNBUSDT"]


def _bars_15m(seed: int, end: pd.Timestamp, n: int = M.KEEP_15M) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(end=end - M.STEP, periods=n, freq="15min", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.002, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.002, n))
    v = rng.uniform(100, 1000, n)
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v})


def _native_1h(b15: pd.DataFrame) -> pd.DataFrame:
    g = b15.set_index("ts").resample("1h", label="left", closed="left")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(), "n": g["open"].count()})
    out = out[out["n"] == 4].drop(columns="n").reset_index()
    return out[["ts", "open", "high", "low", "close", "volume"]]


B4 = pd.Timestamp("2026-10-20T08:00:00Z")   # an 08:00 close: a 4h decision bar (bar opened 07:00)


def test_offset_zero_hourly_equals_native_1h():
    b15 = _bars_15m(1, B4)
    got = M.hourly_ending_at(b15, B4)
    want = _native_1h(b15)
    pd.testing.assert_frame_equal(got.reset_index(drop=True), want.reset_index(drop=True), check_dtype=False)
    assert got["ts"].iloc[-1] == B4 - M.HOUR


def test_offset_15m_bins_end_at_the_boundary():
    b = B4 + pd.Timedelta(minutes=15)
    b15 = _bars_15m(2, b)
    h = M.hourly_ending_at(b15, b)
    assert h["ts"].iloc[-1] == b - M.HOUR                      # last bin opened at 07:15, closes at 08:15
    last4 = b15[(b15.ts >= b - M.HOUR) & (b15.ts < b)]
    assert len(last4) == 4
    assert h["open"].iloc[-1] == last4["open"].iloc[0] and h["close"].iloc[-1] == last4["close"].iloc[-1]
    assert h["high"].iloc[-1] == last4["high"].max() and h["volume"].iloc[-1] == pytest.approx(last4["volume"].sum())
    assert M.tf_offset(b) == "15m"


def test_incomplete_hour_is_dropped_not_padded():
    b15 = _bars_15m(3, B4)
    holed = b15.drop(index=b15.index[-6])                       # remove one 15m bar inside the 2nd-to-last hour
    h = M.hourly_ending_at(holed, B4)
    assert (B4 - 2 * M.HOUR) not in set(h["ts"])
    assert h["ts"].iloc[-1] == B4 - M.HOUR


def _models():
    from src.units.strategies import ml_entry, ml_entry_v2
    return {"ml_entry": ml_entry.load_model(), "ml_entry_v2": ml_entry_v2.load_model()}


def _prepared(b):
    return {s: M.prepare(s, _bars_15m(10 + i, b), b) for i, s in enumerate(SYMS)}


@pytest.mark.parametrize("strategy", ["ml_entry", "ml_entry_v2"])
def test_logged_decision_at_a_4h_close_equals_the_traded_decision(strategy):
    pytest.importorskip("lightgbm")
    from src.units.strategies import ml_entry
    models = _models()
    prep = _prepared(B4)
    cfgs = {n: {"symbols": ["BTCUSDT", "ETHUSDT"], "min_reference_symbols": 5} for n in models}
    rows = [r for r in M.score_boundary(B4, prep, models, strategy_cfgs=cfgs) if r["strategy"] == strategy]
    assert rows and all(r["trading_bar"] for r in rows)
    frames = {s: sb.hourly for s, sb in prep.items()}
    checked = 0
    for r in rows:
        assert r["read_state"] == "ok", r
        try:
            pkg = ml_entry.order_package({"symbol": r["symbol"], "min_reference_symbols": 5}, candles_df=frames[r["symbol"]],
                                         reference_frames={k: v for k, v in frames.items() if k != r["symbol"]},
                                         model=models[strategy])
            traded = pkg["direction"]
            assert pkg["meta"]["p_long"] == pytest.approx(r["pred_long"], abs=1e-5)
        except ValueError as exc:
            traded = "none"
            if str(exc).startswith("cost_gate"):
                assert r["refused"] == "cost_gate"
        assert r["side"] == traded, (r["symbol"], r["side"], traded)
        checked += 1
    assert checked == len(SYMS)


@pytest.mark.parametrize("b", [B4, B4 + pd.Timedelta(minutes=45)])
def test_batched_rows_are_bit_identical_to_decision_row(b):
    import src.runtime.ml_decision_features as F
    prep = _prepared(b)
    frames = {s: sb.hourly for s, sb in prep.items()}
    frames["ZILUSDT"] = frames["ETHUSDT"].iloc[:-1]            # a reference frame whose last bar is a different hour
    got = M.decision_rows(frames, SYMS + ["ZILUSDT"])
    for s in SYMS + ["ZILUSDT"]:
        assert got[s] == F.decision_row(s, frames), s           # exact dict equality, no tolerance
    assert got["ZILUSDT"] is None


def test_off_4h_rows_are_never_trading_bars():
    pytest.importorskip("lightgbm")
    models = _models()
    for b in (B4 + pd.Timedelta(minutes=15), B4 + M.HOUR):     # an offset bar; a 09:00 close (not a 4h close)
        rows = M.score_boundary(b, _prepared(b), models, strategy_cfgs={n: {} for n in models})
        assert rows and not any(r["trading_bar"] for r in rows)


@pytest.mark.parametrize("modname", ["ml_entry", "ml_entry_v2"])
def test_the_strategies_refuse_off_the_4h_close(modname):
    pytest.importorskip("lightgbm")
    import importlib
    mod = importlib.import_module(f"src.units.strategies.{modname}")
    b = B4 + M.HOUR
    prep = _prepared(b)
    frames = {s: sb.hourly for s, sb in prep.items()}
    with pytest.raises(ValueError, match="not_a_decision_bar"):
        mod.order_package({"symbol": "ETHUSDT"}, candles_df=frames["ETHUSDT"], reference_frames=frames)


def test_module_imports_nothing_that_can_trade():
    tree = ast.parse((REPO / "src/runtime/ml_decision_shadow.py").read_text())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    banned = ("accounts", "coordinator", "execute", "risk", "order", "intent", "pipeline", "exchange", "positions")
    bad = sorted(m for m in mods if any(b in m for b in banned))
    assert bad == [], bad


class _Resp:
    def __init__(self, js):
        self._js = js

    def json(self):
        return self._js


def _fake_get(store: dict, calls: list):
    def get(url, params=None, timeout=None):
        calls.append(dict(params))
        df = store.get(params["symbol"])
        if df is None:
            return _Resp({"retCode": 10001, "retMsg": "Not supported symbols", "result": {"list": []}})
        if "end" in params:
            df = df[df["ts"].dt.as_unit("ms").astype("int64") <= params["end"]]   # explicit ms: pandas 3 units vary
        df = df.tail(params["limit"]).iloc[::-1]
        rows = [[str(int(t.value // 10**6)), str(o), str(h), str(lo), str(c), str(v), "0"]
                for t, o, h, lo, c, v in df[["ts", "open", "high", "low", "close", "volume"]].itertuples(index=False)]
        return _Resp({"retCode": 0, "result": {"list": rows}})
    return get


def test_cache_cold_then_warm_and_never_keeps_the_forming_bar(tmp_path):
    b = B4
    full = _bars_15m(5, b + M.STEP, n=2100)                     # includes the FORMING bar opened at b
    calls: list = []
    st, df = M.refresh_cache("ETHUSDT", tmp_path, b, get=_fake_get({"ETHUSDT": full}, calls))
    assert st == "ok" and len(calls) == 2 and df["ts"].iloc[-1] == b - M.STEP and len(df) == M.KEEP_15M
    calls.clear()
    b2 = b + M.STEP
    full2 = _bars_15m(5, b2 + M.STEP, n=2101)
    st, df2 = M.refresh_cache("ETHUSDT", tmp_path, b2, get=_fake_get({"ETHUSDT": full2}, calls))
    assert st == "ok" and len(calls) == 1 and calls[0]["limit"] <= 10 and df2["ts"].iloc[-1] == b2 - M.STEP
    calls.clear()                                                # a skipped run: the newest page no longer connects
    b3 = b2 + 30 * M.STEP
    full3 = _bars_15m(5, b3 + M.STEP, n=2131)
    st, df3 = M.refresh_cache("ETHUSDT", tmp_path, b3, get=_fake_get({"ETHUSDT": full3}, calls))
    assert st == "ok" and df3["ts"].iloc[-1] == b3 - M.STEP
    assert (df3["ts"].diff().dropna() == M.STEP).all()           # no hole bridged
    st, _ = M.refresh_cache("BALUSDT", tmp_path, b, get=_fake_get({}, []))
    assert st == "not_listed"


def test_freshness_has_four_states(tmp_path):
    p = tmp_path / "x.jsonl"
    assert M.freshness(p)["state"] == "absent"
    p.write_text("not json\n")
    assert M.freshness(p)["state"] == "unreadable"
    now = pd.Timestamp("2026-11-01T12:00:00Z")
    p.write_text(json.dumps({"logged_at": (now - pd.Timedelta(minutes=10)).isoformat(), "bar_close": "x"}) + "\n")
    assert M.freshness(p, now_s=now.timestamp())["state"] == "fresh"
    assert M.freshness(p, now_s=(now + pd.Timedelta(hours=1)).timestamp())["state"] == "stale"


def test_run_once_end_to_end(tmp_path):
    pytest.importorskip("lightgbm")
    b = B4 + pd.Timedelta(minutes=30)
    store = {s: _bars_15m(20 + i, b + M.STEP, n=2100) for i, s in enumerate(SYMS)}
    models = _models()
    for m in models.values():                                    # this test's universe: SYMS + 2 unlisted
        m["meta"] = dict(m["meta"], xs_reference=SYMS + ["BALUSDT", "OMGUSDT"])
    out = M.run_once(now=b + pd.Timedelta(seconds=45), log_path=tmp_path / "log.jsonl", cache_dir=tmp_path / "c",
                     get=_fake_get(store, []), models=models)
    assert out["rows"] == len(SYMS) * 2 and out["symbols_not_listed"] == ["BALUSDT", "OMGUSDT"]
    assert out["tf_offset"] == "30m" and out["trading_rows"] == 0
    rows = [json.loads(x) for x in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert {r["read_state"] for r in rows} == {"ok"} and {r["strategy"] for r in rows} == {"ml_entry", "ml_entry_v2"}
    assert all(r["n_reference"] == len(SYMS) for r in rows)


def test_health_check_grades_each_state(tmp_path):
    from src.runtime.health import _DEFAULT_CHECKS, check_ml_decision_shadow
    assert check_ml_decision_shadow in _DEFAULT_CHECKS
    p = tmp_path / "s.jsonl"
    assert check_ml_decision_shadow(path=p).status == "warn"                      # absent
    p.write_text(json.dumps({"logged_at": pd.Timestamp.now(tz="UTC").isoformat(), "bar_close": "x"}) + "\n")
    assert check_ml_decision_shadow(path=p).status == "ok"                        # fresh
    p.write_text(json.dumps({"logged_at": "2020-01-01T00:00:00+00:00", "bar_close": "x"}) + "\n")
    r = check_ml_decision_shadow(path=p)
    assert r.status == "warn" and r.detail.startswith("STALE")
