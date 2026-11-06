"""ML-ENTRY-EQUITY-NATIVE serve parity (spec docs/research/ml-entry-eq-serve-spec-2026-11-06.md): the serving features equal the research harness
features for the same bars; a stale / incomplete / missing pool snapshot is a NAMED refusal; the exit-evaluation path never touches the pool code."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_entry_equity as Q  # noqa: E402

from src.runtime import ml_entry_eq_features as F  # noqa: E402


def _golden():
    bars = Q._synthetic_bars(n_days=420)
    pool = [f"E{i}" for i in range(8)]
    tab = Q.build_table(bars, pool, 5.0, 0.0).dropna(subset=Q.OWN + Q.XS)
    cnt = tab.groupby("ts").symbol.nunique()
    ts = cnt[cnt == len(pool)].index[-40]               # a decision close with all 8 symbols, well after warm-up
    return bars, pool, tab, pd.Timestamp(ts)


def test_serving_features_equal_the_research_harness_features():
    bars, pool, tab, T = _golden()
    trunc = {s: bars[s][pd.to_datetime(bars[s].close_ts, utc=True) <= T][["ts", "open", "high", "low", "close", "volume"]] for s in pool}
    snap = F.build_snapshot(trunc, pool_size=len(pool), bar_close=T)
    assert snap["covered"] == len(pool) and pd.Timestamp(snap["bar_close"]) == T, snap["covered"]
    want = tab[tab.ts == T].set_index("symbol")
    for s in pool:
        got = F.feature_vector(snap, s)
        assert got is not None
        for k in F.FEATURES_B:
            assert np.isclose(got[k], float(want.loc[s, k]), rtol=1e-9, atol=1e-9, equal_nan=False), (s, k, got[k], want.loc[s, k])


def test_feature_names_match_the_harness_config_b():
    assert F.FEATURES_B == Q.CONFIGS["B"]["features"]
    assert not any("btc" in f or "perp" in f for f in F.FEATURES_B)


def test_snapshot_refusals_are_named_not_raised(tmp_path):
    bars, pool, _tab, T = _golden()
    trunc = {s: bars[s][pd.to_datetime(bars[s].close_ts, utc=True) <= T][["ts", "open", "high", "low", "close", "volume"]] for s in pool}
    p = tmp_path / "snap.json"
    assert F.read_snapshot(p, T)[1] == F.REFUSE_MISSING                                   # absent file
    F.write_snapshot(p, F.build_snapshot(trunc, pool_size=len(pool), bar_close=T))
    snap, why = F.read_snapshot(p, T + pd.Timedelta(hours=1))
    assert snap is not None and why is None
    assert F.read_snapshot(p, T + pd.Timedelta(hours=9))[1] == F.REFUSE_STALE              # older than one decision bar
    half = {s: trunc[s] for s in pool[:3]}
    F.write_snapshot(p, F.build_snapshot(half, pool_size=len(pool), bar_close=T))
    assert F.read_snapshot(p, T)[1] == F.REFUSE_INCOMPLETE                                 # 3 of 8 < 80%
    p.write_text("not json")
    assert F.read_snapshot(p, T)[1] == F.REFUSE_MISSING                                    # corrupt file: refusal, no raise


def test_short_history_is_not_imputed():
    bars, pool, _tab, T = _golden()
    short = {s: bars[s].head(F.MIN_BARS - 1)[["ts", "open", "high", "low", "close", "volume"]] for s in pool}
    assert F.build_snapshot(short, pool_size=len(pool))["covered"] == 0


def test_exit_evaluation_path_never_touches_the_pool_code():
    """The model has a FIXED bracket (no re-scoring): order_monitor must not import or call the pool snapshot / feature code (spec § 4)."""
    for rel in ("src/runtime/order_monitor.py",):
        txt = (REPO / rel).read_text()
        assert "ml_entry_eq_features" not in txt and "read_snapshot" not in txt, rel
