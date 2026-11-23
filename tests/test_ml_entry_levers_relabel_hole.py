"""ml_entry_levers.relabel_table follows the table's hole-safe regrid (RQ-20261101-b608-01 run 45086511890, group D2 re-arm).

``E.build_table`` regrids each symbol hourly since ML-ENTRY-HOLE-SAFE-ADOPT (2026-11-12), so the table's ``i`` is a position in the REGRIDDED frame. ``relabel_table``
read the raw cache frame, so after a one-hour data hole every later position was shifted by one bar, the decision phase moved (i = 3 mod 4 -> 2 mod 4) and every later
row failed to join: the unit died with 'relabel left rows without labels' (ADAUSDT, 2024-10-28). Measured on a rebuilt table (60 symbols, 660,652 rows): the fix
reproduces every table label column exactly at the entry bracket (0 mismatching columns).

Locked on a synthetic frame with one hole: (1) with the hole-safe default, relabelling at the entry bracket reproduces the table's own label columns row for row;
(2) a table keyed on the raw frame (hole_safe=False) is a different keying and the join refuses rather than mislabel; (3) a frame with no hole is unchanged by either
setting (so every pre-existing caller is byte-identical).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import scripts.research.ml_decision_entry as E
import scripts.research.ml_entry_levers as L


def _frame(n: int = 700, hole_at: int | None = 300, seed: int = 7, hole_len: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    df = pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"),
                       "open": open_, "high": high, "low": low, "close": close, "volume": 1.0})
    if hole_at is not None:
        df = df.drop(index=range(hole_at, hole_at + hole_len)).reset_index(drop=True)   # missing hourly bars (1 = the ADAUSDT hole)
    return df


def _table_like_build_table(df: pd.DataFrame) -> pd.DataFrame:
    """Decision rows keyed exactly as E.build_table keys them (hole_safe=True): positions in the regridded frame, and, as build_table
    does, a row whose entry-bracket net is NaN (an outcome truncated by the hole) is dropped."""
    lab = E.label_symbol(E.regrid_hourly(df))
    lab["symbol"] = "XUSDT"
    return lab.dropna(subset=["net_long", "net_short"]).reset_index(drop=True)


def _cache(tmp_path, df):
    df.to_pickle(tmp_path / "XUSDT.pkl")
    return tmp_path


def test_relabel_at_entry_bracket_reproduces_the_table_across_a_hole(tmp_path):
    df = _frame(hole_at=300)
    tab = _table_like_build_table(df)
    assert len(tab) > 50
    out = L.relabel_table(tab, _cache(tmp_path, df), E.SL_ATR, E.TP_ATR)
    for c in L.LABEL_COLS:
        a, b = tab[c].to_numpy(), out[c].to_numpy()
        if a.dtype.kind in "fi":
            assert np.allclose(a.astype(float), b.astype(float), equal_nan=True, rtol=0, atol=1e-9), c
        else:
            assert (a == b).all(), c


def test_the_raw_frame_keying_refuses_instead_of_mislabelling(tmp_path):
    df = _frame(hole_at=300)
    tab = _table_like_build_table(df)
    with pytest.raises(RuntimeError, match="without labels"):
        L.relabel_table(tab, _cache(tmp_path, df), E.SL_ATR, E.TP_ATR, hole_safe=False)


def test_a_frame_without_a_hole_is_identical_under_both_settings(tmp_path):
    df = _frame(hole_at=None)
    tab = _table_like_build_table(df)
    cache = _cache(tmp_path, df)
    a = L.relabel_table(tab, cache, 2.0, 4.0)
    b = L.relabel_table(tab, cache, 2.0, 4.0, hole_safe=False)
    assert a[L.LABEL_COLS].equals(b[L.LABEL_COLS])


# ---- option (a) (manager 2026-11-23): rows whose bracket outcome is unobservable are dropped from every arm, counted, never NaN ------------------

def _wide_bracket_case(tmp_path):
    """A 12-bar hole: rows that resolved before it at the entry bracket but not at a wider take-profit have NaN later bars."""
    df = _frame(hole_at=300, hole_len=12, seed=4)
    tab = _table_like_build_table(df)
    return tab, _cache(tmp_path, df)


def test_unobservable_rows_exist_at_a_wider_bracket_and_relabel_still_refuses(tmp_path):
    tab, cache = _wide_bracket_case(tmp_path)
    m = L.unobservable_mask(tab, cache, [(2.0, 50.0)])
    assert m.sum() > 0 and m.sum() < len(tab)
    with pytest.raises(RuntimeError, match="without labels"):
        L.relabel_table(tab, cache, 2.0, 50.0)            # the refusal is kept: NaN never reaches an arm silently


def test_drop_unobservable_makes_relabel_succeed_and_counts_the_drop(tmp_path):
    tab, cache = _wide_bracket_case(tmp_path)
    kept, info = L.drop_unobservable(tab, cache, [(2.0, 50.0)])
    assert info["n_total"] == len(tab) and info["n_dropped"] == len(tab) - len(kept) > 0
    assert info["brackets"] == [[2.0, 50.0]] and "option (a)" in info["rule"]
    out = L.relabel_table(kept, cache, 2.0, 50.0)
    assert not out[["net_long", "net_short"]].isna().any().any()


def test_union_over_brackets_so_every_cell_compares_the_same_rows(tmp_path):
    tab, cache = _wide_bracket_case(tmp_path)
    a = L.unobservable_mask(tab, cache, [(2.0, 4.0)])
    b = L.unobservable_mask(tab, cache, [(2.0, 50.0)])
    both = L.unobservable_mask(tab, cache, [(2.0, 4.0), (2.0, 50.0)])
    assert (both == (a | b)).all()


def test_filter_unobservable_masks_the_arrays_with_the_frame(tmp_path):
    tab, cache = _wide_bracket_case(tmp_path)
    pl, ps = np.arange(len(tab), dtype=float), np.arange(len(tab), dtype=float) * 2
    passes = np.ones(len(tab), bool)
    kept, (pl2, ps2, pass2), info = L.filter_unobservable(tab, cache, (2.0, 50.0), pl, ps, passes)
    assert len(kept) == len(pl2) == len(ps2) == len(pass2) == len(tab) - info["n_dropped"]
    m = L.unobservable_mask(tab, cache, [(2.0, 50.0)])
    assert (pl2 == pl[~m]).all() and (ps2 == ps[~m]).all()


def test_a_keying_error_is_not_mistaken_for_an_unobservable_outcome(tmp_path):
    df = _frame(hole_at=300, hole_len=1)
    tab = _table_like_build_table(df)
    with pytest.raises(RuntimeError, match="keying error"):
        L.unobservable_mask(tab, _cache(tmp_path, df), [(2.0, 4.0)], hole_safe=False)
