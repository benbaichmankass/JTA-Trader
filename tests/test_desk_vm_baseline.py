"""DESK-S3-VOL-MATCHED-BASELINE: the companions to the registered S3 (gross excess, ATR-decile-matched baseline)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from scripts.research import desk_edge_ceiling as ce  # noqa: E402
from scripts.research import desk_gen_replay_driver as d  # noqa: E402
from scripts.research import desk_vm_baseline as vm  # noqa: E402


def _population(seed=3, n_cut=1500, gross_sd=1.0, symbols=("AAA",)):
    """Per (cutoff, symbol): ATR% in 10 levels; cost_r = 2.0/atr; gross R is PURE NOISE (no timing anywhere)."""
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(n_cut):
        for s in symbols:
            atr = 1.0 + (c * 7 % 10)
            for side in ("long", "short"):
                gross = rng.normal(0, gross_sd)
                rows.append({"cutoff": c, "symbol": s, "side": side, "hold": 5, "fold": 2 + ((c // 10) % 2), "week": f"w{c // 30}",
                             "days": 0.01, "atr_pct": atr, "cost_r": 2.0 / atr, "net_r": gross - 2.0 / atr, "gross": gross})
    whole = float(np.mean([r["net_r"] for r in rows]))
    for r in rows:
        r["y"] = r["net_r"] - whole                     # the registered S3 label: net minus the unconditional random entry
    return rows


def _score(rows, picks):
    vm.annotate(rows, lambda r: r["atr_pct"])
    return vm.companions(rows, picks, d.cluster_stats)


def test_vol_rule_s3_is_large_under_the_old_baseline_and_vanishes_when_matched():
    rows = _population()
    # model-free vol rule: pick the highest-ATR% quartile
    picks = [j for j, r in enumerate(rows) if r["atr_pct"] >= 8.0]
    c = _score(rows, picks)
    assert c["S3"]["mean"] > 0.15 and c["S3"]["ci95"][0] > 0.10               # cost selection reads as timing
    assert c["S3_matched"]["ci95"][0] <= 0 <= c["S3_matched"]["ci95"][1]       # ...and is gone under the matched baseline
    assert c["gross_excess"]["ci95"][0] <= 0 <= c["gross_excess"]["ci95"][1]    # gross R has no timing either
    assert c["S3"]["n"] == c["S3_matched"]["n"] == len(picks)                   # population stated, identical


def test_planted_timing_oracle_keeps_a_positive_matched_s3():
    rows = _population()
    # oracle: within the same high-vol states, take only the actions whose gross R turns out positive
    picks = [j for j, r in enumerate(rows) if r["atr_pct"] >= 8.0 and r["gross"] > 0.5]
    c = _score(rows, picks)
    assert c["S3_matched"]["mean"] > 0.5 and c["S3_matched"]["ci95"][0] > 0.3
    assert c["gross_excess_matched"]["ci95"][0] > 0.3


def test_row_cells_never_span_symbols_or_folds_or_sides():
    rows = _population(symbols=("AAA", "BBB"))
    for r in rows:                                     # symbols and folds sit at very different levels at equal ATR%
        r["net_r"] += (5.0 if r["symbol"] == "BBB" else 0.0) + (3.0 if r["fold"] == 3 else 0.0) + (2.0 if r["side"] == "short" else 0.0)
    vm.annotate(rows, lambda r: r["atr_pct"])
    cells = {}
    for r in rows:
        cells.setdefault((r["symbol"], r["fold"], r["side"], r["vol_dec"]), []).append(r["y_vm"])
    assert len(cells) == 2 * 2 * 2 * 10
    assert all(abs(float(np.mean(v))) < 1e-9 for v in cells.values())           # each cell is centred on ITS OWN mean only


def test_ceiling_evaluate_carries_companions_when_rows_have_atr_pct():
    rows = _population()
    for r in rows:
        r["geom"] = "G1"
        r.pop("hold")
    pred = np.array([r["atr_pct"] for r in rows])
    out = ce.evaluate(rows, pred, 0.05)
    assert out["companions"]["S3_matched"]["n"] == out["n"] and "gross_excess" in out["companions"]
    assert out["paired_diff_vs_random"] == d.cluster_stats(ce.s_rows(rows, ce.policy_picks(rows, pred)))["paired_diff_vs_random"]
