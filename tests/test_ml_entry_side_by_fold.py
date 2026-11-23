"""by-side-by-fold report (ML-D3-UNLOCK-20261123): arithmetic, fold bookkeeping, and that existing defaults are untouched."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_decision_entry as E  # noqa: E402


def _tk(sides, rs, days):
    ts = pd.to_datetime(days, utc=True)
    return pd.DataFrame({"symbol": "A", "ts": ts, "side": sides, "net_r": rs, "gross_r": np.array(rs) + 0.1, "cost_r": 0.1})


def test_side_stats_arithmetic_and_cost_stack():
    s = E.split_by_side(_tk(["long", "long", "short"], [-1.0, 0.0, 2.0], ["2025-01-01", "2025-01-02", "2025-01-09"]))
    assert s["long"]["n"] == 2 and s["short"]["n"] == 1 and s["all"]["n"] == 3
    assert abs(s["long"]["mean_net_r"] + 0.5) < 1e-12 and abs(s["long"]["se_net_r"] - 0.5) < 1e-12
    assert abs(s["long"]["mean_gross_r"] - (-0.4)) < 1e-12 and abs(s["long"]["mean_cost_r"] - 0.1) < 1e-12
    assert s["short"]["se_net_r"] is None                      # one observation: no se, never 0


def test_empty_side_is_null_not_zero():
    s = E.side_stats(_tk([], [], []))
    assert s["n"] == 0 and s["mean_net_r"] is None and s["se_net_r"] is None


def test_clustered_se_exceeds_iid_when_a_week_is_one_shock():
    days = ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-13", "2025-01-14", "2025-01-15"]
    s = E.side_stats(_tk(["long"] * 6, [-1, -1, -1, 1, 1, 1], days))
    assert s["se_week_clustered"] > s["se_net_r"]


def test_persistence_counts_only_folds_with_both_sides():
    f = lambda l, s: {"refit": {"long": {"n": 5 if l is not None else 0, "mean_net_r": l}, "short": {"n": 5 if s is not None else 0, "mean_net_r": s}}}
    p = E.persistence([f(-0.5, 0.5), f(-0.1, 0.3), f(0.2, None)])
    assert p["n_folds_with_both_sides"] == 2 and p["folds_long_negative"] == 2 and p["folds_short_positive"] == 2
    assert abs(p["mean_gap_short_minus_long"] - 0.7) < 1e-12


def _table():
    rng = np.random.default_rng(0)
    ts = pd.date_range("2021-06-01", "2022-04-01", freq="4h", tz="UTC")
    rows = []
    for sym in ("A", "B"):
        n = len(ts)
        rows.append(pd.DataFrame({"symbol": sym, "ts": ts, "i": np.arange(n) * 4, "net_long": rng.normal(-0.1, 1, n),
                                  "net_short": rng.normal(0.1, 1, n), "gross_long": 0.0, "gross_short": 0.0, "cost_long": 0.1,
                                  "cost_short": 0.1, "reason_long": 0, "reason_short": 0, "bars_long": 6, "bars_short": 6}))
    return pd.concat(rows, ignore_index=True)


def test_folds_are_labelled_and_frozen_in_sample_flag(monkeypatch):
    tab = _table()
    monkeypatch.setattr(E, "fit_predict", lambda tr, te, f=None, n=None: (np.full(len(te), 1.0), np.full(len(te), 0.5)))

    class B:                      # frozen booster stub: always predicts the short side higher
        def __init__(self, v): self.v = v
        def predict(self, x): return np.full(len(x), self.v)
    frozen = {"m": ({"features": ["ret_1"], "train_end_exclusive": "2021-12-01"}, {"long": B(0.0), "short": B(1.0)})}
    tab["ret_1"] = 0.0
    res = E.by_side_by_fold(tab, 0.1, frozen, dev_folds=["2021-10-01", "2022-01-01"], dev_end="2022-03-01")
    assert [f["test_start"] for f in res["folds"]] == ["2021-10-01", "2022-01-01"]
    assert res["folds"][0]["frozen"]["m"]["in_sample"] is True and res["folds"][1]["frozen"]["m"]["in_sample"] is False
    assert res["folds"][0]["refit"]["long"]["n"] > 0 and res["folds"][0]["refit"]["short"]["n"] == 0   # stub prefers long
    assert res["folds"][0]["frozen"]["m"]["short"]["n"] > 0 and res["folds"][0]["frozen"]["m"]["long"]["n"] == 0
    assert "| fold |" in E.side_fold_table(res)


def test_existing_defaults_untouched():
    assert E.HOLDOUT_START == "2025-10-01" and E.TAU_GRID == [0.0, 0.05, 0.10, 0.15, 0.20, 0.30] and E.DEV_FOLDS[0] == "2022-01-01"
    import inspect
    assert list(inspect.signature(E.walk_forward).parameters) == ["tab", "features", "dev_folds", "dev_end", "n_jobs"]
    assert list(inspect.signature(E.holdout).parameters) == ["tab", "tau", "features", "start", "end", "n_jobs"]


def test_arm_diff_and_gate_verdict_rule():
    days = pd.date_range("2025-01-01", periods=400, freq="D", tz="UTC")
    a = pd.DataFrame({"ts": days, "net_r": np.full(400, 0.2)})
    b = pd.DataFrame({"ts": days, "net_r": np.full(400, 0.0)})
    d = E.arm_diff(a, b)
    assert abs(d["delta"] - 0.2) < 1e-12 and d["se_week_clustered"] == 0.0        # no variance -> se 0, t None
    d2 = {"n_a": 5000, "n_b": 9000, "delta": 0.07, "se_week_clustered": 0.02, "t": 3.5}
    assert E.gate_verdict(d2)[0] == "pass"
    assert E.gate_verdict({**d2, "delta": 0.0})[0] == "fail"                        # 0.0 + 2*0.02 < 0.05
    assert E.gate_verdict({**d2, "delta": 0.04, "t": 2.0, "se_week_clustered": 0.02})[0] == "indeterminate"
    assert E.gate_verdict({**d2, "n_a": 100})[0] == "indeterminate"


def test_gated_arm_never_takes_a_masked_side(monkeypatch):
    tab = _table().assign(ret_1=0.0, ret_168=1.0)                    # uptrend everywhere: trend gate allows long only
    monkeypatch.setattr(E, "fit_predict", lambda tr, te, f=None, n=None: (np.full(len(te), 0.2), np.full(len(te), 0.9)))
    res = E.by_side_by_fold(tab, 0.1, {}, dev_folds=["2021-10-01"], dev_end="2022-03-01", gates=["trend", "short_only"])
    f = res["folds"][0]
    assert f["refit"]["short"]["n"] > 0 and f["refit"]["long"]["n"] == 0                    # ungated: model prefers short
    assert f["gated"]["trend"]["short"]["n"] == 0 and f["gated"]["trend"]["long"]["n"] > 0   # gated: short masked, long falls through
    assert f["gated"]["short_only"]["long"]["n"] == 0
    assert set(res["gate_vs_both_dev"]) == {"trend", "short_only"}
