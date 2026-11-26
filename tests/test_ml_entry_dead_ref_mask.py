"""Row ML-ENTRY-DEAD-REF-FLAT-BARS: a delisted perp's flat zero-volume bars (Binance Vision keeps publishing them) must not
count in ml_entry's cross-sectional features when build_table(mask_dead=True); the default build is unchanged."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import ml_decision_entry as E  # noqa: E402


def _frame(seed, n=900, dead_from=None):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    c = 100 * np.exp(np.cumsum(0.01 * rng.standard_normal(n)))
    o = np.r_[100.0, c[:-1]]
    df = pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998,
                       "close": c, "volume": 1000.0 + rng.random(n)})
    if dead_from is not None:   # delisted: flat at the last price, zero volume (the Binance Vision shape)
        last = df.loc[dead_from - 1, "close"]
        df.loc[dead_from:, ["open", "high", "low", "close"]] = last
        df.loc[dead_from:, "volume"] = 0.0
    return df


def _cache(tmp_path):
    frames = {"BTCUSDT": _frame(1), "ETHUSDT": _frame(2), "SOLUSDT": _frame(3), "DEADUSDT": _frame(4, dead_from=400)}
    for s, f in frames.items():
        f.to_pickle(tmp_path / f"{s}.pkl")
    return list(frames)


def test_mask_dead_bars_counts_and_nans():
    df, n = E.mask_dead_bars(_frame(4, dead_from=400))
    assert n == 500 and df["close"].iloc[400:].isna().all() and df["close"].iloc[:400].notna().all()
    df2, n2 = E.mask_dead_bars(_frame(1))
    assert n2 == 0


def test_dead_member_leaves_the_cross_section_only_when_masked(tmp_path):
    syms = _cache(tmp_path)
    live_only = [s for s in syms if s != "DEADUSDT"]
    base = E.build_table(tmp_path, syms)                    # default: the flat member counts (legacy)
    masked = E.build_table(tmp_path, syms, mask_dead=True)
    ref = E.build_table(tmp_path, live_only)                # what live computes: the dead symbol simply absent
    assert masked.attrs["dead_bars_masked"] == {"DEADUSDT": 500}
    late = pd.Timestamp("2025-01-25", tz="UTC")             # bar ~576: well after the delisting (bar 400), past the warm-ups
    key = ["ts", "symbol"]
    m = masked[(masked.ts > late) & (masked.symbol == "BTCUSDT")].set_index(key)
    r = ref[(ref.ts > late) & (ref.symbol == "BTCUSDT")].set_index(key)
    b = base[(base.ts > late) & (base.symbol == "BTCUSDT")].set_index(key)
    j = m.join(r, rsuffix="_ref", how="inner").join(b, rsuffix="_base", how="inner")
    assert len(j) > 20
    for col in ("breadth_up24", "rel_vol", "xs_rank_ret24"):
        assert np.allclose(j[col], j[f"{col}_ref"], equal_nan=True), col          # masked == live definition
    assert not np.allclose(j["breadth_up24"], j["breadth_up24_base"])               # legacy differs (the skew)
