"""Structure arm of the first-passage ML labeller (row STRUCTURE-EXITS-DEFAULT)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "research"))
import ml_structure_bracket as M  # noqa: E402
import ml_entry_levers as L       # noqa: E402


def _df(m=1500, seed=3):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.004, m)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + r.uniform(0, 0.004, m))
    lo = np.minimum(o, c) * (1 - r.uniform(0, 0.004, m))
    return pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=m, freq="h", tz="UTC"),
                         "open": o, "high": h, "low": lo, "close": c, "volume": 1.0})


def test_same_clock_and_columns_as_label_cell():
    df = _df()
    base, st = L.label_cell(df, 2.0, 3.0), M.label_cell_structure(df, 3)
    assert (base["i"].to_numpy() == st["i"].to_numpy()).all()
    for col in L.LABEL_COLS:
        assert col in st.columns
    assert np.isfinite(st["net_long"]).all() and st["risk_r_unit_long"].gt(0).all()


def test_stop_never_beyond_clamp_and_arm_differs():
    df = _df()
    base, st = L.label_cell(df, 2.0, 3.0), M.label_cell_structure(df, 3)
    assert not np.allclose(base["net_long"], st["net_long"])
    assert st["fallback_long"].mean() < 0.5


def test_long_only_option():
    st = M.label_cell_structure(_df(), 3, sides=("long",))
    assert "net_long" in st and "net_short" not in st


def test_no_lookahead_label_independent_of_far_future():
    df = _df()
    a = M.label_cell_structure(df, 3).set_index("i")
    df2 = df.copy()
    k = 1000
    for col in ("open", "high", "low", "close"):
        df2.loc[k + 40:, col] = df2.loc[k + 40:, col] * 3.0     # change the far future only
    b = M.label_cell_structure(df2, 3).set_index("i")
    common = [i for i in a.index if i + 30 < k + 40 and i in b.index]
    assert len(common) > 100
    assert np.allclose(a.loc[common, "net_long"], b.loc[common, "net_long"])


def test_t_map_identity_equals_default_and_daily_map_is_strictly_earlier_session():
    import ml_entry_alpaca_score as S
    from src.runtime.structure_levels import StructureLevels
    df = _df(800)
    h, lo = df.high.to_numpy(float), df.low.to_numpy(float)
    lv = StructureLevels(h, lo, 3)
    cand = np.arange(100, 400, 7)
    o, hh, ll, cc = (np.stack([df[k].to_numpy(float)[cand + 1 + j] for j in range(24)], 1) for k in ("open", "high", "low", "close"))
    a = np.full(len(cand), 1.0)
    base = M.structure_outcome(lv, o, hh, ll, cc, cand, o[:, 0], a, 1, sl_atr=2.0, tp_atr=3.0)
    ident = M.structure_outcome(lv, o, hh, ll, cc, cand, o[:, 0], a, 1, sl_atr=2.0, tp_atr=3.0, t_map=np.arange(len(df)))
    assert all(np.allclose(x, y, equal_nan=True) for x, y in zip(base, ident))
    d = _df(24 * 40)
    d["ts"] = d.ts + pd.Timedelta(hours=14)
    lv_d, datr, tmap = S.daily_structure(d, 3)
    sess = pd.factorize(d.ts.dt.tz_convert("America/New_York").dt.date)[0]
    assert (tmap == sess - 1).all() and tmap[0] == -1      # never the session still forming
    assert len(datr) == sess.max() + 1
