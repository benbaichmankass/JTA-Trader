"""exit_lever_ablation.py --grade sweep_holdout (RESEARCH-UNBLOCK-BUILDS-W48): the sweep rule on the
discovery span, then ONE read of the selected candidate against the baseline on the held-back span.

Planted/clean pairs: a candidate that only wins on the held-back span is never selected (no_discovery);
a candidate that wins on discovery and holds confirms; one that wins on discovery and loses on the
held-back span is not_replicated; a thin held-back span is underpowered, never a fail; a planted
lookahead trade cannot reach selection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO / "scripts" / "ops"), str(REPO)]
import exit_lever_ablation as e  # noqa: E402

LO = pd.Timestamp("2022-01-01", tz="UTC")
HI = pd.Timestamp("2026-01-01", tz="UTC")
B = pd.Timestamp("2025-01-01", tz="UTC")
PLAN = {"boundary": B, "share": 0.25, "baseline_n_holdout": 0, "grown": False, "short_at_cap": False}


def _book(start: str, end: str, net: float, every_days: int = 7) -> list[dict]:
    out = []
    for d in pd.date_range(start, end, freq=f"{every_days}D", inclusive="left"):
        out.append({"entry_time": f"{d.date()} 00:00:00+00:00", "exit_time": f"{d.date()} 12:00:00+00:00",
                    "net_r": net})
    return out


def _grade(trades, **kw):
    args = dict(baseline="A", candidates=["C"], plan=PLAN, lo=LO, hi=HI, delta_r=4.0, fold_majority=3,
                n_floor=39, holdout_min_trades=25, control=None, same_as=None)
    args.update(kw)
    return e.grade_sweep_holdout(trades, **args)


def _a():   # baseline: +0.1 R a week everywhere (156 discovery trades, 52 held-back)
    return _book("2022-01-01", "2026-01-01", 0.1)


def test_wins_on_discovery_and_holds_confirms():
    g = _grade({"A": _a(), "C": _book("2022-01-01", "2026-01-01", 0.2)})
    assert g["verdict"] == "pass" and g["label"] == "confirmed" and g["selected"] == "C"
    assert g["evaluations_on_holdout"] == 1 and g["holdout_baseline"]["n"] >= 25
    assert g["holdout_delta"]["delta_net_r"] > 0


def test_wins_on_discovery_loses_on_holdout_is_not_replicated():
    c = _book("2022-01-01", "2025-01-01", 0.2) + _book("2025-01-01", "2026-01-01", -0.1)
    g = _grade({"A": _a(), "C": c})
    assert g["verdict"] == "fail" and g["label"] == "not_replicated" and g["selected"] == "C"


def test_a_candidate_that_only_wins_on_the_held_back_span_is_never_selected():
    c = _book("2022-01-01", "2025-01-01", 0.1) + _book("2025-01-01", "2026-01-01", 5.0)
    g = _grade({"A": _a(), "C": c})
    assert g["verdict"] == "fail" and g["label"] == "no_discovery" and g["selected"] is None
    assert g["holdout"] is None and g["evaluations_on_holdout"] == 0


def test_thin_held_back_span_is_underpowered_never_a_fail():
    a = _book("2022-01-01", "2025-01-01", 0.1) + _book("2025-01-01", "2026-01-01", 0.1, every_days=30)
    c = _book("2022-01-01", "2025-01-01", 0.2) + _book("2025-01-01", "2026-01-01", -1.0, every_days=30)
    g = _grade({"A": a, "C": c})
    assert g["verdict"] == "indeterminate" and g["label"] == "underpowered"


def test_thin_discovery_is_insufficient_discovery():
    g = _grade({"A": _a(), "C": _book("2022-01-01", "2026-01-01", 0.2)}, n_floor=500)
    assert g["verdict"] == "indeterminate" and g["label"] == "insufficient_discovery"


def test_failed_control_is_indeterminate():
    g = _grade({"A": _a(), "C": _book("2022-01-01", "2026-01-01", 0.2)}, control={"ok": False})
    assert g["verdict"] == "indeterminate" and g["label"] == "control_failed"


def test_straddling_trade_never_reaches_selection():
    c = _book("2022-01-01", "2026-01-01", 0.2)
    c.append({"entry_time": "2024-12-31 00:00:00+00:00", "exit_time": "2025-01-05 00:00:00+00:00", "net_r": 50.0})
    g = _grade({"A": _a(), "C": c})
    assert g["plan"]["straddling_excluded"]["C"] == 1
    # the +50 R straddler is in neither span: discovery delta is the clean +0.1 x 156
    assert g["discovery_grade"]["candidates"]["C"]["delta_net_r"] == pytest.approx(15.6, abs=0.2)


def test_holdout_confirmation_block_shape():
    g = _grade({"A": _a(), "C": _book("2022-01-01", "2026-01-01", 0.2)})
    blk = e.holdout_confirmation(g, fingerprint="fp", cost_stack={}, lo=LO, hi=HI, unit="RQ-X")
    assert blk["verdict"] == "confirmed" and blk["n_holdout"] == g["holdout"]["n"]
    assert blk["selected_label"] == "C" and blk["evaluations_on_holdout"] == 1


def test_span_max_dd_is_peak_to_trough_in_exit_order():
    tr = [{"entry_time": "2024-01-01", "exit_time": "2024-01-02", "net_r": 2.0},
          {"entry_time": "2024-01-03", "exit_time": "2024-01-04", "net_r": -3.0},
          {"entry_time": "2024-01-05", "exit_time": "2024-01-06", "net_r": 1.0}]
    assert e._span_max_dd(tr) == 3.0


def test_grade_is_registered_on_the_cli():
    assert "sweep_holdout" in e.GRADES
