"""ml_entry MOVING TP (row ML-ENTRY-TP-REVISION, unit RQ-20261101-383f-01): the serving policy == the research harness.

Pins src/runtime/ml_entry_tp_policy.py + the ml_first_passage rule in src/units/strategies/ml_entry.py to their twins in
scripts/research/ml_entry_tp_revision.py (the harness that produced the evidence): the same inputs give the same
check-in features, the same expected net R per level, the same valid set and the same TP move; and the monitor path
emits the TP-doctrine verdict ``{"tp", "tp_reason"}`` only at a check-in, never over a close, never off-grid.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.runtime import ml_decision_features as F
from src.runtime import ml_entry_tp_policy as P
from src.runtime.tp_venue_cap import TP_VENUE_CAP_PCT
from src.units.strategies import ml_entry as M

REPO = Path(__file__).resolve().parents[1]


def _harness():
    sys.path.insert(0, str(REPO / "scripts" / "research"))
    spec = importlib.util.spec_from_file_location("ml_entry_tp_revision",
                                                  REPO / "scripts/research/ml_entry_tp_revision.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _harness()
META = {"model_id": "test", "features": H.TP_FEATURES, "classes": list(range(H.N_CLASS)), "grid_atr": H.GRID,
        "base_tp_atr": H.BASE_TP, "checkins_bars_held": H.CHECKINS, "min_gap_atr": H.MIN_GAP_ATR, "margin_r": 0.05,
        "sl_atr": 2.0, "horizon_h": 24, "fee_bps": 11.0}


def _frame(seed: int, n: int, end: pd.Timestamp) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(end=end, periods=n, freq="1h")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.005, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.005, n))
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": rng.uniform(1e3, 1e4, n)})


def test_constants_match_harness():
    assert H.VENUE_CAP_PCT == TP_VENUE_CAP_PCT
    assert M.TP_RULE == "ml_first_passage"


@pytest.mark.parametrize("seed", range(20))
def test_expected_net_r_valid_levels_and_cost_match_harness(seed):
    rng = np.random.default_rng(seed)
    p = rng.dirichlet(np.ones(H.N_CLASS))
    means = rng.normal(0, 0.8, H.N_CLASS)
    side = int(rng.choice([1, -1]))
    entry, atr = 100.0, float(rng.uniform(0.3, 2.0))
    close = entry + side * float(rng.uniform(-3, 8)) * atr
    cost_h = H.level_cost(entry, atr, side)
    from src.runtime.execution_costs import resolve_cost_policy
    slip, fund = resolve_cost_policy("BTCUSDT")
    cost_p = P.level_cost(entry, atr, side, H.GRID, 2.0, 11.0, slip, fund)
    np.testing.assert_allclose(cost_p, cost_h, rtol=0, atol=1e-15)
    np.testing.assert_allclose(P.expected_net_r(p, means, cost_p, H.GRID, 2.0), H.expected_net_r(p, means, cost_h),
                               rtol=0, atol=1e-12)
    np.testing.assert_array_equal(P.valid_levels(side, entry, atr, close, H.GRID, H.MIN_GAP_ATR, TP_VENUE_CAP_PCT),
                                  H.valid_levels(side, entry, atr, close))


@pytest.mark.parametrize("seed", range(30))
def test_choose_matches_harness_policy_step(seed):
    """The harness policy's chooser and the serving choose() pick the same level for the same probabilities."""
    rng = np.random.default_rng(100 + seed)
    p = rng.dirichlet(np.ones(H.N_CLASS) * 0.5)
    means = rng.normal(0, 0.8, H.N_CLASS)
    side = int(rng.choice([1, -1]))
    entry, atr = 100.0, 1.0
    close = entry + side * float(rng.uniform(-1.5, 4.0))
    q = int(rng.integers(0, len(H.GRID)))
    cost = H.level_cost(entry, atr, side)
    ok = H.valid_levels(side, entry, atr, close)
    ev = H.expected_net_r(p, means, cost)
    cand = np.where(ok, ev, -np.inf)
    best = int(np.argmax(cand))
    want = best if (np.isfinite(cand[best]) and best != q and cand[best] - ev[q] > 0.05) else None
    got = P.choose(p, means, side=side, entry=entry, atr=atr, close=close, resting_idx=q, grid=H.GRID, sl_atr=2.0,
                   min_gap_atr=H.MIN_GAP_ATR, cap_pct=TP_VENUE_CAP_PCT, margin=0.05, cost=cost)["move_to"]
    assert got == want


