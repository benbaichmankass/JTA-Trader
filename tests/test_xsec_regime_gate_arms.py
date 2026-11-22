import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts"), str(REPO / "scripts" / "research")]
import xsec_regime_gate_arms as X  # noqa: E402


def _inputs(n=1500):
    rng = np.random.default_rng(2)
    idx = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")
    cols = {f"S{i}": 100 * np.exp(np.cumsum(rng.normal(0.001 * (i - 2), 0.03, n))) for i in range(6)}
    panel = pd.DataFrame(cols, index=idx)
    funds = {c: pd.Series(0.0001, index=idx) for c in panel.columns}
    cov = {c: {"close_rows": n} for c in panel.columns}
    btc = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.03, n + 400))),
                    index=pd.date_range(idx[0] - pd.Timedelta(days=400), periods=n + 400, freq="D", tz="UTC"))
    return {"panel": panel, "funding": funds, "coverage": cov, "empty": [], "start": idx[0], "end": idx[-1]}, btc


def _args(**kw):
    d = dict(symbols="S0", days=1460, sma_days="50,100", vol_windows="30", vol_q=0.7, draws=15, delta_min=0.25, alpha=0.05,
             min_years=3, n_floor=10, rebalance_days=7, formation_days=28, fee_multiplier=1.0)
    d.update(kw)
    return argparse.Namespace(**d)


def test_self_test():
    X._selftest()


def test_run_counts_every_arm_and_reports_denominator():
    inp, btc = _inputs()
    v = X.run(_args(), inputs=inp, btc=btc)
    assert v["read_state"] == "measured" and v["verdict"] in ("pass", "fail", "indeterminate")
    m = v["measurement"]
    assert m["arm_denominator"] == 3 == len(m["arms"])            # SMA50, SMA100, VOL30_P70
    assert all(0 < a["control_p"] <= 1 for a in m["arms"])
    assert m["baseline"]["n_trades"] > 0 and "per_year" in m["baseline"]


def test_missing_btc_is_no_data_not_a_verdict():
    inp, _ = _inputs()
    v = X.run(_args(), inputs=inp, btc=pd.Series(dtype=float))
    assert v["read_state"] == "no_data" and v["verdict"] == "not_applicable" and v["n"] is None
