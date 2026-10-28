"""DESK-LIFECYCLE-S0: the full-lifecycle factorial replay driver.

Synthetic candles throughout (no network): the chained engine under HOLD equals the bracket engine, each management
action's fill semantics and cost, validation of levels, pending/resume determinism (the chaining), the masked
checkpoint packet (no look-ahead, no leak), the static-rule menu with leave-one-fold-out B3, and the factorial
arithmetic (cells, contrasts, main effects, interaction).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

from scripts.research import desk_gen_replay_driver as g  # noqa: E402
from scripts.research import desk_lifecycle_driver as lc  # noqa: E402

T0 = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp())
SEC = 3600


def _series(rows, prefix=20, atr=1.0, pad=60, symbol="ETHUSDT"):
    rows = list(rows)
    last = rows[-1][3] if rows else 100.0
    allrows = [(100.0, 100.5, 99.5, 100.0)] * prefix + rows + [(last, last + 0.2, last - 0.2, last)] * pad
    a = np.array(allrows, dtype=float)
    n = len(a)
    return g.Series(symbol, np.array([T0 + i * SEC for i in range(n)], dtype=np.int64), a[:, 0], a[:, 1], a[:, 2],
                    a[:, 3], np.full(n, atr), 11.0, 3.0, 1.0)


def _walk(n=400, seed=1, symbol="ETHUSDT"):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    o = np.concatenate([[100.0], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n)))
    return g.Series(symbol, np.array([T0 + i * SEC for i in range(n)], dtype=np.int64), o, h, lo, c,
                    np.full(n, 0.8), 11.0, 3.0, 1.0)


def _entry(i=19, side=1.0, stop=99.0, tp=102.0, horizon=48, eid="E-x", level=100.0):
    return lc.Entry(eid, "claude", "p1", "ETHUSDT", i, side, "market", level, stop, tp, 1, horizon, 1, "2026-W02", "2026-W02")


def test_checkpoints_registered():
    assert lc.checkpoints(48) == [4, 12, 24, 36]
    assert lc.checkpoints(4) == [1, 2, 3]
    assert all(c < 12 for c in lc.checkpoints(12))


def test_hold_equals_simulate_on_random_walks():
    for seed in range(5):
        s = _walk(seed=seed)
        for i in (30, 80, 150):
            for side in (1.0, -1.0):
                c = float(s.c[i])
                e = _entry(i=i, side=side, level=c, stop=c - side * 1.2, tp=c + side * 2.4)
                t = g.simulate(s, i, side, "market", c, e.stop, e.tp, 1, 48)
                r, p = lc.run(s, e)
                assert p is None and r.state == t.state
                if t.state == "filled":
                    assert abs(r.net_r - t.net_r) < 1e-12
                    r2, _ = lc.run(s, e, lc._static("hold"))
                    assert abs(r2.net_r - t.net_r) < 1e-12 and r2.decided >= 0


def test_close_fills_next_open_and_charges_cost():
    rows = [(100, 100.3, 99.8, 100.2)] * 4 + [(100.6, 100.8, 100.4, 100.5)] + [(100.5, 100.6, 100.4, 100.5)] * 50
    s = _series(rows)
    e = _entry()
    r, p = lc.run(s, e, lambda k, j, st: {"action": "close"} if k == 0 else {"action": "hold"})
    assert p is None and r.exit_reason == "claude_close"
    # checkpoint 1 = close of the 4th bar held (index 20..23 -> j = 23); close fills at bar 24's open = 100.6
    assert r.pieces[0][1] == pytest.approx(100.6)
    fill = float(s.o[20])
    assert r.gross_r == pytest.approx((100.6 - fill) / (fill - 99.0))
    assert 0 < r.cost_r < 0.5 and r.net_r == pytest.approx(r.gross_r - r.cost_r)


def test_partial_close_weights_pieces():
    rows = [(100, 100.3, 99.8, 100.2)] * 4 + [(100.6, 100.8, 100.4, 100.5)] + [(100.5, 100.6, 100.4, 100.5)] * 50
    s = _series(rows)
    e = _entry()
    r, _ = lc.run(s, e, lambda k, j, st: {"action": "partial_close"} if k == 0 else {"action": "hold"})
    assert [round(p[0], 3) for p in r.pieces] == [0.5, 0.5] and r.pieces[0][3] == "claude_partial"
    assert r.pieces[1][3] == "timeout"
    # a second partial is invalid -> hold, counted
    r2, _ = lc.run(s, e, lambda k, j, st: {"action": "partial_close"})
    assert r2.invalid >= 1 and len(r2.pieces) == 2


def test_tighten_moves_stop_from_next_bar_and_validation():
    st = {"close_r": 1.0, "stop_r": -1.0, "tp_r": 2.0, "partial_taken": False}
    assert lc.validate({"action": "tighten_sl", "level_r": 0.5}, st) == ("tighten_sl", 0.5, True)
    assert lc.validate({"action": "tighten_sl", "level_r": 0.95}, st)[2] is False      # inside MIN_GAP_R of price
    assert lc.validate({"action": "tighten_sl", "level_r": -1.5}, st)[2] is False      # a loosening is not a tighten
    assert lc.validate({"action": "widen_sl", "level_r": -1.5}, st) == ("widen_sl", -1.5, True)
    assert lc.validate({"action": "widen_sl", "level_r": -2.5}, st)[2] is False        # past the floor
    assert lc.validate({"action": "move_tp", "level_r": 3.0}, st) == ("move_tp", 3.0, True)
    assert lc.validate({"action": "move_tp", "level_r": 1.05}, st)[2] is False
    assert lc.validate({"action": "bogus"}, st)[2] is False and lc.validate(None, st)[2] is False
    # path: up to +1.5 by checkpoint 1, then a pullback to +0.2 -> a tighten to +0.5 stops out at +0.5, hold does not
    rows = [(100, 101.5, 99.9, 101.5)] * 4 + [(101.4, 101.4, 100.2, 100.2)] + [(100.2, 100.3, 100.1, 100.2)] * 50
    s = _series(rows)
    e = _entry()
    r, _ = lc.run(s, e, lambda k, j, st: {"action": "tighten_sl", "level_r": 0.5} if k == 0 else {"action": "hold"})
    assert r.exit_reason == "sl" and r.moved_stop_exit
    fill = float(s.o[20])
    assert r.gross_r == pytest.approx((fill + 0.5 * (fill - 99.0) - fill) / (fill - 99.0))
    h, _ = lc.run(s, e)
    assert h.exit_reason == "timeout"


def test_pending_then_resume_is_deterministic():
    s = _walk(seed=7)
    c = float(s.c[50])
    e = _entry(i=50, side=-1.0, level=c, stop=c + 1.5, tp=c - 6.0)
    dec = {}
    ks = []
    for _ in range(10):
        r, p = lc.run(s, e, lambda k, j, st: dec.get(k))
        if p is None:
            break
        ks.append(p.k)
        dec[p.k] = {"action": "hold"}
    assert ks == sorted(ks) and len(set(ks)) == len(ks)
    full, _ = lc.run(s, e, lambda k, j, st: dec.get(k, {"action": "hold"}))
    hold, _ = lc.run(s, e)
    assert full.net_r == pytest.approx(hold.net_r)


def test_packet_masked_and_no_lookahead():
    s = _walk(seed=3)
    c = float(s.c[60])
    e = _entry(i=60, level=c, stop=c - 2.0, tp=c + 8.0)
    _r, p = lc.run(s, e, lambda k, j, st: None)
    assert p is not None
    pk, key = lc.build_packet(s, e, p)
    txt = json.dumps(pk)
    assert lc.leak_scan(txt, key, ["ETHUSDT", "BTCUSDT"]) == []
    assert pk["bars_ohlc"][-1][0] == 0 and pk["bars_ohlc"][-1][4] == pytest.approx(100.0)
    assert "E-x" not in txt and "claude" not in txt.lower()
    s2 = g.Series(s.symbol, s.t.copy(), s.o.copy(), s.h.copy(), s.l.copy(), s.c.copy(), s.atr.copy(), 11.0, 3.0, 1.0)
    for arr in (s2.o, s2.h, s2.l, s2.c):
        arr[p.j + 1:] *= 3.0
    _r2, p2 = lc.run(s2, e, lambda k, j, st: None)
    assert lc.packet_sha(lc.build_packet(s2, e, p2)[0]) == lc.packet_sha(pk)
    bad = dict(pk, note="ethusdt random 2026-01-05")
    found = lc.leak_scan(json.dumps(bad), key, ["ETHUSDT"])
    assert any(f.startswith("symbol") for f in found) and any(f.startswith("source") for f in found) \
        and any(f.startswith("date") for f in found)


def test_best_static_lofo_uses_other_folds_only():
    hold = {f"p{n}": 0.0 for n in range(8)}
    fold = {f"p{n}": 1 + n % 4 for n in range(8)}
    # rule A wins everywhere except fold 1 (where it would look best only by peeking)
    a = {p: (1.0 if fold[p] != 1 else -5.0) for p in hold}
    b = {p: 0.5 for p in hold}
    out = lc.best_static_lofo({"A": a, "B": b}, fold, hold)
    assert out["p0"] == -5.0       # fold 1 chose A from folds 2-4, and pays A's fold-1 outcome
    out2 = lc.best_static_lofo({"A": {p: (5.0 if fold[p] == 1 else -1.0) for p in hold}, "B": b}, fold, hold)
    assert out2["p0"] == 0.5       # A looks best only on fold 1 itself, so fold 1 gets B


def test_factorial_arithmetic():
    rows = []
    for n in range(40):
        rows.append({"pair_id": f"p{n}", "week": f"2026-W{n % 10:02d}", "fold": 1 + n % 4,
                     "C_h": 0.1, "C_m": 0.4, "R_h": -0.1, "R_m": 0.0, "C_b3": 0.2, "R_b3": 0.0})
    fx = lc.factorial(rows)
    c = fx["contrasts"]
    assert c["mgmt_value|claude_entry"]["mean"] == pytest.approx(0.3)
    assert c["mgmt_value|random_entry"]["mean"] == pytest.approx(0.1)
    assert c["entry_value|hold"]["mean"] == pytest.approx(0.2)
    assert c["entry_value|claude_mgmt"]["mean"] == pytest.approx(0.4)
    assert c["main_effect_mgmt"]["mean"] == pytest.approx(0.2)
    assert c["main_effect_entry"]["mean"] == pytest.approx(0.3)
    assert c["interaction"]["mean"] == pytest.approx(0.2)
    assert c["claude_mgmt_vs_b3|claude_entry"]["mean"] == pytest.approx(0.2)
    assert fx["cells"]["C_m"]["n"] == 40 and fx["cells"]["C_m"]["weeks"] == 10
    # a constant contrast has a degenerate CI at its value; an unjudged arm has n 0, never 0 R
    assert c["interaction"]["ci95"] == pytest.approx([0.2, 0.2])
    fx2 = lc.factorial([dict(r, C_m=None, R_m=None) for r in rows])
    assert fx2["contrasts"]["interaction"]["n"] == 0 and fx2["contrasts"]["interaction"]["mean"] is None


def test_grade_contrast_rule():
    st = {"n": 200, "mean": 0.1, "ci95": [0.02, 0.2]}
    assert lc.grade_contrast(st, 3, True)[0] == "pass"
    assert lc.grade_contrast(st, 3, False)[0] == "pass_rule"
    assert lc.grade_contrast(st, 2, True)[0] == "indeterminate"
    assert lc.grade_contrast({"n": 200, "mean": -0.2, "ci95": [-0.3, -0.1]}, 0, None)[0] == "fail"
    assert lc.grade_contrast({"n": 50, "mean": 0.5, "ci95": [0.4, 0.6]}, 4, True)[0] == "indeterminate"


def test_read_decisions_joins_round_keys(tmp_path):
    rd = tmp_path / "rounds"
    rd.mkdir()
    (rd / "round-01-key.jsonl").write_text(json.dumps({"packet_id": "LC-a", "entry_id": "E-1", "k": 0}) + "\n")
    d = tmp_path / "dec.jsonl"
    d.write_text(json.dumps({"packet_id": "LC-a", "action": "close"}) + "\n" + json.dumps({"packet_id": "LC-a", "action": "hold"}) + "\n")
    got = lc.read_decisions(tmp_path, d)
    assert got == {("E-1", 0): {"packet_id": "LC-a", "action": "close"}}     # first answer wins
    d.write_text(json.dumps({"packet_id": "LC-zz", "action": "hold"}) + "\n")
    with pytest.raises(ValueError):
        lc.read_decisions(tmp_path, d)


# ----------------------------------------------------------------------------- v2: check-in policies, rule arms, M1, walker packet
def _trend_down(n=80):
    rows, px = [], 100.0
    for i in range(n):
        o = px
        px = px - 0.15
        rows.append((o, o + 0.1, px - 0.1, px))
    return rows


def test_policies_select_checkins_and_hold_is_unchanged():
    s = _series(_trend_down())
    e = _entry(side=-1.0, stop=101.0, tp=90.0)
    hold, _ = lc.run(s, e)
    for name in ("C1", "C4", "E", "C4E", "C1E"):
        r, p = lc.run(s, e, lambda k, j, st: {"action": "hold"}, lc.POLICIES[name]())
        assert p is None and r.net_r == pytest.approx(hold.net_r)
    c1, _ = lc.run(s, e, lambda k, j, st: {"action": "hold"}, lc.POLICIES["C1"]())
    c4, _ = lc.run(s, e, lambda k, j, st: {"action": "hold"}, lc.POLICIES["C4"]())
    assert [c["bars_held"] for c in c4.checkins] == [b for b in [c["bars_held"] for c in c1.checkins] if b % 4 == 0]
    ev, _ = lc.run(s, e, lambda k, j, st: {"action": "hold"}, lc.POLICIES["E"]())
    tags = [t for c in ev.checkins for t in c["tags"]]
    assert "r+0.5" in tags and "r+1.0" in tags and tags.count("r+0.5") == 1      # each milestone fires once


def test_chandelier_only_tightens_and_rules_run():
    s = _series(_trend_down())
    e = _entry(side=-1.0, stop=101.0, tp=90.0)
    r, _ = lc.run(s, e, lc._rule2("chandelier_2atr"), lc.POLICIES["C1E"]())
    stops = [c["level_r"] for c in r.checkins if c["action"] == "tighten_sl"]
    assert stops and stops == sorted(stops)
    for rn in lc.RULES2:
        rr, p = lc.run(s, e, lc._rule2(rn), lc.POLICIES["C1E"]())
        assert p is None and rr.state == "filled"


def test_matched_random_fires_same_action_types():
    cks = [{"k": 0, "action": "hold", "level_r": None, "now_r": 0.1, "tags": [], "bars_held": 1},
           {"k": 1, "action": "tighten_sl", "level_r": 0.2, "now_r": 1.0, "tags": [], "bars_held": 2},
           {"k": 2, "action": "close", "level_r": None, "now_r": 1.2, "tags": [], "bars_held": 3}]
    s = _series(_trend_down())
    e = _entry(side=-1.0, stop=101.0, tp=90.0)
    seen = set()
    for seed in range(20):
        r, _ = lc.run(s, e, lc.matched_random(cks, seed), lc.POLICIES["C1"]())
        acts = [a for a in r.actions if a != "hold"]
        assert acts == ["tighten_sl", "close"][:len(acts)]              # same types, same order, never more
        seen.add(len(acts))
    assert 2 in seen


def test_walker_packet_masked_and_incremental():
    s = _walk(seed=5)
    c = float(s.c[60])
    e = _entry(i=60, level=c, stop=c - 2.0, tp=c + 8.0)
    pol = lc.POLICIES["C1"]
    _r, p0 = lc.run(s, e, lambda k, j, st: None, pol())
    pk0, key0 = lc.build_packet_v2(s, e, p0, None)
    assert pk0["trade"]["entry_px"] == 100.0 and len(pk0["new_bars"]) == lc.WALK_FIRST_BARS
    assert lc.leak_scan(json.dumps(pk0), key0, ["ETHUSDT"]) == []
    _r, p1 = lc.run(s, e, lambda k, j, st: {"action": "hold"} if k == 0 else None, pol())
    pk1, _ = lc.build_packet_v2(s, e, p1, p0.j)
    assert [b[0] for b in pk1["new_bars"]] == [p1.j - (e.i + 1)]           # only the bar since the last check-in
    assert pk1["trade"]["actions_so_far"] == ["hold"] and pk1["packet_id"] != pk0["packet_id"]