@pytest.mark.parametrize("jc,side", [(4, 1), (8, -1), (12, 1), (20, -1)])
def test_checkin_features_match_harness(jc, side):
    """Same bars in -> the 29 TP-model inputs at a check-in are identical (live frames end AT the check-in bar; the
    harness frame carries the 24 forward bars its label needs, which no feature reads)."""
    check = pd.Timestamp("2026-01-10 19:00", tz="UTC")             # bar OPEN; closes at 20:00 (a 4h boundary)
    full_end = check + pd.Timedelta(hours=24)
    syms = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
    sym = "ETHUSDT"
    for seed in range(7, 60):                                      # first synthetic path whose stop survives to jc
        full = {s: _frame(seed * 10 + k, 480, full_end) for k, s in enumerate(syms)}
        df = full[sym]
        ic = int((df["ts"] == check).to_numpy().nonzero()[0][0])
        i = ic - jc
        panel = H.feature_panel(full)
        atr_d = float(panel[sym]["atr"].iloc[i])
        hr = H.checkin_rows(sym, df, panel[sym], np.array([i]), np.array([atr_d]), np.array([side]), False)
        hr = hr[hr.bars_held == jc] if len(hr) else hr
        if len(hr) == 1:
            break
    assert len(hr) == 1
    assert int((df["ts"].iloc[i] + pd.Timedelta(hours=1)).hour) % 4 == 0
    live = {s: f[f["ts"] <= check].reset_index(drop=True) for s, f in full.items()}
    own = live[sym]
    row = F.decision_row(sym, live)
    row.pop("_n_reference")
    entry = float(df["open"].iloc[i + 1])                          # harness entry = next bar open
    win = own.iloc[i + 1:]
    st = P.state_features(side=side, entry=entry, atr_entry=atr_d, sl=entry - side * 2.0 * atr_d, highs=win["high"],
                          lows=win["low"], close_now=float(own["close"].iloc[-1]), atr_now=F.atr_last(own),
                          ret_4=row["ret_4"], ret_24=row["ret_24"], bars_held=jc, sl_atr=2.0)
    got = {**row, **st}
    for k in H.TP_FEATURES:
        assert got[k] == pytest.approx(float(hr[k].iloc[0]), rel=1e-9, abs=1e-12), k


class _StubBooster:
    def __init__(self, p):
        self.p = np.asarray(p, float)

    def predict(self, x):
        return np.tile(self.p, (len(x), 1))


def _pkg(df: pd.DataFrame, i: int, side: int, tp_atr: float = 3.0, declared: bool = True):
    entry = float(df["close"].iloc[i])
    atr = F.atr_last(df.iloc[:i + 1])
    meta = {"decision_bar": df["ts"].iloc[i].isoformat(), "atr14": atr, "max_hold_min": 1440,
            "entry_time": df["ts"].iloc[i + 1].isoformat()}
    if declared:
        meta["tp_revision"] = {"rule": M.TP_RULE}
    return {"order_package_id": "p1", "symbol": "ETHUSDT", "direction": "long" if side > 0 else "short",
            "entry": entry, "sl": entry - side * 2 * atr, "tp": entry + side * tp_atr * atr, "meta": meta}, entry, atr


def _setup(jc: int, p_class: int):
    check = pd.Timestamp("2026-01-10 19:00", tz="UTC")
    syms = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
    frames = {s: _frame(k + 31, 450, check) for k, s in enumerate(syms)}
    own = frames["ETHUSDT"]
    i = len(own) - 1 - jc
    p = np.zeros(H.N_CLASS)
    p[p_class] = 1.0
    means = np.full(H.N_CLASS, -0.2)
    model = {"meta": {**META, "class_mean_net_r": list(means)}, "booster": _StubBooster(p)}
    return frames, own, i, model


