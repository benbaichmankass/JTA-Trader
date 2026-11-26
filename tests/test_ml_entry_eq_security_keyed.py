"""RQ-20261126-7c11-01 (b): the security-keyed pool filter of ml_entry_equity.py (opt-in --security-keyed on `structure`)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

pytest.importorskip("lightgbm")
import ml_entry_equity as M  # noqa: E402


def _bars(*spans):
    """RTH-ish hourly bars (7 per weekday) over each [first, last] date span."""
    ts = []
    for a, b in spans:
        for d in pd.bdate_range(a, b, tz="UTC"):
            ts.extend(d + pd.Timedelta(hours=h) for h in range(14, 21))
    return pd.DataFrame({"ts": ts, "close": 1.0})


END = "2026-10-31"
BARS = {
    "SPYX": _bars(("2021-01-04", "2026-10-30")),                          # continuous: kept
    "FB": _bars(("2021-01-04", "2022-06-08"), ("2025-06-26", "2026-10-30")),   # Meta, then an ETF: two securities
    "INFO": _bars(("2021-01-04", "2022-02-25"), ("2024-10-10", "2026-10-30")),
    "SIX": _bars(("2021-01-04", "2024-07-01")),                            # screened company delisted: early end
    "UN": _bars(("2025-03-03", "2026-10-30")),                             # new security only: late start
}


def test_keeps_continuous_and_excludes_reused_tickers():
    kept, rep = M.security_keyed_pool(BARS, ["SPYX", "FB", "INFO", "SIX", "UN", "ULTI"], end_day=END)
    assert kept == ["SPYX"]
    ex = rep["excluded"]
    assert ex["FB"]["reason"] == "two_securities" and len(ex["FB"]["runs"]) == 2
    assert ex["INFO"]["reason"] == "two_securities"
    assert ex["SIX"]["reason"] == "early_end"
    assert ex["UN"]["reason"] == "late_start"
    assert ex["ULTI"]["reason"] == "no_bars"
    assert rep["n_pool_in"] == 6 and rep["n_kept"] == 1


def test_holiday_gaps_do_not_split_a_security():
    df = _bars(("2021-01-04", "2021-12-23"), ("2021-12-28", "2026-10-30"))   # a 4-day holiday gap
    kept, rep = M.security_keyed_pool({"X": df}, ["X"], end_day=END)
    assert kept == ["X"] and rep["excluded"] == {}


def test_pool_order_kept_and_input_bars_not_mutated():
    bars = {**BARS, "AAAX": _bars(("2021-01-04", "2026-10-30"))}
    n_before = {k: len(v) for k, v in bars.items()}
    kept, _ = M.security_keyed_pool(bars, ["SPYX", "FB", "AAAX"], end_day=END)
    assert kept == ["SPYX", "AAAX"]
    assert {k: len(v) for k, v in bars.items()} == n_before


def test_structure_cli_flag_is_opt_in():
    src = (REPO / "scripts" / "research" / "ml_entry_equity.py").read_text()
    assert '"--security-keyed"' in src and 'getattr(a, "security_keyed", False)' in src
    assert 'tag_extra="-SECKEY"' in src
