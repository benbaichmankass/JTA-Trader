"""ml_entry fix arms (RQ-20261124-f1a0-01..05) and the lever-arms verdict.json harness contract (PI-20261124-RQFAILS-0001)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))


def test_fix_arms_self_test():
    import ml_entry_fix_arms as F
    F._self_test()


def test_lever_arms_writes_the_harness_verdict_json():
    """script_run.derive_record reads exactly <out>/verdict.json; lever-arms used to write only verdict_<arm>.json, which landed a
    measured run as producer_failed (RQ-20261124-e1a7-02 run 45455675005)."""
    src = (REPO / "scripts/research/ml_decision_entry.py").read_text()
    body = src[src.index("def lever_arms_cmd"):src.index("def _self_test_lever_arms")]
    assert '(out / "verdict.json").write_text' in body


def test_fix_arms_writes_the_harness_verdict_json():
    src = (REPO / "scripts/research/ml_entry_fix_arms.py").read_text()
    assert '(out / "verdict.json").write_text' in src


def test_run_arm_never_rebinds_its_per_run_inputs_inside_the_fold_loop():
    """f1a0-14 (run 45532031095) died at fold 2: `alt, alt2 = alt` inside the fold loop turned the per-run (fixed, vol) pair into a DataFrame on
    fold 1, so fold 2's unpack raised. No assignment inside run_arm's loops may target `alt` or `tab`."""
    import ast
    src = (Path(__file__).resolve().parents[1] / "scripts/research/ml_entry_fix_arms.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run_arm")
    bad = []
    for loop in (n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))):
        for n in ast.walk(loop):
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                for tgt in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    bad += [n.lineno for nm in ast.walk(tgt) if isinstance(nm, ast.Name) and nm.id in ("alt", "tab")]
    assert bad == [], f"run_arm rebinds alt/tab inside a fold loop at lines {bad}"


def test_clf_target_breakeven_and_edge_scores():
    """clf_target: p* = mean|loss| / (mean win + mean|loss|) from TRAINING labels only, the score is P(net>0) - p*, and a side whose
    signal is pure noise scores near -p* + base rate (so the policy rarely trades it)."""
    import ml_decision_entry as M
    import ml_entry_fix_arms as F
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(0)
    n = 4000
    X = pd.DataFrame(rng.normal(size=(n, len(M.FEATURES))), columns=M.FEATURES)
    sig = X[M.FEATURES[0]].to_numpy()
    long_ = np.where(sig + rng.normal(0, 0.5, n) > 0, 1.5, -1.0)          # long label learnable from feature 0
    short_ = np.where(rng.random(n) < 0.3, 1.5, -1.0)                       # short label pure noise, 30% win
    df = X.assign(net_long=long_, net_short=short_)
    tr, te = df.iloc[:3000], df.iloc[3000:]
    cl, cs, info = F.clf_predict(tr, te, n_jobs=1)
    assert abs(info["long"]["p_star"] - 1.0 / 2.5) < 1e-6 and abs(info["short"]["p_star"] - 1.0 / 2.5) < 1e-6
    assert cl.shape == cs.shape == (len(te),)
    hi = te[M.FEATURES[0]].to_numpy() > 0.5
    assert cl[hi].mean() > 0.2 and cl[~hi].mean() < cl[hi].mean()       # the learnable side clears p* where the feature says so
    assert info["short"]["test_share_above_p_star"] < 0.2                  # the noise side (30% win < p* 40%) rarely clears
    assert "clf_target" in F.ARMS



def test_h8_retrain_relabels_on_the_registered_bracket_with_an_8h_time_stop(tmp_path):
    """h8_retrain (the registered fail_action of f1a0-31/33): the SAME 2/3 ATR bracket with an 8-bar label/time-stop horizon. No 8 h label
    holds longer than 8 bars, while the registered 24-bar labels on the same rows do."""
    import ml_decision_entry as M
    import ml_entry_fix_arms as F
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(1)
    n = 24 * 60
    ts = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999, "close": c,
                  "volume": 1.0}).to_pickle(tmp_path / "BTCUSDT.pkl")
    dec = ts[((ts + pd.Timedelta(hours=1)).hour % M.DECISION_EVERY_H == 0)][20:-30]
    tab = pd.DataFrame({"symbol": "BTCUSDT", "ts": dec})
    lab8 = F.alt_labels(tmp_path, ["BTCUSDT"], tab, M.SL_ATR, M.TP_ATR, horizon=F.H8)
    lab24 = F.alt_labels(tmp_path, ["BTCUSDT"], tab, M.SL_ATR, M.TP_ATR, horizon=None)
    assert F.H8 == 8 and "h8_retrain" in F.ARMS
    assert lab8["net_long"].notna().all() and len(lab8) == len(tab)
    assert lab8[["bars_long", "bars_short"]].max().max() <= 8
    assert lab24[["bars_long", "bars_short"]].max().max() > 8


def test_score_band_cap_threshold_and_control_remove_the_same_count():
    """CAP arms (lever `score_band_cap`): the cap is fitted on TRAIN predictions only, abstains above it, and the random control
    removes exactly as many above-tau rows, so the arm is graded against blind removal of the same size."""
    import numpy as np
    import ml_decision_entry as M
    rng = np.random.default_rng(0)
    train_best = rng.normal(0.15, 0.1, 5000)
    cap = M.cap_threshold(train_best, 0.10, 0.90)
    above = train_best[train_best > 0.10]
    assert abs(cap - np.quantile(above, 0.90)) < 1e-12
    assert M.cap_threshold(np.full(10, 0.5), 0.10, 0.9) is None            # < 50 above tau -> no cap, arm == base
    pl, ps = rng.normal(0.12, 0.1, 2000), rng.normal(0.12, 0.1, 2000)
    cl, cs = M.capped(pl, ps, cap)
    removed = np.isinf(cl) & np.isinf(cs)
    assert removed.sum() == int((np.maximum(pl, ps) > cap).sum()) and removed.sum() > 0
    assert not np.isinf(cl[~removed]).any()                                 # every other row untouched
    rl, rs = M.random_capped(pl, ps, 0.10, cap, np.random.default_rng(1))
    r_removed = np.isinf(rl) & np.isinf(rs)
    assert r_removed.sum() == removed.sum()                                 # same count
    assert (np.maximum(pl, ps)[r_removed] > 0.10).all()                     # drawn only from above-tau rows
    assert M.capped(pl, ps, None)[0] is pl and M.random_capped(pl, ps, 0.1, None, np.random.default_rng(1))[0] is pl


def test_cap_arms_are_on_the_cli_and_paired_with_their_random_control():
    src = (REPO / "scripts/research/ml_decision_entry.py").read_text()
    assert "*ARM_SPECS, *CAP_ARMS" in src
    assert 'pairs[arm] = {"vs_base": "base", "vs_random": f"random_{arm}"}' in src


def test_cap_arms_count_toward_the_sidak_family_bar():
    """Three cap arms in one unit must be graded at the k=3 family bar (t >= 2.3909), not the single-arm 2.0."""
    src = (REPO / "scripts/research/ml_decision_entry.py").read_text()
    assert "k_new = sum(1 for x in arms if x in ARM_SPECS or x in CAP_ARMS" in src


def test_calibration_maps_fit_on_the_slice_and_the_control_keeps_the_values():
    """CAL arms (lever `calibration`): iso is monotone, bin10 returns per-decile means (may be non-monotone), and the control
    bin10_perm uses the SAME decile means permuted (the remap's size without its information)."""
    import numpy as np
    import ml_decision_entry as M
    rng = np.random.default_rng(0)
    pred = rng.normal(0, 1, 4000)
    real = np.where(pred > 1.3, -1.0, pred)                    # a losing top band: what the declared hypothesis describes
    iso = M.calib_map(pred, real, "iso")
    xs = np.linspace(-3, 3, 50)
    assert (np.diff(iso(xs)) >= -1e-12).all()                  # monotone non-decreasing
    b10 = M.calib_map(pred, real, "bin10")
    assert b10(np.array([3.0]))[0] < b10(np.array([1.0]))[0]   # non-monotone: the top decile maps below the one under it
    perm = M.calib_map(pred, real, "bin10_perm", np.random.default_rng(3))
    grid = np.quantile(pred, np.linspace(0.05, 0.95, 10))
    assert sorted(np.round(b10(grid), 10)) == sorted(np.round(perm(grid), 10))   # same values, different order


def test_cal_arms_on_cli_paired_and_counted_in_the_family_bar():
    src = (REPO / "scripts/research/ml_decision_entry.py").read_text()
    assert "*CAP_ARMS, *CAL_ARMS]" in src
    assert 'pairs["cal_bin10"] = {"vs_base": "base", "vs_random": "random_cal_bin10"}' in src
    assert "or x in CAL_ARMS)" in src


def test_exit_head_threshold_arms_change_only_tau():
    """THRESHOLD arms (lever `threshold` on ml-exit-head-donchian-1h): champion target and features, tau replaced."""
    import exit_head_label_bakeoff as L
    assert L.arm_shape("holding_pays") == L.SHAPE
    for arm, tau in L.THRESHOLD_ARMS.items():
        s = L.arm_shape(arm)
        assert s["tau"] == tau and {k: v for k, v in s.items() if k != "tau"} == {k: v for k, v in L.SHAPE.items() if k != "tau"}
        rows = [{"holding_pays": 1}, {"holding_pays": 0}]
        assert L.with_target(rows, arm) is rows                     # the champion's target, unchanged


def test_weekly_series_matrix():
    """--emit-series: per-config per-ISO-week net R sums; control draws excluded; empty week zero-filled."""
    import pandas as pd

    import ml_entry_fix_arms as A
    cat = {
        "base": pd.DataFrame({"ts": pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-20"], utc=True), "net_r": [1.0, -0.5, 2.0]}),
        "arm": pd.DataFrame({"ts": pd.to_datetime(["2025-01-06"], utc=True), "net_r": [0.25]}),
        "control": pd.DataFrame({"ts": pd.to_datetime(["2025-01-06"], utc=True), "net_r": [9.0]}),
    }
    s = A.weekly_series(cat)
    assert s["configs"] == ["arm", "base"]
    assert s["weeks"] == ["2025-W02", "2025-W04"]
    assert s["matrix"]["base"] == [0.5, 2.0]
    assert s["matrix"]["arm"] == [0.25, 0.0]
    assert s["n_trades"] == {"arm": 1, "base": 3}


def _meta_frames(n=4000, seed=7):
    import numpy as np
    import pandas as pd

    import ml_decision_entry as M
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({f: rng.normal(size=n) for f in M.FEATURES})
    df["ts"] = pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC")
    # planted: the rule side's net R is positive iff the first feature is high (a learnable take/skip signal)
    edge = np.where(df[M.FEATURES[0]] > 0, 0.5, -0.5) + rng.normal(scale=0.5, size=n)
    df["net_long"], df["net_short"] = edge, edge
    return df.iloc[: n // 2].reset_index(drop=True), df.iloc[n // 2:].reset_index(drop=True)


def test_meta_take_proba_learns_a_planted_take_signal_linear_and_gbdt():
    """ML-ENTRY-REDESIGN R1: the model decides take/skip on the RULE side; a planted signal must be found by both families."""
    import ml_decision_entry as M
    import ml_entry_fix_arms as A
    tr, te = _meta_frames()
    want = te[M.FEATURES[0]].to_numpy() > 0
    for linear in (True, False):
        p = A.meta_take_proba(tr, te, linear=linear)
        assert p.shape == (len(te),) and ((p > A.META_P) == want).mean() > 0.8, linear
    assert {"meta_rule_linear", "meta_rule_gbdt"} <= set(A.ARMS)
    assert A.META_RULE["min_delta_r"] == 0.010 and A.META_RULE["min_t"] == 2.24
