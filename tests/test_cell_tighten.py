"""Build gap (c) (row BOOK-SIM-REAL-SIZER / RQ-20261101-78fc-09): the cell-restricted tighten lever.

Pins the lever's rule (late cell = open >= min_r R; level = close -/+ room x ATR; never below break-even, never
looser; one-shot), the matched random control's determinism, and that both harnesses are byte-identical when off and
change trades when on.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))

import cell_tighten as ct  # noqa: E402


def test_off_is_a_no_op():
    t = ct.CellTighten(0.0)
    assert not t.on and t.on_close(5, 120.0, 100.0, 10.0, 2.0, 95.0, True) == 95.0


def test_first_mode_fires_once_in_the_late_cell_at_the_tightest_admissible_level():
    t = ct.CellTighten(1.0, room_atr=1.0, mode="first")
    assert t.on_close(1, 105.0, 100.0, 10.0, 2.0, 90.0, True) == 90.0        # +0.5 R: early cell, no move
    assert t.on_close(2, 111.0, 100.0, 10.0, 2.0, 90.0, True) == 109.0       # +1.1 R: close - 1 ATR
    assert t.fired_j == 2
    assert t.on_close(3, 130.0, 100.0, 10.0, 2.0, 109.0, True) == 109.0      # one-shot


def test_never_below_break_even_and_never_looser():
    t = ct.CellTighten(1.0, room_atr=5.0)
    assert t.on_close(1, 112.0, 100.0, 10.0, 3.0, 90.0, True) == 90.0        # 112 - 15 = 97 < entry: refused
    t = ct.CellTighten(1.0, room_atr=1.0)
    assert t.on_close(1, 111.0, 100.0, 10.0, 2.0, 110.0, True) == 110.0      # 109 would loosen: refused
    t = ct.CellTighten(1.0, room_atr=1.0)                                    # short side mirrors
    assert t.on_close(1, 89.0, 100.0, 10.0, 2.0, 110.0, False) == 91.0


def test_random_control_is_seeded_per_trade_and_in_the_same_cell():
    a = [ct.CellTighten(1.0, mode="random", p=0.5, seed=7, entry_i=k) for k in range(40)]
    b = [ct.CellTighten(1.0, mode="random", p=0.5, seed=7, entry_i=k) for k in range(40)]
    for j in range(1, 6):
        for x, y in zip(a, b):
            assert x.on_close(j, 111.0, 100.0, 10.0, 2.0, 90.0, True) == y.on_close(j, 111.0, 100.0, 10.0, 2.0, 90.0, True)
    fired_at = [x.fired_j for x in a]
    assert any(f == 1 for f in fired_at) and any(f is not None and f > 1 for f in fired_at)   # random timing
    early = ct.CellTighten(1.0, mode="random", p=1.0)
    assert early.on_close(1, 105.0, 100.0, 10.0, 2.0, 90.0, True) == 90.0    # never outside the cell


def _bars(tmp: Path) -> Path:
    rng = np.random.default_rng(11)
    n = 6000
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    c = 100 * np.cumprod(1 + 0.0002 * np.sin(np.arange(n) / 300) + rng.normal(0, 0.006, n))
    df = pd.DataFrame({"timestamp": ts, "open": c, "high": c * 1.004, "low": c * 0.996, "close": c, "volume": 1.0})
    p = tmp / "bars.csv"
    df.to_csv(p, index=False)
    return p


def _run(harness: str, data: Path, out: Path, extra: list[str]) -> dict:
    base = {"trend": ["--donchian", "20"], "pullback": ["--trend-lookback", "50", "--pullback-lookback", "10",
                                                         "--pullback-frac", "0.4"]}[harness]
    argv = [sys.executable, str(REPO / f"scripts/backtest_{harness}.py"), "--data", str(data), "--symbol", "BTCUSDT",
            "--resample", "4h", "--atr-period", "14", "--atr-stop-mult", "2.0", "--trail-mult", "4.0",
            "--fee-bps-roundtrip", "7.5", *base, "--emit-trades", str(out / "t.jsonl"), "--json", str(out / "b.json"), *extra]
    r = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    return {"bt": json.loads((out / "b.json").read_text()), "trades": (out / "t.jsonl").read_text()}


def test_harnesses_off_byte_identical_on_changes_trades(tmp_path):
    data = _bars(tmp_path)
    for h in ("trend", "pullback"):
        outs = {}
        for label, extra in (("plain", []), ("off", ["--cell-tighten-min-r", "0"]),
                             ("first", ["--cell-tighten-min-r", "1.0"]),
                             ("random", ["--cell-tighten-min-r", "1.0", "--cell-tighten-mode", "random",
                                         "--cell-tighten-seed", "3"])):
            d = tmp_path / f"{h}_{label}"
            d.mkdir()
            outs[label] = _run(h, data, d, extra)
        assert outs["off"]["trades"] == outs["plain"]["trades"], f"{h}: off must be byte-identical"
        assert outs["first"]["trades"] != outs["plain"]["trades"], f"{h}: the lever never fired on a trending series"
        assert outs["first"]["bt"].get("params", {}).get("cell_tighten_min_r") == 1.0 or h == "pullback"