def _now_candles(own):
    """What the order monitor hands monitor(): closed bars + one forming bar."""
    nxt = own["ts"].iloc[-1] + pd.Timedelta(hours=1)
    forming = own.iloc[[-1]].assign(ts=nxt)
    return pd.concat([own, forming], ignore_index=True)


def test_monitor_emits_tp_verdict_at_checkin(monkeypatch):
    frames, own, i, model = _setup(8, p_class=8)                    # all mass: every level reached, no stop
    pkg, entry, atr = _pkg(own, i, 1)
    monkeypatch.setattr(M, "_frame", lambda df: df[df["ts"] <= own["ts"].iloc[-1]].reset_index(drop=True))
    rev = M.tp_revision({"min_reference_symbols": 2}, _now_candles(own), pkg,
                        frames_fn=lambda s, b, xs: (own, frames), tp_model=model)
    assert rev is not None
    close = float(own["close"].iloc[-1])
    ok = H.valid_levels(1, entry, atr, close)
    want = max(q for q in range(len(H.GRID)) if ok[q])              # reach-all -> the highest valid level wins
    assert rev.tp == pytest.approx(round(entry + H.GRID[want] * atr, 8))
    assert rev.rule == M.TP_RULE and rev.detail["kind"] == "extend"
    from src.runtime.tp_revision import as_verdict
    v = as_verdict(rev)
    assert set(v) == {"tp", "tp_reason"} and v["tp_reason"].startswith(M.TP_RULE)


def test_no_revision_off_checkin_undeclared_offgrid_or_hold(monkeypatch):
    frames, own, i, model = _setup(8, p_class=8)
    monkeypatch.setattr(M, "_frame", lambda df: df[df["ts"] <= own["ts"].iloc[-1]].reset_index(drop=True))
    ff = lambda s, b, xs: (own, frames)  # noqa: E731
    pkg, _, _ = _pkg(own, i, 1, declared=False)
    assert M.tp_revision({"min_reference_symbols": 2}, own, pkg, frames_fn=ff, tp_model=model) is None
    pkg, _, _ = _pkg(own, i + 1, 1)                                  # 7 bars held: not a check-in
    assert M.tp_revision({"min_reference_symbols": 2}, own, pkg, frames_fn=ff, tp_model=model) is None
    pkg, _, _ = _pkg(own, i, 1, tp_atr=3.3)                          # resting TP off the grid: someone else set it
    assert M.tp_revision({"min_reference_symbols": 2}, own, pkg, frames_fn=ff, tp_model=model) is None
    _, _, _, stop_model = _setup(8, p_class=H.N_CLASS // 2)          # all mass: no level reached, stop hit
    pkg, _, _ = _pkg(own, i, 1, tp_atr=1.0)
    # every level is equally worthless (P(reach)=0): no level beats the resting one by the margin -> keep
    assert M.tp_revision({"min_reference_symbols": 2}, own, pkg, frames_fn=ff, tp_model=stop_model) is None


def test_close_verdict_wins_over_a_revision(monkeypatch):
    monkeypatch.setattr(M, "tp_revision", lambda *a, **k: (_ for _ in ()).throw(AssertionError("not reached")))
    old = "2020-01-01T00:00:00+00:00"
    v = M.monitor({}, None, {"meta": {"max_hold_min": 1440, "entry_time": old, "tp_revision": {"rule": M.TP_RULE}}})
    assert v["action"] == "close"


def test_leg_declares_the_rule_and_the_package_threads_it():
    import yaml
    cfg = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]["ml_entry"]
    from src.runtime.tp_revision import RULES, declared_rule
    assert declared_rule(cfg) == M.TP_RULE and M.TP_RULE in RULES
    import src.units.strategies.ml_entry as mod
    src = Path(mod.__file__).read_text()
    assert '{"tp_revision": cfg["tp_revision"]} if declared_rule(cfg) == TP_RULE' in src


def test_served_artifact_matches_the_evidence_record():
    art = P.ARTIFACT
    if not art.exists():
        pytest.skip("artifact not built in this checkout")
    m = P.load_tp_model(art)["meta"]
    assert m["features"] == H.TP_FEATURES and m["grid_atr"] == H.GRID and m["checkins_bars_held"] == H.CHECKINS
    assert m["margin_r"] == 0.05 and m["unit"] == "RQ-20261101-383f-01"
