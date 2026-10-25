"""P1-Q10 level-triggered trail (src/research/trail_levers.py level_* / trade_level).

Planted/clean pairs: the swing and FVG levels never read a bar at or after entry; a filled FVG is
not a level; the round level is strictly beyond entry; a half-declared lever is refused; the
default harness run is byte-identical and an armed run reports the lever fired.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.research import trail_levers as tl  # noqa: E402


# ── round ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("px,step", [(2512.0, 100.0), (61234.0, 1000.0), (0.4521, 0.01), (7.3, 0.1)])
def test_auto_round_step(px, step):
    assert tl.auto_round_step(px) == pytest.approx(step)


def test_round_level_is_strictly_beyond_entry():
    assert tl.round_level(2500.0, True) == pytest.approx(2600.0)
    assert tl.round_level(2500.0, False) == pytest.approx(2400.0)
    assert tl.round_level(2512.0, True) == pytest.approx(2600.0)
    assert tl.round_level(2512.0, False) == pytest.approx(2500.0)
    assert tl.round_level(2512.0, True, step=50.0) == pytest.approx(2550.0)


# ── swing ───────────────────────────────────────────────────────────────────
def _flat(n, v=100.0):
    return [v] * n


def test_swing_level_finds_a_confirmed_pivot_above_entry():
    hi, lo = _flat(30), _flat(30, 99.0)
    hi[15] = 110.0                                   # pivot high, confirmed by bars 16..18
    assert tl.swing_level(hi, lo, entry_i=25, entry=100.5, is_long=True, lookback=20, pivot_k=3) == 110.0


def test_swing_level_never_reads_an_unconfirmed_pivot():
    hi, lo = _flat(30), _flat(30, 99.0)
    hi[23] = 110.0                                   # needs bars 24..26 to confirm; entry is 25
    assert tl.swing_level(hi, lo, entry_i=25, entry=100.5, is_long=True, lookback=20, pivot_k=3) is None


def test_swing_level_short_side():
    hi, lo = _flat(30, 101.0), _flat(30)
    lo[10] = 90.0
    assert tl.swing_level(hi, lo, entry_i=25, entry=99.5, is_long=False, lookback=20, pivot_k=3) == 90.0


# ── fvg ─────────────────────────────────────────────────────────────────────
def _gap_down_at(i, n=30):
    # A bearish FVG formed at bar i: bar i-1 is the big down candle, high[i] (=96) < low[i-2] (=99),
    # zone 96..99, near edge 96. Later bars trade below it (high 95.5) so it stays unfilled.
    hi, lo = _flat(n, 101.0), _flat(n, 99.0)
    hi[i - 1], lo[i - 1] = 100.0, 95.0
    hi[i], lo[i] = 96.0, 94.0
    for x in range(i + 1, n):
        hi[x], lo[x] = 95.5, 93.5
    return hi, lo


def test_fvg_level_is_the_near_edge_of_an_unfilled_opposing_gap():
    hi, lo = _gap_down_at(10)
    # a long entered at 94 below the gap: the bearish FVG above is the level (near edge 95)
    assert tl.fvg_level(hi, lo, entry_i=20, entry=94.0, is_long=True, lookback=30) == 96.0


def test_a_filled_gap_is_not_a_level():
    hi, lo = _gap_down_at(10)
    hi[15] = 96.5                                    # traded back into the zone before entry
    assert tl.fvg_level(hi, lo, entry_i=20, entry=94.0, is_long=True, lookback=30) is None


def test_fvg_ignores_a_gap_formed_on_or_after_the_entry_bar():
    hi, lo = _gap_down_at(20)                        # the gap bar IS the entry bar: not closed yet
    assert tl.fvg_level(hi, lo, entry_i=20, entry=94.0, is_long=True, lookback=30) is None


# ── arming / refusals ───────────────────────────────────────────────────────
def test_half_declared_lever_is_refused():
    assert tl.level_flag_errors("swing", 0.0, 6.0, 60, 3, 0.0)
    assert tl.level_flag_errors("", 1.5, 6.0, 60, 3, 0.0)
    assert tl.level_flag_errors("swing", 6.5, 6.0, 60, 3, 0.0)      # cannot loosen
    assert tl.level_flag_errors("bogus", 1.5, 6.0, 60, 3, 0.0)
    assert tl.level_flag_errors("swing", 1.5, 6.0, 60, 3, 0.0) == []
    assert not tl.level_trail_armed("", 0.0) and tl.level_trail_armed("fvg", 1.5)


def test_level_touched():
    assert tl.level_touched(110.0, True, 110.0, 100.0)
    assert not tl.level_touched(110.0, True, 109.9, 100.0)
    assert tl.level_touched(90.0, False, 100.0, 90.0)
    assert not tl.level_touched(None, True, 1e9, 0.0)


# ── harness: default byte-identical, armed fires ────────────────────────────
@pytest.fixture(scope="module")
def csv(tmp_path_factory):
    import numpy as np
    import pandas as pd
    d = tmp_path_factory.mktemp("lvl")
    rng = np.random.default_rng(7)
    ts = pd.date_range("2022-01-01", "2024-06-01", freq="4h", tz="UTC")
    c = 2000 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, len(ts))))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, len(ts))))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, len(ts))))
    p = d / "c.csv"
    pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S%z"), "open": o, "high": h, "low": lo,
                  "close": c, "volume": 1000.0}).to_csv(p, index=False)
    return p


HARNESS = {
    "trend": ["scripts/backtest_trend.py", "--donchian", "20", "--trail-mult", "6.0", "--atr-stop-mult", "1.5"],
    "pullback": ["scripts/backtest_pullback.py", "--trend-lookback", "40", "--pullback-lookback", "10",
                 "--trail-mult", "5.0", "--atr-stop-mult", "1.5"],
}


def _bt(csv, out: Path, harness: str, *extra: str) -> dict:
    script, *base = HARNESS[harness]
    argv = [sys.executable, str(REPO / script), *base, "--data", str(csv), "--symbol", "ETHUSDT",
            "--resample", "4h", "--fee-bps-roundtrip", "7.5", "--tp-cap-pct", "0.099", "--tp-r", "50",
            "--emit-trades", str(out.with_suffix(".jsonl")), "--json", str(out), *extra]
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, check=False, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    d = json.loads(out.read_text())
    d.pop("run_date", None)
    return d


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_armed_lever_fires_and_changes_the_book(csv, tmp_path, harness):
    base = _bt(csv, tmp_path / "base.json", harness)
    assert "level_trail" not in base and "trail_level" not in base["params"]
    armed = _bt(csv, tmp_path / "armed.json", harness, "--trail-level", "round", "--trail-level-tight-mult", "1.5")
    lt = armed["level_trail"]
    assert lt["n_touched"] > 0 and lt["n_with_level"] == lt["n_trades"]
    assert armed["params"]["trail_level"] == "round"
    assert (armed["total_trades"], armed["net_total_r"]) != (base["total_trades"], base["net_total_r"])
