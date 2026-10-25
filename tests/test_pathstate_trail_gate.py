"""PATHSTATE-TRAIL-GATE: path-state gates on the exit harnesses (Tier-1 research tooling).

--trail-state-* / --bank-state-* / --chop-stop-* in scripts/backtest_pullback.py and scripts/backtest_trend.py,
default-off and byte-identical. The shared tracker is src/research/path_state_gate.py; the features are
scripts/research/path_state_giveback.py::state_at (the function trade_states calls).
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research"), str(REPO / "scripts")]
import path_state_giveback as psg  # noqa: E402
from src.research import path_state_gate as gate  # noqa: E402


def _row(c, fav, adv, peak, bsp=0, atr=0.5, stop_room=1.0):
    return {"c_r": c, "fav_r": fav, "adv_r": adv, "open_r": c, "peak_r": peak, "bars_since_peak": bsp,
            "atr_r": atr, "dist_to_stop_r": stop_room}


def _path(closes, atr=0.5):
    """Rows for a long trade from a list of bar closes in R (fav/adv = close +- 0.1)."""
    rows, pk = [], 0.0
    for i, c in enumerate(closes):
        pk = max(pk, c + 0.1)
        rows.append(_row(c, c + 0.1, c - 0.1, pk, bsp=0 if c + 0.1 >= pk else 1, atr=atr))
    return rows


TREND = [0.4, 0.9, 1.4, 1.9, 2.4, 2.9, 3.4, 3.9]                       # straight up: efficiency ratio ~1
CHOP = [0.4, 1.4, 0.6, 1.6, 0.7, 1.7, 0.8, 1.8, 0.7, 1.7, 0.8, 1.7]    # same range, no direction


# ── the features ARE trade_states' features ─────────────────────────────────
def test_gate_features_are_the_trade_states_features():
    rnd = random.Random(3)
    c, pk, rows = 0.0, 0.0, []
    for i in range(40):
        c += rnd.gauss(0.05, 0.4)
        pk = max(pk, c)
        rows.append(_row(c, c + 0.2, c - 0.2, pk, bsp=i % 5, atr=0.5 + 0.01 * i))
    rows[-1]["is_exit"] = True
    by_t = {s["t"]: s for s in psg.trade_states(rows, 6, -99.0)}
    assert by_t
    for t, s in by_t.items():
        st = psg.state_at(rows[:t + 1], t, 6)          # ONLY rows 0..t are visible
        assert st is not None
        for k in ("er_w", "chop_w", "atr_ratio_t", "dist_atr_t", "vol_ratio_t", "open_r", "peak_r"):
            assert st[k] == s[k], (t, k)


def test_gate_decision_at_t_ignores_every_later_bar():
    rows = _path(CHOP)
    cond = gate.Cond("er", 6, "lt", 0.3)
    for t in range(5, len(rows)):
        a = cond.holds(psg.state_at(rows[:t + 1], t, 6))
        mutated = rows[:t + 1] + [_row(99.0 * (i + 1), 1e3, -1e3, 1e3, atr=9.0) for i in range(5)]
        assert a == cond.holds(psg.state_at(mutated, t, 6)), t


# ── a planted signal only the gate can separate ─────────────────────────────
def _run_gate(closes, **kw):
    g = gate.build_gate(**{**dict(trail_feature="er", trail_window=6, trail_op="lt", trail_thr=0.3,
                                  trail_arm_r=1.5, trail_tight_mult=2.5, bank_feature="", bank_window=6,
                                  bank_op="", bank_thr=0.0, bank_arm_r=0.0, chop_feature="", chop_window=6,
                                  chop_op="", chop_thr=0.0, chop_bars=0, chop_min_peak_r=0.0,
                                  chop_max_open_frac=1.0), **kw})
    g.start()
    fired = []
    for row in _path(closes):
        fired.append(g.on_bar_close(row))
    return g, fired


def test_trail_gate_tightens_in_chop_and_not_in_a_clean_trend():
    for closes, expect in ((TREND, False), (CHOP, True)):
        g = gate.build_gate("er", 6, "lt", 0.3, 1.5, 2.5, "", 6, "", 0.0, 0.0, "", 6, "", 0.0, 0, 0.0, 1.0)
        g.start()
        seen = []
        for row in _path(closes):
            g.on_bar_close(row)
            seen.append(g.tight(5.0))
        assert (min(seen) == 2.5) is expect, (closes[:3], seen)
        assert max(seen) == 5.0 or not expect             # composes by MIN: never loosens the base mult
    g = gate.build_gate("er", 6, "lt", 0.3, 1.5, 2.5, "", 6, "", 0.0, 0.0, "", 6, "", 0.0, 0, 0.0, 1.0)
    g.start()
    for row in _path(CHOP):
        g.on_bar_close(row)
    assert g.tight(2.0) == 2.0                            # an already tighter mult is kept


def test_trail_gate_is_armed_by_peak_r():
    g = gate.build_gate("er", 6, "lt", 0.3, 9.0, 2.5, "", 6, "", 0.0, 0.0, "", 6, "", 0.0, 0, 0.0, 1.0)
    g.start()
    for row in _path(CHOP):
        g.on_bar_close(row)
    assert g.tight(5.0) == 5.0                            # peak never reached 9 R


def test_bank_gate_allows_the_rung_only_when_the_state_holds():
    for closes, allowed in ((TREND, False), (CHOP, True)):
        g = gate.build_gate("", 6, "", 0.0, 0.0, 0.0, "er", 6, "lt", 0.3, 0.0, "", 6, "", 0.0, 0, 0.0, 1.0)
        g.start()
        ok = []
        for row in _path(closes):
            g.on_bar_close(row)
            ok.append(g.bank_allowed())
        assert any(ok) is allowed
    off = gate.build_gate("", 6, "", 0.0, 0.0, 0.0, "", 6, "", 0.0, 0.0, "", 6, "", 0.0, 0, 0.0, 1.0)
    assert off.bank_allowed() and not off.on and off.tight(5.0) == 5.0


def test_chop_stop_fires_after_n_consecutive_qualifying_bars_only():
    _, fired_chop = _run_gate(CHOP, trail_feature="", trail_tight_mult=0.0, chop_feature="er", chop_op="lt",
                              chop_thr=0.3, chop_bars=3, chop_min_peak_r=1.0, chop_max_open_frac=0.9)
    _, fired_trend = _run_gate(TREND, trail_feature="", trail_tight_mult=0.0, chop_feature="er", chop_op="lt",
                               chop_thr=0.3, chop_bars=3, chop_min_peak_r=1.0, chop_max_open_frac=0.9)
    assert any(fired_chop) and not any(fired_trend)
    first = fired_chop.index(True)
    assert first >= 5 + 2                                 # window warm-up (t >= w-1) + 3 consecutive bars
    # one qualifying bar short of N never fires
    _, short = _run_gate(CHOP[:first], trail_feature="", trail_tight_mult=0.0, chop_feature="er", chop_op="lt",
                         chop_thr=0.3, chop_bars=3, chop_min_peak_r=1.0, chop_max_open_frac=0.9)
    assert not any(short)


def test_flag_refusals():
    base = ("", 6, "", 0.0, 0.0, 0.0, "", 6, "", 0.0, 0.0, 0.0, 0.0, "", 6, "", 0.0, 0, 0.0, 1.0, 5.0, 0.0)
    assert gate.path_state_flag_errors(*base) == []
    half = list(base)
    half[0] = "er"                                        # feature without a tight mult
    assert gate.path_state_flag_errors(*half)
    ok = list(base)
    ok[0], ok[5], ok[3] = "er", 2.5, 0.3
    assert gate.path_state_flag_errors(*ok) == []
    loose = list(ok)
    loose[5] = 6.0                                        # tight mult above --trail-mult
    assert gate.path_state_flag_errors(*loose)
    bank = list(base)
    bank[6] = "er"                                        # bank gate with no rung declared
    assert gate.path_state_flag_errors(*bank)
    chop = list(base)
    chop[13] = "er"                                       # chop feature without bars
    assert gate.path_state_flag_errors(*chop)


# ── harness runs (both harnesses) ───────────────────────────────────────────
def _make_csv(path: Path, seed: int = 7, change_from: int | None = None):
    import numpy as np
    import pandas as pd
    ts = pd.date_range("2022-01-01", "2024-06-01", freq="4h", tz="UTC")

    def build(sd):
        rng = np.random.default_rng(sd)
        c = 2000 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, len(ts))))
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, len(ts))))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, len(ts))))
        return np.c_[o, h, lo, c]
    a = build(seed)
    if change_from is not None:
        b = build(seed + 100)
        scale = a[change_from - 1, 3] / b[change_from - 1, 3]
        a[change_from:] = b[change_from:] * scale          # continuous at the seam, different afterwards
    pd.DataFrame({"timestamp": ts.strftime("%Y-%m-%d %H:%M:%S%z"), "open": a[:, 0], "high": a[:, 1],
                  "low": a[:, 2], "close": a[:, 3], "volume": 1000.0}).to_csv(path, index=False)
    return ts


@pytest.fixture(scope="module")
def csv(tmp_path_factory):
    p = tmp_path_factory.mktemp("pstg") / "c.csv"
    _make_csv(p)
    return p


HARNESS = {
    "trend": ["scripts/backtest_trend.py", "--donchian", "20", "--trail-mult", "6.0", "--atr-stop-mult", "1.5"],
    "pullback": ["scripts/backtest_pullback.py", "--trend-lookback", "40", "--pullback-lookback", "10",
                 "--trail-mult", "5.0", "--atr-stop-mult", "1.5"],
}


def _run(csv, out: Path, harness: str, *extra: str, expect_rc: int = 0):
    script, *base = HARNESS[harness]
    argv = [sys.executable, str(REPO / script), *base, "--data", str(csv), "--symbol", "ETHUSDT",
            "--resample", "4h", "--fee-bps-roundtrip", "7.5", "--tp-cap-pct", "0.099", "--tp-r", "50",
            "--emit-trades", str(out.with_suffix(".jsonl")), "--json", str(out), *extra]
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, check=False, timeout=600)
    assert r.returncode == expect_rc, r.stderr[-2000:]
    if expect_rc:
        return r.stderr
    d = json.loads(out.read_text())
    d.pop("run_date", None)
    trades = [json.loads(ln) for ln in out.with_suffix(".jsonl").read_text().splitlines() if ln.strip()]
    return d, trades


ER_TIGHT = ["--trail-state-feature", "er", "--trail-state-window", "6", "--trail-state-op", "lt",
            "--trail-state-thr", "0.3", "--trail-state-arm-r", "1.5", "--trail-state-tight-mult", "2.5"]
CHOP_STOP = ["--chop-stop-feature", "er", "--chop-stop-window", "6", "--chop-stop-thr", "0.25",
             "--chop-stop-bars", "4", "--chop-stop-min-peak-r", "1.0", "--chop-stop-max-open-frac", "0.5"]


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_flags_at_their_defaults_are_byte_identical(csv, tmp_path, harness):
    a = _run(csv, tmp_path / "a.json", harness)
    b = _run(csv, tmp_path / "b.json", harness, "--trail-state-tight-mult", "0", "--trail-state-arm-r", "0",
             "--bank-state-arm-r", "0", "--chop-stop-bars", "0", "--chop-stop-max-open-frac", "1.0")
    assert a == b
    assert "path_state_gate" not in a[0]["params"]


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_a_gate_that_can_never_hold_equals_the_baseline(csv, tmp_path, harness):
    """er is >= 0, so er < 0.0 is never true (er > 1.0 is NOT: a perfectly directional window rounds to 1+eps): every armed gate must then be a no-op, byte for byte."""
    base_d, base_t = _run(csv, tmp_path / "a.json", harness, "--bank-frac", "0.5", "--bank-at-r", "1.0")
    never = ["--trail-state-feature", "er", "--trail-state-op", "lt", "--trail-state-thr", "0.0",
             "--trail-state-arm-r", "0.5", "--trail-state-tight-mult", "2.5",
             "--chop-stop-feature", "er", "--chop-stop-op", "lt", "--chop-stop-thr", "0.0", "--chop-stop-bars", "2"]
    d, t = _run(csv, tmp_path / "n.json", harness, "--bank-frac", "0.5", "--bank-at-r", "1.0", *never)
    assert t == base_t
    d["params"].pop("path_state_gate")
    assert d == base_d
    # the bank gate with an impossible condition removes the bank credit: it is a real gate, not decoration
    bd, bt = _run(csv, tmp_path / "b.json", harness, "--bank-frac", "0.5", "--bank-at-r", "1.0",
                  "--bank-state-feature", "er", "--bank-state-op", "lt", "--bank-state-thr", "0.0")
    nobank = _run(csv, tmp_path / "z.json", harness)
    assert [x["net_r"] for x in bt] == [x["net_r"] for x in nobank[1]]


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_armed_gates_change_the_run_and_chop_stop_is_labelled(csv, tmp_path, harness):
    base_d, base_t = _run(csv, tmp_path / "a.json", harness)
    d, t = _run(csv, tmp_path / "e.json", harness, *ER_TIGHT)
    assert d["params"]["path_state_gate"]["trail"][0] == "er" and t != base_t
    d, t = _run(csv, tmp_path / "k.json", harness, *CHOP_STOP)
    stops = [x for x in t if x["exit_reason"] == "chop_stop"]
    assert stops and d["params"]["path_state_gate"]["chop_stop"][0] == "er"
    # a chop stop only ever fires on a trade that had run >= 1 R and given back half of it
    assert all(x["mfe_r"] >= 1.0 for x in stops)
    d1, t1 = _run(csv, tmp_path / "b.json", harness, "--bank-frac", "0.5", "--bank-at-r", "1.0",
                  "--bank-state-feature", "er", "--bank-state-thr", "0.3")
    d2, t2 = _run(csv, tmp_path / "u.json", harness, "--bank-frac", "0.5", "--bank-at-r", "1.0")
    assert [x["net_r"] for x in t1] != [x["net_r"] for x in t2]      # gated bank != ungated bank


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_changing_bars_after_t_cannot_change_a_trade_closed_before_t(tmp_path, csv, harness):
    """Engine-level no-lookahead: two feeds identical up to bar X and different after it. Every trade that
    closed before X must be identical (same exit, same R) with ALL THREE gates armed."""
    X = 2400
    p2 = tmp_path / "c2.csv"
    ts = _make_csv(p2, change_from=X)
    arm = [*ER_TIGHT, *CHOP_STOP, "--bank-frac", "0.5", "--bank-at-r", "1.0", "--bank-state-feature", "er",
           "--bank-state-thr", "0.3"]
    _, t_a = _run(csv, tmp_path / "x.json", harness, *arm)
    _, t_b = _run(p2, tmp_path / "y.json", harness, *arm)
    cut = str(ts[X])
    done_a = [x for x in t_a if x["exit_time"] < cut]
    done_b = [x for x in t_b if x["exit_time"] < cut]
    assert len(done_a) > 50 and done_a == done_b
    assert any(x["exit_reason"] == "chop_stop" for x in done_a)


@pytest.mark.parametrize("harness", sorted(HARNESS))
def test_half_declared_gates_are_refused(csv, tmp_path, harness):
    err = _run(csv, tmp_path / "h.json", harness, "--trail-state-feature", "er", expect_rc=2)
    assert "tight-mult" in err
    err = _run(csv, tmp_path / "h2.json", harness, "--bank-state-feature", "er", expect_rc=2)
    assert "bank-frac" in err
    err = _run(csv, tmp_path / "h3.json", harness, "--chop-stop-bars", "4", expect_rc=2)
    assert "chop-stop-feature" in err
