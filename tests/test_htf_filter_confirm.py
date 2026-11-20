"""scripts/research/htf_filter_confirm.py: the P3-M27 HTF-filter confirmation grade.

Covers the ORIGINAL RQ-20260928-001 rule (n floor, ON net > OFF net, ON mean not worse than OFF by more than the tolerance) and the clause
the programme node added (ON > OFF with each arm's single worst trade removed): a PASS carried by one outlier is a FAIL, a too-thin sample is
INDETERMINATE, both trade-file formats read, and the fold table bins both arms on the same calendar edges.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import htf_filter_confirm as h  # noqa: E402

T0 = datetime(2024, 10, 25, tzinfo=timezone.utc)


def _rows(rs, step_h=12):
    return [
        {"entry_time": str(T0 + timedelta(hours=step_h * i)), "exit_time": str(T0 + timedelta(hours=step_h * i + 3)),
         "direction": "long", "net_r": r}
        for i, r in enumerate(rs)
    ]


def _g(off, on, **kw):
    return h.grade(_rows(off), _rows(on), min_n=kw.get("min_n", 175), mean_tol=kw.get("mean_tol", 0.3), n_folds=6)


def test_pass_when_on_beats_off_everywhere():
    off = [-0.2] * 200
    on = [-0.1] * 100
    m = _g(off, on)
    assert m["verdict"] == "pass" and m["conditions"]["ex_worst_on_gt_off"]


def test_fail_when_on_net_is_not_higher():
    # control: the same per-trade loss over fewer trades is a HIGHER net R, so it passes
    assert _g([-0.1] * 200, [-0.1] * 100)["verdict"] == "pass"
    m = _g([0.1] * 200, [0.05] * 100)                  # OFF +20, ON +5: ON is not higher
    assert m["verdict"] == "fail" and not m["conditions"]["net_on_gt_off"]


def test_fail_when_mean_is_worse_than_tolerance():
    # control: ON mean +0.15 vs OFF +0.125 clears the mean clause
    off = [-1.0] * 50 + [0.5] * 150                   # net +25, mean +0.125
    on = [-0.9] * 100 + [1.2] * 100                   # net +30, mean +0.15
    assert _g(off, on)["conditions"]["mean_not_worse_than_tol"]
    off2 = [0.9] * 200                                # net +180, mean +0.9
    on2 = [0.3] * 800                                 # net +240 (higher), mean +0.3: worse than OFF by 0.6 > 0.3
    m = _g(off2, on2)
    assert m["conditions"]["net_on_gt_off"] and not m["conditions"]["mean_not_worse_than_tol"] and m["verdict"] == "fail"


def test_fail_when_pass_is_carried_by_one_outlier():
    """OFF has one huge loser; ON avoids it. Net ON > OFF, but with each arm's worst trade removed ON is NOT higher."""
    off = [0.05] * 199 + [-30.0]
    on = [0.02] * 120
    m = _g(off, on)
    assert m["conditions"]["net_on_gt_off"]
    assert m["net_r_off_ex_worst_trade"] > m["net_r_on_ex_worst_trade"]
    assert not m["conditions"]["ex_worst_on_gt_off"] and m["verdict"] == "fail"


def test_indeterminate_below_the_n_floor():
    m = _g([0.1] * 50, [0.2] * 50)
    assert m["verdict"] == "indeterminate" and "175" in m["note"]


def test_empty_arms_do_not_crash():
    m = _g([], [])
    assert m["verdict"] == "indeterminate" and m["folds"] == []


def test_fold_table_uses_the_same_edges_for_both_arms():
    off = _rows([1.0] * 12)
    on = _rows([2.0] * 6)                              # ON stops half way: it must not get its own (shorter) fold edges
    folds = h.fold_table(off, on, 6)
    assert [f["fold"] for f in folds] == [1, 2, 3, 4, 5, 6]
    assert abs(sum(f["off"] for f in folds) - 12.0) < 1e-6 and abs(sum(f["on"] for f in folds) - 12.0) < 1e-6
    assert folds[0]["on"] > 0 and folds[-1]["on"] == 0  # ON's trades all sit in the early folds of the pooled range


def test_read_trades_csv_and_jsonl(tmp_path):
    csvp = tmp_path / "t.csv"
    csvp.write_text("entry_time,exit_time,direction,net_r\n2025-01-01 00:00:00+00:00,2025-01-01 03:00:00+00:00,long,0.5\n", encoding="utf-8")
    jl = tmp_path / "t.jsonl"
    jl.write_text(json.dumps({"entry_time": "2025-01-01", "side": "short", "net_r": -1}) + "\n", encoding="utf-8")
    a, b = h.read_trades(csvp), h.read_trades(jl)
    assert a[0]["net_r"] == 0.5 and a[0]["direction"] == "long"
    assert b[0]["net_r"] == -1.0 and b[0]["direction"] == "short" and b[0]["exit_time"] == "2025-01-01"
